import ruamel.yaml


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
