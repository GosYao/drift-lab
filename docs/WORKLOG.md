# Worklog

Running record of what was done, decided, and deliberately not done. Newest first.

## 2026-11-27 — Queue to issues (0.8.7)

- User authorized publishing ranked findings as issues, linking the existing
  fix, a paused Factory Automation on the Mac, and a workflow_dispatch fallback
  through a reviewed PR. No approvals, merges or AWS operations are included.
- Added structured output and a separate issue publisher. The queue contains
  normalized finding fields and summaries, not raw scanner or Terraform output.
  Stable identity ignores rank, commit, line and installed version, but retains
  file and policy branch. No source severity changes.
- `make check`: 182 tests pass, compilation and repository contracts pass.
- First integration ranking had the intended order but said a PyYAML upgrade
  fixes neither the advisory path nor the code finding. The first half is wrong:
  the upgrade clears the dependency advisory; it does not replace the unsafe
  API. Nothing was published. Instructions now distinguish those facts and ask
  for the finding's own location, not its importer's location.
- Live publish (`cc6911e`): issues #5 to #9 were created in rank order. The
  immediate rerun left #5 and #6 unchanged but created #10 to #12 for the
  last three findings. GitHub's issue list had not yet returned #7 to #9.
  The publisher now records each issue's number in
  `.triage/issues-ledger.json` right after it creates the issue, and reads a
  recorded issue by number before creating another. Reading an issue by number
  does not lag. #10 to #12 were retitled, had their markers removed, and were
  closed as not planned with a pointer to the original. Two later reruns
  reported five unchanged and made no writes. A second host without the local
  ledger still depends on the list, so the publishers run one at a time, never
  together and never within minutes of each other.
- Factory Automation `drift-lab security queue (demo)`
  (`f52f51c7-6431-42e8-9c85-aee1ed7376c3`): cloud automation, paused, yearly
  placeholder schedule, targeting the registered Mac `ot-gyao-mac`, Haiku 5.5
  at low effort. Its prompt runs `make triage-queue`, then `make queue-issues`
  only if ranking exited 0, and forbids edits, commits and issue state
  changes. "Run now" at `5d0bb6d`: ranking exited 0, with the same order as
  the rehearsals (code flaw, access drift, kubelet, PyYAML, pyarrow), and the
  publisher updated #5 to #9 in place with no duplicates. The comment
  linking PR #3 on #5 stayed. Two caveats. The run took about 26 minutes,
  not about 1: the Mac slept, a parallel `make scan` competed for Docker, and
  the load average was 11.6. The first command was also killed by the
  default 60-second command timeout, so the prompt now sets the timeouts.
  The run session starts with `--skip-permissions-unsafe`, so the prompt's
  rules are instructions, not enforcement. Enforcement is the
  `gh` token's scope and the publisher's code.
- Issue #5 (code flaw, fix now) references fix PR #3 in a comment. It is not a
  closing keyword, so the issue stays open until a person closes it.
- `demo/triage-queue` is pushed and trusted (the earlier 0.8.6 “local only” and
  “not trusted” notes describe the state before that later step).

## 2026-11-26 — A ranked triage queue on a demo branch (0.8.6)

### Done

- Branch `demo/triage-queue`, cut from the seeded `feature/scenarios-from-yaml`
  (`87ebf1f`), local only. Main is unchanged and no image was rebuilt. The
  `demo/` prefix is outside the `feature/**` ruleset; nothing was weakened.
- The queue reuses PR #2's code flaw, so fix PR #3 stays step 2a. It adds one
  seeded dependency, `pyarrow==14.0.0` in `tools/dev/requirements.txt`
  (CVE-2023-47248, critical, fixed in 14.0.1), never copied into the image.
- Scanner probes in the pinned Trivy image, before committing: a file named
  `scripts/requirements-dev.txt` or `dev-requirements.txt` is not read at
  all ("language-specific files num=0"), so the dev file must be named
  `requirements.txt`. Pillow, Django, nltk and GitPython each produced 20 to
  50 findings; pyarrow 14.0.0 and h11 0.14.0 each produced exactly one
  critical. pyarrow was chosen. Re-probe before the panel: new advisories
  can add rows.
- `make triage-queue` evidence on this branch: Semgrep `avoid-pyyaml-load`
  (ERROR), Trivy CVE-2020-14343 (CRITICAL, ships) and CVE-2023-47248
  (CRITICAL, never ships), policy-test `support_agent_reads_only_orders`
  failing on PR #1's branch, and the kubelet observation of 2026-10-30, read
  from `docs/observations.json` and labelled as not collected again. That
  "the kubelet requires authentication" is recorded as a statement in
  STATUS.md, not as a probe result, and the evidence says so.

### Rehearsal (glm-5.3-flash, high)

