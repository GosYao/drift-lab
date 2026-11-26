import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import verify_fix  # noqa: E402
from verify_fix import ERROR, FAIL, PASS, SKIP, Gate  # noqa: E402


def git(root, *args):
    return subprocess.run(["git", *args], cwd=str(root), check=True,
                          capture_output=True, text=True).stdout


def problems(changes, before, after):
    return verify_fix.suppression_problems(changes, before.get, after.get)


class SuppressionTests(unittest.TestCase):
    def test_new_suppression_is_named_with_its_line(self):
        found = problems({"app.py": "M"},
                         {"app.py": "import yaml\ndata = yaml.load(text)\n"},
                         {"app.py": "import yaml\ndata = yaml.load(text)  # nosemgrep\n"})
        self.assertEqual(found, ['app.py:2 adds a suppression ("nosemgrep")'])

    def test_existing_suppressions_are_not_flagged(self):
        accepted = "run: | # nosemgrep: yaml.github-actions.security.gha-curl-pipe-shell\n"
        self.assertEqual(problems({"deploy.sh": "M"},
                                  {"deploy.sh": accepted + "echo one\n"},
                                  {"deploy.sh": "echo zero\n" + accepted + "echo two\n"}), [])

    def test_a_second_copy_of_an_existing_suppression_is_flagged(self):
        line = "x = 1  # nosemgrep\n"
        found = problems({"app.py": "M"}, {"app.py": line}, {"app.py": line + line})
        self.assertEqual(len(found), 1)

    def test_trivy_markers_and_new_files_count(self):
        found = problems({"infra/main.tf": "A"}, {},
                         {"infra/main.tf": "# trivy:ignore:AVD-AWS-0057\nresource {}\n"})
        self.assertEqual(found, ['infra/main.tf:1 adds a suppression '
                                 '("trivy:ignore:AVD-AWS-0057")'])

    def test_documentation_may_mention_suppressions(self):
        self.assertEqual(problems({"docs/WORKLOG.md": "M"}, {"docs/WORKLOG.md": ""},
                                  {"docs/WORKLOG.md": "Accepted with nosemgrep.\n"}), [])

    def test_the_checks_that_judge_a_fix_may_not_change(self):
        judges = [".semgrepignore", ".trivyignore", "trivy.yaml", "Makefile",
                  ".github/workflows/pull-request.yml", ".factory/hooks.json",
                  "scripts/scanners.py", "scripts/verify_fix.py",
                  "infra/workloads/policy.tftest.hcl"]
        found = problems(dict.fromkeys(judges, "M"), {}, {})
        self.assertEqual(len(found), len(judges))
        self.assertTrue(all("may not change the checks" in item for item in found))

    def test_removed_or_weakened_tests_are_flagged(self):
        before = ("def test_one(self):\n    self.assertEqual(a, 1)\n"
                  "def test_two(self):\n    self.assertTrue(b)\n")
        after = "def test_one(self):\n    pass\n"
        found = problems({"tests/test_app.py": "M", "tests/test_old.py": "D"},
                         {"tests/test_app.py": before, "tests/test_old.py": before},
                         {"tests/test_app.py": after})
        self.assertEqual(found, [
            "tests/test_app.py no longer has test_two",
            "tests/test_app.py has fewer assertions (2 before, 0 now)",
            "tests/test_old.py was deleted",
        ])

    def test_added_tests_are_fine(self):
        self.assertEqual(problems({"tests/test_new.py": "A"}, {},
                                  {"tests/test_new.py": "def test_x(self):\n"
                                                        "    self.assertTrue(x)\n"}), [])


