#!/usr/bin/env python
from argparse import ArgumentParser

from s3 import Browser

"""
Script to purge everything that depends on a package, all the way to the top.
There's probably a lot of duplicate work being done, to be cleaned up.
"""


def humanize_checksum(index, checksum):
    return f"{index['database']['installs'][checksum]['spec']['name']} ({checksum})"


def get_sub_dependents(index, dependents):
    """
    Dependents is a list of hashes
    """

    all_sub_dependents = dependents.copy()

    for dependent in dependents:
        print(f"  * {humanize_checksum(index, dependent)}")
        sub_dependents = [
            install
            for install in index["database"]["installs"]
            if any(
                x["hash"] == dependent
                for x in index["database"]["installs"][install]["spec"].get(
                    "dependencies", []
                )
            )
        ]

        if sub_dependents:
            humanized_sub_dependents = [
                humanize_checksum(index, sub_dependent)
                for sub_dependent in sub_dependents
            ]
            print(f"     -> {humanized_sub_dependents}")
            all_sub_dependents.extend(sub_dependents)
            all_sub_dependents.extend(get_sub_dependents(index, sub_dependents))

    return all_sub_dependents


def get_dependents(index, package):
    print(f"Finding dependents for {package}")
    dependents = [
        install
        for install in index["database"]["installs"]
        if any(
            x["name"] == package
            for x in index["database"]["installs"][install]["spec"].get(
                "dependencies", []
            )
        )
    ]

    dependents.extend(get_sub_dependents(index, dependents))

    return dependents


def main(bucket, package, delete):
    browser = Browser()
    index = browser.get_index(bucket)
    dependents = get_dependents(index, package)
    print(f"{dependents} ({len(dependents)})")

    if delete:
        for dependent in dependents:
            print(f"Looking for {dependent}")
            package_objects = browser.find_package_objects(dependent, bucket=bucket)
            to_delete = {
                "Objects": [
                    {"Key": x["Key"]} for x in package_objects if dependent in x["Key"]
                ]
            }
            if to_delete["Objects"]:
                print(f"DELETE {to_delete}")
                browser.s3_client.delete_objects(Bucket=bucket, Delete=to_delete)
            else:
                print(
                    f"SKIP {humanize_checksum(index, dependent)} - no objects in cache"
                )


if __name__ == "__main__":
    parser = ArgumentParser(
        "Dependents purger. Finds a package and everything that depends on it, "
        "all the way to the top. Will delete the whole chain if asked to do so.")
    )
    parser.add_argument(
        "-b",
        "--bucket",
        default="spack-build-cache",
        help="The bucket to purge. spack-build-cache or spack-build-cache-dev",
    )
    parser.add_argument("-p", "--package", help="Which package you wish to purge")
    parser.add_argument(
        "-d",
        "--delete",
        help="Actually do the delete. If not set, just prints",
        action="store_true",
        default=False,
    )
    args = parser.parse_args()

    print(f"Bucket: {args.bucket}")
    print(f"Package: {args.package}")
    print(f"Delete: {args.delete}")

    main(args.bucket, args.package, args.delete)
