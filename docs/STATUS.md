# Status

Last updated: 2026-10-30

## Phase 1 — sandbox deployment (in progress: stacks up, drift proven, teardown not yet proven)

The lab is **live in AWS** in account `****4817`, region `ca-central-1`. Access is
through the `demo-admin` IAM Identity Center profile. The user approved this
account, which is a shared, non-empty account behind a corporate SSO start URL,
rather than a dedicated sandbox. The lab's resources are isolated by VPC and the
`drift-lab-*` naming.

| Stack | Resources | State | Re-plan |
| ----- | --------- | ----- | ------- |
| `foundation` | 10 (state bucket, ECR, GitHub observer role, budget); reuses the account's existing GitHub OIDC provider | S3 `foundation/terraform.tfstate` | exit 0, no changes |
| `eks-lab` | 32 (VPC, NAT, EKS 1.36, 1 x t3.medium, 4 add-ons, admin access entry) | S3 `lab/eks/terraform.tfstate` | exit 0, no changes |
| `workloads` | 14 (namespace, quota, 2 SAs, 2 DynamoDB tables, 2 Pod Identity roles + associations, Deployment, NetworkPolicy) | S3 `lab/workloads/terraform.tfstate` | exit 0, no changes |

Verified on the live cluster:

- Node `Ready` (v1.36.5); `aws-node` (with the network policy agent), CoreDNS,
  kube-proxy, and the Pod Identity agent are running.
- The preview pod is `Running 1/1` under `restricted:v1.36` Pod Security, using
  image `drift-lab-preview@sha256:8351be12…` (tag `87f37a8`, linux/amd64).
  Readiness and liveness probes pass under default-deny.
- Both Pod Identity associations exist (`support-agent`, `reporting-agent`).
- Default-deny is enforced: a PolicyEndpoint exists, DNS fails, and the Pod
  Identity agent (`169.254.170.23`) times out from the pod.
- The app serves `/api/health` and `/api/github` via `kubectl port-forward`.

Live drift (2026-10-30): an IAM inline-policy drift and a ServiceAccount drift were
injected out-of-band, detected by `plan -refresh-only`, the normal plan, and the
rules engine, then reconciled with approval. The re-plan was clean. See
`artifacts/validation.md`.

Live collector (2026-10-30): `python -m drift_lab collect` (read-only) was
verified against the lab: complete collection of all eight tracked resources and a
clean baseline comparison (exit 0). The sanitizer now exports changed-attribute
names, filters bookkeeping noise, and collapses the IAM mirror. The preview UI
still replays fixtures.

Phase 1 is **not complete** against its exit criteria. Not yet done:

- Teardown and the up -> down -> up proof.
- Recording actual cost against the budget.

## Phase 0 — local prototype (complete)

- 75 unit tests pass (`make test`); `make check` and `make terraform-check` pass.
- `make policy-test` (capability-intent Terraform tests, mock providers, no
  credentials) passes on the approved revision and fails on a seeded IAM
  broadening.
- Preview UI with five scenarios, the evidence graph, replay, export, and the
  GitHub-side fixture previews (PR, push, scheduled issue).
- Git: public repository `GosYao/drift-lab` with GPG-signed commits; GitHub
  environment `security-lab` created.

## Still not done

- **Collectors are in; the UI is not.** `python -m drift_lab collect` performs
  verified live read-only collection, but the preview UI still replays fixtures.
- **The PR workflow is fully verified live, including the Droid review arm.**
  Pull requests to `main` run the deterministic gates (tests, terraform-check +
  policy-test, Semgrep, Trivy) plus a credential-separated, read-only Droid
  review. On seeded PR #1 (kept open as a live demo): every deterministic gate
  green except the capability-intent gate, which fails on exactly the seeded
  support-role broadening; the read-only review posted citing that gate and its
  exact assertion, ending `VERDICT: request changes`. The GitHub panel in the
  UI remains a fixture preview.
- **Real agent egress is blocked by design.** Pod Identity credentials, DNS, and
  DynamoDB need a reviewed egress allow-list before a real agent replaces the
  fixture viewer.

## Open findings

1. Default-deny egress does not block pod -> local node traffic: the kubelet
   (`:10250`) is reachable from the pod. The kubelet requires authentication, but
   restrict this before running untrusted workloads.
2. The EKS public endpoint is open to the operator's `/32`. Set
   `public_access_cidrs = []` and re-apply once an in-VPC runner exists.
3. ECR basic scan-on-push returned no scan for the image; the account likely uses
   registry-level (Inspector) scanning. Confirm where findings are reported.
4. The budget is reporting-only. Expect roughly $5-7/day while the lab is up (EKS
   control plane, NAT gateway, one node).

## Next decision points

1. Teardown timing: tear the lab down (reverse order, `docs/RUNBOOK.md`) when the
   demo is done, and prove up -> down -> up.
2. Phase 2: read-only collectors using the GitHub observer role.
