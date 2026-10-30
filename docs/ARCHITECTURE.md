# Architecture

## Goal

Demonstrate bounded reasoning around deterministic checks: Droid orchestrates
scanners and Terraform, connects findings to code and identity changes, and produces
validated, explained results. The trust boundary is the product: deterministic code
decides what is true; a model may only explain what the evidence already shows.

## Components (local, stdlib-only Python)

```
scripts/bootstrap_local_tools.py — checksum-pinned Terraform 1.13.5 and
        |                       agent-browser 0.40.0 into .tools/
        v
infra/foundation + infra/eks-lab + infra/workloads     Terraform, validated
        |                                              (NOT applied; no cloud)
        |  terraform plan/show -json (Phase 2, sanitized on ingest)
        v
drift_lab/terraform_plan.py — sanitizer: hashed address + resource type +
        |                    change actions only
        v
drift_lab/scenarios.py — sanitized fixtures: iam, identity, scaling,
        |                 incomplete, clean
        v
drift_lab/engine.py — deterministic validate/compare -> findings + graph +
        |              replay answers; inconclusive when evidence is missing
        v
drift_lab/server.py — 127.0.0.1:8765; CSP; Origin check on POST; 4 KB body cap
        v
drift_lab/static/ — UI: graph, findings, brief, replay, export
```

### Modules

- `drift_lab/engine.py` — validates evidence shape, compares approved vs observed
  state, builds the evidence graph (repository -> Deployment -> ServiceAccount ->
  pod identity -> IAM role -> dataset), and answers replay queries. Missing
  evidence yields `inconclusive`; it never invents findings or edges.
- `drift_lab/terraform_plan.py` — reduces a Terraform plan to hashed address,
  resource type, and change actions. The only sanctioned path from Terraform output
  into reports or models.
- `drift_lab/scenarios.py` — five sanitized scenario fixtures (IAM drift,
  ServiceAccount/pod-identity drift, harmless scaling, missing evidence, clean).
- `drift_lab/server.py` — local HTTP server: `/api/health`, scenario endpoints,
  static files. Binds 127.0.0.1 only; sets a Content-Security-Policy; checks the
  Origin header on POSTs; caps request bodies at 4 KB.
- `drift_lab/__main__.py` — CLI: `serve`, `report --scenario`, `import-plan`.
- `scripts/preflight.py`, `scripts/check_repository.py` — environment checks and
  repository contracts (required docs, DOM id integrity, no `innerHTML`/`eval`).

## Trust boundaries

1. **Deterministic core vs explanation.** Findings, severities, and graph edges come
   from code and tests. A model may summarize or explain them; it cannot create
   edges, upgrade severities, or make the trusted validation decision.
2. **Raw state vs sanitized evidence.** Terraform state and plans stay out of
   reports, the UI, and prompts. Only sanitized plan facts and fixtures cross.
3. **Local execution vs cloud deployment.** Preview, tests, and validation run with
   no cloud credentials. Provisioning uses separate, explicitly authorized
   credentials and the approved revision only (AGENTS.md).
4. **Observation vs action.** The GitHub OIDC role is deliberately an observer:
   describe/list/read state objects and manage `.tflock` files under `lab/*`. It is
   not a deployment role; broadening it is an explicit, reviewed change.

## Terraform stacks

- `infra/foundation` — S3 state bucket (versioning, AES256, TLS-only bucket policy,
  public access block, `prevent_destroy`), immutable ECR with scan-on-push and a
  15-image lifecycle, GitHub OIDC provider plus an exact-subject observer role, and
  a reporting-only monthly budget filtered to the `drift-lab` project tag.
  Bootstrapped with local state; `backend.tf.example` documents the S3 migration
  (`use_lockfile = true`).
- `infra/eks-lab` — 2-AZ VPC (10.84.0.0/16), one NAT gateway, private subnets for
  nodes, S3/DynamoDB gateway endpoints, EKS in API auth mode with an explicit admin
  access entry, private API endpoint only, control-plane logging (api, audit,
  authenticator; 7-day retention), one t3.medium on-demand node with IMDSv2 required
  and an encrypted gp3 root volume, and add-ons (vpc-cni with
  `enableNetworkPolicy = true`, coredns, kube-proxy, eks-pod-identity-agent).
  Backend: S3 at `lab/eks/terraform.tfstate` with native lockfile.
- `infra/workloads` — `restricted` Pod Security namespace with a resource quota, two
  service accounts with token automount disabled, scoped Pod Identity roles over two
  synthetic DynamoDB tables, a digest-pinned preview Deployment (non-root, read-only
  root filesystem, all capabilities dropped), and a default-deny NetworkPolicy.
  Backend: S3 at `lab/workloads/terraform.tfstate`; the Kubernetes provider
  authenticates via `aws eks get-token` against the cluster data source.
- All providers pin `allowed_account_ids` to the sandbox account and tag resources
  (`Project`, `ManagedBy`; `Lifecycle` is persistent for foundation and disposable
  for the lab stacks).

## What is intentionally missing

Live AWS/Kubernetes collectors, scheduling, Droid workflow integration, image
build/publish, remediation flows, and multi-account or multi-cloud support. The
roadmap (`docs/ROADMAP.md`) sequences these; nothing here claims them.
