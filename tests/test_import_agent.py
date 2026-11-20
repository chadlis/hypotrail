"""Ticket #68: `import agent` adopts agent answers produced elsewhere, as JSONL, as an Import Attempt of a Chinook Study."""

import json
from pathlib import Path

import pytest
from _assess_helpers import snapshot
from _chinook_helpers import (
    FIXTURE,
    FIXTURE_CASES,
    episodes_file,
    fixture_lines,
    fixture_population,
    import_agent,
    init_chinook,
    write_lines,
)
from _study_helpers import run_json, sha256

from hypotrail.core import canonical, contracts, requests
from hypotrail.core.errors import EXIT_INTEGRITY_REFUSED, EXIT_INVALID_INPUT, EXIT_LOCK_OR_CONFLICT


@pytest.fixture
def study(tmp_path):
    return init_chinook(tmp_path)[0]


def attempt_dir(study, attempt):
    return Path(study) / "attempts" / attempt["attempt_id"]


def observation_set_of(study, attempt):
    return json.loads((attempt_dir(study, attempt) / "observation_set.json").read_text())


def normalized_of(study, attempt):
    return [json.loads(line) for line in (attempt_dir(study, attempt) / "observations.jsonl").read_text().splitlines()]


def error_of(payload):
    error = payload["error"]
    assert set(error) == {"code", "message", "stage", "details"}
    return error


# --- AC1: the expected keys are the Cases x Repeats of the declared population -----------------------------------------


def test_a_complete_file_is_accepted_as_an_import_attempt(tmp_path, study):
    code, payload, err = import_agent(study, FIXTURE, fixture_population(tmp_path), "imp")
    assert code == 0, (payload, err)
    attempt = payload["attempt"]
    contracts.validate(attempt)
    assert (attempt["operation"], attempt["mode"], attempt["technical_status"]) == ("import", "external_unknown", "completed")
    assert attempt["item_counts"] == {"produced": 4, "failed": 0, "missing": 0}
    contracts.validate(observation_set_of(study, attempt))


def lines_with(edit):
    return lambda lines: edit([dict(line) for line in lines])


REFUSALS = {
    "duplicate": (lambda lines: [*lines, lines[0]], "EPISODE_DUPLICATE", None),
    "absent": (lambda lines: lines[1:], "POPULATION_EPISODE_ABSENT", None),
    "unknown_case": (lambda lines: [*lines, {**lines[0], "case_id": "Z99"}], "EPISODE_OUTSIDE_POPULATION", "unknown_case"),
    "other_partition": (lambda lines: [*lines, {**lines[0], "case_id": "E01"}], "EPISODE_OUTSIDE_POPULATION", "other_partition"),
    "repeat_out_of_range": (lambda lines: [*lines, {**lines[0], "repeat": 1}], "EPISODE_OUTSIDE_POPULATION", "repeat_out_of_range"),
    "case_not_in_population": (lambda lines: [*lines, {**lines[0], "case_id": "D02"}], "EPISODE_OUTSIDE_POPULATION", "not_in_population"),
    "unknown_status": (lambda lines: [{**lines[0], "observation_status": "done"}, *lines[1:]], "OBSERVATION_STATUS_UNKNOWN", None),
    "no_status": (lambda lines: [{k: v for k, v in lines[0].items() if k != "observation_status"}, *lines[1:]], "OBSERVATION_STATUS_UNKNOWN", None),
    "produced_without_answer": (lambda lines: [{k: v for k, v in lines[0].items() if k != "final_answer"}, *lines[1:]], "PRODUCED_WITHOUT_ANSWER", None),
    "both_answers": (lambda lines: [{**lines[0], "raw_answer": "{}"}, *lines[1:]], "ANSWER_AMBIGUOUS", None),
    "bad_repeat": (lambda lines: [{**lines[0], "repeat": "0"}, *lines[1:]], "LINE_FIELD_INVALID", None),
    "negative_repeat": (lambda lines: [{**lines[0], "repeat": -1}, *lines[1:]], "LINE_FIELD_INVALID", None),
    "bad_final_answer": (lambda lines: [{**lines[0], "final_answer": [1]}, *lines[1:]], "LINE_FIELD_INVALID", None),
    "bad_raw_answer": (lambda lines: [{k: v for k, v in {**lines[0], "raw_answer": 3}.items() if k != "final_answer"}, *lines[1:]], "LINE_FIELD_INVALID", None),
    "bad_trace": (lambda lines: [{**lines[0], "trace": "steps"}, *lines[1:]], "LINE_FIELD_INVALID", None),
}


