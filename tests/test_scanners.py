import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scanners  # noqa: E402

RULE = "python.lang.security.deserialization.avoid-pyyaml-load.avoid-pyyaml-load"
SEMGREP = {
    "paths": {"scanned": ["app/loader.py"]},
    "results": [{
        "check_id": RULE, "path": "app/loader.py", "start": {"line": 2},
        "extra": {"severity": "ERROR",
                  "message": "Detected a possible YAML deserialization vulnerability. "
                             "Use yaml.safe_load instead.",
                  "metadata": {"cwe": ["CWE-502: Deserialization of Untrusted Data"]}},
    }],
}
TRIVY = {"Results": [{
    "Target": "requirements.txt",
    "Vulnerabilities": [{
        "VulnerabilityID": "CVE-2020-14343", "PkgName": "PyYAML",
        "InstalledVersion": "5.3.1", "FixedVersion": "5.4", "Severity": "CRITICAL",
        "Title": "PyYAML: incomplete fix for CVE-2020-1747",
        "Description": "Arbitrary code execution through\nfull_load or FullLoader.",
        "PrimaryURL": "https://avd.aquasec.com/nvd/cve-2020-14343"}],
    "Secrets": [{"RuleID": "private-key", "Severity": "HIGH", "Title": "Private key",
                 "StartLine": 7}],
}]}
CLEAN_SEMGREP = {"paths": {"scanned": ["app/loader.py"]}, "results": []}


def git(root, *args):
    return subprocess.run(["git", *args], cwd=str(root), check=True,
                          capture_output=True, text=True).stdout


class ParsingTests(unittest.TestCase):
    def test_semgrep_finding_is_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app" / "loader.py"
            source.parent.mkdir()
            source.write_text("import yaml\n    data = yaml.load(text, Loader=yaml.Loader)\n")
            finding, = scanners.parse_semgrep(SEMGREP, directory)
        self.assertEqual(finding["scanner"], "semgrep")
        self.assertEqual(finding["rule"], RULE)
        self.assertEqual(finding["severity"], "ERROR")
        self.assertEqual(finding["location"], "app/loader.py:2")
        self.assertEqual(finding["title"],
                         "Detected a possible YAML deserialization vulnerability.")
        self.assertEqual(finding["code"], "data = yaml.load(text, Loader=yaml.Loader)")
        self.assertEqual(finding["cwe"], ["CWE-502: Deserialization of Untrusted Data"])

    def test_trivy_vulnerability_and_secret_are_normalized(self):
        vulnerability, secret = scanners.parse_trivy(TRIVY)
        self.assertEqual(vulnerability["rule"], "CVE-2020-14343")
        self.assertEqual(vulnerability["severity"], "CRITICAL")
        self.assertEqual(vulnerability["location"], "requirements.txt (PyYAML 5.3.1)")
        self.assertEqual(vulnerability["fixed"], "5.4")
        self.assertEqual(vulnerability["message"],
                         "Arbitrary code execution through full_load or FullLoader.")
        self.assertEqual(secret["rule"], "private-key")
        self.assertEqual(secret["location"], "requirements.txt:7")

    def test_trivy_without_results_has_no_findings(self):
        self.assertEqual(scanners.parse_trivy({"Results": None}), [])
        self.assertEqual(scanners.parse_trivy({}), [])


