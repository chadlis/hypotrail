"""Command line entry point: `python -m hypotrail`.

With `--json`, stdout holds exactly one JSON object and human diagnostics go to
stderr. Every error has `code`, `message`, `stage` and `details`.
"""

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from hypotrail.core.errors import (
    EXIT_OK,
    HypotrailError,
    InvalidInputError,
    coded_error,
)
from hypotrail.core.factors import FACTORS


def _from_run_tool() -> bool:
    return os.environ.get("HYPOTRAIL_RUN_TOOL") == "1"


class _ArgumentParser(argparse.ArgumentParser):
    """An argument error is a Hypotrail error, so `--json` can report it as one."""

    def error(self, message):
        self.print_usage(sys.stderr)
        raise InvalidInputError(
            "INVALID_ARGUMENTS", message, stage="config", details={"command": self.prog}
        )


class _InOrder(argparse.Action):
    """`--words` and `--words-file` append `("text", TEXT)` and `("file", FILE)` to one list, so the texts keep the order they were given in."""

    def __call__(self, parser, namespace, values, option_string=None):
        kind = "file" if option_string == "--words-file" else "text"
        setattr(namespace, self.dest, [*getattr(namespace, self.dest), (kind, values)])


def _read_sequence_value(text: str) -> int:
    """The value of `--read-sequence`: an integer when the text is one, which the rule of the write journal then judges (the library's rule)."""
    from hypotrail.core import write_journal  # imported when a value is given: `--help` loads no more than the standard library

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
    run_agent.add_argument(
        "--episode-cost-limit-usd",
        type=float,
        metavar="USD",
        help="llm_live only, with --price-list: the cost limit of each Episode in USD, enforced by Inspect's per-sample cost_limit "
        "(an Episode stopped by it is failed with the Reason cost_limit)",
    )
    run_agent.add_argument(
        "--price-list",
        type=Path,
        metavar="FILE",
        help='llm_live only, with --episode-cost-limit-usd: the prices of the model, {"source": {"url": ..., "read_on": "YYYY-MM-DD"}, '
        '"models": {MODEL: {"input", "output", "input_cache_write", "input_cache_read"}}} in USD per million tokens',
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
    status.add_argument(
        "--since",
        type=_read_sequence_value,
        metavar="N",
        help="a write sequence, judged as --read-sequence is: the object also holds `writes_since`, the write-journal entries after it; "
        "a value above the Study's is refused (WRITE_SEQUENCE_AHEAD)",
    )
    status.add_argument("--json", action="store_true", help="print one JSON object")
    status.set_defaults(handler=_status)

    figures = commands.add_parser(
        "figures",
        help="show, for each Comparison of a Study, its paired deltas with the bins and the five numbers of a box computed from them (read only)",
    )
    figures.add_argument("--study", required=True, type=Path, metavar="DIR", help="the Study to read")
    figures.add_argument("--json", action="store_true", help="print one JSON object")
    figures.set_defaults(handler=_figures)

    profile = commands.add_parser(
        "profile",
        help="show the data profile of a Bike Study's train Items: the target over time with the Partition band, one distribution per column, "
        "the association matrix of the columns and the target against each allowed feature (read only)",
    )
    profile.add_argument("--study", required=True, type=Path, metavar="DIR", help="the Study to read")
    profile.add_argument(
        "--examples-dir",
        type=Path,
        metavar="DIR",
        help="directory holding the Workloads (default: the source checkout's examples/ when it holds a Workload; any other install gives this flag); "
        "the Workload gives the names, the marks and the band, the Study's own data every value",
    )
    profile.add_argument("--json", action="store_true", help="print one JSON object")
    profile.set_defaults(handler=_profile)

    lesson = commands.add_parser(
        "lesson",
        help="show the cards the Study's Track serves, one per kind of step the Study holds a record of: what the step is and how to read it (read only)",
    )
    lesson.add_argument("--study", type=Path, metavar="DIR", help="the Study to read")
    lesson.add_argument("--json", action="store_true", help="print one JSON object")
    lesson.set_defaults(handler=_lesson)

    lesson_commands = lesson.add_subparsers(dest="lesson_command")
    lesson_check = lesson_commands.add_parser("check", help="check the files of a lesson pack without opening a Study")
    lesson_check.add_argument("pack_dir", type=Path, metavar="PACK_DIR")
    lesson_check.add_argument("--kept", required=True, type=Path, metavar="DIR", help="kept status and figures reads")
    lesson_check.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print one JSON object")
    lesson_check.set_defaults(handler=_lesson_check)

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
    decide.add_argument(
        "--question-id", metavar="ID", help="the id of the pending question answered (`status --json`, `pending_decisions`); given with --option-id"
    )
    decide.add_argument("--option-id", metavar="ID", help="the id of the option chosen among the pending question's options; given with --question-id")
    decide.add_argument(
        "--words-file",
        dest="words",
        action=_InOrder,
        default=[],
        metavar="FILE",
        help="a file that holds one text of the person's own words, whole and as typed (repeatable, kept in the order given); needs --author human",
    )
    decide.add_argument(
        "--words", dest="words", action=_InOrder, default=[], metavar="TEXT", help="one text of the person's own words (repeatable, kept in the order given)"
    )
    decide.add_argument(
        "--channel",
        choices=["panel", "choice", "chat_relayed", "file_relayed"],
        help="how the words reached the caller, as the caller declares it: chat_relayed when words are given without it; "
        "choice records the text of --option-id and takes no text; file_relayed, words the caller read from a file, needs --source",
    )
    decide.add_argument("--by", metavar="LABEL", help="a declared label of who gave the words, recorded as given")
    decide.add_argument("--json", action="store_true", help="print one JSON object")
    decide.set_defaults(handler=_decide)

    deviation = commands.add_parser(
        "deviation",
        help="record one Declared deviation in a Study: one known limit on what results of the Study show, declared in the Study because its records "
        "cannot establish it (for example an owner review of References still pending), with what is declared, its author and the ids of the "
        "Study's records it cites; or the withdrawal of an earlier one",
    )
    deviation.add_argument("--study", required=True, type=Path, metavar="DIR", help="the Study to record the Declared deviation in")
    deviation.add_argument("--text", required=True, metavar="TEXT", help="what is declared (free text, not empty)")
    deviation.add_argument("--author", required=True, choices=["human", "proxy"], help="who declares: a human, or a proxy answering by rule")
    deviation.add_argument("--source", metavar="TEXT", help="a declared source of the Declared deviation, for either author")
    deviation.add_argument(
        "--artifact",
        required=True,
        action="append",
        metavar="ID",
        help="the id of a record of the Study the Declared deviation cites (repeatable, at least one): Attempts and References sets "
        "for a declaration, or the one Declared deviation it withdraws",
    )
    deviation.add_argument(
        "--request-id",
        required=True,
        metavar="ID",
        help="names the request: the same ID with the same Declared deviation returns the recorded one, "
        "with another request it is refused (REQUEST_CONFLICT)",
    )
    _add_read_sequence(deviation, required=True)
    deviation.add_argument("--json", action="store_true", help="print one JSON object")
    deviation.set_defaults(handler=_deviation)

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
        "report",
        help="render one self-contained HTML page for a Study, from its records and, for a Bike Study, its data profile (a page that shows public_check Items is an Exposure)",
    )
    report.add_argument("--study", required=True, type=Path, metavar="DIR", help="the Study to report")
    report.add_argument("--out", required=True, type=Path, metavar="FILE", help="the page to write (an existing file is replaced; not inside the Study)")
    report.add_argument(
        "--examples-dir",
        type=Path,
        metavar="DIR",
        help="directory holding the Workloads (default: the source checkout's examples/ when it holds a Workload; any other install gives this flag); read for a Bike Study's data profile, "
        "and when the page shows public_check Items, to freeze the Workload's digests",
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
        if r["status"] == "verified"
        else f"{r['workload']}: {r['dataset_id']} declared by its data manifest "
        f"(sha256 {r['sha256'][:12]}..., {r['size_bytes']} bytes, as of {r['as_of']}, licence {r['license']}; no data file opened)"
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
            details={"command": "hypotrail init"},
        )
    if args.workload is None:
        raise InvalidInputError(
            "INVALID_ARGUMENTS",
            "init needs --workload NAME to create a Study (or --new-revision to add a revision to an existing one)",
            stage="config",
            details={"command": "hypotrail init"},
        )
    examples = data.resolve_examples_dir(args.examples_dir)
    if declared_track(Path(examples) / args.workload) == "tool_using_agent":
        from hypotrail.agentic import study
    else:
        from hypotrail.ml import study

    spec = study.init_study(args.workload, args.study, examples)
    references = _references_id(spec)
    human = (
        f"Study created in {args.study}: Workload {spec['workload']}, "
        f"protocol {spec['protocol_digest'][:12]}..., study_id {spec['study_id']}, references_id {references}"
    )
    _emit({"ok": True, "study": spec, "references_id": references}, args.json, human)
    return EXIT_OK


