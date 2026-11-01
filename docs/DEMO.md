# Demo flow

The end-to-end demo of Drift Lab. Everything in this script is verified
against a pushed commit, a recorded CI run, or a documented decision; nothing
below describes fixture replay as live evidence, and no claim generalizes one
data point into a tool comparison.

Run it against the public repository (GosYao/drift-lab) with PR #1 open.

## Opening (30 seconds)

Show PR #1: one red check, the rest green, and an AI review comment citing the
exact failing assertion.

> This is a live AWS lab. A vendor scanner found nothing wrong with this
> change. Our own policy-as-code gate failed it deterministically. And the
> agent, in under a minute, with zero cloud credentials, told us what it
> means, whether it was drift or intent, and how to fix it with proof.

## Part 1 — Background and the three Whys

### Background

- Drift Lab is a real lab in ca-central-1: an EKS cluster and workloads built
  from three Terraform stacks, GPG-signed commits, a read-only live collector,
  and budget alerting. Not a mockup.
- A live drift exercise already ran there: out-of-band changes against the
  approved revision were detected through refresh-only plan JSON and
  sanitized collectors, with sanitizer v2 filtering the noise
  (`resource_version`/`generation` churn, null-vs-empty, update-without-diff,
  IAM inline-policy mirror collapse) so findings show changed attributes, not
  raw plan JSON.
- The PR pipeline is real and verified: `make check` (75 tests plus contracts),
  capability-intent Terraform tests with mock providers, Semgrep and Trivy
  from digest-pinned images, and a credential-separated Droid review arm
  (0.7.0 through 0.7.2).

### Why 1 — Why does drift keep happening even though we write IaC?

Intent lives in more places than code. Terraform encodes what exists; it does
not encode why this role may read only this table. That capability intent
traditionally lives in review approvals, tribal memory, and runbooks. Anything
not encoded somewhere checkable drifts silently. This lab encodes it as
policy-as-code: five Terraform test runs with mock providers asserting the
support agent reads only customer-orders, identity pinning, workload
hardening, and namespace isolation.

### Why 2 — Why don't the scanners we already pay for stop it?

Two reasons, both demonstrated here. First, generic compliance packs check
against industry rules, not your intent: the seeded support-role broadening
(support-agent silently gaining read on customer-archive) passed the external
Lacework IAC and SCA checks on the same PR where the intent-encoded gate
failed it. One seeded case, recorded factually. Second, noise: raw plan output
buries the two lines that matter under version fields and mirror updates.
Triage cost is set by noise, and noise is a deterministic problem.

### Why 3 — Why does an agent change the economics instead of just adding cost?

The expensive part was never detection; it is the human loop: connect finding,
change, intent, fix, proof. The demo's division of labor answers the objection:
deterministic checks make the trust decision, and the agent does the
correlation and explanation. The agent cannot override a gate, cannot
fabricate evidence, and in this pipeline holds no credential that can touch
anything. The trust model stays deterministic; the labor cost collapses.

## Part 2 — Why Droid makes the difference (walkthrough)

Timings are from the recorded CI run on PR #1.

1. **The gate goes red on intent (2 min).** Open PR #1 checks: `policy-test`
   fails on exactly `support-agent must read only the customer-orders table`
   (4 runs pass, 1 fails). `make check`, Semgrep, Trivy: green. Optionally
   contrast the external Lacework IAC/SCA checks, green on the same
   broadening. Talking point: everything a commodity scanner can see is fine
   here; the only thing that caught it is encoded intent, because the intent
   is ours.

2. **The agent's review, already posted (3 min).** Open the Droid review
   comment. Point at each behavior:
   - cites the deterministic gate by name, run, exact assertion condition and
     text — it explains the verdict, it does not issue one;
   - classifies the finding: a proposed intent change, not out-of-band drift
     and not noise, adding the load-bearing sentence — an approved expansion
     would require updating the capability baseline, and this seed does not;
   - refuses to overclaim: states the evidence is mock-provider verification,
     not live AWS access;
   - ends with `VERDICT: request changes` and a verified fix path: restore the
     conditional, re-run `make policy-test`, all five runs pass without
     weakening an assertion.

