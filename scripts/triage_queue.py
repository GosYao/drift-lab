"""Ranked triage queue: every open signal in one list, ranked by what it reaches.

Signals come from three kinds of source, each computed or recorded, never inferred:

  - the pinned scanners on this tree (code and dependency findings);
  - the capability-intent test on every other branch that changes a workload
    role's policy (access drift);
  - recorded observations from the live lab (docs/observations.json), labelled
    with their date. They are read from the file, not collected again.

For each signal this script computes the facts a ranking needs: whether the file
is in the image, what imports it, which identity the workload runs as, whether
the branch is merged. The model named in .factory/droids/triage-queue.md ranks
the signals and gives one reason each. It cannot change a severity or close a
finding. If its answer is unusable, the queue keeps the order the sources
reported it in, marked unranked.
"""

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import chained_exposure
import scanners
import triage

ROOT = Path(__file__).resolve().parent.parent
DROID_FILE = ".factory/droids/triage-queue.md"
OBSERVATIONS = "docs/observations.json"
URGENCIES = ("fix now", "fix soon", "schedule", "backlog")
UNRANKED = "Ranking unavailable, human review required."
RANK_FORMAT = "<rank>. #<finding number> <urgency>: <reason>"
RANK_LINE = re.compile(r"^\s*(\d+)\.\s+#(\d+)\s+(fix now|fix soon|schedule|backlog)\s*:\s*(.+?)\s*$",
                       re.I | re.M)


def git(root, *args):
    return subprocess.run(["git", *args], cwd=str(root), check=True,
                          capture_output=True, text=True).stdout


def droid_contract(path):
    """Ways the queue droid file and this script disagree. Empty when they agree."""
    meta, body = triage.load_droid(path)
    body = " ".join(body.split())
    problems = []
    if meta.get("tools") != "read-only":
        problems.append("tools must be read-only")
    if meta.get("model", "inherit") == "inherit":
        problems.append("the model must be named, not inherited")
    problems += ["the instructions never mention: " + phrase
                 for phrase in (RANK_FORMAT,) + URGENCIES if phrase not in body]
    return problems


# --- the image ---------------------------------------------------------------

def image(dockerfile):
    """What the Dockerfile puts in the image: COPY sources, RUN lines and the CMD."""
    lines = [line.strip() for line in dockerfile.splitlines()]
    return {"sources": chained_exposure.image_sources(dockerfile),
            "runs": [line for line in lines if line.split()[:1] == ["RUN"]],
            "cmd": next((line for line in lines if line.split()[:1] == ["CMD"]), "")}


def importers(root, path, sources):
    """Python files copied into the image that import the module at path."""
    stem = re.escape(Path(path).stem)
    pattern = re.compile(r"^\s*(from\s+[\w.]*\b{0}\s+import\b|from\s+[\w.]+\s+import\s+"
                         r"(\w+\s*,\s*)*{0}\b|import\s+[\w.]*\b{0}\b)".format(stem), re.M)
    found = []
    for name in git(root, "ls-files", "*.py").splitlines():
        if name == path or not chained_exposure.in_image(name, sources):
            continue
        try:
            if pattern.search((Path(root) / name).read_text(errors="replace")):
                found.append(name)
        except OSError:
            continue
    return sorted(found)


def file_of(finding):
    if finding["scanner"] == "semgrep":
        return finding["location"].rsplit(":", 1)[0]
    return finding["location"].split(" (", 1)[0].rsplit(":", 1)[0]


