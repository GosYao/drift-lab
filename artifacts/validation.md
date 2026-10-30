# Live drift validation — 2026-10-30

Sanitized record of the Phase 1 live drift exercise in the `drift-lab` sandbox lab
(`ca-central-1`). It contains no account IDs, ARNs, attribute values, or raw plans.
Address fingerprints are the `import-plan` sanitizer's SHA-256 prefixes.

## Method

1. Baseline: workloads `plan -refresh-only` and a normal plan. Provider
   null-to-empty normalization on the Deployment was accepted into state with a
   refresh-only apply. Afterwards `resource_drift` was empty and the normal plan
   exited 0.
2. Out-of-band changes, made the way an unreviewed hotfix would be:
   - IAM: `iam:PutRolePolicy` added the `customer-archive` table to the
     `drift-lab-support-agent` inline policy (1 table -> 2).
   - Identity: `kubectl patch` set the `support-agent` Deployment's
     `serviceAccountName` to `reporting-agent`.
3. Detection: `plan -refresh-only` (resource_drift) and a normal plan
   (resource_changes), both through `terraform show -json` and
   `python -m drift_lab import-plan`.
4. Cross-check: live IAM, Pod Identity, and Deployment reads were mapped onto the
   engine schema (mode `sanitized-observation`) and compared with the approved
   revision. This was a one-off script at the time; it is now committed as
   `python -m drift_lab collect` (0.5.0), which re-verified the lab live with a
   complete collection and a clean baseline comparison.
5. Reconciliation (user-approved): applied the normal plan, then re-planned.

## Results

| Step | Exit | Sanitized result |
| ---- | ---- | ---------------- |
| Refresh-only after drift | 2 | resource_drift: `aws_iam_role` update (`36ccccf3b074c64a`), `aws_iam_role_policy` update (`63536461110cb740`), `kubernetes_deployment_v1` update (`022b2c3762b9be8c`), `kubernetes_resource_quota_v1` update (`d765f2c1fdb36b3c`, noise) |
| Normal plan after drift | 2 | reconciliation: `aws_iam_role_policy` update, `kubernetes_deployment_v1` update (`Plan: 0 to add, 2 to change, 0 to destroy`) |
| Changed attribute paths | — | `.policy` / `.inline_policy[0].policy`; `.spec[0].template[0].spec[0].service_account_name`; quota: `resource_version` only |
| Rules engine (live evidence) | — | `review_required`: HIGH `Workload identity changed` (sa:support -> sa:reporting); HIGH `IAM read scope expanded` (orders -> archive + orders) |
| Capability path | — | `tool:lookup -> deployment:support -> sa:reporting -> role:reporting -> table:archive`; none in the approved revision |
| Reconcile apply | 0 | `0 added, 2 changed, 0 destroyed`; pod back on `support-agent`; policy back to 1 table |
| Post-reconcile normal plan | 0 | No changes |
| Post-reconcile refresh-only | 2 | `resource_version` only (Deployment, quota): noise |

## Findings

- Both approved drift scenarios were detected from live evidence by Terraform and by
  the rules engine, with agreeing results.
- **The sanitizer couldn't separate noise from drift.** It exported only type and
  action, so the noise rows looked identical to real drift. Addressed in 0.5.0:
  changed-attribute paths (names only), noise filters, and the IAM mirror collapse.
- **Exit code 2 isn't proof of resource drift.** A refresh-only plan also exits 2
  for output-value changes alone.
- **IAM drift appeared twice:** on `aws_iam_role_policy` and on the parent
  `aws_iam_role` (its `inline_policy` mirror). Addressed in 0.5.0 (mirror collapse).
- **Fixture/IaC mismatch:** the fixture range was 2-4 but the IaC deploys 1
  replica. The range is now 1-4.
- Limitation: the pod's egress is blocked by default-deny, so the reachable path is
  a configuration path. Nothing read customer data.
