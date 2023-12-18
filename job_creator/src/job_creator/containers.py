import copy
import glob
import hashlib
import json
import logging
import logging.config
import os
import shutil
import subprocess
from datetime import datetime
from functools import cached_property

from git import Repo

from job_creator.job_templates import buildah_yaml, multiarch_yaml
from job_creator.logging_config import LOGGING_CONFIG

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("job_creator")


architecture_map = {
    "amd64": {
        "tag": "kubernetes",
        "proxy": True,
        "cache_bucket": "spack-build-cache",
        "mirror_url": "https://bbpobjectstorage.epfl.ch",
    },
    "arm64": {
        "tag": "aws_graviton",
        "proxy": False,
        "cache_bucket": "spack-cache-xlme2pbun4",
    },
}


class ImageNotFoundError(Exception):
    pass


class BaseContainer:
    def __init__(
        self,
        name,
        build_path,
        architectures="amd64",
        registry="bbpgitlab.epfl.ch:5050/hpc/spacktainerizah/",
    ):
        self.name = name
        self.registry = registry
        self.registry_image = f"{os.environ.get('CI_REGISTRY_IMAGE')}/{build_path}"
        self._container_checksum = None
        self.build_path = build_path

        if isinstance(architectures, str):
            self.architectures = [architectures]
        else:
            self.architectures = list(architectures)

        self.architecture_jobs = {
            architecture: f"build {self.name} for {architecture}"
            for architecture in self.architectures
        }

        self.registry_image_tag = datetime.strftime(datetime.today(), "%Y.%m.%d")
        if os.environ.get("CI_COMMIT_BRANCH") != os.environ.get("CI_DEFAULT_BRANCH"):
            self.registry_image_tag += f"-{os.environ.get('CI_COMMIT_BRANCH')}"

        self.multiarch_job = {}
        self.build_workflow = copy.deepcopy(buildah_yaml)
        self.build_workflow["build"]["variables"][
            "REGISTRY_IMAGE_TAG"
        ] = self.registry_image_tag
        self.workflow = {}

    def needs_build(self):
        raise NotImplementedError("Children must implement this")

    @cached_property
    def container_checksum(self):
        return self._generate_container_checksum()

    def _generate_container_checksum(self):
        checksums = []
        for filepath in sorted(glob.glob(f"{self.build_path}/*")):
            with open(filepath, "r") as fp:
                checksums.append(hashlib.sha256(fp.read().encode()).hexdigest())
        container_checksum = hashlib.sha256(":".join(checksums).encode()).hexdigest()
        return container_checksum

    def inspect_image(self):
        ci_registry = os.environ.get("CI_REGISTRY")
        skopeo_login_cmd = [
            "skopeo",
            "login",
            "-u",
            os.environ.get("CI_REGISTRY_USER"),
            "-p",
            os.environ.get("CI_REGISTRY_PASSWORD"),
            os.environ.get("CI_REGISTRY"),
        ]
        skopeo_inspect_cmd = [
            "skopeo",
            "inspect",
            f"docker://{self.registry_image}:{self.registry_image_tag}",
        ]
        logger.debug(f"Running `{skopeo_login_cmd}`")
        subprocess.run(skopeo_login_cmd)
        logger.debug(f"Running `{skopeo_inspect_cmd}`")
        result = subprocess.run(skopeo_inspect_cmd, capture_output=True)

        if result.returncode != 0:
            raise ImageNotFoundError(
                f"Image {self.name}:{self.registry_image_tag} not found in {ci_registry}"
            )
        container_info = json.loads(result.stdout)
        return container_info

    def update_before_script(self, job_name, lines):
        """
        :param job_name: which job to update
        :param lines: which lines to add
        """
        if "before_script" in self.workflow[job_name]:
            self.workflow[job_name]["before_script"].extend(lines)
        else:
            self.workflow[job_name]["before_script"] = lines

    def compose_workflow(self):
        for architecture in self.architectures:
            job_name = self.architecture_jobs[architecture]
            self.workflow[job_name] = copy.deepcopy(self.build_workflow["build"])
            self.workflow[job_name]["tags"] = [architecture_map[architecture]["tag"]]
            self.workflow[job_name]["variables"][
                "CI_REGISTRY_IMAGE"
            ] = self.registry_image

            if len(self.architectures) > 1:
                self.workflow[job_name]["variables"][
                    "REGISTRY_IMAGE_TAG"
                ] = f"{self.workflow[job_name]['variables']['REGISTRY_IMAGE_TAG']}-{architecture}"

            if not architecture_map[architecture].get("proxy", True):
                before_script = ["unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY"]
                self.update_before_script(job_name, before_script)

        self.workflow["include"] = self.build_workflow["include"]

        if len(self.architectures) > 1:
            multiarch_job_name = f"create multiarch for {self.name}"
            self.multiarch_job = copy.deepcopy(multiarch_yaml)
            self.multiarch_job[multiarch_job_name] = self.multiarch_job.pop(
                "create-multiarch"
            )
            self.multiarch_job[multiarch_job_name]["needs"] = list(
                self.architecture_jobs.values()
            )
            for idx, line in enumerate(
                self.multiarch_job[multiarch_job_name]["script"]
            ):
                self.multiarch_job[multiarch_job_name]["script"][idx] = line.replace(
                    "%REGISTRY_IMAGE%", self.registry_image
                ).replace("%REGISTRY_IMAGE_TAG%", self.registry_image_tag)

            self.workflow.update(self.multiarch_job)
            if "stages" in self.workflow and "multiarch" not in self.workflow["staes"]:
                self.workflow["stages"].append("multiarch")
            elif "stages" not in self.workflow:
                self.workflow["stages"] = ["build", "multiarch"]


