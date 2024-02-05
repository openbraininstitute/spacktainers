#!/bin/bash

set -e
set -o pipefail

if [[ "$(uname -p)" == "x86_64" ]]; then
    exit 0
fi

curl -L https://developer.arm.com/-/media/Files/downloads/hpc/arm-compiler-for-linux/23-10/arm-compiler-for-linux_23.10_Ubuntu-22.04_aarch64.tar | tar xf -
./arm-compiler-for-linux_23.10_Ubuntu-22.04/arm-compiler-for-linux_23.10_Ubuntu-22.04.sh -a
rm -rf arm-compiler-for-linux_23.10_Ubuntu-22.04

. /etc/profile.d/modules.sh

module use /opt/arm/modulefiles
module load acfl
module load armpl

spack compiler find --scope=site

ARM_MODULE_FILES=/opt/arm/modulefiles/binutils/12.2.0,/opt/arm/modulefiles/acfl/23.10,/opt/arm/moduledeps/acfl/23.10/armpl/23.10.0

sed -i -e '/spec: arm/,/modules:/{/modules:/ s#\[\]#['"${ARM_MODULE_FILES}"']#}' \
      ${SPACK_ROOT}/etc/spack/compilers.yaml

spack external find --scope=site acfl

spack config --scope=site add "packages:all:compiler:[arm]"
spack config --scope=site add "packages:all:providers:blas:[acfl]"
spack config --scope=site add "packages:all:providers:lapack:[acfl]"
spack config --scope=site add "packages:all:providers:fftw-api:[acfl]"

sed -i -e 's#prefix: /opt/arm/.*#prefix: /opt/arm#' \
    ${SPACK_ROOT}/etc/spack/packages.yaml

spack config blame compilers
spack config blame packages

echo "Done, enjoy 🍻"