def _references_id(spec: dict) -> str:
    """The ID of the References set a StudySpec revision holds: the value `assess --references` takes."""
    return next(entry["artifact_id"] for entry in spec["artifacts"] if entry["ref"]["role"] == "references")


def _observation_set_note(observation_set_id) -> str:
    """What the line of an Attempt writer ends with: the Observation set ID that `assess --observations` takes, or that there is none."""
    return "; no Observation set" if observation_set_id is None else f"; Observation set {observation_set_id}"


def _new_revision(args) -> int:
    from hypotrail.core import revisions
    from hypotrail.core import study as layout

    if args.workload is not None:
        raise InvalidInputError(
            "INVALID_ARGUMENTS",
            "--new-revision takes the Workload the Study names: do not give --workload",
            stage="config",
            details={"command": "hypotrail init", "workload": args.workload},
        )
    domain = layout.read_spec(args.study)["domain"]
    if domain == "agentic":
        from hypotrail.agentic import study
    else:
        from hypotrail.ml import study

    spec = study.new_revision(args.study, args.examples_dir, read_sequence=args.read_sequence)
    references = _references_id(spec)
    human = (
        f"Study {args.study} is at revision {revisions.revision_number(spec)}: Workload {spec['workload']}, "
        f"protocol {spec['protocol_digest'][:12]}..., study_id {spec['study_id']}, references_id {references}"
    )
    _emit({"ok": True, "study": spec, "references_id": references}, args.json, human)
    return EXIT_OK


