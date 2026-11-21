"""Ticket #108 (slice #104, L2.1): `--read-sequence` and the refusal of a write made on an older write sequence.

D-033 on chadlis/hypotrail#75, D-034 on chadlis/hypotrail#75, D-036 on chadlis/hypotrail#75 and D-037 on chadlis/hypotrail#75 settle what is tested here: every writing command takes the write sequence its
author read; older than the Study's is `STUDY_CHANGED` (exit 6, stage `sequence`), above it `WRITE_SEQUENCE_AHEAD` (exit 2, stage
`sequence`), negative or not an integer `INVALID_ARGUMENTS`; the check is made under the writer lock, after the request identity.
No model is called.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from _assess_helpers import fresh_study, observation_set_id, references_id
from _chinook_helpers import chinook_examples, database_of, fixture_lines, fixture_population, init_chinook, write_lines
from _compare_helpers import assessed
from _import_helpers import ready
from _order_probe import CHECKS_BEFORE_THE_LOCK as CHECK_CALLS
from _order_table import CHECKS_BEFORE_THE_LOCK
from _report_helpers import report
from _report_tracks import TRACKS, Bike
from _revision_helpers import corrected_chinook_references
from _run_agent_helpers import fixture
from _study_helpers import examples_copy, init_study, run_cli, run_json, run_ml
from test_run_ml import killed
from test_study_lock import held_by_another_process
from test_write_sequence import entries, seq, tree

from hypotrail.core.errors import HypotrailError


# --- the commands that write: each is a scenario ----------------------------------------------------------------------


class Scenario:
    """A Study a writing command works on.

    `argv(study, *more)` is the command line (without `--json`), `library(study, read_sequence)` the same command as a library call and
    `bump(study)` a write made by another command.
    """

    def __init__(self, study, argv, library, bump):
        self.study, self.argv, self.library, self.bump = study, argv, library, bump

    def call(self, study, *more):
        return run_json(*self.argv(study, *more))

    def copy_to(self, folder) -> Path:
        """An identical copy of the Study, in `folder`."""
        target = Path(folder) / "study"
        shutil.copytree(self.study, target)
        return target


def bike_bump(study):
    code, payload, err = run_ml(study, "seasonal_7", "dev", "bump")
    assert code == 0, (payload, err)


def chinook_bump(study):
    code, payload, err = fixture(study, "plain", "bump")
    assert code == 0, (payload, err)


def new_revision_scenario(tmp_path):
    study, _ = init_chinook(tmp_path)
    corrected = corrected_chinook_references(tmp_path, lambda r: r["D03"].update(rows=[[r["D03"]["rows"][0][0] + 1]]))

    def library(path, read_sequence):
        from hypotrail.agentic import study as track

        return track.new_revision(path, corrected, read_sequence=read_sequence)

    argv = lambda path, *more: ["init", "--study", path, "--new-revision", "--examples-dir", corrected, *more]  # noqa: E731
    return Scenario(study, argv, library, chinook_bump)


def run_ml_scenario(tmp_path):
    study, _ = init_study(tmp_path)

    def library(path, read_sequence, request_id="w-run"):
        from hypotrail.ml import run

        return run.run_ml(path, "seasonal_7", "dev", request_id, read_sequence=read_sequence)

    argv = lambda path, *more: ["run", "ml", "--study", path, "--config", "seasonal_7", "--partition", "dev", "--request-id", "w-run", *more]  # noqa: E731
    return Scenario(study, argv, library, bike_bump)


def run_agent_scenario(tmp_path):
    study, _ = init_chinook(tmp_path)

    def library(path, read_sequence, request_id="w-agent"):
        from hypotrail.agentic import run

        return run.run_agent(path, mode="scripted_fixture", config="plain", request_id=request_id, read_sequence=read_sequence)

    argv = lambda path, *more: ["run", "agent", "--study", path, "--mode", "scripted_fixture", "--config", "plain", "--request-id", "w-agent", *more]  # noqa: E731
    return Scenario(study, argv, library, chinook_bump)


def import_ml_scenario(tmp_path):
    study, _ = init_study(tmp_path)
    source, mapping, population, _ = ready(tmp_path)

    def library(path, read_sequence, request_id="w-import"):
        from hypotrail.ml import imports

        return imports.import_ml(path, source, mapping, population, request_id, read_sequence=read_sequence)

    argv = lambda path, *more: [  # noqa: E731
        "import", "ml", "--study", path, "--source", source, "--mapping", mapping, "--population", population, "--request-id", "w-import", *more
    ]
    return Scenario(study, argv, library, bike_bump)


def import_agent_scenario(tmp_path):
    study, _ = init_chinook(tmp_path)
    source = write_lines(tmp_path / "answers.jsonl", fixture_lines())
    population = fixture_population(tmp_path)

    def library(path, read_sequence, request_id="w-import-agent"):
        from hypotrail.agentic import imports

        return imports.import_agent(path, source, population, request_id, read_sequence=read_sequence)

    argv = lambda path, *more: ["import", "agent", "--study", path, "--source", source, "--population", population, "--request-id", "w-import-agent", *more]  # noqa: E731
    return Scenario(study, argv, library, chinook_bump)


def assess_scenario(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    observations, references = observation_set_id(study, attempts["seasonal_7"]), references_id(study)

    def library(path, read_sequence):
        from hypotrail.ml import assess as track

        return track.assess(path, observations, "regression_mae_v1", references, read_sequence=read_sequence)

    argv = lambda path, *more: [  # noqa: E731
        "assess", "--study", path, "--observations", observations, "--scorer", "regression_mae_v1", "--references", references, *more
    ]
    return Scenario(study, argv, library, bike_bump)


def compare_scenario(tmp_path):
    study, _, ids = assessed(tmp_path, "seasonal_7", "ridge_v1")
    control, candidate = ids["seasonal_7"]["assessment_id"], ids["ridge_v1"]["assessment_id"]

    def library(path, read_sequence):
        from hypotrail.core import comparison

        return comparison.compare(path, control, candidate, read_sequence=read_sequence)

    argv = lambda path, *more: ["compare", "--study", path, "--control", control, "--candidate", candidate, *more]  # noqa: E731
    return Scenario(study, argv, library, bike_bump)


def recover_scenario(tmp_path):
    study, folder = killed(tmp_path, kill_at=4)

    def library(path, read_sequence):
        from hypotrail.core import state

        return state.recover(path, folder.name, read_sequence=read_sequence)

    argv = lambda path, *more: ["recover", "--study", path, "--attempt", folder.name, *more]  # noqa: E731
    return Scenario(study, argv, library, bike_bump)


def report_scenario(tmp_path):
    study, _ = TRACKS["bike"].public_outputs(tmp_path)  # a page that shows public_check Items is an Exposure

    def library(path, read_sequence):
        from hypotrail import cli
        from hypotrail.report import command

        return command.report(path, Path(path).parent / "page.html", live_basis=cli._live_basis(None), read_sequence=read_sequence)

    argv = lambda path, *more: ["report", "--study", path, "--out", Path(path).parent / "page.html", *more]  # noqa: E731
    return Scenario(study, argv, library, bike_bump)


def decide_scenario(tmp_path):
    study, _ = init_study(tmp_path)
    code, payload, err = run_ml(study, "seasonal_7", "dev", "w-held")
    assert code == 0, (payload, err)
    attempt = payload["attempt"]["attempt_id"]

    def library(path, read_sequence, request_id="w-decide", question="Which Configuration?", **fields):
        from hypotrail.core import decisions

        given = {"question": question, "option": "seasonal_7", "author": "human", "source": None, "cited_ids": [attempt], **fields}
        return decisions.decide(path, request_id=request_id, read_sequence=read_sequence, **given)

    argv = lambda path, *more: [  # noqa: E731
        "decide", "--study", path, "--question", "Which Configuration?", "--option", "seasonal_7", "--author", "human", "--artifact", attempt,
        "--request-id", "w-decide", *more,
    ]
    return Scenario(study, argv, library, bike_bump)


SCENARIOS = {
    "init --new-revision": new_revision_scenario,
    "run ml": run_ml_scenario,
    "run agent": run_agent_scenario,
    "import ml": import_ml_scenario,
    "import agent": import_agent_scenario,
    "assess": assess_scenario,
    "compare": compare_scenario,
    "recover": recover_scenario,
    "report": report_scenario,
    "decide": decide_scenario,
}

# `decide` requires the option: without it, it is refused, so the rows that run a command without the option leave it out (tests/test_decide.py)
OPTIONAL = [command for command in SCENARIOS if command != "decide"]


def error_of(payload):
    assert payload["ok"] is False and set(payload) == {"ok", "error"}
    assert set(payload["error"]) == {"code", "message", "stage", "details"}
    return payload["error"]


# --- the first criterion and Tightened K: given and current, the command does what it does without the option ----------

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
TIMESTAMP = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?"
DIGEST = r"[0-9a-f]{64}"  # the digest of a record that holds a UUID or a timestamp differs between two executions: it is masked with them
MASK = re.compile(f"{UUID}|{TIMESTAMP}|{DIGEST}")


# Inspect names its log by the time and a random id, and the log holds both: its path, digest and size differ between two executions
INSPECT_LOG = re.compile(r'"path": "[^"]*\.eval", "role": "inspect_log", "sha256": "[0-9a-f]{64}", "size_bytes": \d+')


SIZE = re.compile(r'"size_bytes": \d+')  # a record that holds a timestamp has a length that varies with it


def masked(payload, *roots) -> str:
    text = json.dumps(payload, sort_keys=True)
    for root in roots:
        text = text.replace(str(root), "<dir>")
    text = INSPECT_LOG.sub("<inspect log>", text)
    text = SIZE.sub('"size_bytes": "<masked>"', text)
    return MASK.sub("<masked>", text)


def key_paths(value, prefix="") -> set:
    if isinstance(value, dict):
        return {path for key, item in value.items() for path in ({f"{prefix}/{key}"} | key_paths(item, f"{prefix}/{key}"))}
    if isinstance(value, list):
        return {path for item in value for path in key_paths(item, f"{prefix}[]")}
    return set()


@pytest.mark.parametrize("command", OPTIONAL)
def test_given_and_current_the_command_gives_what_it_gives_without_the_option_and_advances_the_sequence_by_two(command, tmp_path):
    scenario = SCENARIOS[command](tmp_path)
    with_option, without = scenario.copy_to(tmp_path / "with"), scenario.copy_to(tmp_path / "without")
    before = seq(with_option)
    assert before == seq(without)
    code_with, payload_with, err_with = scenario.call(with_option, "--read-sequence", before)
    code_without, payload_without, err_without = scenario.call(without)
    assert (code_with, code_without) == (0, 0), (payload_with, err_with)
    assert masked(payload_with, tmp_path / "with") == masked(payload_without, tmp_path / "without")
    assert key_paths(payload_with) == key_paths(payload_without)
    assert seq(with_option) == before + 2
    assert seq(without) == before + 2


@pytest.mark.parametrize("command", SCENARIOS)
def test_given_and_current_to_the_library_the_command_gives_its_result(command, tmp_path):
    scenario = SCENARIOS[command](tmp_path)
    before = seq(scenario.study)
    scenario.library(scenario.study, before)
    assert seq(scenario.study) == before + 2


# --- the second criterion, Tightened A and H: given and older, refused with one code, nothing written -----------------


def older(command, tmp_path):
    """(scenario, the value its author read, the Study's files then): a write is made after the read."""
    scenario = SCENARIOS[command](tmp_path)
    read = seq(scenario.study)
    scenario.bump(scenario.study)
    assert seq(scenario.study) == read + 2
    return scenario, read, tree(scenario.study)


@pytest.mark.parametrize("command", SCENARIOS)
def test_given_and_older_the_command_is_refused_with_study_changed_naming_the_writes_since_and_writes_nothing(command, tmp_path):
    scenario, read, files = older(command, tmp_path)
    current = seq(scenario.study)
    code, payload, err = scenario.call(scenario.study, "--read-sequence", read)
    error = error_of(payload)
    assert (code, error["code"], error["stage"]) == (6, "STUDY_CHANGED", "sequence")
    assert set(error["details"]) == {"read_sequence", "write_sequence", "writes_since"}
    assert (error["details"]["read_sequence"], error["details"]["write_sequence"]) == (read, current)
    assert error["details"]["writes_since"] == entries(scenario.study)[read:]
    assert tree(scenario.study) == files
    assert seq(scenario.study) == current


@pytest.mark.parametrize("command", SCENARIOS)
def test_the_refusal_reaches_stderr_without_json_and_stdout_stays_empty(command, tmp_path):
    scenario, read, files = older(command, tmp_path)
    code, out, err = run_cli(*scenario.argv(scenario.study, "--read-sequence", read))
    assert code == 6 and out == ""
    assert err.startswith("STUDY_CHANGED [sequence]:")
    assert tree(scenario.study) == files


@pytest.mark.parametrize("command", SCENARIOS)
def test_a_library_caller_catches_the_same_code_and_details(command, tmp_path):
    scenario, read, files = older(command, tmp_path)
    _, payload, _ = scenario.call(scenario.study, "--read-sequence", read)
    with pytest.raises(HypotrailError) as caught:
        scenario.library(scenario.study, read)
    assert (caught.value.code, caught.value.exit_code, caught.value.stage) == ("STUDY_CHANGED", 6, "sequence")
    assert caught.value.to_dict() == payload["error"]
    assert tree(scenario.study) == files


# --- Tightened C: ahead, negative, and a value that is not an integer -----------------------------------------------------


@pytest.mark.parametrize("command", SCENARIOS)
def test_given_above_the_current_value_the_command_is_refused_with_write_sequence_ahead(command, tmp_path):
    scenario = SCENARIOS[command](tmp_path)
    current, files = seq(scenario.study), tree(scenario.study)
    code, payload, err = scenario.call(scenario.study, "--read-sequence", current + 1)
    error = error_of(payload)
    assert (code, error["code"], error["stage"]) == (2, "WRITE_SEQUENCE_AHEAD", "sequence")
    assert error["details"] == {"read_sequence": current + 1, "write_sequence": current}
    assert tree(scenario.study) == files


@pytest.mark.parametrize("value", ["-1", "abc", "1.5", ""])
@pytest.mark.parametrize("command", SCENARIOS)
def test_a_value_that_is_negative_or_not_an_integer_is_refused_as_an_argument_and_nothing_is_written(command, value, tmp_path):
    scenario = SCENARIOS[command](tmp_path)
    files = tree(scenario.study)
    code, payload, err = scenario.call(scenario.study, "--read-sequence", value)
    error = error_of(payload)
    assert (code, error["code"], error["stage"]) == (2, "INVALID_ARGUMENTS", "config")
    assert "--read-sequence" in error["message"] and "unrecognized" not in error["message"]  # the option is known; its value is what is refused
    assert tree(scenario.study) == files


@pytest.mark.parametrize("value", [-1, 1.5, True, "valid"], ids=["negative", "not an integer", "boolean", "current value"])
@pytest.mark.parametrize("command", SCENARIOS)
def test_a_library_caller_is_refused_a_bad_read_sequence_as_an_argument_before_any_lock_and_nothing_is_written(command, value, tmp_path):
    # #108 Tightened C, R1-P-03: the library entry gives the code and `details` of the CLI, before the lock (a held lock does not change it)
    scenario = SCENARIOS[command](tmp_path)
    files, before = tree(scenario.study), seq(scenario.study)
    if value == "valid":
        scenario.library(scenario.study, before)
        assert seq(scenario.study) == before + 2
        return
    _, payload, _ = scenario.call(scenario.study, "--read-sequence", str(value))
    with held_by_another_process(scenario.study), pytest.raises(HypotrailError) as caught:
        scenario.library(scenario.study, value)
    assert (caught.value.code, caught.value.exit_code, caught.value.stage) == ("INVALID_ARGUMENTS", 2, "config")
    assert caught.value.details == error_of(payload)["details"]
    assert tree(scenario.study) == files and seq(scenario.study) == before


# R2-P-01: a call with two argument faults gives the same code and `details` as the command line, whose parser refuses the value first
TWO_FAULTS = [
    ("run ml", {"request_id": ""}, ["--request-id", ""]),
    ("run agent", {"request_id": ""}, ["--request-id", ""]),
    ("import ml", {"request_id": ""}, ["--request-id", ""]),
    ("import agent", {"request_id": ""}, ["--request-id", ""]),
    ("decide", {"request_id": ""}, ["--request-id", ""]),
    ("decide", {"question": ""}, ["--question", ""]),
]


@pytest.mark.parametrize("command, fault, flags", TWO_FAULTS, ids=[f"{command} {next(iter(fault))}" for command, fault, _ in TWO_FAULTS])
def test_a_call_with_a_bad_read_sequence_and_another_argument_fault_gives_the_code_and_details_of_the_command_line(command, fault, flags, tmp_path):
    scenario = SCENARIOS[command](tmp_path)
    files = tree(scenario.study)
    _, payload, _ = scenario.call(scenario.study, *flags, "--read-sequence", "-1")
    cli = error_of(payload)
    assert cli["code"] == "INVALID_ARGUMENTS"  # argparse refuses the value before the handler looks at the other argument
    with held_by_another_process(scenario.study), pytest.raises(HypotrailError) as caught:
        scenario.library(scenario.study, -1, **fault)
    assert (caught.value.code, caught.value.stage, caught.value.details) == (cli["code"], cli["stage"], cli["details"])
    assert caught.value.message in cli["message"]  # R2-S-05: one rule, one message, for the parser and the library
    assert tree(scenario.study) == files


# D-041 on chadlis/hypotrail#75 item 1: a call with one argument fault gives the code and `details` of the command line, `decide`'s included.
# A call with several faults need not report the same one first: the parser orders them by position on the command line.
def _replace_value(argv, flag, value):
    at = argv.index(flag) + 1
    return [*argv[:at], value, *argv[at + 1:]]


def _drop_option(argv, flag):
    at = argv.index(flag)
    return [*argv[:at], *argv[at + 2:]]


# row: (the command line's edit, the library's fields, whether the command line gives --read-sequence)
DECIDE_SINGLE_FAULTS = {
    "read sequence missing": (lambda argv: argv, {"read_sequence": None}, False),
    "author unknown": (lambda argv: _replace_value(argv, "--author", "robot"), {"author": "robot"}, True),
    "no artifact": (lambda argv: _drop_option(argv, "--artifact"), {"cited_ids": []}, True),
    "question empty": (lambda argv: _replace_value(argv, "--question", ""), {"question": ""}, True),
    "option empty": (lambda argv: _replace_value(argv, "--option", ""), {"option": ""}, True),
    "request id empty": (lambda argv: _replace_value(argv, "--request-id", ""), {"request_id": ""}, True),
}


@pytest.mark.parametrize("row", DECIDE_SINGLE_FAULTS)
def test_decide_with_one_argument_fault_gives_the_library_the_code_stage_and_details_of_the_command_line(row, tmp_path):
    edit, fault, gives_the_value = DECIDE_SINGLE_FAULTS[row]
    scenario = SCENARIOS["decide"](tmp_path)
    files, current = tree(scenario.study), seq(scenario.study)
    argv = edit(scenario.argv(scenario.study, *(["--read-sequence", str(current)] if gives_the_value else [])))
    code, payload, err = run_cli(*argv, "--json")
    cli = error_of(json.loads(payload))
    assert code == 2
    library_fault = dict(fault)
    read = library_fault.pop("read_sequence", current)
    with pytest.raises(HypotrailError) as caught:
        scenario.library(scenario.study, read, **library_fault)
    assert (caught.value.code, caught.value.stage, caught.value.details) == (cli["code"], cli["stage"], cli["details"])
    assert tree(scenario.study) == files


# --- Tightened J and E: init that creates a Study takes no option ------------------------------------------------------------


def test_init_that_creates_a_study_given_the_option_is_refused_as_an_argument_and_writes_nothing(tmp_path):
    study = tmp_path / "fresh"
    code, payload, err = run_json("init", "--workload", "bike_day", "--study", study, "--read-sequence", 0)
    error = error_of(payload)
    assert (code, error["code"]) == (2, "INVALID_ARGUMENTS")
    assert "--read-sequence" in error["message"] and "unrecognized" not in error["message"]  # init knows the option and refuses it
    assert not (study / "study.json").exists() and not (study / "write_journal").exists()


# --- Tightened D: the order of the refusals, one row per pair of neighbours --------------------------------------------------


def test_an_empty_request_id_with_no_study_is_refused_as_request_id_empty(tmp_path):
    code, payload, err = run_ml(tmp_path / "none", "seasonal_7", "dev", "", "--read-sequence", 3)
    assert (code, error_of(payload)["code"]) == (2, "REQUEST_ID_EMPTY")


def test_no_study_with_an_older_value_is_refused_as_study_not_found(tmp_path):
    code, payload, err = run_ml(tmp_path / "none", "seasonal_7", "dev", "r", "--read-sequence", 0)
    assert (code, error_of(payload)["code"]) == (2, "STUDY_NOT_FOUND")


def test_a_held_lock_with_an_older_value_is_refused_as_study_locked(tmp_path):
    study, _ = init_study(tmp_path)
    run_ml(study, "seasonal_7", "dev", "first")
    with held_by_another_process(study):
        code, payload, err = run_ml(study, "seasonal_7", "dev", "second", "--read-sequence", 0)
    assert (code, error_of(payload)["code"]) == (6, "STUDY_LOCKED")


def test_a_replay_with_an_older_value_returns_the_recorded_attempt_and_writes_nothing(tmp_path):
    study, _ = init_study(tmp_path)
    _, first, _ = run_ml(study, "seasonal_7", "dev", "r1")
    files, current = tree(study), seq(study)
    code, payload, err = run_ml(study, "seasonal_7", "dev", "r1", "--read-sequence", 0)
    assert code == 0 and payload["replayed"] is True
    assert payload["attempt"]["attempt_id"] == first["attempt"]["attempt_id"]
    assert tree(study) == files and seq(study) == current


def test_a_request_conflict_with_an_older_value_is_refused_as_request_conflict(tmp_path):
    study, _ = init_study(tmp_path)
    run_ml(study, "seasonal_7", "dev", "r1")
    code, payload, err = run_ml(study, "ridge_v1", "dev", "r1", "--read-sequence", 0)
    assert (code, error_of(payload)["code"]) == (6, "REQUEST_CONFLICT")


def shifted_partitions(declaration):
    declaration["partitions"]["dev"][1] = "2012-06-29"
    declaration["partitions"]["public_check"][0] = "2012-06-30"


@pytest.mark.parametrize("track", ["run ml", "run agent"])
def test_an_older_value_with_a_changed_protocol_is_refused_as_study_changed(track, tmp_path):
    if track == "run ml":
        study, _ = init_study(tmp_path)
        bike_bump(study)
        examples = examples_copy(tmp_path, edit=shifted_partitions, name="shifted")
        call = lambda *more: run_ml(study, "seasonal_7", "dev", "new", "--examples-dir", examples, *more)  # noqa: E731
    else:
        study, _ = init_chinook(tmp_path)
        chinook_bump(study)
        examples = chinook_examples(tmp_path, edit=lambda d: d.update(question="changed"), name="changed")
        call = lambda *more: fixture(study, "plain", "new", "--examples-dir", examples, *more)  # noqa: E731
    files = tree(study)
    code, payload, err = call("--read-sequence", 0)
    assert (code, error_of(payload)["code"]) == (6, "STUDY_CHANGED"), (payload, err)
    assert tree(study) == files


# --- Tightened L: where `run` and `import` keep their other refusals relative to the stale check -------------------------------


def test_run_agent_with_data_that_differs_from_its_lock_and_an_older_value_gives_study_changed(tmp_path):
    study, _ = init_chinook(tmp_path)
    chinook_bump(study)
    examples = chinook_examples(tmp_path, name="flipped")
    database = database_of(examples)
    content = bytearray(database.read_bytes())
    content[len(content) // 2] ^= 1
    database.write_bytes(bytes(content))
    files = tree(study)
    code, payload, err = fixture(study, "plain", "new", "--examples-dir", examples, "--read-sequence", 0)
    assert (code, error_of(payload)["code"]) == (6, "STUDY_CHANGED"), (payload, err)
    assert tree(study) == files


def test_run_ml_with_data_that_differs_from_its_lock_and_an_older_value_gives_data_integrity(tmp_path):
    study, _ = init_study(tmp_path)
    bike_bump(study)
    examples = examples_copy(tmp_path, name="flipped")
    data_file = examples / "bike_day" / "data" / "day.csv"
    content = bytearray(data_file.read_bytes())
    content[len(content) // 2] ^= 1
    data_file.write_bytes(bytes(content))
    files = tree(study)
    code, payload, err = run_ml(study, "seasonal_7", "dev", "new", "--examples-dir", examples, "--read-sequence", 0)
    assert (code, error_of(payload)["code"]) == (3, "DATA_INTEGRITY"), (payload, err)
    assert tree(study) == files


def test_run_ml_on_a_chinook_study_with_an_older_value_gives_unsupported_capability(tmp_path):
    study, _ = init_chinook(tmp_path)
    chinook_bump(study)
    files = tree(study)
    code, payload, err = run_ml(study, "seasonal_7", "dev", "new", "--read-sequence", 0)
    assert (code, error_of(payload)["code"]) == (2, "UNSUPPORTED_CAPABILITY"), (payload, err)
    assert tree(study) == files


def test_run_ml_with_an_unknown_retry_of_and_an_older_value_gives_retry_of_unknown(tmp_path):
    study, _ = init_study(tmp_path)
    bike_bump(study)
    files = tree(study)
    code, payload, err = run_ml(study, "seasonal_7", "dev", "new", "--retry-of", "nope", "--read-sequence", 0)
    assert (code, error_of(payload)["code"]) == (2, "RETRY_OF_UNKNOWN"), (payload, err)
    assert tree(study) == files


# --- Tightened M (D-038 on chadlis/hypotrail#75): two checks that read only the arguments and the spec keep their place before the lock ---------------


CHAPTER_04 = Path(__file__).resolve().parent.parent / "docs" / "handbook" / "chapters" / "04-study-and-attempts.html"


def checks_before_the_lock():
    """{command: code} of the table `checks-before-the-lock` of chapter 04 (R2-S-01): what the handbook says keeps its place before the lock."""
    table = re.search(r'<table[^>]*id="checks-before-the-lock".*?</table>', CHAPTER_04.read_text(encoding="utf-8"), re.S)
    assert table, "chapter 04 has no table `checks-before-the-lock`"
    return {command: code for command, code in re.findall(r'<tr data-command="([^"]+)" data-exit="\d+" data-code="([^"]+)"', table[0])}


def provoked(case):
    """The call of a row of the probe's table, as `(study, the Study's files, the call)`; the value it gives is below the Study's."""

    def provoke(tmp_path):
        study, call = CHECK_CALLS[case](tmp_path)
        return study, tree(study), lambda: call(max(seq(study) - 2, 0))

    return provoke


PROVOKED = {case: provoked(case) for case in CHECKS_BEFORE_THE_LOCK}


def test_the_table_of_the_checks_before_the_lock_lists_the_checks_the_test_provokes():
    assert set(checks_before_the_lock()) == set(PROVOKED)


@pytest.mark.parametrize("command", sorted(PROVOKED))
def test_each_check_of_the_table_before_the_lock_gives_its_code_with_the_lock_held_and_an_older_value_and_writes_nothing(command, tmp_path):
    # #108 Tightened M (D-038 on chadlis/hypotrail#75): neither the lock nor the older value (STUDY_LOCKED, STUDY_CHANGED) comes before it
    study, files, call = PROVOKED[command](tmp_path)
    with held_by_another_process(study):
        code, payload, err = call()
    assert (code, error_of(payload)["code"]) == (CHECKS_BEFORE_THE_LOCK[command][1], checks_before_the_lock()[command]), (payload, err)
    assert tree(study) == files


# --- Tightened F: report compares the value only when its page would record an Exposure ----------------------------------------


def test_report_of_dev_items_only_with_an_older_value_writes_its_page(tmp_path):
    study = Bike().dev_study(tmp_path)
    read = seq(study)
    bike_bump(study)
    out = tmp_path / "page.html"
    code, payload, err = report(study, out, "--read-sequence", read)
    assert code == 0, (payload, err)
    assert out.is_file() and payload["report"]["exposure"]["recorded"] is False


def test_report_of_public_check_items_with_an_older_value_records_no_exposure_and_writes_no_page(tmp_path):
    study, _ = TRACKS["bike"].public_outputs(tmp_path)
    read = seq(study)
    bike_bump(study)
    files, out = tree(study), tmp_path / "page.html"
    code, payload, err = report(study, out, "--read-sequence", read)
    assert (code, error_of(payload)["code"]) == (6, "STUDY_CHANGED"), (payload, err)
    assert tree(study) == files and not out.exists()
    _, status, _ = run_json("status", "--study", study)
    assert status["exposures"]["recorded_in_this_study"] == 0


# --- the third criterion: not given, nothing changes (the existing suite, and this row) ----------------------------------------


@pytest.mark.parametrize("command", OPTIONAL)
def test_not_given_the_command_is_not_refused_on_an_older_study(command, tmp_path):
    scenario, _, _ = older(command, tmp_path)
    code, payload, err = scenario.call(scenario.study)
    assert code == 0, (payload, err)
