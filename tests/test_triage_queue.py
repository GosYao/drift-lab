import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import triage_queue  # noqa: E402

DOCKERFILE = """FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY drift_lab /app/drift_lab
CMD ["python", "-m", "drift_lab", "serve"]
"""
CODE = {"scanner": "semgrep", "rule": "avoid-pyyaml-load", "severity": "ERROR",
        "location": "drift_lab/loader.py:3", "title": "Unsafe YAML load"}
SHIPPED = {"scanner": "trivy", "rule": "CVE-1", "severity": "CRITICAL",
           "location": "requirements.txt (PyYAML 5.3.1)", "package": "PyYAML",
           "installed": "5.3.1"}
DEV_ONLY = {"scanner": "trivy", "rule": "CVE-2", "severity": "CRITICAL",
            "location": "tools/dev/requirements.txt (pyarrow 14.0.0)", "package": "pyarrow",
            "installed": "14.0.0"}
RUN = {"ok": True, "text": "", "requested": "m", "model": "m", "effort": "high",
       "asked": "high", "credits": 10, "seconds": 3, "turns": 1, "session": None, "error": ""}


def repository(files):
    directory = tempfile.TemporaryDirectory()
    root = Path(directory.name)
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True)
    return directory, root


def evidence(findings):
    return {"branch": "demo/triage-queue", "head": "abc1234", "dirty": False,
            "results": [], "gates": [], "findings": findings,
            "exposure": {"status": "none", "facts": ["Nothing chained."]}}


class ImageFactTests(unittest.TestCase):
    def setUp(self):
        self.directory, self.root = repository({
            "Dockerfile": DOCKERFILE, "requirements.txt": "PyYAML==5.3.1\n",
            "tools/dev/requirements.txt": "pyarrow==14.0.0\n",
            "drift_lab/loader.py": "import yaml\n",
            "drift_lab/server.py": "from .loader import load\n",
            "scripts/tool.py": "from drift_lab.loader import load\n"})
        self.addCleanup(self.directory.cleanup)
        self.built = triage_queue.image(DOCKERFILE)

    def test_a_dependency_file_outside_the_image_never_ships(self):
        facts = triage_queue.scanner_facts(self.root, DEV_ONLY, self.built)
        self.assertEqual(len(facts), 1)
        self.assertIn("is not copied into the image", facts[0])
        self.assertIn("never contains `pyarrow 14.0.0`", facts[0])

    def test_a_dependency_the_image_installs_names_the_run_line(self):
        facts = triage_queue.scanner_facts(self.root, SHIPPED, self.built)
        self.assertIn("`requirements.txt` is copied into the image.", facts)
        self.assertIn("The image installs it: `RUN pip install --no-cache-dir -r "
                      "/app/requirements.txt`.", facts)

    def test_code_in_the_image_names_only_importers_that_ship(self):
        facts = triage_queue.scanner_facts(self.root, CODE, self.built)
        self.assertIn("It is imported by `drift_lab/server.py`.", facts)
        self.assertFalse(any("scripts/tool.py" in fact for fact in facts))
        self.assertTrue(any(fact.startswith("The image starts with `CMD") for fact in facts))


