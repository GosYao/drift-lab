PYTHON ?= python3
TERRAFORM ?= $(if $(wildcard .tools/terraform),.tools/terraform,terraform)

.PHONY: preview test check report preflight terraform-check policy-test

preview:
	$(PYTHON) -m drift_lab serve

test:
	$(PYTHON) -m unittest discover -s tests -v

check: test
	$(PYTHON) -m compileall -q drift_lab tests scripts
	$(PYTHON) scripts/check_repository.py

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
