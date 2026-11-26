import contextlib
import io
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

    def test_unittest_output_is_read_one_failure_at_a_time(self):
        rule, dashes = "=" * 70 + "\n", "-" * 70 + "\n"
        output = (
            rule + "FAIL: test_payload (tests.test_app.AppTests.test_payload)\n"
            "The payload must not run.\n" + dashes +
            "Traceback (most recent call last):\n"
            '  File "/repo/tests/test_app.py", line 9, in test_payload\n'
            "    self.assertFalse(marker.exists(), 'the payload ran')\n"
            "    ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n"
            "AssertionError: True is not false : the payload ran\n"
            "a second line of the message\n\n" +
            rule + "ERROR: test_other (unittest.loader._FailedTest.test_other)\n" + dashes +
            "ImportError: Failed to import test module: test_other\n"
            "Traceback (most recent call last):\n"
            '  File "/usr/lib/python3/unittest/loader.py", line 396, in _find_test_path\n'
            "    module = self._get_module_from_name(name)\n"
            "ModuleNotFoundError: No module named 'app.other'\n\n" +
            dashes + "Ran 2 tests in 0.010s\n\nFAILED (failures=1, errors=1)\n")
        found = [(kind, name, verify_fix.failure_reason(body))
                 for kind, name, body in verify_fix.PROBLEM.findall(output)]
        self.assertEqual(found, [
            ("FAIL", "test_payload", "AssertionError: True is not false : the payload ran"),
            ("ERROR", "test_other", "ModuleNotFoundError: No module named 'app.other'")])
        self.assertEqual(verify_fix.assertion_failures({"problems": found}), found[:1])


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
        self.assertIn("tests/test_calc.py fails on the base (FAIL: test_added: "
                      "AssertionError: 5 != 6) and passes now", gate.detail)

    def test_a_test_that_passes_on_the_base_proves_nothing(self):
        self.write("calc.py", "def area(width, height):\n    return width * height\n")
        self.add_test("self.assertEqual(area(2, 2), 4)")
        gate = self.regression_gate()
        self.assertEqual(gate.status, FAIL)
        self.assertIn("passes on the base too", gate.detail)

    def test_a_test_that_cannot_run_on_the_base_proves_nothing(self):
        # The base has no perimeter(), so the test fails to import there. That
        # shows nothing about how the base behaved.
        self.write("calc.py", "def area(width, height):\n    return width + height\n\n\n"
                              "def perimeter(width, height):\n"
                              "    return 2 * (width + height)\n")
        self.write("tests/test_perimeter.py",
                   "import unittest\nfrom calc import perimeter\n\n\n"
                   "class PerimeterTests(unittest.TestCase):\n"
                   "    def test_square(self):\n"
                   "        self.assertEqual(perimeter(1, 1), 4)\n")
        gate = self.regression_gate()
        self.assertEqual(gate.status, FAIL)
        self.assertEqual(gate.detail, "tests/test_perimeter.py does not fail an assertion "
                                      "on the base (ERROR: test_perimeter), so it does not "
                                      "prove the fix")

    def test_a_crash_on_the_base_is_not_an_assertion(self):
        # scale= does not exist on the base, so the new test raises TypeError there.
        self.write("calc.py", "def area(width, height, scale=1):\n"
                              "    return (width + height) * scale\n")
        self.add_test("self.assertEqual(area(1, 1, scale=2), 4)")
        gate = self.regression_gate()
        self.assertEqual(gate.status, FAIL)
        self.assertIn("does not fail an assertion on the base (ERROR: test_added)",
                      gate.detail)

    def test_red_green_shows_the_assertion_that_fails_on_the_base(self):
        self.assertEqual(verify_fix.red_green(self.root, self.base),
                         ("red-green: no test file under tests/ was added or changed",
                          False))
        self.write("calc.py", "def area(width, height):\n    return width * height\n")
        self.add_test("self.assertEqual(area(2, 3), 6)")
        text, proven = verify_fix.red_green(self.root, self.base)
        self.assertTrue(proven)
        self.assertTrue(text.startswith("red-green: tests/test_calc.py\n"))
        self.assertRegex(text, r"  RED    on the base \w+: 1 of 2 did not pass\n"
                               r"         FAIL: test_added\n"
                               r"         AssertionError: 5 != 6\n"
                               r"  GREEN  on this tree: 2 tests pass\n")
        self.assertTrue(text.endswith("passes after it."))
        self.assertIn("\033[1;31mRED  \033[0m",
                      verify_fix.red_green(self.root, self.base, color=True)[0])

    def test_red_green_refuses_what_the_gate_refuses(self):
        self.write("calc.py", "def area(width, height):\n    return width * height\n")
        self.add_test("self.assertEqual(area(2, 2), 4)")
        text, proven = verify_fix.red_green(self.root, self.base)
        self.assertFalse(proven)
        self.assertRegex(text, r"  GREEN  on the base \w+: 2 tests pass\n")
        self.assertTrue(text.endswith("pass on this tree."))
        # A test that fails here is not run on the base. (The second test_added
        # replaces the first: one name, one method.)
        self.add_test("self.assertEqual(area(2, 3), 7)")
        text, proven = verify_fix.red_green(self.root, self.base)
        self.assertFalse(proven)
        self.assertNotRegex(text, r"on the base \w+:")
        self.assertIn("  RED    on this tree: 1 of 2 did not pass", text)

    def test_one_proving_test_file_is_enough_among_several(self):
        # The fix also touches a test file that passes both ways. The gate and
        # red-green must agree that the other file still proves the fix.
        self.write("calc.py", "def area(width, height):\n    return width * height\n")
        self.add_test("self.assertEqual(area(2, 3), 6)")
        self.write("tests/test_other.py",
                   "import unittest\n\n\n"
                   "class OtherTests(unittest.TestCase):\n"
                   "    def test_true(self):\n"
                   "        self.assertTrue(True)\n")
        self.assertEqual(self.regression_gate().status, PASS)
        text, proven = verify_fix.red_green(self.root, self.base)
        self.assertTrue(proven)
        self.assertRegex(text, r"red-green: tests/test_other.py\n\n"
                               r"  GREEN  on the base \w+: 1 test passes\n")
        self.assertTrue(text.endswith("passes after it."))

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

    def commit(self, *parents):
        """Commit the working tree as a raw object: no identity, no signature."""
        git(self.root, "add", "-A")
        lines = ["tree " + git(self.root, "write-tree").strip()]
        lines += ["parent " + parent for parent in parents]
        lines += ["author Fixture <fixture@example.invalid> 0 +0000",
                  "committer Fixture <fixture@example.invalid> 0 +0000", "", "fixture", ""]
        return subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"],
                              cwd=str(self.root), input="\n".join(lines), check=True,
                              capture_output=True, text=True).stdout.strip()

    def command_line(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = verify_fix.main(["--root", str(self.root), *arguments])
        return code, out.getvalue(), err.getvalue()

    def test_the_command_line_shows_red_green_against_a_base_in_the_history(self):
        base = self.commit()
        self.write("calc.py", "def area(width, height):\n    return width * height\n")
        self.add_test("self.assertEqual(area(2, 3), 6)")
        git(self.root, "update-ref", "HEAD", self.commit(base))
        code, out, _ = self.command_line("--base", base, "--red-green")
        self.assertEqual(code, 0)
        self.assertIn("  RED    on the base {}: 1 of 2 did not pass".format(base[:7]), out)
        self.assertIn("Proven: ", out)

    def test_the_command_line_refuses_a_base_beside_this_branch(self):
        # main moved on after this branch was cut. Compared with the new main,
        # the branch's older test file would look like a test the fix changed.
        base = self.commit()
        self.write("calc.py", "def area(width, height):\n    return width * height\n")
        self.write("tests/test_calc.py",
                   (self.root / "tests/test_calc.py").read_text()
                   .replace("area(0, 0), 0", "area(2, 3), 6"))
        newer = self.commit(base)
        self.write("calc.py", "def area(width, height):\n    return width + height\n")
        self.write("tests/test_calc.py",
                   (self.root / "tests/test_calc.py").read_text()
                   .replace("area(2, 3), 6", "area(2, 3), 5"))
        git(self.root, "update-ref", "HEAD", self.commit(base))
        # The gate alone is fooled: the stale test fails on the newer code.
        changes = verify_fix.changed_files(self.root, newer)
        self.assertEqual(verify_fix.gate_regression_test(
            self.root, newer, changes, sys.executable).status, PASS)
        for arguments in (["--red-green"], []):
            code, out, err = self.command_line("--base", newer, *arguments)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("base {} is not in this tree's history".format(newer), err)


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
