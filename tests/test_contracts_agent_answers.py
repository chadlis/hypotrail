"""Consumer conformance of `agent-answers/1` (C3 of D-172 on chadlis/hypotrail#75).

The schemas and `import agent` accept the examples and refuse each invalid case as `expected.json` says. The line schema
agrees with `LINE_KEYS`, `USAGE_FIELDS` and `OUTCOMES`. No model is called.
"""

import json
from pathlib import Path

import jsonschema
import pytest
from _assess_helpers import snapshot
from _chinook_helpers import import_agent, write_lines
from _study_helpers import run_json

from hypotrail.agentic import imports

CONTRACT = Path(__file__).resolve().parents[1] / "src" / "hypotrail" / "agentic" / "contracts" / "agent-answers-1"
EXAMPLES = CONTRACT / "examples"
REFUSED = sorted(path for path in (EXAMPLES / "refused").iterdir() if path.is_dir())


def schema(name):
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


def line_problems(path: Path):
    validator = jsonschema.Draft202012Validator(schema("line.schema.json"))
    lines = [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines() if text.strip()]
    return [[error.message for error in validator.iter_errors(line)] for line in lines]


def population_problems(path: Path):
    validator = jsonschema.Draft202012Validator(schema("population.schema.json"))
    return [error.message for error in validator.iter_errors(json.loads(path.read_text(encoding="utf-8")))]


@pytest.mark.parametrize("name", ["line.schema.json", "population.schema.json"])
def test_each_schema_is_a_valid_draft_2020_12_schema_whose_id_names_its_directory(name):
    loaded = schema(name)
    jsonschema.Draft202012Validator.check_schema(loaded)
    assert loaded["$id"].endswith(f"/src/hypotrail/agentic/contracts/agent-answers-1/{name}")


