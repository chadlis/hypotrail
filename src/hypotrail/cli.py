"""Command line entry point: `python -m hypotrail`.

With `--json`, stdout holds exactly one JSON object and human diagnostics go to
stderr. Every error has `code`, `message`, `stage` and `details`.
"""

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from hypotrail.core import write_journal
from hypotrail.core.errors import (
    EXIT_INFRASTRUCTURE,
    EXIT_OK,
    HypotrailError,
    InvalidInputError,
    coded_error,
)
from hypotrail.core.factors import FACTORS


class _ArgumentParser(argparse.ArgumentParser):
    """An argument error is a Hypotrail error, so `--json` can report it as one."""

    def error(self, message):
        self.print_usage(sys.stderr)
        raise InvalidInputError(
            "INVALID_ARGUMENTS", message, stage="config", details={"command": self.prog}
        )


def _read_sequence_value(text: str):
    """The value of `--read-sequence`: an integer when the text is one, which the rule of the write journal then judges (the library's rule)."""
    value = int(text) if re.fullmatch(r"-?[0-9]+", text) else text
    fault = write_journal.read_sequence_fault(value)
    if fault is not None:
        raise argparse.ArgumentTypeError(fault)
    return value


def _add_read_sequence(parser, *, required: bool = False) -> None:
    parser.add_argument(
        "--read-sequence",
        type=_read_sequence_value,
        required=required,
        metavar="N",
        help="the write sequence the author read (`status --json`, `write_sequence`): when the Study was written to since, "
        "the command is refused (STUDY_CHANGED) and writes nothing; "
        + ("required" if required else "not given, the command is not checked"),
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
        help="directory holding the Workloads (default: the source checkout's examples/ when it holds a Workload; any other install gives this flag)",
    )
    verify.add_argument("--json", action="store_true", help="print one JSON object")
    verify.set_defaults(handler=_data_verify)

    fetch = data_commands.add_parser(
        "fetch", help="acquire a Workload's public sources from the URLs of its lock, checked against the lock"
    )
    fetch.add_argument("--lock", required=True, type=Path, metavar="LOCK", help="the data-sources.lock.json to acquire")
    fetch.add_argument(
        "--dest",
        required=True,
        type=Path,
        metavar="DIR",
        help="the Workload directory the files are published in: each source lands at its lock's local_path under it (for example examples/bike_day)",
    )
    fetch.add_argument("--json", action="store_true", help="print one JSON object")
    fetch.set_defaults(handler=_data_fetch)

    init = commands.add_parser("init", help="create a Study for a Workload, or add a revision to a Study (--new-revision)")
    init.add_argument("--workload", metavar="NAME", help="the Workload to study (for example bike_day); required unless --new-revision")
    init.add_argument("--study", required=True, type=Path, metavar="DIR", help="the Study folder to create, or to add a revision to")
    init.add_argument(
        "--new-revision",
        action="store_true",
        help="add a StudySpec revision to the existing Study: the Protocol its Workload declares now "
        "(a corrected References set, for example); the Workload is the one the Study names, so --workload is not given",
    )
    init.add_argument(
        "--examples-dir",
        type=Path,
        metavar="DIR",
        help="directory holding the Workloads (default: the source checkout's examples/ when it holds a Workload; any other install gives this flag)",
    )
    _add_read_sequence(init)
    init.add_argument("--json", action="store_true", help="print one JSON object")
    init.set_defaults(handler=_init)

    run = commands.add_parser("run", help="run one Configuration as one Attempt of a Study")
    run_commands = run.add_subparsers(dest="run_command", metavar="TRACK")
    run_ml = run_commands.add_parser(
        "ml", help="run a Configuration of the temporal regression Track (for example seasonal_7, ridge_v1)"
    )
    run_ml.add_argument("--study", required=True, type=Path, metavar="DIR", help="the Study to record the Attempt in")
    run_ml.add_argument("--config", required=True, metavar="NAME", help="the declared Configuration to run")
    run_ml.add_argument("--partition", required=True, metavar="NAME", help="the Partition to predict (for example dev)")
    run_ml.add_argument(
        "--request-id",
        required=True,
        metavar="ID",
        help="names the request: the same ID with the same request returns the recorded Attempt, "
        "with another request it is refused (REQUEST_CONFLICT)",
    )
    run_ml.add_argument("--retry-of", metavar="ATTEMPT_ID", help="the earlier Attempt this new Attempt is made after, on purpose")
    run_ml.add_argument(
        "--examples-dir",
        type=Path,
        metavar="DIR",
        help="directory holding the Workloads (default: the source checkout's examples/ when it holds a Workload; any other install gives this flag)",
    )
    _add_read_sequence(run_ml)
    run_ml.add_argument("--json", action="store_true", help="print one JSON object")
    run_ml.set_defaults(handler=_run_ml)

    run_agent = run_commands.add_parser(
        "agent",
        help="run a Configuration of the tool-using agent Track: the scenarios (scripted_fixture) or a Partition against a model (llm_live, opt-in, paid)",
    )
    run_agent.add_argument("--study", required=True, type=Path, metavar="DIR", help="the Study to record the Attempt in")
    run_agent.add_argument(
        "--mode",
        required=True,
        choices=["scripted_fixture", "llm_live"],
        help="scripted_fixture runs the Workload's scenarios with Inspect's mock model; llm_live runs one Partition against an explicit Anthropic model "
        "(needs --partition, --repeats and --model, and HYPOTRAIL_ANTHROPIC_API_KEY)",
    )
    run_agent.add_argument("--config", required=True, metavar="NAME", help="the declared Configuration to run (one the Workload declares)")
    run_agent.add_argument(
        "--request-id",
        required=True,
        metavar="ID",
        help="names the request: the same ID with the same request returns the recorded Attempt, "
        "with another request it is refused (REQUEST_CONFLICT)",
    )
    run_agent.add_argument("--partition", metavar="NAME", help="llm_live only: the Partition to run, dev or public_check")
    run_agent.add_argument("--repeats", type=int, metavar="N", help="llm_live only: Repeats per Case, an integer from 1 to 3")
    run_agent.add_argument("--model", metavar="MODEL", help="llm_live only: the explicit model identifier, as anthropic/<model>; no default")
    run_agent.add_argument(
        "--cases",
        action="append",
        metavar="CASE_ID",
        help="llm_live only: a Case of the Partition (repeatable; default: every Case of the Partition)",
    )
    run_agent.add_argument("--retry-of", metavar="ATTEMPT_ID", help="the earlier Attempt this new Attempt is made after, on purpose")
    run_agent.add_argument(
        "--examples-dir",
        type=Path,
        metavar="DIR",
        help="directory holding the Workloads (default: the source checkout's examples/ when it holds a Workload; any other install gives this flag)",
    )
    _add_read_sequence(run_agent)
    run_agent.add_argument("--json", action="store_true", help="print one JSON object")
    run_agent.set_defaults(handler=_run_agent)

    import_ = commands.add_parser("import", help="adopt outputs produced elsewhere as an Import Attempt of a Study")
    import_commands = import_.add_subparsers(dest="import_command", metavar="TRACK")
    import_ml = import_commands.add_parser(
        "ml", help="import a complete predictions CSV of the temporal regression Track (from a program that never imports hypotrail)"
    )
    import_ml.add_argument("--study", required=True, type=Path, metavar="DIR", help="the Study to record the Import in")
    import_ml.add_argument("--source", required=True, type=Path, metavar="CSV", help="the predictions file (UTF-8 CSV), kept as it is")
    import_ml.add_argument("--mapping", required=True, type=Path, metavar="MAPPING", help="JSON: which columns are row_id and y_pred, and the dataset digest")
    import_ml.add_argument("--population", required=True, type=Path, metavar="FILE", help='JSON {"item_ids": [...]}: the Items the file must hold, all of one Partition')
    import_ml.add_argument(
        "--request-id",
        required=True,
        metavar="ID",
        help="names the request: the same ID with the same request returns the recorded Import, "
        "with another request it is refused (REQUEST_CONFLICT)",
    )
    import_ml.add_argument(
        "--examples-dir",
        type=Path,
        metavar="DIR",
        help="directory holding the Workloads (default: the source checkout's examples/ when it holds a Workload; any other install gives this flag)",
    )
    _add_read_sequence(import_ml)
    import_ml.add_argument("--json", action="store_true", help="print one JSON object")
    import_ml.set_defaults(handler=_import_ml)

    import_agent = import_commands.add_parser(
        "agent", help="import agent answers produced elsewhere, as JSON Lines, into a Study of the tool-using agent Track"
    )
    import_agent.add_argument("--study", required=True, type=Path, metavar="DIR", help="the Study to record the Import in")
    import_agent.add_argument("--source", required=True, type=Path, metavar="SOURCE",
        help="the answers file (JSON Lines, UTF-8) or an Inspect log (.eval, needs Inspect), kept as it is",
    )
    import_agent.add_argument(
        "--population",
        required=True,
        type=Path,
        metavar="FILE",
        help='JSON {"episodes": [{"case_id", "repeat"}, ...]}: the Episodes the file must hold, all Cases of one Partition',
    )
    import_agent.add_argument(
        "--request-id",
        required=True,
        metavar="ID",
        help="names the request: the same ID with the same request returns the recorded Import, "
        "with another request it is refused (REQUEST_CONFLICT)",
    )
    import_agent.add_argument(
        "--examples-dir",
        type=Path,
        metavar="DIR",
        help="directory holding the Workloads (default: the source checkout's examples/ when it holds a Workload; any other install gives this flag)",
    )
    _add_read_sequence(import_agent)
    import_agent.add_argument("--json", action="store_true", help="print one JSON object")
    import_agent.set_defaults(handler=_import_agent)

    assess = commands.add_parser("assess", help="apply one registered Scorer to one kept Observation set")
    assess.add_argument("--study", required=True, type=Path, metavar="DIR", help="the Study that keeps the Observation set")
    assess.add_argument("--observations", required=True, metavar="OBSERVATION_SET_ID", help="the Observation set to score")
    assess.add_argument(
        "--scorer", required=True, metavar="SCORER_ID", help="a registered Scorer (regression_mae_v1, regression_rmse_v1, chinook_contract_v1)"
    )
    assess.add_argument("--references", required=True, metavar="REFERENCES_ID", help="the References set of the Study to score against")
    assess.add_argument(
        "--examples-dir",
        type=Path,
        metavar="DIR",
        help="directory holding the Workloads (default: the source checkout's examples/ when it holds a Workload; any other install gives this flag); read only for an Assessment of public_check Items, to freeze the Workload's digests",
    )
    _add_read_sequence(assess)
    assess.add_argument("--json", action="store_true", help="print one JSON object")
    assess.set_defaults(handler=_assess)

    compare = commands.add_parser("compare", help="compare two Assessments of a Study as Control and Candidate")
    compare.add_argument("--study", required=True, type=Path, metavar="DIR", help="the Study that keeps the Assessments")
    compare.add_argument("--control", required=True, metavar="ASSESSMENT_ID", help="the Assessment measured against (the Control)")
    compare.add_argument("--candidate", required=True, metavar="ASSESSMENT_ID", help="the Assessment measured (the Candidate)")
    compare.add_argument(
        "--factor",
        choices=FACTORS,
        default=None,
        help="the factor that is intentionally different between the two sides of an agent Comparison (default: configuration)",
    )
    compare.add_argument(
        "--examples-dir",
        type=Path,
        metavar="DIR",
        help="directory holding the Workloads (default: the source checkout's examples/ when it holds a Workload; any other install gives this flag); read only for a Comparison of public_check Items, to freeze the Workload's digests",
    )
    _add_read_sequence(compare)
    compare.add_argument("--json", action="store_true", help="print one JSON object")
    compare.set_defaults(handler=_compare)

    status = commands.add_parser("status", help="show the local state of a Study: its Attempts and their artifacts (read only)")
    status.add_argument("--study", required=True, type=Path, metavar="DIR", help="the Study to inspect")
    status.add_argument("--json", action="store_true", help="print one JSON object")
    status.set_defaults(handler=_status)

    decide = commands.add_parser(
        "decide", help="record one decision in a Study: the question it answers, the option chosen, its author and the ids it cites"
    )
    decide.add_argument("--study", required=True, type=Path, metavar="DIR", help="the Study to record the decision in")
    decide.add_argument("--question", required=True, metavar="TEXT", help="the question the decision answers (free text, not empty)")
    decide.add_argument("--option", required=True, metavar="TEXT", help="the option chosen (free text, not empty)")
    decide.add_argument("--author", required=True, choices=["human", "proxy"], help="who decides: a human, or a proxy answering by rule")
    decide.add_argument("--source", metavar="TEXT", help="a declared source of the decision, for either author")
    decide.add_argument(
        "--artifact",
        required=True,
        action="append",
        metavar="ID",
        help="the id of a record of the Study the decision concerns (repeatable, at least one): an Attempt, Observation set, Assessment, "
        "Comparison, Study artifact, revision, freeze record, Exposure entry or decision",
    )
    decide.add_argument(
        "--request-id",
        required=True,
        metavar="ID",
        help="names the request: the same ID with the same decision returns the recorded decision, "
        "with another decision it is refused (REQUEST_CONFLICT)",
    )
    _add_read_sequence(decide, required=True)
    decide.add_argument("--json", action="store_true", help="print one JSON object")
    decide.set_defaults(handler=_decide)

    recover = commands.add_parser(
        "recover",
        help="record an Attempt left running by a writer that is gone as interrupted (nothing is resubmitted)",
    )
    recover.add_argument("--study", required=True, type=Path, metavar="DIR", help="the Study holding the Attempt")
    recover.add_argument("--attempt", required=True, metavar="ATTEMPT_ID", help="the running Attempt to record as interrupted")
    _add_read_sequence(recover)
    recover.add_argument("--json", action="store_true", help="print one JSON object")
    recover.set_defaults(handler=_recover)

    report = commands.add_parser(
        "report", help="render one self-contained HTML page for a Study, from its records alone (a page that shows public_check Items is an Exposure)"
    )
    report.add_argument("--study", required=True, type=Path, metavar="DIR", help="the Study to report")
    report.add_argument("--out", required=True, type=Path, metavar="FILE", help="the page to write (an existing file is replaced; not inside the Study)")
    report.add_argument(
        "--examples-dir",
        type=Path,
        metavar="DIR",
        help="directory holding the Workloads (default: the source checkout's examples/ when it holds a Workload; any other install gives this flag); read only when the page shows public_check Items, to freeze the Workload's digests",
    )
    _add_read_sequence(report)
    report.add_argument("--json", action="store_true", help="print one JSON object")
    report.set_defaults(handler=_report_command)

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
    live.add_argument(
        "--examples-dir",
        type=Path,
        metavar="DIR",
        help="directory holding the Workloads (default: the source checkout's examples/ when it holds a Workload; any other install gives this flag)",
    )
    live.add_argument("--out", type=Path, required=True, metavar="DIR", help="empty output directory")
    live.add_argument("--json", action="store_true", help="print one JSON object")
    live.set_defaults(handler=_spike_live)
    return parser


