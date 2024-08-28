import glob
import logging
import os
from pathlib import Path
from pprint import pformat

import click
import requests
from furl import furl

logger = logging.getLogger(__name__)
fh = logging.FileHandler("get_artifacts.log")
fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(msg)s")
fh.setFormatter(fmt)
sh = logging.StreamHandler()
sh.setFormatter(fmt)

logger.setLevel(logging.DEBUG)
fh.setLevel(logging.DEBUG)
sh.setLevel(logging.DEBUG)

logger.addHandler(fh)
logger.addHandler(sh)


def artifacts_url(base_url, project_id, job_id):
    url = base_url / "projects" / str(project_id) / "jobs" / str(job_id) / "artifacts"
    logger.debug(f"Artifacts url: {url}")
    return url


def bridges_url(base_url, project_id, pipeline_id):
    url = (
        base_url
        / "projects"
        / str(project_id)
        / "pipelines"
        / str(pipeline_id)
        / "bridges"
    )
    logger.debug(f"Bridges url: {url}")
    return url


def jobs_url(base_url, project_id, pipeline_id):
    url = (
        base_url
        / "projects"
        / str(project_id)
        / "pipelines"
        / str(pipeline_id)
        / "jobs"
    )
    logger.debug(f"Jobs url: {url}")
    return url


def pipeline_url(base_url, project_id, pipeline_id):
    url = base_url / "projects" / str(project_id) / "pipelines" / str(pipeline_id)
    logger.debug(f"Pipeline url: {url}")
    return url


@click.command()
@click.option(
    "--parent-pipeline", "-P", help="ID of the parent pipeline", required=True
)
@click.option("--private-token", "-t", help="Private gitlab api token", required=False)
def get_artifacts(parent_pipeline, private_token):
    project_id = "2432"
    logger.info(f"Getting artifacts for pipeline {parent_pipeline}")

    session = requests.Session()
    session.headers["Content-Type"] = "application/json"
    if private_token:
        # Yes, there is a CI_JOB_TOKEN, but that doesn't have the necessary permissions
        # https://docs.gitlab.com/ee/ci/jobs/ci_job_token.html
        # it can, for example, not access the pipelines API
        logger.debug("Using private token specified on the command line")
        session.headers["PRIVATE-TOKEN"] = private_token
    else:
        raise RuntimeError(
            "No gitlab api token found, either specify it with `-t` or run this in a job"
        )

    base_url = furl(os.environ.get("CI_API_V4_URL", "https://bbpgitlab.epfl.ch/api/v4"))
    logger.info("Finding bridge jobs")
    bridges = session.get(bridges_url(base_url, project_id, parent_pipeline)).json()
    logger.debug(f"Bridges: {pformat(bridges)}")
    bridge = next(
        b for b in bridges if b["name"] == "base containers and pipeline generation"
    )
    logger.debug(f"Bridge: {pformat(bridge)}")
    logger.info("Finding base containers and pipeline generation")
    run_pipeline = session.get(
        pipeline_url(
            base_url,
            bridge["downstream_pipeline"]["project_id"],
            bridge["downstream_pipeline"]["id"],
        )
    ).json()
    logger.debug(f"Run pipeline: {pformat(run_pipeline)}")
    logger.info("Getting jobs from base containers and pipeline generation")
    jobs = session.get(jobs_url(base_url, project_id, run_pipeline["id"])).json()
    logger.debug(f"Jobs: {pformat(jobs)}")
    for architecture in [
        archdir.name for archdir in Path("container_definitions").glob("[!_]*")
    ]:
        logger.info(f"Architecture: {architecture}")
        process_job = next(
            j for j in jobs if j["name"] == f"process spack pipeline for {architecture}"
        )
        spack_artifacts = session.get(
            artifacts_url(base_url, project_id, process_job["id"])
        )
        logger.info(f"Downloading spack artifacts for {architecture}")
        with open(f"spack.artifacts.{architecture}.zip", "wb") as fp:
            fp.write(spack_artifacts.content)

        spacktainer_job = next(
            j
            for j in jobs
            if j["name"] == f"generate spacktainer jobs for {architecture}"
        )
        spacktainer_artifacts = session.get(
            artifacts_url(base_url, project_id, spacktainer_job["id"])
        )
        logger.info(f"Downloading spacktainer artifacts for {architecture}")
        with open(f"spacktainer.artifacts.{architecture}.zip", "wb") as fp:
            fp.write(spacktainer_artifacts.content)


if __name__ == "__main__":
    get_artifacts()