- Runs 1 to 3, first instructions: all usable. Code flaw 1st and pyarrow last
  in 3 of 3; access drift 2nd in 2 of 3. Run 1 ranked the PyYAML CVE 2nd and
  said the upgrade "fixes the sink finding with it", which is wrong: the pin
  does not remove `Loader=yaml.Loader`. The droid now says rule 4 turns on
  whether the code calls the advisory's function, and that an upgrade never
  fixes a code finding that names an unsafe API.
- Runs 4 to 8, current instructions: all usable. Code flaw 1st, PyYAML 4th and
  pyarrow last in 5 of 5; the exact order code, access drift, kubelet, PyYAML,
  pyarrow in 4 of 5 (run 6 put the kubelet 2nd). 52 to 70 s end to end, the
  model 17 to 27 s and 703 to 1,317 credits. Run 5 cited `server.py:80` for
  the `yaml.load` call, which is in `scenario_import.py:11`.
- `make check`: 169 tests and the repository contracts pass after
  `make install` (the branch pins PyYAML 5.3.1 into `.venv`).

### Not done

- Not pushed, not in the pipeline; the per-PR packets are unchanged. The
  worktree is not yet trusted in interactive Droid.

## 2026-11-26 — Code owners and the push (0.8.2)

### Done

- Added `.github/CODEOWNERS` naming `garymax-cloud`, the second collaborator
  account, for `AGENTS.md`, `Makefile`, `.factory/`, `.github/`, `scripts/`,
  `tests/`, `infra/` and `requirements.txt`. A repository contract keeps the
  judge, the rules and the tests owned.

### Decisions

- With the user's authorization: push `main`, the seeded branch (PR #2) and
  the stacked fix branch, merge `main` into PR #1's branch, then turn on
  rulesets for `main` and `feature/**`: changes by pull request only, the
  deterministic checks required, a code-owner approval required, no force
  push or deletion, and no bypass, the repository admin included. The user
  chose no bypass so that "GitHub enforces the approval" is true for the
  author too. Later changes to `main` go through a pull request approved by
  the second account.
- The prepared `nosemgrep` branch stays local. It is the deterministic
  negative example, and it is not a pull request.

## 2026-11-26 — The verifier asked too little of the regression test (0.8.1)

### What went wrong

- Running the pipeline's verify-fix step locally, before any push, showed
  that the fix pull request as planned (into `main`) would be VERIFIED on
  evidence that proved nothing. The finding lives on the unmerged seeded
  branch, so on `main` the module under test does not exist. The regression
  test failed to import there, and the gate counted that error as "fails on
  the base". Both base scans reported no findings, because `main` never had
  them. Every gate was green and none of them had shown the vulnerability.
- A local test merge of the fix branch into `main` also conflicted in this
  file. GitHub does not run `pull_request` workflows for a pull request with
  a merge conflict, so the checks would not have started at all.
- Checking the new refusal by hand turned up a second false proof. A fix
  branch cut from an older `main`, compared with the current `main`, had an
  out-of-date copy of a test file. The gate took it for the regression test:
  it fails an assertion on the newer code and passes on the branch's older
  code. The verifier now refuses a base that is not in the tree's history.
  The pipeline was never exposed, because it verifies the merge commit.
- Nothing was pushed with that evidence.

### Done

- `regression-test` now needs a changed test to fail an assertion on the
  base. An import error or a crash there is refused and named in the gate's
  detail. `make red-green` shows the same evidence: the changed tests on the
  base, then on this tree.
- AGENTS.md and the fix droid ask for a regression test that reproduces the
  exploit through the entry point an attacker would use, with a harmless
  marker file as the effect.
- The workflow runs on pull requests into any branch, and the verify-fix job
  takes its judge from the default branch. A repository contract keeps both.
- The review's model line reports an override of the droid file, and a
  reasoning effort other than the one asked for.
- 150 unit tests pass (`make check`), on Python 3.14 and the system 3.9.

### Decisions

- A fix pull request targets the branch that has the finding, not `main`.
  The seeded fix goes into `feature/scenarios-from-yaml`, and merging it is
  what clears PR #2. Compared with that base the regression test fails an
  assertion, and both scanners report the findings the fix removes.
- Triage model: `glm-5.3-flash`. Compared with `mistral-medium-3.5` on the
  vulnerable branch, the fix branch, and the test merge of PR #1. glm took 16
  to 86 s and 771 to 1,099 Factory credits a run, kept "the vulnerable
  version is installed" apart from "the vulnerable function is called", and
  named the PR #1 chain. mistral used about 13,000 credits a run, said the
  advisory's function was called, and missed the packet format on the PR #1
  shape (the fail-safe published "Triage unavailable" as designed). Both
  report reasoning effort `high` when asked for `medium`, so the droid file
  now asks for `high`.

### Not done

- Still nothing pushed. Branch protection on `main` does not cover a pull
  request into a feature branch: protect `feature/**` as well when the GitHub
  writes are authorized. How GitHub runs the workflow on that pull request is
  unconfirmed until then.
