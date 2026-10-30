"""Read-only live collector for the deployed drift lab.

Maps three fixed, read-only queries onto the engine's sanitized-observation
schema: the IAM inline policies of the lab's two agent roles, their EKS Pod
Identity associations, and the preview Deployment. Raw CLI output, ARNs,
account IDs, and policy statements never leave this module; the emitted
snapshot carries only allowlisted schema attributes. The collector never
writes, applies, or reconciles anything.
"""

from datetime import datetime, timezone
import json
import os
import subprocess

from .engine import compare, validate


class CollectorError(Exception):
    """A read failed. `reason` is a safe bucket, never the raw CLI output."""

    def __init__(self, read, reason):
        super().__init__(read + " unavailable: " + reason)
        self.read = read
        self.reason = reason


def _classify(stderr):
    """Bucket CLI failures without echoing CLI text into any report."""
    text = (stderr or "").lower()
    if ("nosuchentity" in text or "notfound" in text or "not found" in text
            or "does not exist" in text or "no such" in text):
        return "not-found"
    if ("accessdenied" in text or "denied" in text or "forbidden" in text
            or "unauthorized" in text):
        return "denied"
    return "failed"


class CliRunner:
    """Runs the three read-only CLI queries. Injectable for tests.

    Commands are fixed argv lists: no shell, no user-supplied fragments.
    """

    def __init__(self, profile=None, region=None, kubeconfig=None):
        self.profile = profile
        self.region = region
        self.kubeconfig = kubeconfig

    def build_env(self):
        env = None
        for key, value in (("AWS_PROFILE", self.profile),
                           ("AWS_REGION", self.region),
                           ("KUBECONFIG", self.kubeconfig)):
            if value:
                env = dict(os.environ) if env is None else env
                env[key] = value
        return env

    def _run(self, read, argv):
        try:
            result = subprocess.run(argv, capture_output=True, text=True,
                                    timeout=120, env=self.build_env())
        except (OSError, subprocess.TimeoutExpired):
            raise CollectorError(read, "unavailable") from None
        if result.returncode != 0:
            raise CollectorError(read, _classify(result.stderr))
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise CollectorError(read, "unreadable") from None

    def role_policy_argv(self, role_name, policy_name):
        return ["aws", "iam", "get-role-policy", "--role-name", role_name,
                "--policy-name", policy_name, "--output", "json"]

    def pod_identity_list_argv(self, cluster_name, namespace, service_account):
        return ["aws", "eks", "list-pod-identity-associations",
                "--cluster-name", cluster_name, "--namespace", namespace,
                "--service-account", service_account, "--output", "json"]

    def pod_identity_describe_argv(self, cluster_name, association_id):
        return ["aws", "eks", "describe-pod-identity-association",
                "--cluster-name", cluster_name, "--association-id",
                association_id, "--output", "json"]

    def deployment_argv(self, namespace, deployment_name):
        return ["kubectl", "get", "deployment", deployment_name,
                "-n", namespace, "-o", "json"]

    def role_policy_document(self, role_name, policy_name):
        data = self._run("iam:get-role-policy",
                         self.role_policy_argv(role_name, policy_name))
        document = data.get("PolicyDocument") if isinstance(data, dict) else None
        if not isinstance(document, dict):
            raise CollectorError("iam:get-role-policy", "unreadable")
        return document

    def pod_identity_role_arn(self, cluster_name, namespace, service_account):
        """List the service account's association, then describe it for the ARN.

        The EKS API only supports describe-by-association-id.
        """
        listed = self._run("eks:list-pod-identity-associations",
                           self.pod_identity_list_argv(cluster_name, namespace,
                                                       service_account))
        associations = listed.get("associations") if isinstance(listed, dict) else None
        if not isinstance(associations, list):
            raise CollectorError("eks:list-pod-identity-associations", "unreadable")
        if not associations:
            raise CollectorError("eks:list-pod-identity-associations", "not-found")
        if len(associations) > 1 or not isinstance(associations[0], dict):
            raise CollectorError("eks:list-pod-identity-associations",
                                 "ambiguous" if associations else "unreadable")
        identifier = associations[0].get("associationId")
        if not isinstance(identifier, str) or not identifier:
            raise CollectorError("eks:list-pod-identity-associations", "unreadable")
        described = self._run("eks:describe-pod-identity-association",
                              self.pod_identity_describe_argv(cluster_name, identifier))
        detail = described.get("association") if isinstance(described, dict) else None
        role_arn = detail.get("roleArn") if isinstance(detail, dict) else None
        if not isinstance(role_arn, str) or not role_arn:
            raise CollectorError("eks:describe-pod-identity-association", "unreadable")
        return role_arn

    def deployment(self, namespace, deployment_name):
        data = self._run("kubectl:get-deployment",
                         self.deployment_argv(namespace, deployment_name))
        try:
            spec = data["spec"]["template"]["spec"]
            return {"service_account": spec["serviceAccountName"],
                    "replicas": data["spec"].get("replicas", 1),
                    "image": spec["containers"][0]["image"]}
        except (KeyError, IndexError, TypeError):
            raise CollectorError("kubectl:get-deployment", "unreadable") from None


