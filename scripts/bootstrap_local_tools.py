"""Optional, checksum-verified local validation tools for this macOS ARM workspace.

Downloads only into the ignored .tools directory. No global installation.
Checksums were obtained from the official release checksum/API metadata.
"""

import argparse
import hashlib
import io
from pathlib import Path
import platform
from urllib.request import urlopen
import zipfile

TOOLS = {
    "terraform": (
        "https://releases.hashicorp.com/terraform/1.13.5/terraform_1.13.5_darwin_arm64.zip",
        "1bf942231235e7e1a4c38c6d7b820e54f526ac487f87d19f0c4a425c6ddb62cb",
    ),
    "agent-browser": (
        "https://github.com/vercel-labs/agent-browser/releases/download/v0.40.0/agent-browser-darwin-arm64",
        "b064c9107a0431c76d8916e47c2c8ac322f49c2b2720d6c9036ab538ec1ed911",
    ),
}

parser = argparse.ArgumentParser()
parser.add_argument("tool", choices=TOOLS)
args = parser.parse_args()
if platform.system() != "Darwin" or platform.machine() != "arm64":
    raise SystemExit("This optional bootstrap is pinned for macOS ARM64 only.")
url, expected = TOOLS[args.tool]
with urlopen(url, timeout=90) as response:
    data = response.read()
if hashlib.sha256(data).hexdigest() != expected:
    raise SystemExit("Checksum mismatch; no executable was installed.")
if args.tool == "terraform":
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        data = archive.read("terraform")
directory = Path(__file__).resolve().parent.parent / ".tools"
directory.mkdir(exist_ok=True, mode=0o700)
destination = directory / args.tool
destination.write_bytes(data)
destination.chmod(0o700)
print("Verified local tool:", destination)
