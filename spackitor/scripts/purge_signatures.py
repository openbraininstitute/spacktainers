import json
from io import BytesIO

import boto3
from botocore.exceptions import ClientError

from src import spackitor

BUCKET = "spack-build-cache"
S3_PAGINATION = 1000


def main():
    """
    Purge all signature objects which no longer have a package
    """
    session = boto3.session.Session()
    s3_client = session.client(
        service_name="s3",
        endpoint_url="https://bbpobjectstorage.epfl.ch",
        aws_access_key_id="QNJQ73E6O6HQICUIAM8B",
        aws_secret_access_key="TOnJkQX3Uorex1OPfqTEY3P8lAX1Y2ipFdLSNDhx",
    )
    objects = {
        "IsTruncated": True,
        "NextContinuationToken": "",
        "Contents": [{"Key": ""}],
    }

    all_objects = []
    delete_from_bucket = []
    keep_in_bucket = []

    while objects["IsTruncated"]:
        print(objects["Contents"][-1])
        objects = s3_client.list_objects_v2(Bucket=BUCKET, ContinuationToken=objects["NextContinuationToken"], StartAfter=objects["Contents"][-1]["Key"])
        for s3_object in objects["Contents"]:
            all_objects.append(s3_object["Key"])

    for s3_object_key in all_objects:
        if s3_object_key.endswith(".spec.json.sig"):
            real_spec = download_sig(s3_client, s3_object_key)
            obj_key = spackitor.build_key(real_spec["spec"]["nodes"][0])
            if obj_key in all_objects:
                print(f"Object {obj_key} found - keeping signature")
                keep_in_bucket.append(s3_object["Key"])
            else:
                print(f"Object {obj_key} not found - removing signature")
                delete_from_bucket.append({"Key": s3_object["Key"]})

    print(f"Will keep {len(keep_in_bucket)} signatures.")
    print(f"Will kill {len(delete_from_bucket)} signatures.")

    for keys_to_delete in spackitor.split_list(delete_from_bucket, S3_PAGINATION):
        spackitor.delete(s3_client, BUCKET, {"Objects": keys_to_delete})


def download_sig(s3_client, sig_key):
    """
    Download and parse a signature file, return the contents stripped of signature
    and parsed through json
    """
    bio = BytesIO()
    s3_client.download_fileobj(BUCKET, sig_key, bio)
    bio.seek(0)
    sig_spec = bio.read()
    real_spec = json.loads("\n".join(sig_spec.decode().splitlines()[3:-16]))

    return real_spec


if __name__ == "__main__":
    main()
