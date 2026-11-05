"""Command line entry point: `python -m hypotrail`.

With `--json`, stdout holds exactly one JSON object and human diagnostics go to
stderr. Every error has `code`, `message`, `stage` and `details`.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from hypotrail.core.errors import (
    EXIT_INFRASTRUCTURE,
    EXIT_OK,
    HypotrailError,
    InvalidInputError,
)


class _ArgumentParser(argparse.ArgumentParser):
    """An argument error is a Hypotrail error, so `--json` can report it as one."""

    def error(self, message):
        self.print_usage(sys.stderr)
        raise InvalidInputError(
            "INVALID_ARGUMENTS", message, stage="config", details={"command": self.prog}
        )


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
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

    spike = commands.add_parser("spike", help="feasibility spike entry points")
    spike_commands = spike.add_subparsers(dest="spike_command", metavar="ACTION")
    live = spike_commands.add_parser(
        "live",
        help="opt-in, paid: run the spike task against a real Anthropic model "
        "(at most 2 Episodes on dev Cases)",
    )
    live.add_argument(
        "--config",
        required=True,
        metavar="NAME",
        help="the declared Configuration to run, one per invocation (chinook: plain or verify)",
    )
    live.add_argument("--model", help="explicit model identifier, as anthropic/<model>; no default")
    live.add_argument(
        "--case",
        action="append",
        metavar="CASE_ID",
        help="a dev Case (repeatable; default: D03 and D05)",
    )
    live.add_argument("--repeats", type=int, default=1, help="Repeats per Case (default 1)")
    live.add_argument("--out", type=Path, required=True, metavar="DIR", help="empty output directory")
    live.add_argument("--json", action="store_true", help="print one JSON object")
    live.set_defaults(handler=_spike_live)
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


def _spike_live(args) -> int:
    import os

    from hypotrail.agentic import cases
    from hypotrail.agentic.declaration import load_workload
    from hypotrail.core import data, live

    model = live.require_model(args.model)
    examples = data.default_examples_dir()
    workload_dir = examples / "chinook"
    workload = load_workload(workload_dir)
    # An undeclared Configuration is refused here, before the key is read and before Inspect is
    # imported.
    workload.system_text(args.config)
    # Neither the declaration nor `hypotrail.agentic.cases` imports Inspect, so they are read
    # here, before the key.
    dev_ids = {case["case_id"] for case in cases.load_cases(workload.cases_path("dev"))}
    case_ids = args.case or ["D03", "D05"]
    live.check_bounds(case_ids, args.repeats, dev_ids)
    # The key is read last among the cheap checks and before Inspect is imported:
    # without it nothing else starts and nothing is sent.
    api_key = live.read_api_key(os.environ)
    data.verify_workloads(examples, ["chinook"])

    from hypotrail.agentic import live as agentic_live

    record = agentic_live.run_live(
        model_id=model,
        api_key=api_key,
        workload_dir=workload_dir,
        configuration=args.config,
        case_ids=case_ids,
        repeats=args.repeats,
        out_dir=args.out,
    )
    lines = [
        f"live run recorded in {args.out} (configuration {args.config}, model {record['model']}, "
        f"tool loop observed: {record['tool_loop_observed']})"
    ] + [
        f"  {e['case_id']} repeat {e['repeat']}: {e['status']}" for e in record["episodes"]
    ]
    _emit({"ok": True, "run": record}, args.json, "\n".join(lines))
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parser.parse_args(arguments)
    except InvalidInputError as error:
        # No namespace exists yet: `--json` is looked for in the arguments.
        return _report(error, "--json" in arguments)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return EXIT_OK
    try:
        return handler(args)
    except HypotrailError as error:
        failure = error
    except OSError as error:
        failure = HypotrailError(
            "INFRASTRUCTURE_FAILURE",
            f"{type(error).__name__}: {error}",
            stage="infrastructure",
            exit_code=EXIT_INFRASTRUCTURE,
        )
    except Exception as error:
        # The text of an unexpected exception can carry anything, a provider key
        # included, so only its type is reported.
        failure = HypotrailError(
            "UNEXPECTED_ERROR",
            f"unexpected {type(error).__name__}",
            stage="infrastructure",
            details={"type": type(error).__name__},
            exit_code=EXIT_INFRASTRUCTURE,
        )
    return _report(failure, getattr(args, "json", False))


def _report(failure: HypotrailError, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": failure.to_dict()}, indent=2))
    print(f"{failure.code} [{failure.stage}]: {failure.message}", file=sys.stderr)
    return failure.exit_code
