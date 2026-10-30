import argparse
import json
import sys
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
    collect_cmd = commands.add_parser(
        "collect",
        help="Read-only live collection into the sanitized-observation schema")
    collect_cmd.add_argument("--config", type=Path, required=True,
                             help="Lab topology JSON (see configs/collector.json)")
    collect_cmd.add_argument("--baseline", type=Path,
                             help="Compare against a snapshot collected from the approved state")
    collect_cmd.add_argument("--profile", help="AWS profile for the read-only CLI calls")
    collect_cmd.add_argument("--region", help="AWS region for the read-only CLI calls")
    collect_cmd.add_argument("--kubeconfig", type=Path,
                             help="Kubeconfig for the read-only kubectl call")
    collect_cmd.add_argument("--observed-at",
                             help="Override the observation timestamp (ISO-8601)")
    args = parser.parse_args()
    if args.command == "serve":
        from .server import serve as run
        run(args.host, args.port)
    elif args.command == "report":
        print(json.dumps(compare(*scenario(args.scenario)), indent=2))
    elif args.command == "collect":
        from .collector import (CliRunner, collect_exit_code, collect_snapshot,
                                compare_with_baseline)
        try:
            config = json.loads(args.config.read_text(encoding="utf-8"))
            snapshot = collect_snapshot(
                config,
                CliRunner(profile=args.profile, region=args.region,
                           kubeconfig=str(args.kubeconfig) if args.kubeconfig else None),
                observed_at=args.observed_at)
            if args.baseline:
                baseline_snapshot = json.loads(args.baseline.read_text(encoding="utf-8"))
                output = compare_with_baseline(baseline_snapshot, snapshot)
            else:
                output = snapshot
        except (ValueError, OSError) as error:
            parser.exit(2, "collect: " + str(error) + "\n")
        print(json.dumps(output, indent=2))
        return collect_exit_code(output)
    else:
        print(json.dumps(load_plan(args.path), indent=2))


if __name__ == "__main__":
    sys.exit(main())