def _run_ml(args) -> int:
    from hypotrail.core import attempts
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
    observation_set_id = attempts.observation_set_id(args.study, manifest)
    counts = manifest.get("item_counts")
    human = (
        f"Attempt {manifest['attempt_id']} {manifest['technical_status']}"
        + (f" ({counts['produced']} Items produced, {counts['failed']} failed, {counts['missing']} missing)" if counts else "")
        + (" (recorded earlier: nothing was recomputed)" if replayed else "")
        + _observation_set_note(observation_set_id)
    )
    _emit({"ok": True, "replayed": replayed, "attempt": manifest, "observation_set_id": observation_set_id}, args.json, human)
    return EXIT_OK


def _run_agent(args) -> int:
    from hypotrail.agentic import run
    from hypotrail.core import attempts

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
            episode_cost_limit_usd=args.episode_cost_limit_usd,
            price_list=args.price_list,
        )
    except HypotrailError as error:  # a refusal, or an Attempt that failed (then the Study was scanned and `details.warnings` holds what it found)
        _print_warnings(error.details.get("warnings", []))
        raise
    observation_set_id = attempts.observation_set_id(args.study, manifest)
    counts = manifest.get("item_counts")
    human = (
        f"Attempt {manifest['attempt_id']} {manifest['technical_status']} (Mode {manifest['mode']})"
        f" (model {manifest['effective_config']['model']}, served_model {manifest['effective_config']['served_model']})"  # both, as recorded
        + (f" ({counts['produced']} Episodes produced, {counts['failed']} failed, {counts['missing']} missing)" if counts else "")
        + (" (recorded earlier: nothing was run again)" if replayed else "")
        + _observation_set_note(observation_set_id)
    )
    _print_warnings(warnings)
    _emit({"ok": True, "replayed": replayed, "attempt": manifest, "observation_set_id": observation_set_id, "warnings": warnings}, args.json, human)
    return EXIT_OK


