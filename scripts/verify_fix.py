"""Verified-fix gates for security fixes on fix/ branches.

A fix is verified when every gate passes for the working tree, compared with a
base commit (default: where the branch left its upstream, otherwise HEAD):

  no-new-suppression  no new scanner suppression, no change to the checks that
                      judge the fix, no removed test or assertion
  regression-test     a changed test fails an assertion on the base code and
                      passes now
  tests               the unit suite passes against the pinned dependencies
  policy-test         the capability-intent tests pass, when infra/ changed
  semgrep, trivy      the pinned scanners report nothing

The pull-request pipeline runs these gates as its verify-fix job, and Droid's
Stop hook runs them with --stop-hook. A gate that cannot run counts as failed.
A verified fix is evidence for a reviewer: a person still approves the merge.

--red-green shows the regression-test evidence on its own: each changed test
file run on the base, then on this tree.
"""

import argparse
import collections
import concurrent.futures
import contextlib
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import scanners

ROOT = Path(__file__).resolve().parent.parent
FIX_BRANCH_PREFIX = "fix/"
MAX_BLOCKS = 3
STATE_FILE = "verify-fix-state.json"

Gate = collections.namedtuple("Gate", "name status detail")
PASS, FAIL, SKIP, ERROR = "PASS", "FAIL", "SKIP", "ERROR"

SUPPRESSION = re.compile(r"nosemgrep|\bnosem\b|trivy:ignore")
IGNORE_FILES = (".semgrepignore", ".trivyignore", ".trivyignore.yaml", "trivy.yaml")
# The checks that judge a fix. A fix that edits one of these proves nothing.
JUDGES = (".github/workflows/", ".factory/hooks.json", "Makefile",
          "scripts/scanners.py", "scripts/verify_fix.py")
