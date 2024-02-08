import copy
import glob
import hashlib
import json
import logging
import logging.config
import os
import shlex
import shutil
import subprocess
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import Dict, List

import boto3
from botocore.exceptions import ClientError
from git import Repo

from job_creator.architectures import architecture_map, prod
from job_creator.ci_objects import Job, Workflow
from job_creator.job_templates import (bb5_download_sif_yaml,
                                       bbp_containerizer_include_yaml,
                                       build_custom_containers_yaml,
                                       build_spacktainer_yaml,
                                       buildah_build_yaml,
                                       buildah_include_yaml, create_sif_yaml,
                                       docker_hub_push_yaml, multiarch_yaml)
from job_creator.logging_config import LOGGING_CONFIG
from job_creator.spack_template import spack_template
from job_creator.utils import (docker_hub_login, docker_hub_repo_exists,
                               docker_hub_repo_tag_exists, load_yaml,
                               merge_dicts, write_yaml)

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("job_creator")


class ImageNotFoundError(Exception):
    pass


class BaseContainer:
    """
    Base class with common container functionality
    """

    def __init__(
        self,
        name,
        build_path,
        architectures="amd64",
        registry="bbpgitlab.epfl.ch:5050/hpc/spacktainerizah/",
    ):
        self.name = name
        self.job_name = f"build {self.name}"
        self.registry = registry
        self.registry_image = f"{os.environ.get('CI_REGISTRY_IMAGE')}/{build_path}"
        self.build_path = build_path

        if isinstance(architectures, str):
            self.architectures = [architectures]
        else:
            self.architectures = list(architectures)

        self.workflow = Workflow(**copy.deepcopy(buildah_include_yaml))

    @property
    def registry_image_tag(self) -> str:
        """
        The tag the container will have once created: at least the date,
        optionally followed by the branch name if not building on CI_DEFAULT_BRANCH
        """
        if os.environ.get("CI_COMMIT_BRANCH") == os.environ.get("CI_DEFAULT_BRANCH"):
            tag = "latest"
        else:
            tag = datetime.strftime(datetime.today(), "%Y.%m.%d")
            tag += f"-{os.environ.get('CI_COMMIT_BRANCH')}"

        return tag

    def generate(self, *args, **kwargs) -> Workflow:
        """
        The method which will generate a workflow to build this container
        """
        raise NotImplementedError("Children must implement this")

    def needs_build(self) -> bool:
        """
        Does the container need building?
        """
        raise NotImplementedError("Children must implement this")

    @cached_property
    def container_checksum(self) -> str:
        """
        Checksum calculated based on the files needed to build the container (e.g. Dockerfile)
        """
        return self._generate_container_checksum()

    def _generate_container_checksum(self) -> str:
        """
        Checksum calculated based on the files needed to build the container (e.g. Dockerfile)
        """
        checksums = []
        for filepath in sorted(glob.glob(f"{self.build_path}/*")):
            with open(filepath, "r") as fp:
                checksums.append(hashlib.sha256(fp.read().encode()).hexdigest())
        container_checksum = hashlib.sha256(":".join(checksums).encode()).hexdigest()
        return container_checksum

    def container_info(
        self,
        registry: str | None = None,
        registry_user: str | None = None,
        registry_password: str | None = None,
        registry_image: str | None = None,
    ) -> Dict:
        """
        Get the container info from the repository through `skopeo inspect`
        """
        registry = registry if registry else os.environ.get("CI_REGISTRY")
        registry_user = (
            registry_user if registry_user else os.environ.get("CI_REGISTRY_USER")
        )
        registry_password = (
            registry_password
            if registry_password
            else os.environ.get("CI_REGISTRY_PASSWORD")
        )
        registry_image = registry_image if registry_image else self.registry_image
        skopeo_login_cmd = [
            "skopeo",
            "login",
            "-u",
            registry_user,
            "-p",
            registry_password,
            registry,
        ]
        logger.debug(f"Running `{skopeo_login_cmd}`")
        subprocess.run(skopeo_login_cmd)

        for architecture in self.architectures:
            skopeo_inspect_cmd = [
                "skopeo",
                "inspect",
                f"--override-arch={architecture}",
                f"docker://{registry_image}:{self.registry_image_tag}",
            ]
            logger.debug(f"Running `{skopeo_inspect_cmd}`")
            result = subprocess.run(skopeo_inspect_cmd, capture_output=True)

            if result.returncode != 0:
                raise ImageNotFoundError(
                    f"Image {self.name}:{self.registry_image_tag} not found in {registry}"
                )
            info = json.loads(result.stdout)

            # if the override-arch is not found, skopeo just returns whatever other arch
            # is available without complaining. Thanks, skopeo!
            if info["Architecture"] != architecture:
                raise ImageNotFoundError(
                    f"Image {self.name}:{self.registry_image_tag} with architecture {architecture} not found in {registry}"
                )

        return info

    def compose_workflow(self) -> None:
        """
        Append architecture to the REGISTRY_IMAGE_TAG if necessary
        and create multiarch job if necessary
        """
        if len(self.architectures) > 1:
            for job in self.workflow.jobs:
                job.variables[
                    "REGISTRY_IMAGE_TAG"
                ] = f"{job.variables['REGISTRY_IMAGE_TAG']}-{job.architecture}"

        self.create_multiarch_job()

    def create_multiarch_job(self) -> None:
        """
        If the container is being built for multiple architectures, create a multiarch job
        """
        if len(self.architectures) > 1:
            multiarch_job_name = f"create multiarch for {self.name}"
            multiarch_job = Job(multiarch_job_name, **copy.deepcopy(multiarch_yaml))
            multiarch_job.needs = [job.name for job in self.workflow.jobs]
            logger.debug("Replace placeholders in multiarch job script")
            for idx, line in enumerate(multiarch_job.script):
                multiarch_job.script[idx] = line.replace(
                    "%REGISTRY_IMAGE%", self.registry_image
                ).replace("%REGISTRY_IMAGE_TAG%", self.registry_image_tag)

            self.workflow.add_job(multiarch_job)

    def get_s3_connection(self, bucket: Dict) -> boto3.client:
        if keypair_variables := bucket.get("keypair_variables"):
            os.environ["AWS_ACCESS_KEY_ID"] = os.environ[
                keypair_variables["access_key"]
            ]
            os.environ["AWS_SECRET_ACCESS_KEY"] = os.environ[
                keypair_variables["secret_key"]
            ]

        s3 = boto3.client("s3")

        return s3


