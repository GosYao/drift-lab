"""Basic repository-contract checks, not a replacement for Terraform validation."""

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
required = ["README.md", "AGENTS.md", "docs/STATUS.md", "docs/ARCHITECTURE.md",
            "docs/WORKLOG.md", "docs/CHANGELOG.md", "docs/RUNBOOK.md",
            "docs/ROADMAP.md", "docs/adr/0001-evidence-first.md",
            "infra/foundation/main.tf", "infra/eks-lab/main.tf",
            "infra/workloads/main.tf",
            ".factory/hooks.json", ".factory/droids/triage.md",
            ".factory/droids/fix.md",
            "scripts/scanners.py", "scripts/verify_fix.py", "scripts/triage.py",
            "scripts/chained_exposure.py"]
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

# The droids and the Stop hook are the contract between the repository and the
# agent harness; check they still say what the pipeline assumes they say.
sys.path.insert(0, str(ROOT / "scripts"))
import triage  # noqa: E402

problems = triage.droid_contract(ROOT / ".factory/droids/triage.md")
if problems:
    raise SystemExit("Triage droid contract failed: " + "; ".join(problems))
fix_meta, _ = triage.load_droid(ROOT / ".factory/droids/fix.md")
if fix_meta.get("model", "inherit") == "inherit":
    raise SystemExit("The fix droid must name its model, not inherit one.")

hooks = json.loads((ROOT / ".factory/hooks.json").read_text())
commands = [hook for group in hooks.get("Stop", []) for hook in group.get("hooks", [])]
runs_verifier = any("verify_fix.py" in command.get("command", "")
                    and "--stop-hook" in command.get("command", "")
                    and int(command.get("timeout", 0)) >= 120
                    for command in commands)
if not runs_verifier:
    raise SystemExit("The Stop hook must run verify_fix.py --stop-hook "
                     "with a timeout of at least 120 seconds.")

print("Repository contracts and static DOM references: passed.")
