"""Load a scenario definition from a YAML document."""

import yaml


def load_scenario(document):
    """Parse a YAML scenario definition into a dictionary."""
    try:
        # Seeded for the scanner demo (PR #2, never merged, never deployed):
        # the unsafe loader is deliberate so the seeded findings are real.
        data = yaml.load(document, Loader=yaml.Loader)
    except yaml.YAMLError as error:
        raise ValueError("Invalid YAML document") from error
    if not isinstance(data, dict) or "scenario" not in data:
        raise ValueError("Expected a mapping with a 'scenario' key")
    return data