@pytest.mark.parametrize("name", sorted(REFUSALS))
def test_each_fault_of_the_expected_keys_is_refused_with_its_own_code_exit_2_and_publishes_no_observation_set(tmp_path, study, name):
    edit, code_expected, problem = REFUSALS[name]
    source = write_lines(tmp_path / "answers.jsonl", edit(fixture_lines()))
    before = snapshot(study)
    code, payload, _ = import_agent(study, source, fixture_population(tmp_path), "imp")
    assert code == EXIT_INVALID_INPUT == 2
    error = error_of(payload)
    assert (error["code"], error["stage"]) == (code_expected, "import")
    if problem is not None:
        assert error["details"]["problem"] == problem
    assert snapshot(study) == before  # no Attempt, no Observation set


def test_a_line_that_is_not_json_is_refused_with_its_line_number(tmp_path, study):
    source = tmp_path / "answers.jsonl"
    source.write_text(FIXTURE.read_text().replace("\n", "\n{not json\n", 1), encoding="utf-8")
    code, payload, _ = import_agent(study, source, fixture_population(tmp_path), "imp")
    assert (code, error_of(payload)["code"], error_of(payload)["details"]["line"]) == (2, "LINE_NOT_JSON", 2)


def test_a_json_line_that_is_not_an_object_is_refused(tmp_path, study):
    source = tmp_path / "answers.jsonl"
    source.write_text("[1, 2]\n", encoding="utf-8")
    code, payload, _ = import_agent(study, source, fixture_population(tmp_path), "imp")
    assert (code, error_of(payload)["code"]) == (2, "LINE_NOT_AN_OBJECT")


def test_a_non_finite_number_in_a_line_is_not_json_and_is_refused(tmp_path, study):
    source = tmp_path / "answers.jsonl"
    source.write_text('{"case_id": "D01", "repeat": 0, "observation_status": "failed", "x": NaN}\n', encoding="utf-8")
    code, payload, _ = import_agent(study, source, fixture_population(tmp_path), "imp")
    assert (code, error_of(payload)["code"]) == (2, "LINE_NOT_JSON")


def test_the_population_comes_from_its_file_and_never_from_the_answers(tmp_path, study):
    # the file holds a Case the population does not list: it cannot add an Episode to it
    population = episodes_file(tmp_path, [("D01", 0), ("D03", 0), ("D07", 0)])
    code, payload, _ = import_agent(study, FIXTURE, population, "imp")
    assert (code, error_of(payload)["code"]) == (2, "EPISODE_OUTSIDE_POPULATION")


@pytest.mark.parametrize(
    "content, code_expected",
    [
        ('["D01"]', "POPULATION_INVALID"),
        ('{"episodes": []}', "POPULATION_INVALID"),
        ('{"episodes": [{"case_id": "D01"}]}', "POPULATION_INVALID"),
        ('{"episodes": [{"case_id": "D01", "repeat": 0}, {"case_id": "D01", "repeat": 0}]}', "POPULATION_INVALID"),
        ('{"episodes": [{"case_id": "D01", "repeat": -1}]}', "POPULATION_INVALID"),
        ('{"episodes": [{"case_id": "D01", "repeat": 0}], "extra": 1}', "POPULATION_INVALID"),
        ('{"episodes": [{"case_id": "Z99", "repeat": 0}]}', "POPULATION_CASE_UNKNOWN"),
        ('{"episodes": [{"case_id": "D01", "repeat": 0}, {"case_id": "E01", "repeat": 0}]}', "POPULATION_MIXED_PARTITIONS"),
    ],
)
def test_a_population_that_is_not_the_expected_Episodes_of_one_Partition_is_refused(tmp_path, study, content, code_expected):
    population = tmp_path / "population.json"
    population.write_text(content, encoding="utf-8")
    before = snapshot(study)
    code, payload, _ = import_agent(study, FIXTURE, population, "imp")
    assert (code, error_of(payload)["code"], error_of(payload)["stage"]) == (2, code_expected, "import")
    assert snapshot(study) == before


