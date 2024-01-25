import datetime
import json
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Set, Union

import boto3
import click
from botocore.exceptions import ClientError

DEFAULT_MAX_AGE = 30
DEFAULT_BUCKET = "spack-build-cache"
S3_PAGINATION = 1000


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(msg)s")
fh = logging.FileHandler("./spackitor.log")
fh.setFormatter(fmt)
fh.setLevel(logging.DEBUG)
logger.addHandler(fh)
sh = logging.StreamHandler()
sh.setFormatter(fmt)
sh.setLevel(logging.INFO)
logger.addHandler(sh)


def extract_target(spec_target: Union[str, dict]) -> str:
    """ """
    return spec_target["name"] if isinstance(spec_target, dict) else spec_target


def build_sig_key(spec: dict) -> str:
    """
    Take a spack spec and build the expected .json.sig key in the binary build cache for it
    """
    target = extract_target(spec["arch"]["target"])
    key_name = "-".join(
        [
            spec["arch"]["platform"],
            spec["arch"]["platform_os"],
            target,
            spec["compiler"]["name"],
            spec["compiler"]["version"],
            spec["name"],
            spec["version"],
            spec["hash"],
        ]
    )

    path = "/".join(["build_cache", f"{key_name}.spec.json.sig"])

    return path


def build_key(spec: dict) -> str:
    """
    Take a spack spec and build the expected key in the binary build cache for it
    """
    logger.debug(f"Building key with spec {spec}")
    target = extract_target(spec["arch"]["target"])

    part1 = "-".join([spec["arch"]["platform"], spec["arch"]["platform_os"], target])
    part2 = "-".join([spec["compiler"]["name"], spec["compiler"]["version"]])
    part3 = "-".join([spec["name"], spec["version"]])
    part4 = "-".join(
        [
            spec["arch"]["platform"],
            spec["arch"]["platform_os"],
            target,
            spec["compiler"]["name"],
            spec["compiler"]["version"],
            spec["name"],
            spec["version"],
            spec["hash"],
        ]
    )

    path = "/".join(["build_cache", part1, part2, part3, part4])
    path += ".spack"

    return path


def parse_spack_env(spack_env_path: str) -> List[str]:
    """
    Parse a spack environment file and get all package spec S3 paths in it.
    """
    if not os.path.exists(spack_env_path):
        raise ValueError(f"{spack_env_path} does not exist")

    paths = []

    with open(spack_env_path, "r") as fp:
        spack_env = json.load(fp)

    for spec_hash in spack_env["concrete_specs"]:
        spec = spack_env["concrete_specs"][spec_hash]
        path = build_key(spec)

        paths.append(path)

    return paths


