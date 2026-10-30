# Changelog

Notable changes to this project. The format follows Keep a Changelog; the version
number tracks prototype milestones, not releases to users.

## 0.3.0 — 2026-10-29

Phase 1 sandbox deployment (stacks up; teardown not yet proven).

### Added

- `infra/eks-lab`: `public_access_cidrs` variable (default `[]`, `/32`-only
  validation) for temporary operator access to the EKS API.
- `infra/foundation/backend.tf` (S3 backend, after the local-state bootstrap).

### Fixed

- `infra/workloads`: the Pod Security `enforce-version` label now uses the `v1.x` form.
- `infra/workloads`: the container sets `run_as_non_root = true`, so pods pass
  restricted Pod Security (the provider otherwise sends `false`).
- tfvars examples: the immutable GitHub OIDC subject format, reuse of an existing
  OIDC provider, and the full-path ARN for SSO roles in EKS access entries.

### Deployed

- foundation (10), eks-lab (32), and workloads (14) in `ca-central-1`. All re-plan clean.
## 0.2.0 — 2026-10-29

GitHub-side fixture previews.

### Added

- `drift_lab/github_view.py`: three deterministic GitHub previews built from the
  same engine reports as the drift UI, so cited finding IDs match:
  - **Pull request opened**: check-run list (success, failure, in progress), the
    `infra/workloads/main.tf` diff that broadens the support role, an inline review
    comment on the added line, and a "requested changes" summary comment.
  - **Push to main**: two commits, each with check-runs and a commit comment
    (expected scaling passes; the identity hotfix fails).
  - **Scheduled drift check**: an auto-filed issue with labels, evidence, and a
    comment thread, because runtime drift has no PR to comment on.
- API: `GET /api/triggers` and `GET /api/github?trigger=pr|push|scheduled`.
- UI: a "How it lands on GitHub" panel and a "GitHub signals" nav entry. Every
  comment carries a PREVIEW badge, and the panel states that nothing is sent to GitHub.
- 12 new tests (49 total): fixture boundaries, inline comments anchored to real
  diff lines, finding-ID parity with the engine, check-run shape, and endpoints.
- Screenshots: `artifacts/github-preview-{pr,pr-inline,push,issue}.png`.

## 0.1.0 — 2026-10-29

First working local prototype (Phase 0).

### Added

- `drift_lab` core: five drift scenarios (IAM, identity, scaling, incomplete
  evidence, clean baseline), deterministic comparison and validation engine,
  evidence-backed graph (repository -> Deployment -> ServiceAccount -> pod identity
  -> IAM role -> dataset), and `inconclusive` results on missing evidence.
- Terraform plan sanitizer (hashed address, resource type, change actions only) and
  the `import-plan` CLI command.
- Local preview server at `127.0.0.1:8765` (CSP, Origin check, 4 KB body cap) with a
  static UI: graph, findings, written brief, scenario replay, JSON export.
- Test suite (37 tests) plus repository contract and preflight scripts.
- Checksum-pinned tool bootstrap (Terraform 1.13.5, agent-browser 0.40.0) and a
  `terraform-check` target pinned to `.tools/terraform` with `-input=false`.
- Three Terraform stacks (foundation, eks-lab, workloads) with locked providers
  (AWS 6.71.0, Kubernetes 2.38.0), all passing `fmt -check`, `init -backend=false`,
  and `validate`. No cloud resources were created.
- Documentation: README, STATUS, ARCHITECTURE, RUNBOOK, ROADMAP, WORKLOG, and ADRs
  0001-0003.
