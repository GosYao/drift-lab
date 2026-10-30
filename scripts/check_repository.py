"""Basic repository-contract checks, not a replacement for Terraform validation."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
required = ["README.md", "AGENTS.md", "docs/STATUS.md", "docs/ARCHITECTURE.md",
            "docs/WORKLOG.md", "docs/CHANGELOG.md", "docs/RUNBOOK.md",
            "docs/ROADMAP.md", "docs/adr/0001-evidence-first.md",
            "infra/foundation/main.tf", "infra/eks-lab/main.tf",
            "infra/workloads/main.tf"]
missing = [name for name in required if not (ROOT / name).is_file()]
if missing:
    raise SystemExit("Missing documented files: " + ", ".join(missing))
html = (ROOT / "drift_lab/static/index.html").read_text()
js = (ROOT / "drift_lab/static/app.js").read_text()
ids = set(re.findall(r'id="([^"]+)"', html))
references = set(re.findall(r'\$\("([^"]+)"\)', js))
if references - ids:
    raise SystemExit("Missing HTML IDs: " + ", ".join(sorted(references - ids)))
if "innerHTML" in js or "eval(" in js:
    raise SystemExit("Use textContent/DOM APIs for report values, not HTML/eval.")
print("Repository contracts and static DOM references: passed.")
