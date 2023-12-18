buildah_yaml = {
    "include": [
        {"project": "cs/gitlabci-templates", "file": "/build-image-using-buildah.yml"}
    ],
    "build": {
        "extends": ".build-image-using-buildah",
        "stage": "build",
        "tags": ["${TAG}"],
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
    },
}

multiarch_yaml = {
    "create-multiarch": {
        "image": "ubuntu:latest",
        "stage": "multiarch",
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
}