TEST_NAME = re.compile(r"^\s*def (test_\w+)", re.M)
ASSERTION = re.compile(r"\bself\.assert\w+\(|^\s*assert\s", re.M)
PIN = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*==\s*([^\s;#]+)")
# One failure block in unittest's output: its kind, the test's name, its traceback.
# The optional line is the first line of the test's docstring.
PROBLEM = re.compile(r"^(FAIL|ERROR): (\S+)[^\n]*\n(?:[^\n]*\n)?-{20,}\n(.*?)"
                     r"(?=^[=-]{20,}$)", re.M | re.S)


def git(root, *args):
    return subprocess.run(["git", *args], cwd=str(root), check=True,
                          capture_output=True, text=True).stdout


def default_base(root):
    """The commit a fix is compared with: where the branch left its upstream, else HEAD.

    A fix branch cut from the branch it repairs tracks that branch, so committed
    and uncommitted fix work are both compared with the code that had the finding.
    """
    try:
        return git(root, "merge-base", "HEAD", "@{upstream}").strip()
    except subprocess.CalledProcessError:
        return git(root, "rev-parse", "HEAD").strip()


def changed_files(root, base):
    """Paths that differ between base and the working tree: {path: "A", "M" or "D"}."""
    fields = git(root, "diff", "--name-status", "--no-renames", "-z", base).split("\0")
    changes = {path: status[0] for status, path in zip(fields[0::2], fields[1::2])}
    untracked = git(root, "ls-files", "-z", "--others", "--exclude-standard")
    changes.update({path: "A" for path in untracked.split("\0") if path})
    return changes


def base_text(root, base, path):
    done = subprocess.run(["git", "show", "{}:{}".format(base, path)], cwd=str(root),
                          capture_output=True)
    return done.stdout.decode(errors="replace") if done.returncode == 0 else None


def tree_text(root, path):
    try:
        return (Path(root) / path).read_text(errors="replace")
    except OSError:
        return None


def marker_lines(text):
    return collections.Counter(line.strip() for line in text.splitlines()
                               if SUPPRESSION.search(line))


def suppression_problems(changes, before, after):
    """Reasons this change weakens a check. before and after map a path to its text."""
    problems = []
    for path in sorted(changes):
        if (path in IGNORE_FILES or path.endswith(".tftest.hcl")
                or path.startswith(JUDGES)):
            problems.append("{} changed: a fix may not change the checks that judge it"
                            .format(path))
            continue
        old, new = before(path) or "", after(path) or ""
        if not path.endswith(".md"):
            added = marker_lines(new) - marker_lines(old)
            for number, line in enumerate(new.splitlines(), 1):
                line = line.strip()
                if added[line] > 0:
                    added[line] -= 1
                    marker = line[SUPPRESSION.search(line).start():][:90]
                    problems.append('{}:{} adds a suppression ("{}")'
                                    .format(path, number, marker))
        if path.startswith("tests/") and path.endswith(".py") and changes[path] != "A":
            if changes[path] == "D":
                problems.append("{} was deleted".format(path))
                continue
            for name in sorted(set(TEST_NAME.findall(old)) - set(TEST_NAME.findall(new))):
                problems.append("{} no longer has {}".format(path, name))
            fewer = len(ASSERTION.findall(old)), len(ASSERTION.findall(new))
            if fewer[1] < fewer[0]:
                problems.append("{} has fewer assertions ({} before, {} now)"
                                .format(path, *fewer))
    return problems


def gate_no_new_suppression(root, base, changes):
    problems = suppression_problems(changes, lambda path: base_text(root, base, path),
                                    lambda path: tree_text(root, path))
    if not problems:
        return Gate("no-new-suppression", PASS,
                    "no new suppression; checks and tests are intact")
    more = "; and {} more".format(len(problems) - 6) if len(problems) > 6 else ""
    return Gate("no-new-suppression", FAIL, "; ".join(problems[:6]) + more)


def test_python(root):
    candidate = Path(root) / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def failure_reason(traceback):
    """The exception line of one failure block: the first line after the last frame."""
    lines = traceback.rstrip().splitlines()
    frames = [index for index, line in enumerate(lines) if line.startswith("  File ")]
    after = lines[frames[-1] + 1:] if frames else lines
    reason = next((line for line in after if line.strip() and not line.startswith(" ")), "")
    return (reason or (lines[-1] if lines else "")).strip()[:200]


def run_unittest(python, cwd, pattern=None, timeout=300):
    command = [python, "-m", "unittest", "discover", "-s", "tests"]
    if pattern:
        command += ["-p", pattern]
    try:
        done = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True,
                              timeout=timeout,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    except subprocess.TimeoutExpired:
        return {"ok": False, "ran": 0, "first": "", "problems": [],
                "summary": "timed out after {} seconds".format(timeout)}
    output = done.stderr + done.stdout
    ran = re.search(r"^Ran (\d+) tests? in", output, re.M)
    first = re.search(r"^(?:FAIL|ERROR): \S+", output, re.M)
    lines = output.strip().splitlines()
    count = int(ran.group(1)) if ran else 0
    return {"ok": done.returncode == 0 and count > 0, "ran": count,
            "first": first.group(0) if first else "",
            "summary": lines[-1] if lines else "no output",
            "problems": [(kind, name, failure_reason(body))
                         for kind, name, body in PROBLEM.findall(output)]}


def assertion_failures(result):
    """The tests that ran and failed an assertion.

    An ERROR is not one: a test that cannot be imported, or that crashes, says
    nothing about how the code under test behaved.
    """
    return [problem for problem in result["problems"] if problem[0] == "FAIL"]


def changed_tests(changes):
    return sorted(path for path, status in changes.items()
                  if status in "AM" and fnmatch.fnmatch(path, "tests/test_*.py"))


def before_and_after(root, base, candidates, python):
    """[(path, result on this tree, result on the base)] for each changed test file.

    The base is the base commit's code with only the changed test files copied in.
    A test that does not pass on this tree is not run on the base (None).
    """
    results = []
    with scanners.scratch_dir(root) as scratch:
        before = scanners.export_tree(root, scratch / "base", base)
        for path in candidates:
            (before / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(Path(root) / path), str(before / path))
        for path in candidates:
            now = run_unittest(python, root, Path(path).name)
            old = run_unittest(python, before, Path(path).name) if now["ok"] else None
            results.append((path, now, old))
    return results


def regression_proof(results):
    """(proven, detail) for what before_and_after() returned.

    Proven means every changed test file passes on this tree and at least one
    of them fails an assertion on the base.
    """
    proven, unproven = [], []
    for path, now, old in results:
        if old is None:
            return False, "{} does not pass on this tree: {}".format(
                path, now["first"] or now["summary"])
        asserted = assertion_failures(old)
        if old["ok"]:
            unproven.append("{} passes on the base too".format(path))
        elif not asserted:
            unproven.append("{} does not fail an assertion on the base ({})"
                            .format(path, old["first"] or old["summary"]))
        else:
            proven.append("{} fails on the base (FAIL: {}: {}) and passes now"
                          .format(path, *asserted[0][1:]))
    if proven:
        return True, "; ".join(proven)
    return False, "; ".join(unproven) + ", so it does not prove the fix"


def gate_regression_test(root, base, changes, python, dependencies=(True, "")):
    candidates = changed_tests(changes)
    if not candidates:
        return Gate("regression-test", FAIL,
                    "no test file under tests/ was added or changed")
    if not dependencies[0]:
        return Gate("regression-test", ERROR, "could not run: " + dependencies[1])
    proven, detail = regression_proof(before_and_after(root, base, candidates, python))
    return Gate("regression-test", PASS if proven else FAIL, detail)


def pins(root):
    try:
        lines = (Path(root) / "requirements.txt").read_text().splitlines()
    except OSError:
        return {}
    return dict(match.groups() for match in map(PIN.match, lines) if match)


def installed_versions(python, names):
    code = ("import importlib.metadata as m, json, sys\n"
            "out = {}\n"
            "for name in sys.argv[1:]:\n"
            "    try:\n"
            "        out[name] = m.version(name)\n"
            "    except m.PackageNotFoundError:\n"
            "        out[name] = None\n"
            "print(json.dumps(out))\n")
    done = subprocess.run([python, "-c", code, *names], capture_output=True, text=True)
    return json.loads(done.stdout) if done.returncode == 0 else dict.fromkeys(names)


def sync_dependencies(root, python):
    """Make the test interpreter match requirements.txt. Returns (ok, description).

    Only the project's own .venv is ever changed, and only to the exact pins.
    """
    wanted = pins(root)
    if not wanted:
        return True, ""

    def mismatches():
        have = installed_versions(python, sorted(wanted))
        return ["{} {} is installed, {} is pinned".format(name, have[name] or "nothing", pin)
                for name, pin in sorted(wanted.items()) if have[name] != pin]

    in_project_venv = os.path.abspath(python).startswith(str(Path(root) / ".venv"))
    if mismatches() and in_project_venv:
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run([python, "-m", "pip", "install", "-q",
                            "--disable-pip-version-check", "-r", "requirements.txt"],
                           cwd=str(root), capture_output=True, timeout=300)
    wrong = mismatches()
    if wrong:
        return False, "; ".join(wrong) + " (run make install)"
    return True, ", ".join("{} {}".format(*item) for item in sorted(wanted.items()))


def gate_tests(root, python, dependencies=(True, "")):
    ok, described = dependencies
    if not ok:
        return Gate("tests", FAIL, described)
    result = run_unittest(python, root)
    suffix = " ({})".format(described) if described else ""
    if result["ok"]:
        return Gate("tests", PASS, "{} tests pass{}".format(result["ran"], suffix))
    return Gate("tests", FAIL, (result["first"] or result["summary"]) + suffix)


def gate_policy_test(root, changes):
    if not any(path.startswith("infra/") for path in changes):
        return Gate("policy-test", SKIP, "infra/ unchanged")
    try:
        done = subprocess.run(["make", "-s", "policy-test"], cwd=str(root),
                              capture_output=True, text=True, timeout=420)
    except (OSError, subprocess.TimeoutExpired) as error:
        return Gate("policy-test", ERROR, "could not run: {}".format(error))
    output = (done.stdout + done.stderr).strip()
    if done.returncode == 0:
        return Gate("policy-test", PASS, "capability-intent tests pass")
    failed = re.findall(r'run "([^"]+)"\.\.\. fail', output)
    if failed:
        return Gate("policy-test", FAIL, "failed: " + ", ".join(failed))
    return Gate("policy-test", ERROR,
                "could not run: " + (output.splitlines() or ["no output"])[-1][:200])


def scanner_gate(name, now, before=None):
    history = ""
    if before is not None and before["status"] == "error":
        history = "; the base scan could not run"
    elif before is not None:
        keys = sorted(finding["key"] for finding in before["findings"])
        history = "; the base had {}".format(", ".join(keys) if keys else "no findings")
    if now["status"] == "error":
        return Gate(name, ERROR, "could not run: " + now["detail"])
    if now["findings"]:
        listed = "; ".join("{} at {}".format(finding["rule"], finding["location"])
                           for finding in now["findings"][:5])
        return Gate(name, FAIL, "{} found: {}{}".format(len(now["findings"]), listed, history))
    return Gate(name, PASS, "no findings" + history)


def gate_scanners(root, base, scan_base, scan=scanners.run_scanner):
    names = sorted(scanners.SCANNERS)
    with scanners.scratch_dir(root) as scratch:
        trees = {"now": scanners.export_tree(root, scratch / "tree")}
        if scan_base:
            trees["base"] = scanners.export_tree(root, scratch / "base", base)

        # One thread per scanner: two runs of one scanner never share its cache.
        def series(name):
            return {when: scan(name, str(tree)) for when, tree in trees.items()}

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(names)) as pool:
            results = dict(zip(names, pool.map(series, names)))
    return [scanner_gate(name, results[name]["now"], results[name].get("base"))
            for name in names]


def verify(root, base, scan_base=False, scan=scanners.run_scanner):
    changes = changed_files(root, base)
    python = test_python(root)
    dependencies = sync_dependencies(root, python)
    return [
        gate_no_new_suppression(root, base, changes),
        gate_regression_test(root, base, changes, python, dependencies),
        gate_tests(root, python, dependencies),
        gate_policy_test(root, changes),
    ] + gate_scanners(root, base, scan_base, scan)


def verified(gates):
    return all(gate.status in (PASS, SKIP) for gate in gates)


def verdict(gates):
    failed = [gate.name for gate in gates if gate.status not in (PASS, SKIP)]
    if not failed:
        return "VERIFIED: every gate passed. A person still approves the merge."
    return "NOT VERIFIED: {} of {} gates did not pass ({}).".format(
        len(failed), len(gates), ", ".join(failed))


def render_text(gates, heading):
    width = max(len(gate.name) for gate in gates)
    lines = [heading]
    lines += ["  {:<5} {:<{}}  {}".format(gate.status, gate.name, width, gate.detail)
              for gate in gates]
    return "\n".join(lines + [verdict(gates)])


def render_markdown(gates, base, head):
    lines = ["### Fix evidence", "",
             "Computed by `scripts/verify_fix.py` from base `{}` to `{}`. "
             "This section is not model output.".format(base, head), "",
             "**{}**".format(verdict(gates)), "",
             "| Gate | Result | Evidence |", "| --- | --- | --- |"]
    lines += ["| {} | {} | {} |".format(gate.name, gate.status,
                                        gate.detail.replace("|", "\\|")) for gate in gates]
    return "\n".join(lines) + "\n"


def red_green(root, base, color=False):
    """The regression-test evidence, shown: each changed test on the base, then here.

    Returns (text, proven); proven is the regression-test gate's own answer.
    """
    candidates = changed_tests(changed_files(root, base))
    if not candidates:
        return "red-green: no test file under tests/ was added or changed", False
    python = test_python(root)
    ok, described = sync_dependencies(root, python)
    if not ok:
        return "red-green: could not run: " + described, False
    short = git(root, "rev-parse", "--short", base).strip()

    def row(where, result):
        word, code = (("GREEN", 32) if result["ok"] else
                      ("RED", 31) if assertion_failures(result) else ("ERROR", 33))
        word = "\033[1;{}m{:<5}\033[0m".format(code, word) if color else "{:<5}".format(word)
        if result["ok"]:
            count = "1 test passes" if result["ran"] == 1 else \
                "{} tests pass".format(result["ran"])
        elif result["problems"]:
            count = "{} of {} did not pass".format(len(result["problems"]), result["ran"])
        else:
            count = result["summary"]
        lines = ["  {}  on {}: {}".format(word, where, count)]
        for kind, name, reason in result["problems"][:3]:
            lines += ["         {}: {}".format(kind, name), "         " + reason]
        return lines

    results = before_and_after(root, base, candidates, python)
    proven, lines = regression_proof(results)[0], []
    for path, now, old in results:
        lines += ["red-green: " + path, ""]
        if old is not None:
            lines += row("the base " + short, old)
        lines += row("this tree", now) + [""]
    lines.append("Proven: the test fails an assertion on the code before the fix and "
                 "passes after it." if proven else
                 "Not proven: the test must fail an assertion on the base and pass on "
                 "this tree.")
    return "\n".join(lines), proven


def describe(root, base):
    # In the pipeline the merge commit is checked out detached; the branch is in the event.
    branch = (os.environ.get("GITHUB_HEAD_REF")
              or git(root, "rev-parse", "--abbrev-ref", "HEAD").strip())
    short = git(root, "rev-parse", "--short", base).strip()
    dirty = bool(git(root, "status", "--porcelain").strip())
    head = "the working tree" if dirty else git(root, "rev-parse", "--short", "HEAD").strip()
    return branch, short, head


def worktree_fingerprint(root):
    digest = hashlib.sha256(git(root, "rev-parse", "HEAD").encode())
    digest.update(subprocess.run(["git", "diff", "HEAD", "--binary"], cwd=str(root),
                                 check=True, capture_output=True).stdout)
    untracked = git(root, "ls-files", "-z", "--others", "--exclude-standard")
    for name in sorted(filter(None, untracked.split("\0"))):
        digest.update(name.encode())
        with contextlib.suppress(OSError):
            digest.update((Path(root) / name).read_bytes())
    return digest.hexdigest()


def hook_state(root):
    """What the Stop hook acts on, or None when it should stay out of the way.

    Only a fix/ branch that differs from its base is verified, so a session that
    changed nothing is never blocked, and neither is work on any other branch.
    """
    try:
        branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except (OSError, subprocess.CalledProcessError):
        return None  # not a repository, or no commit yet
    if not branch.startswith(FIX_BRANCH_PREFIX):
        return None
    base = default_base(root)
    if not changed_files(root, base):
        return None
    git_dir = git(root, "rev-parse", "--absolute-git-dir").strip()
    return {"branch": branch, "base": base, "fingerprint": worktree_fingerprint(root),
            "state_path": Path(git_dir) / STATE_FILE}


def decide(root, state, payload, verifier=verify):
    """The Stop hook's answer for one state: the JSON object to print, or None."""
    try:
        saved = json.loads(state["state_path"].read_text())
    except (OSError, ValueError):
        saved = {}
    if saved.get("verified") == state["fingerprint"]:
        return None  # this exact tree already passed
    gates = verifier(root, state["base"])
    report = render_text(gates, "verify-fix: {} against base {}"
                         .format(state["branch"], state["base"][:7]))
    if verified(gates):
        state["state_path"].write_text(
            json.dumps({"verified": state["fingerprint"], "blocks": 0}))
        return {"systemMessage": report}
    # stop_hook_active is true only while a Stop hook is already continuing the turn.
    blocks = saved.get("blocks", 0) + 1 if payload.get("stop_hook_active") else 1
    state["state_path"].write_text(json.dumps({"verified": None, "blocks": blocks}))
    if blocks > MAX_BLOCKS:
        return {"systemMessage": report + "\nGiving up after {} attempts. This fix is "
                "NOT VERIFIED, and the pipeline will say the same.".format(MAX_BLOCKS)}
    return {"decision": "block", "reason": report + "\n\nThe fix is not done. Remove the "
            "cause of each gate that did not pass, then finish. Do not add a suppression, "
            "do not change the checks, and do not weaken a test."}


def stop_hook(root, payload, verifier=verify):
    state = hook_state(root)
    return decide(root, state, payload, verifier) if state else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="checkout to verify (default: the one this script is in)")
    parser.add_argument("--base",
                        help="commit in this tree's history to compare the working "
                             "tree with (default: where the branch left its upstream, "
                             "otherwise HEAD)")
    parser.add_argument("--scan-base", action="store_true",
                        help="also scan the base, to record what the scanners said before")
    parser.add_argument("--report", type=Path, help="write the result as Markdown")
    parser.add_argument("--red-green", action="store_true",
                        help="show the changed tests failing on the base, then "
                             "passing on this tree")
    parser.add_argument("--stop-hook", action="store_true",
                        help="run as Droid's Stop hook: read the event on stdin")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.stop_hook:
        try:
            payload = json.load(sys.stdin)
            result = stop_hook(root, payload if isinstance(payload, dict) else {})
        except Exception as error:  # A hook crash must be visible, not a silent pass.
            result = {"systemMessage": "verify-fix could not run ({}). This fix is NOT "
                      "VERIFIED.".format(error)}
        if result:
            print(json.dumps(result))
        return 0
    try:
        base = git(root, "rev-parse", "--verify",
                   (args.base or default_base(root)) + "^{commit}").strip()
    except subprocess.CalledProcessError:
        print("verify-fix: unknown base commit: {}".format(args.base), file=sys.stderr)
        return 2
    # Compared with a commit beside this branch, the base's own newer changes
    # would count as the fix's, and a test that is merely out of date could
    # pass for proof. The pipeline verifies the merge commit, so its base is
    # always in the history.
    if subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"],
                      cwd=str(root), capture_output=True).returncode != 0:
        print("verify-fix: base {} is not in this tree's history, so its newer changes "
              "would count as this fix's. Rebase or merge first."
              .format(args.base or base[:7]), file=sys.stderr)
        return 2
    if args.red_green:
        text, proven = red_green(root, base, color=sys.stdout.isatty()
                                 and "NO_COLOR" not in os.environ)
        print(text)
        return 0 if proven else 1
    branch, short, head = describe(root, base)
    gates = verify(root, base, args.scan_base)
    print(render_text(gates, "verify-fix: {} on {} against base {}".format(head, branch, short)))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_markdown(gates, short, head))
    return 0 if verified(gates) else 1


if __name__ == "__main__":
    sys.exit(main())
