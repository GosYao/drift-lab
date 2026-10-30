# Worklog

Running record of what was done, decided, and deliberately not done. Newest first.

## 2026-10-29 — GitHub-side previews (0.2.0)

### Done

- Added `drift_lab/github_view.py` with three trigger fixtures (PR review, push
  check-runs and commit comments, scheduled drift issue). Comment text is
  template-generated from `engine.compare`/`engine.replay` output, and the
  PR diff follows the real `infra/workloads/main.tf` lines 71-82.
- Added `/api/triggers` and `/api/github` routes, the UI panel, styles, and 12 tests.
  `make check` passes: 49 tests, compileall, and repository contracts.
- Restarted the preview server. Verified all three triggers through agent-browser
  snapshots and captured screenshots (`artifacts/github-preview-*.png`). Screenshot
  capture worked this time, which resolves the earlier screenshot follow-up for
  this view.

### Decisions

- Scheduled drift files an issue instead of a PR comment, because runtime drift is
  found after deploy and has no diff to annotate.
- Check verdicts come from the deterministic finding. Comment prose only explains it.
- The Semgrep and Trivy check-runs are illustrative fixture rows. Those scanners
  have not run in this repository yet.

### Not done

- No GitHub App, workflow, token, or API call. Nothing was posted to any repository.
  Real publishing needs a control repository, app permissions (checks:write,
  pull-requests:write, issues:write), and authorization.

## 2026-10-29

### Done

- Scaffolded the repository: `AGENTS.md` (ground rules), `Makefile`, `Dockerfile`,
  `.dockerignore`, `.gitignore`, `artifacts/`.
- Built the local prototype: `drift_lab/` (scenario fixtures, deterministic engine,
  plan sanitizer, HTTP server, CLI, static UI) and the test suite — 37 tests
  passing.
- Added `scripts/preflight.py`, `scripts/check_repository.py`, and
  `scripts/bootstrap_local_tools.py`; installed checksum-pinned Terraform 1.13.5 and
  agent-browser 0.40.0 under `.tools/` and verified both.
- Authored three Terraform stacks; applied `terraform fmt`; created provider lock
  files. All stacks pass `init -backend=false` + `validate` (AWS pinned 6.71.0,
  Kubernetes pinned 2.38.0). No AWS API call was made and no backend was configured.
- Ran the preview server locally; confirmed pages and the API respond on
  `127.0.0.1:8765`; captured an agent-browser accessibility snapshot of the UI.
- Wrote the documentation set (README, STATUS, ARCHITECTURE, RUNBOOK, ROADMAP,
  CHANGELOG, ADRs 0001-0003). Pinned `make terraform-check` to `.tools/terraform`
  with `-input=false`, and removed a stray `@import` line from `styles.css`.
- Extended `scripts/preflight.py` to report pinned `.tools/` binaries, so Terraform
  is not reported missing when it is used from `.tools/` instead of PATH.

### Decisions

- Evidence-first architecture (ADR-0001): the deterministic engine decides; models
  only explain; `inconclusive` is a valid outcome; sanitize before any boundary
  crossing.
- Three Terraform stacks with strict apply/destroy order (ADR-0002); S3 native
  lockfile; `prevent_destroy` state bucket.
- EKS baseline (ADR-0003): Pod Identity, private API endpoint, IMDSv2, restricted
  namespace, default-deny NetworkPolicy, digest-pinned image.
- EKS over Lambda to showcase Kubernetes-flavored drift; Terraform for repeatable
  up/down/up; drift detection via `plan -refresh-only` and plan-JSON exit codes;
  remediation may be reconciliation rather than a PR; no claim of Wiz-style feature
  parity.

### Checks that failed or were skipped (recorded, not hidden)

- agent-browser viewport sizing: not controllable from this Factory pane — skipped.
- UI screenshot: failed twice (daemon read stall, `Resource temporarily unavailable`); no image artifact saved. The page itself loads and snapshots fine, so the failure is specific to screenshot capture.
- `terraform plan` against AWS: not run (no credentials, no authorization, no
  backend).
- Docker image build/push: not run; the Deployment's image digest does not exist yet.
- Live AWS/Kubernetes collection and Droid workflow integration: not implemented in
  Phase 0 (fixtures only, by design).
- Git initialization/commit: not done; the directory is not a repository yet.

### Known risks

- Default-deny NetworkPolicy vs kubelet probes (readiness/liveness) is untested
  until deployed; probes may need an explicit allowance.
- Default-deny egress blocks DynamoDB/Bedrock for any real agent; Pod Identity
  credential delivery under this policy is unverified. A reviewed allow-list is
  required before a real workload.
- CNI network-policy enforcement relies on node-role CNI permissions at bootstrap;
  move CNI to a dedicated identity before untrusted workloads.
- Private EKS API endpoint requires in-VPC access for administration and for the
  `workloads` apply.
- Budget is reporting-only (no alerts yet); `expires_at` tags are advisory until a
  cleanup controller exists.

### Follow-ups

- Initialize git and make the first commit (include `.terraform.lock.hcl` files;
  `.gitignore` already excludes `.terraform/`, state, and tfvars while keeping
  `*.tfvars.example`).
- Decide the control repository, GitHub environment, and exact OIDC subject; verify
  GitHub's current subject-claim format before any foundation apply.
- Get explicit authorization for Phase 1: apply order, image publish, up -> down ->
  up proof, probe/NetworkPolicy verification.
- Retry the UI screenshot for `artifacts/preview.png` (try headed mode or an alternate capture tool; the CLI snapshot path works).
- Phase 2: read-only AWS/Kubernetes collectors emitting the same evidence shape as
  the fixtures.
