"""Pins of what the two import commands share, written before those helpers are written once, and kept unchanged by the change that does it.

Each pin goes through the command line, as a user does, for each import command that reaches the helper: the refusal of an input file that
cannot be read, of a serialized source, and of an Episode outside the population (once per value of `problem`, from JSON Lines and from an
Inspect log); what the request identity holds, and the refusal that follows, for a mapping, a population and a line that are not strict
JSON; the `{"value", "origin"}` of each producer field of the Observation set's `provenance`, with `unknown_fields`; and that the `usage` of
an Episode imported from an Inspect log has no `cost` key. No provider is called: the logs are written by Inspect's mock model.
"""

import json
from pathlib import Path

import pytest
from _chinook_helpers import FIXTURE, episodes_file, fixture_lines, fixture_population, import_agent, init_chinook, write_lines
from _import_helpers import MAPPING, import_ml, mapping_of, ready
from _log_helpers import scripted_log
from _study_helpers import init_study

SERIALIZED_PICKLE = b"\x80\x04N."  # `pickle.dumps(None)`: a source whose first byte is the pickle protocol marker
ML_SERIALIZED = "the source is a serialized object (pickle, joblib or an array dump); an import adopts a CSV of predictions and loads nothing"
AGENT_SERIALIZED = "the source is a serialized object (pickle, joblib or an array dump); an import adopts JSON Lines and loads nothing"


@pytest.fixture
def bike(tmp_path):
    return init_study(tmp_path)[0]


@pytest.fixture
def chinook(tmp_path):
    return init_chinook(tmp_path)[0]


def refused(result) -> tuple:
    """(exit code, the error object) of a refused command."""
    code, payload, err = result
    assert payload["ok"] is False, (payload, err)
    return code, payload["error"]


def observation_set_of(study, payload) -> dict:
    assert payload["ok"] is True, payload
    return json.loads((Path(study) / "attempts" / payload["attempt"]["attempt_id"] / "observation_set.json").read_text(encoding="utf-8"))


def normalized_of(study, payload) -> list:
    path = Path(study) / "attempts" / payload["attempt"]["attempt_id"] / "observations.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def first_copy_first(text: str, member: str) -> str:
    """The JSON object `text` with `member` written before its first member: a first copy of a key, which a strict read refuses and a lenient one overrides."""
    return "{" + member + ", " + text[1:]


# --- an input file that cannot be read ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["source", "mapping", "population"])
def test_import_ml_refuses_an_input_file_that_cannot_be_read_with_its_code_its_message_the_import_stage_and_its_one_detail(tmp_path, bike, which):
    files = dict(zip(("source", "mapping", "population"), ready(tmp_path)[:3]))
    gone = tmp_path / "gone"
    files[which] = gone
    code, error = refused(import_ml(bike, files["source"], files["mapping"], files["population"], "r"))
    assert code == 2
    assert error["code"] == f"{which.upper()}_NOT_FOUND"
    assert error["message"] == f"the {which} file cannot be read: {gone}"
    assert error["stage"] == "import"
    assert set(error["details"]) == {which}


@pytest.mark.parametrize("which, name", [("source", "gone.jsonl"), ("source", "gone.eval"), ("population", "gone.json")])
def test_import_agent_refuses_an_input_file_that_cannot_be_read_with_its_code_its_message_the_import_stage_and_its_one_detail(tmp_path, chinook, which, name):
    files = {"source": FIXTURE, "population": fixture_population(tmp_path)}
    gone = tmp_path / name
    files[which] = gone
    code, error = refused(import_agent(chinook, files["source"], files["population"], "r"))
    assert code == 2
    assert error["code"] == f"{which.upper()}_NOT_FOUND"
    assert error["message"] == f"the {which} file cannot be read: {gone}"
    assert error["stage"] == "import"
    assert set(error["details"]) == {which}


# --- a serialized source, by suffix and by first byte ------------------------------------------------------------------------