def _emit(payload: dict, as_json: bool, human: str) -> None:
    print(json.dumps(payload, indent=2) if as_json else human)


def _data_verify(args) -> int:
    from hypotrail.core import data

    examples = data.resolve_examples_dir(args.examples_dir)
    reports = data.verify_workloads(examples, args.workload)
    lines = [
        f"{r['workload']}: {r['dataset_id']} verified "
        f"({r['file']}, sha256 {r['sha256'][:12]}..., licence {r['license']})"
        for r in reports
    ]
    _emit({"ok": True, "datasets": reports}, args.json, "\n".join(lines))
    return EXIT_OK


def _data_fetch(args) -> int:
    from hypotrail.core import fetch

    reports = fetch.fetch(args.lock, args.dest)
    lines = []
    for r in reports:
        lines.append(f"{r['dataset_id']}: {r['file']} {r['status']} (sha256 {r['sha256'][:12]}..., checked against the lock)")
        lines.append(f"  notice {r['notice']['file'] or '(none)'}: {r['notice']['status']}")
    _emit({"ok": True, "sources": reports}, args.json, "\n".join(lines))
    return EXIT_OK


def _init(args) -> int:
    from hypotrail.core import data
    from hypotrail.core.study import declared_track

    if args.new_revision:
        return _new_revision(args)
    if args.read_sequence is not None:
        raise InvalidInputError(
            "INVALID_ARGUMENTS",
            "--read-sequence is for --new-revision: a Study that is created has no write sequence to read",
            stage="config",
            details={"command": "init"},
        )
    if args.workload is None:
        raise InvalidInputError(
            "INVALID_ARGUMENTS",
            "init needs --workload NAME to create a Study (or --new-revision to add a revision to an existing one)",
            stage="config",
            details={"command": "init"},
        )
    examples = data.resolve_examples_dir(args.examples_dir)
    if declared_track(Path(examples) / args.workload) == "tool_using_agent":
        from hypotrail.agentic import study
    else:
        from hypotrail.ml import study

    spec = study.init_study(args.workload, args.study, examples)
    human = (
        f"Study created in {args.study}: Workload {spec['workload']}, "
        f"protocol {spec['protocol_digest'][:12]}..., study_id {spec['study_id']}"
    )
    _emit({"ok": True, "study": spec}, args.json, human)
    return EXIT_OK


