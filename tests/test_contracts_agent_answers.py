"""Consumer conformance of `agent-answers/1` (C3 of D-172 on chadlis/hypotrail#75).

The schemas and `import agent` accept the examples and refuse each invalid case as `expected.json` says. The line schema
agrees with `LINE_KEYS`, `USAGE_FIELDS` and `OUTCOMES`. No model is called.
"""

import json
from pathlib import Path

import jsonschema
import pytest
from _assess_helpers import snapshot
from _chinook_helpers import import_agent
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