@pytest.mark.parametrize("name, first_byte", [("predictions.pkl", False), ("predictions.PICKLE", False), ("predictions.joblib", False), ("predictions.npy", False), ("predictions.npz", False), ("predictions.csv", True)])
def test_import_ml_refuses_a_serialized_source_by_suffix_and_by_first_byte_with_its_own_message(tmp_path, bike, name, first_byte):
    source, mapping, population, _ = ready(tmp_path)
    serialized = tmp_path / "serialized" / name
    serialized.parent.mkdir()
    serialized.write_bytes(SERIALIZED_PICKLE if first_byte else source.read_bytes())
    code, error = refused(import_ml(bike, serialized, mapping, population, "r"))
    assert code == 2
    assert error["code"] == "SOURCE_SERIALIZED"
    assert error["message"] == ML_SERIALIZED
    assert error["stage"] == "import"
    assert set(error["details"]) == {"source"}


@pytest.mark.parametrize("name, first_byte", [("answers.pkl", False), ("answers.pickle", False), ("answers.JOBLIB", False), ("answers.npy", False), ("answers.npz", False), ("answers.jsonl", True)])
def test_import_agent_refuses_a_serialized_source_by_suffix_and_by_first_byte_with_its_own_message(tmp_path, chinook, name, first_byte):
    serialized = tmp_path / name
    serialized.write_bytes(SERIALIZED_PICKLE if first_byte else FIXTURE.read_bytes())
    code, error = refused(import_agent(chinook, serialized, fixture_population(tmp_path), "r"))
    assert code == 2
    assert error["code"] == "SOURCE_SERIALIZED"
    assert error["message"] == AGENT_SERIALIZED
    assert error["stage"] == "import"
    assert set(error["details"]) == {"source"}


# --- an Episode outside the population, once per value of `problem` -----------------------------------------------------------

# {problem: the line added to the kit's four lines}: D01, D03, D07 and D08 of `dev`, Repeat 0, are the population.
OUTSIDE_LINES = {
    "unknown_case": {"case_id": "Z99", "repeat": 0},
    "other_partition": {"case_id": "E01", "repeat": 0},
    "not_in_population": {"case_id": "D02", "repeat": 0},
    "repeat_out_of_range": {"case_id": "D01", "repeat": 1},
}


@pytest.mark.parametrize("problem", sorted(OUTSIDE_LINES))
def test_import_agent_refuses_a_line_outside_the_population_with_each_problem_its_message_the_import_stage_and_its_details(tmp_path, chinook, problem):
    lines = fixture_lines()
    lines.append({**lines[0], **OUTSIDE_LINES[problem]})
    case_id, repeat = OUTSIDE_LINES[problem]["case_id"], OUTSIDE_LINES[problem]["repeat"]
    code, error = refused(import_agent(chinook, write_lines(tmp_path / "answers.jsonl", lines), fixture_population(tmp_path), "r"))
    assert code == 2
    assert error["code"] == "EPISODE_OUTSIDE_POPULATION"
    assert error["message"] == f"line 5: ({case_id}, repeat {repeat}) is not an Episode of the population"
    assert error["stage"] == "import"
    assert set(error["details"]) == {"case_id", "repeat", "line", "problem"}
    assert error["details"]["problem"] == problem


def relabelled(log, case_id):
    """The log with the id of its last sample set to `case_id`."""
    from inspect_ai.log import read_eval_log, write_eval_log

    loaded = read_eval_log(str(log))
    loaded.samples[-1].id = case_id
    write_eval_log(loaded, str(log))
    return log


# {problem: (the log, the population)}, each log written by the mock model on `dev` Cases.
OUTSIDE_LOGS = {
    "unknown_case": (lambda tmp: relabelled(scripted_log(tmp, ("D01", "D03")), "Z99"), [("D01", 0), ("D03", 0)], ("Z99", 0)),
    "other_partition": (lambda tmp: relabelled(scripted_log(tmp, ("D01", "D03")), "E01"), [("D01", 0), ("D03", 0)], ("E01", 0)),
    "not_in_population": (lambda tmp: scripted_log(tmp, ("D01", "D03")), [("D01", 0)], ("D03", 0)),
    "repeat_out_of_range": (lambda tmp: scripted_log(tmp, ("D01",), repeats=2), [("D01", 0)], ("D01", 1)),
}


