spack_template = {
    "spack": {
        "packages": {
            "all": {"require": "%gcc@12.3.0", "providers": {"mpi": ["mpich"]}},
        },
        "concretizer": {
            "unify": "when_possible",
            "reuse": False,
            "targets": {"granularity": "generic"},
        },
        "config": {"install_tree": "/opt/software", "build_jobs": 4},
        "view": "/opt/view",
    }
}
