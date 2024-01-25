import datetime
import itertools
import json
import os
from pathlib import PosixPath
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from dateutil.tz import tzutc

from spackitor import spackitor

EXPECTED_PACKAGES = [
    "build_cache/linux-ubuntu20.04-x86_64/gcc-9.4.0/present_new_enough-1.2.3/linux-ubuntu20.04-x86_64-gcc-9.4.0-present_new_enough-1.2.3-4zgnw5n6v32wunbjg4ajkt3tukld2uo6.spack",
    "build_cache/linux-ubuntu20.04-x86_64/gcc-9.4.0/absent_new_enough-4.5.6/linux-ubuntu20.04-x86_64-gcc-9.4.0-absent_new_enough-4.5.6-rexlp3wrtheojr4o3dsa5lcctgixpa6x.spack",
    "build_cache/linux-ubuntu22.04-x86_64/gcc-12.2.0/present_too_old-1.4.3/linux-ubuntu22.04-x86_64-gcc-12.2.0-present_too_old-1.4.3-xi6262rcvjhsobjid63toj7nwvjlj6x5.spack",
    "build_cache/linux-ubuntu20.04-x86_64/gcc-9.4.0/absent_too_old-4.3.1-4.3.4/linux-ubuntu20.04-x86_64-gcc-9.4.0-absent_too_old-4.3.1-4.3.4-ydl77hkfdl6w4tuwv5wznvbxmf6uvvra.spack",
]

SECOND_EXPECTED_PACKAGES = [
    "build_cache/linux-ubuntu20.04-x86_64/gcc-9.4.0/from_second_specfile_new_enough-3.5/linux-ubuntu20.04-x86_64-gcc-9.4.0-from_second_specfile_new_enough-3.5-zfzudapqgpxfqj4os2oym3ne6qvkzlap.spack",
    "build_cache/linux-ubuntu20.04-x86_64/gcc-9.4.0/from_second_specfile_too_old-39.2-alpha1/linux-ubuntu20.04-x86_64-gcc-9.4.0-from_second_specfile_too_old-39.2-alpha1-mjbs2jb2hwyybpqghgwamdw5exb3s44b.spack",
]

EXPECTED_SIGNATURES = [
    "build_cache/linux-ubuntu20.04-x86_64-gcc-9.4.0-present_new_enough-1.2.3-4zgnw5n6v32wunbjg4ajkt3tukld2uo6.spec.json.sig",
]

MAX_AGE = 3
LAST_MODIFIED_NEW_ENOUGH = datetime.datetime.now(tzutc()) - datetime.timedelta(days=1)
LAST_MODIFIED_TOO_OLD = datetime.datetime.now(tzutc()) - datetime.timedelta(days=5)


def test_build_sig_key():
    spackitor.build_sig_key(
        {
            "arch": {
                "platform": "linux",
                "platform_os": "ubuntu20.04",
                "target": "x86_64",
            },
            "compiler": {"name": "gcc", "version": "9.4.0"},
            "name": "present_new_enough",
            "version": "1.2.3",
            "hash": "4zgnw5n6v32wunbjg4ajkt3tukld2uo6",
        }
    )


@pytest.mark.parametrize("specify_env", [True, False])
@patch("spackitor.spackitor.parse_spack_env")
@patch("spackitor.spackitor.get_s3_client")
@patch("spackitor.spackitor.traverse_index", return_value=None)
@patch("os.path.exists", return_value=True)
def test_clean_cache(
    mock_exists,
    mock_traverse_index,
    mock_get_s3_client,
    mock_parse_spack_env,
    specify_env,
):
    spack_env = " " if specify_env else None
    spackitor._clean_cache(
        spack_env, spack_directory="/opt/spack", bucket="spack-build-cache"
    )
    if not specify_env:
        mock_parse_spack_env.assert_not_called()
    else:
        mock_parse_spack_env.assert_called_once()

    mock_traverse_index.assert_called_once()


@patch("spackitor.spackitor.boto3")
def test_raises_no_access_keys(mocked_boto3):
    with pytest.raises(
        ValueError,
        match="^No or incomplete AWS access key found. Please set the AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables.$",
    ):
        spackitor.get_s3_client()