def _new_revision(args) -> int:
    from hypotrail.core import revisions
    from hypotrail.core import study as layout

    if args.workload is not None:
        raise InvalidInputError(
            "INVALID_ARGUMENTS",
            "--new-revision takes the Workload the Study names: do not give --workload",
            stage="config",
            details={"command": "init", "workload": args.workload},
        )
    domain = layout.read_spec(args.study)["domain"]
    if domain == "agentic":
        from hypotrail.agentic import study
    else:
        from hypotrail.ml import study

    spec = study.new_revision(args.study, args.examples_dir, read_sequence=args.read_sequence)
    human = (
        f"Study {args.study} is at revision {revisions.revision_number(spec)}: Workload {spec['workload']}, "
        f"protocol {spec['protocol_digest'][:12]}..., study_id {spec['study_id']}"
    )
    _emit({"ok": True, "study": spec}, args.json, human)
    return EXIT_OK


def _run_ml(args) -> int:
    from hypotrail.ml import run

    manifest, replayed = run.run_ml(
        args.study,
        args.config,
        args.partition,
        args.request_id,
        retry_of=args.retry_of,
        examples_dir=args.examples_dir,
        read_sequence=args.read_sequence,
    )
    counts = manifest.get("item_counts")
    human = (
        f"Attempt {manifest['attempt_id']} {manifest['technical_status']}"
        + (f" ({counts['produced']} Items produced, {counts['failed']} failed, {counts['missing']} missing)" if counts else "")
        + (" (recorded earlier: nothing was recomputed)" if replayed else "")
    )
    _emit({"ok": True, "replayed": replayed, "attempt": manifest}, args.json, human)
    return EXIT_OK


