"""Fixture previews of how the deterministic checks would land on GitHub.

Nothing here authenticates to GitHub, calls its API, or writes to a repository.
Each payload is a template built from the same deterministic reports that power
the drift UI, so the finding IDs cited in comments and check summaries match the
IDs produced by ``drift_lab.engine.compare`` for the linked fixture scenario.
"""

import json

from .engine import compare, replay
from .scenarios import STAMP, scenario

DISPLAY_TIME = "Oct 29, 2026"

TRIGGERS = [
    {"id": "pr", "name": "Pull request opened", "description":
     "Inline review comments and check-run status on a PR that broadens IAM scope."},
    {"id": "push", "name": "Push to main", "description":
     "Check-runs and commit comments for two commits pushed to the default branch."},
    {"id": "scheduled", "name": "Scheduled drift check", "description":
     "Runtime drift found after deploy files an issue; there is no PR to comment on."},
]

PREVIEW = {
    "fixture": True,
    "rendered_at": STAMP,
    "note": "Fixture preview rendered locally. No GitHub API call, token, or write.",
}

ANALYSIS = {
    "provider": "deterministic-local-rules",
    "model_invoked": False,
    "note": "Template text generated from fixture rules; no GitHub write occurred.",
}


def paragraph(text):
    return {"kind": "paragraph", "text": text}


def listing(items):
    return {"kind": "list", "items": items}


def code(text):
    return {"kind": "code", "text": text}


def show(value):
    return value if isinstance(value, str) else json.dumps(value)


def finding_for(name, field):
    report = compare(*scenario(name))
    for item in report["findings"]:
        if item["field"] == field:
            return item
    raise ValueError("Expected fixture finding is missing: " + field)


# Faithful to infra/workloads/main.tf lines 71-82; the PR broadens the
# support-agent role policy to also read customer-archive.
PR_DIFF_FILE = {
    "path": "infra/workloads/main.tf", "additions": 2, "deletions": 1,
    "hunks": [{
        "header": '@@ -71,11 +71,12 @@ resource "aws_iam_role_policy" "agent" {',
        "lines": [
            {"origin": " ", "old_line": 71, "new_line": 71,
             "text": '    Version = "2012-10-17"'},
            {"origin": " ", "old_line": 72, "new_line": 72,
             "text": "    Statement = [{"},
            {"origin": " ", "old_line": 73, "new_line": 73,
             "text": '      Effect    = "Allow"'},
            {"origin": " ", "old_line": 74, "new_line": 74,
             "text": '      Action    = ["dynamodb:GetItem", "dynamodb:Query"]'},
            {"origin": " ", "old_line": 75, "new_line": 75,
             "text": '      Resource = each.key == "support-agent" ? ['},
            {"origin": "-", "old_line": 76, "new_line": None,
             "text": '        aws_dynamodb_table.synthetic["customer-orders"].arn'},
            {"origin": "+", "old_line": None, "new_line": 76,
             "text": '        aws_dynamodb_table.synthetic["customer-orders"].arn,'},
            {"origin": "+", "old_line": None, "new_line": 77,
             "text": '        aws_dynamodb_table.synthetic["customer-archive"].arn'},
            {"origin": " ", "old_line": 77, "new_line": 78,
             "text": "        ] : ["},
            {"origin": " ", "old_line": 78, "new_line": 79,
             "text": '        aws_dynamodb_table.synthetic["customer-orders"].arn,'},
            {"origin": " ", "old_line": 79, "new_line": 80,
             "text": '        aws_dynamodb_table.synthetic["customer-archive"].arn'},
            {"origin": " ", "old_line": 80, "new_line": 81, "text": "      ]"},
            {"origin": " ", "old_line": 81, "new_line": 82, "text": "    }]"},
        ],
    }],
}


