import copy
import logging
import logging.config
import os
import urllib

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

    def __init__(self, include=None, rules=None, variables=None):
        self.stages = []
        self.jobs = []
        self.include = include or []
        self.rules = rules or []
        self.variables = variables or {}

    def add_include(self, include):
        if include not in self.include:
            self.include.append(include)

    def add_stage(self, stage):
        if stage not in self.stages:
            self.stages.append(stage)

    def _add_joblike(self, add_type, joblike, replace=False):
        if joblike.name in self:
            logger.debug(f"{add_type.capitalize()} {joblike.name} already in workflow")
            return
        self.jobs.append(joblike)
        if joblike.stage:
            self.add_stage(joblike.stage)

    def add_job(self, job, special_spack_treatment=False):
        """
        Add a job to the workflow

        :param job: the Job object to add
        :param special_spack_treatment: when merging spack pipelines, we'll encounter duplicate
                                        jobs. In this case, we'll want the job in the earliest
                                        possible stage.

        """
        replace = False
        if (
            job.name in self
            and not job.name.startswith("rebuild-index")
            and special_spack_treatment
        ):
            logger.debug(f"Job {job.name} already in workflow, special spack treatment set")
            existing_job = self.get_job(job.name)[0]
            existing_stage_number = int(existing_job.stage.split("-")[1])
            new_stage_number = int(job.stage.split("-")[1])
            if new_stage_number < existing_stage_number:
                logger.debug(
                    f"Stage {new_stage_number} < {existing_stage_number} - replacing"
                )
                replace = True
            elif new_stage_number == existing_stage_number:
                logger.debug(
                    f"Stage {existing_stage_number} == {new_stage_number} - not replacing"
                )
            else:
                logger.debug(
                    f"Stage {existing_stage_number} < {new_stage_number} - not replacing"
                )
        self._add_joblike("job", job, replace)

    def get_job(self, job_name, startswith=False):
        """
        Return a job with a given name, if it's present in the workflow

        :param startswith: if set to True, return a list of jobs whose names start with the given string
        """

        retval = None

        if startswith:
            retval = [job for job in self.jobs if job.name.startswith(job_name)]
        else:
            retval = [job for job in self.jobs if job.name == job_name]

        return retval

    def add_trigger(self, trigger):
        self._add_joblike("trigger", trigger)

    def to_dict(self):
        as_dict = {"stages": self.stages} if self.stages else {}
        as_dict.update({job.name: job.to_dict() for job in self.jobs})
        if self.include:
            as_dict["include"] = self.include
        if self.rules:
            as_dict["workflow"] = {"rules": self.rules}
        if self.variables:
            as_dict["variables"] = self.variables
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
        my_stages = copy.deepcopy(self.stages)
        other_stages = copy.deepcopy(other.stages)
        if set(my_stages).issubset(set(other_stages)):
            new.stages = other_stages
        else:
            new.stages = self._dedup(my_stages + other_stages)

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

        my_stages = copy.deepcopy(self.stages)
        other_stages = copy.deepcopy(other.stages)
        if set(my_stages).issubset(set(other_stages)):
            self.stages = other_stages
        else:
            for stage in other.stages:
                self.add_stage(stage)
        for other_job in other.jobs:
            self.add_job(other_job)
        for other_include in other.include:
            self.add_include(other_include)

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
        force_needs=False,
        needs=None,
        script=None,
        stage=None,
        artifacts=None,
        before_script=None,
        variables=None,
        timeout=None,
        bucket="cache",
        rules=None,
        append_arch=True,
        **kwargs,
    ):
        """
        :param bucket: set to either "cache" to use the cache bucket,
                       or "infra" to use the infra bucket
        """
        self.force_needs = force_needs
        self.extra_properties = []
        self.name = name
        self.tags = []
        self.needs = needs or []
        self.script = script
        self.stage = stage
        self.artifacts = artifacts
        self.before_script = before_script if before_script else []
        self.variables = variables or {}
        self.timeout = timeout
        self.rules = rules or []
        self.image = None
        self._bucket = bucket
        for key, value in kwargs.items():
            logger.debug(f"Setting {key}: {value}")
            self.extra_properties.append(key)
            setattr(self, key, value)
        self.set_architecture(architecture, append_arch)

    def set_architecture(self, architecture=None, append_arch=True):
        if architecture:
            if append_arch:
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

    def configure_s3cmd(self):
        """
        * determine proxy
        * determine access keys
        """
        if not self.architecture:
            raise NoArchitecture(
                f"Cannot configure s3cmd - no architecture specified for {self.name}"
            )

        script_lines = []
        if architecture_map[self.architecture].get("proxy", False):
            proxy = urllib.parse.urlsplit(os.environ["HTTP_PROXY"])
            proxy_host = proxy.hostname
            proxy_port = proxy.port
            script_lines += [
                f"sed -i 's/^proxy_host.*/proxy_host={proxy_host}/' /root/.s3cfg",
                f"sed -i 's/^proxy_port.*/proxy_port={proxy_port}/' /root/.s3cfg",
            ]

        if bucket_keypair := architecture_map[self.architecture][self.bucket_key].get(
            "keypair_variables"
        ):
            script_lines += [
                f"sed -i 's/^access_key.*/access_key='${bucket_keypair['access_key']}'/' /root/.s3cfg",
                f"sed -i 's/^secret_key.*/secret_key='${bucket_keypair['secret_key']}'/' /root/.s3cfg",
            ]

        self.update_before_script(script_lines, append=True)

    @property
    def bucket_key(self):
        if self._bucket == "cache":
            return "cache_bucket"
        elif self._bucket == "infra":
            return "containers_bucket"
        else:
            raise ValueError(f"Don't know what to do with bucket {self._bucket}")

    def set_aws_variables(self):
        if not self.architecture:
            raise NoArchitecture(
                f"Cannot set AWS variables - no architecture specified for {self.name}"
            )

        script_lines = []

        if bucket_keypair := architecture_map[self.architecture][self.bucket_key].get(
            "keypair_variables"
        ):
            script_lines = [
                f"export AWS_ACCESS_KEY_ID=${bucket_keypair['access_key']}",
                f"export AWS_SECRET_ACCESS_KEY=${bucket_keypair['secret_key']}",
            ]
        else:
            logger.info(f"No keypair defined for {self.architecture}")
        if endpoint_url := architecture_map[self.architecture][self.bucket_key].get(
            "endpoint_url"
        ):
            script_lines.append(f"export S3_ENDPOINT_URL={endpoint_url}")

        self.update_before_script(script_lines)

    def add_need(self, need):
        if need not in self.needs:
            self.needs.append(need)

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
            if prop_name == "needs" and self.force_needs:
                return {"needs": []}
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
            "image",
            "timeout",
            "rules",
        ] + self.extra_properties:
            as_dict.update(self._property_as_dict(prop_name))

        return as_dict

    def __repr__(self):
        return f"<Job> {self.name}"


class Trigger:
    def __init__(
        self, name, trigger, needs=None, stage=None, architecture=None, rules=None
    ):
        self.name = name
        if architecture:
            self.name += f" for {architecture}"

        self.trigger = trigger
        self.needs = needs
        self.stage = stage
        self.rules = rules or []

    def to_dict(self):
        as_dict = {"trigger": self.trigger}
        if self.needs:
            as_dict["needs"] = self.needs
        if self.stage:
            as_dict["stage"] = self.stage
        if self.rules:
            as_dict["rules"] = self.rules

        return as_dict