class SourceTests(unittest.TestCase):
    def test_observations_are_labelled_as_recorded_not_collected(self):
        directory, root = repository({triage_queue.OBSERVATIONS: json.dumps({"observations": [{
            "id": "kubelet", "title": "Kubelet reachable", "location": "node :10250",
            "recorded": "2026-10-30", "source": "docs/STATUS.md",
            "facts": ["Observed: reachable."]}]})})
        self.addCleanup(directory.cleanup)
        [finding] = triage_queue.observations(root)
        self.assertEqual(finding["severity"], "not rated")
        self.assertIn("Recorded live observation from 2026-10-30", finding["facts"][0])
        self.assertIn("did not collect it again", finding["facts"][0])
        self.assertEqual(finding["facts"][1], "Observed: reachable.")

    def test_no_observation_file_means_no_observations(self):
        directory, root = repository({"README.md": "x\n"})
        self.addCleanup(directory.cleanup)
        self.assertEqual(triage_queue.observations(root), [])

    def test_only_branches_that_change_a_policy_are_tested(self):
        same = {"name": "a", "reads": {"r": ["t1"]}, "fork_reads": {"r": ["t1"]}}
        wider = {"name": "b", "reads": {"r": ["t1", "t2"]}, "fork_reads": {"r": ["t1"]}}
        unknown = {"name": "c", "reads": None, "fork_reads": None}
        self.assertEqual([branch["name"] for branch in
                          triage_queue.policy_branches([same, wider, unknown])], ["b", "c"])

    def test_policy_facts_say_unmerged_and_what_the_role_gains(self):
        branch = {"name": "verify/x", "head": "326eac5", "pull_request": 1,
                  "reads": {"support-agent": ["archive", "orders"]},
                  "fork_reads": {"support-agent": ["orders"]}}
        stack = {"deployments": [{"name": "support-agent", "identity": "support-agent",
                                  "identity_line": 111}]}
        facts = triage_queue.policy_facts(branch, stack, "origin/main")
        self.assertIn("not merged into `origin/main`", facts[0])
        self.assertIn("adds `archive`", facts[1])
        self.assertIn("Deployment `support-agent` runs as that role", facts[2])


class RankingTests(unittest.TestCase):
    FULL = ("## Ranked queue\n1. #2 fix now: reachable from request input.\n"
            "2. **#1 schedule**: ships, affected function not called.\n"
            "3. #3 backlog: never ships.\n")

    def test_a_full_ranking_is_read_in_rank_order(self):
        self.assertEqual([row[:2] for row in triage_queue.ranking(self.FULL, 3)],
                         [(2, "fix now"), (1, "schedule"), (3, "backlog")])

    def test_a_missing_or_doubled_finding_is_not_a_ranking(self):
        self.assertIsNone(triage_queue.ranking(self.FULL, 4))
        doubled = self.FULL.replace("3. #3", "3. #2")
        self.assertIsNone(triage_queue.ranking(doubled, 3))
        self.assertIsNone(triage_queue.ranking(self.FULL + "3. #3 backlog: again.\n", 3))

    def test_the_rank_sits_beside_the_unchanged_severity(self):
        queue, usable = triage_queue.compose(
            evidence([CODE, SHIPPED, DEV_ONLY]),
            dict(RUN, text="1. #1 fix now: request input reaches it.\n"
                           "2. #2 schedule: affected function not called.\n"
                           "3. #3 backlog: never ships.\n"))
        self.assertTrue(usable)
        rows = [line for line in queue.splitlines() if line.startswith("| 3 |")]
        self.assertEqual(len(rows), 1)
        self.assertIn("| CRITICAL | backlog | never ships. |", rows[0])
        self.assertIn("named in `.factory/droids/triage-queue.md`", queue)

    def test_an_unusable_answer_keeps_the_source_order_and_severities(self):
        for run in (dict(RUN, text="Looks fine to me."),
                    dict(RUN, ok=False, error="the model run timed out after 5 seconds")):
            queue, usable = triage_queue.compose(evidence([CODE, SHIPPED, DEV_ONLY]), run)
            self.assertFalse(usable)
            self.assertIn(triage_queue.UNRANKED, queue)
            rows = [line for line in queue.splitlines() if line.startswith("| - |")]
            self.assertEqual([row.split("|")[2].split()[0] for row in rows],
                             ["#1", "#2", "#3"])
            self.assertTrue(all("unranked" in row for row in rows))
            self.assertIn("| CRITICAL | unranked |", rows[1])


class ContractTests(unittest.TestCase):
    def test_the_repository_queue_droid_satisfies_the_contract(self):
        self.assertEqual(triage_queue.droid_contract(ROOT / triage_queue.DROID_FILE), [])

    def test_contract_catches_a_weakened_droid(self):
        text = (ROOT / triage_queue.DROID_FILE).read_text()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.md"
            path.write_text(text.replace("tools: read-only", "tools: all")
                            .replace("model: glm-5.3-flash", "model: inherit"))
            problems = triage_queue.droid_contract(path)
        self.assertIn("tools must be read-only", problems)
        self.assertIn("the model must be named, not inherited", problems)


if __name__ == "__main__":
    unittest.main()