def pull_request_payload():
    """PR trigger: check-runs plus an inline review comment and a summary."""
    finding = finding_for("iam", "read_tables")
    replayed = replay(*scenario("iam"))
    inline_comment = {
        "author": "droid[bot]", "initials": "D",
        "relationship": "requested changes", "posted_at": DISPLAY_TIME,
        "path": PR_DIFF_FILE["path"], "line": 77, "side": "RIGHT",
        "body": [
            paragraph("This line adds customer-archive to the support role's read "
                      "scope. After merge, support-reader — assumed by the "
                      "support-agent workload — gains DynamoDB read access to "
                      "customer-archive (tenant customer-b)."),
            paragraph("Capability chain: tool:lookup → deployment:support → "
                      "sa:support → role:support → table:archive. The approved tool "
                      "contract (sample-app/tools.py lookup_order) reads "
                      "customer-orders only."),
            paragraph("Deterministic finding {}: {} ({}). The verdict is "
                      "rule-based; a model would only explain the evidence or "
                      "draft a fix after it.".format(
                          finding["id"], finding["title"], finding["severity"].upper())),
        ],
    }
    summary_comment = {
        "author": "droid[bot]", "initials": "D",
        "relationship": "requested changes", "posted_at": DISPLAY_TIME,
        "body": [
            paragraph("Requested changes. Comparing this head revision against the "
                      "approved revision (fixture:approved-v1) found one "
                      "security-relevant difference."),
            paragraph("Merging gives support-reader read access to customer-archive "
                      "(tenant customer-b). The approved baseline scopes that table "
                      "to reporting-reader, so the support workload would reach data "
                      "it does not need."),
            listing([
                "{} — {}: read_tables {} → {}".format(
                    finding["id"], finding["title"],
                    show(finding["before"]), show(finding["after"])),
                "Fixture replay: {} (canary {}).".format(
                    replayed["message"].rstrip("."), replayed["canary"]),
                "Allowlist comparison over declared resources, not an AWS "
                "effective-permissions evaluation.",
            ]),
            paragraph("If the archive lookup is intentional, split it into a "
                      "separately reviewed role instead of broadening support-reader. "
                      "The verified-fix check can draft that change once the impact "
                      "is confirmed."),
        ],
    }
    check_runs = [
        {"name": "terraform-validate / workloads", "status": "completed",
         "conclusion": "success",
         "summary": "fmt -check and init -backend=false + validate passed on the "
                    "PR revision."},
        {"name": "semgrep / config", "status": "completed", "conclusion": "success",
         "summary": "No new findings with the repository ruleset."},
        {"name": "trivy / config", "status": "completed", "conclusion": "success",
         "summary": "No new misconfigurations in the scanned IaC."},
        {"name": "droid / drift-capability", "status": "completed",
         "conclusion": "failure",
         "summary": "{}: IAM read scope expanded on role:support — 1 "
                    "security-relevant difference vs the approved revision.".format(
                        finding["id"])},
        {"name": "droid / verified-fix", "status": "in_progress", "conclusion": None,
         "summary": "Standing by to draft a suggested change; in preview mode "
                    "nothing is posted."},
    ]
    return {
        "schema_version": 1, "kind": "pull_request",
        "trigger": {"id": "pr", "name": "Pull request opened"},
        "frame": {
            "description": "A pull request broadens the support role's read scope. "
                           "Check-runs report status before merge, and the review "
                           "lands as an inline comment plus a summary.",
        },
        "preview": PREVIEW, "analysis": ANALYSIS,
        "pull_request": {
            "number": 42, "title": "Add archive lookup to the support agent",
            "author": "gyao", "state": "Open",
            "branch": "feature/archive-lookup", "base": "main", "head": "9f2c7a1",
            "commits": 1, "files_changed": 1, "additions": 2, "deletions": 1,
        },
        "checks": {
            "overall": {"conclusion": "failure",
                        "summary": "1 failing check · 3 passing · 1 in progress"},
            "runs": check_runs,
        },
        "diff": {"files": [PR_DIFF_FILE]},
        "review": {
            "state": "CHANGES_REQUESTED",
            "summary_comment": summary_comment,
            "inline": [inline_comment],
        },
    }


def push_payload():
    """Push trigger: a check-run row per commit plus commit comments."""
    scaling = finding_for("scaling", "replicas")
    identity = finding_for("identity", "service_account")
    commits = [
        {
            "sha": "e4a91c2", "message": "Scale preview deployment to 3 replicas",
            "author": "gyao", "initials": "G",
            "checks": {
                "overall": {"conclusion": "success",
                            "summary": "All checks passed · 2 checks"},
                "runs": [
                    {"name": "terraform-validate / workloads", "status": "completed",
                     "conclusion": "success",
                     "summary": "fmt -check and init -backend=false + validate passed."},
                    {"name": "droid / drift-policy", "status": "completed",
                     "conclusion": "success",
                     "summary": "{}: replicas 2 → 3 stays inside the approved range "
                                "[2, 4] — expected, recorded.".format(scaling["id"])},
                ],
            },
            "comments": [{
                "author": "droid[bot]", "initials": "D",
                "relationship": "commented on commit e4a91c2",
                "posted_at": DISPLAY_TIME,
                "body": [
                    paragraph("Checked against the approved revision: replicas 2 → 3 "
                              "stays inside the approved range [2, 4]. Recorded as {} "
                              "— expected, no security reconciliation needed.".format(
                                  scaling["id"])),
                    paragraph("Expected scaling is tracked separately from permission "
                              "and identity changes, so this commit does not raise an "
                              "alert."),
                ],
            }],
        },
        {
            "sha": "7b3f0d8",
            "message": "hotfix: point support-agent at reporting-agent",
            "author": "gyao", "initials": "G",
            "checks": {
                "overall": {"conclusion": "failure",
                            "summary": "1 failing check · 1 in progress"},
                "runs": [
                    {"name": "terraform-validate / workloads", "status": "in_progress",
                     "conclusion": None, "summary": "Queued behind the drift-policy "
                                                    "report."},
                    {"name": "droid / drift-policy", "status": "completed",
                     "conclusion": "failure",
                     "summary": "{}: workload identity changed — support-agent now "
                                "uses reporting-agent.".format(identity["id"])},
                ],
            },
            "comments": [{
                "author": "droid[bot]", "initials": "D",
                "relationship": "commented on commit 7b3f0d8",
                "posted_at": DISPLAY_TIME,
                "body": [
                    paragraph("The Deployment support-agent now runs as service "
                              "account reporting-agent, which assumes reporting-reader. "
                              "That role reads customer-archive (tenant customer-b); "
                              "the approved baseline scopes the support workload to "
                              "support-reader and customer-orders only."),
                    paragraph("Deterministic finding {}: {} ({}). Capability chain "
                              "after this commit: tool:lookup → deployment:support → "
                              "sa:reporting → role:reporting → table:archive.".format(
                                  identity["id"], identity["title"],
                                  identity["severity"].upper())),
                    paragraph("If the identity switch is intentional, re-approve the "
                              "revision and let the scheduled drift check confirm the "
                              "live cluster matches it. Otherwise revert this commit; "
                              "do not hotfix the cluster out-of-band."),
                ],
            }],
        },
    ]
    return {
        "schema_version": 1, "kind": "push",
        "trigger": {"id": "push", "name": "Push to main"},
        "frame": {
            "description": "Two commits hit the default branch. Each commit gets "
                           "check-run status; the harmless scaling change passes, "
                           "while the identity hotfix fails and gets a commit comment.",
        },
        "preview": PREVIEW, "analysis": ANALYSIS,
        "push": {"branch": "main", "pusher": "gyao", "before": "c81e4f2",
                 "commits": commits},
    }


