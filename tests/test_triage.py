import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import triage  # noqa: E402

FINDING = {"scanner": "semgrep", "rule": "avoid-pyyaml-load", "severity": "ERROR",
           "location": "drift_lab/scenario_import.py:12", "key": "k1",
           "title": "Unsafe YAML load", "message": "yaml.load with the unsafe Loader."}
CVE = {"scanner": "trivy", "rule": "CVE-2020-14343", "severity": "CRITICAL",
       "location": "requirements.txt (PyYAML 5.3.1)", "key": "k2", "title": "PyYAML RCE",
       "message": "full_load and FullLoader are affected.", "fixed": "5.4"}
EVIDENCE = {
    "branch": "feature/scenarios-from-yaml", "head": "abc1234", "base": "def5678",
    "dirty": False, "pull_request": {"number": "2", "title": "Load scenarios from YAML",
                                     "author": "GosYao"},
    "results": [{"scanner": "semgrep", "label": "semgrep", "status": "findings",
                 "findings": [FINDING], "detail": ""},
                {"scanner": "trivy", "label": "trivy", "status": "findings",
                 "findings": [CVE], "detail": ""}],
    "findings": [FINDING, CVE],
    "gates": [{"name": "make check", "exit": 0, "output": "ok", "skipped": ""},
              {"name": "make policy-test", "exit": None, "output": "",
               "skipped": "infra/ unchanged"}],
    "exposure": {"status": "computed", "facts": [
        "This change touches code that runs in Deployment `support-agent`.",
        "No other branch on the remote changes that role's policy."]},
    "fix_evidence": "", "stat": " 2 files changed", "diff": "diff --git ...",
    "untracked": [],
}
PACKETS = """Intro line.

### 1. semgrep `avoid-pyyaml-load`

- **Recommendation:** true positive. Request input reaches the unsafe loader.
- **Class:** code
- **Reachability:** drift_lab/server.py:88 calls it with the request body.

### 2. trivy `CVE-2020-14343`

- **Recommendation:** true positive. The vulnerable version is pinned.
- **Class:** dependency

VERDICT: request changes
"""


def run_dict(**overrides):
    run = {"ok": True, "text": PACKETS, "requested": "gemini-3.8-flash",
           "model": "gemini-3.8-flash", "effort": "medium", "credits": 210,
           "seconds": 42, "turns": 5, "session": "s-1", "error": ""}
    run.update(overrides)
    return run


class ContractTests(unittest.TestCase):
    def test_the_repository_droid_file_satisfies_the_contract(self):
        self.assertEqual(triage.droid_contract(ROOT / triage.DROID_FILE), [])

    def test_contract_catches_a_weakened_droid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "triage.md"
            path.write_text("---\nname: triage\nmodel: inherit\n---\nDo triage.\n")
            problems = triage.droid_contract(path)
        self.assertIn("tools must be read-only", problems)
        self.assertIn("the model must be named, not inherited", problems)
        self.assertTrue(any("VERDICT: request changes" in p for p in problems))


