# Worklog

Running record of what was done, decided, and deliberately not done. Newest first.

## 2026-10-30 — Droid review arm verified end-to-end (0.7.2)

### Done

- User set `FACTORY_API_KEY` as a repository secret; re-triggered seeded PR #1
  (empty commit f8f50cf). The full arm ran as designed:
  - `droid availability`: pass — reports the key as configured (boolean only;
    the value never left the secret store)
  - `droid review (read-only)`: pass, 57s — captures `make check` (exit 0,
    75 tests + contracts) and `make policy-test` (exit 2), runs the read-only
    `droid exec` review with those outcomes and the standing prompt, uploads
    the review as an artifact
  - `post droid review`: pass, 5s — the token-only job posts the review as a
    PR comment
- The posted review behaved as the design intends:
  - cites the deterministic gate, run, exact assertion condition, and assertion
    text — it does not re-decide the verdict
  - classifies the seed correctly: a proposed intent change, not out-of-band
    drift or noise; an approved expansion would have to update the capability
    baseline, and this seed does not
  - states the evidence is mock-provider verification, not live AWS access
  - notes the merge-ref nuance (workspace HEAD carries main's later commits)
    without inventing issues from it
  - ends with the required single line, `VERDICT: request changes`, and a
    verified fix path: restore the conditional, re-run `make policy-test`, all
    five runs pass without weakening assertions

### Verified

- PR #1 stays open as the live demo: all deterministic gates green except the
  seeded capability failure, and the Droid review posted citing exactly that
  failure. The workflow never plans or applies against AWS, and no job holds
  both the Factory key and a GitHub write token.

## 2026-10-30 — First live PR run: the scanner caught the pipeline itself (0.7.1)

### Done

- Opened verification PR #1, seeded with the 0.6.0 support-role read
  broadening (deliberate regression, never to be merged). First live run of
  the 0.7.0 workflow:
  - `make check`: pass
  - `terraform-check + policy-test`: fail — run
    `support_agent_reads_only_orders` fails on "support-agent must read only
    the customer-orders table"; the other four capability runs pass
  - `trivy`: pass
  - `droid availability`: pass (it reports only whether FACTORY_API_KEY is
    configured, never the value)
  - `droid review (read-only)` and `post droid review`: skipped, as designed
  - `semgrep`: fail — a real finding, below
- The Semgrep finding: `gha-curl-pipe-shell` on the new workflow's Droid CLI
  install step. Local pre-verification on 0.7.0 could not see it: the scanner
  ran before the workflow file existed. CI scanning the new file activated the
  yaml.github-actions rules (286 to 310 rules, 54 to 56 files) and the pattern
  matched. The deterministic scanner caught a genuine supply-chain pattern in
  the very change that introduced the scanning — the prototype's thesis
  applied to itself.

### Decision

- Accepted inline (annotation on the `run: |` match line, rationale in the
  workflow): the Factory CLI install is the vendor's documented path, over
  TLS from the vendor's own domain, on an ephemeral runner, in a job whose
  only credential is the FACTORY_API_KEY that same vendor issued.
  Download-then-exec would hide the identical trust from the scanner without
  reducing it — a scanner pass bought by laundering the pattern. The inline
  annotation keeps the acceptance visible at the source line instead.
- Not chosen: `--skip-rule` (would silence the pattern for future workflow
  files too) and download-then-exec (security theater: semgrep passes while the
  same script still executes).
- Annotation placement: the rule matches the whole `run:` block, so the
  annotation goes on the `run: |` line — the first line of the match — not
  the `curl` line. Same lesson as 0.7.0's KMS annotation: the ID in the
  annotation must be the full rule ID, and the line must be the match start.

### Verified

- The re-triggered run on PR #1 (merge of main with the 0.7.1 annotation and
  the seeded broadening) landed the intended matrix:
  - `make check`: pass
  - `semgrep`: pass — the inline acceptance works in CI
  - `trivy`: pass
  - `terraform-check + policy-test`: fail — 4 passed, 1 failed, on exactly
    "support-agent must read only the customer-orders table"
  - `droid availability`: pass (FACTORY_API_KEY still unset)
  - `droid review (read-only)` / `post droid review`: skipped, as designed
- Cross-arm observation, recorded factually: the external Lacework IAC and SCA
  checks (partner-demo account) reported pass on the same seeded broadening.
  Generic compliance packs do not encode this lab's capability intent; the
  repo's own policy-as-code does. One seeded case, no generalization beyond
  it.

### Not done

- The full Droid review arm (credentialed exec + posted comment) awaits the
  user setting `FACTORY_API_KEY` as a repository secret; the user chose to
  verify it end-to-end and to keep PR #1 open as a live demo.

## 2026-10-30 — Pull-request workflow with credential-separated Droid review (0.7.0)

### Done

- Pre-verified the scanner arms locally before wiring CI, using the same
  digest-pinned images CI runs: Semgrep 1.183.0 (OWASP Top 10; 286 rules over
  54 files) and Trivy 0.76.1 (vuln + secret). Both clean on main.
- Added `.github/workflows/pull-request.yml`: deterministic gates (make check;
  terraform-check + policy-test; semgrep; trivy) plus a Droid review arm with
  separated credentials — `FACTORY_API_KEY` lives only in the read-only
  `droid exec` job, `GITHUB_TOKEN` (pull-requests: write) only in the posting
  job. Actions pinned by SHA; scanner images pinned by digest.
- The Droid job captures `make check` and `make policy-test` outcomes for the
  PR and passes them with the standing prompt, so the review cites
  deterministic findings instead of re-deciding them.

### Findings

- Semgrep flagged the synthetic DynamoDB tables
  (`aws-dynamodb-table-unencrypted`: wants a customer-managed KMS key).
  Triaged and accepted inline with rationale — synthetic, disposable data;
  AWS-managed SSE is deliberate for this lab.
- Trivy found no secrets: the deliberate test-fixture strings are not
  credential-shaped, and real account IDs never enter the repo.
- The Droid arm stays skipped until `FACTORY_API_KEY` is set as a repository
  secret (user action; the gate job never exposes the value).

### Not done

- The Droid arm has not been observed on a real run yet: it needs the repo
  secret.

## 2026-10-30 — Capability intent as policy-as-code (0.6.0)

### Done

- Added `infra/workloads/policy.tftest.hcl`: five plan-only runs with mocked AWS
  and Kubernetes providers, asserting the approved capability intent (read
  scope, identity pinning, workload hardening, namespace isolation). Runs in a
  disposable copy (`make policy-test`) so the operator's initialized S3-backend
  directory is untouched; no credentials and no account access.
- Verified both directions: passes on the approved revision; a seeded
  support-role broadening (orders + archive, the live drift shape) fails the
  suite with exit 1.

### Findings

- Terraform test mock providers need `override_during = plan` (on the provider
  and in each `override_resource` block) for computed values to be known in
  plan-only runs; otherwise assertions fail with "Unknown condition value".
- Generated mock ARNs are not format-valid, which breaks apply runs through
  attributes that validate ARNs (`aws_eks_pod_identity_association.role_arn`).
  Plan-only runs plus explicit ARN overrides avoid both problems.
- Provider shape quirks: `policy_types` and `capabilities.drop` compare as sets,
  and `spec.replicas` surfaces as the string "1"; normalize with `toset()` and
  `tonumber()`.

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