def _import_ml(args) -> int:
    from hypotrail.core import attempts
    from hypotrail.ml import imports

    manifest, replayed = imports.import_ml(
        args.study, args.source, args.mapping, args.population, args.request_id, examples_dir=args.examples_dir, read_sequence=args.read_sequence
    )
    observation_set_id = attempts.observation_set_id(args.study, manifest)
    counts = manifest["item_counts"]
    human = (
        f"Import {manifest['attempt_id']} {manifest['technical_status']} "
        f"({counts['produced']} Items produced, Mode {manifest['mode']})"
        + (" (recorded earlier: nothing was read again)" if replayed else "")
        + _observation_set_note(observation_set_id)
    )
    _emit({"ok": True, "replayed": replayed, "attempt": manifest, "observation_set_id": observation_set_id}, args.json, human)
    return EXIT_OK


def _import_agent(args) -> int:
    from hypotrail.agentic import imports
    from hypotrail.core import attempts

    manifest, replayed = imports.import_agent(
        args.study, args.source, args.population, args.request_id, examples_dir=args.examples_dir, read_sequence=args.read_sequence
    )
    observation_set_id = attempts.observation_set_id(args.study, manifest)
    counts = manifest["item_counts"]
    human = (
        f"Import {manifest['attempt_id']} {manifest['technical_status']} "
        f"({counts['produced']} Episodes produced, {counts['failed']} failed, {counts['missing']} missing; Mode {manifest['mode']})"
        + (" (recorded earlier: nothing was read again)" if replayed else "")
        + _observation_set_note(observation_set_id)
    )
    _emit({"ok": True, "replayed": replayed, "attempt": manifest, "observation_set_id": observation_set_id}, args.json, human)
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

    notes = []
    record = assess.assess(
        args.study, args.observations, args.scorer, args.references, examples_dir=args.examples_dir, read_sequence=args.read_sequence, notes=notes, run_tool=_from_run_tool()
    )
    for note in notes:
        print(note, file=sys.stderr)
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
        args.study, args.observations, args.scorer, args.references, examples_dir=args.examples_dir, read_sequence=args.read_sequence, run_tool=_from_run_tool()
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


def _profile_read(examples_dir):
    """What `report` hands the page of a regression Study to draw: the Track's `profile` read, or the code of what stopped it.

    The page never fails because of the profile, so any failure is handed over as its code, a refusal as its own.
    """

    def read(study) -> dict:
        try:
            from hypotrail.ml import profile

            return {"ok": True, **profile.profile(study, examples_dir)}
        except Exception as error:
            return {"ok": False, "code": coded_error(error).code}

    return read


def _compare(args) -> int:
    from hypotrail.core import agent_comparison, comparison

    record = comparison.compare(
        args.study, args.control, args.candidate, args.factor, live_basis=_live_basis(args.examples_dir), read_sequence=args.read_sequence, run_tool=_from_run_tool()
    )
    delta, coverage = record["delta"], record["coverage"]
    value = "no value" if delta["value"] is None else f"{delta['value']:+.6g} {delta['unit']}"
    if delta.get("reason"):
        value += f" ({delta['reason']})"
    interval = record.get("interval") or {}
    if interval.get("lower") is not None:
        units = {"case": "Cases", "item": "Items", "group": "groups"}[interval["unit"]]
        value += f", {interval['level']:g} interval [{interval['lower']:+.6g}, {interval['upper']:+.6g}] over {interval['units']} {units}"
        if interval["block_length"] is not None:
            value += f" in blocks of {interval['block_length']} days"
    direction = "better" if record.get("primary_criterion") else "worse"
    unit = "paired Episodes" if record.get("primary_criterion") else "paired Items"
    status = record["comparability"]["status"]
    deviations = [w["code"] for w in record["warnings"] if w["code"] in comparison.DEVIATIONS + agent_comparison.DEVIATIONS]
    if deviations:
        status += f", with warning {', '.join(deviations)}"
    human = (
        f"Comparison {record['comparison_id']} ({status}): delta {delta['metric']} {value} "
        f"(Candidate minus Control; positive means the Candidate is {direction}) over {coverage['paired']} of {coverage['expected']} {unit}"
    )
    if "settings" in record:
        states = [entry["state"] for entry in record["settings"]["keys"]]
        human += "; settings: " + ", ".join(f"{states.count(state)} {state}" for state in agent_comparison.SETTING_STATES)
    _print_warnings(record["warnings"])
    _emit({"ok": True, "comparison": record}, args.json, human)
    return EXIT_OK