def scanner_facts(root, finding, built):
    path = file_of(finding)
    sources = built["sources"]
    copied = ", ".join("`{}`".format(source) for source in sources if source != "Dockerfile")
    if not chained_exposure.in_image(path, sources):
        what = "`{} {}`".format(finding["package"], finding["installed"]) \
            if finding.get("package") else "this file"
        return ["`{}` is not copied into the image (the Dockerfile copies only {}), so the "
                "image never contains {}.".format(path, copied or "nothing", what)]
    facts = ["`{}` is copied into the image.".format(path)]
    if finding.get("package"):
        installs = [run for run in built["runs"] if Path(path).name in run]
        facts.append("The image installs it: `{}`.".format(installs[0]) if installs else
                     "No RUN line in the Dockerfile installs it.")
        return facts
    users = importers(root, path, sources)
    if users:
        facts.append("It is imported by {}.".format(", ".join("`{}`".format(user)
                                                             for user in users)))
    if built["cmd"]:
        facts.append("The image starts with `{}`.".format(built["cmd"]))
    return facts


# --- access drift on other branches --------------------------------------------

def terraform_binary(root):
    if os.environ.get("TERRAFORM"):
        return os.environ["TERRAFORM"]
    common = Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    for candidate in (Path(root) / ".tools/terraform", common.parent / ".tools/terraform"):
        if os.access(str(candidate), os.X_OK):
            return str(candidate)
    return shutil.which("terraform")


def policy_branches(branches):
    """The other branches that change a workload role's policy, or might."""
    return [branch for branch in branches
            if branch["reads"] is None or branch["reads"] != branch["fork_reads"]]


def policy_test_at(root, ref, terraform, timeout=600):
    """(exit code or None, output) of the capability-intent tests at ref."""
    if not terraform:
        return None, "terraform is not installed"
    env = dict(os.environ, TF_IN_AUTOMATION="1")
    output = ""
    try:
        with scanners.scratch_dir(root) as scratch:
            tree = scanners.export_tree(root, scratch / "tree", ref)
            work = "-chdir=" + str(tree / "infra/workloads")
            for args in (["init", "-input=false", "-backend=false"], ["test"]):
                done = subprocess.run([terraform, work, *args], capture_output=True,
                                      text=True, timeout=timeout, env=env)
                output += done.stdout + done.stderr
                if done.returncode and args[0] == "init":
                    return None, output
            return done.returncode, output
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as error:
        return None, output + "could not run: {}".format(error)


def policy_facts(branch, stack, default_ref):
    facts = ["{} is open and not merged into `{}`, the approved deployment revision."
             .format(chained_exposure.named(branch), default_ref)]
    if branch["reads"] is None:
        return facts + ["Its policy change has a shape that is not modelled; a person must "
                        "read it."]
    for identity in sorted(branch["reads"]):
        theirs = branch["reads"][identity]
        forked = branch["fork_reads"].get(identity, [])
        adds, drops = sorted(set(theirs) - set(forked)), sorted(set(forked) - set(theirs))
        if not adds and not drops:
            continue
        facts.append("It changes role `aws_iam_role.agent[\"{}\"]`: it {}.".format(
            identity, chained_exposure.delta(adds, drops)))
        for deployment in stack["deployments"] if stack else []:
            if deployment["identity"] == identity:
                facts.append("Deployment `{}` runs as that role (`{}:{}`).".format(
                    deployment["name"], chained_exposure.STACK, deployment["identity_line"]))
    return facts


def access_drift(root, terraform=None, run=policy_test_at):
    """(findings, gates) from the capability-intent tests on the policy branches."""
    default_ref = chained_exposure.default_branch(root)
    if not default_ref:
        return [], [{"name": "policy-test on other branches", "exit": None,
                     "output": "", "skipped": "no default branch on the remote"}]
    try:
        stack = chained_exposure.parse_stack((Path(root) / chained_exposure.STACK).read_text())
    except (OSError, chained_exposure.Unknown):
        stack = None
    findings, gates = [], []
    terraform = terraform or terraform_binary(root)
    for branch in policy_branches(chained_exposure.other_branches(root, default_ref)):
        code, output = run(root, "origin/" + branch["name"], terraform)
        gates.append({"name": "policy-test on " + branch["name"], "exit": code,
                      "output": output, "skipped": ""})
        for finding in triage.policy_findings(output) if code else []:
            finding["location"] = "{} on `{}`".format(finding["location"], branch["name"])
            finding["facts"] = policy_facts(branch, stack, default_ref)
            findings.append(finding)
    if not gates:
        gates.append({"name": "policy-test on other branches", "exit": None, "output": "",
                      "skipped": "no other branch changes a workload role's policy"})
    return findings, gates


