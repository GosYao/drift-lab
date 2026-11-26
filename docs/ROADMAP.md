# Roadmap

Phases have exit criteria. A phase is complete when its criteria are demonstrated,
not when its code is written. Nothing here authorizes cloud deployment by itself;
every cloud-touching phase needs explicit approval first.

## Phase 0 — local prototype (complete)

Evidence-first engine, five scenarios, plan sanitizer, local UI, tests, repository
checks, three validated Terraform stacks, pinned tooling.

Exit criteria (met): `make test`, `make check`, and `make terraform-check` pass
without cloud credentials; the UI renders every scenario with honest provenance
labels; no AWS API was called.

## Phase 1 — authorized sandbox deployment

Apply foundation -> eks-lab -> workloads in the dedicated account; migrate backends;
publish the preview image to ECR by digest; prove up -> down -> up. Verify kubelet
probes, addon startup, and Pod Identity association under the default-deny
NetworkPolicy. Capture real drift evidence: a baseline plan, then two approved manual
drifts (IAM policy and ServiceAccount/pod identity), each detected with
`plan -refresh-only` and plan-JSON drift fields, sanitized through `import-plan`.

Exit criteria: full up -> down -> up reproduced at least twice; both drift scenarios
detected from live evidence; teardown leaves no orphaned resources; actual monthly
cost recorded against the budget.

## Phase 2 — real collectors

Read-only AWS and Kubernetes collectors (IAM roles/policies, Pod Identity
associations, ServiceAccounts, live resource attributes) that emit the same evidence
shape as the fixtures. Extend the observer role only with review. Collectors must
fail safe: missing evidence -> `inconclusive`, never a guess.

Started 2026-10-30: `python -m drift_lab collect` performs the operator-side
collection live (laptop credentials, not the GitHub observer role) and was
verified against the lab with a clean baseline comparison. The observer-role path
and the UI wiring are still open.

Exit criteria: end-to-end drift detection from live collection to UI brief with no
fixture in the hot path; collector tests run against sanitized recordings.

## Phase 3 — Droid integration

Wire drift events into a Droid workflow: on detection, Droid fetches the sanitized
evidence, explains impact against the graph, and proposes a verified fix (pull
request or reconciliation). Every fix must pass the same deterministic validation
before it is called verified; remediation may be reconciliation rather than a PR.

Started 2026-10-30: the deterministic validation gate now includes capability-intent
Terraform tests (`make policy-test`, mock providers, credential-free); a seeded
support-role broadening fails them. A pull-request workflow (0.7.0) runs the
deterministic gates and a credential-separated, read-only Droid review that
cites their outcomes instead of re-deciding them. The arm is verified
end-to-end (0.7.2): the posted review cited the failing assertion, classified
the seed, and ended `VERDICT: request changes`.

Exit criteria: at least one live drift handled end-to-end with a verified fix; cost
per verified fix measured and recorded.

## Phase 4 — benchmark

Three arms: scanners only; scanners plus an ordinary Droid security review; scanners
plus this evidence-first pipeline. Report finding quality, time to verified fix, and
cost per verified fix, with honest caveats about scenario coverage.

Exit criteria: a repeatable benchmark script and a written report.

## Phase 5 — beyond the prototype

Azure/GCP targets, human-gated automatic reconciliation, multi-account evidence
graphs, depth toward Wiz-style security graphs (without claiming parity), and
hardening (rate limits, audit trail, least-privilege refinement).

Exit criteria: to be agreed with the user; the prototype does not pre-commit to any
of these.
