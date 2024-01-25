import json
from io import BytesIO

import boto3
from botocore.exceptions import ClientError

from src import spackitor

BUCKET = "spack-build-cache"
S3_PAGINATION = 1000


def main(string_to_purge):
    """
    Purge all objects which contain a given string
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
        objects = s3_client.list_objects_v2(Bucket=BUCKET, ContinuationToken=objects["NextContinuationToken"], StartAfter=objects["Contents"][-1]["Key"])
        for s3_object in objects["Contents"]:
            all_objects.append(s3_object["Key"])

    for s3_object_key in all_objects:
        if string_to_purge in s3_object_key:
            print(f"Object {s3_object_key} contains {string_to_purge} - removing")
            delete_from_bucket.append({"Key": s3_object["Key"]})

    print(f"Will remove {len(delete_from_bucket)} objects.")

    for keys_to_delete in spackitor.split_list(delete_from_bucket, S3_PAGINATION):
        spackitor.delete(s3_client, BUCKET, {"Objects": keys_to_delete})


if __name__ == "__main__":
    main("l3xgawhlb2tdgsz3mhmmd7bjlrgfv6oi")
    main("7dy2hyb3qr44s4qi7de4v2fjj3xisfeq")
    main("rrlt4yla3jv52ye3mwiyre7tts2hziro")
    main("isnguizzrzkmyxbfhzgrkcbpo5wvw45b")