def scheduled_payload():
    """Scheduled trigger: runtime drift has no PR, so the run files an issue."""
    finding = finding_for("iam", "read_tables")
    issue = {
        "number": 57,
        "title": "Drift detected: support-reader can read customer-archive",
        "author": "droid[bot]", "initials": "D", "state": "Open",
        "opened_at": DISPLAY_TIME,
        "meta": "Filed by the scheduled drift run (fixture:drift-daily); runtime "
                "drift has no pull request to comment on.",
        "labels": [
            {"id": "security", "name": "security"},
            {"id": "drift", "name": "drift"},
            {"id": "automation", "name": "auto-filed"},
        ],
        "body": [
            paragraph("The scheduled check compared the observed cluster against "
                      "the approved revision (fixture:approved-v1) and found one "
                      "security-relevant difference. An issue is filed because "
                      "runtime drift is detected after deploy, with no pull request "
                      "to review."),
            listing([
                "{} — {} ({}): role:support read_tables {} → {}".format(
                    finding["id"], finding["title"], finding["severity"].upper(),
                    show(finding["before"]), show(finding["after"])),
                "Observation provenance: {} · {} · {}".format(
                    finding["evidence"]["source"],
                    finding["evidence"]["reference"],
                    finding["evidence"]["observed_at"]),
                "Coverage note: scoped attribute comparison, not an AWS "
                "effective-permissions evaluation.",
            ]),
            paragraph("Capability chain after drift: tool:lookup → "
                     "deployment:support → sa:support → role:support → "
                     "table:archive. Reconciliation happens through a protected "
                     "deployment or a re-approval of the revision; no automatic "
                     "remediation runs without authorization."),
            code("# Re-run the deterministic comparison locally (fixture mode)\n"
                 "make report   # python -m drift_lab report --scenario iam"),
        ],
    }
    return {
        "schema_version": 1, "kind": "issue",
        "trigger": {"id": "scheduled", "name": "Scheduled drift check"},
        "frame": {
            "description": "Runtime drift is found after deploy. With no pull "
                           "request to comment on, the scheduled run files an issue "
                           "carrying the same deterministic evidence.",
        },
        "preview": PREVIEW, "analysis": ANALYSIS,
        "source_scenario": "iam",
        "issue": issue,
        "comments": [
            {
                "author": "gyao", "initials": "G", "relationship": "maintainer",
                "posted_at": DISPLAY_TIME,
                "body": [
                    paragraph("Nobody on the team claims this policy edit. Pinned "
                              "the issue; treating it as an out-of-band change until "
                              "proven otherwise."),
                ],
            },
            {
                "author": "droid[bot]", "initials": "D", "relationship": "assistant",
                "posted_at": DISPLAY_TIME,
                "body": [
                    paragraph("The out-of-band edit adds customer-archive to "
                              "support-reader. The approved revision still scopes that "
                              "role to customer-orders, so a reconciliation plan would "
                              "revert exactly this grant."),
                    paragraph("Next step, which requires authorization: run the "
                              "protected deployment to restore the approved role "
                              "policy, then re-run this check to confirm the live "
                              "cluster matches the approved revision."),
                ],
            },
        ],
    }


BUILDERS = {"pr": pull_request_payload, "push": push_payload,
            "scheduled": scheduled_payload}


def preview(identifier):
    if identifier not in BUILDERS:
        raise ValueError("Unknown trigger")
    return BUILDERS[identifier]()
