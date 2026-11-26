# Demo flow

The end-to-end demo of Drift Lab: from findings to a verified fix. Everything
in this script is verified against a pushed commit, a recorded CI run, or a
documented decision; nothing below describes fixture replay as live evidence,
and no claim generalizes one data point into a tool comparison.

Run it against the public repository (GosYao/drift-lab) with the seeded pull
requests open: PR #1 (support-role read broadening, labelled seeded, never to
merge), PR #2 (the vulnerable YAML import, labelled seeded, never to merge or
deploy), and the fix pull request for PR #2's findings.

## Opening (60 seconds)

Show PR #2, "Load scenarios from YAML", with two red checks: Semgrep (unsafe
YAML deserialization in the new import endpoint) and Trivy (a critical CVE in
the pinned PyYAML). Next tab: PR #1, red on the capability-intent policy test
for broadening the support agent's read scope.

> Two pull requests, two scanners, one attack path. Each scanner found its own
> finding. Neither check sees the other pull request, so nothing tells you
> that together they are a way from this service to the customer archive.
> What happens after the finding is your problem, so that is the demo.

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
- The PR pipeline runs the full loop: `make check` (unit tests plus
  contracts), capability-intent Terraform tests with mock providers, Semgrep
  and Trivy from digest-pinned images through one shared definition
  (`scripts/scanners.py`), a verify-fix job for `fix/` branches, and a
  credential-separated Droid review that posts one packet per finding.

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
IAC and SCA checks on the same PR where the intent-encoded gate failed it. One
seeded case, recorded factually. Second, noise: raw plan output buries the two
lines that matter under version fields and mirror updates. Triage cost is set
by noise, and noise is a deterministic problem.

### Why 3 — Why does an agent change the economics instead of just adding cost?

The expensive part was never detection; it is the human loop: connect finding,
change, intent, fix, proof. The demo's division of labor answers the
objection: deterministic checks make the trust decision, and the agent does
the correlation and explanation. The agent cannot override a gate, cannot
fabricate evidence, cannot add a suppression, and in this pipeline holds no
credential that can touch anything. The trust model stays deterministic; the
labor cost collapses.

## Part 2 — The loop, step by step

1. **Triage with evidence (3 min).** `scripts/triage.py` computes the evidence
   first: the scanner findings, the gate outcomes, the chained exposure, and
   the diff. The triage model — one `model:` line in the reviewed file
   `.factory/droids/triage.md` — runs read-only and writes one packet per
   finding: recommendation (true positive, false positive, accepted risk),
   class, reachability with `file:line` evidence, chained exposure, and what
   else the change touches. The posted review carries the model's packets
   above the computed evidence, so a packet can recommend but never change
   what a gate said. If the model fails, times out, or returns an unusable
   answer, the review says "Triage unavailable, human review required." and
   every finding keeps the severity its gate reported. Talking point: the
   reviewer starts from a recommendation with evidence, not from a raw
   finding.

2. **Chained exposure, computed (1 min).** The packet's exposure line is not
   the model's guess: `scripts/chained_exposure.py` reads the Terraform
   source, works out which service account the changed workload runs as, which
   IAM role Pod Identity binds to it, what that role's policy can read, and
   which other branches on the remote change the same policy or the same
   workload's code. That is the line that connects PR #2's endpoint to PR #1's
   broadening. A construct the script does not model is reported as unknown
   and sent to a person; a model may word the line, never invent the edge.

3. **Fix with proof (4 min).** On a branch named `fix/...`, when the agent
   tries to finish, the Stop hook (`.factory/hooks.json`) runs
   `scripts/verify_fix.py` against the base: no new suppression (a `nosemgrep`
   comment, an ignore-file entry, a weaker command, a removed or weakened
   test), a regression test that fails on the base and passes now, the full
   unit suite against the pinned dependencies, the capability-intent policy
   test when `infra/` changed, and both pinned scanners clean. A failing gate
   blocks the stop and the reason becomes the agent's next instruction; after
   three blocks the hook gives up and the fix stays NOT VERIFIED. Show the
   refusal once: the same finding "fixed" with a `nosemgrep` comment fails the
   first gate and names the suppression. A pin bump alone would turn the
   dependency scanner green and leave the unsafe call in place; a suppression
   would turn the code scanner green and fix nothing. The fix is not done
   because the model says so; it is done because the scanner and the test say
   so.

4. **The fix pull request (2 min).** The pipeline's verify-fix job runs the
   same gates in CI, using the verifier and scanner definitions from the base
   revision, so the fix cannot change the checks that judge it. Its evidence
   (gate results before and after) is uploaded as an artifact and folded into
   the review packet the droid-review job posts. Green checks plus a packet:
   the scanner output before and after, the regression test, the
   no-suppression result, the chained-exposure line, and the model that wrote
   it.