@pytest.mark.parametrize("problem", sorted(OUTSIDE_LOGS))
def test_import_agent_refuses_a_log_sample_outside_the_population_with_each_problem_its_message_the_import_stage_and_its_details(tmp_path, chinook, problem):
    make, keys, (case_id, repeat) = OUTSIDE_LOGS[problem]
    code, error = refused(import_agent(chinook, make(tmp_path), episodes_file(tmp_path, keys), "r"))
    assert code == 2
    assert error["code"] == "LOG_EPISODE_OUTSIDE_POPULATION"
    assert error["message"] == f"({case_id}, repeat {repeat}) is in the log and is not an Episode of the population"
    assert error["stage"] == "import"
    assert set(error["details"]) == {"case_id", "repeat", "problem"}
    assert error["details"]["problem"] == problem


# --- the strict JSON read: what the request holds, then the refusal ------------------------------------------------------------
# The request holds what the strict read gives, which is nothing for input that is not strict JSON. It is seen through the
# `differs` of `REQUEST_CONFLICT`, against a recorded request of the same `request_id`; the same input under a new `request_id`
# then meets the input's own refusal.


def test_import_ml_holds_model_unknown_for_a_mapping_that_is_not_strict_json_then_refuses_it_as_not_json(tmp_path, bike):
    source, mapping, population, digest = ready(tmp_path)
    assert import_ml(bike, source, mapping, population, "recorded")[0] == 0  # a mapping that declares no model: the model is `unknown`
    declaring = json.dumps({**MAPPING, "dataset_sha256": digest, "model": "acme-1"})
    not_strict = tmp_path / "not-strict-mapping.json"
    not_strict.write_text(first_copy_first(declaring, '"row_id": 3'), encoding="utf-8")
    code, error = refused(import_ml(bike, source, not_strict, population, "recorded"))
    assert (code, error["code"]) == (6, "REQUEST_CONFLICT")
    assert error["details"]["differs"] == ["input_digests"]  # the request's model is `unknown`, not the `acme-1` of the last copy
    code, error = refused(import_ml(bike, source, not_strict, population, "new"))
    assert code == 2
    assert error["code"] == "MAPPING_INVALID"
    assert error["message"] == "the mapping is not a JSON document in UTF-8"
    assert error["stage"] == "import"
    assert set(error["details"]) == {"mapping", "problem"}


def test_import_ml_holds_no_partition_for_a_population_that_is_not_strict_json_then_refuses_it_as_not_json(tmp_path, bike):
    source, mapping, population, _ = ready(tmp_path)
    assert import_ml(bike, source, mapping, population, "recorded")[0] == 0  # the recorded request's Partition is `dev`
    not_strict = tmp_path / "not-strict-population.json"
    not_strict.write_text(first_copy_first(population.read_text(encoding="utf-8"), '"item_ids": []'), encoding="utf-8")
    code, error = refused(import_ml(bike, source, mapping, not_strict, "recorded"))
    assert (code, error["code"]) == (6, "REQUEST_CONFLICT")
    assert error["details"]["differs"] == ["partition", "input_digests"]  # the request's Partition is null, not `dev`
    code, error = refused(import_ml(bike, source, mapping, not_strict, "new"))
    assert code == 2
    assert error["code"] == "POPULATION_INVALID"
    assert error["message"] == "the population is not a JSON document in UTF-8"
    assert error["stage"] == "import"
    assert set(error["details"]) == {"population", "problem"}


def test_import_agent_holds_no_partition_for_a_population_that_is_not_strict_json_then_refuses_it_as_not_json(tmp_path, chinook):
    population = fixture_population(tmp_path)
    assert import_agent(chinook, FIXTURE, population, "recorded")[0] == 0  # the recorded request's Partition is `dev`, with one Repeat
    not_strict = tmp_path / "not-strict-population.json"
    not_strict.write_text(first_copy_first(population.read_text(encoding="utf-8"), '"episodes": []'), encoding="utf-8")
    code, error = refused(import_agent(chinook, FIXTURE, not_strict, "recorded"))
    assert (code, error["code"]) == (6, "REQUEST_CONFLICT")
    assert error["details"]["differs"] == ["partition", "repeats", "input_digests"]  # the request's Partition is null and its Repeats `unknown`
    code, error = refused(import_agent(chinook, FIXTURE, not_strict, "new"))
    assert code == 2
    assert error["code"] == "POPULATION_INVALID"
    assert error["message"] == "the population is not a JSON document in UTF-8"
    assert error["stage"] == "import"
    assert set(error["details"]) == {"population", "problem"}