class ClassifyTests(unittest.TestCase):
    def test_findings_and_clean(self):
        found = scanners.classify("semgrep", 1, json.dumps(SEMGREP), "")
        self.assertEqual(found["status"], "findings")
        self.assertEqual(len(found["findings"]), 1)
        clean = scanners.classify("semgrep", 0, json.dumps(CLEAN_SEMGREP), "")
        self.assertEqual((clean["status"], clean["findings"]), ("clean", []))
        self.assertEqual(scanners.classify("trivy", 0, '{"Results": []}', "")["status"],
                         "clean")

    def test_anything_unexpected_is_an_error_never_clean(self):
        cases = [
            ("semgrep", 0, "", "docker: image not found"),         # no output at all
            ("semgrep", 0, "not json", ""),                         # unparseable
            ("semgrep", 0, json.dumps({"results": []}), ""),        # scanned no files
            ("semgrep", 1, json.dumps(CLEAN_SEMGREP), ""),          # failed, nothing parsed
            ("semgrep", 0, json.dumps(SEMGREP), ""),                # findings, exit 0
            ("semgrep", 2, json.dumps(CLEAN_SEMGREP), ""),          # scanner crashed
            ("trivy", 1, '{"Results": []}', ""),
            ("trivy", 125, "", "Cannot connect to the Docker daemon"),
        ]
        for name, code, stdout, stderr in cases:
            with self.subTest(name=name, code=code, stdout=stdout[:20]):
                result = scanners.classify(name, code, stdout, stderr)
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["findings"], [])
                self.assertTrue(result["detail"])

    def test_missing_docker_is_an_error(self):
        with mock.patch.object(scanners, "docker_binary", return_value=None):
            result = scanners.run_scanner("trivy", "/nowhere")
        self.assertEqual(result["status"], "error")
        self.assertIn("docker", result["detail"])


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q")
        (self.root / ".gitignore").write_text("*.log\n")
        (self.root / "tracked.py").write_text("ORIGINAL = True\n")
        (self.root / "gone.py").write_text("gone = True\n")
        git(self.root, "add", "-A")
        self.base = git(self.root, "write-tree").strip()

    def test_working_tree_export_is_what_git_would_commit(self):
        (self.root / "tracked.py").write_text("CHANGED = True\n")
        (self.root / "gone.py").unlink()
        (self.root / "new.py").write_text("new = True\n")
        (self.root / "debug.log").write_text("ignored\n")
        out = scanners.export_tree(self.root, Path(self.directory.name) / "now")
        names = sorted(path.name for path in out.iterdir())
        self.assertEqual(names, [".gitignore", "new.py", "tracked.py"])
        self.assertEqual((out / "tracked.py").read_text(), "CHANGED = True\n")

    def test_ref_export_ignores_the_working_tree(self):
        (self.root / "tracked.py").write_text("CHANGED = True\n")
        (self.root / "new.py").write_text("new = True\n")
        out = scanners.export_tree(self.root, Path(self.directory.name) / "base", self.base)
        names = sorted(path.name for path in out.iterdir())
        self.assertEqual(names, [".gitignore", "gone.py", "tracked.py"])
        self.assertEqual((out / "tracked.py").read_text(), "ORIGINAL = True\n")

    def test_scratch_directory_is_inside_the_repository_and_removed(self):
        with scanners.scratch_dir(self.root) as scratch:
            self.assertEqual(scratch.parent, self.root / scanners.SCRATCH)
            self.assertTrue(scratch.is_dir())
        self.assertFalse((self.root / scanners.SCRATCH).exists())


class CommandLineTests(unittest.TestCase):
    def run_main(self, results, *args):
        output = io.StringIO()
        with mock.patch.object(scanners, "scan", return_value=results), \
                redirect_stdout(output):
            return scanners.main(list(args)), output.getvalue()

    def test_exit_status_is_the_worst_result(self):
        clean = scanners.classify("trivy", 0, '{"Results": []}', "")
        found = scanners.classify("semgrep", 1, json.dumps(SEMGREP), "")
        broken = scanners.classify("trivy", 125, "", "no daemon")
        self.assertEqual(self.run_main([clean], "trivy")[0], 0)
        self.assertEqual(self.run_main([found, clean], "semgrep", "trivy")[0], 1)
        status, printed = self.run_main([found, broken], "semgrep", "trivy")
        self.assertEqual(status, 2)
        self.assertIn(RULE, printed)
        self.assertIn("could not run", printed)

    def test_results_are_written_for_the_review_job(self):
        found = scanners.classify("semgrep", 1, json.dumps(SEMGREP), "")
        with tempfile.TemporaryDirectory() as directory:
            self.run_main([found], "semgrep", "--out-dir", directory)
            written = json.loads((Path(directory) / "semgrep.json").read_text())
        self.assertEqual(written["status"], "findings")
        self.assertEqual(written["findings"][0]["rule"], RULE)


if __name__ == "__main__":
    unittest.main()
