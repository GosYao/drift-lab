"""Pinned scanners: one definition for the pull-request pipeline and the verifier.

Both scanners run from digest-pinned images against a clean export of the tree
(tracked files plus untracked files that are not ignored), so a local run sees
what a fresh checkout would see. Findings are normalized into one shape that
the verifier and the triage prompt both read.

Exit status: 0 no findings, 1 findings, 2 a scanner could not run.
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCANNERS = {
    "semgrep": {
        "label": "semgrep (p/owasp-top-ten)",
        "image": "semgrep/semgrep@sha256:"
                 "2e45517a85e13a9cca14a2a00df6bb48affd66b8ebfae1b0991cd57578362fb0",
        "mount": "/src",
        "volumes": [],
        "command": ["semgrep", "scan", "--config", "p/owasp-top-ten", "--error",
                    "--metrics=off", "--json"],
    },
    "trivy": {
        "label": "trivy (vuln, secret; HIGH, CRITICAL)",
        "image": "aquasec/trivy@sha256:"
                 "790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c",
        "mount": "/repo",
        # The vulnerability database is cached between local runs.
        "volumes": ["drift-lab-trivy-cache:/root/.cache/trivy"],
        "command": ["fs", "--scanners", "vuln,secret", "--severity", "HIGH,CRITICAL",
                    "--exit-code", "1", "--no-progress", "--ignore-unfixed",
                    "--skip-dirs", ".git", "--format", "json", "/repo"],
    },
}
DOCKER_FALLBACKS = ("/usr/local/bin/docker", "/opt/homebrew/bin/docker")
TIMEOUT_SECONDS = 240
SCRATCH = ".verify-tmp"


def docker_binary():
    found = shutil.which("docker")
    if found:
        return found
    return next((path for path in DOCKER_FALLBACKS if os.access(path, os.X_OK)), None)


def git(root, *args, text=True):
    return subprocess.run(["git", *args], cwd=str(root), check=True,
                          capture_output=True, text=text).stdout


@contextlib.contextmanager
def scratch_dir(root):
    """A disposable directory inside the repository, where Docker can always mount it.

    The system temporary directory is not shared with every container runtime;
    an unshared path mounts as an empty directory and a scanner then reports
    nothing. The scratch directory is ignored by git.
    """
    parent = Path(root) / SCRATCH
    parent.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=str(parent)) as scratch:
            yield Path(scratch)
    finally:
        with contextlib.suppress(OSError):
            parent.rmdir()  # only succeeds when no other run is using it


def export_tree(root, destination, ref=None):
    """Copy what git would commit into destination: a ref, or the working tree."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    # The scanner containers run as another user; the export must be readable.
    destination.chmod(0o755)
    if ref:
        archive = git(root, "archive", "--format=tar", ref, text=False)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            try:
                tar.extractall(str(destination), filter="data")
            except TypeError:  # Python before the extraction-filter backport
                tar.extractall(str(destination))
        return destination
    listed = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for name in sorted(set(filter(None, listed.split("\0")))):
        source = Path(root) / name
        if not (source.is_file() or source.is_symlink()):
            continue  # deleted in the working tree
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(target), follow_symlinks=False)
    return destination


def first_sentence(text):
    text = " ".join((text or "").split())
    end = text.find(". ")
    return text if end < 0 else text[:end + 1]


def source_line(source_dir, path, line):
    try:
        lines = (Path(source_dir) / path).read_text(errors="replace").splitlines()
        return lines[line - 1].strip()
    except (OSError, IndexError):
        return ""


def parse_semgrep(payload, source_dir=None):
    findings = []
    for item in payload.get("results", []):
        extra = item.get("extra", {})
        path, line = item.get("path", ""), item.get("start", {}).get("line", 0)
        cwe = extra.get("metadata", {}).get("cwe", [])
        findings.append({
            "scanner": "semgrep",
            "rule": item.get("check_id", ""),
            "severity": extra.get("severity", ""),
            "location": "{}:{}".format(path, line),
            "key": "{} @ {}".format(item.get("check_id", ""), path),
            "title": first_sentence(extra.get("message", "")),
            "message": " ".join(extra.get("message", "").split()),
            "cwe": [cwe] if isinstance(cwe, str) else list(cwe),
            "code": source_line(source_dir, path, line) if source_dir else "",
        })
    return findings


