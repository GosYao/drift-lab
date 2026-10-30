# Worklog

Running record of what was done, decided, and deliberately not done. Newest first.

## 2026-10-30 — Sanitizer paths and the committed live collector (0.5.0)

### Done

- Verified the GitHub `security-lab` environment lockdown: required reviewer,
  branch-policy rule, custom policies, `main` only.
- Sanitizer upgrade, closing the drift-exercise findings: changed-attribute paths
  (names only, non-identifier segments hashed), `resource_version`/`generation`
  and null-versus-empty noise rows dropped, the `aws_iam_role.inline_policy`
  mirror collapsed into the changed `aws_iam_role_policy` for the same role, and
  `refresh_only_verdict` classifying output-only exit 2 as no-drift. 13 tests.
- Committed the one-off live cross-check as `python -m drift_lab collect`
  (read-only, injectable CLI runner, fail-closed mapping, sanitized snapshots,
  exit codes 0/2/3). Live smoke test against the lab: the first run failed closed
  on the Pod Identity reads; fixed the runner (list, then describe by association
  id) and re-verified: complete collection of all eight tracked resources, clean
  baseline comparison, exit 0. 12 tests.
- `make check`: 75 tests, byte-compile, repository contracts.

### Findings

- `aws eks describe-pod-identity-association` requires `--association-id`;
  service accounts are not a lookup key. The collector lists, then describes.
- The collector's fail-closed design held up live: failed reads produced an
  `incomplete` snapshot (exit 3) with the affected resources omitted, never a
  guessed value or a deletion claim.

### Not done

- Teardown and the up -> down -> up proof; cost recording.
- The preview UI still replays fixtures; `collect` output is not wired into it.

## 2026-10-30 — Live drift exercise (0.4.0)

### Done

- Renewed SSO (user-approved). Took a baseline of `workloads`: accepted the provider
  null-to-empty normalization on the Deployment into state (refresh-only apply), so
  `resource_drift` started empty.
- Injected two out-of-band drifts: an IAM inline-policy edit (support role gains
  `customer-archive`) and a `kubectl patch` of the Deployment's ServiceAccount to
  `reporting-agent`.
- Both were detected by `plan -refresh-only` (resource_drift) and by the normal plan
  (exit 2, 2 updates), and sanitized through `import-plan`. Live reads fed to the
  rules engine gave two HIGH findings and the forbidden-dataset capability path.
- Reconciled with user approval: applied the normal plan (2 changed). The re-plan
  was clean (exit 0); the remaining refresh-only rows were `resource_version`
  noise only.
- Changed the fixture replica range from 2-4 to 1-4 to match the deployed IaC.
  Added a regression test (50 tests).
- Evidence record: `artifacts/validation.md` (sanitized).

### Findings

- The sanitizer reports noise (`resource_version`, null versus empty) the same way
  as real drift. It needs changed-attribute paths and noise filters.
- Refresh-only exit 2 also fires for output-value changes alone.
- IAM inline-policy drift appears on both the policy and the parent role.

### Not done

- Teardown and the up -> down -> up proof; cost recording.
## 2026-10-29 — Phase 1 deployment (0.3.0)

### Done

- Git: initialized `main` and made a GPG-signed first commit (`87f37a8`) with the
  user's key. Created the public repository `GosYao/drift-lab` and pushed. Created
  the `security-lab` environment.
- AWS login via `aws sso login --profile demo-admin` (user-approved in the browser).
- Account check (read-only) before any apply: the profile uses a corporate SSO start
  URL, and the account is not empty. us-east-1 has 5 VPCs and 121 tagged
  resources; ca-central-1 has 3 custom VPCs, 79 tagged resources, and an unrelated
  EKS cluster. I raised this; the user chose to proceed in ca-central-1. There were
  no name collisions. A GitHub OIDC provider already existed, so it is reused.
- Verified the OIDC subject: repositories created after 2026-07-15 use immutable
  subjects. The role trusts
  `repo:GosYao@45461592/drift-lab@1439230701:environment:security-lab`.
- Added an opt-in EKS public endpoint (`public_access_cidrs`, `/32` only; see the
  ADR 0003 amendment) so the laptop can apply `workloads`.
- `foundation`: planned 10 resources, applied, migrated state to S3, re-plan clean.
- `eks-lab`: planned 32, applied 30. The access entry failed because EKS rejects
  the path-less SSO role ARN (the "remove the path" advice applies to `aws-auth`,
  not access entries). Re-applied the remaining 2 with the full ARN.
- Image: built `linux/amd64` on a digest-pinned `python:3.12-slim`, pushed tag
  `87f37a8` (digest `sha256:8351be12…`), and smoke-tested it locally read-only, as
  UID 10001, with all capabilities dropped.
- `workloads`: three fixes found only by a live apply.
  1. The PSA `enforce-version` label must be `v1.36`, not `1.36`.
  2. The Kubernetes provider writes container `runAsNonRoot: false` unless it is
     set explicitly, so restricted Pod Security rejected the pod. Set
     `run_as_non_root = true` on the container.
  3. After the failed rollout, the provider hit an "Unexpected Identity Change" bug
     on the tainted Deployment. Ran `state rm`, deleted the empty Deployment, and
     re-created it.
- Verified the pod, probes, Pod Identity, the enforced default-deny policy, and the
  app via port-forward. All three stacks re-plan with exit 0.

### Findings

- Default-deny egress still allows pod -> local node kubelet (`:10250`).
- ECR basic scan-on-push produced no scan; the account likely uses enhanced
  (Inspector) scanning.

### Not done

- Teardown and the up -> down -> up proof; the live drift exercises; cost recording.
- Removing the public endpoint `/32`.
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
