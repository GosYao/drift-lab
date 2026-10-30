# ADR 0003: EKS with Pod Identity, private API, and default-deny networking

- Status: Accepted (2026-10-29)
- Scope: `infra/eks-lab`, `infra/workloads`

## Context

EKS was chosen over serverless (Lambda) deliberately: the user wants to demonstrate
Kubernetes-flavored drift (ServiceAccount and pod-identity changes), and the
identity chain Kubernetes -> Pod Identity -> IAM -> data is central to the demo. The
cluster is a short-lived sandbox in a dedicated account, but it must still start
from a defensible baseline, with the security-relevant choices explicit rather than
default.

## Decision

- **EKS in API auth mode, no bootstrap creator admin.** Access is granted only to
  the reviewed admin role through an access entry associated with the cluster admin
  policy.
- **Private API endpoint only** (`endpoint_public_access = false`): the cluster is
  not reachable from the internet; administration needs a route into the VPC.
- **Pod Identity over IRSA**, with `automount_service_account_token = false` on the
  service accounts; roles trust `pods.eks.amazonaws.com` and are scoped to read-only
  actions on the synthetic tables.
- **IMDSv2 required** on nodes (`http_tokens = "required"`, hop limit 1).
- **vpc-cni with `enableNetworkPolicy = true`** so NetworkPolicy is actually
  enforced rather than decorative.
- **Namespace is `restricted`** (Pod Security Admission) with a resource quota; the
  preview container is non-root, read-only root filesystem, no privilege escalation,
  all capabilities dropped, image pinned by digest.
- **Default-deny NetworkPolicy** (ingress and egress) on the namespace. The fixture
  preview needs no network access; any real agent needs a separately reviewed
  allow-list (credential path, DynamoDB, and later Bedrock), never a silent
  broadening.

## Consequences

- **Administration and the `workloads` apply require in-VPC access** because the API
  endpoint is private. Accepted: it is the posture being demonstrated.
- **The default-deny policy blocks DynamoDB/Bedrock egress for any real agent**
  until an explicit policy is reviewed and added. Recorded as a known risk, not an
  accident.
- **CNI network-policy enforcement relies on node-role CNI permissions** at
  bootstrap; moving CNI to a dedicated identity is required before any untrusted
  workload or real-data pilot.
- **Kubelet probes (readiness/liveness against `/api/health`) under default-deny
  ingress are untested until deployed.** Phase 1 must verify probes, addon startup,
  and Pod Identity association end-to-end before the demo is trusted.
