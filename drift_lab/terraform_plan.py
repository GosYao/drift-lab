"""Allowlist-only extraction of metadata from Terraform's plan JSON.

The raw plan can contain secrets. This intentionally discards attribute values,
outputs, variables, provider configuration and resource IDs before model export.
Changed-attribute paths are exported as names only: Terraform attribute names and
collection indices are kept, and every other path segment (map keys, for_each
keys) is hashed before export.
"""

import hashlib
import json
import re

_SAFE_SEGMENT = re.compile(r"[a-z][a-z0-9_-]*")
_INDEX_SEGMENT = re.compile(r"[0-9]+")

# Server-side bookkeeping attributes change on every write and carry no drift
# signal, so rows whose only differences are these are dropped, not reported.
NOISE_ATTRIBUTES = frozenset({"resource_version", "generation"})


def _segment(name):
    """Export a path segment as a name only; hash anything not identifier-like."""
    text = str(name)
    if _SAFE_SEGMENT.fullmatch(text) or _INDEX_SEGMENT.fullmatch(text):
        return text
    return "redacted-" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:8]


def _equivalent(before, after):
    """Provider null-versus-empty-collection normalization is not drift."""
    if before == after:
        return True
    empty = ({}, [])
    if before is None and after in empty:
        return True
    return after is None and before in empty


def _walk(before, after, path, out):
    if _equivalent(before, after):
        return
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after), key=str):
            _walk(before.get(key), after.get(key), path + [_segment(key)], out)
    elif (isinstance(before, list) and isinstance(after, list)
            and len(before) == len(after)):
        for index, (old, new) in enumerate(zip(before, after)):
            _walk(old, new, path + [str(index)], out)
    else:
        out.append(path)


def _changed_paths(change):
    """Attribute paths that differ, names only.

    Returns (paths, comparable). comparable is False when the change does not
    carry both a before and an after object (create, delete, or summaries
    without values), so no paths can be derived and the row is never treated
    as noise.
    """
    before, after = change.get("before"), change.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return [], False
    raw = []
    _walk(before, after, [], raw)
    paths = [path for path in raw if path and path[-1] not in NOISE_ATTRIBUTES]
    return paths, True


def _role_name(kind, change):
    """Role identity for the mirror rule; kept internal, never exported."""
    key = "role" if kind == "aws_iam_role_policy" else "name"
    for side in ("after", "before"):
        values = change.get(side)
        if isinstance(values, dict) and isinstance(values.get(key), str) and values[key]:
            return values[key]
    return None


def _collapse_inline_policy_mirror(rows):
    """Collapse the aws_iam_role inline_policy mirror of aws_iam_role_policy rows.

    The provider reports one inline-policy change twice: on the policy resource
    and on the parent role's inline_policy attribute. When a changed policy row
    already describes the same role, the role's inline_policy path is that
    mirror, not a second finding.
    """
    mirrored = {row["_role"] for row in rows
                 if row["resource_type"] == "aws_iam_role_policy" and row["_role"]}
    if not mirrored:
        return rows
    kept = []
    for row in rows:
        if (row["resource_type"] == "aws_iam_role" and row["actions"] == ["update"]
                and row["_role"] in mirrored):
            paths = [path for path in row["changed_paths"]
                     if path and path[0] != "inline_policy"]
            if not paths:
                continue  # the aws_iam_role_policy row already carries this finding
            row = dict(row, changed_paths=paths)
        kept.append(row)
    return kept


def summarize_plan(plan):
    if not isinstance(plan, dict) or str(plan.get("format_version", "")).split(".")[0] != "1":
        raise ValueError("Unsupported Terraform JSON format")
    outputs = plan.get("output_changes", {})
    if not isinstance(outputs, dict):
        raise ValueError("Plan output changes must be an object")
    result = {"schema_version": 2, "source": "terraform-plan",
              "output_changes_count": len(outputs),
              "resource_drift": [], "reconciliation": [],
              "limitations": [
                  "Metadata only; raw attribute values are deliberately excluded.",
                  "No live collection, apply, or effective-permission evaluation was performed.",
                  "Changed-attribute paths are names only; other segments are hashed.",
                  "resource_version and generation churn and null-versus-empty "
                  "normalization are filtered out as noise.",
                  "aws_iam_role inline_policy changes that mirror a changed "
                  "aws_iam_role_policy for the same role are collapsed into it.",
              ]}
    for source, destination in (("resource_drift", "resource_drift"),
                                ("resource_changes", "reconciliation")):
        entries = plan.get(source, [])
        if not isinstance(entries, list):
            raise ValueError("Plan change collections must be arrays")
        rows = []
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError("Plan change entries must be objects")
            change = item.get("change", {})
            if not isinstance(change, dict):
                raise ValueError("Plan changes must be objects")
            actions = change.get("actions", [])
            allowed = {"no-op", "read", "create", "update", "delete", "forget"}
            if not isinstance(actions, list) or any(a not in allowed for a in actions):
                raise ValueError("Unsupported Terraform action")
            if actions == ["no-op"]:
                continue
            address = item.get("address")
            kind = item.get("type")
            if not isinstance(address, str) or not isinstance(kind, str):
                raise ValueError("Resource address and type are required")
            paths, comparable = _changed_paths(change)
            if actions == ["update"] and comparable and not paths:
                continue  # bookkeeping-only churn: not drift
            # Addresses can contain sensitive for_each keys, so export a hash.
            rows.append({
                "address_fingerprint": hashlib.sha256(address.encode()).hexdigest()[:16],
                "resource_type": kind if kind.replace("_", "").isalnum() else "redacted",
                "actions": actions,
                "changed_paths": paths,
                "_role": _role_name(kind, change),
            })
        result[destination] = [
            {key: value for key, value in row.items() if not key.startswith("_")}
            for row in _collapse_inline_policy_mirror(rows)
        ]
    return result


def refresh_only_verdict(exit_code, summary):
    """Classify a `terraform plan -refresh-only -detailed-exitcode` result.

    Exit 2 is not proof of resource drift: output-value changes alone also exit
    2, and noise-only rows are filtered out of the sanitized summary first.
    """
    if exit_code == 0:
        return "clean"
    if exit_code == 1:
        return "error"
    if exit_code == 2:
        return "drift" if summary["resource_drift"] else "no-drift"
    raise ValueError("Unsupported Terraform exit code")


def load_plan(path):
    with open(path, encoding="utf-8") as handle:
        return summarize_plan(json.load(handle))
