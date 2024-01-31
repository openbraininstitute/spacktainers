import copy
import glob
import logging
import logging.config
import os
from datetime import datetime

from ruamel.yaml import YAML

from job_creator.architectures import architecture_map
from job_creator.ci_objects import Job, Workflow
from job_creator.job_templates import (packages_yaml,
                                       process_spack_pipeline_yaml)
from job_creator.logging_config import LOGGING_CONFIG
from job_creator.utils import merge_dicts

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("job_creator")


def read_container_definitions(arch):
    """
    Read and iterate through all container definitions
    """
    yaml = YAML(typ="safe", pure=True)
    for df in glob.glob(f"container_definitions/{arch}/*.yaml"):
        logger.debug(f"Reading file {df}")
        with open(df, "r") as fp:
            yield yaml.load(fp)


def parse_container_definitions(arch):
    """
    Loop through the container definitions and collect all specs and package restrictions
    """
    logger.debug(f"Parsing container definitions for {arch}")
    specs = []
    package_restrictions = {}
    for container_definition in read_container_definitions(arch):
        specs.extend(container_definition["spack"]["specs"])
        logger.debug(f"Found specs: {container_definition['spack']['specs']}")
        if packages := container_definition["spack"].get("packages"):
            merge_dicts(package_restrictions, packages)

    return specs, package_restrictions


def process_spack_yaml(specs, package_restrictions, architecture):
    """
    Create the spack.yaml file that will contain all specs and requirements to build all
    containers.
    """
    yaml = YAML(typ="safe", pure=True)
    with open("spack.yaml", "r") as fp:
        spack = yaml.load(fp)

    spack["spack"]["specs"] = specs
    merge_dicts(spack, {"spack": {"packages": package_restrictions}})

    spack["spack"]["gitlab-ci"]["tags"] = [architecture_map[architecture]["tag"]]
    mapping = next(
        mapping
        for mapping in spack["spack"]["gitlab-ci"]["mappings"]
        if isinstance(mapping, dict) and "runner-attributes" in mapping
    )
    mapping["runner-attributes"]["tags"] = [architecture_map[architecture]["tag"]]
    mapping["runner-attributes"]["image"] = builder_image()
    mapping["runner-attributes"]["image"]["entrypoint"] = [""]
    mapping["match"] = [architecture_map[architecture]["base_arch"]]
    spack["spack"]["gitlab-ci"]["service-job-attributes"]["image"] = builder_image()
    spack["spack"]["gitlab-ci"]["service-job-attributes"]["tags"] = [
        architecture_map[architecture]["tag"]
    ]

    spack["spack"]["mirrors"][
        "bbpS3_upload"
    ] = f"s3://{architecture_map[architecture]['cache_bucket']['name']}"
    for package, pkg_conf in spack["spack"]["packages"].items():
        if pkg_conf.get("require") == "%BASE_ARCH%":
            pkg_conf["require"] = architecture_map[architecture]["base_arch"]

    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 120
    with open(f"merged_spack_{architecture}.yaml", "w") as fp:
        yaml.dump(spack, fp)


def builder_image():
    """
    Return the builder image as it needs to appear in the pipeline yaml
    """
    current_branch = os.environ.get("CI_COMMIT_BRANCH")
    if current_branch == os.environ.get("CI_DEFAULT_BRANCH"):
        image_tag = "latest"
    else:
        today = datetime.strftime(datetime.today(), "%Y.%m.%d")
        image_tag = f"{today}-{current_branch}"
    image = {
        "name": f"bbpgitlab.epfl.ch:5050/hpc/spacktainerizah/builder:{image_tag}",
        "pull_policy": "always",
    }

    return image


def generate_process_spack_jobs(architectures):
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
        job.needs.append(
            {
                "job": f"generate build cache population job for {architecture}",
                "artifacts": True,
            },
        )
        job.variables.update(
            {
                "SPACK_GENERATED_PIPELINE": f"jobs_scratch_dir.{architecture}/pipeline.yml",
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

    for architecture in architectures:
        logger.info(
            f"Generating generate build cache population job for {architecture}"
        )
        packages_job = Job(
            "generate build cache population job",
            architecture=architecture,
            **copy.deepcopy(packages_yaml),
        )
        logger.debug("Adding build cache-related variables")
        packages_job.variables["SPACK_BUILD_CACHE_BUCKET"] = architecture_map[
            architecture
        ]["cache_bucket"]["name"]
        packages_job.variables[
            "ENV_DIR"
        ] = f"${{CI_PROJECT_DIR}}/jobs_scratch_dir.{architecture}"
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

        logger.debug(f"Renaming merged_spack_{architecture}.yaml")
        packages_job.update_before_script(
            f"mv merged_spack_{architecture}.yaml spack.yaml", append=True
        )
        logger.debug("Getting needed specs")
        specs, package_restrictions = parse_container_definitions(architecture)
        logger.debug("Processing spack.yaml")
        process_spack_yaml(specs, package_restrictions, architecture)
        workflow.add_job(packages_job)

    logger.debug("Generating job to process spack-generated yaml")
    workflow += generate_process_spack_jobs(architectures)

    return workflow
