"""Read-only local prerequisite inventory. Never prints credentials."""

import json
import platform
import shutil
import sys
from pathlib import Path

tools = {name: bool(shutil.which(name)) for name in
         ("python3", "git", "terraform", "aws", "kubectl", "docker", "droid")}
root = Path(__file__).resolve().parent.parent
pinned_tools = {
    name: (root / ".tools" / name).is_file()
    for name in ("terraform", "agent-browser")
}
print(json.dumps({
    "python": platform.python_version(),
    "tools": tools,
    "pinned_tools": pinned_tools,
    "preview_ready": sys.version_info >= (3, 9),
    "terraform_available": tools["terraform"] or pinned_tools["terraform"],
    "cloud_ready": all(tools[name] for name in ("terraform", "aws", "kubectl", "docker", "droid")),
    "note": "Tool presence is not AWS authorization, model access, or deployment approval.",
}, indent=2))
