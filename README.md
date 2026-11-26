# Drift Lab

An evidence-first prototype that shows how Droid adds value on top of deterministic
cloud checks. Droid does not replace scanners or Terraform. It orchestrates them,
connects findings to code and identity changes, validates evidence deterministically,
and explains impact with a scoped, verified remediation.

The engine and UI run locally in fixture mode. A Phase 1 lab (EKS in `ca-central-1`)
has been deployed with explicit authorization; see `docs/STATUS.md` for what is live
and what is not. Cloud steps are authorization-gated and documented in
`docs/RUNBOOK.md`.

## What the prototype demonstrates

- Five replayable drift scenarios: IAM policy drift, ServiceAccount/pod-identity
  drift, a harmless scaling change, missing evidence, and a clean baseline.
- A deterministic engine that refuses to guess: missing evidence produces an
  `inconclusive` result, never a fabricated finding or graph edge.
- A small evidence-backed graph: repository -> Deployment -> ServiceAccount ->
  pod identity -> IAM role -> dataset.
- A Terraform plan sanitizer: raw state and plans never reach reports or a model;
  only hashed addresses, resource types, change actions, and changed-attribute
  names survive.
- A read-only live collector (`python -m drift_lab collect`): IAM, Pod Identity,
  and Kubernetes reads mapped onto the same sanitized schema, failing closed on
  anything outside the read-only model (verified live; see `docs/RUNBOOK.md`).
- Policy-as-code: capability intent (read scope, identity pinning, workload
  hardening, namespace isolation) asserted by credential-free `terraform test`
  runs with mock providers; a seeded IAM broadening fails them.
- A pull-request workflow where deterministic gates decide and a read-only
  Droid review with separate credentials explains the findings instead of
  re-deciding them: one review packet per finding over computed evidence
  (scanner output, gate outcomes, chained exposure, diff), with a fail-safe
  that keeps the scanner's severity when the model cannot answer.
- A verified-fix loop: on `fix/` branches a Stop hook and a pipeline job run
  the same gates (no new suppression, a regression test that fails on the base
  and passes after, the unit suite, the policy test, both pinned scanners), so
  "fixed" is a reproducible state a person approves, not a model's claim.
- A local preview UI with the graph, findings, a written brief, scenario replay,
  and JSON export.
- Three Terraform stacks (foundation, EKS lab, workloads) with an explicit security
  baseline, applied in a sandbox lab (teardown proof pending).

## Quick start

```make
make preview          # serve the UI at http://127.0.0.1:8765 (Ctrl-C to stop)
make test             # unit tests; stdlib only, no cloud access
make check            # tests + byte-compile + repository contract checks
make terraform-check  # terraform fmt -check + init -backend=false + validate
make policy-test      # capability-intent terraform tests; mock providers, no credentials
make report           # print the iam scenario report as JSON
make preflight        # local environment preflight
make scan             # Semgrep + Trivy from the pinned images (needs Docker)
make triage           # one review packet per finding (needs the droid CLI)
make verify-fix       # the gates a security fix must pass
make install          # install requirements.txt into .venv, when a branch has one
make demo-reset       # clear Stop-hook state and scratch directories
```

Python 3.9+ is the only runtime requirement on main. A branch that adds a
dependency pins it in `requirements.txt`; `make install` installs it into
`.venv` and the tooling (tests, verifier) uses that interpreter automatically. `scripts/bootstrap_local_tools.py`
installs checksum-pinned Terraform 1.13.5 and agent-browser 0.40.0 into `.tools/`
if you want the exact versions this prototype was validated with.

## Repository layout

| Path | Purpose |
| ---- | ------- |
| `drift_lab/` | Local engine: scenarios, comparison, plan sanitizer, collector, server, UI |
| `tests/` | `unittest` suite (engine, sanitizer, collector, server) |
| `configs/` | Lab topology for the live collector (non-secret names only) |
| `.github/` | PR workflow: deterministic gates + verify-fix + credential-separated review packets |
| `scripts/` | Preflight, repository contracts, tool bootstrap, scanner runner, triage packets, chained exposure, fix verifier |
| `.factory/` | The agent harness: triage and fix droids with named models, and the Stop hook that runs the verifier |
| `infra/foundation` | State bucket, ECR, GitHub OIDC observer role, budget |
| `infra/eks-lab` | VPC, private-endpoint EKS cluster, managed node group |
| `infra/workloads` | Namespace, service accounts, Pod Identity roles, synthetic tables, preview app |
| `docs/` | Status, architecture, ADRs, runbook, roadmap, changelog, worklog, demo script |
| `artifacts/` | Generated exports (screenshots, sanitized reports, interactive demo page, slide deck) |
| `Dockerfile` | Preview container image; built and published only during Phase 1 |

## Ground rules

See `AGENTS.md` for the full set. The short version:

- Detection and graph construction are deterministic. A model may explain evidence;
  it cannot fabricate graph edges or make the trusted validation decision.
- Fixture replay is labeled as fixture replay, never described as live collection or
  exploitation.
- No AWS provisioning, GitHub writes, or automatic reconciliation without explicit
  authorization.
- Raw Terraform state and plans never enter reports or prompts; the sanitizer runs
  first.
- No suppressions to turn a check green; a security fix needs a regression test
  that fails before and passes after, and `make verify-fix` must say VERIFIED.
- Infrastructure planning uses the approved deployment revision, not PR-supplied
  code. Application, deployment, and publishing credentials stay separate.

## Documentation

- `docs/STATUS.md` — what works today, what does not, what is next
- `docs/ARCHITECTURE.md` — components, data flow, trust boundaries
- `docs/adr/` — accepted decisions and rationale
- `docs/RUNBOOK.md` — local and (future) cloud operating procedures
- `docs/ROADMAP.md` — phase plan with exit criteria
- `docs/CHANGELOG.md` / `docs/WORKLOG.md` — what changed, and how
