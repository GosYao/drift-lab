# Demo queue → GitHub issues

This is a custom demo integration, not Factory CVE Remediation. It scans the
seeded demo tree, tests policy-changing open branches, reads dated observations,
and asks the queue droid to recommend an order. A person decides. The model
does not change severity, verify fixes, close issues, approve or merge PRs.

## Local entry points

In the trusted `demo/triage-queue` worktree, with Docker running, Terraform,
the Droid CLI and authenticated `gh` on PATH:

```sh
make install
make triage-queue
python3 scripts/queue_issues.py
make queue-issues
```

The first command installs only the application's PyYAML pin, not the seeded
dev dependency. Ranking writes `.triage/queue.md` and `.triage/queue.json`.
The publisher defaults to a no-network preview; `--publish` authorizes writes
only to `GosYao/drift-lab`. `make queue-issues` explicitly supplies that flag.

Issues carry a stable marker keyed by scanner, rule and location, ignoring
line numbers and installed versions. Urgency labels are `fix now`, `fix soon`,
`schedule`, `backlog`, or `unranked` on an unusable model answer. The publisher
updates open issues, preserves unrelated labels and comments, leaves closed
issues closed, and does nothing to findings missing from a later queue.
It never interprets absence as proof of a fix. Duplicate markers fail closed.

Run publishers serially. A checkout-local lock prevents overlapping local
publishes; it is not a distributed lock. The GitHub fallback has its own
concurrency group. Do not run that fallback and the Mac Automation together.

## Automation boundary

The paused cloud Automation targets the registered Mac, not the EKS cluster.
“Run now” works while paused, but the Mac, desktop app/daemon, Docker and
authenticated CLIs must be available. It runs the two explicit Make targets.
The Mac already holds personal CLI authentication; this is not a
credential-isolated production runner. The fallback separates the Factory
credential from the GitHub issue-write token into different jobs.

Seeded PRs #1 and #2 never merge. The fixed PR targets the vulnerable feature
branch. Issue links are references, not automatic closure instructions.
The kubelet row is a dated observation, not a fresh probe.
