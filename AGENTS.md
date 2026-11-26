# Working on this prototype

- Read `docs/STATUS.md` and the relevant architecture decision before changing scope.
- Keep `docs/CHANGELOG.md` and `docs/WORKLOG.md` current for meaningful changes.
- Never describe fixture observations, fixture replay, or template explanations as live
  AWS collection, exploitation, or an actual Droid investigation.
- Detection and graph construction are deterministic. A model may explain evidence;
  it cannot fabricate graph edges or make the trusted validation decision.
- Never add a suppression to turn a check green: no `nosemgrep`, no ignore-file
  entries, no weaker scanner command. Accepting risk is a human decision with a
  recorded rationale in `docs/WORKLOG.md`.
- A security fix needs a regression test that reproduces the exploit: it sends the
  attack input through the entry point an attacker would use and asserts that the
  attack's effect does not happen. It must fail that assertion on the code before
  the fix and pass after. Use a harmless, observable effect (a marker file in a
  temporary directory), never a destructive or networked payload.
- `make verify-fix` must report VERIFIED before a security fix is called done.
- Do not put credentials, raw Terraform state, raw plans, or customer data in reports.
- No AWS provisioning, GitHub writes, or automatic reconciliation without authorization.
- Test with `make test`. Run `make check` for the complete locally available checks.
- Infrastructure planning must use the approved deployment revision, not PR-supplied code.
- Keep application execution, cloud deployment, and report publishing credentials separate.
- Document prerequisites and skipped checks; never replace an unavailable check with a
  claimed success.
