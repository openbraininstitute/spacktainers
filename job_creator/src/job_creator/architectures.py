import os


prod = os.environ.get("CI_COMMIT_REF_SLUG") == os.environ.get("CI_DEFAULT_BRANCH")

architecture_map = {
    "amd64": {
        "tag": "kubernetes",
        "proxy": True,
        "cache_bucket": {
            "name": "spack-build-cache" if prod else "spack-build-cache-dev",
            "max_age": 90 if prod else 30,
            "endpoint_url": "https://bbpobjectstorage.epfl.ch",
            "keypair_variables": {
                "access_key": "BBP_CACHE_ACCESS_KEY_ID",
                "secret_key": "BBP_CACHE_SECRET_ACCESS_KEY",
            },
        },
        "containers_bucket": {
            "name": "sboinfrastructureassets",
            "keypair_variables": {
                "access_key": "AWS_INFRASTRUCTURE_ACCESS_KEY_ID",
                "secret_key": "AWS_INFRASTRUCTURE_SECRET_ACCESS_KEY",
            },
        },
        "base_arch": "%gcc@12 os=ubuntu22.04 target=x86_64_v3",
        "variables": {
            "KUBERNETES_CPU_REQUEST": 4,
            "KUBERNETES_CPU_LIMIT": 8,
            "KUBERNETES_MEMORY_REQUEST": "8Gi",
            "KUBERNETES_MEMORY_LIMIT": "8Gi",
        },
    },
    "arm64": {
        "tag": "aws_graviton",
        "proxy": False,
        "cache_bucket": {
            "name": "spack-cache-xlme2pbun4",
            "max_age": 90 if prod else 30,
            "keypair_variables": {
                "access_key": "AWS_CACHE_ACCESS_KEY_ID",
                "secret_key": "AWS_CACHE_SECRET_ACCESS_KEY",
            },
        },
        "containers_bucket": {
            "name": "sboinfrastructureassets",
            "keypair_variables": {
                "access_key": "AWS_INFRASTRUCTURE_ACCESS_KEY_ID",
                "secret_key": "AWS_INFRASTRUCTURE_SECRET_ACCESS_KEY",
            },
        },
        "base_arch": "%gcc@12 os=ubuntu22.04 target=armv8.4a",
    },
}
