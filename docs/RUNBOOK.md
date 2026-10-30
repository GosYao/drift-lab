# Runbook

## Local operations (no cloud, no credentials)

Prerequisites: Python 3.9+ and `make`. Optional: `.tools/` binaries installed by
`scripts/bootstrap_local_tools.py` (checksum-pinned Terraform 1.13.5 and
agent-browser 0.40.0).

| Command | Effect |
| ------- | ------ |
| `make preview` | Serve the UI at `http://127.0.0.1:8765`; stop with Ctrl-C |
| `make test` | Run the unit suite (no network) |
| `make check` | Tests + byte-compile + repository contract checks |
| `make terraform-check` | `fmt -check`, `init -backend=false`, `validate` for all stacks; uses `.tools/terraform` when present; configures no backend and touches no AWS account |
| `make report` | Print the `iam` scenario report as JSON |
| `make preflight` | Check the local environment |

A preview server left running in the background can be stopped with
`kill -- -<pid>` (the negative pid kills its process group).

Importing sanitized plan evidence (used from Phase 1/2 onward):

```
python3 -m drift_lab import-plan <plan.json>
```

The sanitizer keeps only hashed addresses, resource types, and change actions. Raw
plans and state are never stored, displayed, or sent to a model.

## Cloud operations (authorization-gated — not performed yet)

Preconditions, in order:

1. A **dedicated sandbox AWS account** holding no production data or roles.
2. **Explicit user authorization** for each provisioning or teardown step
   (AGENTS.md). There is no self-serve path in this repo.
3. Reviewed values, set via `terraform.tfvars` (never committed): `account_id`,
   `github_oidc_subject` (exact `repo:OWNER/REPO:environment:NAME`, verified against
   GitHub's current claims format), `cluster_admin_principal_arn`,
   `kubernetes_version` (confirm regional support), `application_image` (published
   digest).
4. Cost guardrails acknowledged: the budget is reporting-only; the expected
   footprint is one t3.medium node, one NAT gateway, two on-demand DynamoDB tables;
   teardown is exercised, not assumed.

Bootstrap and apply order (foundation -> eks-lab -> workloads):

```
cd infra/foundation
terraform init -backend=false            # bootstrap with local state
terraform apply                          # creates the state bucket (prevent_destroy)
cp backend.tf.example backend.tf
terraform init -reconfigure -backend-config=bucket=<state_bucket> -backend-config=region=<region>

cd ../eks-lab
terraform init -backend-config=bucket=<state_bucket> -backend-config=region=<region>
terraform apply

cd ../workloads
terraform init -backend-config=bucket=<state_bucket> -backend-config=region=<region>
terraform apply                          # requires in-VPC access: private EKS API
```

Notes:

- `eks-lab` and `workloads` carry their S3 backend blocks in `versions.tf`
  (`use_lockfile = true`); only bucket and region are supplied at init.
- `workloads` reaches the EKS API through the Kubernetes provider
  (`aws eks get-token`), and the endpoint is private: run that step from inside the
  VPC (runner, bastion, or VPN).
- Planning discipline: plan from the approved deployment revision only. Record plan
  exit codes (`0` clean, `1` error, `2` changes pending) and the sanitized
  `resource_drift` / `resource_changes` summary as evidence.

Teardown (reverse order, after explicit authorization):

```
cd infra/workloads && terraform destroy
cd ../eks-lab       && terraform destroy
cd ../foundation    && terraform destroy
```

`terraform destroy` in `foundation` removes the ECR, OIDC, and budget resources but
refuses to delete the state bucket (`prevent_destroy`). Deleting the bucket is a
deliberate final step: empty all object versions, then remove the guard and delete
(or delete the bucket directly with the AWS console/CLI).

## Known open items

- Private API endpoint: cluster administration and the `workloads` apply need
  in-VPC access.
- Default-deny NetworkPolicy blocks egress for any real agent (DynamoDB, Bedrock);
  a reviewed allow-list is a prerequisite. Pod Identity credential delivery and
  kubelet probes under this policy are unverified until deployment.
- CNI network-policy enforcement uses node-role permissions at bootstrap; move CNI
  to a dedicated identity before untrusted workloads (ADR-0003).
- Budget alerts need a reviewed recipient/SNS configuration before apply.
- `expires_at` is an advisory tag; no cleanup controller is installed.
- The preview Deployment cannot schedule until an image is published by digest.

## Troubleshooting

- Port 8765 busy: `lsof -i :8765`, stop the stale process.
- The first `terraform init` downloads providers into `.terraform/`; later runs
  reuse the lock files and cache.
- Never debug by removing the sanitizer, the CSP, the Origin check, the body cap,
  or a `prevent_destroy` guard. If a check blocks you, record it in the worklog and
  fix the cause.
