"""Command line entry point: `python -m hypotrail`.

With `--json`, stdout holds exactly one JSON object and human diagnostics go to
stderr. Every error has `code`, `message`, `stage` and `details`.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from hypotrail.core.errors import EXIT_INFRASTRUCTURE, EXIT_OK, HypotrailError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hypotrail",
        description="Small, explicit studies of predictive and agentic systems.",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    data = commands.add_parser("data", help="check the public datasets")
    data_commands = data.add_subparsers(dest="data_command", metavar="ACTION")
    verify = data_commands.add_parser(
        "verify", help="check the datasets against data-sources.lock.json"
    )
    verify.add_argument(
        "--workload",
        action="append",
        metavar="NAME",
        help="verify only this Workload (repeatable); default: all",
    )
    verify.add_argument(
        "--examples-dir",
        type=Path,
        metavar="DIR",
        help="directory holding the Workloads (default: the repository's examples/)",
    )
    verify.add_argument("--json", action="store_true", help="print one JSON object")
    verify.set_defaults(handler=_data_verify)
    return parser


def _emit(payload: dict, as_json: bool, human: str) -> None:
    print(json.dumps(payload, indent=2) if as_json else human)


def _data_verify(args) -> int:
    from hypotrail.core import data

    examples = args.examples_dir or data.default_examples_dir()
    reports = data.verify_workloads(examples, args.workload)
    lines = [
        f"{r['workload']}: {r['dataset_id']} verified "
        f"({r['file']}, sha256 {r['sha256'][:12]}..., licence {r['license']})"
        for r in reports
    ]
    _emit({"ok": True, "datasets": reports}, args.json, "\n".join(lines))
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return EXIT_OK
    try:
        return handler(args)
    except HypotrailError as error:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": error.to_dict()}, indent=2))
            print(f"{error.code} [{error.stage}]: {error.message}", file=sys.stderr)
        else:
            print(f"{error.code} [{error.stage}]: {error.message}", file=sys.stderr)
        return error.exit_code
    except OSError as error:
        failure = HypotrailError(
            "INFRASTRUCTURE_FAILURE",
            f"{type(error).__name__}: {error}",
            stage="infrastructure",
            exit_code=EXIT_INFRASTRUCTURE,
        )
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": failure.to_dict()}, indent=2))
        print(f"{failure.code}: {failure.message}", file=sys.stderr)
        return failure.exit_code