def test_import_agent_holds_model_unknown_for_a_line_that_is_not_strict_json_then_refuses_the_line_as_not_json(tmp_path, chinook):
    population = fixture_population(tmp_path)
    assert import_agent(chinook, FIXTURE, population, "recorded")[0] == 0  # the kit's lines declare no model: the model is `unknown`
    lines = [{**line, "producer": {"model": "acme-1"}} for line in fixture_lines()]
    texts = [json.dumps(line) for line in lines]
    texts[0] = first_copy_first(texts[0], '"case_id": "Z99"')
    not_strict = tmp_path / "not-strict-answers.jsonl"
    not_strict.write_text("".join(text + "\n" for text in texts), encoding="utf-8")
    code, error = refused(import_agent(chinook, not_strict, population, "recorded"))
    assert (code, error["code"]) == (6, "REQUEST_CONFLICT")
    assert error["details"]["differs"] == ["input_digests"]  # the request's model is `unknown`, not the `acme-1` every line holds
    code, error = refused(import_agent(chinook, not_strict, population, "new"))
    assert code == 2
    assert error["code"] == "LINE_NOT_JSON"
    assert error["message"] == "line 1 of the source is not JSON"
    assert error["stage"] == "import"
    assert set(error["details"]) == {"line"}


# --- the producer entry of each provenance field -------------------------------------------------------------------------------

UNKNOWN_ENTRY = {"value": None, "origin": "unknown"}


def test_import_ml_records_each_producer_field_the_mapping_declares_as_declared_and_stripped_and_saw_public_check_as_unknown(tmp_path, bike):
    source, _, population, digest = ready(tmp_path)
    mapping = mapping_of(tmp_path, digest, name="declaring.json", model=" acme-1 ", generated_at="2026-11-01", historical_protocol="h-1", tool_use="none")
    _, payload, _ = import_ml(bike, source, mapping, population, "r")
    record = observation_set_of(bike, payload)
    provenance = record["provenance"]
    assert provenance["model"] == {"value": "acme-1", "origin": "declared"}
    assert provenance["generation_time"] == {"value": "2026-11-01", "origin": "declared"}
    assert provenance["historical_protocol"] == {"value": "h-1", "origin": "declared"}
    assert provenance["tool_use"] == {"value": "none", "origin": "declared"}
    assert provenance["saw_public_check"] == UNKNOWN_ENTRY
    assert record["unknown_fields"] == ["saw_public_check"]


def test_import_ml_records_each_producer_field_the_mapping_does_not_declare_as_unknown(tmp_path, bike):
    source, mapping, population, _ = ready(tmp_path)
    _, payload, _ = import_ml(bike, source, mapping, population, "r")
    record = observation_set_of(bike, payload)
    provenance = record["provenance"]
    assert provenance["model"] == UNKNOWN_ENTRY
    assert provenance["generation_time"] == UNKNOWN_ENTRY
    assert provenance["historical_protocol"] == UNKNOWN_ENTRY
    assert provenance["tool_use"] == UNKNOWN_ENTRY
    assert provenance["saw_public_check"] == UNKNOWN_ENTRY
    assert record["unknown_fields"] == ["model", "generation_time", "historical_protocol", "tool_use", "saw_public_check"]


def test_import_agent_records_each_producer_field_every_line_declares_alike_as_declared_and_stripped(tmp_path, chinook):
    producer = {"model": " acme-1 ", "generation_time": "2026-11-01", "historical_protocol": "h-1", "tool_use": "none"}
    lines = [{**line, "producer": producer, "origin": "elsewhere", "mode": "batch"} for line in fixture_lines()]
    _, payload, _ = import_agent(chinook, write_lines(tmp_path / "answers.jsonl", lines), fixture_population(tmp_path), "r")
    record = observation_set_of(chinook, payload)
    provenance = record["provenance"]
    assert provenance["model"] == {"value": "acme-1", "origin": "declared"}
    assert provenance["generation_time"] == {"value": "2026-11-01", "origin": "declared"}
    assert provenance["historical_protocol"] == {"value": "h-1", "origin": "declared"}
    assert provenance["tool_use"] == {"value": "none", "origin": "declared"}
    assert provenance["saw_public_check"] == UNKNOWN_ENTRY
    assert provenance["file_origin"] == {"value": "elsewhere", "origin": "declared"}
    assert provenance["file_mode"] == {"value": "batch", "origin": "declared"}
    assert record["unknown_fields"] == ["saw_public_check", "settings"]  # #266: no line declares `settings`