def _run_agent(args) -> int:
    from hypotrail.agentic import run

    try:
        manifest, replayed, warnings = run.run_agent(
            args.study,
            mode=args.mode,
            config=args.config,
            request_id=args.request_id,
            partition=args.partition,
            repeats=args.repeats,
            model=args.model,
            cases=args.cases,
            retry_of=args.retry_of,
            examples_dir=args.examples_dir,
            read_sequence=args.read_sequence,
        )
    except HypotrailError as error:  # a refusal, or an Attempt that failed (then the Study was scanned and `details.warnings` holds what it found)
        _print_warnings(error.details.get("warnings", []))
        raise
    counts = manifest.get("item_counts")
    human = (
        f"Attempt {manifest['attempt_id']} {manifest['technical_status']} (Mode {manifest['mode']})"
        f" (model {manifest['effective_config']['model']}, served_model {manifest['effective_config']['served_model']})"  # both, as recorded
        + (f" ({counts['produced']} Episodes produced, {counts['failed']} failed, {counts['missing']} missing)" if counts else "")
        + (" (recorded earlier: nothing was run again)" if replayed else "")
    )
    _print_warnings(warnings)
    _emit({"ok": True, "replayed": replayed, "attempt": manifest, "warnings": warnings}, args.json, human)
    return EXIT_OK


