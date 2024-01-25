import copy
import logging
import logging.config

from job_creator.architectures import architecture_map
from job_creator.logging_config import LOGGING_CONFIG

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("job_creator")


class NoArchitecture(Exception):
    pass


class Workflow:
    """
    Gitlab Workflow model
    Make sure to add your jobs/stages in the order they need to execute!
    """

    def __init__(self, include=None):
        self.stages = []
        self.jobs = []
        self.include = include if include else []

    def add_stage(self, stage):
        if stage not in self.stages:
            self.stages.append(stage)

    def _add_joblike(self, add_type, joblike):
        if joblike.name in self:
            logger.debug(f"{add_type.capitalize()} {joblike.name} already in workflow")
            return
        self.jobs.append(joblike)
        if joblike.stage:
            self.add_stage(joblike.stage)
    def add_job(self, job):
        self._add_joblike("job", job)

    def add_trigger(self, trigger):
        self._add_joblike("trigger", trigger)

    def to_dict(self):
        as_dict = {"stages": self.stages}
        as_dict.update({job.name: job.to_dict() for job in self.jobs})
        if self.include:
            as_dict["include"] = self.include
        return as_dict

    def _dedup(self, seq):
        """
        Deduplicate items in a list while keeping order
        See https://stackoverflow.com/questions/480214/how-do-i-remove-duplicates-from-a-list-while-preserving-order
        Will keep the first item
        """
        seen = list()
        seen_append = seen.append
        return [x for x in seq if not (x in seen or seen_append(x))]

    def __add__(self, other):
        if not isinstance(other, Workflow):
            raise TypeError(f"cannot add Workflow and {type(other)}")

        new = Workflow()
        stages = copy.deepcopy(self.stages)
        stages.extend(copy.deepcopy(other.stages))
        stages = self._dedup(stages)
        new.stages = stages

        new.jobs = copy.deepcopy(self.jobs)
        for other_job in other.jobs:
            new.add_job(other_job)

        include = copy.deepcopy(self.include)
        include.extend(copy.deepcopy(other.include))
        include = self._dedup(include)
        new.include = include

        return new

    def __iadd__(self, other):
        if not isinstance(other, Workflow):
            raise TypeError(f"cannot add Workflow and {type(other)}")

        self.stages.extend(other.stages)
        for other_job in other.jobs:
            self.add_job(other_job)
        self.include.extend(other.include)

        return self

    def __contains__(self, item):
        """
        Check whether a specific job name is part of this workflow
        """
        return item in [j.name for j in self.jobs]


class Job:
    def __init__(
        self,
        name,
        architecture=None,
        needs=None,
        script=None,
        stage=None,
        artifacts=None,
        before_script=None,
        variables=None,
        **kwargs,
    ):
        self.extra_properties = []
        self.name = name
        self.tags = []
        self.needs = needs if needs else []
        self.script = script if script else None
        self.stage = stage if stage else None
        self.artifacts = artifacts if artifacts else None
        self.before_script = before_script if before_script else []
        self.variables = variables if variables else {}
        self.image = None
        for key, value in kwargs.items():
            logger.debug(f"Setting {key}: {value}")
            self.extra_properties.append(key)
            setattr(self, key, value)
        self.set_architecture(architecture)

    def set_architecture(self, architecture=None):
        if architecture:
            self.name += f" for {architecture}"
            self.architecture = architecture
            architecture_tag = architecture_map[architecture]["tag"]
            if architecture_tag not in self.tags:
                self.tags.append(architecture_tag)
            self.set_proxy_variables()
            self.set_aws_variables()
        else:
            self.architecture = None

    def set_proxy_variables(self):
        if not architecture_map[self.architecture].get("proxy", True):
            self.update_before_script(
                "unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY"
            )

    def set_aws_variables(self):
        if not self.architecture:
            raise NoArchitecture(
                f"Cannot set AWS variables - no architecture specified for {self.name}"
            )

        script_lines = []
        if bucket_keypair := architecture_map[self.architecture]["cache_bucket"].get(
            "keypair_variables"
        ):
            script_lines = [
                f"export AWS_ACCESS_KEY_ID=${bucket_keypair['access_key']}",
                f"export AWS_SECRET_ACCESS_KEY=${bucket_keypair['secret_key']}",
            ]
        else:
            logger.info(f"No keypair defined for {self.architecture}")
        if endpoint_url := architecture_map[self.architecture]["cache_bucket"].get(
            "endpoint_url"
        ):
            script_lines.append(f"export S3_ENDPOINT_URL={endpoint_url}")

        self.update_before_script(script_lines)

    def update_before_script(self, lines, append=False):
        """
        Set the given lines as the before_script if there isn't one yet
        If append=True, insert the lines at the end
        If append=False, insert the lines at the start
        """
        if isinstance(lines, str):
            lines = [lines]
        if not set(lines).issubset(set(self.before_script)):
            if append:
                self.before_script.extend(lines)
            else:
                self.before_script[0:0] = lines

    def _property_as_dict(self, prop_name):
        if hasattr(self, prop_name) and getattr(self, prop_name):
            return {prop_name: getattr(self, prop_name)}
        else:
            return {}

    def add_spack_mirror(self):
        bucket_info = architecture_map[self.architecture]["cache_bucket"]
        endpoint_url = bucket_info.get("endpoint_url")
        aws_keypair = bucket_info.get("keypair_variables")

        mirror_add_cmd = [
            "spack mirror add",
            f"--s3-access-key-id=${aws_keypair['access_key']}",
            f"--s3-access-key-secret=${aws_keypair['secret_key']}",
            f"--s3-endpoint-url={endpoint_url}" if endpoint_url else "",
            f"s3Cache s3://{bucket_info['name']}",
        ]
        before_script_lines = [
            ". ${SPACK_ROOT}/share/spack/setup-env.sh",
            "spack mirror rm bbpS3 || true",
            " ".join(mirror_add_cmd),
        ]

        self.update_before_script(before_script_lines, append=True)

    def to_dict(self):
        as_dict = {}

        for prop_name in [
            "needs",
            "script",
            "stage",
            "artifacts",
            "tags",
            "before_script",
            "variables",
            "needs",
            "image",
        ] + self.extra_properties:
            as_dict.update(self._property_as_dict(prop_name))

        return as_dict

    def __repr__(self):
        return f"<Job> {self.name}"


class Trigger:
    def __init__(self, name, trigger, needs=None, stage=None, architecture=None):
        self.name = name
        if architecture:
            self.name += f" for {architecture}"

        self.trigger = trigger
        self.needs = needs if needs else None
        self.stage = stage if stage else None

    def to_dict(self):
        as_dict = {"trigger": self.trigger}
        if self.needs:
            as_dict["needs"] = self.needs
        if self.stage:
            as_dict["stage"] = self.stage

        return as_dict
