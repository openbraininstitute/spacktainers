import copy
import logging
import logging.config
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from ruamel.yaml import YAML

from job_creator.architectures import architecture_map
from job_creator.ci_objects import Job, Workflow
from job_creator.job_templates import (packages_yaml,
                                       process_spack_pipeline_yaml)
from job_creator.logging_config import LOGGING_CONFIG
from job_creator.utils import merge_dicts

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("job_creator")


def read_container_definitions(arch: str) -> Tuple[str, Dict]:
    """
    Read and iterate through all container definitions, returning a tuple containing
    the container name and its definition
    """
    yaml = YAML(typ="safe", pure=True)
    arch_folder = Path(f"container_definitions/{arch}/")
    for df in arch_folder.glob(f"*.yaml"):
        logger.debug(f"Reading file {df.name}")
        with open(df, "r") as fp:
            yield df.stem, yaml.load(fp)


def process_spack_yaml(
    container_name: str, container_definition: Dict, architecture: str
) -> None:
    """
    Create the full spack.yaml needed to build a container
    """
    yaml = YAML(typ="safe", pure=True)
    with open("spack.yaml", "r") as fp:
        spack = yaml.load(fp)

    spack["spack"]["specs"] = container_definition["spack"]["specs"]
    if package_restrictions := container_definition["spack"].get("packages"):
        merge_dicts(spack, {"spack": {"packages": package_restrictions}})

    for section in spack["spack"]["ci"]["pipeline-gen"]:
        for key in section:
            section[key]["tags"] = [architecture_map[architecture]["tag"]]
            section[key]["image"] = builder_image()
            section[key]["image"]["entrypoint"] = [""]

    spack["spack"]["mirrors"][
        "bbpS3_upload"
    ] = f"s3://{architecture_map[architecture]['cache_bucket']['name']}"
    for package, pkg_conf in spack["spack"]["packages"].items():
        if pkg_conf.get("require") == "%BASE_ARCH%":
            pkg_conf["require"] = architecture_map[architecture]["base_arch"]

    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 120
    with open(f"merged_spack_{container_name}_{architecture}.yaml", "w") as fp:
        yaml.dump(spack, fp)


def builder_image():
    """
    Return the builder image as it needs to appear in the pipeline yaml
    """
    current_branch = os.environ.get("CI_COMMIT_REF_SLUG")
    if current_branch == os.environ.get("CI_DEFAULT_BRANCH"):
        image_tag = "latest"
    else:
        today = datetime.strftime(datetime.today(), "%Y.%m.%d")
        image_tag = f"{today}-{current_branch}"
    image = {
        "name": f"bbpgitlab.epfl.ch:5050/hpc/spacktainers/builder:{image_tag}",
        "pull_policy": "always",
    }

    return image


def generate_process_spack_jobs(architectures, cache_population_job_names):
    """
    Generate the job that will process the spack-produced jobs
    """
    workflow = Workflow()
    for architecture in architectures:
        job = Job(
            "process spack pipeline",
            architecture=architecture,
            **copy.deepcopy(process_spack_pipeline_yaml),
        )
        for job_name in cache_population_job_names[architecture]:
            job.needs.append(
                {
                    "job": job_name,
                    "artifacts": True,
                },
            )
        job.variables.update(
            {
                "SPACK_PIPELINES_ARCH_DIR": f"jobs_scratch_dir.{architecture}",
                "OUTPUT_DIR": f"artifacts.{architecture}",
            }
        )
        workflow.add_job(job)

    return workflow


def generate_packages_workflow(architectures):
    """
    Generate the job that will run `spack ci generate`
    """
    logger.info("Generating packages jobs")
    workflow = Workflow()
    cache_population_job_names = {arch: [] for arch in architectures}

    for architecture in architectures:
        logger.info(
            f"Generating generate build cache population jobs for {architecture}"
        )
        for container_name, container_definition in read_container_definitions(
            architecture
        ):
            logger.info(
                f"Generating generate build cache population job for {container_name}"
            )
            packages_job = Job(
                f"generate build cache population job for {container_name}",
                architecture=architecture,
                **copy.deepcopy(packages_yaml),
            )
            cache_population_job_names[architecture].append(packages_job.name)
            logger.debug("Adding build cache-related variables")
            packages_job.variables["SPACK_BUILD_CACHE_BUCKET"] = architecture_map[
                architecture
            ]["cache_bucket"]["name"]
            packages_job.variables[
                "ENV_DIR"
            ] = f"${{CI_PROJECT_DIR}}/jobs_scratch_dir.{architecture}/{container_name}/"
            packages_job.variables["CONTAINER_NAME"] = container_name
            packages_job.variables.update(
                architecture_map[architecture].get("variables", {})
            )
            logger.debug("Adding tags, image and needs")
            packages_job.image = builder_image()
            packages_job.needs.append(
                {
                    "pipeline": os.environ.get("CI_PIPELINE_ID"),
                    "job": "generate base pipeline",
                    "artifacts": True,
                }
            )
            logger.debug("Keypair variables")
            packages_job.add_spack_mirror()
            packages_job.set_aws_variables()

            logger.debug(f"Adding rename merged_spack_{architecture}.yaml command")
            packages_job.update_before_script(
                f"mv merged_spack_{container_name}_{architecture}.yaml spack.yaml",
                append=True,
            )
            logger.debug("Generating spack.yaml for containers")
            logger.debug(f"{container_name} definition: {container_definition}")
            process_spack_yaml(
                container_name,
                container_definition,
                architecture,
            )
            workflow.add_job(packages_job)

    logger.debug("Generating job to process spack-generated yaml")
    workflow += generate_process_spack_jobs(architectures, cache_population_job_names)

    return workflow, cache_population_job_names