@patch("spackitor.spackitor.boto3")
def test_uses_aws_env_vars(mock_boto3):
    mock_access_key = "access key"
    mock_secret_key = "secret key"
    endpoint_url = "https://bbpobjectstorage.epfl.ch"
    os.environ["AWS_ACCESS_KEY_ID"] = mock_access_key
    os.environ["AWS_SECRET_ACCESS_KEY"] = mock_secret_key
    os.environ["S3_ENDPOINT_URL"] = endpoint_url

    mock_session = MagicMock()
    mock_boto3.session.Session.return_value = mock_session

    spackitor.get_s3_client()

    mock_session.client.assert_called_with(
        service_name="s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=mock_access_key,
        aws_secret_access_key=mock_secret_key,
    )


def test_build_key():
    with open("spackitor/tests/spack.lock", "r") as fp:
        spec = json.load(fp)
    path = spackitor.build_key(
        spec["concrete_specs"]["4zgnw5n6v32wunbjg4ajkt3tukld2uo6"]
    )
    assert (
        path
        == "build_cache/linux-ubuntu20.04-x86_64/gcc-9.4.0/present_new_enough-1.2.3/linux-ubuntu20.04-x86_64-gcc-9.4.0-present_new_enough-1.2.3-4zgnw5n6v32wunbjg4ajkt3tukld2uo6.spack"
    )


def test_parse_nonexistant_spack_env():
    spack_env = "/tmp/this/file/does/not/exist.txt"
    with pytest.raises(ValueError, match=f"^{spack_env} does not exist$"):
        spackitor.parse_spack_env(spack_env)


def test_parse_spack_env():
    spack_env = "spackitor/tests/spack.lock"

    packages = spackitor.parse_spack_env(spack_env)
    assert packages == EXPECTED_PACKAGES