- The verifier does not read assertions. One rewritten in place to check
  less, with the count unchanged, passes `no-new-suppression`; the reviewer
  reads the test diff.

## 2026-11-26 — Local history and status cleanup

- With user authorization, removed the stray shell line from the unpublished
  loop commit's message. Rebuilt its local descendants with identical file
  trees and valid signatures; Git now recognizes every co-author trailer.
  No GitHub writes occurred, and the suppression worktree's edits were kept.
- Commit mapping: loop 740d162 -> 0b33d26, parser f62f779 -> ea26fd3,
  seeded feature 1c35d38 -> 4b34a57, verified fix 9d7b887 -> 04ff104.
  Earlier entries retain their original rehearsal revision identifiers.
  Recovery references are under `refs/repair-backups/2026-11-26/`.
- Corrected STATUS's unit-test count from 139 to 140, including the parser's
  added regression test.

## 2026-11-26 — Rehearsal of the loop, and one parser fix (0.8.0)

### Done

- Rehearsed the full loop in worktrees. The seeded branch
  (`feature/scenarios-from-yaml`, 1c35d38) is red on both scanners exactly as
  designed, and posting `!!python/object/apply:eval` to the import endpoint
  returns 200 on PyYAML 5.3.1. The prepared suppression branch is refused:
  scanners green, `no-new-suppression` and `regression-test` FAIL.
- `droid exec --auto medium -m gpt-5.5` produced the real fix in ~4.8 min
  (`yaml.safe_load`, pin 5.3.1 -> 6.0.4, regression test); the Stop hook
  verified it on the first stop with every gate PASS. Fix branch
  `fix/yaml-safe-load` (9d7b887) verifies with the before/after record.
- Rehearsed triage on three shapes: the vulnerable branch (true-positive
  packets; the CVE packet separates "the vulnerable version is installed"
  from "the vulnerable function is called"), the fix branch (VERDICT: no
  issues found, plus the fix evidence), and a test merge of main into PR #1's
  branch (policy-test packet; VERDICT: request changes).
- Fixed `policy_findings` for terraform's real output: run lines on stdout,
  Error diagnostics on stderr inside box-drawing frames. Diagnostics are
  matched to runs by name, and an unrecognized format degrades to a fallback
  location instead of losing the finding. Tests use the framed shape.
- Decisions: triage droid `gpt-5.4-mini` (gemini-3.8-flash errors on this
  org; the fail-safe published correctly when it did), fix droid `gpt-5.5`;
  "spring 2027" in speech; a second GitHub account as collaborator for the
  reviewer identity.

### Not done

- Nothing is pushed. main, the seeded branch, and the fix branch wait for
  authorization, then PR #2, the fix PR, branch protection on main, merging
  main into PR #1's branch, and the collaborator invite.

## 2026-11-26 — Findings to verified fixes: the loop (0.8.0)

### Done

