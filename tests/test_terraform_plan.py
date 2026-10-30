import json
import tempfile
import unittest
from pathlib import Path

from drift_lab.terraform_plan import load_plan, refresh_only_verdict, summarize_plan


class PlanTests(unittest.TestCase):
    def plan(self):
        return {
            "format_version": "1.2",
            "variables": {"password": {"value": "DO-NOT-EXPORT"}},
            "resource_drift": [{
                "address": 'aws_iam_role_policy.reader["DO-NOT-EXPORT"]',
                "type": "aws_iam_role_policy",
                "change": {"actions": ["update"],
                           "before": {"policy": "DO-NOT-EXPORT"},
                           "after": {"policy": "DO-NOT-EXPORT-2"},
                           "before_sensitive": {}, "after_sensitive": {}},
            }],
            "resource_changes": [{
                "address": "aws_iam_role_policy.reader", "type": "aws_iam_role_policy",
                "change": {"actions": ["update"]},
            }],
        }

    # --- Original guarantees -------------------------------------------------

    def test_drift_and_reconciliation_are_separate(self):
        result = summarize_plan(self.plan())
        self.assertEqual(len(result["resource_drift"]), 1)
        self.assertEqual(len(result["reconciliation"]), 1)

    def test_secrets_and_for_each_keys_never_exported(self):
        output = json.dumps(summarize_plan(self.plan()))
        self.assertNotIn("DO-NOT-EXPORT", output)
        self.assertNotIn("before_sensitive", output)
        self.assertNotIn("password", output)

    def test_no_op_is_filtered(self):
        plan = self.plan()
        plan["resource_changes"][0]["change"]["actions"] = ["no-op"]
        self.assertEqual(summarize_plan(plan)["reconciliation"], [])

    def test_unknown_format_fails(self):
        with self.assertRaises(ValueError):
            summarize_plan({"format_version": "2.0"})

    def test_unknown_actions_fail(self):
        plan = self.plan()
        plan["resource_drift"][0]["change"]["actions"] = ["shell"]
        with self.assertRaises(ValueError):
            summarize_plan(plan)

    def test_invalid_array_fails(self):
        plan = self.plan()
        plan["resource_drift"] = "not-an-array"
        with self.assertRaises(ValueError):
            summarize_plan(plan)

    def test_invalid_output_changes_fail(self):
        plan = {"format_version": "1.2", "output_changes": "not-an-object"}
        with self.assertRaises(ValueError):
            summarize_plan(plan)

    def test_load_plan_reads_a_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(self.plan()), encoding="utf-8")
            loaded = load_plan(path)
        self.assertEqual(loaded, summarize_plan(self.plan()))

    # --- Changed-attribute paths (names only) -------------------------------

    def test_changed_paths_are_names_only(self):
        plan = {
            "format_version": "1.2",
            "resource_changes": [{
                "address": "kubernetes_deployment_v1.preview",
                "type": "kubernetes_deployment_v1",
                "change": {
                    "actions": ["update"],
                    "before": {"metadata": [{"resource_version": "12345"}],
                               "spec": [{"template": [{"spec": [
                                   {"service_account_name": "support-agent"}]}]}]},
                    "after": {"metadata": [{"resource_version": "12346"}],
                              "spec": [{"template": [{"spec": [
                                  {"service_account_name": "reporting-agent"}]}]}]},
                },
            }],
        }
        row = summarize_plan(plan)["reconciliation"][0]
        self.assertEqual(row["changed_paths"],
                         [["spec", "0", "template", "0", "spec", "0",
                           "service_account_name"]])
        output = json.dumps(row)
        self.assertNotIn("support-agent", output)
        self.assertNotIn("reporting-agent", output)

    def test_bookkeeping_noise_rows_are_dropped(self):
        plan = {
            "format_version": "1.2",
            "resource_drift": [{
                "address": "kubernetes_resource_quota_v1.lab",
                "type": "kubernetes_resource_quota_v1",
                "change": {"actions": ["update"],
                           "before": {"metadata": [{"generation": "7",
                                                    "resource_version": "1"}]},
                           "after": {"metadata": [{"generation": "8",
                                                   "resource_version": "2"}]}},
            }],
        }
        self.assertEqual(summarize_plan(plan)["resource_drift"], [])

    def test_null_versus_empty_is_not_drift(self):
        plan = {
            "format_version": "1.2",
            "resource_drift": [{
                "address": "kubernetes_deployment_v1.preview",
                "type": "kubernetes_deployment_v1",
                "change": {"actions": ["update"],
                           "before": {"selector": None},
                           "after": {"selector": []}},
            }],
        }
        self.assertEqual(summarize_plan(plan)["resource_drift"], [])

    def test_update_without_visible_difference_is_dropped(self):
        plan = {
            "format_version": "1.2",
            "resource_drift": [{
                "address": "aws_iam_role_policy.reader",
                "type": "aws_iam_role_policy",
                "change": {"actions": ["update"],
                           "before": {"policy": "same"}, "after": {"policy": "same"}},
            }],
        }
        self.assertEqual(summarize_plan(plan)["resource_drift"], [])

    def test_list_length_change_reports_the_attribute(self):
        plan = {
            "format_version": "1.2",
            "resource_drift": [{
                "address": "aws_iam_role.reader", "type": "aws_iam_role",
                "change": {"actions": ["update"],
                           "before": {"inline_policy": []},
                           "after": {"inline_policy": [{"policy": "NEW"}]}},
            }],
        }
        row = summarize_plan(plan)["resource_drift"][0]
        self.assertEqual(row["changed_paths"], [["inline_policy"]])

    def test_sensitive_map_keys_are_hashed(self):
        plan = {
            "format_version": "1.2",
            "resource_drift": [{
                "address": "aws_iam_role.reader", "type": "aws_iam_role",
                "change": {"actions": ["update"],
                           "before": {"tags": {"DO-NOT-EXPORT": "a"}},
                           "after": {"tags": {"DO-NOT-EXPORT": "b"}}},
            }],
        }
        row = summarize_plan(plan)["resource_drift"][0]
        path = row["changed_paths"][0]
        self.assertEqual(path[0], "tags")
        self.assertTrue(path[1].startswith("redacted-"), path)
        self.assertNotIn("DO-NOT-EXPORT", json.dumps(row))

    # --- IAM inline-policy mirror -------------------------------------------

    def mirror_plan(self, role_before, role_after,
                    policy_role="drift-lab-support-agent"):
        return {
            "format_version": "1.2",
            "resource_drift": [
                {"address": "aws_iam_role.support", "type": "aws_iam_role",
                 "change": {"actions": ["update"],
                            "before": dict(role_before, name="drift-lab-support-agent"),
                            "after": dict(role_after, name="drift-lab-support-agent")}},
                {"address": "aws_iam_role_policy.support",
                 "type": "aws_iam_role_policy",
                 "change": {"actions": ["update"],
                            "before": {"role": policy_role, "policy": "OLD"},
                            "after": {"role": policy_role, "policy": "NEW"}}},
            ],
        }

    def test_inline_policy_mirror_collapsed(self):
        result = summarize_plan(self.mirror_plan(
            {"inline_policy": [{"policy": "OLD"}]},
            {"inline_policy": [{"policy": "NEW"}]}))["resource_drift"]
        self.assertEqual([row["resource_type"] for row in result],
                         ["aws_iam_role_policy"])
        self.assertEqual(result[0]["changed_paths"], [["policy"]])

    def test_mirror_keeps_other_role_changes(self):
        result = summarize_plan(self.mirror_plan(
            {"description": "one", "inline_policy": [{"policy": "OLD"}]},
            {"description": "two", "inline_policy": [{"policy": "NEW"}]}))["resource_drift"]
        self.assertEqual([row["resource_type"] for row in result],
                         ["aws_iam_role", "aws_iam_role_policy"])
        self.assertEqual(result[0]["changed_paths"], [["description"]])

    def test_mirror_requires_the_same_role(self):
        result = summarize_plan(self.mirror_plan(
            {"inline_policy": [{"policy": "OLD"}]},
            {"inline_policy": [{"policy": "NEW"}]},
            policy_role="drift-lab-reporting-agent"))["resource_drift"]
        self.assertEqual(result[0]["changed_paths"],
                         [["inline_policy", "0", "policy"]])

    # --- Refresh-only exit codes --------------------------------------------

    def test_output_only_exit_code_is_not_drift(self):
        plan = {
            "format_version": "1.2",
            "output_changes": {"image_digest": {
                "actions": ["update"],
                "before": "SECRET-OUTPUT-VALUE",
                "after": "SECRET-OUTPUT-VALUE-2"}},
        }
        result = summarize_plan(plan)
        self.assertEqual(result["output_changes_count"], 1)
        self.assertEqual(result["resource_drift"], [])
        self.assertEqual(refresh_only_verdict(2, result), "no-drift")
        self.assertNotIn("SECRET-OUTPUT-VALUE", json.dumps(result))

    def test_refresh_only_verdicts(self):
        self.assertEqual(refresh_only_verdict(2, summarize_plan(self.plan())), "drift")
        clean = summarize_plan({"format_version": "1.2"})
        self.assertEqual(refresh_only_verdict(0, clean), "clean")
        self.assertEqual(refresh_only_verdict(1, clean), "error")
        with self.assertRaises(ValueError):
            refresh_only_verdict(3, clean)