def _require(condition, message):
    if not condition:
        raise ValueError("Collector config: " + message)


def validate_config(config):
    """Fail closed on a config that cannot describe the lab topology."""
    _require(isinstance(config, dict), "must be an object")
    for key in ("environment", "region", "cluster_name", "namespace",
                "approved_revision"):
        _require(isinstance(config.get(key), str) and config[key],
                 key + " is required")
    deployment = config.get("deployment")
    _require(isinstance(deployment, dict), "deployment is required")
    _require(isinstance(deployment.get("id"), str)
             and isinstance(deployment.get("name"), str),
             "deployment id and name are required")
    tool = config.get("agent_tool")
    _require(isinstance(tool, dict), "agent_tool is required")
    _require(all(isinstance(tool.get(key), str) and tool[key]
                 for key in ("id", "name", "workload", "source")),
             "agent_tool id, name, workload and source are required")
    for key in ("service_accounts", "roles", "tables"):
        entries = config.get(key)
        _require(isinstance(entries, list) and entries,
                 key + " must be a non-empty list")
        _require(all(isinstance(entry, dict) for entry in entries),
                 key + " entries must be objects")
        identifiers = [entry.get("id") for entry in entries]
        names = [entry.get("name") for entry in entries]
        _require(all(isinstance(value, str) and value for value in identifiers),
                 key + " ids must be strings")
        _require(all(isinstance(value, str) and value for value in names),
                 key + " names must be strings")
        _require(len(set(identifiers)) == len(identifiers),
                 key + " ids must be unique")
        _require(len(set(names)) == len(names), key + " names must be unique")
    _require(all(isinstance(entry.get(key), str) and entry[key]
                 for entry in config["service_accounts"]
                 for key in ("id", "name")),
             "service accounts need id and name")
    _require(all(isinstance(entry.get(key), str) and entry[key]
                 for entry in config["roles"]
                 for key in ("id", "name", "display", "policy_name")),
             "roles need id, name, display and policy_name")
    _require(all(isinstance(entry.get(key), str) and entry[key]
                 for entry in config["tables"]
                 for key in ("id", "name", "classification", "tenant")),
             "tables need id, name, classification and tenant")
    actions = config.get("read_actions")
    _require(isinstance(actions, list) and actions
             and all(isinstance(action, str) and action for action in actions),
             "read_actions must be a non-empty list")
    policy = config.get("policy")
    _require(isinstance(policy, dict), "policy is required")
    allowed_range = policy.get("approved_replica_range")
    _require(isinstance(allowed_range, list) and len(allowed_range) == 2
             and all(type(value) is int for value in allowed_range)
             and allowed_range[0] <= allowed_range[1],
             "policy.approved_replica_range must be [low, high]")
    identifiers = ([deployment["id"], tool["id"]]
                   + [entry["id"] for entry in config["service_accounts"]]
                   + [entry["id"] for entry in config["roles"]]
                   + [entry["id"] for entry in config["tables"]])
    _require(len(set(identifiers)) == len(identifiers),
             "resource ids must be unique across the lab")
    return config


def _dataset_for(resource, tables, cluster_name):
    for table in tables:
        if resource.endswith("/" + cluster_name + "-" + table["name"]):
            return table["id"]
    return None


def _policy_tables(document, config):
    """Configured datasets a policy grants configured read actions on.

    Returns (ids, problems). Grants outside the read-only model, conditioned
    grants, negated grants, and unmapped resources become problems: the
    collector never fabricates a dataset and never silently drops a grant.
    """
    tables = config["tables"]
    read_actions = set(config["read_actions"])
    problems = []
    granted = set()
    statements = document.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list):
        return [], ["aws-iam: policy statement shape is unreadable"]
    for statement in statements:
        if not isinstance(statement, dict):
            problems.append("aws-iam: policy statement shape is unreadable")
            continue
        if "Condition" in statement:
            problems.append("aws-iam: policy conditions are outside the read-only model")
        if "NotAction" in statement or "NotResource" in statement:
            problems.append("aws-iam: policy negation is outside the read-only model")
        if statement.get("Effect") != "Allow":
            continue
        actions = statement.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        if not isinstance(actions, list) or not actions:
            problems.append("aws-iam: policy statement shape is unreadable")
            continue
        resources = statement.get("Resource", [])
        if isinstance(resources, str):
            resources = [resources]
        if not isinstance(resources, list):
            problems.append("aws-iam: policy statement shape is unreadable")
            continue
        if any(not isinstance(action, str) or action not in read_actions
               for action in actions):
            problems.append("aws-iam: policy grants actions outside the read-only model")
        mapped = []
        for resource in resources:
            if not isinstance(resource, str):
                problems.append("aws-iam: policy resource shape is unreadable")
                continue
            dataset = _dataset_for(resource, tables, config["cluster_name"])
            if dataset is None:
                problems.append("aws-iam: policy grants a resource outside the mapped table set")
            else:
                mapped.append(dataset)
        if mapped and all(isinstance(action, str) and action in read_actions
                          for action in actions):
            granted.update(mapped)
    return sorted(granted), problems