- Built the loop that turns findings into verified fixes, on top of the existing
  gates: `scripts/scanners.py` (one pinned scanner definition, normalized
  findings, fail-closed when a scanner cannot run), `scripts/verify_fix.py`
  (the fix gates: no new suppression, regression test fails on the base and
  passes now, unit suite against pinned dependencies, policy test when infra
  changed, both scanners), the Stop hook in `.factory/hooks.json` (verifies on
  `fix/` branches, three blocks, then gives up NOT VERIFIED),
  `scripts/chained_exposure.py` (Terraform + git computation of which identity
  a changed workload runs as, what it can read, and which other branches touch
  the same policy or code), and `scripts/triage.py` with
  `.factory/droids/triage.md` (computed evidence in, one packet per finding
  out, fail-safe that keeps the scanner's severity).
- Pipeline: scanner jobs upload findings artifacts even on failure; a
  `verify-fix` job runs on `fix/` branches with the judge taken from the
  base revision; the review job assembles packets via `scripts/triage.py`;
  the two-job credential split (Factory key vs GitHub token) is unchanged.
  `.github/droid-review-prompt.md` removed, replaced by the droid file plus
  computed evidence.
- AGENTS.md gained the two security-fix rules (no suppressions; regression
  test plus VERIFIED before a fix is done); README, RUNBOOK, DEMO, STATUS
  updated; the external scanner's name scrubbed from DEMO.md, WORKLOG.md and
  the interactive demo page (current files only); DEMO.md's optional UI step
  removed.
- 139 unit tests pass (`make check`), including the new suites for scanner
  classification, suppression and regression gates, the hook's block cap,
  chained-exposure parsing, and packet composition with its fail-safe. Both
  scanners run clean on main through `scripts/scanners.py`; the workflow
  YAML parses and the job graph is as designed.

### Not done

- Seeded PR #2 (vulnerable YAML import), the fix branch, and the rehearsal
  with the real models: next steps, verified locally before any push.
- GitHub writes (pushing main and branches, opening the PRs, merging main
  into PR #1's branch, branch protection, the second collaborator account)
  all await explicit user authorization.
- The recording and the snippets file.

### Decisions

- The triage model is named in `.factory/droids/triage.md`, not in a
  pipeline variable: `droid exec` cannot delegate to a custom droid (no Task
  tool in exec), so the droid file is the single reviewed copy of the model,
  the tool policy (read-only), and the packet format; `check_repository.py`
  fails when the contract breaks (model inherited instead of named, format
  phrases removed, Stop hook missing or short-timeout).
- The verify-fix job takes the verifier and the scanner definition from the
  base revision (`git archive` of the base), so the fix cannot change the
  checks that judge it; the same JUDGES list is enforced locally by the
  no-new-suppression gate.
- The Stop hook only acts on `fix/` branches whose tree differs from the
  base, so read-only sessions and ordinary branches are never blocked; a tree
  that already passed is not verified again (fingerprint in the git dir).
- The triage packet recommends but never changes a check result; the posted
  review carries the model's packets above the computed evidence, and a
  model failure is published as "Triage unavailable, human review required."
  instead of being retried into a guess.
- macOS Docker cannot mount the system temp directory (an unshared path
  mounts empty and a scanner then reports nothing), so scanner exports live
  in `.verify-tmp/` inside the repository and Trivy probes the mount first.

## 2026-11-15 — Folded demo plan; Phase 1 hardening of the reference build (0.7.5)

### Done

- Wrote the software-factory demo program's plan of record in the reference-build working copy (`~/project/droid-software-factory`, git-tracked, import commit `7312c09`): `docs/build-plan.md` folds the agreed narrative spine (entry / pivot / thesis), the demo acts (Build, Repair, Review, Attack, plus Maintain and the one-rulebook close), the per-task model matrix (A: strong hosted coder, B: different-family reviewer, C: small/fast for chores, A′: in-cluster vLLM via BYOK), and the harness beat ("same session, different brain") with its Phase 2 acceptance test. No code in this repo changed; this repo stays the live review-arm evidence (seeded PR #1).
- Phase 1 (fix the reference build, local only) complete there: run-breaking custom model IDs fixed (`custom:<displayName-slug>-<index>`, short displayNames), unverified settings keys removed (`sessionDefaultSettings`, `allowManagedHooksOnly`, `telemetry.format`), `hooks.json` merged into `settings.json`, Router ID `auto` replaced by explicit placeholders.
- Security findings closed: read-only `github-fetcher` token split from the publish token; reviewer runs read-only with the verdict parsed from its captured output (fail-closed); publish rebuilds the diff in a fresh clone (`core.hooksPath=/dev/null`) with protected-path rejection, secret scanning, and config-manifest re-verification; guardrail hooks moved to a read-only ConfigMap mount with sha256 manifest verification before every launch; blanket 443 egress replaced by a git-server CIDR block; the PR-review trigger ignores forks; `guard-execute` blocks `/proc`, `environ`, `git config`, and wrapped commands; `protect-paths` canonicalizes paths and blocks `.git` internals.
- Honesty pass over the reference docs: "nothing leaves the building" → sovereign = "no model vendor sees the code" (only the airgap build is "nothing leaves"); "green is a fact" → the in-pod loop is the agent verifying itself, the PR's CI re-run is the independent fact; "Claude Code can't switch models" → the claim is that only Droid *governs* multi-model.
- Validated locally in the working copy: YAML (ruby stdlib) and JSON parse, `bash -n` on all scripts, and 20 functional hook/verdict/regex tests pass (one real bug found and fixed: `realpath -m` is unavailable on macOS/BSD, so path canonicalization needed a lexical fallback). `shellcheck` is not installed here; skipped and documented. Nothing has run on a cluster yet.

### Not done

- Phase 2 (kind proof, connected profile, seeding `acme-ledger`, recording the acts) — needs a sandbox GitHub repo and a Factory key for the runner, both user-authorized. Phases 3-6 unchanged from the plan.

### Decisions

- The demo keeps Kubernetes + Tekton as the platform arm; drift-lab remains the review-arm target and the already-live PR-workflow evidence. The folded plan lives with the reference build, not in this repo.

## 2026-11-01 — Interactive demo page and slide deck (0.7.4)

### Done

- Built `artifacts/demo-interactive.html` from `docs/DEMO.md`. It has six tabs,
  expandable Whys, a six-step walkthrough, and a gate lab that shows the seeded
  diff and each gate's recorded verdict. Every check-run and review element is
  labeled as a reproduction of PR #1 (run 41073964551), not live AWS data.
- Smoke-tested the page in headless Chrome. All tabs, arrow-key navigation,
  accordions, six steps, and seven gates worked, with no console errors and
  zero non-file network requests.
- Built `artifacts/drift-lab-demo.pptx` (14 slides, 16:9) and checked every
  dense slide visually for clipping. Fixed one overflow and a CSS specificity
  bug that rendered footnotes at body size.

### Not done

- The deck slides are images, so text cannot be edited in PowerPoint. Edits go
  through regenerating the deck.

## 2026-11-01 — Demo script for the verified pipeline (0.7.3)

### Done

- Added `docs/DEMO.md`, the presentation script for the demo flow: background
  and the three Whys (intent lives outside code; generic compliance packs do
  not encode your intent; the agent takes the triage/fix labor while
  deterministic checks keep the trust decision), the walkthrough against PR #1
  with recorded timings (57s review job), the benefit analysis table, and the
  closing cost-per-verified-fix framing.
- Every claim in the script traces to a commit, a recorded run, or a
  documented decision. The deliberately excluded claims are stated on stage:
  one seeded case only, the UI is fixture replay, the benchmark arms are
  designed but unmeasured, and remediation stays authorized human work.
- README layout table now lists the demo script.

## 2026-10-30 — Droid review arm verified end-to-end (0.7.2)

### Done

- User set `FACTORY_API_KEY` as a repository secret; re-triggered seeded PR #1
  (empty commit f8f50cf). The full arm ran as designed:
  - `droid availability`: pass — reports the key as configured (boolean only;
    the value never left the secret store)
  - `droid review (read-only)`: pass, 57s — captures `make check` (exit 0,
    75 tests + contracts) and `make policy-test` (exit 2), runs the read-only
    `droid exec` review with those outcomes and the standing prompt, uploads
    the review as an artifact
  - `post droid review`: pass, 5s — the token-only job posts the review as a
    PR comment
- The posted review behaved as the design intends:
  - cites the deterministic gate, run, exact assertion condition, and assertion
    text — it does not re-decide the verdict
  - classifies the seed correctly: a proposed intent change, not out-of-band
    drift or noise; an approved expansion would have to update the capability
    baseline, and this seed does not
  - states the evidence is mock-provider verification, not live AWS access
  - notes the merge-ref nuance (workspace HEAD carries main's later commits)
    without inventing issues from it
  - ends with the required single line, `VERDICT: request changes`, and a
    verified fix path: restore the conditional, re-run `make policy-test`, all
    five runs pass without weakening assertions

### Verified

- PR #1 stays open as the live demo: all deterministic gates green except the
  seeded capability failure, and the Droid review posted citing exactly that
  failure. The workflow never plans or applies against AWS, and no job holds
  both the Factory key and a GitHub write token.

## 2026-10-30 — First live PR run: the scanner caught the pipeline itself (0.7.1)

### Done

- Opened verification PR #1, seeded with the 0.6.0 support-role read
  broadening (deliberate regression, never to be merged). First live run of
  the 0.7.0 workflow:
  - `make check`: pass
  - `terraform-check + policy-test`: fail — run
    `support_agent_reads_only_orders` fails on "support-agent must read only
    the customer-orders table"; the other four capability runs pass
  - `trivy`: pass
  - `droid availability`: pass (it reports only whether FACTORY_API_KEY is
    configured, never the value)
  - `droid review (read-only)` and `post droid review`: skipped, as designed
  - `semgrep`: fail — a real finding, below
- The Semgrep finding: `gha-curl-pipe-shell` on the new workflow's Droid CLI
  install step. Local pre-verification on 0.7.0 could not see it: the scanner
  ran before the workflow file existed. CI scanning the new file activated the
  yaml.github-actions rules (286 to 310 rules, 54 to 56 files) and the pattern
  matched. The deterministic scanner caught a genuine supply-chain pattern in
  the very change that introduced the scanning — the prototype's thesis
  applied to itself.

### Decision

- Accepted inline (annotation on the `run: |` match line, rationale in the
  workflow): the Factory CLI install is the vendor's documented path, over
  TLS from the vendor's own domain, on an ephemeral runner, in a job whose
  only credential is the FACTORY_API_KEY that same vendor issued.
  Download-then-exec would hide the identical trust from the scanner without
  reducing it — a scanner pass bought by laundering the pattern. The inline
  annotation keeps the acceptance visible at the source line instead.
- Not chosen: `--skip-rule` (would silence the pattern for future workflow
  files too) and download-then-exec (security theater: semgrep passes while the
  same script still executes).
- Annotation placement: the rule matches the whole `run:` block, so the
  annotation goes on the `run: |` line — the first line of the match — not
  the `curl` line. Same lesson as 0.7.0's KMS annotation: the ID in the
  annotation must be the full rule ID, and the line must be the match start.

### Verified

- The re-triggered run on PR #1 (merge of main with the 0.7.1 annotation and
  the seeded broadening) landed the intended matrix:
  - `make check`: pass
  - `semgrep`: pass — the inline acceptance works in CI
  - `trivy`: pass
  - `terraform-check + policy-test`: fail — 4 passed, 1 failed, on exactly
    "support-agent must read only the customer-orders table"
  - `droid availability`: pass (FACTORY_API_KEY still unset)
  - `droid review (read-only)` / `post droid review`: skipped, as designed
- Cross-arm observation, recorded factually: the external IAC and SCA
  checks (partner-demo account) reported pass on the same seeded broadening.
  Generic compliance packs do not encode this lab's capability intent; the
  repo's own policy-as-code does. One seeded case, no generalization beyond
  it.

### Not done

- The full Droid review arm (credentialed exec + posted comment) awaits the
  user setting `FACTORY_API_KEY` as a repository secret; the user chose to
  verify it end-to-end and to keep PR #1 open as a live demo.

## 2026-10-30 — Pull-request workflow with credential-separated Droid review (0.7.0)

### Done

- Pre-verified the scanner arms locally before wiring CI, using the same
  digest-pinned images CI runs: Semgrep 1.183.0 (OWASP Top 10; 286 rules over
  54 files) and Trivy 0.76.1 (vuln + secret). Both clean on main.
- Added `.github/workflows/pull-request.yml`: deterministic gates (make check;
  terraform-check + policy-test; semgrep; trivy) plus a Droid review arm with
  separated credentials — `FACTORY_API_KEY` lives only in the read-only
  `droid exec` job, `GITHUB_TOKEN` (pull-requests: write) only in the posting
  job. Actions pinned by SHA; scanner images pinned by digest.
- The Droid job captures `make check` and `make policy-test` outcomes for the
  PR and passes them with the standing prompt, so the review cites
  deterministic findings instead of re-deciding them.

### Findings

- Semgrep flagged the synthetic DynamoDB tables
  (`aws-dynamodb-table-unencrypted`: wants a customer-managed KMS key).
  Triaged and accepted inline with rationale — synthetic, disposable data;
  AWS-managed SSE is deliberate for this lab.
- Trivy found no secrets: the deliberate test-fixture strings are not
  credential-shaped, and real account IDs never enter the repo.
- The Droid arm stays skipped until `FACTORY_API_KEY` is set as a repository
  secret (user action; the gate job never exposes the value).

### Not done

- The Droid arm has not been observed on a real run yet: it needs the repo
  secret.

## 2026-10-30 — Capability intent as policy-as-code (0.6.0)

### Done

- Added `infra/workloads/policy.tftest.hcl`: five plan-only runs with mocked AWS
  and Kubernetes providers, asserting the approved capability intent (read
  scope, identity pinning, workload hardening, namespace isolation). Runs in a
  disposable copy (`make policy-test`) so the operator's initialized S3-backend
  directory is untouched; no credentials and no account access.
- Verified both directions: passes on the approved revision; a seeded
  support-role broadening (orders + archive, the live drift shape) fails the
  suite with exit 1.

### Findings

- Terraform test mock providers need `override_during = plan` (on the provider
  and in each `override_resource` block) for computed values to be known in
  plan-only runs; otherwise assertions fail with "Unknown condition value".
- Generated mock ARNs are not format-valid, which breaks apply runs through
  attributes that validate ARNs (`aws_eks_pod_identity_association.role_arn`).
  Plan-only runs plus explicit ARN overrides avoid both problems.
- Provider shape quirks: `policy_types` and `capabilities.drop` compare as sets,
  and `spec.replicas` surfaces as the string "1"; normalize with `toset()` and
  `tonumber()`.

## 2026-10-30 — Sanitizer paths and the committed live collector (0.5.0)

### Done

- Verified the GitHub `security-lab` environment lockdown: required reviewer,
  branch-policy rule, custom policies, `main` only.
- Sanitizer upgrade, closing the drift-exercise findings: changed-attribute paths
  (names only, non-identifier segments hashed), `resource_version`/`generation`
  and null-versus-empty noise rows dropped, the `aws_iam_role.inline_policy`
  mirror collapsed into the changed `aws_iam_role_policy` for the same role, and
  `refresh_only_verdict` classifying output-only exit 2 as no-drift. 13 tests.
- Committed the one-off live cross-check as `python -m drift_lab collect`
  (read-only, injectable CLI runner, fail-closed mapping, sanitized snapshots,
  exit codes 0/2/3). Live smoke test against the lab: the first run failed closed
  on the Pod Identity reads; fixed the runner (list, then describe by association
  id) and re-verified: complete collection of all eight tracked resources, clean
  baseline comparison, exit 0. 12 tests.
- `make check`: 75 tests, byte-compile, repository contracts.

### Findings

- `aws eks describe-pod-identity-association` requires `--association-id`;
  service accounts are not a lookup key. The collector lists, then describes.
- The collector's fail-closed design held up live: failed reads produced an
  `incomplete` snapshot (exit 3) with the affected resources omitted, never a
  guessed value or a deletion claim.

### Not done

- Teardown and the up -> down -> up proof; cost recording.
- The preview UI still replays fixtures; `collect` output is not wired into it.

## 2026-10-30 — Live drift exercise (0.4.0)

### Done

- Renewed SSO (user-approved). Took a baseline of `workloads`: accepted the provider
  null-to-empty normalization on the Deployment into state (refresh-only apply), so
  `resource_drift` started empty.
- Injected two out-of-band drifts: an IAM inline-policy edit (support role gains
  `customer-archive`) and a `kubectl patch` of the Deployment's ServiceAccount to
  `reporting-agent`.
- Both were detected by `plan -refresh-only` (resource_drift) and by the normal plan
  (exit 2, 2 updates), and sanitized through `import-plan`. Live reads fed to the
  rules engine gave two HIGH findings and the forbidden-dataset capability path.
- Reconciled with user approval: applied the normal plan (2 changed). The re-plan
  was clean (exit 0); the remaining refresh-only rows were `resource_version`
  noise only.
- Changed the fixture replica range from 2-4 to 1-4 to match the deployed IaC.
  Added a regression test (50 tests).
- Evidence record: `artifacts/validation.md` (sanitized).

### Findings

- The sanitizer reports noise (`resource_version`, null versus empty) the same way
  as real drift. It needs changed-attribute paths and noise filters.
- Refresh-only exit 2 also fires for output-value changes alone.
- IAM inline-policy drift appears on both the policy and the parent role.

### Not done

- Teardown and the up -> down -> up proof; cost recording.
## 2026-10-29 — Phase 1 deployment (0.3.0)

### Done

- Git: initialized `main` and made a GPG-signed first commit (`87f37a8`) with the
  user's key. Created the public repository `GosYao/drift-lab` and pushed. Created
  the `security-lab` environment.
- AWS login via `aws sso login --profile demo-admin` (user-approved in the browser).
- Account check (read-only) before any apply: the profile uses a corporate SSO start
  URL, and the account is not empty. us-east-1 has 5 VPCs and 121 tagged
  resources; ca-central-1 has 3 custom VPCs, 79 tagged resources, and an unrelated
  EKS cluster. I raised this; the user chose to proceed in ca-central-1. There were
  no name collisions. A GitHub OIDC provider already existed, so it is reused.
- Verified the OIDC subject: repositories created after 2026-07-15 use immutable
  subjects. The role trusts
  `repo:GosYao@45461592/drift-lab@1439230701:environment:security-lab`.
- Added an opt-in EKS public endpoint (`public_access_cidrs`, `/32` only; see the
  ADR 0003 amendment) so the laptop can apply `workloads`.
- `foundation`: planned 10 resources, applied, migrated state to S3, re-plan clean.
- `eks-lab`: planned 32, applied 30. The access entry failed because EKS rejects
  the path-less SSO role ARN (the "remove the path" advice applies to `aws-auth`,
  not access entries). Re-applied the remaining 2 with the full ARN.
- Image: built `linux/amd64` on a digest-pinned `python:3.12-slim`, pushed tag
  `87f37a8` (digest `sha256:8351be12…`), and smoke-tested it locally read-only, as
  UID 10001, with all capabilities dropped.
- `workloads`: three fixes found only by a live apply.
  1. The PSA `enforce-version` label must be `v1.36`, not `1.36`.
  2. The Kubernetes provider writes container `runAsNonRoot: false` unless it is
     set explicitly, so restricted Pod Security rejected the pod. Set
     `run_as_non_root = true` on the container.
  3. After the failed rollout, the provider hit an "Unexpected Identity Change" bug
     on the tainted Deployment. Ran `state rm`, deleted the empty Deployment, and
     re-created it.
- Verified the pod, probes, Pod Identity, the enforced default-deny policy, and the
  app via port-forward. All three stacks re-plan with exit 0.

### Findings

- Default-deny egress still allows pod -> local node kubelet (`:10250`).
- ECR basic scan-on-push produced no scan; the account likely uses enhanced
  (Inspector) scanning.

### Not done

- Teardown and the up -> down -> up proof; the live drift exercises; cost recording.
- Removing the public endpoint `/32`.
## 2026-10-29 — GitHub-side previews (0.2.0)

### Done

- Added `drift_lab/github_view.py` with three trigger fixtures (PR review, push
  check-runs and commit comments, scheduled drift issue). Comment text is
  template-generated from `engine.compare`/`engine.replay` output, and the
  PR diff follows the real `infra/workloads/main.tf` lines 71-82.
- Added `/api/triggers` and `/api/github` routes, the UI panel, styles, and 12 tests.
  `make check` passes: 49 tests, compileall, and repository contracts.
- Restarted the preview server. Verified all three triggers through agent-browser
  snapshots and captured screenshots (`artifacts/github-preview-*.png`). Screenshot
  capture worked this time, which resolves the earlier screenshot follow-up for
  this view.

### Decisions

- Scheduled drift files an issue instead of a PR comment, because runtime drift is
  found after deploy and has no diff to annotate.
- Check verdicts come from the deterministic finding. Comment prose only explains it.
- The Semgrep and Trivy check-runs are illustrative fixture rows. Those scanners
  have not run in this repository yet.

### Not done

- No GitHub App, workflow, token, or API call. Nothing was posted to any repository.
  Real publishing needs a control repository, app permissions (checks:write,
  pull-requests:write, issues:write), and authorization.

## 2026-10-29

### Done

- Scaffolded the repository: `AGENTS.md` (ground rules), `Makefile`, `Dockerfile`,
  `.dockerignore`, `.gitignore`, `artifacts/`.
- Built the local prototype: `drift_lab/` (scenario fixtures, deterministic engine,
  plan sanitizer, HTTP server, CLI, static UI) and the test suite — 37 tests
  passing.
- Added `scripts/preflight.py`, `scripts/check_repository.py`, and
  `scripts/bootstrap_local_tools.py`; installed checksum-pinned Terraform 1.13.5 and
  agent-browser 0.40.0 under `.tools/` and verified both.
- Authored three Terraform stacks; applied `terraform fmt`; created provider lock
  files. All stacks pass `init -backend=false` + `validate` (AWS pinned 6.71.0,
  Kubernetes pinned 2.38.0). No AWS API call was made and no backend was configured.
- Ran the preview server locally; confirmed pages and the API respond on
  `127.0.0.1:8765`; captured an agent-browser accessibility snapshot of the UI.
- Wrote the documentation set (README, STATUS, ARCHITECTURE, RUNBOOK, ROADMAP,
  CHANGELOG, ADRs 0001-0003). Pinned `make terraform-check` to `.tools/terraform`
  with `-input=false`, and removed a stray `@import` line from `styles.css`.
- Extended `scripts/preflight.py` to report pinned `.tools/` binaries, so Terraform
  is not reported missing when it is used from `.tools/` instead of PATH.

### Decisions

- Evidence-first architecture (ADR-0001): the deterministic engine decides; models
  only explain; `inconclusive` is a valid outcome; sanitize before any boundary
  crossing.
- Three Terraform stacks with strict apply/destroy order (ADR-0002); S3 native
  lockfile; `prevent_destroy` state bucket.
- EKS baseline (ADR-0003): Pod Identity, private API endpoint, IMDSv2, restricted
  namespace, default-deny NetworkPolicy, digest-pinned image.
- EKS over Lambda to showcase Kubernetes-flavored drift; Terraform for repeatable
  up/down/up; drift detection via `plan -refresh-only` and plan-JSON exit codes;
  remediation may be reconciliation rather than a PR; no claim of Wiz-style feature
  parity.

### Checks that failed or were skipped (recorded, not hidden)

- agent-browser viewport sizing: not controllable from this Factory pane — skipped.
- UI screenshot: failed twice (daemon read stall, `Resource temporarily unavailable`); no image artifact saved. The page itself loads and snapshots fine, so the failure is specific to screenshot capture.
- `terraform plan` against AWS: not run (no credentials, no authorization, no
  backend).
- Docker image build/push: not run; the Deployment's image digest does not exist yet.
- Live AWS/Kubernetes collection and Droid workflow integration: not implemented in
  Phase 0 (fixtures only, by design).
- Git initialization/commit: not done; the directory is not a repository yet.

### Known risks

- Default-deny NetworkPolicy vs kubelet probes (readiness/liveness) is untested
  until deployed; probes may need an explicit allowance.
- Default-deny egress blocks DynamoDB/Bedrock for any real agent; Pod Identity
  credential delivery under this policy is unverified. A reviewed allow-list is
  required before a real workload.
- CNI network-policy enforcement relies on node-role CNI permissions at bootstrap;
  move CNI to a dedicated identity before untrusted workloads.
- Private EKS API endpoint requires in-VPC access for administration and for the
  `workloads` apply.
- Budget is reporting-only (no alerts yet); `expires_at` tags are advisory until a
  cleanup controller exists.

### Follow-ups

- Initialize git and make the first commit (include `.terraform.lock.hcl` files;
  `.gitignore` already excludes `.terraform/`, state, and tfvars while keeping
  `*.tfvars.example`).
- Decide the control repository, GitHub environment, and exact OIDC subject; verify
  GitHub's current subject-claim format before any foundation apply.
- Get explicit authorization for Phase 1: apply order, image publish, up -> down ->
  up proof, probe/NetworkPolicy verification.
- Retry the UI screenshot for `artifacts/preview.png` (try headed mode or an alternate capture tool; the CLI snapshot path works).
- Phase 2: read-only AWS/Kubernetes collectors emitting the same evidence shape as
  the fixtures.
