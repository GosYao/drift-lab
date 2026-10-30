"""Allowlist-only extraction of metadata from Terraform's plan JSON.

The raw plan can contain secrets. This intentionally discards attribute values,
outputs, variables, provider configuration and resource IDs before model export.
"""

import hashlib
import json


def summarize_plan(plan):
    if not isinstance(plan, dict) or str(plan.get("format_version", "")).split(".")[0] != "1":
        raise ValueError("Unsupported Terraform JSON format")
    result = {"schema_version": 1, "source": "terraform-plan",
              "resource_drift": [], "reconciliation": [],
              "limitations": [
                  "Metadata only; raw attribute values are deliberately excluded.",
                  "No live collection, apply, or effective-permission evaluation was performed.",
              ]}
    for source, destination in (("resource_drift", "resource_drift"),
                                ("resource_changes", "reconciliation")):
        entries = plan.get(source, [])
        if not isinstance(entries, list):
            raise ValueError("Plan change collections must be arrays")
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError("Plan change entries must be objects")
            change = item.get("change", {})
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
            # Addresses can contain sensitive for_each keys, so export a hash.
            result[destination].append({
                "address_fingerprint": hashlib.sha256(address.encode()).hexdigest()[:16],
                "resource_type": kind if kind.replace("_", "").isalnum() else "redacted",
                "actions": actions,
            })
    return result


def load_plan(path):
    with open(path, encoding="utf-8") as handle:
        return summarize_plan(json.load(handle))
