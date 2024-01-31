FROM alpine:3.18
# https://github.com/mattn/go-sqlite3/issues/1164#issuecomment-1848677118

ARG SINGULARITY_VERSION
ARG S3CMD_VERSION

RUN apk add bash linux-headers libseccomp-dev glib-dev fuse3-dev libc-dev gcc make autoconf automake libtool squashfs-tools go wget py3-dateutil
RUN wget https://github.com/sylabs/singularity/releases/download/v${SINGULARITY_VERSION}/singularity-ce-${SINGULARITY_VERSION}.tar.gz
RUN tar xf singularity-ce-${SINGULARITY_VERSION}.tar.gz
RUN cd singularity-ce-${SINGULARITY_VERSION} && \
    ./mconfig && \
    cd builddir && \
    make && \
    make install
RUN singularity --version

RUN mkdir /opt/s3cmd
COPY _s3cfg /root/.s3cfg
RUN cat /root/.s3cfg
RUN wget https://github.com/s3tools/s3cmd/releases/download/v${S3CMD_VERSION}/s3cmd-${S3CMD_VERSION}.tar.gz
RUN tar xf s3cmd-${S3CMD_VERSION}.tar.gz -C /opt/s3cmd/ --strip-components=1
ENV PATH="${PATH}:/opt/s3cmd"

ENTRYPOINT ["/bin/bash"]
