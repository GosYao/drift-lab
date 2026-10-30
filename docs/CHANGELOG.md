# Changelog

Notable changes to this project. The format follows Keep a Changelog; the version
number tracks prototype milestones, not releases to users.

## 0.7.0 — 2026-10-30

GitHub Actions pull-request workflow with credential-separated Droid review.

### Added

- `.github/workflows/pull-request.yml`: deterministic gates on every PR to
  `main` — `make check`, `make terraform-check` + `make policy-test` (no
  backend, no credentials), Semgrep (OWASP Top 10) and Trivy (vuln + secret)
  from digest-pinned images. Third-party actions are pinned by commit SHA.
- Droid review with separated credentials: a gate job exposes only whether
  `FACTORY_API_KEY` is configured (never its value); the credentialed job runs a
  read-only `droid exec` review with the captured deterministic outcomes and no
  GitHub write token, and uploads the review as an artifact; a separate job
  holding only `GITHUB_TOKEN` (pull-requests: write) posts it. Droid cites the
  deterministic findings and cannot override their verdicts.
- `.github/droid-review-prompt.md`: standing review instructions (cite gates,
  classify drift, never override verdicts, state a verified fix path).

### Accepted

- Semgrep `aws-dynamodb-table-unencrypted` (customer-managed KMS key) is
  accepted inline in `infra/workloads/main.tf`: the tables hold only synthetic,
  disposable drift-test data behind AWS-managed SSE. Scanner runs are
  pre-verified clean locally with the same pinned image digests CI uses.

## 0.6.0 — 2026-10-30

Policy-as-code: capability intent as credential-free Terraform tests.

### Added

- `infra/workloads/policy.tftest.hcl`: five `terraform test` runs against mock
  providers (no account, no credentials), executed in a disposable copy by
  `make policy-test`. They encode the capability intent of the approved revision:
  - `support-agent` reads only `customer-orders`; `reporting-agent` reads
    `customer-orders` and `customer-archive`; both hold only
    `dynamodb:GetItem`/`dynamodb:Query` (no writes, no wildcards).
  - Pod Identity associations are pinned to the matching lab roles; service
    accounts do not automount API tokens.
  - The preview workload runs on the `support-agent` identity, at 1 replica,
    with a digest-pinned image, as non-root, no privilege escalation, a
    read-only root filesystem, and all capabilities dropped.
  - The namespace enforces restricted Pod Security and the default-deny policy
    selects all pods in both directions.
  - Distinct synthetic ARNs are overridden during plan so scope and identity
    assertions compare real differences, not shared generated strings.
- Verified both directions: the suite passes on the approved revision and fails
  (exit 1) on a seeded support-role broadening — the same drift shape as the live
  exercise.
- `make policy-test` target; `.policy-test-tmp/` is gitignored.

## 0.5.0 — 2026-10-30

Sanitized attribute paths and the read-only live collector.

### Added

- `python -m drift_lab collect`: read-only live collector mapping IAM inline
  policies, EKS Pod Identity associations, and the preview Deployment onto the
  engine schema (mode `sanitized-observation`). Injectable CLI runner, fail-closed
  mapping (grants, roles, or service accounts outside the read-only model become
  `incomplete`, never a guess), sanitized snapshots (no ARNs, account IDs, or
  policy statements; images normalized to repository@digest), and machine-readable
  exit codes (0 clean/complete, 2 review required, 3 inconclusive/incomplete).
  `--baseline` compares a fresh collection against an approved snapshot. Verified
  live against the ca-central-1 lab: complete collection, clean comparison.
- `configs/collector.json`: committed lab topology (non-secret names only).
- `refresh_only_verdict`: classifies refresh-only exit codes against the sanitized
  summary, so output-only changes (exit 2) are not drift.

### Changed

- Plan sanitizer (schema v2): changed-attribute paths exported as names only
  (non-identifier segments hashed), `resource_version`/`generation` and
  null-versus-empty noise rows dropped, the `aws_iam_role.inline_policy` mirror of
  a changed `aws_iam_role_policy` for the same role collapsed, and output changes
  counted without values.
- 25 new tests (75 total).

## 0.4.0 — 2026-10-30

Live drift exercise.

### Changed

- The fixture `approved_replica_range` is now `[1, 4]` (the engine default too),
  matching the 1-replica Deployment in `infra/workloads`. The scaling text and the
  GitHub push preview are updated to match.

### Added

- `test_replica_range_matches_deployed_iac` (50 tests total).
- `artifacts/validation.md`: sanitized record of the live IAM and ServiceAccount
  drift detection and reconciliation.
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
