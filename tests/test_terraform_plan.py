import json
import unittest

from drift_lab.terraform_plan import summarize_plan


class PlanTests(unittest.TestCase):
    def plan(self):
        return {
            "format_version": "1.2",
            "variables": {"password": {"value": "DO-NOT-EXPORT"}},
            "resource_drift": [{
                "address": 'aws_iam_role_policy.reader["DO-NOT-EXPORT"]',
                "type": "aws_iam_role_policy",
                "change": {"actions": ["update"], "before": {"secret": "DO-NOT-EXPORT"},
                           "after": {"secret": "DO-NOT-EXPORT"},
                           "before_sensitive": {}, "after_sensitive": {}},
            }],
            "resource_changes": [{
                "address": "aws_iam_role_policy.reader", "type": "aws_iam_role_policy",
                "change": {"actions": ["update"]},
            }],
        }

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