def _report_command(args) -> int:
    from hypotrail.report import command

    result = command.report(
        args.study, args.out, live_basis=_live_basis(args.examples_dir), read_sequence=args.read_sequence, profile=_profile_read(args.examples_dir), run_tool=_from_run_tool()
    )
    recorded = result["exposure"]
    human = f"Report written to {result['out']}" + (f" (an Exposure: journal entry {recorded['entry_id']})" if recorded["recorded"] else " (no public_check Item shown: no Exposure recorded)")
    _emit({"ok": True, "report": result}, args.json, human)
    return EXIT_OK


def _status(args) -> int:
    from hypotrail.core import state

    report = state.status(args.study, since=args.since)
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
    if args.since is not None:
        writes = report["writes_since"]
        lines.append(f"{len(writes)} write-journal {'entry' if len(writes) == 1 else 'entries'} after {args.since}, up to {report['write_sequence']}:")
        for position, entry in enumerate(writes, args.since + 1):
            lines.append(f"  {position} {entry['phase']} {entry['command']}" + (f" ({entry['outcome']})" if "outcome" in entry else ""))
    _emit({"ok": True, **report}, args.json, "\n".join(lines))
    return EXIT_OK


def _figures(args) -> int:
    from hypotrail.core import figures

    report = figures.read(args.study)
    lines = []
    for entry in report["comparisons"]:
        if entry["unavailable"] is None:
            numbers = ", ".join(f"{name} {value:.6g}" for name, value in entry["quartiles"].items())
            lines.append(f"{entry['comparison_id']}: {len(entry['paired_deltas'])} pairs, {numbers}")
        else:
            lines.append(f"{entry['comparison_id']}: no figures ({entry['unavailable']})")
    _emit({"ok": True, **report}, args.json, "\n".join(lines) or "no Comparison in this Study")
    return EXIT_OK


def _profile(args) -> int:
    from hypotrail.ml import profile

    read = profile.profile(args.study, args.examples_dir)
    _emit({"ok": True, **read}, args.json, "\n".join(_profile_lines(read)))
    return EXIT_OK


def _lesson_track(domain: str):
    """The module of the Track that serves the `lesson` read of a Study of `domain`, or None when that Track serves no cards."""
    if domain == "agentic":
        from hypotrail.agentic import lesson
    elif domain == "regression":
        from hypotrail.ml import lesson
    else:
        return None
    return lesson


def _lesson_check(args) -> int:
    from hypotrail.lessons import check

    if args.study is not None or not args.kept.is_dir():
        raise InvalidInputError(
            "INVALID_ARGUMENTS", "lesson check needs a kept-read directory and no Study",
            stage="config", details={"command": "hypotrail lesson check"},
        )
    errors = check(args.pack_dir, args.kept)
    if errors:
        raise InvalidInputError(
            "LESSON_PACK_INVALID", "the lesson pack failed validation",
            stage="config", details={"errors": errors},
        )
    _emit({"ok": True}, args.json, "lesson pack valid")
    return EXIT_OK


def _lesson(args) -> int:
    if args.study is None:
        raise InvalidInputError(
            "INVALID_ARGUMENTS", "the following arguments are required: --study",
            stage="config", details={"command": "hypotrail lesson"},
        )
    from hypotrail.core import study as layout

    domain = layout.read_spec(args.study)["domain"]
    track = _lesson_track(domain)
    if track is None:
        raise InvalidInputError(
            "UNSUPPORTED_CAPABILITY",
            f"`lesson` reads the cards of a Study's Track; the Track of this Study's {domain!r} domain serves none",
            stage="study",
            details={"command": "lesson", "study_domain": domain},
        )
    read = track.lesson(args.study)
    lines = [f"{card['title']}: {card['text']}" for card in read["cards"]]
    _emit({"ok": True, **read}, args.json, "\n".join(lines) or "no card applies to this Study yet")
    return EXIT_OK


