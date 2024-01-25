buildah_include_yaml = {
    "include": [
        {"project": "cs/gitlabci-templates", "file": "/build-image-using-buildah.yml"}
    ],
}

buildah_build_yaml = {
    "extends": ".build-image-using-buildah",
    "stage": "build base containers",
    "timeout": "8h",
    "variables": {
        "KUBERNETES_CPU_LIMIT": 4,
        "KUBERNETES_CPU_REQUEST": 2,
        "KUBERNETES_MEMORY_LIMIT": "16Gi",
        "KUBERNETES_MEMORY_REQUEST": "4Gi",
        "REGISTRY_IMAGE_TAG": "",
        "BUILD_PATH": "",
        "CI_REGISTRY_IMAGE": "",
        "BUILDAH_EXTRA_ARGS": (
            '--label org.opencontainers.image.revision="$CI_COMMIT_SHA"'
            ' --label org.opencontainers.image.authors="$GITLAB_USER_NAME <$GITLAB_USER_EMAIL>"'
            ' --label org.opencontainers.image.url="$CI_PROJECT_URL"'
            ' --label org.opencontainers.image.source="$CI_PROJECT_URL"'
            ' --label org.opencontainers.image.created="$CI_JOB_STARTED_AT"'
            ' --label ch.epfl.bbpgitlab.ci-pipeline-url="$CI_PIPELINE_URL"'
            ' --label ch.epfl.bbpgitlab.ci-commit-branch="$CI_COMMIT_BRANCH" '
        ),
    },
}

multiarch_yaml = {
    "image": "ubuntu:latest",
    "stage": "base containers multiarch",
    "script": [
        "apt-get update && apt-get install -y podman",
        'echo "Creating multiarch manifest %REGISTRY_IMAGE%:%REGISTRY_IMAGE_TAG%"',
        "podman login -u ${CI_REGISTRY_USER} -p ${CI_REGISTRY_PASSWORD} --tls-verify=false ${CI_REGISTRY}",
        "podman manifest create mylist",
        'echo "Adding %REGISTRY_IMAGE%:%REGISTRY_IMAGE_TAG%-arm64"',
        "podman manifest add --tls-verify=false mylist %REGISTRY_IMAGE%:%REGISTRY_IMAGE_TAG%-arm64",
        'echo "Adding %REGISTRY_IMAGE%:%REGISTRY_IMAGE_TAG%-amd64"',
        "podman manifest add --tls-verify=false mylist %REGISTRY_IMAGE%:%REGISTRY_IMAGE_TAG%-amd64",
        "podman manifest push --tls-verify=false mylist %REGISTRY_IMAGE%:%REGISTRY_IMAGE_TAG%",
        'if [[ "$CI_COMMIT_BRANCH" == "$CI_DEFAULT_BRANCH" ]]; then',
        '    echo "Also creating multiarch manifest for %REGISTRY_IMAGE%:latest multiarch"',
        "    podman manifest create mylist-latest",
        '    echo "Adding %REGISTRY_IMAGE%:latest-arm64"',
        "    podman manifest add --tls-verify=false mylist-latest %REGISTRY_IMAGE%:latest-arm64",
        '    echo "Adding %REGISTRY_IMAGE%:latest-amd64"',
        "    podman manifest add --tls-verify=false mylist-latest %REGISTRY_IMAGE%:latest-amd64",
        "    podman manifest push --tls-verify=false mylist-latest %REGISTRY_IMAGE%:latest",
        "fi",
    ],
}

packages_yaml = {
    "timeout": "1h",
    "stage": "generate build cache population job",
    "script": [
        "cat /proc/cpuinfo",
        "cat /proc/meminfo",
        'git config --global url."https://gitlab-ci-token:${CI_JOB_TOKEN}@bbpgitlab.epfl.ch/".insteadOf ssh://git@bbpgitlab.epfl.ch/',
        ". $SPACK_ROOT/share/spack/setup-env.sh",
        "spack arch",
        'spack gpg trust "$SPACK_DEPLOYMENT_KEY_PUBLIC"',
        'spack gpg trust "$SPACK_DEPLOYMENT_KEY_PRIVATE"',
        "cat spack.yaml",
        "spack env activate --without-view .",
        "spack config blame packages",
        "spack config blame mirrors",
        "spack concretize -f",
        'spack -d ci generate --check-index-only --artifacts-root "${ENV_DIR}" --output-file "${ENV_DIR}/pipeline.yml"',
    ],
    "artifacts": {"when": "always", "paths": ["${ENV_DIR}"]},
}

process_spack_pipeline_yaml = {
    "image": "ubuntu:latest",
    "stage": "process spack-generated pipelines",
    "script": [
        "apt-get update && apt-get install -y ca-certificates git python3 python3-pip",
        "pip install --upgrade pip setuptools",
        "pip install -e ./job_creator",
        "jc process-spack-pipeline -f ${SPACK_GENERATED_PIPELINE} -o ${OUTPUT_DIR}",
    ],
    "artifacts": {"when": "always", "paths": ["artifacts.*", "spack_pipeline.yaml"]},
}

clean_cache_yaml = {
    "image": "python:3.10-buster",
    "timeout": "4h",
    "allow_failure": True,
    "script": [
        "apt-get update && apt-get install -y git",
        "pip install ./spackitor",
        "git clone https://github.com/bluebrain/spack",
        "spackitor -e ${SPACK_ENV} --bucket ${BUCKET} --max-age ${MAX_AGE} --spack-directory ./spack",
    ],
}