class Spacktainerizer(BaseContainer):
    """
    Base class for the runtime and builder containers that contain our Spack fork
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.spack_branch = os.environ.get("SPACK_BRANCH", "develop")

    @cached_property
    def spack_commit(self) -> str:
        """
        Get the latest spack commit
        """
        logger.debug(f"Cloning spack for {self.name} {self.spack_branch}")
        spack_clone_dir = "spack"
        if os.path.exists(spack_clone_dir):
            shutil.rmtree(spack_clone_dir)
        spack = Repo.clone_from(
            "https://github.com/bluebrain/spack",
            to_path=spack_clone_dir,
            multi_options=[f"-b {self.spack_branch}", "--depth=1"],
        )
        return spack.head.commit.hexsha

    def needs_build(self) -> bool:
        """
        Check whether the container needs building:
          * Does the container exist?
          * Have any of the files needed for it (e.g. Dockerfile) changed?
          * Was the existing container built with the most recent spack commit?
        """

        logger.info(f"Checking whether we need to build {self.name}")
        try:
            container_info = self.container_info()
            existing_spack_commit = container_info["Labels"][
                "ch.epfl.bbpgitlab.spack_commit"
            ]
            existing_container_checksum = container_info["Labels"][
                "ch.epfl.bbpgitlab.container_checksum"
            ]
        except ImageNotFoundError as ex:
            logger.info(ex)
            logger.info(f"We'll have to build {self.name}")
            return True
        logger.debug("Image found!")

        logger.debug(f"Existing container checksum: {existing_container_checksum}")
        logger.debug(f"My container checksum: {self.container_checksum}")
        logger.debug(f"Existing spack commit: {existing_spack_commit}")
        logger.debug(f"My spack commit: {self.spack_commit}")
        if (
            existing_container_checksum == self.container_checksum
            and existing_spack_commit == self.spack_commit
        ):
            logger.info(f"No need to build {self.name}")
            return False

        logger.info(f"We'll have to build {self.name}")
        return True

    def generate(self, *args, **kwargs) -> Workflow:
        """
        Generate the workflow that will build this container, if necessary
        """
        if not self.needs_build():
            return Workflow()

        buildah_extra_args = [
            f"--build-arg SPACK_BRANCH={self.spack_branch}",
            f'--label org.opencontainers.image.title="{self.name}"',
            f'--label org.opencontainers.image.version="{self.registry_image_tag}"',
            f'--label ch.epfl.bbpgitlab.spack_commit="{self.spack_commit}"',
            f'--label ch.epfl.bbpgitlab.container_checksum="{self.container_checksum}"',
        ]

        for architecture in self.architectures:
            arch_job = Job(
                self.job_name, architecture, **copy.deepcopy(buildah_build_yaml)
            )
            arch_job.variables["CI_REGISTRY_IMAGE"] = self.registry_image
            arch_job.variables["REGISTRY_IMAGE_TAG"] = self.registry_image_tag
            arch_job.variables[
                "BUILDAH_EXTRA_ARGS"
            ] += f" {' '.join(buildah_extra_args)}"
            arch_job.variables["BUILD_PATH"] = self.build_path
            cache_bucket = architecture_map[architecture]["cache_bucket"]
            arch_job.variables[
                "BUILDAH_EXTRA_ARGS"
            ] += f' --build-arg CACHE_BUCKET="s3://{cache_bucket["name"]}"'
            if endpoint_url := architecture_map[architecture]["cache_bucket"].get(
                "endpoint_url"
            ):
                arch_job.variables[
                    "BUILDAH_EXTRA_ARGS"
                ] += f' --build-arg MIRROR_URL="{endpoint_url}"'

            arch_job.update_before_script(
                ['cp "$SPACK_DEPLOYMENT_KEY_PUBLIC" "$CI_PROJECT_DIR/builder/key.pub"'],
                append=True,
            )
            self.workflow.add_job(arch_job)

        self.compose_workflow()

        return self.workflow


class Singularitah(BaseContainer):
    """
    A container containing singularity and s3cmd
    """

    def __init__(self, singularity_version, s3cmd_version, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.singularity_version = singularity_version
        self.s3cmd_version = s3cmd_version

    def needs_build(self) -> bool:
        """
        Check whether the container needs building:
          * Does it exist?
          * Does it have the correct s3cmd and singularity versions?
          * Has the Dockerfile or any of the related files changed?
        """
        logger.info(f"Checking whether we need to build {self.name}")
        try:
            container_info = self.container_info()
            existing_singularity_version = container_info["Labels"][
                "ch.epfl.bbpgitlab.singularity_version"
            ]
            existing_s3cmd_version = container_info["Labels"][
                "ch.epfl.bbpgitlab.s3cmd_version"
            ]
            existing_container_checksum = container_info["Labels"][
                "ch.epfl.bbpgitlab.container_checksum"
            ]
        except ImageNotFoundError as ex:
            logger.info(ex)
            logger.info(f"We'll have to build {self.name}")
            return True
        logger.debug(f"Image {self.name} found")

        if (
            existing_container_checksum == self.container_checksum
            and existing_s3cmd_version == self.s3cmd_version
            and existing_singularity_version == self.singularity_version
        ):
            logger.info(f"No need to build {self.name}")
            return False

        logger.info(f"We'll have to build {self.name}")
        return True

    def generate(self, *args, **kwargs) -> Workflow:
        """
        Generate the workflow that will build this container, if necessary
        """
        if not self.needs_build():
            return Workflow()

        buildah_extra_args = [
            f'--label org.opencontainers.image.title="{self.name}"',
            f'--label org.opencontainers.image.version="{self.registry_image_tag}"',
            f'--label ch.epfl.bbpgitlab.singularity_version="{self.singularity_version}"',
            f'--label ch.epfl.bbpgitlab.s3cmd_version="{self.s3cmd_version}"',
            f'--label ch.epfl.bbpgitlab.container_checksum="{self.container_checksum}"',
            f'--build-arg SINGULARITY_VERSION="{self.singularity_version}"',
            f'--build-arg S3CMD_VERSION="{self.s3cmd_version}"',
        ]
        for architecture in self.architectures:
            build_job = Job(
                self.job_name,
                architecture=architecture,
                **copy.deepcopy(buildah_build_yaml),
            )
            build_job.variables["CI_REGISTRY_IMAGE"] = self.registry_image
            build_job.variables["REGISTRY_IMAGE_TAG"] = self.registry_image_tag
            build_job.variables[
                "BUILDAH_EXTRA_ARGS"
            ] += f" {' '.join(buildah_extra_args)}"
            build_job.variables["BUILD_PATH"] = self.build_path

            self.workflow.add_job(build_job)
        self.compose_workflow()

        return self.workflow


class Spackah(BaseContainer):
    """
    A container built based on one or more Spack specs.
    """

    def __init__(
        self,
        name,
        architecture,
        out_dir,
        registry="bbpgitlab.epfl.ch:5050/hpc/spacktainerizah/",
    ):
        self.name = name
        self.architectures = [architecture]
        self.architecture = architecture
        self.registry = registry
        self.registry_image = f"{os.environ.get('CI_REGISTRY_IMAGE')}/{name}"
        self.container_definition_file = (
            f"container_definitions/{self.architecture}/{self.name}.yaml"
        )
        self.spacktainer_yaml = load_yaml(self.container_definition_file)
        self.container_yaml = {"spack": self.spacktainer_yaml.pop("spack")}
        self.hub_namespace = "bluebrain"
        self.hub_repo = f"spackah-{self.name}"

        includes = merge_dicts(
            copy.deepcopy(buildah_include_yaml),
            copy.deepcopy(bbp_containerizer_include_yaml),
        )
        self.workflow = Workflow(**includes)

        self.spack_env_dir = out_dir / self.architecture / self.name
        self.spack_env_dir.mkdir(parents=True, exist_ok=True)

        self._generate_spack_yaml()
        self.concretize_spec()

    def concretize_spec(self) -> None:
        """
        Concretize the full container spec with Spack
        Will set the spack_lock property
        """
        spack_root = os.environ["SPACK_ROOT"]
        spack_cmd = shlex.split(
            f"bash -c 'source {spack_root}/share/spack/setup-env.sh && "
            f"spack env activate {self.spack_env_dir} && spack concretize -f'",
        )
        result = subprocess.run(spack_cmd)
        if result.returncode != 0:
            stdout = result.stdout.decode() if result.stdout else ""
            stderr = result.stderr.decode() if result.stderr else ""
            raise RuntimeError(
                f"Failed to concretize spec for {self.name}:\n{stdout}\n{stderr}"
            )

        self.spack_lock = self.spack_env_dir / "spack.lock"

    def _generate_container_checksum(self) -> str:
        """
        Calculate the checksum of the container definition file
        """
        with open(
            f"container_definitions/{self.architecture}/{self.name}.yaml", "r"
        ) as fp:
            container_checksum = hashlib.sha256(fp.read().encode()).hexdigest()

        return container_checksum

    def _generate_spack_yaml(self) -> None:
        """
        Merges the container definition with the Spack yaml template
        """
        spack_yaml = copy.deepcopy(spack_template)
        merge_dicts(spack_yaml, self.container_yaml)
        write_yaml(spack_yaml, self.spack_env_dir / "spack.yaml")

    def get_main_package(self) -> str:
        """
        Determine the main package for this container (first in the spec list)
        """
        main_spec = self.container_yaml["spack"]["specs"][0]
        main_package = main_spec.split("~")[0].split("+")[0].strip()
        return main_package

    def get_package_version(self, package_name: str) -> str:
        """
        Get the version of a package present in the spack lockfile
        """
        with open(self.spack_lock, "r") as fp:
            spack_lock = json.load(fp)

        logger.debug(f"Looking for package {package_name}")
        logger.debug(f"Roots: {spack_lock['roots']}")
        spack_hash = next(
            root
            for root in spack_lock["roots"]
            if root["spec"].split("~")[0].split("+")[0] == package_name
        )["hash"]
        package_version = spack_lock["concrete_specs"][spack_hash]["version"]

        return package_version

    @property
    def registry_image_tag(self) -> str:
        """
        The tag the container will have once created
        main package version followed by architecture,
        if not building on main also insert the CI_COMMIT_REF_SLUG
        """
        main_package_version = self.get_package_version(self.get_main_package())
        if prod:
            tag = f"{main_package_version}"
        else:
            ci_commit_ref_slug = os.environ.get("CI_COMMIT_REF_SLUG")
            tag = f"{main_package_version}__{ci_commit_ref_slug}"

        return tag

    def _create_build_job(self, builder_image_tag: str) -> Job:
        """
        Create the job that will build the container image
        """
        build_job = Job(
            f"build {self.name} container",
            architecture=self.architecture,
            needs=[
                {
                    "pipeline": os.environ.get("CI_PIPELINE_ID"),
                    "job": f"generate spacktainer jobs for {self.architecture}",
                    "artifacts": True,
                },
            ],
            **copy.deepcopy(build_spacktainer_yaml),
        )

        buildah_extra_args = [
            f"--label org.opencontainers.image.title={self.name}",
            f"--label org.opencontainers.image.version={self.registry_image_tag}",
            f"--label ch.epfl.bbpgitlab.spack_lock_sha256={self.spack_lock_checksum}",
            f"--label ch.epfl.bbpgitlab.container_checksum={self.container_checksum}",
        ]

        build_path = "spacktainer"

        build_job.variables["CI_REGISTRY_IMAGE"] = self.registry_image
        build_job.variables["REGISTRY_IMAGE_TAG"] = self.registry_image_tag
        build_job.variables["SPACK_ENV_DIR"] = str(self.spack_env_dir)
        build_job.variables["ARCH"] = self.architecture
        build_job.variables["BUILD_PATH"] = build_path
        build_job.variables["BUILDAH_EXTRA_ARGS"] += f" {' '.join(buildah_extra_args)}"

        dockerfile = Path(f"{build_path}/Dockerfile")
        dockerfile_lines = [
            f"FROM bbpgitlab.epfl.ch:5050/hpc/spacktainerizah/builder:{builder_image_tag} AS builder",
            f"FROM bbpgitlab.epfl.ch:5050/hpc/spacktainerizah/runtime:{builder_image_tag}",
            "# Triggers building the 'builder' image, otherwise it is optimized away",
            "COPY --from=builder /etc/debian_version /etc/debian_version",
        ]

        if self.spacktainer_yaml:
            for filepair in self.spacktainer_yaml["spacktainer"].get("files"):
                source, target = filepair.split(":")
                dockerfile_lines.append(f'"COPY {source} {target}"')

        build_job.update_before_script(
            f"mkdir -p {dockerfile.parent}",
        )
        build_job.update_before_script(
            [f"echo {line} >> {dockerfile}" for line in dockerfile_lines], append=True
        )
        build_job.artifacts = {
            "when": "always",
            "paths": ["spacktainer/Dockerfile"],
        }

        return build_job

    def _create_sif_job(self, build_job: Job | None, singularity_image_tag: str) -> Job:
        """
        Create the job that will build and upload the SIF image
        """
        create_sif_job = Job(
            f"create {self.name} sif file",
            architecture=self.architecture,
            bucket="infra",
            **copy.deepcopy(create_sif_yaml),
        )
        if build_job:
            create_sif_job.needs.append(build_job.name)

        bucket = architecture_map[self.architecture]["containers_bucket"]
        fs_container_path = f"/tmp/{self.container_filename}"

        create_sif_job.variables["CI_REGISTRY_IMAGE"] = self.registry_image
        create_sif_job.variables["REGISTRY_IMAGE_TAG"] = self.registry_image_tag
        create_sif_job.variables["FS_CONTAINER_PATH"] = fs_container_path
        create_sif_job.variables["CONTAINER_NAME"] = self.name
        create_sif_job.variables["SPACK_LOCK_SHA256"] = self.spack_lock_checksum
        create_sif_job.variables["CONTAINER_CHECKSUM"] = self.container_checksum
        create_sif_job.variables["BUCKET"] = bucket["name"]
        create_sif_job.variables[
            "S3_CONTAINER_PATH"
        ] = f"s3://{bucket['name']}/containers/spacktainerizah/{self.container_filename}"

        create_sif_job.image = f"bbpgitlab.epfl.ch:5050/hpc/spacktainerizah/singularitah:{singularity_image_tag}"
        create_sif_job.configure_s3cmd()

        return create_sif_job

    def _create_docker_hub_push_job(self, build_job: Job | None) -> Job:
        """
        Create the job that will push the container image to docker hub
        """
        job = Job(
            f"push {self.name}:{self.registry_image_tag} to docker hub",
            **copy.deepcopy(docker_hub_push_yaml),
        )
        job.variables["CONTAINER_NAME"] = self.name
        job.variables["REGISTRY_IMAGE_TAG"] = self.registry_image_tag
        job.variables["HUB_REPO_NAMESPACE"] = self.hub_namespace
        job.variables["HUB_REPO_NAME"] = self.hub_repo
        if build_job:
            job.needs.append(build_job.name)

        return job

    def _create_bb5_download_sif_job(
        self, create_sif_job: Job | None, s3cmd_version: str
    ):
        job = Job(
            f"download {self.name} SIF to bb5", **copy.deepcopy(bb5_download_sif_yaml)
        )
        sif_root = Path("/gpfs/bbp.cscs.ch/ssd/containers/hpc/spacktainerizah")
        sif_file = sif_root / self.container_filename
        job.variables["BUCKET"] = architecture_map[self.architecture][
            "containers_bucket"
        ]["name"]
        job.variables["SIF_FILENAME"] = self.container_filename
        job.variables["FULL_SIF_PATH"] = str(sif_file)
        job.variables["SPACK_LOCK_CHECKSUM"] = self.spack_lock_checksum
        job.variables["CONTAINER_CHECKSUM"] = self.container_checksum
        job.variables["S3CMD_VERSION"] = s3cmd_version
        if create_sif_job:
            job.needs.append(create_sif_job.name)
        return job

    def generate(
        self, builder_image_tag: str, singularity_image_tag: str, s3cmd_version: str
    ) -> Workflow:
        """
        Generate the workflow that will build this container, if necessary
        """

        build_job = None
        create_sif_job = None

        if self.needs_build():
            build_job = self._create_build_job(builder_image_tag)
            self.workflow.add_job(build_job)

        if self.needs_sif_upload():
            create_sif_job = self._create_sif_job(build_job, singularity_image_tag)
            self.workflow.add_job(create_sif_job)

        if self.architecture == "amd64":
            logger.info("We want the amd64 containers on bb5")
            bb5_download_sif_job = self._create_bb5_download_sif_job(
                create_sif_job, s3cmd_version
            )
            self.workflow.add_job(bb5_download_sif_job)

        if self.needs_docker_hub_push():
            docker_hub_push_job = self._create_docker_hub_push_job(build_job)
            self.workflow.add_job(docker_hub_push_job)

        logger.info(f"Workflow stages for {self.name}: {self.workflow.stages}")
        return self.workflow

    @cached_property
    def spack_lock_checksum(self) -> str:
        """
        Calculate the sha256sum of the spack.lock file for this container
        """
        with open(self.spack_lock, "r") as fp:
            checksum = hashlib.sha256(fp.read().encode()).hexdigest()

        return checksum

    @property
    def container_filename(self) -> str:
        """
        SIF filename for the container in the S3 bucket
        """
        return f"{self.name}__{self.registry_image_tag}.sif"

    def needs_docker_hub_push(self) -> bool:
        """
        Check whether the container needs to be pushed to Docker Hub
        * repository exists
        * tag not present
        * checksums mismatch
        """
        if os.environ.get("CI_COMMIT_BRANCH") != os.environ.get("CI_DEFAULT_BRANCH"):
            logger.info("Not on default branch, no need to push to docker hub")
            return False

        docker_hub_user = os.environ["DOCKERHUB_USER"]
        docker_hub_auth_token = os.environ["DOCKERHUB_PASSWORD"]
        dh = docker_hub_login(docker_hub_user, docker_hub_auth_token)
        if not docker_hub_repo_exists(dh, self.hub_namespace, self.hub_repo):
            logger.info(
                f"Docker Hub repository {self.hub_namespace}/{self.hub_repo} does not exist - no need to push"
            )
            return False
        if not docker_hub_repo_tag_exists(
            dh, self.hub_namespace, self.hub_repo, self.registry_image_tag
        ):
            logger.info(
                f"Tag {self.registry_image_tag} does not exist in Docker Hub repo {self.hub_namespace}/{self.hub_repo} - we'll have to push"
            )
            return True

        container_info = self.container_info(
            "hub.docker.com",
            docker_hub_user,
            docker_hub_auth_token,
            f"{self.hub_namespace}/{self.hub_repo}",
        )
        repo_spack_lock_checksum = container_info["Labels"][
            "ch.epfl.bbpgitlab.spack_lock_sha256"
        ]
        repo_container_checksum = container_info["Labels"][
            "ch.epfl.bbpgitlab.container_checksum"
        ]

        logger.debug(f"existing spack.lock checksum: {existing_spack_lock_checksum}")
        logger.debug(f"my spack.lock checksum: {self.spack_lock_checksum}")

        logger.debug(f"existing container checksum: {repo_container_checksum}")
        logger.debug(f"my container checksum: {self.container_checksum}")

        if (
            existing_container_checksum == self.container_checksum
            and existing_spack_lock_checksum == self.spack_lock_checksum
        ):
            logger.info(
                f"No need to push {self.name}:{self.registry_image_tag} to docker hub"
            )
            return False

        logger.info(
            f"We'll have to push {self.name}:{self.registry_image_tag} to docker hub"
        )
        return True

    def needs_sif_upload(self) -> bool:
        """
        Check whether the container needs to be uploaded as a SIF file
        """
        bucket = architecture_map[self.architecture]["containers_bucket"]
        s3 = self.get_s3_connection(bucket)
        try:
            object_info = s3.head_object(
                Bucket=bucket["name"],
                Key=f"containers/spacktainerizah/{self.container_filename}",
            )
            bucket_container_checksum = object_info["ResponseMetadata"][
                "HTTPHeaders"
            ].get("x-amz-meta-container-checksum", "container checksum not set")
            bucket_spack_sha256 = object_info["ResponseMetadata"]["HTTPHeaders"].get(
                "x-amz-meta-spack-lock-sha256", "container spack lock sha256 not set"
            )
        except ClientError:
            logger.debug(f"No SIF file found for {self.name}")
            return True

        if (
            bucket_container_checksum != self.container_checksum
            or bucket_spack_sha256 != self.spack_lock_checksum
        ):
            logger.debug(
                f"Rebuild SIF for checksum mismatch: {bucket_container_checksum}/{self.container_checksum} or {bucket_spack_sha256}/{self.spack_lock_checksum}"
            )
            return True

        return False

    def needs_build(self) -> bool:
        """
        Check whether the container needs building:
        * Check whether the container exists
        * Check its container_checksum
        * Check its spack_sha265
        """
        try:
            container_info = self.container_info()
            existing_container_checksum = container_info["Labels"][
                "ch.epfl.bbpgitlab.container_checksum"
            ]
            existing_spack_lock_checksum = container_info["Labels"][
                "ch.epfl.bbpgitlab.spack_lock_sha256"
            ]
        except ImageNotFoundError as ex:
            logger.info(ex)
            logger.info(f"Image not found - we'll have to build {self.name}")
            return True

        logger.debug(f"existing spack.lock checksum: {existing_spack_lock_checksum}")
        logger.debug(f"my spack.lock checksum: {self.spack_lock_checksum}")

        if (
            existing_container_checksum == self.container_checksum
            and existing_spack_lock_checksum == self.spack_lock_checksum
        ):
            logger.info(f"No need to build {self.name}")
            return False

        logger.info(f"We'll have to build {self.name}")
        return True

    def compose_workflow(self):
        raise NotImplementedError("Not applicable for Spackah containers")

    def create_multiarch_job(self):
        raise NotImplementedError("Not applicable for Spackah containers")


class CustomContainer(BaseContainer):
    """
    Custom containers are containers which are not built by us, but which already exist on
    docker hub. Write a singularity definition file and place it under the desired architecture,
    giving it the name you want your container to have.
    """

    def __init__(
        self,
        name,
        architecture,
    ):
        self.name = name
        self.architecture = architecture
        self.architectures = [self.architecture]

    @cached_property
    def definition(self) -> List[str]:
        """
        Read the definition file and return the content as a list of lines
        """
        with open(
            f"container_definitions/{self.architecture}/{self.name}.def", "r"
        ) as fp:
            return fp.readlines()

    def get_source(self) -> tuple[str, str]:
        """
        Read the definition file and return the image and tag of the source container image
        """
        from_line = next(
            line for line in self.definition if line.lower().startswith("from:")
        )
        _, image, tag = [x.strip() for x in from_line.split(":")]

        return image, tag

    @property
    def registry_image_tag(self) -> str:
        """
        Determine the tag the container will have in the registry
        In this case, it is taken straight from the source container
        """
        _, version = self.get_source()
        if prod:
            tag = f"{version}__{self.architecture}"
        else:
            ci_commit_ref_slug = os.environ.get("CI_COMMIT_REF_SLUG")
            tag = f"{version}__{ci_commit_ref_slug}__{self.architecture}"

        return tag

    @cached_property
    def source_container_checksum(self) -> str:
        return self.read_source_container_checksum()

    def read_source_container_checksum(self) -> str:
        """
        Inspect the container we're converting to SIF and get its checksum
        """
        source_image, source_version = self.get_source()
        skopeo_inspect_cmd = [
            "skopeo",
            "inspect",
            f"--override-arch={self.architecture}",
            f"docker://{source_image}:{source_version}",
        ]
        logger.debug(f"Running `{skopeo_inspect_cmd}`")
        result = subprocess.run(skopeo_inspect_cmd, capture_output=True)

        if result.returncode != 0:
            raise ImageNotFoundError(
                f"Issue with skopeo command: {result.stderr.decode()}"
            )
        info = json.loads(result.stdout)
        container_checksum = info["Digest"].split(":")[-1]
        return container_checksum

    @property
    def container_filename(self) -> str:
        """
        SIF filename for the container in the S3 bucket
        """
        return f"{self.name}__{self.registry_image_tag}.sif"

    def needs_build(self) -> bool:
        """
        Check whether the container needs building:
        1. Does the container exist in the bucket?
        2. Compare digest from source with bucket container

        # TODO if necessary, this can probably be refined to a per-job level
               instead of the whole chain
        """
        bucket = architecture_map[self.architecture]["containers_bucket"]
        s3 = self.get_s3_connection(bucket)
        try:
            object_info = s3.head_object(
                Bucket=bucket["name"],
                Key=f"containers/spacktainerizah/{self.container_filename}",
            )
            bucket_checksum = object_info["ResponseMetadata"]["HTTPHeaders"][
                "x-amz-meta-digest"
            ]
            if bucket_checksum != self.source_container_checksum:
                logger.debug(
                    f"{self.name}: local: {self.source_container_checksum}, bucket: {bucket_checksum}"
                )
                return True
        except ClientError:
            logger.debug(f"No container found for {self.name}")
            return True

        return False

    def generate(self, singularity_image_tag: str) -> Workflow:
        """
        Generate the workflow that will build this container, if necessary
        """
        workflow = Workflow()
        if self.needs_build():
            build_job = Job(
                f"build sif file for {self.name}",
                force_needs=True,
                architecture=self.architecture,
                bucket="infra",
                **copy.deepcopy(build_custom_containers_yaml),
            )

            bucket_name = architecture_map[self.architecture]["containers_bucket"][
                "name"
            ]
            build_job.variables["CONTAINER_FILENAME"] = self.container_filename
            build_job.variables[
                "CONTAINER_DEFINITION"
            ] = f"container_definitions/{self.architecture}/{self.name}.def"
            build_job.variables["SOURCE_DIGEST"] = self.source_container_checksum
            build_job.variables[
                "S3_CONTAINER_PATH"
            ] = f"s3://{bucket_name}/containers/spacktainerizah/{self.container_filename}"
            build_job.configure_s3cmd()
            build_job.image = f"bbpgitlab.epfl.ch:5050/hpc/spacktainerizah/singularitah:{singularity_image_tag}"

            workflow.add_job(build_job)

        return workflow


def generate_base_container_workflow(
    singularity_version: str, s3cmd_version: str, architectures: List[str]
) -> Workflow:
    """
    Generate the workflow that will build the base containers (builder, runtime, singularitah)

    :param singularity_version: which version of singularity to install in the singularitah container
    :param s3cmd_version: which version of s3cmd to install in the singularitah container
    :param architectures: which architectures to build for ([amd64, arm64])
    """
    logger.info("Generating base container jobs")
    singularitah = Singularitah(
        name="singularitah",
        singularity_version=singularity_version,
        s3cmd_version=s3cmd_version,
        build_path="singularitah",
        architectures=architectures,
    )
    builder = Spacktainerizer(
        name="builder", build_path="builder", architectures=architectures
    )
    runtime = Spacktainerizer(
        name="runtime", build_path="runtime", architectures=architectures
    )
    workflow = singularitah.generate()
    workflow += builder.generate()
    workflow += runtime.generate()

    return workflow


def generate_spack_containers_workflow(
    architecture: str, out_dir: Path, s3cmd_version: str
) -> Workflow:
    """
    Generate the workflow that will build the actual spack-based containers

    :param architecture: which architecture to generate the workflow for (amd64, arm64)
    :param out_dir: which directory to put the output into
    """
    workflow = Workflow()
    builder = Spacktainerizer(
        name="builder", build_path="builder", architectures=[architecture]
    )
    for container_path in glob.glob(f"container_definitions/{architecture}/*yaml"):
        container_name = os.path.splitext(os.path.basename(container_path))[0]
        logger.info(
            f"Generating workflow for container {container_name} on {architecture}"
        )

        singularitah = Singularitah(
            name="singularitah",
            singularity_version="",
            s3cmd_version="",
            build_path="singularitah",
            architectures=[architecture],
        )
        logger.info(f"Generating job for {container_name}")
        container = Spackah(
            name=container_name, architecture=architecture, out_dir=out_dir
        )
        container_workflow = container.generate(
            builder.registry_image_tag, singularitah.registry_image_tag, s3cmd_version
        )
        logger.debug(
            f"Container {container_name} workflow jobs are {container_workflow.jobs}"
        )
        workflow += container_workflow

    for custom_container_path in glob.glob(
        f"container_definitions/{architecture}/*def"
    ):
        custom_container_name = os.path.splitext(
            os.path.basename(custom_container_path)
        )[0]
        logger.info(
            f"Generating workflow for custom container {custom_container_name} on {architecture}"
        )
        custom = CustomContainer(custom_container_name, architecture)
        custom_workflow = custom.generate(singularitah.registry_image_tag)
        logger.debug(
            f"Container {custom_container_name} workflow jobs are {custom_workflow.jobs}"
        )
        workflow += custom_workflow

    logger.debug(f"Workflow jobs are {workflow.jobs}")
    if not workflow.jobs:
        workflow.add_job(
            Job(
                name="No containers to rebuild",
                script="echo No containers to rebuild",
            )
        )
    return workflow
