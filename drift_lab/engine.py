"""Deterministic comparison and graph construction over sanitized snapshots.

This is not an AWS effective-permissions evaluator. The fixture grant model is
explicitly limited to a list of synthetic tables.
"""

from copy import deepcopy
import hashlib
import json

KINDS = {"agent_tool", "deployment", "service_account", "iam_role", "dataset"}
ATTRIBUTES = {
    "agent_tool": {"workload", "source"},
    "deployment": {"service_account", "replicas", "image"},
    "service_account": {"role"},
    "iam_role": {"read_tables"},
    "dataset": {"classification", "tenant"},
}


def validate(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise ValueError("Unsupported snapshot schema")
    if snapshot.get("mode") not in {"fixture", "sanitized-observation"}:
        raise ValueError("Snapshot must declare its evidence mode")
    collection = snapshot.get("collection", {})
    if collection.get("status") not in {"complete", "incomplete"}:
        raise ValueError("Collection status is required")
    if not isinstance(collection.get("errors"), list):
        raise ValueError("Collection errors must be a list")
    if collection["errors"] and collection["status"] == "complete":
        raise ValueError("A collection with errors cannot be complete")
    if not isinstance(snapshot.get("resources"), list):
        raise ValueError("Resources must be a list")
    identifiers = set()
    for item in snapshot["resources"]:
        if not isinstance(item, dict) or item.get("kind") not in KINDS:
            raise ValueError("Unsupported resource kind")
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError("Resource IDs must be unique nonempty strings")
        identifiers.add(identifier)
        if not isinstance(item.get("name"), str):
            raise ValueError("Resource name is required")
        attrs = item.get("attributes")
        if not isinstance(attrs, dict) or set(attrs) != ATTRIBUTES[item["kind"]]:
            raise ValueError("Resource attributes must match the allowlisted schema")
        for key, value in attrs.items():
            if key == "replicas":
                if type(value) is not int or value < 0:
                    raise ValueError("Replicas must be a nonnegative integer")
            elif key == "read_tables":
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    raise ValueError("Read tables must be a list of resource IDs")
            elif not isinstance(value, str):
                raise ValueError("Attribute values must be strings")
        evidence = item.get("evidence", {})
        if not all(isinstance(evidence.get(key), str)
                   for key in ("source", "reference", "observed_at")):
            raise ValueError("Every resource needs evidence provenance")
    return snapshot


def indexed(snapshot):
    return {item["id"]: item for item in snapshot["resources"]}


def edges(snapshot):
    result = []
    for item in snapshot["resources"]:
        attrs = item["attributes"]
        for field, label in (("workload", "runs as"), ("service_account", "uses"),
                             ("role", "assumes")):
            if field in attrs:
                result.append((item["id"], attrs[field], label))
        for table in attrs.get("read_tables", []):
            result.append((item["id"], table, "read grant"))
    return result


def reachable(snapshot, start, destination):
    graph = {}
    for source, target, _ in edges(snapshot):
        graph.setdefault(source, []).append(target)
    queue = [(start, [start])]
    seen = set()
    while queue:
        node, path = queue.pop(0)
        if node == destination:
            return path
        if node in seen:
            continue
        seen.add(node)
        queue.extend((target, path + [target]) for target in graph.get(node, []))
    return []


def compare(expected, observed):
    validate(expected)
    validate(observed)
    if expected.get("environment") != observed.get("environment"):
        raise ValueError("Cannot compare different environments")
    if expected.get("mode") != observed.get("mode"):
        raise ValueError("Cannot mix fixture and observed evidence")
    before, after = indexed(expected), indexed(observed)
    findings = []
    complete = observed["collection"]["status"] == "complete"
    allowed_range = expected.get("policy", {}).get("approved_replica_range", [2, 4])
    if (not isinstance(allowed_range, list) or len(allowed_range) != 2
            or any(type(v) is not int for v in allowed_range)
            or allowed_range[0] > allowed_range[1]):
        raise ValueError("Invalid approved replica range")
    for identifier in sorted(before.keys() | after.keys()):
        old, new = before.get(identifier), after.get(identifier)
        changes = []
        if old is None:
            changes.append(("resource", None, "newly observed"))
        elif new is None:
            changes.append(("resource", "previously observed", None))
        elif old["kind"] != new["kind"]:
            raise ValueError("Resource kind cannot change for an existing ID")
        else:
            for key in sorted(old["attributes"]):
                previous, current = old["attributes"][key], new["attributes"][key]
                if key == "read_tables":
                    previous, current = sorted(set(previous)), sorted(set(current))
                if previous != current:
                    changes.append((key, previous, current))
        for field, previous, current in changes:
            severity, status = "medium", "potential"
            title = "Tracked configuration changed"
            reason = "Review the observed difference against the approved configuration."
            action = "Review the owner and reconcile through a protected deployment."
            if new is None:
                severity, status = ("high", "potential") if complete else ("unknown", "inconclusive")
                title = "Tracked resource missing" if complete else "Resource could not be observed"
                reason = ("The complete scoped snapshot no longer contains this resource."
                          if complete else "Missing evidence is not evidence of resource deletion.")
            elif old is None:
                title = "Resource not present in the approved snapshot"
                reason = "Ownership and Terraform management status require investigation."
            elif field == "read_tables":
                additions = set(current) - set(previous)
                severity = "high" if additions else "medium"
                title = "IAM read scope expanded" if additions else "IAM read scope reduced"
                reason = ("The normalized policy adds synthetic dataset read grants. "
                          "This is not a full evaluation of AWS effective permissions.")
                action = "Review a fresh reconciliation plan; approved IaC is already restrictive."
            elif field in {"service_account", "role"}:
                severity, title = "high", "Workload identity changed"
                reason = "The live identity relationship differs from the approved deployment."
                action = "Restore the approved identity through the protected workload deployment."
            elif field == "replicas":
                in_range = allowed_range[0] <= current <= allowed_range[1]
                severity, status = ("info", "expected") if in_range else ("medium", "potential")
                title = "Scaling within approved bounds" if in_range else "Scaling outside approved bounds"
                reason = "Scaling is classified separately from permission or identity changes."
                action = "No security reconciliation needed." if in_range else action
            elif field == "image":
                severity, title = "high", "Running image differs from approved release"
                reason = "The observed image cannot be treated as the reviewed application revision."
            item = new or old
            fingerprint = hashlib.sha256(
                json.dumps([identifier, field, previous, current], sort_keys=True).encode()
            ).hexdigest()[:12]
            findings.append({
                "id": "DRIFT-" + fingerprint, "resource_id": identifier,
                "resource_name": item["name"], "field": field,
                "before": previous, "after": current, "title": title,
                "severity": severity, "status": status, "explanation": reason,
                "recommendation": action, "evidence": deepcopy(item["evidence"]),
            })
    # Incomplete scope must remain visible even if all returned resources match.
    if not complete and not any(f["status"] == "inconclusive" for f in findings):
        findings.append({
            "id": "COLLECTION-INCOMPLETE", "resource_id": None,
            "resource_name": "Collection scope", "field": "collection",
            "before": "complete", "after": "incomplete",
            "title": "Collection is incomplete", "severity": "unknown",
            "status": "inconclusive",
            "explanation": "Some required observations are unavailable.",
            "recommendation": "Restore collector access and repeat observation.",
            "evidence": {"source": "collector", "reference": "collection.status",
                         "observed_at": observed.get("observed_at", "unknown")},
        })
    old_edges, new_edges = set(edges(expected)), set(edges(observed))
    all_resources = {**before, **after}
    graph_edges = [
        {"source": source, "target": target, "label": label,
         "state": "unchanged" if edge in old_edges & new_edges else
                  ("added" if edge in new_edges else "removed")}
        for edge in sorted(old_edges | new_edges)
        for source, target, label in [edge]
    ]
    unresolved = sorted({edge["target"] for edge in graph_edges} - set(all_resources))
    if unresolved:
        complete = False
    changed_ids = {f["resource_id"] for f in findings if f["status"] != "expected"}
    return {
        "schema_version": 1, "environment": expected["environment"],
        "mode": observed["mode"], "deployment": deepcopy(expected.get("deployment", {})),
        "observed_at": observed.get("observed_at"),
        "status": "inconclusive" if not complete else
                  ("review_required" if any(f["status"] == "potential" for f in findings)
                   else "no_security_drift_observed"),
        "collection": deepcopy(observed["collection"]),
        "coverage": {
            "tracked_resources": len(before), "observed_resources": len(after),
            "unresolved_references": unresolved,
            "limitations": [
                "Only allowlisted attributes and declared relationships are evaluated.",
                "Policy grants are not AWS effective-permission or network reachability proof.",
                "No live cloud collection or model invocation occurs in fixture mode.",
            ],
        },
        "findings": sorted(findings, key=lambda f: (
            {"high": 0, "unknown": 1, "medium": 2, "info": 3}[f["severity"]], f["id"])),
        "graph": {
            "nodes": [
                {"id": identifier, "kind": item["kind"], "name": item["name"],
                 "state": "unobserved" if identifier not in after else
                          ("changed" if identifier in changed_ids else "unchanged"),
                 "evidence": deepcopy(item["evidence"])}
                for identifier, item in all_resources.items()
            ],
            "edges": graph_edges,
        },
        "analysis": {
            "provider": "deterministic-local-rules", "model_invoked": False,
            "note": "Template explanations, not a Droid-generated investigation.",
        },
    }


def replay(expected, observed):
    """Demonstrate a synthetic grant path, never claim a live exploit."""
    report = compare(expected, observed)
    if report["mode"] != "fixture":
        raise ValueError("Replay is restricted to synthetic fixtures")
    if report["status"] == "inconclusive":
        return {"status": "inconclusive", "simulation_only": True,
                "message": "Required observations are missing; replay cannot establish a result."}
    policy = expected["policy"]
    path = reachable(observed, policy["principal_tool"], policy["forbidden_dataset"])
    return {
        "status": "fixture_violation" if path else "fixture_blocked",
        "simulation_only": True, "path": path,
        "canary": "SYNTHETIC-CUSTOMER-B-RECORD" if path else None,
        "message": ("The fixture grant model permits the forbidden dataset path."
                    if path else "The fixture grant model has no path to the forbidden dataset."),
        "limitations": "Not an LLM attack, AWS permission check, network test, or real email delivery.",
    }