@patch("spackitor.spackitor.download_index")
@patch("spackitor.spackitor.get_s3_client")
@patch("spackitor.spackitor.list_spack_packages_in_repo")
def test_traverse_index(
    mock_list_packages_in_repo,
    mock_get_s3_client,
    mock_download_index,
):
    """
    In the package names, "present/absent" means to "present/absent in the spack environment"
    """

    mock_download_index.return_value = {
        "database": {
            "installs": {
                "4zgnw5n6v32wunbjg4ajkt3tukld2uo6": {
                    "spec": {
                        "arch": {
                            "platform": "linux",
                            "platform_os": "ubuntu20.04",
                            "target": "x86_64",
                        },
                        "compiler": {"name": "gcc", "version": "9.4.0"},
                        "name": "present_new_enough",
                        "version": "1.2.3",
                        "hash": "4zgnw5n6v32wunbjg4ajkt3tukld2uo6",
                    },
                },
                "rexlp3wrtheojr4o3dsa5lcctgixpa6x": {
                    "spec": {
                        "arch": {
                            "platform": "linux",
                            "platform_os": "ubuntu20.04",
                            "target": "x86_64",
                        },
                        "compiler": {"name": "gcc", "version": "9.4.0"},
                        "name": "absent_new_enough",
                        "version": "4.5.6",
                        "hash": "rexlp3wrtheojr4o3dsa5lcctgixpa6x",
                    },
                },
                "xi6262rcvjhsobjid63toj7nwvjlj6x5": {
                    "spec": {
                        "arch": {
                            "platform": "linux",
                            "platform_os": "ubuntu22.04",
                            "target": "x86_64",
                        },
                        "compiler": {"name": "gcc", "version": "12.2.0"},
                        "name": "present_too_old",
                        "version": "1.4.3",
                        "hash": "xi6262rcvjhsobjid63toj7nwvjlj6x5",
                    }
                },
                "ydl77hkfdl6w4tuwv5wznvbxmf6uvvra": {
                    "spec": {
                        "arch": {
                            "platform": "linux",
                            "platform_os": "ubuntu20.04",
                            "target": "x86_64",
                        },
                        "compiler": {"name": "gcc", "version": "9.4.0"},
                        "name": "absent_too_old",
                        "version": "4.3.1-4.3.4",
                        "hash": "ydl77hkfdl6w4tuwv5wznvbxmf6uvvra",
                    }
                },
                "xqlk7kkfqg6988uwv5wznvbxmf6uv29z": {
                    "spec": {
                        "arch": {
                            "platform": "linux",
                            "platform_os": "ubuntu20.04",
                            "target": "x86_64",
                        },
                        "compiler": {"name": "gcc", "version": "9.4.0"},
                        "name": "deleted-package",
                        "version": "4.3.1-4.3.4",
                        "hash": "xqlk7kkfqg6988uwv5wznvbxmf6uv29z",
                    }
                },
                "zfzudapqgpxfqj4os2oym3ne6qvkzlap": {
                    "spec": {
                        "arch": {
                            "platform": "linux",
                            "platform_os": "ubuntu20.04",
                            "target": "x86_64",
                        },
                        "compiler": {"name": "gcc", "version": "9.4.0"},
                        "name": "from_second_specfile_new_enough",
                        "version": "3.5",
                        "hash": "zfzudapqgpxfqj4os2oym3ne6qvkzlap",
                    }
                },
                "mjbs2jb2hwyybpqghgwamdw5exb3s44b": {
                    "spec": {
                        "arch": {
                            "platform": "linux",
                            "platform_os": "ubuntu20.04",
                            "target": "x86_64",
                        },
                        "compiler": {"name": "gcc", "version": "9.4.0"},
                        "name": "from_second_specfile_too_old",
                        "version": "39.2-alpha1",
                        "hash": "mjbs2jb2hwyybpqghgwamdw5exb3s44b",
                    }
                },
                "zrffl34kskkdfh289045lkkdhsi1l4jh": {
                    "spec": {
                        "arch": {
                            "platform": "linux",
                            "platform_os": "ubuntu20.04",
                            "target": "x86_64",
                        },
                        "compiler": {"name": "gcc", "version": "9.4.0"},
                        "name": "depends_on_deleted",
                        "version": "7.8.9",
                        "hash": "zrffl34kskkdfh289045lkkdhsi1l4jh",
                        "dependencies": [
                            {"name": "absent_too_old",
                             "hash": "ydl77hkfdl6w4tuwv5wznvbxmf6uvvra",
                             "type": ["build", "run"]},
                        ],
                    },
                },
            }
        }
    }

    prod_updated_index = {
        "database": {
            "installs": {
                "4zgnw5n6v32wunbjg4ajkt3tukld2uo6": {
                    "spec": {
                        "arch": {
                            "platform": "linux",
                            "platform_os": "ubuntu20.04",
                            "target": "x86_64",
                        },
                        "compiler": {"name": "gcc", "version": "9.4.0"},
                        "name": "present_new_enough",
                        "version": "1.2.3",
                        "hash": "4zgnw5n6v32wunbjg4ajkt3tukld2uo6",
                    },
                },
                "rexlp3wrtheojr4o3dsa5lcctgixpa6x": {
                    "spec": {
                        "arch": {
                            "platform": "linux",
                            "platform_os": "ubuntu20.04",
                            "target": "x86_64",
                        },
                        "compiler": {"name": "gcc", "version": "9.4.0"},
                        "name": "absent_new_enough",
                        "version": "4.5.6",
                        "hash": "rexlp3wrtheojr4o3dsa5lcctgixpa6x",
                    },
                },
                "xi6262rcvjhsobjid63toj7nwvjlj6x5": {
                    "spec": {
                        "arch": {
                            "platform": "linux",
                            "platform_os": "ubuntu22.04",
                            "target": "x86_64",
                        },
                        "compiler": {"name": "gcc", "version": "12.2.0"},
                        "name": "present_too_old",
                        "version": "1.4.3",
                        "hash": "xi6262rcvjhsobjid63toj7nwvjlj6x5",
                    }
                },
                "zfzudapqgpxfqj4os2oym3ne6qvkzlap": {
                    "spec": {
                        "arch": {
                            "platform": "linux",
                            "platform_os": "ubuntu20.04",
                            "target": "x86_64",
                        },
                        "compiler": {"name": "gcc", "version": "9.4.0"},
                        "name": "from_second_specfile_new_enough",
                        "version": "3.5",
                        "hash": "zfzudapqgpxfqj4os2oym3ne6qvkzlap",
                    }
                },
            }
        }
    }

    mock_list_packages_in_repo.return_value = [
        "present_new_enough",
        "absent_new_enough",
        "present_too_old",
        "absent_too_old",
        "from_second_specfile_new_enough",
        "depends_on_deleted",
    ]
    whitelist = [
        key
        for key in EXPECTED_PACKAGES + SECOND_EXPECTED_PACKAGES
        if "absent" not in key
    ]

    delete_objects = MagicMock(
        return_value={"ResponseMetadata": {"HTTPStatusCode": 200}}
    )
    mock_s3_client = MagicMock()
    mock_s3_client.head_object = mock_head
    mock_s3_client.delete_objects = delete_objects
    spackitor.traverse_index(
        mock_s3_client, "spack-build-cache", whitelist, set(), MAX_AGE, "/opt/spack"
    )
    print(f"Call count: {delete_objects.call_count}")
    delete_objects.assert_called_with(
        Bucket="spack-build-cache",
        Delete={
            "Objects": [
                {
                    "Key": "build_cache/linux-ubuntu20.04-x86_64/gcc-9.4.0/absent_too_old-4.3.1-4.3.4/linux-ubuntu20.04-x86_64-gcc-9.4.0-absent_too_old-4.3.1-4.3.4-ydl77hkfdl6w4tuwv5wznvbxmf6uvvra.spack"
                },
                {
                    "Key": "build_cache/linux-ubuntu20.04-x86_64-gcc-9.4.0-absent_too_old-4.3.1-4.3.4-ydl77hkfdl6w4tuwv5wznvbxmf6uvvra.spec.json.sig"
                },
                {
                    "Key": "build_cache/linux-ubuntu20.04-x86_64/gcc-9.4.0/deleted-package-4.3.1-4.3.4/linux-ubuntu20.04-x86_64-gcc-9.4.0-deleted-package-4.3.1-4.3.4-xqlk7kkfqg6988uwv5wznvbxmf6uv29z.spack"
                },
                {
                    "Key": "build_cache/linux-ubuntu20.04-x86_64-gcc-9.4.0-deleted-package-4.3.1-4.3.4-xqlk7kkfqg6988uwv5wznvbxmf6uv29z.spec.json.sig"
                },
                {
                    "Key": "build_cache/linux-ubuntu20.04-x86_64/gcc-9.4.0/from_second_specfile_too_old-39.2-alpha1/linux-ubuntu20.04-x86_64-gcc-9.4.0-from_second_specfile_too_old-39.2-alpha1-mjbs2jb2hwyybpqghgwamdw5exb3s44b.spack"
                },
                {
                    "Key": "build_cache/linux-ubuntu20.04-x86_64-gcc-9.4.0-from_second_specfile_too_old-39.2-alpha1-mjbs2jb2hwyybpqghgwamdw5exb3s44b.spec.json.sig"
                },
                {
                    "Key": "build_cache/linux-ubuntu20.04-x86_64/gcc-9.4.0/depends_on_deleted-7.8.9/linux-ubuntu20.04-x86_64-gcc-9.4.0-depends_on_deleted-7.8.9-zrffl34kskkdfh289045lkkdhsi1l4jh.spack"
                },
                {
                    "Key": "build_cache/linux-ubuntu20.04-x86_64-gcc-9.4.0-depends_on_deleted-7.8.9-zrffl34kskkdfh289045lkkdhsi1l4jh.spec.json.sig"
                },
            ]
        },
    )