class GateTests(unittest.TestCase):
    def test_scanner_gate_reports_now_and_before(self):
        finding = {"rule": "CVE-1", "location": "requirements.txt (PyYAML 5.3.1)",
                   "key": "CVE-1 @ PyYAML"}
        dirty = {"status": "findings", "findings": [finding], "detail": ""}
        clean = {"status": "clean", "findings": [], "detail": ""}
        broken = {"status": "error", "findings": [], "detail": "docker is not available"}
        self.assertEqual(verify_fix.scanner_gate("trivy", clean, dirty),
                         Gate("trivy", PASS, "no findings; the base had CVE-1 @ PyYAML"))
        self.assertEqual(verify_fix.scanner_gate("trivy", clean),
                         Gate("trivy", PASS, "no findings"))
        failed = verify_fix.scanner_gate("trivy", dirty, clean)
        self.assertEqual(failed.status, FAIL)
        self.assertIn("CVE-1 at requirements.txt (PyYAML 5.3.1)", failed.detail)
        self.assertIn("the base had no findings", failed.detail)
        self.assertEqual(verify_fix.scanner_gate("trivy", broken).status, ERROR)
        self.assertIn("the base scan could not run",
                      verify_fix.scanner_gate("trivy", clean, broken).detail)

    def test_a_gate_that_could_not_run_is_not_verified(self):
        passing = [Gate("tests", PASS, "75 tests pass"), Gate("policy-test", SKIP, "")]
        self.assertTrue(verify_fix.verified(passing))
        self.assertTrue(verify_fix.verdict(passing).startswith("VERIFIED"))
        for status in (FAIL, ERROR):
            gates = passing + [Gate("semgrep", status, "detail")]
            self.assertFalse(verify_fix.verified(gates))
            self.assertEqual(verify_fix.verdict(gates),
                             "NOT VERIFIED: 1 of 3 gates did not pass (semgrep).")

    def test_reports_name_every_gate(self):
        gates = [Gate("tests", PASS, "75 tests pass"), Gate("trivy", FAIL, "a | b")]
        text = verify_fix.render_text(gates, "verify-fix: heading")
        self.assertIn("  PASS  tests  75 tests pass", text)
        self.assertTrue(text.endswith("(trivy)."))
        markdown = verify_fix.render_markdown(gates, "abc1234", "the working tree")
        self.assertIn("| trivy | FAIL | a \\| b |", markdown)
        self.assertIn("not model output", markdown)

    def test_pins_and_missing_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(verify_fix.sync_dependencies(directory, sys.executable),
                             (True, ""))
            Path(directory, "requirements.txt").write_text(
                "# pinned\ndrift-lab-absent-package==1.2.3  # comment\n")
            self.assertEqual(verify_fix.pins(directory),
                             {"drift-lab-absent-package": "1.2.3"})
            ok, described = verify_fix.sync_dependencies(directory, sys.executable)
        self.assertFalse(ok)
        self.assertIn("nothing is installed, 1.2.3 is pinned", described)
        self.assertEqual(verify_fix.gate_tests(directory, sys.executable, (ok, described)),
                         Gate("tests", FAIL, described))