def _import_ml(args) -> int:
    from hypotrail.ml import imports

    manifest, replayed = imports.import_ml(
        args.study, args.source, args.mapping, args.population, args.request_id, examples_dir=args.examples_dir, read_sequence=args.read_sequence
    )
    counts = manifest["item_counts"]
    human = (
        f"Import {manifest['attempt_id']} {manifest['technical_status']} "
        f"({counts['produced']} Items produced, Mode {manifest['mode']})"
        + (" (recorded earlier: nothing was read again)" if replayed else "")
    )
    _emit({"ok": True, "replayed": replayed, "attempt": manifest}, args.json, human)
    return EXIT_OK


def _import_agent(args) -> int:
    from hypotrail.agentic import imports

    manifest, replayed = imports.import_agent(
        args.study, args.source, args.population, args.request_id, examples_dir=args.examples_dir, read_sequence=args.read_sequence
    )
    counts = manifest["item_counts"]
    human = (
        f"Import {manifest['attempt_id']} {manifest['technical_status']} "
        f"({counts['produced']} Episodes produced, {counts['failed']} failed, {counts['missing']} missing; Mode {manifest['mode']})"
        + (" (recorded earlier: nothing was read again)" if replayed else "")
    )
    _emit({"ok": True, "replayed": replayed, "attempt": manifest}, args.json, human)
    return EXIT_OK