class ObjectLister:
    def __init__(self, max_age):
        self.counter = 0
        self.object_count = 3272
        self.max_age = max_age
        self.packages = sorted(
            [
                str(uuid4()).replace("-", "_") + "_too_old"
                for x in range(self.object_count)
            ]
        )

        self.specs = [
            {
                "spec": {
                    "arch": {
                        "platform": "linux",
                        "platform_os": "ubuntu",
                        "target": "x86_64",
                    },
                    "compiler": {"name": "gcc", "version": "9.3.0"},
                    "name": package,
                    "version": "1.2.3",
                    "hash": str(uuid4()).split("-")[0],
                }
            }
            for package in self.packages
        ]
        print(f"Packages: {len(self.packages)}")
        package_objects = [
            f"build_cache/{spec['spec']['arch']['platform']}-{spec['spec']['arch']['platform_os']}-{spec['spec']['arch']['target']}/{spec['spec']['compiler']['name']}-{spec['spec']['compiler']['version']}/{spec['spec']['name']}-{spec['spec']['version']}/{spec['spec']['arch']['platform']}-{spec['spec']['arch']['platform_os']}-{spec['spec']['arch']['target']}-{spec['spec']['compiler']['name']}-{spec['spec']['compiler']['version']}-{spec['spec']['name']}-{spec['spec']['version']}-{spec['spec']['hash']}.spack"
            for spec in self.specs
        ]

        sig_objects = [
            f"build_cache/{spec['spec']['arch']['platform']}-{spec['spec']['arch']['platform_os']}-{spec['spec']['arch']['target']}-{spec['spec']['compiler']['name']}-{spec['spec']['compiler']['version']}-{spec['spec']['name']}-{spec['spec']['version']}-{spec['spec']['hash']}.spec.json.sig"
            for spec in self.specs
        ]

        self.s3_objects = [
            x
            for x in itertools.chain.from_iterable(
                itertools.zip_longest(package_objects, sig_objects)
            )
        ]

        print(f"First package: {self.packages[0]}")
        print(f"Packages 999-1000: {self.packages[999:1001]}")
        print(f"Packages 1999-2000: {self.packages[1999:2001]}")
        print(f"Packages 2999-3000: {self.packages[2999:3001]}")
        print(f"Last package: {self.packages[-1]}")

    def list(self, *args, **kwargs):
        print(f"Counter is {self.counter}")
        is_truncated = True if self.counter + 1000 < self.object_count else False

        print(f"Truncated: {is_truncated}")
        s3_object_list = {
            "IsTruncated": is_truncated,
            "NextContinuationToken": "abc",
            "Contents": [
                {
                    "Key": s3_object,
                    "LastModified": datetime.datetime.now(tzutc())
                    - datetime.timedelta(days=self.max_age + 1),
                }
                for s3_object in self.s3_objects[self.counter : self.counter + 1000]
            ],
        }
        self.counter += 1000
        print(f"Counter is now {self.counter}")
        return s3_object_list