def _profile_lines(read: dict) -> list:
    """One short line per part of the profile."""
    def shown(value) -> str:
        return "no value" if value is None else f"{value:.6g}"

    target, columns, associations = read["target"], read["columns"], read["associations"]
    quartiles = target["figures"]["quartiles"] or {}
    flagged = [pair for pair in associations["pairs"] if pair["flagged"]]
    return [
        f"{read['items']} {read['partition']} Items, revision {read['revision_number']}, write sequence {read['write_sequence']}; "
        f"the Workload's Protocol {'is' if read['workload_protocol'] == 'same' else 'is no longer'} this Study's",
        "Partitions: " + ", ".join(f"{p['name']} {p['first']} to {p['last']}" for p in read["band"]),
        f"target {target['column']} ({target['unit']}) over {len(target['series'])} days: "
        + ", ".join(f"{name} {shown(quartiles.get(name))}" for name in ("min", "median", "max")),
        f"{len(columns)} columns, {sum(c['kind'] == 'categorical' for c in columns)} categorical, "
        f"{sum(not c['available'] for c in columns)} not available at prediction time",
        f"{len(associations['pairs'])} pairs, {len(flagged)} at |value| >= {associations['level']}: "
        + (", ".join(f"{p['a']} and {p['b']} {shown(p['value'])}" for p in flagged) or "none"),
        "against the target: " + ", ".join(f"{e['name']} {e['measure']} {shown(e['value'])}" for e in read["against_target"]),
    ]


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
        question_id=args.question_id,
        option_id=args.option_id,
        words=args.words,
        channel=args.channel,
        by=args.by,
    )
    words = record.get("words")  # a replayed `decision/1` record holds no `words`
    human = (
        f"Decision {record['decision_id']} by {record['author']}: {record['option']} "
        f"(cites {len(record['cited_ids'])} ids, write sequence {record['write_sequence']})"
        + ("" if words is None else f" (words: {len(words['texts'])} text{'' if len(words['texts']) == 1 else 's'}, channel {words['channel']})")
        + (" (recorded earlier: nothing was written)" if replayed else "")
    )
    _emit({"ok": True, "replayed": replayed, "decision": record}, args.json, human)
    return EXIT_OK


def _deviation(args) -> int:
    from hypotrail.core import deviations

    deviations.check_arguments(text=args.text, author=args.author, cited_ids=args.artifact, request_id=args.request_id, read_sequence=args.read_sequence)
    record, replayed = deviations.record(
        args.study,
        text=args.text,
        author=args.author,
        source=args.source,
        cited_ids=args.artifact,
        request_id=args.request_id,
        read_sequence=args.read_sequence,
    )
    human = (
        f"Declared deviation {record['declared_deviation_id']} by {record['author']} "
        f"(cites {len(record['cited_ids'])} ids, write sequence {record['write_sequence']})"
        + (" (recorded earlier: nothing was written)" if replayed else "")
    )
    _emit({"ok": True, "replayed": replayed, "declared_deviation": record}, args.json, human)
    return EXIT_OK


def _recover(args) -> int:
    from hypotrail.core import state

    manifest = state.recover(args.study, args.attempt, read_sequence=args.read_sequence)
    human = f"Attempt {manifest['attempt_id']} recorded as interrupted (partial artifacts kept; to make it again, record a new Attempt with a new --request-id and --retry-of)"
    _emit({"ok": True, "attempt": manifest}, args.json, human)
    return EXIT_OK


def _spike_live(args) -> int:
    import os

    from hypotrail.agentic import cases, partitions
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
    dev_ids = {case["case_id"] for case in cases.load_cases(workload.cases_path(partitions.DEV))}
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
    return _report(failure, getattr(args, "json", False))


def _print_warnings(warnings) -> None:
    for warning in warnings:
        print(f"{warning['code']}: {warning['message']}", file=sys.stderr)


def _report(failure: HypotrailError, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": failure.to_dict()}, indent=2))
    print(f"{failure.code} [{failure.stage}]: {failure.message}", file=sys.stderr)
    return failure.exit_code
