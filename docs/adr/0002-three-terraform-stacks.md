# ADR 0002: Split infrastructure into three Terraform stacks

- Status: Accepted (2026-10-29)
- Scope: `infra/foundation`, `infra/eks-lab`, `infra/workloads`

## Context

The lab needs a repeatable up -> down -> up proof, controlled blast radius, and a
hard cost envelope. A monolithic stack would couple the state bucket's lifecycle to
the cluster's and the workload's, making teardown dangerous and iteration slow. It
would also make the trusted state store depend on the resources whose state it keeps.

## Decision

Three stacks, applied and destroyed in strict order:

1. `infra/foundation` — created first because it owns the state bucket. The bucket
   is versioned, encrypted, TLS-only, public-blocked, and `prevent_destroy`.
   Bootstrapped with local state once, then migrated to the S3 backend documented in
   `backend.tf.example` (`use_lockfile = true`).
2. `infra/eks-lab` — network and cluster; S3 backend at `lab/eks/terraform.tfstate`
   with native lockfile. No remote-state dependency on foundation; the stack
   validates standalone with `init -backend=false`.
3. `infra/workloads` — namespace, identities, synthetic tables, preview app; S3
   backend at `lab/workloads/terraform.tfstate`. Reads the cluster by name
   (`cluster_name`) rather than through remote state.

Apply order: foundation -> eks-lab -> workloads. Destroy order: exactly the
reverse. The runbook encodes this so it is never improvised.

## Consequences

- Cross-stack wiring flows through variables and outputs, not remote-state guessing;
  each stack validates in isolation.
- State locking is S3-native (`use_lockfile = true`); no DynamoDB lock table is
  created or needed.
- The observer role can only read state objects under `lab/*` and manage
  `lab/*.tflock`, which covers the two lab stacks and deliberately not foundation's
  own state.
- End-of-project cleanup of the state bucket is a deliberate, separate manual step
  (`prevent_destroy`); teardown of the lab stacks is routine.
