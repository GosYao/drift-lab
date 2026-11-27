PYTHON ?= python3
# Once `make install` has created .venv, the prototype uses it automatically.
PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,$(PYTHON))
TERRAFORM ?= $(if $(wildcard .tools/terraform),.tools/terraform,terraform)

.PHONY: preview test check install report preflight terraform-check policy-test \
	scan triage triage-queue verify-fix red-green demo-reset

preview:
	$(PYTHON) -m drift_lab serve

test:
	$(PYTHON) -m unittest discover -s tests -v

check: test
	$(PYTHON) -m compileall -q drift_lab tests scripts
	$(PYTHON) scripts/check_repository.py

# Dependencies are pinned in requirements.txt and installed into .venv only.
# On branches without requirements.txt the prototype is stdlib-only.
install:
	@if [ -f requirements.txt ]; then \
		[ -d .venv ] || python3 -m venv .venv; \
		.venv/bin/pip install -q --disable-pip-version-check -r requirements.txt; \
		echo "Installed requirements.txt into .venv; make test now uses it."; \
	else \
		echo "No requirements.txt: stdlib-only, nothing to install."; \
	fi

report:
	$(PYTHON) -m drift_lab report --scenario iam

preflight:
	$(PYTHON) scripts/preflight.py

terraform-check:
	$(TERRAFORM) fmt -check -recursive infra
	$(TERRAFORM) -chdir=infra/foundation init -input=false -backend=false
	$(TERRAFORM) -chdir=infra/foundation validate
	$(TERRAFORM) -chdir=infra/eks-lab init -input=false -backend=false
	$(TERRAFORM) -chdir=infra/eks-lab validate
	$(TERRAFORM) -chdir=infra/workloads init -input=false -backend=false
	$(TERRAFORM) -chdir=infra/workloads validate

# Capability-intent tests with mock providers: no cloud account, no credentials.
# Runs in a disposable copy so the operator's initialized working directory
# (S3 backend) is never touched.
policy-test:
	rm -rf .policy-test-tmp
	mkdir -p .policy-test-tmp
	cp -R infra/workloads .policy-test-tmp/workloads
	rm -rf .policy-test-tmp/workloads/.terraform
	$(TERRAFORM) -chdir=.policy-test-tmp/workloads init -input=false -backend=false
	$(TERRAFORM) -chdir=.policy-test-tmp/workloads test
	rm -rf .policy-test-tmp

# The pinned scanners, exactly as the pipeline runs them (needs Docker).
scan:
	$(PYTHON) scripts/scanners.py semgrep trivy

# One review packet per finding: computed evidence plus the triage model's
# reading of it (needs the droid CLI; read-only).
triage:
	$(PYTHON) scripts/triage.py

# Every open signal in one ranked list: this tree's scanners, the policy test
# on branches that change a role's policy, and recorded observations (needs
# Docker, Terraform and the droid CLI; read-only).
triage-queue:
	$(PYTHON) scripts/triage_queue.py

# The gates a security fix must pass: no new suppression, a regression test
# that fails on the base, the unit suite, the policy test when infra changed,
# and both scanners. The Stop hook runs the same check on fix/ branches.
verify-fix:
	$(PYTHON) scripts/verify_fix.py

# The regression-test gate's evidence, shown: the fix's changed tests run on
# the base (red), then on this tree (green).
red-green:
	$(PYTHON) scripts/verify_fix.py --red-green

# Demo hygiene: clear the Stop hook's verified state (including linked
# worktrees) and the triage and scanner scratch directories.
demo-reset:
	rm -rf .triage .verify-tmp
	@main="$$(git rev-parse --absolute-git-dir)" && rm -f "$$main/verify-fix-state.json" && \
		for dir in "$$main"/worktrees/*; do rm -f "$$dir/verify-fix-state.json" 2>/dev/null || true; done && \
		echo "verify-fix state cleared; the hook verifies again on the next stop."
