import json
from copy import deepcopy
from pathlib import Path
import unittest

from drift_lab.collector import (CliRunner, CollectorError, collect_exit_code,
                                 collect_snapshot, compare_with_baseline,
                                 validate_config)
from drift_lab.scenarios import baseline

CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "collector.json"
STAMP = "2026-10-30T18:00:00Z"
# Deliberately fake coordination value; never a real account.
ACCOUNT = "123456789012"
IMAGE_DIGEST = "sha256:" + "a" * 64
IMAGE = (ACCOUNT + ".dkr.ecr.ca-central-1.amazonaws.com"
         + "/drift-lab-preview@" + IMAGE_DIGEST)


def table_arn(table):
    return "arn:aws:dynamodb:ca-central-1:" + ACCOUNT + ":table/drift-lab-" + table


def policy_document(*tables, actions=("dynamodb:GetItem", "dynamodb:Query")):
    return {"Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": list(actions),
                           "Resource": [table_arn(table) for table in tables]}]}


def role_arn(name):
    return "arn:aws:iam::" + ACCOUNT + ":role/drift-lab-" + name


class FakeRunner:
    """Offline stand-in for the CLI runner; never a live collection."""

    def __init__(self, policies=None, associations=None, deployment=None,
                 failures=()):
        self.policies = policies or {
            "drift-lab-support-agent": policy_document("customer-orders"),
            "drift-lab-reporting-agent": policy_document("customer-orders",
                                                         "customer-archive"),
        }
        self.associations = associations or {
            "support-agent": role_arn("support-agent"),
            "reporting-agent": role_arn("reporting-agent"),
        }
        self.pod_spec = deployment or {
            "service_account": "support-agent", "replicas": 1, "image": IMAGE,
        }
        self.failures = set(failures)

    def role_policy_document(self, role_name, policy_name):
        if "iam:" + role_name in self.failures:
            raise CollectorError("iam:get-role-policy", "denied")
        return deepcopy(self.policies[role_name])

    def pod_identity_role_arn(self, cluster_name, namespace, service_account):
        if "eks:" + service_account in self.failures:
            raise CollectorError("eks:describe-pod-identity-association", "denied")
        return self.associations[service_account]

    def deployment(self, namespace, deployment_name):
        if "k8s:deployment" in self.failures:
            raise CollectorError("kubectl:get-deployment", "denied")
        return deepcopy(self.pod_spec)


def lab_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