@pytest.mark.parametrize("which", ["source", "population"])
def test_a_file_that_cannot_be_read_is_refused(tmp_path, study, which):
    gone = tmp_path / "gone"
    args = (gone, fixture_population(tmp_path)) if which == "source" else (FIXTURE, gone)
    code, payload, _ = import_agent(study, *args, "imp")
    assert (code, error_of(payload)["code"], which in error_of(payload)["details"]) == (2, f"{which.upper()}_NOT_FOUND", True)


def test_a_source_that_is_not_utf8_or_is_a_serialized_object_is_refused(tmp_path, study):
    latin = tmp_path / "latin.jsonl"
    latin.write_bytes(b'{"case_id": "\xe9"}\n')
    code, payload, _ = import_agent(study, latin, fixture_population(tmp_path), "imp")
    assert (code, error_of(payload)["code"]) == (2, "SOURCE_NOT_UTF8")
    pickled = tmp_path / "answers.pkl"
    pickled.write_bytes(b"\x80\x04N.")
    code, payload, _ = import_agent(study, pickled, fixture_population(tmp_path), "imp")
    assert (code, error_of(payload)["code"]) == (2, "SOURCE_SERIALIZED")


def test_a_failed_and_a_missing_line_stand_for_an_episode_without_an_answer_and_the_import_is_completed(tmp_path, study):
    lines = fixture_lines()
    lines[1] = {"case_id": "D03", "repeat": 0, "observation_status": "failed"}
    lines[2] = {"case_id": "D07", "repeat": 0, "observation_status": "missing"}
    source = write_lines(tmp_path / "answers.jsonl", lines)
    code, payload, err = import_agent(study, source, fixture_population(tmp_path), "imp")
    assert code == 0, (payload, err)
    attempt = payload["attempt"]
    assert (attempt["technical_status"], attempt["item_counts"]) == ("completed", {"produced": 2, "failed": 1, "missing": 1})
    by_case = {line["case_id"]: line for line in normalized_of(study, attempt)}
    assert [by_case[c]["status"] for c in FIXTURE_CASES] == ["produced", "failed", "missing", "produced"]


# --- AC2 and Tightened C, A2: what is kept and what is known ----------------------------------------------------------


def test_the_import_keeps_the_original_file_its_report_and_the_normalized_observations(tmp_path, study):
    population = fixture_population(tmp_path)
    _, payload, _ = import_agent(study, FIXTURE, population, "imp")
    attempt = payload["attempt"]
    folder = attempt_dir(study, attempt)
    kept = folder / "source" / FIXTURE.name
    assert kept.read_bytes() == FIXTURE.read_bytes()
    refs = {ref["role"]: ref for ref in [*attempt["input_refs"], *attempt["output_refs"]]}
    assert refs["import_source"]["sha256"] == sha256(FIXTURE)
    assert refs["import_population"]["sha256"] == sha256(population)
    report = json.loads((folder / "validation_report.json").read_text())
    assert (report["source_sha256"], report["lines_read"], report["population_episodes"]) == (sha256(FIXTURE), 4, 4)
    assert all(check["result"] == "passed" for check in report["checks"])
    assert [set(line) >= {"case_id", "repeat", "status", "answer_given_as"} for line in normalized_of(study, attempt)] == [True] * 4


