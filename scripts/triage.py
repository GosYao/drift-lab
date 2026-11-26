"""Review packets: computed evidence in, one packet per finding out.

The evidence is computed here: the pinned scanners, the gate outcomes, the chained
exposure, the fix evidence, and the diff. A model writes the packets from it. The
model, its tools and its instructions come from one reviewed file,
.factory/droids/triage.md, and the model runs read-only through `droid exec`.

What comes out always carries the computed evidence beside the model's text, so a
packet can recommend but can never change what a gate said.

Fail-safe: if the model run fails, times out, or returns text that does not match
the packet format, the result says "Triage unavailable, human review required."
and every finding keeps the severity its gate reported.
"""

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import chained_exposure
import scanners
import verify_fix

ROOT = Path(__file__).resolve().parent.parent
DROID_FILE = ".factory/droids/triage.md"
WORK_DIR = ".triage"
RECOMMENDATIONS = ("true positive", "false positive", "accepted risk")
VERDICTS = ("no issues found", "comment", "request changes")
UNAVAILABLE = "Triage unavailable, human review required."
PACKET_HEADING = "### <number>. <gate> `<rule>`"
POLICY_TESTS = "infra/workloads/"
TIMEOUT_SECONDS = 600
DIFF_LINES = 400
ANSI = re.compile(r"\x1b\[[0-9;]*m")
HEADING = re.compile(r"^#{2,4} +(\d+)\. +(.*)$", re.M)


def load_droid(path):
    """(frontmatter, instructions) of a custom droid file."""
    match = re.match(r"---\n(.*?)\n---\n(.*)", Path(path).read_text(), re.S)
    if not match:
        raise ValueError("{} has no frontmatter".format(path))
    meta = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        if value.strip():
            meta[key.strip()] = value.strip()
    return meta, match.group(2).strip()


def droid_contract(path):
    """Ways the droid file and this script disagree. Empty when they agree."""
    meta, body = load_droid(path)
    body = " ".join(body.split())
    problems = []
    if meta.get("tools") != "read-only":
        problems.append("tools must be read-only")
    if meta.get("model", "inherit") == "inherit":
        problems.append("the model must be named, not inherited")
    expected = (PACKET_HEADING, "**Recommendation:**", UNAVAILABLE) + RECOMMENDATIONS \
        + tuple("VERDICT: " + verdict for verdict in VERDICTS)
    problems += ["the instructions never mention: " + phrase
                 for phrase in expected if phrase not in body]
    return problems


def scanner_results(root, evidence_dir=None):
    """Normalized scanner results: the pipeline's, when handed over, else a run now."""
    names = sorted(scanners.SCANNERS)
    if evidence_dir is None:
        return scanners.scan(root, names)
    results = []
    for name in names:
        try:
            result = json.loads((Path(evidence_dir) / (name + ".json")).read_text())
            if (result["scanner"] != name or not isinstance(result["findings"], list)
                    or result["status"] not in ("clean", "findings", "error")):
                raise ValueError(name)
        except (OSError, ValueError, KeyError, TypeError):
            # A result that did not arrive is never read as a clean scan.
            result = {"scanner": name, "label": scanners.SCANNERS[name]["label"],
                      "status": "error", "findings": [],
                      "detail": "its result did not reach the review step"}
        results.append(result)
    return results


def policy_findings(output):
    """One finding per failed capability-intent run in `terraform test` output.

    Terraform prints the `run "..."... fail` lines to stdout and the Error
    diagnostics (file, line, condition, assert message) to stderr inside
    box-drawing frames, so the two are matched by run name, not position.
    """
    text = ANSI.sub("", output)
    diagnostics = {}
    for match in re.finditer(
            r"on (\S+) line (\d+), in run \"([^\"]+)\":\s*\n[│\s]*\d+:\s*condition\s*=\s*(.+)",
            text):
        tail = text[match.end():match.end() + 2000].split("╵", 1)[0]
        said = [re.sub(r"^[│╷╵├─\s]+", "", line).strip() for line in tail.splitlines()]
        said = [line for line in said if line and
                not line.startswith(("Warning", "Diff", "+", "-", "[", "]"))]
        diagnostics[match.group(3)] = (
            match.group(1), match.group(2), match.group(4).strip(),
            said[-1] if said else "")
    findings = []
    parts = re.split(r'^\s*run "([^"]+)"\.\.\. (pass|fail)\s*$', text, flags=re.M)
    for name, result, detail in zip(parts[1::3], parts[2::3], parts[3::3]):
        if result != "fail":
            continue
        file, line, condition, message = diagnostics.get(name, (None, None, "", ""))
        location = POLICY_TESTS + "{}:{}".format(file, line) if file else POLICY_TESTS
        findings.append({
            "scanner": "policy-test", "rule": name, "severity": "FAIL",
            "location": location, "key": "{} @ {}".format(name, location),
            "title": message or "A capability-intent assertion failed.",
            "message": "Failed assertion: " + condition if condition else "",
        })
    return findings


