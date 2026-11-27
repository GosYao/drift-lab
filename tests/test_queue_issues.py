import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import queue_issues
import triage_queue
from test_triage_queue import CODE, SHIPPED, DEV_ONLY, RUN, evidence


def queue():
    return triage_queue.structured_queue(evidence([CODE, SHIPPED, DEV_ONLY]),
        dict(RUN, text="1. #1 fix now: request input reaches it.\n"
                      "2. #2 schedule: affected function not called.\n"
                      "3. #3 backlog: never ships.\n"))


class GitHub:
    def __init__(self):
        self.issues, self.labels, self.writes = [], {}, []

    def __call__(self, path, method="GET", payload=None, paginate=False):
        if method == "GET":
            return [copy.deepcopy(self.issues if "/issues?" in path else
                                  [{"name": name} for name in self.labels])]
        self.writes.append((method, path, payload))
        if path.endswith("/labels"):
            self.labels[payload["name"]] = payload["color"]
            return payload
        if method == "POST":
            issue = {"number": len(self.issues) + 1, "state": "open",
                     "html_url": "https://github.com/GosYao/drift-lab/issues/5"}
            self.issues.append(issue)
        else:
            issue = next(item for item in self.issues
                         if str(item["number"]) == path.rsplit("/", 1)[-1])
        issue.update(payload, labels=[{"name": name} for name in payload["labels"]])
        return copy.deepcopy(issue)