def get_s3_client() -> boto3.session.Session.client:
    """
    Get an S3 client object, using the AWS_* environment variables as credentials
    """
    aws_access_key_id = os.environ.get("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    endpoint_url = os.environ.get("S3_ENDPOINT_URL", None)

    if not aws_access_key_id or not aws_secret_access_key:
        raise ValueError(
            "No or incomplete AWS access key found. Please set the AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables."
        )

    logger.info(f"Connecting with endpoint {endpoint_url}")
    session = boto3.session.Session()
    s3_client = session.client(
        service_name="s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )
    return s3_client


def list_spack_packages_in_repo(spack_directory: str) -> List[str]:
    """
    List all packages in the spack directory
    Returns a list of package names
    """

    all_packages = []

    for bbrepo in ["repo-bluebrain", "repo-patches"]:
        all_packages.extend(
            [
                p.name
                for p in Path(
                    os.sep.join([spack_directory, "bluebrain", bbrepo, "packages"])
                ).glob("*")
            ]
        )

    for builtin_repo in ["builtin"]:
        all_packages.extend(
            [
                p.name
                for p in Path(
                    os.sep.join(
                        [
                            spack_directory,
                            "var",
                            "spack",
                            "repos",
                            builtin_repo,
                            "packages",
                        ]
                    )
                ).glob("*")
            ]
        )

    return all_packages


def split_list(source, chunk_size):
    for x in range(0, len(source), chunk_size):
        yield source[x : x + chunk_size]


def traverse_index(
    s3_client: boto3.session.Session.client,
    bucket: str,
    whitelist: List[str],
    deleted_hashes: Set[str],
    max_age: int,
    spack_directory: str,
):
    """
    Traverse the S3 bucket, and clean paths which are not in the whitelist (if any) and older than
    the maximum age.
    If deleted_hashes contains anything, any packages depending on these hashes will also be
    deleted.
    """
    index = download_index(s3_client, bucket)
    existing_packages = list_spack_packages_in_repo(spack_directory)
    delete_from_bucket = []
    for package_checksum in index["database"]["installs"]:
        package_spec = index["database"]["installs"][package_checksum]["spec"]
        dependency_hashes = set(
            [dep["hash"] for dep in package_spec.get("dependencies", [])]
        )
        key = build_key(package_spec)
        sig_key = build_sig_key(package_spec)
        head = object_exists(s3_client, bucket, key)
        if head:
            if deleted_hashes.intersection(dependency_hashes):
                click.echo(
                    f"Cleanup: Package {package_spec['name']} / {package_spec['hash']} depended on at least one deleted object"
                )
                delete_from_bucket.append({"Key": key})
                delete_from_bucket.append({"Key": sig_key})
                deleted_hashes.add(package_spec["hash"])
            last_modified = head["LastModified"]
            age = (
                datetime.datetime.now(head["LastModified"].tzinfo)
                - head["LastModified"]
            )
            if package_spec["name"] not in existing_packages:
                click.echo(
                    f"Cleanup: Package {package_spec['name']} not in existing packages"
                )
                delete_from_bucket.append({"Key": key})
                delete_from_bucket.append({"Key": sig_key})
                deleted_hashes.add(package_spec["hash"])
                continue
            if key in whitelist:
                click.echo(f"Skip: Package {package_spec['name']} is in whitelist")
                continue
            if age.days > max_age:
                click.echo(
                    f"Cleanup: {package_spec['name']}: {age.days} days > {max_age}: {key}"
                )
                delete_from_bucket.append({"Key": key})
                delete_from_bucket.append({"Key": sig_key})
                deleted_hashes.add(package_spec["hash"])

    for keys_to_delete in split_list(delete_from_bucket, S3_PAGINATION):
        delete(s3_client, bucket, {"Objects": keys_to_delete})

    return deleted_hashes


def delete(s3_client: boto3.session.Session.client, bucket: str, keys_to_delete: dict):
    """
    Perform the delete call and raise if a response code >= 400 was returned
    """
    click.echo(f"Deleting {len(keys_to_delete['Objects'])} objects")
    response = s3_client.delete_objects(Bucket=bucket, Delete=keys_to_delete)
    if response["ResponseMetadata"]["HTTPStatusCode"] >= 400:
        raise RuntimeError(f"Failed to delete, here is the full response: {response}")


def download_index(s3_client: boto3.session.Session.client, bucket: str) -> dict:
    """
    Download the index.json file from the build cache and returns the contents.

    Returns the contents of the index
    """
    bio = BytesIO()
    s3_client.download_fileobj(bucket, "build_cache/index.json", bio)
    index = json.loads(bio.getvalue())

    return index


def _clean_cache(
    spack_envs: tuple,
    spack_directory: str,
    bucket: str,
    max_age: int = DEFAULT_MAX_AGE,
):
    if not (os.path.exists(spack_directory)):
        raise ValueError(f"Spack directory {spack_directory} does not exist - aborting")

    whitelist_paths = []

    if spack_envs:
        for spack_env in spack_envs:
            whitelist_paths.extend(parse_spack_env(spack_env))

    whitelist_paths = list(set(whitelist_paths))

    s3_client = get_s3_client()

    deleted_hashes = set()
    while deleted_hashes := traverse_index(
        s3_client, bucket, whitelist_paths, deleted_hashes, max_age, spack_directory
    ):
        pass


def object_exists(
    s3_client: boto3.session.Session.client, bucket: str, key: str
) -> Optional[dict]:
    try:
        head = s3_client.head_object(Bucket=bucket, Key=key)
        return head
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return None
        else:
            raise


@click.command()
@click.option(
    "--spack-envs",
    "-e",
    help="Comma-separated list of spack environment files",
    multiple=True,
)
@click.option(
    "--bucket",
    "-b",
    default=DEFAULT_BUCKET,
    help="S3 bucket in which the build cache lives",
)
@click.option(
    "--max-age",
    "-a",
    default=DEFAULT_MAX_AGE,
    type=int,
    help="Maximum age in days for anything that will be cleaned - older will be removed.",
)
@click.option(
    "--spack-directory", "-s", help="Where the spack repository was checked out"
)
def clean_cache(
    spack_envs: Optional[tuple], spack_directory: str, bucket: str, max_age: int
):
    """
    Clean the specified cache.

    If a (list of) spack environment files is given, anything not in them that is older than the specified time will be removed.
    If no spack environment file is given, anything older than the specified time will be removed.

    The spack directory is necessary to check whether packages have been removed from the repository. If they have been, they will be deleted from the build cache as well.
    """

    click.echo(f"Spack envs: {spack_envs}")
    click.echo(f"Spack directory: {spack_directory}")
    click.echo(f"Bucket: {bucket}")
    click.echo(f"Max age: {max_age}")
    _clean_cache(spack_envs, spack_directory, bucket, max_age)


if __name__ == "__main__":
    clean_cache()