def run_make(root, target, timeout=900):
    try:
        done = subprocess.run(["make", target], cwd=str(root), capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, "could not run: {}".format(error)
    return done.returncode, done.stdout + done.stderr


def gate_outcomes(root, changes, run=run_make):
    """What the unit suite and the capability-intent tests say about this tree."""
    code, output = run(root, "check")
    gates = [{"name": "make check", "exit": code, "output": output, "skipped": ""}]
    if any(path.startswith("infra/") for path in changes):
        code, output = run(root, "policy-test")
        gates.append({"name": "make policy-test", "exit": code, "output": output,
                      "skipped": ""})
    else:
        gates.append({"name": "make policy-test", "exit": None, "output": "",
                      "skipped": "infra/ unchanged"})
    return gates


def gate_summary(gate):
    if gate["skipped"]:
        return "`{}`: not run, {}".format(gate["name"], gate["skipped"])
    if gate["exit"] is None:
        return "`{}`: could not run".format(gate["name"])
    return "`{}`: exit {}".format(gate["name"], gate["exit"])


def scanner_summary(result):
    if result["status"] == "error":
        return "{}: could not run ({}); this is not a clean scan".format(
            result["label"], result["detail"])
    count = len(result["findings"])
    return "{}: {}".format(result["label"], "no findings" if not count else
                           "{} finding{}".format(count, "" if count == 1 else "s"))


def change_diff(root, base, limit=DIFF_LINES):
    stat = verify_fix.git(root, "diff", "--stat", base).rstrip()
    lines = verify_fix.git(root, "diff", "--unified=3", base).splitlines()
    cut = ("\n(diff cut at {} of {} lines; read the files for the rest)"
           .format(limit, len(lines)) if len(lines) > limit else "")
    return stat, "\n".join(lines[:limit]) + cut


def gather(root, base, evidence_dir=None):
    """Everything computed about this change. Nothing here is model output."""
    git = verify_fix.git
    changes = verify_fix.changed_files(root, base)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        scans = pool.submit(scanner_results, root, evidence_dir)
        outcomes = pool.submit(gate_outcomes, root, changes)
        results, gates = scans.result(), outcomes.result()
    findings = [finding for result in results for finding in result["findings"]]
    for gate in gates:
        if gate["name"] == "make policy-test" and gate["exit"]:
            findings += policy_findings(gate["output"])
    fix_evidence = ""
    if evidence_dir is not None and (Path(evidence_dir) / "fix-evidence.md").is_file():
        fix_evidence = (Path(evidence_dir) / "fix-evidence.md").read_text().strip()
    stat, diff = change_diff(root, base)
    number = os.environ.get("PR_NUMBER", "")
    return {
        "branch": (os.environ.get("GITHUB_HEAD_REF")
                   or git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()),
        "head": git(root, "rev-parse", "--short", "HEAD").strip(),
        "base": git(root, "rev-parse", "--short", base).strip(),
        "dirty": bool(git(root, "status", "--porcelain").strip()),
        "pull_request": {"number": number, "title": os.environ.get("PR_TITLE", ""),
                         "author": os.environ.get("PR_AUTHOR", "")} if number else None,
        "results": results, "findings": findings, "gates": gates,
        "exposure": chained_exposure.compute(root, base),
        "fix_evidence": fix_evidence, "stat": stat, "diff": diff,
        "untracked": sorted(path for path, status in changes.items() if status == "A"
                            and path not in stat),
    }


def subject(evidence):
    pull = evidence["pull_request"]
    if pull:
        return "#{} {}".format(pull["number"], pull["title"]).strip()
    state = "the working tree on " if evidence["dirty"] else ""
    return "{}`{}` at `{}`".format(state, evidence["branch"], evidence["head"])


def evidence_for_model(evidence):
    lines = ["# Evidence for this change", "",
             "Computed by `scripts/triage.py`. Use it as given.", "",
             "Change: {}, compared with base `{}`.".format(subject(evidence), evidence["base"]),
             "", "## Findings that need a packet", ""]
    if not evidence["findings"]:
        lines.append("None: no scanner finding and no failed capability-intent test.")
    for number, finding in enumerate(evidence["findings"], 1):
        lines.append("{}. {} `{}`".format(number, finding["scanner"], finding["rule"]))
        lines.append("   - severity reported by the gate: {}".format(finding["severity"]))
        lines.append("   - location: {}".format(finding["location"]))
        for label, key in (("code", "code"), ("fixed in", "fixed"), ("title", "title"),
                           ("detail", "message"), ("reference", "url")):
            if finding.get(key):
                lines.append("   - {}: {}".format(label, str(finding[key])[:900]))
        if finding.get("cwe"):
            lines.append("   - weakness: {}".format("; ".join(finding["cwe"])))
    lines += ["", "## Scanners", ""]
    lines += ["- " + scanner_summary(result) for result in evidence["results"]]
    lines += ["", "## Gate outcomes", ""]
    for gate in evidence["gates"]:
        lines.append("- " + gate_summary(gate))
        tail = ANSI.sub("", gate["output"]).strip().splitlines()[-(40 if gate["exit"] else 6):]
        if tail:
            lines += ["", "```"] + tail + ["```", ""]
    lines += ["", "## Chained exposure", ""]
    lines += ["- " + fact for fact in evidence["exposure"]["facts"]]
    if evidence["fix_evidence"]:
        lines += ["", "## Fix evidence", "", evidence["fix_evidence"]]
    lines += ["", "## Diff against the base", "", "```", evidence["stat"], "```"]
    if evidence["untracked"]:
        lines += ["", "Not yet tracked by git: " + ", ".join(evidence["untracked"])]
    lines += ["", "```diff", evidence["diff"], "```"]
    return "\n".join(lines)


def evidence_for_reviewer(evidence):
    lines = ["### Computed evidence (not model output)", ""]
    if evidence["findings"]:
        lines += ["| # | Finding | Severity from the gate | Location |",
                  "| --- | --- | --- | --- |"]
        for number, finding in enumerate(evidence["findings"], 1):
            fixed = ", fixed in {}".format(finding["fixed"]) if finding.get("fixed") else ""
            lines.append("| {} | {} `{}` | {} | {}{} |".format(
                number, finding["scanner"], finding["rule"], finding["severity"],
                finding["location"], fixed))
    else:
        lines.append("No scanner finding and no failed capability-intent test.")
    lines += ["", "- **Scanners:** {}.".format(
        ". ".join(scanner_summary(result) for result in evidence["results"])),
              "- **Gates:** {}.".format(
                  ". ".join(gate_summary(gate) for gate in evidence["gates"])),
              "", "**Chained exposure**", ""]
    lines += ["- " + fact for fact in evidence["exposure"]["facts"]]
    if evidence["fix_evidence"]:
        lines += ["", evidence["fix_evidence"]]
    return "\n".join(lines)


def droid_binary():
    fallback = os.path.expanduser("~/.local/bin/droid")
    return shutil.which("droid") or (fallback if os.access(fallback, os.X_OK) else None)


def tool_summary(event, root):
    """One readable line for a tool call in the model's event stream."""
    name = event.get("toolName") or event.get("toolId") or "tool"
    parameters = event.get("parameters") if isinstance(event.get("parameters"), dict) else {}
    if name == "Script":
        script = str(parameters.get("script", ""))
        called = list(dict.fromkeys(re.findall(r"tools\.(\w+)\(", script))) or [name]
        name = ", ".join(called)
        values = [value for _, value in re.findall(
            r"""(?:file_path|path|pattern|command)\s*:\s*(['"`])(.+?)\1""", script)]
    else:
        values = [str(parameters[key]) for key in ("file_path", "path", "pattern", "command")
                  if parameters.get(key)]
    values = list(dict.fromkeys(value.replace(str(root) + "/", "") for value in values))
    return "{} {}".format(name, ", ".join(values[:3])).strip()[:110]


def run_droid(prompt_file, model, effort, root, timeout=TIMEOUT_SECONDS,
              say=lambda line: None, binary=None):
    """Run the model read-only on the prompt and report what happened. Never raises."""
    run = {"ok": False, "text": "", "requested": model, "model": None, "effort": None,
           "credits": None, "seconds": None, "turns": None, "session": None, "error": ""}
    binary = binary or droid_binary()
    if not binary:
        run["error"] = "the droid CLI is not installed"
        return run
    # No --auto flag: droid exec is read-only unless told otherwise.
    command = [binary, "exec", "--model", model]
    if effort:
        command += ["--reasoning-effort", effort]
    command += ["--output-format", "stream-json", "-f", str(prompt_file)]
    say("$ droid " + " ".join(command[1:]).replace(str(root) + "/", ""))
    started = time.monotonic()
    try:
        process = subprocess.Popen(command, cwd=str(root), stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
    except OSError as error:
        run["error"] = "droid exec could not start: {}".format(error)
        return run
    expired = threading.Event()

    def stop():
        expired.set()
        process.kill()

    timer = threading.Timer(timeout, stop)
    timer.start()
    noise = []
    try:
        for line in process.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                event = None
            if not isinstance(event, dict):
                if line.strip():
                    noise.append(line.strip())
                continue
            kind = event.get("type")
            if kind == "system" and event.get("subtype") == "init":
                run.update(model=event.get("model"), effort=event.get("reasoning_effort"),
                           session=event.get("session_id"))
                say("  model {} · reasoning {} · read-only".format(run["model"], run["effort"]))
            elif kind == "tool_call":
                say("  · " + tool_summary(event, root))
            elif kind == "completion":
                run.update(text=event.get("finalText") or "", turns=event.get("numTurns"),
                           credits=(event.get("usage") or {}).get("factory_credits"))
            elif kind == "error":
                noise.append(str(event.get("message") or event))
        code = process.wait()
    finally:
        timer.cancel()
    run["seconds"] = round(time.monotonic() - started)
    if expired.is_set():
        run["error"] = "the model run timed out after {} seconds".format(timeout)
    elif code != 0:
        run["error"] = "droid exec exited {}{}".format(
            code, ": " + noise[-1][:200] if noise else "")
    elif not run["text"].strip():
        run["error"] = "the model returned no text"
    else:
        run["ok"] = True
    return run


def packets(text):
    """{number: (heading, section)} for each numbered packet in the model's text."""
    found, matches = {}, list(HEADING.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        found[int(match.group(1))] = (match.group(2), text[match.start():end])
    return found


def recommendation(section):
    match = re.search(r"^[-*] +\*\*Recommendation:?\*\*:? *(.+)$", section, re.M)
    value = match.group(1).strip(" *`_.").lower() if match else ""
    return next((option for option in RECOMMENDATIONS if value.startswith(option)), None)


def review_problems(text, findings):
    """(why the whole text is unusable, or ""; the findings without a usable packet)."""
    verdicts = re.findall(r"^VERDICT: *(.+?) *$", text, re.M)
    if len(verdicts) != 1 or verdicts[0] not in VERDICTS:
        return "the model's text does not end in one VERDICT line", findings
    if findings and verdicts[0] == "no issues found":
        return "the model's verdict contradicts the gates", findings
    found = packets(text)
    missing = [finding for number, finding in enumerate(findings, 1)
               if number not in found or finding["rule"] not in found[number][0]
               or recommendation(found[number][1]) is None]
    if findings and len(missing) == len(findings):
        return "the model's text has no usable packet", findings
    return "", missing


def fail_safe(evidence, finding):
    number = evidence["findings"].index(finding) + 1
    return "- {}. {} `{}`: {} It keeps the severity its gate reported: {}.".format(
        number, finding["scanner"], finding["rule"], UNAVAILABLE, finding["severity"])


def model_line(run):
    named = "`{}`, named in `{}`".format(run["requested"], DROID_FILE)
    if not run["ok"]:
        return "**Triage model:** {}. It did not produce a usable result: {}.".format(
            named, run["error"] or "see above")
    ran = "" if run["model"] in (None, run["requested"]) else \
        " The run reported `{}` instead.".format(run["model"])
    numbers = ["{} s".format(run["seconds"])]
    if run["turns"] is not None:
        numbers.append("{} turns".format(run["turns"]))
    if run["credits"] is not None:
        numbers.append("{} Factory credits".format(run["credits"]))
    effort = ", reasoning effort `{}`".format(run["effort"]) if run["effort"] else ""
    return "**Triage model:** {}{}.{} {}.".format(named, effort, ran, ", ".join(numbers))


def compose(evidence, run):
    """The review a person reads: the model's packets, then the computed evidence."""
    problem, missing = (run["error"], evidence["findings"]) if not run["ok"] else \
        review_problems(run["text"], evidence["findings"])
    if problem:
        run = dict(run, ok=False, error=problem)
    lines = ["## Review packet: " + subject(evidence), "",
             "A model's reading of the computed evidence below. It recommends. It cannot "
             "change a check result, and a person approves the merge.", ""]
    if problem:
        lines += ["**{}** ({}.)".format(UNAVAILABLE, problem[0].upper() + problem[1:]), ""]
    else:
        lines += [run["text"].strip(), ""]
        if missing:
            lines += ["**No usable packet for:**", ""]
    lines += [fail_safe(evidence, finding) for finding in missing]
    lines += ["" if missing else None, "---", "", evidence_for_reviewer(evidence), "",
              model_line(run)]
    return "\n".join(line for line in lines if line is not None) + "\n", not problem


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="commit this change is compared with (default: "
                                       "where HEAD left the default branch)")
    parser.add_argument("--evidence", type=Path,
                        help="directory with the pipeline's <scanner>.json results and "
                             "fix-evidence.md (default: run the scanners now)")
    parser.add_argument("--out", type=Path, default=ROOT / WORK_DIR / "review.md",
                        help="where to write the review (default: .triage/review.md)")
    parser.add_argument("--model", default=os.environ.get("TRIAGE_MODEL"),
                        help="use this model instead of the one the droid file names")
    parser.add_argument("--evidence-only", action="store_true",
                        help="write the evidence and the prompt, then stop")
    parser.add_argument("--timeout", type=int, default=TIMEOUT_SECONDS,
                        help="seconds to wait for the model (default: %(default)s)")
    args = parser.parse_args(argv)

    def say(line):
        print(line, file=sys.stderr, flush=True)

    droid_error = ""
    try:
        meta, instructions = load_droid(ROOT / DROID_FILE)
    except (OSError, ValueError) as error:
        meta, instructions, droid_error = {"model": ""}, "", str(error)
    model = args.model or meta.get("model") or "unspecified"
    default_ref = chained_exposure.default_branch(ROOT)
    base = args.base or (verify_fix.git(ROOT, "merge-base", "HEAD", default_ref).strip()
                         if default_ref else "HEAD")
    say("triage: computing the evidence (scanners, gates, chained exposure)")
    evidence = gather(ROOT, base, args.evidence)
    say("triage: {} against base {}: {}".format(
        subject(evidence).replace("`", ""), evidence["base"],
        "; ".join(scanner_summary(result) for result in evidence["results"])))
    work = ROOT / WORK_DIR
    work.mkdir(exist_ok=True)
    (work / "evidence.md").write_text(evidence_for_model(evidence) + "\n")
    prompt = work / "prompt.md"
    prompt.write_text("{}\n\n{}\n".format(instructions, evidence_for_model(evidence)))
    if args.evidence_only:
        say("triage: wrote {0}/evidence.md and {0}/prompt.md".format(WORK_DIR))
        return 0
    say("triage: model {} from {}".format(model, DROID_FILE if not args.model
                                          else "the command line or TRIAGE_MODEL"))
    if droid_error:
        say("triage: " + UNAVAILABLE.lower() + " " + droid_error)
        run = {"ok": False, "text": "", "requested": model, "model": None,
               "effort": None, "credits": None, "seconds": None, "turns": None,
               "session": None, "error": droid_error}
    else:
        run = run_droid(prompt, model, meta.get("reasoningEffort"), ROOT,
                        args.timeout, say)
    review, usable = compose(evidence, run)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(review)
    print(review)
    if not usable:
        # The fail-safe is a designed outcome, so the step succeeds and the review is
        # still published; the annotation makes the outage visible on the run.
        say("::warning title=Triage unavailable::{}".format(UNAVAILABLE))
    say("triage: wrote {}".format(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
