# Spacktainerizah


## Containers Built With Spack Packages

After having deployed our software on BB5 as modules for a long time, the move to the cloud calls for a different way of deploying software: containers. They offer more flexibility and will tie us less strongly to any specific cloud provider.

This repository aims to be the one-stop shop for all of our container needs.

## Components From Original Repositories

* [Spacktainerizer](https://bbpgitlab.epfl.ch/hpc/spacktainerizer/): the base image which contains our spack fork
* [Singularitah](https://bbpgitlab.epfl.ch/hpc/personal/heeren/singularitah): arm64 container with singularity (and s3cmd) installation for sif manipulation on arm nodes
* [Spack-cacher](https://bbpgitlab.epfl.ch/hpc/spack-cacher): builds spack packages and puts them in a build cache
* [Spackitor](https://bbpgitlab.epfl.ch/hpc/spackitor): cleans the build cache: anything that is too old or no longer used gets removed
* [Spackah](https://bbpgitlab.epfl.ch/hpc/spackah): builds the actual containers

## Stages

1. base containers
   * Build runtime / builder
   * Build singularitah
2. packages
   * Build cache
3. containers
   * Build containers
   * Publish containers
4. cleanup
   * spackitor. Can run immediately after build packages stage

## CI/CD Variables

* `AWS_CACHE_ACCESS_KEY_ID` / `AWS_CACHE_SECRET_ACCESS_KEY`: AWS keypair for accessing the cache bucket hosted by Amazon
* `BBP_CACHE_ACCESS_KEY_ID` / `BBP_CACHE_SECRET_ACCESS_KEY`: AWS keypair for accessing the cache bucket hosted by BBP
* `SPACK_DEPLOYMENT_KEY_PUBLIC`: the Spack public deployment key (as a file!)
* `DOCKERHUB_USER` / `DOCKERHUB_PASSWORD`: credentials for docker hub
* `GITLAB_API_TOKEN`: private (!) gitlab token with API_READ access (CI_JOB_TOKEN does not have enough permissions). Change this once I'm gone

## Base containers

* [Singularitah](bbpgitlab.epfl.ch:5050/hpc/spacktainerizah/singularitah)
* [Builder](bbpgitlab.epfl.ch:5050/hpc/spacktainerizah/builder)
* [Runner](bbpgitlab.epfl.ch:5050/hpc/spacktainerizah/runtime)