def test_failed_delete_raises():
    mock_s3_client = MagicMock()
    response = {"ResponseMetadata": {"HTTPStatusCode": 500}}
    delete_objects = MagicMock(return_value=response)
    mock_s3_client.delete_objects = delete_objects
    with pytest.raises(
        RuntimeError, match=f"^Failed to delete, here is the full response: {response}$"
    ):
        spackitor.delete(mock_s3_client, "bukkit", {"Objects": []})


@patch("spackitor.spackitor.download_index")
@patch("spackitor.spackitor.get_s3_client")
@patch("spackitor.spackitor.list_spack_packages_in_repo")
def test_traverse_index_many_keys(
    mock_list_packages_in_repo,
    mock_get_s3_client,
    mock_download_index,
):
    """
    Test behaviour when there are more than 1000 keys to be deleted.
    """
    max_age = 3
    lister = ObjectLister(max_age)
    mock_index = {
        "database": {"installs": {spec["spec"]["hash"]: spec for spec in lister.specs}}
    }

    mock_download_index.return_value = mock_index
    mock_list_packages_in_repo.return_value = lister.packages
    whitelist = []
    delete_objects = MagicMock(
        return_value={"ResponseMetadata": {"HTTPStatusCode": 200}}
    )
    mock_s3_client = MagicMock()
    mock_s3_client.delete_objects = delete_objects
    mock_s3_client.head_object = mock_head
    spackitor.traverse_index(
        mock_s3_client,
        bucket="spack-build-cache",
        whitelist=whitelist,
        deleted_hashes=set(),
        max_age=max_age,
        spack_directory="/opt/spack",
    )

    assert delete_objects.call_count == 7
    calls = [
        call(
            Bucket="spack-build-cache",
            Delete={
                "Objects": [
                    {"Key": s3_object} for s3_object in lister.s3_objects[0:1000]
                ]
            },
        ),
        call(
            Bucket="spack-build-cache",
            Delete={
                "Objects": [
                    {"Key": s3_object} for s3_object in lister.s3_objects[1000:2000]
                ]
            },
        ),
        call(
            Bucket="spack-build-cache",
            Delete={
                "Objects": [
                    {"Key": s3_object} for s3_object in lister.s3_objects[2000:3000]
                ]
            },
        ),
        call(
            Bucket="spack-build-cache",
            Delete={
                "Objects": [
                    {"Key": s3_object} for s3_object in lister.s3_objects[3000:4000]
                ]
            },
        ),
        call(
            Bucket="spack-build-cache",
            Delete={
                "Objects": [
                    {"Key": s3_object} for s3_object in lister.s3_objects[4000:5000]
                ]
            },
        ),
        call(
            Bucket="spack-build-cache",
            Delete={
                "Objects": [
                    {"Key": s3_object} for s3_object in lister.s3_objects[5000:6000]
                ]
            },
        ),
        call(
            Bucket="spack-build-cache",
            Delete={
                "Objects": [
                    {"Key": s3_object} for s3_object in lister.s3_objects[6000:6546]
                ]
            },
        ),
    ]
    delete_objects.assert_has_calls(calls)


