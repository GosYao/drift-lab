import argparse
import json
from pathlib import Path

from .engine import compare
from .scenarios import scenario, SCENARIOS
from .terraform_plan import load_plan


def main():
    parser = argparse.ArgumentParser(description="Evidence-first drift lab; local fixture mode by default.")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Run the local preview")
    serve.add_argument("--host", choices=["127.0.0.1", "0.0.0.0"], default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    demo = commands.add_parser("report", help="Print a deterministic fixture report")
    demo.add_argument("--scenario", choices=[s["id"] for s in SCENARIOS], default="iam")
    imp = commands.add_parser("import-plan", help="Emit metadata only; never emit raw plan values")
    imp.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "serve":
        from .server import serve as run
        run(args.host, args.port)
    elif args.command == "report":
        print(json.dumps(compare(*scenario(args.scenario)), indent=2))
    else:
        print(json.dumps(load_plan(args.path), indent=2))


if __name__ == "__main__":
    main()
