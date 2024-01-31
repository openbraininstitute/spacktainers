buildah_include_yaml = {
    "include": [
        {"project": "cs/gitlabci-templates", "file": "/build-image-using-buildah.yml"}
    ],
}

bbp_containerizer_include_yaml = {
    "include": [
        {
            "project": "nse/bbp-containerizer",
            "file": "/python/ci/templates/convert-image.yml",
        }
    ]
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

generate_containers_workflow_yaml = {
    "stage": "generate containers workflow",
    "variables": {
        "KUBERNETES_CPU_LIMIT": 4,
        "KUBERNETES_CPU_REQUEST": 2,
        "KUBERNETES_MEMORY_LIMIT": "16Gi",
        "KUBERNETES_MEMORY_REQUEST": "4Gi",
    },
    "script": [
        "apt-get update && apt-get install -y ca-certificates git python3 python3-pip skopeo",
        "pip install --upgrade pip setuptools",
        "pip install -e ./job_creator",
        "jc generate-spackah-workflow -a ${ARCHITECTURE} -o ${OUTPUT_DIR}",
    ],
    "artifacts": {
        "when": "always",
        "paths": [
            "artifacts.*/*/*/spack.lock",
            "artifacts.*/*/*/spack.yaml",
            "${OUTPUT_DIR}",
            "job_creator.log",
        ],
    },
}

build_spackah_yaml = {
    "stage": "build spackah containers",
    "extends": ".build-image-using-buildah",
    "variables": {
        "KUBERNETES_CPU_LIMIT": 4,
        "KUBERNETES_CPU_REQUEST": 2,
        "KUBERNETES_MEMORY_LIMIT": "16Gi",
        "KUBERNETES_MEMORY_REQUEST": "4Gi",
        "BUILDAH_EXTRA_ARGS": (
            ' --label org.opencontainers.image.revision="$CI_COMMIT_SHA"'
            ' --label org.opencontainers.image.authors="$GITLAB_USER_NAME <$GITLAB_USER_EMAIL>"'
            ' --label org.opencontainers.image.url="$CI_PROJECT_URL"'
            ' --label org.opencontainers.image.source="$CI_PROJECT_URL"'
            ' --label org.opencontainers.image.created="$CI_JOB_STARTED_AT"'
            ' --label ch.epfl.bbpgitlab.ci-pipeline-url="$CI_PIPELINE_URL"'
            ' --label ch.epfl.bbpgitlab.ci-commit-branch="$CI_COMMIT_BRANCH"'
            ' --build-arg GITLAB_CI="$GITLAB_CI"'
            ' --build-arg CI_JOB_TOKEN="$CI_JOB_TOKEN"'
        ),
    },
    "before_script": [
        "cp $SPACK_ENV_DIR/spack.yaml ${BUILD_PATH}/",
    ],
}

create_sif_yaml = {
    "stage": "create SIF files",
    "variables": {
        "KUBERNETES_CPU_LIMIT": 4,
        "KUBERNETES_CPU_REQUEST": 2,
        "KUBERNETES_MEMORY_LIMIT": "16Gi",
        "KUBERNETES_MEMORY_REQUEST": "4Gi",
    },
    "script": [
        "/bin/bash",
        "cat /root/.s3cfg",
        "ps",
        "export SINGULARITY_DOCKER_USERNAME=${CI_REGISTRY_USER}",
        "export SINGULARITY_DOCKER_PASSWORD=${CI_JOB_TOKEN}",
        'singularity pull --no-https "${FS_CONTAINER_PATH}" "docker://${CI_REGISTRY_IMAGE}:${REGISTRY_IMAGE_TAG}"',
        "set +e",
        "container_info=$(s3cmd info ${S3_CONTAINER_PATH}); retval=$?",
        "echo $retval",
        "set -e",
        "if [[ ${retval} -ne 0 ]]; then",
        "    echo ${S3_CONTAINER_PATH} does not exist yet - deleting old versions and uploading",
        "    for existing_sif in $(s3cmd ls s3://${BUCKET}/containers/spacktainerizah/${CONTAINER_NAME}__ | awk '{print $4}'); do",
        "        LAST_MOD=$(s3cmd info ${existing_sif} | awk '/^\s+Last mod:/' | tr -d ':')",
        "        echo last mod is ${LAST_MOD}",
        "        remove=$(python -c \"from datetime import datetime, timedelta; print(datetime.strptime('${LAST_MOD}'.strip(), 'Last mod  %a, %d %b %Y %H%M%S %Z') < datetime.now() - timedelta(weeks=1))\")",
        "        echo remove is ${remove}",
        '        if [ "${remove}" == "True" ]; then',
        "            echo Removing ${existing_sif}",
        "            s3cmd rm ${existing_sif}",
        "        else",
        "            echo ${existing_sif} is less than a week old - keeping it for now as it might still be in use.",
        "        fi" "    done",
        "    echo Uploading",
        "    s3cmd put --add-header x-amz-meta-container-checksum:${CONTAINER_CHECKSUM} --add-header x-amz-meta-spack-lock-sha256:${SPACK_LOCK_SHA256} ${FS_CONTAINER_PATH} ${S3_CONTAINER_PATH}",
        "else",
        "    echo ${S3_CONTAINER_PATH} exists - checking sha256sum",
        "    bucket_spack_lock_sha256=$(echo ${container_info} | awk -F':' '/x-amz-meta-spack-lock-sha256/ {print $2}' | sed 's/ //g')",
        "    bucket_container_checksum=$(echo ${container_info} | awk -F':' '/x-amz-meta-container-checksum/ {print $2}' | sed 's/ //g')",
        '    echo "Bucket spack lock sha256 is ${bucket_spack_lock_sha256} (expected ${SPACK_LOCK_SHA256})"',
        '    echo "Bucket container checksum is ${bucket_container_checksum} (expected ${CONTAINER_CHECKSUM})"',
        '    if [[ "${CONTAINER_CHECKSUM}" != "${bucket_container_checksum}" ]] || [[ "${SPACK_LOCK_SHA256}" != "${bucket_spack_lock_sha256}" ]]; then',
        "        echo checksum mismatch - re-uploading",
        "        s3cmd put --add-header x-amz-meta-container-checksum:${CONTAINER_CHECKSUM} --add-header x-amz-meta-spack-lock-sha256:${SPACK_LOCK_SHA256} ${FS_CONTAINER_PATH} ${S3_CONTAINER_PATH}",
        "    else",
        "        echo checksums match - nothing to do here",
        "    fi",
        "fi",
    ],
}

build_custom_containers_yaml = {
    "stage": "create SIF files",
    "variables": {
        "KUBERNETES_CPU_LIMIT": 4,
        "KUBERNETES_CPU_REQUEST": 2,
        "KUBERNETES_MEMORY_LIMIT": "16Gi",
        "KUBERNETES_MEMORY_REQUEST": "4Gi",
    },
    "script": [
        "cat /root/.s3cfg",
        "echo Building SIF",
        "singularity build ${CONTAINER_FILENAME} ${CONTAINER_DEFINITION}",
        "echo Uploading ${CONTAINER_FILENAME} to ${S3_CONTAINER_PATH}",
        "s3cmd put --add-header x-amz-meta-digest:${SOURCE_DIGEST} ${CONTAINER_FILENAME} ${S3_CONTAINER_PATH}",
    ],
}