def test_import_time_is_apart_from_generation_time_and_every_field_has_an_origin(tmp_path, study):
    _, payload, _ = import_agent(study, FIXTURE, fixture_population(tmp_path), "imp")
    attempt = payload["attempt"]
    config = attempt["effective_config"]
    assert config["import_time"] == attempt["started_at"]
    producer = config["producer"]
    assert set(producer) == {"model", "generation_time", "historical_protocol", "tool_use", "saw_public_check", "file_origin", "file_mode"}
    assert producer["generation_time"] == {"value": None, "origin": "unknown"}
    assert {name: entry["origin"] for name, entry in producer.items()} == {
        "model": "unknown", "generation_time": "unknown", "historical_protocol": "unknown", "tool_use": "unknown",
        "saw_public_check": "unknown", "file_origin": "declared", "file_mode": "declared",
    }
    observation_set = observation_set_of(study, attempt)
    assert observation_set["provenance"]["import_time"] == config["import_time"]
    assert set(observation_set["unknown_fields"]) == {"model", "generation_time", "historical_protocol", "tool_use", "saw_public_check"}


def test_what_the_file_establishes_is_declared_and_never_verified_and_conflicting_lines_stay_unknown(tmp_path, study):
    lines = fixture_lines()
    for line in lines:
        line["producer"] = {"model": "acme-1", "generation_time": "2026-11-01T10:00:00+00:00", "tool_use": "none"}
    lines[0]["producer"]["tool_use"] = "sql"  # the lines disagree on tool_use
    source = write_lines(tmp_path / "answers.jsonl", lines)
    _, payload, _ = import_agent(study, source, fixture_population(tmp_path), "imp")
    producer = payload["attempt"]["effective_config"]["producer"]
    assert producer["model"] == {"value": "acme-1", "origin": "declared"}
    assert producer["generation_time"] == {"value": "2026-11-01T10:00:00+00:00", "origin": "declared"}
    assert producer["tool_use"] == {"value": None, "origin": "unknown"}
    assert producer["saw_public_check"] == {"value": None, "origin": "unknown"}
    assert payload["attempt"]["effective_config"]["model"] == "acme-1"
    assert "verified" not in json.dumps(payload["attempt"])


def test_no_record_states_that_the_answers_were_produced_independently(tmp_path, study):
    _, payload, _ = import_agent(study, FIXTURE, fixture_population(tmp_path), "imp")
    folder = attempt_dir(study, payload["attempt"])
    for path in [p for p in folder.rglob("*") if p.is_file() and p.parent.name != "source"]:
        assert "independent" not in path.read_text(encoding="utf-8").lower(), path


def test_the_mode_the_file_states_is_a_declared_field_never_the_imports_mode(tmp_path, study):
    _, payload, _ = import_agent(study, FIXTURE, fixture_population(tmp_path), "imp")
    attempt = payload["attempt"]
    assert attempt["mode"] == "external_unknown" and attempt["operation"] == "import"
    assert attempt["effective_config"]["producer"]["file_mode"] == {"value": "scripted_fixture", "origin": "declared"}
    assert observation_set_of(study, attempt)["mode"] == "external_unknown"


# --- AC4: the kit's authored fixture ----------------------------------------------------------------------------------


def test_the_kits_authored_fixture_imports_with_its_origin_declared_and_never_as_a_live_run(tmp_path, study):
    _, payload, _ = import_agent(study, FIXTURE, fixture_population(tmp_path), "imp")
    attempt = payload["attempt"]
    assert attempt["effective_config"]["producer"]["file_origin"] == {"value": "authored_fixture", "origin": "declared"}
    observation_set = observation_set_of(study, attempt)
    assert observation_set["provenance"]["file_origin"] == {"value": "authored_fixture", "origin": "declared"}
    written = "".join(p.read_text(encoding="utf-8") for p in attempt_dir(study, attempt).rglob("*") if p.is_file() and p.parent.name != "source")
    for forbidden in ("llm_live", "anthropic", "openai", "claude"):
        assert forbidden not in written.lower(), forbidden


def test_the_two_forms_of_answer_are_recorded_as_given(tmp_path, study):
    lines = fixture_lines()
    lines[0] = {**{k: v for k, v in lines[0].items() if k != "final_answer"}, "raw_answer": json.dumps(fixture_lines()[0]["final_answer"])}
    source = write_lines(tmp_path / "answers.jsonl", lines)
    _, payload, _ = import_agent(study, source, fixture_population(tmp_path), "imp")
    given = {line["case_id"]: line["answer_given_as"] for line in normalized_of(study, payload["attempt"])}
    assert given == {"D01": "raw_answer", "D03": "final_answer", "D07": "final_answer", "D08": "final_answer"}