def _rescoring_note(record: dict) -> str:
    """What the human line adds when the Assessment follows an earlier one that differs from it."""
    rescoring = record.get("rescoring")
    if rescoring is None:
        return ""
    return (
        f"; rescoring of Assessment {rescoring['earlier_assessment_id']}: cause {rescoring['cause']}, "
        f"{len(rescoring['changed_items'])} Criteria changed"
    )


def _assess(args) -> int:
    from hypotrail.core import scorers

    scorer = scorers.REGISTRY.get(args.scorer) if isinstance(args.scorer, str) else None
    if scorer is not None and scorer.domain == scorers.AGENTIC:
        return _assess_agent(args)
    from hypotrail.ml import assess

    record = assess.assess(
        args.study, args.observations, args.scorer, args.references, examples_dir=args.examples_dir, read_sequence=args.read_sequence
    )
    counts, metric = record["counts"], record["metrics"][0]
    value = "no value" if metric["value"] is None else f"{metric['value']:.6g} {metric['unit']}"
    human = (
        f"Assessment {record['assessment_id']}: {metric['id']} {value} over {counts['scored']} of "
        f"{counts['expected']} expected Items ({counts['unscored']} unscored, {counts['errored']} errored)" + _rescoring_note(record)
    )
    _emit({"ok": True, "assessment": record}, args.json, human)
    return EXIT_OK


def _assess_agent(args) -> int:
    from hypotrail.agentic import assess

    record = assess.assess(
        args.study, args.observations, args.scorer, args.references, examples_dir=args.examples_dir, read_sequence=args.read_sequence
    )
    counts = record["counts"]
    quality, share = record["metrics"]

    def shown(rate):
        return "no value" if rate["value"] is None else f"{rate['value']:.3g}"

    human = (
        f"Assessment {record['assessment_id']}: primary Criterion {record['primary_criterion']}: {counts['correct']} correct of {counts['expected']} expected Episodes "
        f"({counts['scored']} scored, {counts['unscored']} unscored, {counts['errored']} errored); {quality['id']} {shown(quality)}, {share['id']} {shown(share)}" + _rescoring_note(record)
    )
    _emit({"ok": True, "assessment": record}, args.json, human)
    return EXIT_OK


def _live_basis(examples_dir):
    """What `compare` and `report` hand the core to freeze a Workload on an Exposure: the Study's Track reads it, the core imports no Track.

    It reads nothing itself: the core calls it with the spec it read under the writer lock.
    """

    def basis(spec: dict) -> dict:
        if spec["domain"] == "agentic":
            from hypotrail.agentic import study as track
        else:
            from hypotrail.ml import study as track
        return track.live_basis(examples_dir)(spec)

    return basis


def _compare(args) -> int:
    from hypotrail.core import comparison

    record = comparison.compare(
        args.study, args.control, args.candidate, args.factor, live_basis=_live_basis(args.examples_dir), read_sequence=args.read_sequence
    )
    delta, coverage = record["delta"], record["coverage"]
    value = "no value" if delta["value"] is None else f"{delta['value']:+.6g} {delta['unit']}"
    if delta.get("reason"):
        value += f" ({delta['reason']})"
    direction = "better" if record.get("primary_criterion") else "worse"
    unit = "paired Episodes" if record.get("primary_criterion") else "paired Items"
    human = (
        f"Comparison {record['comparison_id']} ({record['comparability']['status']}): delta {delta['metric']} {value} "
        f"(Candidate minus Control; positive means the Candidate is {direction}) over {coverage['paired']} of {coverage['expected']} {unit}"
    )
    _print_warnings(record["warnings"])
    _emit({"ok": True, "comparison": record}, args.json, human)
    return EXIT_OK


