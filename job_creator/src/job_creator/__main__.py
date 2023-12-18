import logging
import logging.config

import click
import yaml

from job_creator.containers import Singularitah, Spacktainerizer
from job_creator.logging_config import LOGGING_CONFIG

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("job_creator")


@click.command
@click.option(
    "--singularity-version", "-S", default="4.0.2", help="Singularity version"
)
@click.option("--s3cmd-version", "-s", default="2.3.0", help="s3cmd version")
@click.option(
    "--output-file",
    "-o",
    default="generated_pipeline.yaml",
    help="Which file to write the output to",
)
def main(singularity_version, s3cmd_version, output_file):
    logger.info("Generating jobs")
    singularitah = Singularitah(
        name="singularitah",
        singularity_version=singularity_version,
        s3cmd_version=s3cmd_version,
        build_path="singularitah",
    )
    builder = Spacktainerizer(
        name="builder", build_path="builder", architectures=["amd64", "arm64"]
    )
    runtime = Spacktainerizer(
        name="runtime", build_path="runtime", architectures=["amd64", "arm64"]
    )
    singularity_job = singularitah.generate()
    builder_job = builder.generate()
    runtime_job = runtime.generate()

    singularity_job.update(builder_job)
    singularity_job.update(runtime_job)

    if not singularity_job:
        logger.info("All containers up to date - generating no-op job.")
        singularity_job = {
            "No containers to rebuild": {
                "script": ["echo 'All containers are up to date'"]
            }
        }

    with open(output_file, "w") as fp:
        yaml.safe_dump(singularity_job, fp)


if __name__ == "__main__":
    main()