# --- Tightened H: nothing is executed ---------------------------------------------------------------------------------


def test_nothing_in_the_file_is_executed_or_deserialised_as_code(tmp_path, study, monkeypatch):
    import builtins

    called = []
    monkeypatch.setattr(builtins, "eval", lambda *a, **k: called.append("eval"))
    monkeypatch.setattr(builtins, "exec", lambda *a, **k: called.append("exec"))
    lines = fixture_lines()
    lines[0]["trace"] = [{"kind": "tool_call", "function": "__import__('os').system('true')", "arguments": {"x": "exec(1)"}}]
    lines[1]["raw_answer"] = "__import__('os').system('true')"
    del lines[1]["final_answer"]
    source = write_lines(tmp_path / "answers.jsonl", lines)
    code, payload, err = import_agent(study, source, fixture_population(tmp_path), "imp")
    assert code == 0, (payload, err)
    assert called == []
    kept = [line for line in normalized_of(study, payload["attempt"]) if line["case_id"] == "D03"][0]
    assert kept["raw_answer"] == "__import__('os').system('true')"  # kept as data


# --- the request identity (AC9, Tightened I2) --------------------------------------------------------------------------


def test_request_id_is_required_and_not_empty(tmp_path, study):
    population = fixture_population(tmp_path)
    code, payload, _ = run_json("import", "agent", "--study", study, "--source", FIXTURE, "--population", population)
    assert (code, error_of(payload)["code"]) == (EXIT_INVALID_INPUT, "INVALID_ARGUMENTS")
    code, payload, _ = import_agent(study, FIXTURE, population, "")
    assert (code, error_of(payload)["code"]) == (EXIT_INVALID_INPUT, "REQUEST_ID_EMPTY")


def test_the_identity_holds_every_element_with_its_value_or_unknown(tmp_path, study):
    population = fixture_population(tmp_path)
    _, payload, _ = import_agent(study, FIXTURE, population, "imp")
    attempt = payload["attempt"]
    identity = requests.identity(attempt["effective_config"], attempt["code_environment"])
    assert set(identity) == set(requests.ELEMENTS)
    assert (identity["command"], identity["workload"], identity["mode"], identity["partition"]) == ("import agent", "chinook", "external_unknown", "dev")
    assert (identity["configuration"], identity["model"], identity["repeats"]) == ("unknown", "unknown", 1)
    digests = identity["input_digests"]
    assert (digests["source"], digests["population"]) == (sha256(FIXTURE), sha256(population))
    assert digests["dataset"] == sha256(Path(study) / "datasets" / "Chinook_Sqlite.sqlite")


def test_the_same_request_returns_the_recorded_import_and_validates_and_writes_nothing(tmp_path, study, monkeypatch):
    from hypotrail.agentic import imports

    population = fixture_population(tmp_path)
    _, first, _ = import_agent(study, FIXTURE, population, "imp")
    before = snapshot(study)

    def never(*args, **kwargs):
        raise AssertionError("the source was validated again")

    for name in ("_checked_lines", "_checked_population"):
        monkeypatch.setattr(imports, name, never)
    code, again, err = import_agent(study, FIXTURE, population, "imp")
    assert code == 0, (again, err)
    assert again["replayed"] is True and again["attempt"] == first["attempt"]
    assert snapshot(study) == before


@pytest.mark.parametrize("what", ["source", "population"])
def test_the_same_request_id_with_another_request_is_request_conflict_exit_6(tmp_path, study, what):
    population = fixture_population(tmp_path)
    _, first, _ = import_agent(study, FIXTURE, population, "imp")
    before = snapshot(study)
    if what == "source":
        other = write_lines(tmp_path / "other.jsonl", [{**line, "final_answer": line["final_answer"]} for line in reversed(fixture_lines())])
        args = (other, population)
    else:
        args = (FIXTURE, episodes_file(tmp_path, [(c, 0) for c in FIXTURE_CASES[:3]], name="other-population.json"))
    code, payload, _ = import_agent(study, *args, "imp")
    assert code == EXIT_LOCK_OR_CONFLICT == 6
    error = error_of(payload)
    assert error["code"] == "REQUEST_CONFLICT" and error["details"]["attempt_id"] == first["attempt"]["attempt_id"]
    assert error["details"]["differs"] == ["input_digests"]
    assert snapshot(study) == before