def _report_command(args) -> int:
    from hypotrail.report import command

    result = command.report(args.study, args.out, live_basis=_live_basis(args.examples_dir), read_sequence=args.read_sequence)
    recorded = result["exposure"]
    human = f"Report written to {result['out']}" + (f" (an Exposure: journal entry {recorded['entry_id']})" if recorded["recorded"] else " (no public_check Item shown: no Exposure recorded)")
    _emit({"ok": True, "report": result}, args.json, human)
    return EXIT_OK


def _status(args) -> int:
    from hypotrail.core import state

    report = state.status(args.study)
    lines = [f"Study {report['study']['study_id']} ({report['study']['workload']}); a writer is {'active' if report['writer_alive'] else 'not active'}"]
    exposures = report["exposures"]
    lines.append(
        f"  {exposures['recorded_in_this_study']} Exposures recorded in this Study; any earlier exposure to public_check is {exposures['earlier_exposure']}"
        + (f"; marked check_informed: {len(report['check_informed'])}" if report["check_informed"] else "")
    )
    if report["decisions"]:
        outdated = sum(1 for decision in report["decisions"] if not decision["applies"])
        lines.append(f"Decisions: {len(report['decisions'])} recorded, {outdated} no longer {'applies' if outdated == 1 else 'apply'}")
    for attempt in report["attempts"]:
        lines.append(
            f"  {attempt['attempt_id']} {attempt['technical_status']} request {attempt['request_id']}, "
            f"{len(attempt['artifacts'])} artifacts"
            + (" (no live writer: `recover` can record it as interrupted)" if attempt["recoverable"] else "")
        )
    _emit({"ok": True, **report}, args.json, "\n".join(lines))
    return EXIT_OK


def _decide(args) -> int:
    from hypotrail.core import decisions

    record, replayed = decisions.decide(
        args.study,
        question=args.question,
        option=args.option,
        author=args.author,
        source=args.source,
        cited_ids=args.artifact,
        request_id=args.request_id,
        read_sequence=args.read_sequence,
    )
    human = (
        f"Decision {record['decision_id']} by {record['author']}: {record['option']} "
        f"(cites {len(record['cited_ids'])} ids, write sequence {record['write_sequence']})"
        + (" (recorded earlier: nothing was written)" if replayed else "")
    )
    _emit({"ok": True, "replayed": replayed, "decision": record}, args.json, human)
    return EXIT_OK


def _recover(args) -> int:
    from hypotrail.core import state

    manifest = state.recover(args.study, args.attempt, read_sequence=args.read_sequence)
    human = f"Attempt {manifest['attempt_id']} recorded as interrupted (partial artifacts kept; to make it again, record a new Attempt with a new --request-id and --retry-of)"
    _emit({"ok": True, "attempt": manifest}, args.json, human)
    return EXIT_OK


def _spike_live(args) -> int:
    import os

    from hypotrail.agentic import cases
    from hypotrail.agentic.declaration import load_workload
    from hypotrail.core import data, live

    model = live.require_model(args.model)
    examples = data.resolve_examples_dir(args.examples_dir)
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
        f"live execution recorded in {args.out} (configuration {args.config}, model {record['model']}, "
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
    except Exception as error:
        failure = coded_error(error)
        if isinstance(error, OSError) and not isinstance(error, HypotrailError) and handler is not _run_agent:
            # every other command keeps its earlier report (#81): only `run agent` reports an OS error by its type alone
            failure = HypotrailError("INFRASTRUCTURE_FAILURE", f"{type(error).__name__}: {error}", stage="infrastructure", exit_code=EXIT_INFRASTRUCTURE)
    return _report(failure, getattr(args, "json", False))


def _print_warnings(warnings) -> None:
    for warning in warnings:
        print(f"{warning['code']}: {warning['message']}", file=sys.stderr)


def _report(failure: HypotrailError, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": failure.to_dict()}, indent=2))
    print(f"{failure.code} [{failure.stage}]: {failure.message}", file=sys.stderr)
    return failure.exit_code