# --- recorded observations -------------------------------------------------------

def observations(root):
    """Findings from the recorded live observations. Never re-collected here."""
    path = Path(root) / OBSERVATIONS
    if not path.is_file():
        return []
    findings = []
    for item in json.loads(path.read_text()).get("observations", []):
        findings.append({
            "scanner": "recorded observation", "rule": item["id"],
            "severity": item.get("severity", "not rated"), "location": item["location"],
            "key": item["id"], "title": item["title"], "message": "",
            "facts": ["Recorded live observation from {} ({}). This run read it from `{}`; "
                      "it did not collect it again.".format(item["recorded"], item["source"],
                                                           OBSERVATIONS)]
                     + list(item["facts"]),
        })
    return findings


# --- the queue ---------------------------------------------------------------------

def gather(root):
    """Every signal and its computed facts. Nothing here is model output."""
    built = image((Path(root) / chained_exposure.DOCKERFILE).read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        scans = pool.submit(scanners.scan, root, sorted(scanners.SCANNERS))
        drift = pool.submit(access_drift, root)
        results, (policy, gates) = scans.result(), drift.result()
    findings = []
    for result in results:
        for finding in result["findings"]:
            findings.append(dict(finding, facts=scanner_facts(root, finding, built)))
    findings += policy + observations(root)
    return {"branch": git(root, "rev-parse", "--abbrev-ref", "HEAD").strip(),
            "head": git(root, "rev-parse", "--short", "HEAD").strip(),
            "dirty": bool(git(root, "status", "--porcelain").strip()),
            "results": results, "gates": gates, "findings": findings,
            "exposure": chained_exposure.compute(root)}


def subject(evidence):
    state = "the working tree on " if evidence["dirty"] else ""
    return "{}`{}` at `{}`".format(state, evidence["branch"], evidence["head"])


def evidence_for_model(evidence):
    lines = ["# Evidence for the queue", "", "Computed by `scripts/triage_queue.py`. "
             "Use it as given.", "", "Queue: " + subject(evidence), "", "## Findings to rank", ""]
    for number, finding in enumerate(evidence["findings"], 1):
        lines.append("{}. {} `{}`".format(number, finding["scanner"], finding["rule"]))
        lines.append("   - severity reported by the source: {}".format(finding["severity"]))
        lines.append("   - location: {}".format(finding["location"]))
        for label, key in (("code", "code"), ("fixed in", "fixed"), ("title", "title"),
                           ("detail", "message")):
            if finding.get(key):
                lines.append("   - {}: {}".format(label, str(finding[key])[:600]))
        lines += ["   - computed: " + fact for fact in finding.get("facts", [])]
    if not evidence["findings"]:
        lines.append("None.")
    lines += ["", "## Sources", ""]
    lines += ["- " + triage.scanner_summary(result) for result in evidence["results"]]
    lines += ["- " + triage.gate_summary(gate) for gate in evidence["gates"]]
    lines += ["", "## Chained exposure", ""]
    lines += ["- " + fact for fact in evidence["exposure"]["facts"]]
    return "\n".join(lines)


def ranking(text, count):
    """[(number, urgency, reason)] in rank order, or None when it is not a full ranking."""
    rows = {}
    for match in RANK_LINE.finditer(text.replace("**", "").replace("`#", "#")):
        rank, number = int(match.group(1)), int(match.group(2))
        if rank in rows:
            return None
        rows[rank] = (number, match.group(3).lower(), match.group(4).strip())
    if sorted(rows) != list(range(1, count + 1)):
        return None
    if sorted(number for number, _, _ in rows.values()) != list(range(1, count + 1)):
        return None
    return [rows[rank] for rank in sorted(rows)]


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def compose(evidence, run):
    """The queue a person reads: the ranking beside the source's severity, then the facts."""
    findings = evidence["findings"]
    order = ranking(run["text"], len(findings)) if run["ok"] and findings else None
    problem = run["error"] if not run["ok"] else ("" if order or not findings else
                                                  "the model's text is not a full ranking")
    if problem:
        run = dict(run, ok=False, error=problem)
    lines = ["## Triage queue: " + subject(evidence), "",
             "A model's ranking of the computed evidence below. It recommends an order. It "
             "cannot change a severity or close a finding; a person decides.", ""]
    if problem:
        lines += ["**{}** ({}.) The queue is in the order the sources reported it.".format(
            UNRANKED, problem[0].upper() + problem[1:]), ""]
        order = [(number, "unranked", UNRANKED) for number in range(1, len(findings) + 1)]
    lines += ["| Rank | Finding | Severity from the source | Urgency | Why |",
              "| --- | --- | --- | --- | --- |"]
    for rank, (number, urgency, reason) in enumerate(order, 1):
        finding = findings[number - 1]
        lines.append("| {} | #{} {} `{}` | {} | {} | {} |".format(
            rank if not problem else "-", number, finding["scanner"], cell(finding["rule"]),
            finding["severity"], urgency, cell(reason)))
    lines += ["", "---", "", "### Computed evidence (not model output)", ""]
    for number, finding in enumerate(findings, 1):
        lines.append("{}. {} `{}`, {}: {}".format(number, finding["scanner"], finding["rule"],
                                                 finding["severity"], finding["location"]))
        lines += ["   - " + fact for fact in finding.get("facts", [])]
    lines += ["", "**Sources:** {}.".format(". ".join(
        [triage.scanner_summary(result) for result in evidence["results"]]
        + [triage.gate_summary(gate) for gate in evidence["gates"]])), "",
        "**Chained exposure**", ""]
    lines += ["- " + fact for fact in evidence["exposure"]["facts"]]
    lines += ["", triage.model_line(run, DROID_FILE)]
    return "\n".join(lines) + "\n", not problem


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / triage.WORK_DIR / "queue.md")
    parser.add_argument("--model", default=os.environ.get("TRIAGE_MODEL"),
                        help="use this model instead of the one the droid file names")
    parser.add_argument("--evidence-only", action="store_true",
                        help="write the evidence and the prompt, then stop")
    parser.add_argument("--timeout", type=int, default=triage.TIMEOUT_SECONDS)
    args = parser.parse_args(argv)

    def say(line):
        print(line, file=sys.stderr, flush=True)

    meta, instructions = triage.load_droid(ROOT / DROID_FILE)
    model = args.model or meta.get("model") or "unspecified"
    say("triage-queue: computing the evidence (scanners, policy tests on open branches, "
        "recorded observations)")
    evidence = gather(ROOT)
    say("triage-queue: {} findings on {}".format(len(evidence["findings"]),
                                                 subject(evidence).replace("`", "")))
    work = ROOT / triage.WORK_DIR
    work.mkdir(exist_ok=True)
    prompt = work / "queue-prompt.md"
    prompt.write_text("{}\n\n{}\n".format(instructions, evidence_for_model(evidence)))
    if args.evidence_only:
        say("triage-queue: wrote {}".format(prompt))
        return 0
    run = triage.run_droid(prompt, model, meta.get("reasoningEffort"), ROOT, args.timeout, say)
    if args.model and args.model != meta.get("model"):
        run["overrides"] = meta.get("model")
    queue, _ = compose(evidence, run)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(queue)
    print(queue)
    say("triage-queue: wrote {}".format(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
