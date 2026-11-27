"""Publish a computed demo queue as idempotent GitHub issues, never close them."""

import argparse
import fcntl
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "GosYao/drift-lab"
LABELS = {"security queue": "5319e7", "fix now": "b60205", "fix soon": "d93f0b",
          "schedule": "fbca04", "backlog": "c5def5", "unranked": "ededed"}
MARKER = re.compile(r"<!-- drift-lab-queue:([a-f0-9]{64}) -->")


def validate(queue):
    """Reject malformed or duplicated rows before making any external writes."""
    if queue.get("schema") != 1 or type(queue.get("ranked")) is not bool:
        raise ValueError("unsupported queue schema")
    for key in ("branch", "head", "model"):
        if not isinstance(queue.get(key), str) or not queue[key]:
            raise ValueError("missing queue " + key)
    for key in ("sources", "exposure"):
        if not isinstance(queue.get(key), list) or any(
                not isinstance(value, str) for value in queue[key]):
            raise ValueError("invalid queue " + key)
    if not isinstance(queue.get("findings"), list):
        raise ValueError("missing findings")
    ids = set()
    for rank, row in enumerate(queue["findings"], 1):
        for key in ("id", "scanner", "rule", "severity", "location", "title", "reason"):
            if not isinstance(row.get(key), str) or not row[key] or len(row[key]) > 4000:
                raise ValueError("invalid finding " + key)
        if not re.fullmatch(r"[a-f0-9]{64}", row["id"]) or row["id"] in ids:
            raise ValueError("invalid or duplicate finding id")
        ids.add(row["id"])
        urgency = row.get("urgency")
        if urgency not in LABELS or urgency == "security queue":
            raise ValueError("invalid urgency")
        if queue["ranked"]:
            if type(row.get("rank")) is not int or row["rank"] != rank or urgency == "unranked":
                raise ValueError("inconsistent ranking")
        elif row.get("rank") is not None or urgency != "unranked":
            raise ValueError("unranked queue cannot claim urgency")
        if not isinstance(row.get("facts"), list) or any(
                not isinstance(fact, str) for fact in row["facts"]):
            raise ValueError("invalid facts")


def issue_body(queue, row):
    lines = ["<!-- drift-lab-queue:{} -->".format(row["id"]),
             "**Demo queue. Seeded changes are not merged or deployed.**", "",
             "Queue: `{}` at `{}`{}.".format(queue["branch"], queue["head"],
                 " (working tree)" if queue.get("dirty") else ""),
             "Rank: {}. Urgency: **{}** (model recommendation).".format(
                 row["rank"] if queue["ranked"] else "unranked", row["urgency"]),
             "Severity from the source: **{}**, unchanged.".format(row["severity"]),
             "", "### Recommendation", "", row["reason"], "",
             "### Computed evidence (not model output)", "",
             "- Source: {} `{}`".format(row["scanner"], row["rule"]),
             "- Location: `{}`".format(row["location"])]
    lines += ["- " + fact for fact in row["facts"]]
    lines += ["", "### Chained exposure", ""] + ["- " + fact for fact in queue["exposure"]]
    lines += ["", "### Sources", ""] + ["- " + source for source in queue["sources"]]
    lines += ["", queue["model"], "",
              "A person decides. This publisher never closes or reopens issues. "
              "A missing finding is not proof of remediation."]
    body = "\n".join(lines) + "\n"
    if len(body) > 60000:
        raise ValueError("issue body too large")
    return body


def api(path, method="GET", payload=None, paginate=False):
    command = ["gh", "api", "--method", method, path]
    if paginate:
        command += ["--paginate", "--slurp"]
    if payload is not None:
        command += ["--input", "-"]
    done = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                          capture_output=True, text=True, check=True, timeout=120)
    return json.loads(done.stdout)


def publish(queue, call=api, write=False):
    validate(queue)
    desired = [(row, "[Security queue] " + row["title"][:180], issue_body(queue, row))
               for row in queue["findings"]]
    if not write:
        return [{"action": "preview", "id": row["id"], "title": title,
                 "urgency": row["urgency"]} for row, title, _ in desired]
    base = "repos/" + REPO
    issues = [issue for page in call(base + "/issues?state=all&per_page=100", paginate=True)
              for issue in page if "pull_request" not in issue]
    existing = {}
    for issue in issues:
        for identity in MARKER.findall(issue.get("body") or ""):
            if identity in existing:
                raise ValueError("duplicate issue markers; human review required")
            existing[identity] = issue
    labels = {item["name"] for page in call(base + "/labels?per_page=100", paginate=True)
              for item in page}
    for label in sorted({"security queue"} | {row["urgency"] for row, _, _ in desired}):
        if label not in labels:
            call(base + "/labels", method="POST", payload={"name": label, "color": LABELS[label]})
    result = []
    for row, title, body in desired:
        issue = existing.get(row["id"])
        if issue and issue["state"] == "closed":
            result.append({"action": "kept closed", "url": issue["html_url"], "id": row["id"]})
            continue
        wanted = {"security queue", row["urgency"]}
        if issue:
            wanted |= {label["name"] for label in issue["labels"]} - set(LABELS)
        payload = {"title": title, "body": body, "labels": sorted(wanted)}
        if issue and all(issue[key] == payload[key] for key in ("title", "body")) and \
                {label["name"] for label in issue["labels"]} == wanted:
            action = "unchanged"
        else:
            path = base + "/issues" + ("/" + str(issue["number"]) if issue else "")
            issue = call(path, method="PATCH" if issue else "POST", payload=payload)
            action = "updated" if row["id"] in existing else "created"
        result.append({"action": action, "url": issue["html_url"], "id": row["id"]})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=ROOT / ".triage/queue.json")
    parser.add_argument("--publish", action="store_true", help="authorize GitHub issue writes")
    args = parser.parse_args(argv)
    # Serialize publishers sharing this checkout. Cross-host calls must also be serialized.
    with args.queue.with_suffix(".publish.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        queue = json.loads(args.queue.read_text())
        print(json.dumps(publish(queue, write=args.publish), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
