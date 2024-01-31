import glob
import logging
import logging.config
import os

import ruamel.yaml

from job_creator.logging_config import LOGGING_CONFIG

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("job_creator")


class NonAliasingRoundTripRepresenter(ruamel.yaml.representer.RoundTripRepresenter):
    def ignore_aliases(self, data):
        return True


def load_yaml(path):
    yaml = ruamel.yaml.YAML(typ="safe")
    with open(path, "r") as fp:
        loaded = yaml.load(fp)

    return loaded


def write_yaml(content, path):
    yaml = ruamel.yaml.YAML()
    yaml.Representer = NonAliasingRoundTripRepresenter
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 120
    yaml.default_flow_style = False
    yaml.default_style = '"'
    with open(path, "w") as fp:
        yaml.dump(content, fp)


def merge_dicts(a, b, path=None):
    """Merges b into a

    :param a: dict to merge into
    :param b: dict to merge into a
    :param path: where we are in the merge, for error reporting

    :returns: dictionary a with values from b merged in
    :rtype: dict
    """
    path = [] if path is None else path
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                merge_dicts(a[key], b[key], path + [str(key)])
            elif a[key] == b[key]:
                pass  # same leaf value
            elif isinstance(a[key], list) and isinstance(b[key], list):
                a[key].extend(b[key])
            else:
                raise Exception("Conflict at %s" % ".".join(path + [str(key)]))
        else:
            a[key] = b[key]
    return a


def get_architectures():
    """
    Retrieve the architectures that need to be built based on the container definitions
    """
    architectures = [
        os.path.basename(archdir) for archdir in glob.glob("container_definitions/*")
    ]

    return architectures


def get_arch_or_multiarch_job(workflow, architecture, container_name="builder"):
    """
    Given a workflow and the name of a container (in practise, this will usually be builder),
    this method will return a list with either the build job or, if applicable, the multiarch job.
    If the container doesn't need to be built, will return an empty list
    """

    multiarch_job_name = f"create multiarch for {container_name}"
    builder_job_name = f"build {container_name}"

    logger.debug(f"Getting {container_name} build jobs in {workflow.jobs}")
    if multiarch_jobs := workflow.get_job(multiarch_job_name):
        logger.debug(f"Multi-arch jobs found: {multiarch_jobs}")
        return multiarch_jobs
    elif build_jobs := workflow.get_job(builder_job_name):
        logger.debug(f"Build jobs found: {build_jobs}")
        return build_jobs
    else:
        return []