class RepositoryTests(unittest.TestCase):
    """Gates that read git. The base is a tree object, so no commit is needed."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        git(self.root, "init", "-q")
        self.write("calc.py", "def area(width, height):\n    return width + height\n")
        self.write("tests/test_calc.py",
                   "import unittest\nfrom calc import area\n\n\n"
                   "class CalcTests(unittest.TestCase):\n"
                   "    def test_zero(self):\n"
                   "        self.assertEqual(area(0, 0), 0)\n")
        git(self.root, "add", "-A")
        self.base = git(self.root, "write-tree").strip()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def add_test(self, body):
        with (self.root / "tests/test_calc.py").open("a") as handle:
            handle.write("\n    def test_added(self):\n        " + body + "\n")

    def regression_gate(self):
        changes = verify_fix.changed_files(self.root, self.base)
        return verify_fix.gate_regression_test(self.root, self.base, changes, sys.executable)

    def test_changed_files_sees_edits_additions_and_deletions(self):
        self.write("calc.py", "def area(width, height):\n    return width * height\n")
        self.write("new.py", "NEW = True\n")
        (self.root / "tests/test_calc.py").unlink()
        self.assertEqual(verify_fix.changed_files(self.root, self.base),
                         {"calc.py": "M", "new.py": "A", "tests/test_calc.py": "D"})

    def test_a_test_that_fails_before_and_passes_after_proves_the_fix(self):
        self.write("calc.py", "def area(width, height):\n    return width * height\n")
        self.add_test("self.assertEqual(area(2, 3), 6)")
        gate = self.regression_gate()
        self.assertEqual(gate.status, PASS)
        self.assertIn("fails on the base (FAIL: test_added", gate.detail)

    def test_a_test_that_passes_on_the_base_proves_nothing(self):
        self.write("calc.py", "def area(width, height):\n    return width * height\n")
        self.add_test("self.assertEqual(area(2, 2), 4)")
        gate = self.regression_gate()
        self.assertEqual(gate.status, FAIL)
        self.assertIn("passes on the base too", gate.detail)

    def test_a_fix_without_a_test_is_refused(self):
        self.write("calc.py", "def area(width, height):\n    return width * height\n")
        gate = self.regression_gate()
        self.assertEqual(gate.status, FAIL)
        self.assertIn("no test file", gate.detail)

    def test_a_new_test_that_fails_now_is_refused(self):
        self.add_test("self.assertEqual(area(2, 3), 6)")
        gate = self.regression_gate()
        self.assertEqual(gate.status, FAIL)
        self.assertIn("does not pass on this tree", gate.detail)

    def test_suppression_gate_compares_with_the_base(self):
        self.write("calc.py", "def area(width, height):  # nosemgrep\n"
                              "    return width + height\n")
        changes = verify_fix.changed_files(self.root, self.base)
        gate = verify_fix.gate_no_new_suppression(self.root, self.base, changes)
        self.assertEqual(gate, Gate("no-new-suppression", FAIL,
                                    'calc.py:1 adds a suppression ("nosemgrep")'))
        git(self.root, "add", "-A")
        accepted = git(self.root, "write-tree").strip()
        unchanged = verify_fix.changed_files(self.root, accepted)
        self.assertEqual(verify_fix.gate_no_new_suppression(self.root, accepted,
                                                            unchanged).status, PASS)

    def test_policy_gate_skips_when_infra_is_unchanged(self):
        self.assertEqual(verify_fix.gate_policy_test(self.root, {"calc.py": "M"}),
                         Gate("policy-test", SKIP, "infra/ unchanged"))


class StopHookTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.state = {"branch": "fix/unsafe-load", "base": "0123456789abcdef",
                      "fingerprint": "tree-one", "state_path": self.root / "state.json"}
        self.calls = []

    def verifier(self, *gates):
        def run(root, base):
            self.calls.append(base)
            return list(gates)
        return run

    def decide(self, verifier, active=False):
        return verify_fix.decide(self.root, self.state, {"stop_hook_active": active},
                                 verifier)

    def test_a_failing_fix_is_sent_back_with_the_reason(self):
        failing = self.verifier(Gate("tests", PASS, "75 tests pass"),
                                Gate("semgrep", FAIL, "1 found: avoid-pyyaml-load"))
        result = self.decide(failing)
        self.assertEqual(result["decision"], "block")
        self.assertIn("verify-fix: fix/unsafe-load against base 0123456", result["reason"])
        self.assertIn("FAIL  semgrep  1 found: avoid-pyyaml-load", result["reason"])
        self.assertIn("NOT VERIFIED", result["reason"])
        self.assertIn("Do not add a suppression", result["reason"])
        self.assertEqual(self.calls, ["0123456789abcdef"])

    def test_retries_are_capped_and_end_not_verified(self):
        failing = self.verifier(Gate("semgrep", FAIL, "1 found"))
        results = [self.decide(failing)]
        results += [self.decide(failing, active=True)
                    for _ in range(verify_fix.MAX_BLOCKS)]
        decisions = [result.get("decision") for result in results]
        self.assertEqual(decisions, ["block"] * verify_fix.MAX_BLOCKS + [None])
        self.assertIn("Giving up after 3 attempts", results[-1]["systemMessage"])
        self.assertIn("NOT VERIFIED", results[-1]["systemMessage"])
        # A new prompt starts a new count.
        self.assertEqual(self.decide(failing)["decision"], "block")

    def test_a_verified_tree_is_reported_once_and_not_run_again(self):
        passing = self.verifier(Gate("semgrep", PASS, "no findings"))
        result = self.decide(passing)
        self.assertNotIn("decision", result)
        self.assertIn("VERIFIED: every gate passed", result["systemMessage"])
        self.assertEqual(json.loads(self.state["state_path"].read_text())["verified"],
                         "tree-one")
        self.assertIsNone(self.decide(passing))
        self.assertEqual(len(self.calls), 1)
        self.state["fingerprint"] = "tree-two"
        self.assertIsNotNone(self.decide(passing))
        self.assertEqual(len(self.calls), 2)

    def test_the_hook_stays_out_of_what_is_not_a_fix_branch(self):
        self.assertIsNone(verify_fix.hook_state(self.root))  # not a repository
        git(self.root, "init", "-q")
        self.assertIsNone(verify_fix.hook_state(self.root))  # no commit yet
        self.assertIsNone(verify_fix.stop_hook(self.root, {}, self.verifier()))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
