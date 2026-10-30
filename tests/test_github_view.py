"""Contract checks for the GitHub fixture previews.

These payloads are templates, not GitHub API responses. The tests keep the
fixtures honest: previews must declare they are fixtures, cite the same
deterministic finding IDs as the drift engine, and stay renderable.
"""

import json
import unittest

from drift_lab.engine import compare
from drift_lab.github_view import TRIGGERS, preview
from drift_lab.scenarios import scenario


def body_blocks(payload):
    if payload["kind"] == "pull_request":
        return (payload["review"]["summary_comment"]["body"]
                + [block for comment in payload["review"]["inline"]
                   for block in comment["body"]])
    if payload["kind"] == "push":
        return [block for commit in payload["push"]["commits"]
                for comment in commit["comments"] for block in comment["body"]]
    return (payload["issue"]["body"]
            + [block for comment in payload["comments"] for block in comment["body"]])


def check_runs(payload):
    if payload["kind"] == "pull_request":
        return payload["checks"]["runs"]
    if payload["kind"] == "push":
        return [run for commit in payload["push"]["commits"]
                for run in commit["checks"]["runs"]]
    return []


class GithubViewTests(unittest.TestCase):
    def test_every_trigger_renders(self):
        for trigger in TRIGGERS:
            payload = preview(trigger["id"])
            self.assertEqual(payload["trigger"]["id"], trigger["id"])
            self.assertTrue(payload["frame"]["description"])
        with self.assertRaises(ValueError):
            preview("bogus")

    def test_previews_declare_their_boundaries(self):
        for trigger in TRIGGERS:
            payload = preview(trigger["id"])
            self.assertTrue(payload["preview"]["fixture"])
            self.assertIn("No GitHub API call", payload["preview"]["note"])
            self.assertFalse(payload["analysis"]["model_invoked"])

    def test_pr_inline_comment_anchors_to_a_real_diff_line(self):
        payload = preview("pr")
        for comment in payload["review"]["inline"]:
            file = next(item for item in payload["diff"]["files"]
                        if item["path"] == comment["path"])
            lines = [line for hunk in file["hunks"] for line in hunk["lines"]]
            self.assertTrue(any(line["origin"] != "-"
                                and line["new_line"] == comment["line"]
                                for line in lines))

    def test_pr_cites_the_same_finding_as_the_drift_report(self):
        report = compare(*scenario("iam"))
        payload = preview("pr")
        rendered = json.dumps(payload)
        for finding in report["findings"]:
            self.assertIn(finding["id"], rendered)

    def test_push_shows_every_check_state(self):
        payload = preview("push")
        runs = check_runs(payload)
        statuses = {run["status"] for run in runs}
        conclusions = {run["conclusion"] for run in runs}
        self.assertIn("completed", statuses)
        self.assertIn("in_progress", statuses)
        self.assertIn("success", conclusions)
        self.assertIn("failure", conclusions)

    def test_check_run_shape(self):
        for trigger in TRIGGERS:
            for run in check_runs(preview(trigger["id"])):
                if run["status"] == "completed":
                    self.assertIn(run["conclusion"], {"success", "failure"})
                else:
                    self.assertIsNone(run["conclusion"])
                self.assertTrue(run["name"] and run["summary"])

    def test_body_blocks_use_supported_kinds(self):
        for trigger in TRIGGERS:
            for block in body_blocks(preview(trigger["id"])):
                self.assertIn(block["kind"], {"paragraph", "list", "code"})

    def test_scheduled_issue_carries_drift_evidence(self):
        report = compare(*scenario("iam"))
        payload = preview("scheduled")
        rendered = json.dumps(payload["issue"])
        self.assertIn(report["findings"][0]["id"], rendered)
        self.assertTrue(payload["issue"]["labels"])
        self.assertEqual(payload["source_scenario"], "iam")


if __name__ == "__main__":
    unittest.main()