class CollectorTests(unittest.TestCase):
    def collect(self, runner=None, observed_at=STAMP):
        return collect_snapshot(lab_config(), runner or FakeRunner(), observed_at)

    def test_clean_collection_validates_and_stays_clean(self):
        first = self.collect()
        second = self.collect(observed_at="2026-10-30T18:05:00Z")
        self.assertEqual(first["collection"]["status"], "complete")
        self.assertEqual(collect_exit_code(first), 0)
        report = compare_with_baseline(first, second)
        self.assertEqual(report["status"], "no_security_drift_observed")
        self.assertEqual(collect_exit_code(report), 0)

    def test_snapshot_is_sanitized(self):
        snapshot = self.collect()
        output = json.dumps(snapshot)
        self.assertNotIn("arn:aws", output)
        self.assertNotIn(ACCOUNT, output)
        self.assertNotIn("PolicyDocument", output)
        deployment = next(item for item in snapshot["resources"]
                          if item["kind"] == "deployment")
        self.assertEqual(deployment["attributes"]["image"],
                         "drift-lab-preview@" + IMAGE_DIGEST)

    def test_committed_config_matches_the_fixture_topology(self):
        fixture = {item["id"]: item["attributes"]
                   for item in baseline()["resources"]}
        collected = {item["id"]: item["attributes"]
                     for item in self.collect()["resources"]}
        for identifier, attributes in fixture.items():
            observed = collected[identifier]
            if identifier == "deployment:support":
                self.assertEqual(observed["service_account"],
                                 attributes["service_account"])
                continue
            if "read_tables" in observed:
                # The engine normalizes grant order; the collector emits sorted.
                self.assertEqual(sorted(observed["read_tables"]),
                                 sorted(attributes["read_tables"]))
                continue
            self.assertEqual(observed, attributes)

    def test_iam_drift_is_detected(self):
        runner = FakeRunner(policies={
            "drift-lab-support-agent": policy_document("customer-orders",
                                                       "customer-archive"),
            "drift-lab-reporting-agent": policy_document("customer-orders",
                                                         "customer-archive")})
        report = compare_with_baseline(self.collect(), self.collect(runner))
        finding = next(f for f in report["findings"]
                       if f["field"] == "read_tables")
        self.assertEqual(finding["title"], "IAM read scope expanded")
        self.assertEqual(finding["severity"], "high")
        self.assertEqual(collect_exit_code(report), 2)
        self.assertNotIn(ACCOUNT, json.dumps(report))

    def test_identity_drift_is_detected(self):
        runner = FakeRunner(deployment={"service_account": "reporting-agent",
                                        "replicas": 1, "image": IMAGE})
        report = compare_with_baseline(self.collect(), self.collect(runner))
        finding = next(f for f in report["findings"]
                       if f["field"] == "service_account")
        self.assertEqual(finding["title"], "Workload identity changed")
        edges = report["graph"]["edges"]
        self.assertTrue(any(e["state"] == "added" and e["target"] == "sa:reporting"
                            for e in edges))
        self.assertTrue(any(e["state"] == "removed" and e["target"] == "sa:support"
                            for e in edges))

    def test_failed_reads_are_incomplete_not_deletions(self):
        snapshot = self.collect(runner=FakeRunner(
            failures={"iam:drift-lab-support-agent"}))
        self.assertEqual(snapshot["collection"]["status"], "incomplete")
        self.assertTrue(snapshot["collection"]["errors"])
        self.assertNotIn("role:support",
                        {item["id"] for item in snapshot["resources"]})
        report = compare_with_baseline(self.collect(), snapshot)
        self.assertEqual(report["status"], "inconclusive")
        self.assertEqual(collect_exit_code(report), 3)
        node = next(n for n in report["graph"]["nodes"]
                    if n["id"] == "role:support")
        self.assertEqual(node["state"], "unobserved")
        self.assertIn("Resource could not be observed",
                      {f["title"] for f in report["findings"]})

    def test_grants_outside_the_read_model_fail_closed(self):
        runner = FakeRunner(policies={
            "drift-lab-support-agent": policy_document(
                "customer-orders",
                actions=("dynamodb:GetItem", "dynamodb:PutItem")),
            "drift-lab-reporting-agent": policy_document("customer-orders",
                                                         "customer-archive")})
        snapshot = self.collect(runner=runner)
        self.assertEqual(snapshot["collection"]["status"], "incomplete")
        self.assertTrue(any("read-only" in error
                            for error in snapshot["collection"]["errors"]))
        self.assertNotIn("role:support",
                        {item["id"] for item in snapshot["resources"]})

    def test_unmapped_grants_fail_closed(self):
        wildcard = {"Version": "2012-10-17",
                    "Statement": [{"Effect": "Allow",
                                   "Action": "dynamodb:GetItem",
                                   "Resource": table_arn("*")}]}
        unmapped = policy_document("unknown-table")
        for document in (wildcard, unmapped):
            runner = FakeRunner(policies={
                "drift-lab-support-agent": document,
                "drift-lab-reporting-agent": policy_document("customer-orders",
                                                             "customer-archive")})
            snapshot = self.collect(runner=runner)
            self.assertEqual(snapshot["collection"]["status"], "incomplete")
            self.assertTrue(any("mapped table set" in error for error in
                                snapshot["collection"]["errors"]))
        runner = FakeRunner(associations={
            "support-agent": role_arn("support-agent"),
            "reporting-agent": role_arn("admin")})
        snapshot = self.collect(runner=runner)
        self.assertEqual(snapshot["collection"]["status"], "incomplete")
        self.assertTrue(any("mapped role set" in error for error in
                            snapshot["collection"]["errors"]))
        runner = FakeRunner(deployment={"service_account": "default",
                                        "replicas": 1, "image": IMAGE})
        snapshot = self.collect(runner=runner)
        self.assertEqual(snapshot["collection"]["status"], "incomplete")
        self.assertTrue(any("outside the mapped set" in error for error in
                            snapshot["collection"]["errors"]))

    def test_cli_runner_builds_read_only_commands(self):
        runner = CliRunner(profile="demo-admin", region="ca-central-1",
                           kubeconfig="/tmp/drift-kubeconfig")
        self.assertEqual(runner.role_policy_argv("r", "policy"),
                         ["aws", "iam", "get-role-policy", "--role-name", "r",
                          "--policy-name", "policy", "--output", "json"])
        self.assertEqual(runner.pod_identity_list_argv("cluster", "ns", "sa"),
                         ["aws", "eks", "list-pod-identity-associations",
                          "--cluster-name", "cluster", "--namespace", "ns",
                          "--service-account", "sa", "--output", "json"])
        self.assertEqual(runner.pod_identity_describe_argv("cluster", "assoc-1"),
                         ["aws", "eks", "describe-pod-identity-association",
                          "--cluster-name", "cluster", "--association-id",
                          "assoc-1", "--output", "json"])
        self.assertEqual(runner.deployment_argv("ns", "deploy"),
                         ["kubectl", "get", "deployment", "deploy", "-n", "ns",
                          "-o", "json"])
        env = runner.build_env()
        self.assertEqual(env["AWS_PROFILE"], "demo-admin")
        self.assertEqual(env["AWS_REGION"], "ca-central-1")
        self.assertEqual(env["KUBECONFIG"], "/tmp/drift-kubeconfig")

    def test_exit_codes(self):
        self.assertEqual(collect_exit_code({"collection": {"status": "complete"}}), 0)
        self.assertEqual(collect_exit_code({"collection": {"status": "incomplete"}}), 3)
        self.assertEqual(collect_exit_code(
            {"findings": [], "status": "no_security_drift_observed"}), 0)
        self.assertEqual(collect_exit_code(
            {"findings": [1], "status": "review_required"}), 2)
        self.assertEqual(collect_exit_code(
            {"findings": [1], "status": "inconclusive"}), 3)

    def test_incomplete_baseline_is_rejected(self):
        incomplete = self.collect(runner=FakeRunner(
            failures={"iam:drift-lab-support-agent"}))
        with self.assertRaises(ValueError):
            compare_with_baseline(incomplete, self.collect())

    def test_config_validation_rejects_bad_configs(self):
        config = lab_config()
        config.pop("cluster_name")
        with self.assertRaises(ValueError):
            validate_config(config)
        config = lab_config()
        config["tables"][0]["id"] = config["tables"][1]["id"]
        with self.assertRaises(ValueError):
            validate_config(config)
        config = lab_config()
        config["policy"]["approved_replica_range"] = [4, 1]
        with self.assertRaises(ValueError):
            validate_config(config)
        config = lab_config()
        config["read_actions"] = []
        with self.assertRaises(ValueError):
            validate_config(config)


if __name__ == "__main__":
    unittest.main()