def test_import_agent_records_each_producer_field_no_line_declares_or_the_lines_declare_differently_as_unknown(tmp_path, chinook):
    lines = [{key: value for key, value in line.items() if key not in ("producer", "origin", "mode")} for line in fixture_lines()]
    lines[0]["producer"] = {"model": "acme-1"}  # one line declares a model and the others do not
    lines[0]["mode"], lines[1]["mode"] = "batch", "stream"  # two lines declare modes that differ
    _, payload, _ = import_agent(chinook, write_lines(tmp_path / "answers.jsonl", lines), fixture_population(tmp_path), "r")
    record = observation_set_of(chinook, payload)
    provenance = record["provenance"]
    assert provenance["model"] == UNKNOWN_ENTRY
    assert provenance["generation_time"] == UNKNOWN_ENTRY
    assert provenance["historical_protocol"] == UNKNOWN_ENTRY
    assert provenance["tool_use"] == UNKNOWN_ENTRY
    assert provenance["saw_public_check"] == UNKNOWN_ENTRY
    assert provenance["file_origin"] == UNKNOWN_ENTRY
    assert provenance["file_mode"] == UNKNOWN_ENTRY
    assert record["unknown_fields"] == ["model", "generation_time", "historical_protocol", "tool_use", "saw_public_check", "file_origin", "file_mode", "settings"]


def log_with_empty_system_text(tmp_path):
    """A log of D01 and D03 by the mock model whose header states an empty system text."""
    from inspect_ai.log import read_eval_log, write_eval_log

    log = scripted_log(tmp_path, ("D01", "D03"))
    loaded = read_eval_log(str(log))
    loaded.eval.metadata["system_text"] = ""
    write_eval_log(loaded, str(log))
    return log


def test_import_agent_records_what_a_log_header_states_as_declared_and_an_empty_or_absent_value_as_unknown(tmp_path, chinook):
    from inspect_ai.log import read_eval_log

    from hypotrail.agentic import limits

    log = log_with_empty_system_text(tmp_path)
    header = read_eval_log(str(log), header_only=True)
    _, payload, _ = import_agent(chinook, log, episodes_file(tmp_path, [("D01", 0), ("D03", 0)]), "r")
    record = observation_set_of(chinook, payload)
    provenance, stated = record["provenance"], record["provenance"]["log"]
    assert provenance["model"] == {"value": "mockllm/model", "origin": "declared"}
    assert provenance["generation_time"] == {"value": header.eval.created, "origin": "declared"}
    assert provenance["historical_protocol"] == UNKNOWN_ENTRY
    assert provenance["tool_use"] == UNKNOWN_ENTRY
    assert provenance["saw_public_check"] == UNKNOWN_ENTRY
    assert provenance["file_origin"] == UNKNOWN_ENTRY
    assert provenance["file_mode"] == {"value": "scripted_fixture", "origin": "declared"}
    assert stated["configuration"] == {"value": "plain", "origin": "declared"}
    assert stated["system_text"] == {"value": "", "origin": "unknown"}
    assert stated["limits"] == {"value": limits.effective_limits(header), "origin": "declared"}
    assert stated["inspect_version"] == {"value": "0.3.287", "origin": "declared"}
    assert stated["log_format_version"] == {"value": 2, "origin": "declared"}
    assert stated["log_status"] == {"value": "success", "origin": "declared"}
    assert record["unknown_fields"] == ["historical_protocol", "tool_use", "saw_public_check", "file_origin", "settings", "log.system_text"]


# --- the usage of an Episode imported from an Inspect log ---------------------------------------------------------------------


def test_the_usage_of_each_episode_imported_from_an_inspect_log_has_no_cost_key(tmp_path, chinook):
    log = scripted_log(tmp_path, ("D01", "D03"), repeats=2)
    keys = [(case_id, repeat) for case_id in ("D01", "D03") for repeat in range(2)]
    _, payload, _ = import_agent(chinook, log, episodes_file(tmp_path, keys), "r")
    episodes = normalized_of(chinook, payload)
    assert [(episode["case_id"], episode["repeat"]) for episode in episodes] == keys
    for episode in episodes:
        assert "cost" not in episode["usage"], (episode["case_id"], episode["repeat"])