class ParseTests(unittest.TestCase):
    def test_policy_findings_names_the_failed_run_and_its_assertion(self):
        output = (
            "policy.tftest.hcl... in progress\n"
            '  run "support_agent_reads_only_orders"... fail\n'
            "\n"
            "Error: Test assertion failed\n"
            "\n"
            "  on policy.tftest.hcl line 69, in run \"support_agent_reads_only_orders\":\n"
            "  69:     condition     = jsondecode(aws_iam_role_policy.agent\n"
            "\x1b[0m\x1b[1m\u2502 Warning: LHS and RHS values are of different types\n"
            "\n"
            "support-agent must read only the customer-orders table.\n"
            '  run "reporting_agent_reads_orders_and_archive"... pass\n'
            "policy.tftest.hcl... fail\n\nFailure! 4 passed, 1 failed.\n")
        finding, = triage.policy_findings(output)
        self.assertEqual(finding["rule"], "support_agent_reads_only_orders")
        self.assertEqual(finding["location"], "infra/workloads/policy.tftest.hcl:69")
        self.assertEqual(finding["title"],
                         "support-agent must read only the customer-orders table.")
        self.assertIn("jsondecode(", finding["message"])

    def test_a_clean_policy_run_yields_no_findings(self):
        self.assertEqual(triage.policy_findings(
            '  run "a"... pass\n  run "b"... pass\nSuccess! 2 passed, 0 failed.\n'), [])

    def test_a_scanner_result_that_did_not_arrive_is_an_error_not_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            results = triage.scanner_results(ROOT, directory)
        self.assertTrue(all(r["status"] == "error" for r in results))
        self.assertIn("did not reach the review step", results[0]["detail"])

    def test_scanner_results_read_the_pipeline_files(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, result in (("semgrep", triage.scanner_results.__name__ and
                                  {"scanner": "semgrep", "label": "semgrep",
                                   "status": "findings", "findings": [FINDING],
                                   "detail": ""}),
                                 ("trivy", {"scanner": "trivy", "label": "trivy",
                                            "status": "clean", "findings": [],
                                            "detail": ""})):
                (Path(directory) / (name + ".json")).write_text(json.dumps(result))
            semgrep, trivy_result = triage.scanner_results(ROOT, directory)
        self.assertEqual(semgrep["findings"], [FINDING])
        self.assertEqual(trivy_result["status"], "clean")


class ReviewTests(unittest.TestCase):
    def test_review_problems_accepts_a_matching_review(self):
        self.assertEqual(triage.review_problems(PACKETS, [FINDING, CVE]), ("", []))

    def test_a_packet_without_a_recommendation_is_unusable(self):
        text = PACKETS.replace("- **Recommendation:** true positive. The vulnerable "
                               "version is pinned.\n", "")
        problem, missing = triage.review_problems(text, [FINDING, CVE])
        self.assertEqual(problem, "")
        self.assertEqual(missing, [CVE])

    def test_a_verdict_that_contradicts_the_gates_is_unusable(self):
        text = PACKETS.replace("VERDICT: request changes", "VERDICT: no issues found")
        problem, missing = triage.review_problems(text, [FINDING, CVE])
        self.assertIn("contradicts", problem)
        self.assertEqual(missing, [FINDING, CVE])

    def test_missing_and_doubled_verdicts_are_unusable(self):
        for text in (PACKETS.replace("VERDICT: request changes\n", ""),
                     PACKETS + "VERDICT: comment\n"):
            problem, _ = triage.review_problems(text, [])
            self.assertIn("VERDICT", problem)

    def test_a_numbered_heading_for_the_wrong_rule_does_not_count(self):
        text = PACKETS.replace("`CVE-2020-14343`", "`something-else`")
        _, missing = triage.review_problems(text, [FINDING, CVE])
        self.assertEqual(missing, [CVE])

    def test_compose_layers_model_text_then_computed_evidence(self):
        review, usable = triage.compose(EVIDENCE, run_dict())
        self.assertTrue(usable)
        self.assertTrue(review.startswith("## Review packet: #2 Load scenarios from YAML"))
        self.assertIn(PACKETS.strip(), review)
        self.assertLess(review.index("VERDICT: request changes"),
                        review.index("### Computed evidence (not model output)"))
        self.assertIn("| 1 | semgrep `avoid-pyyaml-load` | ERROR |", review)
        self.assertIn("**Chained exposure**", review)
        self.assertIn("`gemini-3.8-flash`, named in `.factory/droids/triage.md`", review)
        self.assertIn("42 s, 5 turns, 210 Factory credits", review)

    def test_compose_fails_safe_when_the_model_fails(self):
        review, usable = triage.compose(
            EVIDENCE, run_dict(ok=False, text="", error="droid exec exited 1: boom"))
        self.assertFalse(usable)
        self.assertIn("**Triage unavailable, human review required.**", review)
        self.assertIn("- 1. semgrep `avoid-pyyaml-load`: Triage unavailable, human review "
                      "required. It keeps the severity its gate reported: ERROR.", review)
        self.assertIn("2. trivy `CVE-2020-14343`", review)
        self.assertIn("CRITICAL", review)
        self.assertIn("droid exec exited 1: boom", review)
        self.assertIn("### Computed evidence", review)

    def test_compose_keeps_a_finding_without_a_usable_packet_visible(self):
        text = PACKETS.replace("`CVE-2020-14343`", "`something-else`")
        review, usable = triage.compose(EVIDENCE, run_dict(text=text))
        self.assertTrue(usable)
        self.assertIn("**No usable packet for:**", review)
        self.assertIn("2. trivy `CVE-2020-14343`: Triage unavailable", review)
        self.assertIn("VERDICT: request changes", review)

    def test_model_line_reports_a_substituted_model(self):
        line = triage.model_line(run_dict(model="claude-haiku-5-5", credits=None))
        self.assertIn("`gemini-3.8-flash`, named in", line)
        self.assertIn("The run reported `claude-haiku-5-5` instead.", line)
        self.assertNotIn("credits", line)


class DroidRunTests(unittest.TestCase):
    def fake_droid(self, directory, script):
        path = Path(directory) / "droid"
        path.write_text("#!/bin/sh\n" + script)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return str(path)

    def test_run_droid_parses_the_stream(self):
        events = [
            {"type": "system", "subtype": "init", "model": "gemini-3.8-flash",
             "reasoning_effort": "medium", "session_id": "s-1"},
            {"type": "tool_call", "toolId": "Script", "toolName": "Script",
             "parameters": {"script": "const r = await tools.Read({ file_path: "
                                      "'/repo/Makefile' });\ntext(r);"}},
            {"type": "completion", "finalText": "the review",
             "numTurns": 3, "usage": {"factory_credits": 99}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            payload = "".join(json.dumps(event) + "\n" for event in events)
            binary = self.fake_droid(directory, "cat <<'JSON'\n" + payload + "JSON\n")
            said = []
            run = triage.run_droid("prompt.md", "gemini-3.8-flash", "medium", ROOT,
                                   binary=binary, say=said.append)
        self.assertTrue(run["ok"])
        self.assertEqual(run["model"], "gemini-3.8-flash")
        self.assertEqual((run["credits"], run["turns"]), (99, 3))
        self.assertEqual(run["text"], "the review")
        self.assertIn("$ droid exec --model gemini-3.8-flash", said[0])
        self.assertIn("model gemini-3.8-flash · reasoning medium · read-only", said[1])
        self.assertIn("Read /repo/Makefile", said[2])

    def test_run_droid_reports_failures_and_never_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            exits = self.fake_droid(directory, "echo 'something broke' >&2\nexit 7\n")
            run = triage.run_droid("prompt.md", "m", None, ROOT, binary=exits,
                                   say=lambda line: None)
            self.assertFalse(run["ok"])
            self.assertIn("exited 7", run["error"])
            self.assertIn("something broke", run["error"])

            hangs = self.fake_droid(directory, "sleep 30\n")
            run = triage.run_droid("prompt.md", "m", None, ROOT, timeout=0.5,
                                   binary=hangs, say=lambda line: None)
            self.assertFalse(run["ok"])
            self.assertIn("timed out", run["error"])

            empty = self.fake_droid(directory, "exit 0\n")
            run = triage.run_droid("prompt.md", "m", None, ROOT, binary=empty,
                                   say=lambda line: None)
            self.assertEqual(run["error"], "the model returned no text")

        with mock.patch.object(triage, "droid_binary", return_value=None):
            run = triage.run_droid("prompt.md", "m", None, ROOT)
        self.assertEqual(run["error"], "the droid CLI is not installed")


class EvidenceTextTests(unittest.TestCase):
    def test_evidence_for_model_lists_every_finding_with_its_source(self):
        text = triage.evidence_for_model(EVIDENCE)
        self.assertIn("1. semgrep `avoid-pyyaml-load`", text)
        self.assertIn("- location: drift_lab/scenario_import.py:12", text)
        self.assertIn("2. trivy `CVE-2020-14343`", text)
        self.assertIn("- fixed in: 5.4", text)
        self.assertIn("## Chained exposure", text)
        self.assertIn("No other branch on the remote changes that role's policy.", text)
        self.assertIn("`make policy-test`: not run, infra/ unchanged", text)

    def test_evidence_for_reviewer_never_claims_a_clean_scan_for_an_error(self):
        evidence = dict(EVIDENCE, results=[
            {"scanner": "trivy", "label": "trivy", "status": "error", "findings": [],
             "detail": "docker is not available"}])
        text = triage.evidence_for_reviewer(evidence)
        self.assertIn("could not run (docker is not available); this is not a clean scan",
                      text)
        self.assertNotIn("no findings", text)


if __name__ == "__main__":
    unittest.main()
