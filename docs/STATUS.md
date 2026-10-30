# Status

Last updated: 2026-10-29

## Phase 0 — local prototype (complete)

Everything below runs locally with no cloud account, credentials, or AWS API calls:

- 49 unit tests pass (`make test`).
- Preview UI at `http://127.0.0.1:8765` (`make preview`): all five scenarios, the
  evidence graph, findings, written brief, replay controls, and JSON export.
- GitHub-side fixture previews (PR review comments and check-runs, push check-runs
  and commit comments, scheduled drift issue) in the "How it lands on GitHub" panel.
  These are rendered locally; nothing is posted to GitHub.
- `make check` passes: tests, byte-compile, repository contracts.
- `make terraform-check` passes: `fmt -check` plus `init -backend=false` and
  `validate` for all three stacks (AWS provider pinned 6.71.0, Kubernetes pinned
  2.38.0).
- Checksum-pinned Terraform 1.13.5 and agent-browser 0.40.0 are installed under
  `.tools/` and verified.

Deliberately not done in Phase 0:

- **No AWS resources exist.** No `plan` or `apply` has run against AWS; validation
  is `init -backend=false` only. No state backend, credentials, or account were
  touched.
- **No live collectors.** Scenarios replay sanitized fixtures; nothing collects from
  AWS or Kubernetes yet.
- **No Droid integration.** No workflow, automation, or model call exists in the
  repo; UI briefs are template-generated and labeled as such.
- **No GitHub integration.** The GitHub panel is a fixture preview. No App,
  workflow, token, or API write exists. The Semgrep and Trivy check rows are
  illustrative only.
- **No image build/publish.** The preview Deployment references a digest that must
  be published first.
- **Not under version control yet.** Git initialization and the first commit
  (including `.terraform.lock.hcl` files) are a recorded follow-up.

## Next decision points

1. Authorization to apply `infra/foundation`, then `infra/eks-lab`, then
   `infra/workloads` in a dedicated sandbox account, with a full up -> down -> up
   proof (`docs/RUNBOOK.md`).
2. Choose the control repository, GitHub environment, and exact OIDC subject before
   any apply; the observer role trusts exactly that subject, and the format must be
   verified against GitHub's current claims.
3. Phase 2: read-only AWS/Kubernetes collectors to replace fixture replay with real
   evidence.