class StructuredTests(unittest.TestCase):
    def test_structured_output_preserves_severities_and_provenance(self):
        data = queue()
        queue_issues.validate(data)
        self.assertEqual([row["severity"] for row in data["findings"]],
                         ["ERROR", "CRITICAL", "CRITICAL"])
        self.assertEqual([row["urgency"] for row in data["findings"]],
                         ["fix now", "schedule", "backlog"])
        self.assertNotIn("text", data)

    def test_identity_ignores_line_version_rank_and_commit_but_not_file_or_branch(self):
        self.assertEqual(triage_queue.finding_id(CODE),
                         triage_queue.finding_id(dict(CODE, location="drift_lab/loader.py:99")))
        self.assertEqual(triage_queue.finding_id(SHIPPED),
                         triage_queue.finding_id(dict(SHIPPED,
                             location="requirements.txt (PyYAML 6.0.4)")))
        self.assertNotEqual(triage_queue.finding_id(SHIPPED),
                            triage_queue.finding_id(dict(SHIPPED,
                                location="tools/dev/requirements.txt (PyYAML 5.3.1)")))
        policy = dict(CODE, location="policy:3 on `a`")
        self.assertNotEqual(triage_queue.finding_id(policy),
                            triage_queue.finding_id(dict(policy, location="policy:3 on `b`")))

    def test_bad_model_output_becomes_unranked_in_both_formats(self):
        run = dict(RUN, text="looks fine")
        data = triage_queue.structured_queue(evidence([CODE]), run)
        queue_issues.validate(data)
        text, ok = triage_queue.compose(evidence([CODE]), run)
        self.assertFalse(ok)
        self.assertFalse(data["ranked"])
        self.assertEqual(data["findings"][0]["urgency"], "unranked")
        self.assertIn(triage_queue.UNRANKED, text)
        self.assertIn(triage_queue.UNRANKED, data["findings"][0]["reason"])

    def test_empty_queue_is_valid_in_both_formats(self):
        data = triage_queue.structured_queue(evidence([]), RUN)
        queue_issues.validate(data)
        text, ok = triage_queue.compose(evidence([]), RUN)
        self.assertTrue(ok)
        self.assertEqual(data["findings"], [])

    def test_real_main_writes_json_beside_markdown(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(triage_queue, "ROOT", Path(tmp)), \
                patch.object(triage_queue.triage, "load_droid",
                             return_value=({"model": "m"}, "instructions")), \
                patch.object(triage_queue, "gather", return_value=evidence([CODE])), \
                patch.object(triage_queue.triage, "run_droid",
                             return_value=dict(RUN, text="1. #1 fix now: reachable.")):
            out = Path(tmp) / "queue.md"
            self.assertEqual(triage_queue.main(["--out", str(out)]), 0)
            data = json.loads(out.with_suffix(".json").read_text())
            queue_issues.validate(data)
            self.assertIn("fix now", out.read_text())


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.data, self.api = queue(), GitHub()

    def test_preview_makes_no_calls(self):
        result = queue_issues.publish(self.data, call=self.api)
        self.assertTrue(all(row["action"] == "preview" for row in result))
        self.assertEqual(self.api.writes, [])

    def test_publish_then_rerun_makes_no_new_issues_or_writes(self):
        first = queue_issues.publish(self.data, call=self.api, write=True)
        self.assertEqual([row["action"] for row in first], ["created"] * 3)
        self.api.writes.clear()
        second = queue_issues.publish(self.data, call=self.api, write=True)
        self.assertEqual([row["action"] for row in second], ["unchanged"] * 3)
        self.assertEqual(self.api.writes, [])

    def test_ranking_change_updates_only_managed_labels_and_preserves_comments(self):
        queue_issues.publish(self.data, call=self.api, write=True)
        self.api.issues[0]["labels"].append({"name": "reviewed"})
        self.api.issues[0]["comments"] = 2
        self.data["findings"][0]["urgency"] = "fix soon"
        self.api.writes.clear()
        result = queue_issues.publish(self.data, call=self.api, write=True)
        self.assertEqual(result[0]["action"], "updated")
        self.assertEqual({label["name"] for label in self.api.issues[0]["labels"]},
                         {"security queue", "fix soon", "reviewed"})
        self.assertEqual(self.api.issues[0]["comments"], 2)
        self.assertTrue(all("state" not in payload for _, _, payload in self.api.writes))

    def test_closed_or_absent_findings_are_never_reopened_or_closed(self):
        queue_issues.publish(self.data, call=self.api, write=True)
        self.api.issues[0]["state"] = "closed"
        self.data["findings"].pop()
        self.api.writes.clear()
        result = queue_issues.publish(self.data, call=self.api, write=True)
        self.assertEqual(result[0]["action"], "kept closed")
        self.assertEqual(len(self.api.issues), 3)
        self.assertEqual(self.api.issues[2]["state"], "open")
        self.assertEqual(self.api.writes, [])

    def test_duplicate_input_and_duplicate_remote_markers_fail_before_writes(self):
        invalid = copy.deepcopy(self.data)
        invalid["findings"][1]["id"] = invalid["findings"][0]["id"]
        with self.assertRaises(ValueError):
            queue_issues.publish(invalid, call=self.api, write=True)
        self.assertEqual(self.api.writes, [])
        queue_issues.publish(self.data, call=self.api, write=True)
        self.api.issues.append(copy.deepcopy(self.api.issues[0]))
        self.api.writes.clear()
        with self.assertRaises(ValueError):
            queue_issues.publish(self.data, call=self.api, write=True)
        self.assertEqual(self.api.writes, [])

    def test_malformed_later_row_is_rejected_before_any_write(self):
        self.data["findings"][-1]["urgency"] = "dismissed"
        with self.assertRaises(ValueError):
            queue_issues.publish(self.data, call=self.api, write=True)
        self.assertEqual(self.api.writes, [])

    def test_partial_publish_rerun_does_not_duplicate_completed_issue(self):
        def fail(path, **kwargs):
            if kwargs.get("method") == "POST" and path.endswith("/issues") and self.api.issues:
                raise RuntimeError("network failed")
            return self.api(path, **kwargs)
        with self.assertRaises(RuntimeError):
            queue_issues.publish(self.data, call=fail, write=True)
        result = queue_issues.publish(self.data, call=self.api, write=True)
        self.assertEqual([row["action"] for row in result], ["unchanged", "created", "created"])
        self.assertEqual(len(self.api.issues), 3)

    def test_source_and_recorded_facts_are_visible_without_raw_outputs(self):
        self.data["findings"][0]["facts"] = ["Recorded 2026-10-30, not collected again."]
        body = queue_issues.issue_body(self.data, self.data["findings"][0])
        self.assertIn("Recorded 2026-10-30, not collected again.", body)
        self.assertIn("Severity from the source: **ERROR**, unchanged.", body)
        self.assertIn("A person decides.", body)


if __name__ == "__main__":
    unittest.main()