def _normalize_image(image):
    """Keep repository@digest; drop registry and account information."""
    return image.rsplit("/", 1)[-1]


def _timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _agent_tool(config, observed_at):
    tool = config["agent_tool"]
    return {"id": tool["id"], "kind": "agent_tool", "name": tool["name"],
            "attributes": {"workload": tool["workload"],
                           "source": tool["source"]},
            "evidence": {"source": "collector-config",
                         "reference": "declared lab capability; not a live read",
                         "observed_at": observed_at}}


def _datasets(config, observed_at):
    return [{"id": table["id"], "kind": "dataset", "name": table["name"],
             "attributes": {"classification": table["classification"],
                            "tenant": table["tenant"]},
             "evidence": {"source": "collector-config",
                          "reference": "lab dataset registry; not a live read",
                          "observed_at": observed_at}}
            for table in config["tables"]]


def _role(config, role, runner, observed_at, errors):
    full_name = config["cluster_name"] + "-" + role["name"]
    try:
        document = runner.role_policy_document(full_name, role["policy_name"])
    except CollectorError as error:
        errors.append(str(error))
        return []
    granted, problems = _policy_tables(document, config)
    errors.extend(problems)
    if problems:
        return []
    return [{"id": role["id"], "kind": "iam_role", "name": role["display"],
             "attributes": {"read_tables": granted},
             "evidence": {"source": "aws-iam",
                          "reference": "get-role-policy " + full_name
                                       + "/" + role["policy_name"],
                          "observed_at": observed_at}}]


def _service_account(config, account, runner, observed_at, errors):
    try:
        role_arn = runner.pod_identity_role_arn(config["cluster_name"],
                                                config["namespace"],
                                                account["name"])
    except CollectorError as error:
        errors.append(str(error))
        return []
    role_ids = {config["cluster_name"] + "-" + entry["name"]: entry["id"]
                for entry in config["roles"]}
    role_id = role_ids.get(role_arn.rsplit("/", 1)[-1])
    if role_id is None:
        errors.append("aws-eks: pod identity association points outside the mapped role set")
        return []
    return [{"id": account["id"], "kind": "service_account",
             "name": account["name"],
             "attributes": {"role": role_id},
             "evidence": {"source": "aws-eks",
                          "reference": "describe-pod-identity-association "
                                       + config["namespace"] + "/" + account["name"],
                          "observed_at": observed_at}}]


def _deployment(config, runner, observed_at, errors):
    try:
        pod = runner.deployment(config["namespace"],
                                 config["deployment"]["name"])
    except CollectorError as error:
        errors.append(str(error))
        return []
    account_ids = {entry["name"]: entry["id"]
                   for entry in config["service_accounts"]}
    account_id = account_ids.get(pod["service_account"])
    if account_id is None:
        errors.append("kubernetes: deployment service account is outside the mapped set")
        return []
    replicas = pod["replicas"]
    if type(replicas) is not int or replicas < 0:
        errors.append("kubernetes: deployment replica count is invalid")
        return []
    return [{"id": config["deployment"]["id"], "kind": "deployment",
             "name": config["deployment"]["name"],
             "attributes": {"service_account": account_id,
                            "replicas": replicas,
                            "image": _normalize_image(pod["image"])},
             "evidence": {"source": "kubectl",
                          "reference": "get deployment "
                                       + config["deployment"]["name"]
                                       + " -n " + config["namespace"],
                          "observed_at": observed_at}}]


def collect_snapshot(config, runner, observed_at=None):
    """Build a sanitized-observation snapshot from live, read-only queries."""
    validate_config(config)
    observed_at = observed_at or _timestamp()
    errors = []
    resources = [_agent_tool(config, observed_at)]
    resources.extend(_datasets(config, observed_at))
    for role in config["roles"]:
        resources.extend(_role(config, role, runner, observed_at, errors))
    for account in config["service_accounts"]:
        resources.extend(_service_account(config, account, runner,
                                          observed_at, errors))
    resources.extend(_deployment(config, runner, observed_at, errors))
    snapshot = {
        "schema_version": 1,
        "environment": config["environment"],
        "mode": "sanitized-observation",
        "observed_at": observed_at,
        "deployment": {"revision": config["approved_revision"],
                       "region": config["region"]},
        "collection": {"status": "incomplete" if errors else "complete",
                       "errors": errors},
        "resources": resources,
        "policy": {"approved_replica_range":
                   config["policy"]["approved_replica_range"]},
    }
    return validate(snapshot)


def compare_with_baseline(baseline, snapshot):
    """Compare a collected snapshot against a collected approved baseline."""
    if baseline.get("collection", {}).get("status") != "complete":
        raise ValueError("Baseline snapshot is incomplete; collect a complete "
                         "approved baseline first")
    return compare(baseline, snapshot)


def collect_exit_code(result):
    """Machine-readable outcome: 0 clean, 2 review required, 3 inconclusive."""
    if "findings" in result:
        return {"no_security_drift_observed": 0, "review_required": 2,
                "inconclusive": 3}[result["status"]]
    return 0 if result["collection"]["status"] == "complete" else 3