class Spacktainerizer(BaseContainer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._spack_commit = None

    @property
    def spack_commit(self):
        if not self._spack_commit:
            logger.debug(f"Cloning spack for {self.name}")
            spack_clone_dir = "spack"
            if os.path.exists(spack_clone_dir):
                shutil.rmtree(spack_clone_dir)
            spack = Repo.clone_from(
                "https://github.com/bluebrain/spack",
                to_path=spack_clone_dir,
                multi_options=["-b develop", "--depth=1"],
            )
            self._spack_commit = spack.head.commit.hexsha

        return self._spack_commit

    def needs_build(self):
        logger.info(f"Checking whether we need to build {self.name}")
        try:
            container_info = self.inspect_image()
        except ImageNotFoundError as ex:
            logger.info(ex)
            return True
        logger.debug("Image found!")

        existing_spack_commit = container_info["Labels"][
            "ch.epfl.bbpgitlab.spack_commit"
        ]
        existing_container_checksum = container_info["Labels"][
            "ch.epfl.bbpgitlab.container_checksum"
        ]
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

    def generate(self):
        if not self.needs_build():
            return {}

        buildah_extra_args = [
            f'--label org.opencontainers.image.title="{self.name}"',
            f'--label org.opencontainers.image.version="{self.registry_image_tag}"',
            f'--label ch.epfl.bbpgitlab.spack_commit="{self.spack_commit}"',
            f'--label ch.epfl.bbpgitlab.container_checksum="{self.container_checksum}"',
        ]
        self.build_workflow["build"]["variables"][
            "BUILDAH_EXTRA_ARGS"
        ] += f" {' '.join(buildah_extra_args)}"
        self.build_workflow["build"]["variables"]["BUILD_PATH"] = self.build_path

        self.compose_workflow()

        for architecture in self.architectures:
            job_name = self.architecture_jobs[architecture]
            if cache_bucket := architecture_map[architecture].get("cache_bucket"):
                self.workflow[job_name]["variables"][
                    "BUILDAH_EXTRA_ARGS"
                ] += f' --build-arg CACHE_BUCKET="s3://{cache_bucket}"'
            if mirror_url := architecture_map[architecture].get("mirror_url"):
                self.workflow[job_name]["variables"][
                    "BUILDAH_EXTRA_ARGS"
                ] += f' --build-arg MIRROR_URL="{mirror_url}"'
            copy_key = [
                'cp "$SPACK_DEPLOYMENT_KEY_PUBLIC" "$CI_PROJECT_DIR/builder/key.pub"'
            ]
            self.update_before_script(job_name, copy_key)

        return self.workflow


class Singularitah(BaseContainer):
    def __init__(self, singularity_version, s3cmd_version, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.singularity_version = singularity_version
        self.s3cmd_version = s3cmd_version

    def needs_build(self):
        logger.info(f"Checking whether we need to build {self.name}")
        try:
            container_info = self.inspect_image()
        except ImageNotFoundError as ex:
            logger.info(ex)
            return True
        logger.debug(f"Image {self.name} found")

        existing_singularity_version = container_info["Labels"][
            "ch.epfl.bbpgitlab.singularity_version"
        ]
        existing_s3cmd_version = container_info["Labels"][
            "ch.epfl.bbpgitlab.s3cmd_version"
        ]
        existing_container_checksum = container_info["Labels"][
            "ch.epfl.bbpgitlab.container_checksum"
        ]
        if (
            existing_container_checksum == self.container_checksum
            and existing_s3cmd_version == self.s3cmd_version
            and existing_singularity_version == self.singularity_version
        ):
            logger.info(f"No need to build {self.name}")
            return False

        logger.info(f"We'll have to build {self.name}")
        return True

    def generate(self):
        if not self.needs_build():
            return {}

        buildah_extra_args = [
            f'--label org.opencontainers.image.title="{self.name}"',
            f'--label org.opencontainers.image.version="{self.registry_image_tag}"',
            f'--label ch.epfl.bbpgitlab.singularity_version="{self.singularity_version}"',
            f'--label ch.epfl.bbpgitlab.s3cmd_version="{self.s3cmd_version}"',
            f'--label ch.epfl.bbpgitlab.container_checksum="{self.container_checksum}"',
            f'--build-arg SINGULARITY_VERSION="{self.singularity_version}"',
            f'--build-arg S3CMD_VERSION="{self.s3cmd_version}"',
        ]
        self.build_workflow["build"]["variables"][
            "BUILDAH_EXTRA_ARGS"
        ] += f" {' '.join(buildah_extra_args)}"
        self.build_workflow["build"]["variables"]["BUILD_PATH"] = self.build_path

        self.compose_workflow()

        return self.workflow