3. **The self-application moment (1 min).** CI Semgrep caught the `curl | sh`
   install pattern in the workflow itself — the one file local pre-verification
   could not cover, because it did not exist yet (0.7.1). The scanner caught
   the agent pipeline; agent-plus-human triaged it: accepted inline with
   rationale at the source line, recorded in the WORKLOG. Scanner finds, human
   decides, agent documents — working on itself.

4. **The trust architecture (1 min).** The answer to "isn't an agent in CI
   dangerous?":
   - the review job holds only `FACTORY_API_KEY`, no GitHub token, and runs
     `droid exec` read-only by default;
   - a separate job holding only `GITHUB_TOKEN` (pull-requests: write) posts
     the review;
   - no job can both decide and publish; the availability gate exposes a
     boolean, never the key value;
   - CI never plans or applies against AWS; actions pinned by SHA, scanner
     images by digest, every commit GPG-signed.

5. **The local UI (optional, 30 sec).** `make preview`, then
   http://127.0.0.1:8765 — the GitHub-view preview and scenario reports. Be
   explicit with the audience: this panel replays synthetic fixtures; live
   collection today is the CLI (`python -m drift_lab collect`), and wiring it
   into the UI is next. Honest boundaries read as strength.

## Part 3 — Technical and business benefit analysis

| Dimension | What the demo showed | Business translation |
| --- | --- | --- |
| Noise engineering | Sanitizer v2 filters: changed-attribute paths, version churn, IAM mirror collapse | Triage reads meaningful lines, not raw plan JSON; triage cost engineered down deterministically |
| Intent as code | 5 capability tests, mock providers, credential-free; seeded broadening fails them | Every PR checks intent pre-merge at near-zero marginal cost; no AWS credentials in PR checks |
| Detection vs explanation | Gates decide; agent cites, classifies, gives fix path and verdict | Senior-reviewer-quality triage in 57s, auditable, non-fabricating |
| Cross-tool delta | External IAC/SCA checks passed the seeded broadening; the lab's own gate failed it | Your intent is a differentiator no vendor product carries (one seeded case, not a generalization) |
| Supply chain | Pinned actions and digests, signed commits, read-only collector, sanitized snapshots | No account IDs or raw state leave the repo; findings shareable without redaction work |
| Credential separation | Factory key and GitHub token never co-located; review job read-only | The agent adds capability without adding blast radius; the auditable answer to agent risk |
| Cost control | Lab at $5-7/day under a $500 budget alert; agent arm no-ops without the key | Agent spend is a gate, not a leak; the whole lab costs less than one incident triage hour |

The metric this prototype is built around: **cost per verified fix**. A fix
counts as verified only when it passes deterministic re-verification — the
agent's own review states the criterion. The recorded run gives the
numerator's ingredients: 57 seconds of agent review, seconds of pinned
scanners, zero cloud credentials. The benchmark phase measures it properly
across arms (scanners-only, plus ordinary Droid review, plus policy-as-code
plus Droid), so the claim becomes a number instead of an anecdote. That phase
is designed, not yet measured.

## Honest boundaries to state on stage

- One seeded case; no generalization beyond it, no competitor-parity claims.
- The UI is fixture replay; live collection is the CLI for now.
- The benchmark arms are designed, not yet measured.
- No automatic reconciliation: drift is detected and explained; remediation
  stays authorized human work.

## Closing line

> Detection is solved — we proved it by making our own gate catch what the
> vendor scanners passed. What is not solved is turning findings into
> decisions, and decisions into verified fixes. That is the 57 seconds you
> just saw — and it is why the next phase measures cost per verified fix.

## Appendix — quick references

- PR #1 (seeded broadening, live demo): https://github.com/GosYao/drift-lab/pull/1
- Workflow: `.github/workflows/pull-request.yml`; review prompt:
  `.github/droid-review-prompt.md`
- Policy gate: `infra/workloads/policy.tftest.hcl` via `make policy-test`
- Inline acceptances to show: `infra/workloads/main.tf` (KMS on synthetic
  tables), `.github/workflows/pull-request.yml` (CLI install pattern)
- Records: `docs/WORKLOG.md` (0.7.0-0.7.2), `docs/CHANGELOG.md`,
  `docs/STATUS.md`, `docs/RUNBOOK.md` (CI section)
- Commits: c0fea7f (workflow), 2362d1f (CI catch acceptance), 7bf7c31
  (Droid arm verification)