def test_the_example_lines_and_population_are_accepted_and_keep_the_rules_a_schema_cannot_say():
    assert line_problems(EXAMPLES / "answers.jsonl") == [[], []]
    assert population_problems(EXAMPLES / "population.json") == []
    lines = [json.loads(text) for text in (EXAMPLES / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    episodes = json.loads((EXAMPLES / "population.json").read_text(encoding="utf-8"))["episodes"]
    assert [(line["case_id"], line["repeat"]) for line in lines] == [(e["case_id"], e["repeat"]) for e in episodes]
    assert len({json.dumps(line["settings"], sort_keys=True) for line in lines}) == 1
    assert not any("final_answer" in line for line in lines)


@pytest.mark.parametrize("case", REFUSED, ids=[path.name for path in REFUSED])
def test_each_refused_case_is_refused_by_the_line_schema(case):
    expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
    assert expected["caught_by"] == "schema" and expected["exit"] == 2
    assert any(line_problems(case / "answers.jsonl")), f"{case.name} should be refused by the line schema"
    assert population_problems(case / "population.json") == []


def test_the_line_schema_agrees_with_line_keys_usage_fields_and_outcomes():
    loaded = schema("line.schema.json")
    assert loaded["additionalProperties"] is False
    assert set(loaded["properties"]) == set(imports.LINE_KEYS)
    assert set(loaded["required"]) == {key for key, when in imports.LINE_KEYS.items() if when == imports.ALWAYS}
    assert {key for key, when in imports.LINE_KEYS.items() if when == imports.WHEN_PRODUCED} == {"raw_answer", "final_answer"}
    assert tuple(loaded["properties"]["usage"]["additionalProperties"]["required"]) == imports.USAGE_FIELDS
    assert tuple(loaded["properties"]["outcome"]["enum"]) == imports.OUTCOMES


def chinook_prose_study(tmp_path):
    study = Path(tmp_path) / "study"
    code, payload, err = run_json("init", "--workload", "chinook_prose", "--study", study)
    assert code == 0, (payload, err)
    return study


def test_import_agent_accepts_the_example_lines_and_population(tmp_path):
    code, payload, err = import_agent(chinook_prose_study(tmp_path), EXAMPLES / "answers.jsonl", EXAMPLES / "population.json", "examples")
    assert code == 0, (payload, err)


@pytest.mark.parametrize(
    ("status", "fields", "accepted"),
    [
        pytest.param("produced", {"raw_answer": "An authored answer."}, True, id="raw-answer"),
        pytest.param("produced", {"final_answer": {"summary": "An authored answer."}}, True, id="structured-answer"),
        pytest.param("produced", {}, False, id="answer-required"),
        pytest.param("missing", {}, True, id="missing-without-answer"),
        pytest.param("failed", {"trace": [{"kind": "tool"}]}, True, id="failed-with-trace"),
        pytest.param("failed", {"trace": [{}]}, False, id="trace-kind-required"),
        pytest.param("produced", {"raw_answer": "A study answer.", "outcome": "answered"}, True, id="declared-outcome"),
        pytest.param("produced", {"raw_answer": "A study answer.", "outcome": "other"}, False, id="unknown-outcome"),
        pytest.param("missing", {"usage": {"model": {"tokens": None, "latency_seconds": 1.5, "cost_usd": 0}}}, True, id="nullable-measure"),
        pytest.param("missing", {"usage": {"model": {"tokens": True, "latency_seconds": 1.5, "cost_usd": 0}}}, False, id="boolean-tokens"),
        pytest.param("missing", {"metadata": {"details": {"route": "fixture"}}}, True, id="nested-metadata"),
        pytest.param("missing", {"metadata": None}, False, id="metadata-object"),
    ],
)
def test_the_line_schema_and_import_agent_agree_on_synthetic_line_variants(tmp_path, status, fields, accepted):
    episode = {"case_id": "D01", "repeat": 0}
    line = {**episode, "observation_status": status, **fields}
    source = write_lines(tmp_path / "answers.jsonl", [line])
    population = tmp_path / "population.json"
    population.write_text(json.dumps({"episodes": [episode]}), encoding="utf-8")
    study = chinook_prose_study(tmp_path)

    schema_accepts = jsonschema.Draft202012Validator(schema("line.schema.json")).is_valid(line)
    before = snapshot(study)
    code, payload, err = import_agent(study, source, population, "agreement")
    assert schema_accepts == (code == 0), (payload, err)
    assert schema_accepts is accepted
    if not accepted:
        assert code == 2 and payload["ok"] is False
        assert snapshot(study) == before


def test_legacy_unknown_fields_are_accepted_as_source_data_without_changing_provenance(tmp_path):
    lines = [json.loads(text) for text in (EXAMPLES / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    lines[0]["unknown_fields"] = ["settings", "fixture-only-provenance-key"]
    source = write_lines(tmp_path / "legacy.jsonl", lines)
    assert line_problems(source) == [[], []]

    study = chinook_prose_study(tmp_path)
    code, payload, err = import_agent(study, source, EXAMPLES / "population.json", "legacy")
    assert code == 0, (payload, err)
    attempt = study / "attempts" / payload["attempt"]["attempt_id"]
    assert (attempt / "source" / source.name).read_bytes() == source.read_bytes()
    entries = [json.loads(line) for line in (attempt / "observations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all("unknown_fields" not in entry for entry in entries)
    observations = json.loads((attempt / "observation_set.json").read_text(encoding="utf-8"))
    assert observations["provenance"]["settings"]["origin"] == "declared"
    assert not {"settings", "fixture-only-provenance-key"} & set(observations["unknown_fields"])


@pytest.mark.parametrize("legacy", [None, ["model", 2]])
def test_a_malformed_legacy_unknown_fields_value_is_refused_by_schema_and_cli(tmp_path, legacy):
    lines = [json.loads(text) for text in (EXAMPLES / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    lines[0]["unknown_fields"] = legacy
    source = write_lines(tmp_path / "malformed.jsonl", lines)
    assert line_problems(source)[0]
    study = chinook_prose_study(tmp_path)
    before = snapshot(study)
    code, payload, _ = import_agent(study, source, EXAMPLES / "population.json", "refused")
    assert (code, payload["error"]["code"], payload["error"]["details"]) == (2, "LINE_FIELD_INVALID", {"line": 1, "field": "unknown_fields"})
    assert snapshot(study) == before


@pytest.mark.parametrize("case", REFUSED, ids=[path.name for path in REFUSED])
def test_import_agent_refuses_each_refused_case_with_the_code_expected_json_names(tmp_path, case):
    expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
    study = chinook_prose_study(tmp_path)
    before = snapshot(study)
    code, payload, err = import_agent(study, case / "answers.jsonl", case / "population.json", "refused")
    assert (code, payload.get("error", {}).get("code")) == (expected["exit"], expected["code"]), (payload, err)
    assert snapshot(study) == before


def test_import_agent_replays_a_historical_import_with_an_unknown_line_key_without_writing(tmp_path, monkeypatch):
    study = chinook_prose_study(tmp_path)
    case = EXAMPLES / "refused" / "unknown-key"
    files = (case / "answers.jsonl", case / "population.json")
    with monkeypatch.context() as patch:
        patch.setattr(imports, "LINE_KEYS", {**imports.LINE_KEYS, "reference": imports.OPTIONAL})
        code, original, err = import_agent(study, *files, "legacy")
        assert code == 0, (original, err)

    before = snapshot(study)
    code, replay, err = import_agent(study, *files, "legacy")
    assert code == 0 and replay == {**original, "replayed": True}, (replay, err)
    refused, payload, _ = import_agent(study, *files, "new")
    assert (refused, payload.get("error", {}).get("code")) == (2, "LINE_KEY_UNKNOWN")
    assert snapshot(study) == before
