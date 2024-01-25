ARG BASE_IMAGE=ubuntu:22.04
ARG MIRROR_URL=""
ARG CACHE_BUCKET="s3://spack-build-cache"
FROM $BASE_IMAGE as bootstrap

ENV SPACK_ROOT=/opt/spack \
    CURRENTLY_BUILDING_DOCKER_IMAGE=1 \
    container=docker

RUN export DEBIAN_FRONTEND=noninteractive && apt-get update \
 && apt-get install -y build-essential curl file gfortran git python3 python3-boto3 rpm unzip

# Yes, again. Line 1 by itself is not enough to export this ARG into the shell in RUN
ARG BASE_IMAGE
# BlueBrain internal S3 bucket
ARG MIRROR_URL
# For AWS S3 bucket
ARG CACHE_BUCKET

RUN if [ "$BASE_IMAGE" = "ubuntu:20.04" ]; then echo "Skipping gcc-12 for $BASE_IMAGE"; \
 else export DEBIAN_FRONTEND=noninteractive && apt-get install -y gcc-12 g++-12 gfortran-12; fi


SHELL ["/bin/bash", "--login", "-c"]

RUN mkdir $SPACK_ROOT && cd $SPACK_ROOT \
 && git clone --single-branch --branch develop https://github.com/BlueBrain/spack.git . \
 && mkdir -p $SPACK_ROOT/opt/spack

RUN ln -s $SPACK_ROOT/share/spack/docker/entrypoint.bash \
          /usr/local/bin/docker-shell \
 && ln -s $SPACK_ROOT/share/spack/docker/entrypoint.bash \
          /usr/local/bin/interactive-shell \
 && ln -s $SPACK_ROOT/share/spack/docker/entrypoint.bash \
          /usr/local/bin/spack-env

RUN mkdir -p /root/.spack \
 && cp $SPACK_ROOT/share/spack/docker/modules.yaml \
        /root/.spack/modules.yaml \
 && cp $SPACK_ROOT/bluebrain/sysconfig/containers/packages.yaml \
        /root/.spack/packages.yaml \
 && rm -rf /root/*.* /run/nologin $SPACK_ROOT/.git

# [WORKAROUND]
# https://superuser.com/questions/1241548/
#     xubuntu-16-04-ttyname-failed-inappropriate-ioctl-for-device#1253889
RUN [ -f ~/.profile ]                                               \
 && sed -i 's/mesg n/( tty -s \\&\\& mesg n || true )/g' ~/.profile \
 || true

WORKDIR /root
SHELL ["docker-shell"]

# Creates the package cache
RUN spack compiler find \
 && spack compiler list
# OpenGL cannot be build by Spack
RUN spack external find opengl

# Add in an external ISPC for the Viz team
RUN cd /opt \
 && curl -L https://github.com/ispc/ispc/releases/download/v1.18.0/ispc-v1.18.0-linux.tar.gz|tar xzf - \
 && rm -rf /opt/ispc-v1.18.0-linux/{examples,css,*.html} \
 && spack external find -p /opt/ispc-v1.18.0-linux ispc

# This will list any missing packages that should be installed via apt.
RUN spack bootstrap status
RUN spack bootstrap now
# Add the BBP build cache, this should only allow _read_ access.
RUN echo "Mirror URL is .${MIRROR_URL}. and CACHE_BUCKET is .${CACHE_BUCKET}."
RUN if [ -n "${MIRROR_URL}" ]; then spack mirror add --s3-endpoint-url ${MIRROR_URL} bbpS3 ${CACHE_BUCKET}; fi

COPY key.pub key.pub
RUN spack gpg trust key.pub

# Build stage with Spack pre-installed and ready to be used
FROM bootstrap as builder

ENTRYPOINT ["/bin/bash", "/usr/local/bin/spack-env"]
# on graviton runners, the CMD does not seem to get appended to the ENTRYPOINT
#ENTRYPOINT ["/bin/bash", "/opt/spack/share/spack/docker/entrypoint.bash"]
#CMD ["interactive-shell"]

# What we want to install and how we want to install it
# is specified in a manifest file (spack.yaml)
RUN mkdir /opt/spack-environment
ONBUILD COPY spack.yaml /opt/spack-environment/spack.yaml

# Set the git token for CI builds
ONBUILD ARG CI_JOB_TOKEN
ONBUILD RUN if [[ -n "${CI_JOB_TOKEN}" ]]; then git config --global url."https://gitlab-ci-token:${CI_JOB_TOKEN}@bbpgitlab.epfl.ch/".insteadOf ssh://git@bbpgitlab.epfl.ch/ ; fi

# Set the git token for manual builds
ONBUILD ARG GITLAB_PRIVATE_TOKEN
ONBUILD RUN if [[ -n "${GITLAB_PRIVATE_TOKEN}" ]]; then git config --global url."https://oauth2:${GITLAB_PRIVATE_TOKEN}@bbpgitlab.epfl.ch/".insteadOf ssh://git@bbpgitlab.epfl.ch/ ; fi

ONBUILD RUN git config --list

ONBUILD RUN spack config blame mirrors

# Install the software, remove unnecessary deps
ONBUILD RUN cd /opt/spack-environment && \
            spack env activate . && \
            spack concretize && \
            spack install --fail-fast && \
            spack gc -y

# Strip all the binaries
ONBUILD RUN find -L /opt/view/* -type f -exec readlink -f '{}' \; | \
            xargs file -i | \
            grep 'charset=binary' | \
            grep 'x-executable\|x-archive\|x-sharedlib' | \
            awk -F: '{print $1}' | xargs strip -s

# Modifications to the environment that are necessary to run
ONBUILD RUN cd /opt/spack-environment && \
            spack env activate --sh -d . >> /etc/profile.d/z10_spack_environment.sh

# Singularity by default sets the LD_LIBRARY_PATH to /.singularity.d/libs that includes
# libraries mounted from the host system. Since spack when enabling the environment might
# overwrite the LD_LIBRARYT_PATH we make sure that /.singularity.d/libs is always there
ONBUILD RUN echo "if [[ \$LD_LIBRARY_PATH != *"/.singularity.d/libs"* ]]; then export LD_LIBRARY_PATH=\${LD_LIBRARY_PATH:+\$LD_LIBRARY_PATH:}/.singularity.d/libs; fi" >> /etc/profile.d/z10_spack_environment.sh
