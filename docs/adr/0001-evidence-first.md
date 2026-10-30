# ADR 0001: Evidence-first validation with a deterministic core

- Status: Accepted (2026-10-29)
- Scope: engine, plan sanitizer, reporting, all future collectors and integrations

## Context

The prototype's value proposition is bounded reasoning around deterministic checks.
If a model could decide whether drift is real, describe relationships it did not
observe, or see raw Terraform state or plans, the demo would be unfalsifiable and
unsafe: findings could be fabricated and sensitive data could leak into reports and
prompts. Results also need to hold up as scenarios, collectors, and eventually real
clouds replace fixtures.

## Decision

1. **Deterministic code makes the trusted decision.** Comparison, severity, graph
   construction, and validation live in `drift_lab/engine.py` and are covered by
   unit tests. A model may explain or summarize evidence; it cannot create edges,
   change severities, or make the trusted validation decision.
2. **Inconclusive is a first-class outcome.** When required evidence is missing, the
   engine reports `inconclusive` together with what is missing. It never guesses a
   finding or an edge to keep a demo pretty.
3. **Sanitize before anything crosses a boundary.** `drift_lab/terraform_plan.py`
   reduces plans to hashed address, resource type, and change actions. Raw state and
   plans never reach reports, the UI, or a model.
4. **Label provenance.** Fixture replay is labeled as fixture replay. Live
   collection, when it exists, will be labeled live. Template briefs are labeled
   templates.

## Consequences

- The engine needs explicit evidence contracts per scenario (what must be observed
  before a finding is valid), which is more work than free-form analysis.
- Explanations are constrained by evidence, which is the point: claims are
  checkable, and cost per verified fix can be measured honestly.
- Future features (collectors, Droid workflows, reconciliation) must extend the
  evidence contracts, never bypass the sanitizer or the engine.
