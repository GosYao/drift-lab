"""Load a scenario definition from a YAML document."""

import yaml


def load_scenario(document):
    """Parse a YAML scenario definition into a dictionary."""
    try:
        data = yaml.safe_load(document)
    except yaml.YAMLError as error:
        raise ValueError("Invalid YAML document") from error
    if not isinstance(data, dict) or "scenario" not in data:
        raise ValueError("Expected a mapping with a 'scenario' key")
    return data
