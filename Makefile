PYTHON ?= python3
TERRAFORM ?= $(if $(wildcard .tools/terraform),.tools/terraform,terraform)

.PHONY: preview test check report preflight terraform-check

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
