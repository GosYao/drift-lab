# Status

Last updated: 2026-10-29

## Phase 1 — sandbox deployment (in progress: stacks up, teardown not yet proven)

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

Phase 1 is **not complete** against its exit criteria. Not yet done:

- Teardown and the up -> down -> up proof.
- The two approved manual drifts detected from live evidence.
- Recording actual cost against the budget.

## Phase 0 — local prototype (complete)

- 49 unit tests pass (`make test`); `make check` and `make terraform-check` pass.
- Preview UI with five scenarios, the evidence graph, replay, export, and the
  GitHub-side fixture previews (PR, push, scheduled issue).
- Git: public repository `GosYao/drift-lab` with GPG-signed commits; GitHub
  environment `security-lab` created.

## Still not done

- **No live collectors.** The UI still replays fixtures; it does not read the
  deployed cluster.
- **No Droid or GitHub workflow.** The GitHub panel is a fixture preview. No App or
  workflow exists, and nothing is posted. The Semgrep and Trivy rows are
  illustrative only.
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
2. Authorize the two live drift exercises (IAM policy and ServiceAccount).
3. Phase 2: read-only collectors using the GitHub observer role.