@patch("spackitor.spackitor.BytesIO")
def test_download_index(mock_bytes_io):
    mock_bio = MagicMock()
    mock_spec = '{"database": {"version": "6", "installs": {"sjvxlmpwkszvwto62aahpwx3gbfp7s55": "some_spec"}}}'
    mock_bio.getvalue = MagicMock(return_value=mock_spec)
    mock_bytes_io.return_value = mock_bio
    bucket = "bukkit"
    mock_s3_client = MagicMock()
    mock_s3_client.download_fileobj = MagicMock(return_value=mock_spec)
    spackitor.download_index(mock_s3_client, bucket)
    mock_s3_client.download_fileobj.assert_called_with(
        bucket, "build_cache/index.json", mock_bio
    )


def test_nonexistant_spack_directory():
    spack_directory = "/some/path/that/does/not/exist"
    with pytest.raises(
        ValueError,
        match=f"^Spack directory {spack_directory} does not exist - aborting$",
    ):
        spackitor._clean_cache(
            None, spack_directory=spack_directory, bucket="spack-build-cache-dev"
        )


def test_list_spack_packages_in_repo():
    """
    * repo-patches
      * patch-package1
      * patch-package2
    * repo-bluebrain
      * bb-package1
      * bb-package2
      * bb-package3
    * builtin
      * builtin-package1
    """

    class MockPath:
        def __init__(self, path):
            self.path = path

        def glob(self, glob):
            if self.path == "/opt/spack/bluebrain/repo-patches/packages":
                return iter(
                    [
                        PosixPath(os.sep.join([self.path, "patch-package1"])),
                        PosixPath(os.sep.join([self.path, "patch-package2"])),
                    ]
                )
            if self.path == "/opt/spack/bluebrain/repo-bluebrain/packages":
                return iter(
                    [
                        PosixPath(os.sep.join([self.path, "bb-package1"])),
                        PosixPath(os.sep.join([self.path, "bb-package2"])),
                        PosixPath(os.sep.join([self.path, "bb-package3"])),
                    ]
                )
            if self.path == "/opt/spack/var/spack/repos/builtin/packages":
                return iter(
                    [
                        PosixPath(os.sep.join([self.path, "builtin-package1"])),
                    ]
                )

    spack_dir = "/opt/spack"
    with patch("spackitor.spackitor.Path", MockPath):
        all_packages = spackitor.list_spack_packages_in_repo(spack_dir)

    assert all_packages == [
        "bb-package1",
        "bb-package2",
        "bb-package3",
        "patch-package1",
        "patch-package2",
        "builtin-package1",
    ]


def mock_head(*args, **kwargs):
    if "checksum2" in kwargs["Key"]:
        raise ClientError(
            error_response={"Error": {"Code": "404"}}, operation_name="HEAD"
        )
    elif "checksum3" in kwargs["Key"]:
        raise ClientError(
            error_response={"Error": {"Code": "500"}}, operation_name="HEAD"
        )
    elif "test_exists_false" in kwargs["Key"]:
        raise ClientError(
            error_response={"Error": {"Code": "404"}}, operation_name="HEAD"
        )
    elif "too_old" in kwargs["Key"]:
        return {"ResponseMetadata": {}, "LastModified": LAST_MODIFIED_TOO_OLD}
    else:
        return {"ResponseMetadata": {}, "LastModified": LAST_MODIFIED_NEW_ENOUGH}


@pytest.mark.parametrize("exists", [True, False])
def test_object_exists(exists):
    mock_s3_client = MagicMock()
    mock_s3_client.head_object = mock_head
    exists = spackitor.object_exists(
        mock_s3_client, "bukkit", "test_exists" if exists else "test_exists_false"
    )

    if exists:
        assert exists == {
            "ResponseMetadata": {},
            "LastModified": LAST_MODIFIED_NEW_ENOUGH,
        }
    else:
        assert exists is None