5. **The trust architecture (1 min).** The answer to "isn't an agent in CI
   dangerous?":
   - the review job holds only `FACTORY_API_KEY`, no GitHub token, and runs
     `droid exec` read-only;
   - a separate job holding only `GITHUB_TOKEN` (pull-requests: write) posts
     the review;
   - no job can both decide and publish; the availability gate exposes a
     boolean, never the key value;
   - the model for each job is a line in a reviewed file, not a per-user
     setting;
   - CI never plans or applies against AWS; actions pinned by SHA, scanner
     images by digest, every commit GPG-signed;
   - the merge control is branch protection plus a human approver, not the
     agent.

## Part 3 — Technical and business benefit analysis

| Dimension | What the demo showed | Business translation |
| --- | --- | --- |
| Noise engineering | Sanitizer v2 filters: changed-attribute paths, version churn, IAM mirror collapse | Triage reads meaningful lines, not raw plan JSON; triage cost engineered down deterministically |
| Intent as code | 5 capability tests, mock providers, credential-free; seeded broadening fails them | Every PR checks intent pre-merge at near-zero marginal cost; no AWS credentials in PR checks |
| Detection vs explanation | Gates decide; the triage model recommends one packet per finding over computed evidence | Reviewer starts from a recommendation with evidence; the model never changes a check result |
| Fail-safe triage | Model failure renders "triage unavailable, human review required"; severities unchanged | The agent can add labor savings but can never silently lower the bar |
| Fix with proof | Verifier gates: no suppression, regression test fails-before/passes-after, scanners clean, locally and in CI | "Fixed" becomes a reproducible state with evidence, not a claim in a comment |
| Cross-tool delta | External IAC/SCA checks passed the seeded broadening; the lab's own gate failed it | Your intent is a differentiator no vendor product carries (one seeded case, not a generalization) |
| Supply chain | Pinned actions and digests, signed commits, read-only collector, sanitized snapshots | No account IDs or raw state leave the repo; findings shareable without redaction work |
| Credential separation | Factory key and GitHub token never co-located; review job read-only | The agent adds capability without adding blast radius; the auditable answer to agent risk |
| Cost control | Lab at $5-7/day under a $500 budget alert; agent arm no-ops without the key; the packet records the model and credits used | Agent spend is visible per run; the whole lab costs less than one incident triage hour |

The metric this prototype is built around: **cost per verified fix**. A fix
counts as verified only when the deterministic gates pass: the scanner that
reported the finding reports nothing, a regression test fails before and
passes after, no new suppression, and a person approves the merge. The review
packet records the ingredients, including the model and the Factory credits
the run used, so the numerator becomes a number instead of an anecdote.

## Honest boundaries to state on stage

- One seeded pair of pull requests; no generalization beyond it, no
  competitor-parity claims.
- The UI is fixture replay; live collection is the CLI for now.
- The verifier re-runs the scanners and tests; it does not reproduce an
  exploit, and the demo does not claim it does.
- The chained-exposure script models the lab's own Terraform constructs only
  and answers "unknown" on anything else; it reads source, not live AWS
  permissions.
- No automatic reconciliation: drift is detected and explained; remediation
  stays authorized human work.

## Closing line

> Detection is solved; we proved it by making our own gate catch what the
> vendor checks passed. What is not solved is turning findings into decisions,
> and decisions into verified fixes. That loop — one packet per finding, a
> proof for the fix, and a person's approval on the record — is what you just
> saw.

## Appendix — quick references

- Seeded PR #1 (policy broadening): https://github.com/GosYao/drift-lab/pull/1
- Workflow: `.github/workflows/pull-request.yml`; triage droid:
  `.factory/droids/triage.md`; Stop hook: `.factory/hooks.json`
- Scripts: `scripts/scanners.py` (one pinned scanner definition),
  `scripts/triage.py` (evidence + packets + fail-safe),
  `scripts/chained_exposure.py`, `scripts/verify_fix.py` (the fix gates)
- Policy gate: `infra/workloads/policy.tftest.hcl` via `make policy-test`
- Inline acceptances to show: `infra/workloads/main.tf` (KMS on synthetic
  tables), `.github/workflows/pull-request.yml` (CLI install pattern)
- Records: `docs/WORKLOG.md` (0.7.0-0.7.2, 0.8.0), `docs/CHANGELOG.md`,
  `docs/STATUS.md`, `docs/RUNBOOK.md` (CI section)