def test_a_request_id_taken_by_another_file_is_a_conflict_even_when_the_new_file_holds_no_answer(tmp_path, study):
    population = fixture_population(tmp_path)
    import_agent(study, FIXTURE, population, "imp")
    other = write_lines(tmp_path / "answers-2.jsonl", [{"case_id": c, "repeat": 0, "observation_status": "missing"} for c in FIXTURE_CASES])
    code, payload, _ = import_agent(study, other, population, "imp")
    assert (code, error_of(payload)["code"]) == (EXIT_LOCK_OR_CONFLICT, "REQUEST_CONFLICT")


# --- the guards around the Study ---------------------------------------------------------------------------------------


def test_a_changed_protocol_is_refused_before_anything_is_written(tmp_path, study):
    from _chinook_helpers import chinook_examples

    examples = chinook_examples(tmp_path)
    references = examples / "chinook" / "references" / "chinook-references.jsonl"
    references.write_bytes(references.read_bytes().replace(b"[[3503]]", b"[[3504]]", 1))
    before = snapshot(study)
    code, payload, _ = import_agent(study, FIXTURE, fixture_population(tmp_path), "imp", "--examples-dir", examples)
    assert (code, error_of(payload)["code"]) == (EXIT_INTEGRITY_REFUSED, "PROTOCOL_CHANGED")
    assert snapshot(study) == before


def test_an_import_agent_into_a_study_of_the_other_track_is_refused(tmp_path):
    from _study_helpers import init_study

    bike, _ = init_study(tmp_path)
    code, payload, _ = import_agent(bike, FIXTURE, fixture_population(tmp_path), "imp")
    assert (code, error_of(payload)["code"]) == (EXIT_INVALID_INPUT, "UNSUPPORTED_CAPABILITY")


def test_import_ml_into_a_chinook_study_is_refused(tmp_path, study):
    from _import_helpers import import_ml

    code, payload, _ = import_ml(study, FIXTURE, tmp_path / "m.json", fixture_population(tmp_path), "imp")
    assert (code, error_of(payload)["code"]) == (EXIT_INVALID_INPUT, "UNSUPPORTED_CAPABILITY")


def test_an_import_of_public_check_cases_is_recorded_and_its_assessment_is_refused_later(tmp_path, study):
    keys = [("E01", 0), ("E11", 0)]
    source = write_lines(tmp_path / "answers.jsonl", [{"case_id": c, "repeat": r, "observation_status": "missing"} for c, r in keys])
    code, payload, err = import_agent(study, source, episodes_file(tmp_path, keys), "imp")
    assert code == 0, (payload, err)
    assert payload["attempt"]["effective_config"]["partition"] == "public_check"


def test_the_observations_are_canonical_and_the_same_for_a_permuted_file(tmp_path, study):
    population = fixture_population(tmp_path)
    _, first, _ = import_agent(study, FIXTURE, population, "a")
    permuted = write_lines(tmp_path / "permuted.jsonl", list(reversed(fixture_lines())))
    _, second, _ = import_agent(study, permuted, population, "b")
    one = (attempt_dir(study, first["attempt"]) / "observations.jsonl").read_bytes()
    two = (attempt_dir(study, second["attempt"]) / "observations.jsonl").read_bytes()
    assert one == two
    assert all(canonical.is_canonical(line.encode()) for line in one.decode().splitlines())


def test_run_ml_in_a_chinook_study_is_refused(study):
    from _study_helpers import run_ml

    code, payload, _ = run_ml(study, "seasonal_7", "dev", "r")
    assert (code, error_of(payload)["code"]) == (EXIT_INVALID_INPUT, "UNSUPPORTED_CAPABILITY")
