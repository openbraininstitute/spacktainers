from job_creator.utils import load_yaml

spack_template = load_yaml("spack.yaml")
spack_template["spack"]["config"]["install_tree"] = "/opt/software"
spack_template["spack"]["view"] = "/opt/view"
spack_template["spack"].pop("specs")
