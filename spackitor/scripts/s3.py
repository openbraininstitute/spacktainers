#!/usr/bin/env python

import json
import os
from io import BytesIO

import boto3


class Browser:
    def __init__(self):
        self.s3_client = self.get_s3_client()

    def list(self, bucket="spack-build-cache", prefix="", delimiter=""):
        """
        Iterator to list all objects in the bucket (max 1000 at a time).
        There is a way to play with prefix and delimiter to group them.
        TODO: use these two params for more efficient searching.
        """
        objects = {
            "IsTruncated": True,
            "NextContinuationToken": "",
            "Contents": [{"Key": ""}],
        }

        while objects["IsTruncated"]:
            objects = self.s3_client.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix,
                Delimiter=delimiter,
                ContinuationToken=objects["NextContinuationToken"],
                StartAfter=objects["Contents"][-1]["Key"],
            )

            yield objects

    def find_lonely_objects(self, bucket="spack-build-cache", delete=False):
        """
        Find "lonely" objects: .spack without matching .spec.json.sig or vice versa

        If you specify delete=True, they will be deleted as well.
        """
        found_keys = []
        for object_set in self.list(bucket, prefix="", delimiter=""):
            for key in object_set["Contents"]:
                found_keys.append(key["Key"])

        sig_ext = ".spec.json.sig"
        spack_ext = ".spack"
        replaced = (
            lambda x: os.path.basename(x).replace(sig_ext, spack_ext)
            if x.endswith(sig_ext)
            else os.path.basename(x).replace(spack_ext, sig_ext)
        )
        lonely_keys = [
            x
            for x in found_keys
            if replaced(x) not in [os.path.basename(y) for y in found_keys]
        ]

        if delete:
            print(
                f"Deleting {len(lonely_keys)} keys - don't forget to rebuild the index!"
            )
            for keys_to_delete in self.split_list(lonely_keys):
                self.s3_client.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": [{"Key": key} for key in keys_to_delete]},
                )

        return lonely_keys

    def split_list(self, source, chunk_size=1000):
        for x in range(0, len(source), chunk_size):
            yield source[x : x + chunk_size]

    def find_package_objects(self, package, bucket="spack-build-cache"):
        """
        Find all objects in the bucket that contain the package name
        """
        found_keys = []
        for object_set in self.list(bucket, prefix="", delimiter=""):
            for key in object_set["Contents"]:
                if package in key["Key"]:
                    found_keys.append(key)

        return found_keys

    def get_index(self, bucket="spack-build-cache"):
        """
        Get the contents of the index.json object, nicely parsed
        """
        bio = BytesIO()
        self.s3_client.download_fileobj(bucket, "build_cache/index.json", bio)
        return json.loads(bio.getvalue())

    def get_s3_client(self):
        """
        Return a Boto3 client object that is connected to bbpobjectstorage.epfl.ch
        ~/.ssh/buildcache_keys contains two lines: access and secret key. In that order.
        """
        access_key, secret_key = [
            line.strip()
            for line in open(os.path.expanduser("~/.ssh/buildcache_keys"), "r")
        ]

        session = boto3.session.Session()
        s3_client = session.client(
            service_name="s3",
            endpoint_url="https://bbpobjectstorage.epfl.ch",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

        return s3_client


def main():
    browser = Browser()
    return browser.s3_client


if __name__ == "__main__":
    main()


browser = Browser()