def parse_trivy(payload):
    findings = []
    for result in payload.get("Results") or []:
        target = result.get("Target", "")
        for item in result.get("Vulnerabilities") or []:
            package = "{} {}".format(item.get("PkgName", ""), item.get("InstalledVersion", ""))
            findings.append({
                "scanner": "trivy",
                "rule": item.get("VulnerabilityID", ""),
                "severity": item.get("Severity", ""),
                "location": "{} ({})".format(target, package),
                "key": "{} @ {}".format(item.get("VulnerabilityID", ""), item.get("PkgName", "")),
                "title": item.get("Title", ""),
                "message": " ".join((item.get("Description") or "").split()),
                "package": item.get("PkgName", ""),
                "installed": item.get("InstalledVersion", ""),
                "fixed": item.get("FixedVersion", ""),
                "url": item.get("PrimaryURL", ""),
            })
        for item in result.get("Secrets") or []:
            location = "{}:{}".format(target, item.get("StartLine", 0))
            findings.append({
                "scanner": "trivy",
                "rule": item.get("RuleID", ""),
                "severity": item.get("Severity", ""),
                "location": location,
                "key": "{} @ {}".format(item.get("RuleID", ""), target),
                "title": item.get("Title", ""),
                "message": "Secret detected by rule {}.".format(item.get("RuleID", "")),
            })
    return findings


def classify(name, returncode, stdout, stderr, source_dir=None):
    """Turn one scanner run into a result. Anything unexpected is an error, never clean."""
    result = {"scanner": name, "label": SCANNERS[name]["label"], "status": "error",
              "findings": [], "detail": ""}
    try:
        payload = json.loads(stdout)
    except ValueError:
        tail = (stderr or stdout or "").strip().splitlines()[-1:] or ["no output"]
        result["detail"] = "exit {}: {}".format(returncode, tail[0][:200])
        return result
    if name == "semgrep":
        findings = parse_semgrep(payload, source_dir)
        if not payload.get("paths", {}).get("scanned"):
            result["detail"] = "semgrep scanned no files"
            return result
    else:
        findings = parse_trivy(payload)
    if returncode == 0 and not findings:
        result["status"] = "clean"
    elif returncode == 1 and findings:
        result["status"], result["findings"] = "findings", findings
    else:
        result["detail"] = "exit {} with {} findings parsed".format(returncode, len(findings))
    return result


def run_scanner(name, source_dir, timeout=TIMEOUT_SECONDS):
    spec = SCANNERS[name]
    docker = docker_binary()
    if not docker:
        return {"scanner": name, "label": spec["label"], "status": "error", "findings": [],
                "detail": "docker is not available, so the scanner did not run"}
    mount = ["-v", "{}:{}:ro".format(source_dir, spec["mount"])]
    command = [docker, "run", "--rm", *mount]
    for volume in spec["volumes"]:
        command += ["-v", volume]
    command += [spec["image"], *spec["command"]]
    # Semgrep refuses an empty mount by itself. Trivy would report a clean scan
    # of nothing, so confirm the container can see the tree first.
    probe = [docker, "run", "--rm", *mount, "--entrypoint", "/bin/sh", spec["image"],
             "-c", 'test -n "$(ls -A {})"'.format(spec["mount"])]
    try:
        if name == "trivy" and subprocess.run(probe, capture_output=True,
                                              timeout=timeout).returncode != 0:
            return {"scanner": name, "label": spec["label"], "status": "error",
                    "findings": [], "detail": "the container could not see the tree to scan"}
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"scanner": name, "label": spec["label"], "status": "error", "findings": [],
                "detail": "timed out after {} seconds".format(timeout)}
    return classify(name, done.returncode, done.stdout, done.stderr, source_dir)


def scan(root, names, ref=None):
    """Export the tree once and run each named scanner against the export."""
    with scratch_dir(root) as scratch:
        source = export_tree(root, scratch / "tree", ref)
        return [run_scanner(name, str(source)) for name in names]


def render(result):
    if result["status"] == "error":
        return ["{}: could not run: {}".format(result["label"], result["detail"])]
    if not result["findings"]:
        return ["{}: no findings".format(result["label"])]
    count = len(result["findings"])
    lines = ["{}: {} finding{}".format(result["label"], count, "" if count == 1 else "s")]
    for finding in result["findings"]:
        lines.append("  {:<8} {}".format(finding["severity"], finding["rule"]))
        lines.append("           {}".format(finding["location"]))
        if finding["title"]:
            lines.append("           {}".format(finding["title"][:160]))
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scanner", nargs="+", choices=sorted(SCANNERS))
    parser.add_argument("--ref", help="scan this commit instead of the working tree")
    parser.add_argument("--out-dir", type=Path,
                        help="write <scanner>.json with the normalized result here")
    args = parser.parse_args(argv)
    status = 0
    for result in scan(ROOT, args.scanner, args.ref):
        print("\n".join(render(result)), flush=True)
        if args.out_dir:
            args.out_dir.mkdir(parents=True, exist_ok=True)
            target = args.out_dir / (result["scanner"] + ".json")
            target.write_text(json.dumps(result, indent=2) + "\n")
        status = max(status, {"clean": 0, "findings": 1, "error": 2}[result["status"]])
    return status


if __name__ == "__main__":
    sys.exit(main())
