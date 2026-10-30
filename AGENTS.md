# Working on this prototype

- Read `docs/STATUS.md` and the relevant architecture decision before changing scope.
- Keep `docs/CHANGELOG.md` and `docs/WORKLOG.md` current for meaningful changes.
- Never describe fixture observations, fixture replay, or template explanations as live
  AWS collection, exploitation, or an actual Droid investigation.
- Detection and graph construction are deterministic. A model may explain evidence;
  it cannot fabricate graph edges or make the trusted validation decision.
- Do not put credentials, raw Terraform state, raw plans, or customer data in reports.
- No AWS provisioning, GitHub writes, or automatic reconciliation without authorization.
- Test with `make test`. Run `make check` for the complete locally available checks.
- Infrastructure planning must use the approved deployment revision, not PR-supplied code.
- Keep application execution, cloud deployment, and report publishing credentials separate.
- Document prerequisites and skipped checks; never replace an unavailable check with a
  claimed success.
