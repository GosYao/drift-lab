"""Synthetic snapshots. These are deliberately not represented as live observations."""

from copy import deepcopy

STAMP = "2026-10-29T12:00:00Z"

SCENARIOS = [
    {"id": "iam", "name": "IAM permission drift", "description":
     "A support role gains read access to a second synthetic dataset."},
    {"id": "identity", "name": "Kubernetes identity drift", "description":
     "The Deployment switches to the reporting ServiceAccount."},
    {"id": "scaling", "name": "Expected scaling change", "description":
     "Replicas increase within the approved one-to-four range."},
    {"id": "incomplete", "name": "Incomplete collection", "description":
     "The IAM collector cannot inspect the current policy."},
    {"id": "clean", "name": "Approved baseline", "description":
     "All collected attributes match the approved snapshot."},
]


def resource(identifier, kind, name, attributes, path):
    return {
        "id": identifier, "kind": kind, "name": name, "attributes": attributes,
        "evidence": {"source": "synthetic-fixture", "reference": path,
                     "observed_at": STAMP},
    }


def baseline():
    return {
        "schema_version": 1,
        "environment": "eks-security-lab",
        "mode": "fixture",
        "observed_at": STAMP,
        "deployment": {
            "revision": "fixture:approved-v1", "state_version": "fixture:state-v7",
            "image_digest": "fixture:approved-image", "region": "us-east-1",
        },
        "collection": {"status": "complete", "errors": []},
        "resources": [
            resource("tool:lookup", "agent_tool", "lookup_order",
                     {"workload": "deployment:support", "source":
                      "sample-app/tools.py:lookup_order"}, "fixture://tool/lookup"),
            resource("deployment:support", "deployment", "support-agent",
                     {"service_account": "sa:support", "replicas": 2,
                      "image": "fixture:approved-image"},
                     "fixture://kubernetes/deployment/support-agent"),
            resource("sa:support", "service_account", "support-agent",
                     {"role": "role:support"}, "fixture://eks/pod-identity/support"),
            resource("sa:reporting", "service_account", "reporting-agent",
                     {"role": "role:reporting"}, "fixture://eks/pod-identity/reporting"),
            resource("role:support", "iam_role", "support-reader",
                     {"read_tables": ["table:orders"]}, "fixture://iam/support-reader"),
            resource("role:reporting", "iam_role", "reporting-reader",
                     {"read_tables": ["table:orders", "table:archive"]},
                     "fixture://iam/reporting-reader"),
            resource("table:orders", "dataset", "customer-orders",
                     {"classification": "synthetic", "tenant": "customer-a"},
                     "fixture://dynamodb/customer-orders"),
            resource("table:archive", "dataset", "customer-archive",
                     {"classification": "synthetic", "tenant": "customer-b"},
                     "fixture://dynamodb/customer-archive"),
        ],
        "policy": {"approved_replica_range": [1, 4],
                   "forbidden_dataset": "table:archive",
                   "principal_tool": "tool:lookup"},
    }


def scenario(identifier):
    if identifier not in {item["id"] for item in SCENARIOS}:
        raise ValueError("Unknown scenario")
    expected = baseline()
    observed = deepcopy(expected)
    resources = {item["id"]: item for item in observed["resources"]}
    if identifier == "iam":
        resources["role:support"]["attributes"]["read_tables"].append("table:archive")
    elif identifier == "identity":
        resources["deployment:support"]["attributes"]["service_account"] = "sa:reporting"
    elif identifier == "scaling":
        resources["deployment:support"]["attributes"]["replicas"] = 3
    elif identifier == "incomplete":
        observed["resources"] = [item for item in observed["resources"]
                                 if item["id"] != "role:support"]
        observed["collection"] = {
            "status": "incomplete",
            "errors": ["AccessDenied: synthetic IAM observation is unavailable."],
        }
    return expected, observed
