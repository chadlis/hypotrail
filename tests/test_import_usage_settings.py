"""The JSONL line's `usage`, `metadata` and `settings`, and the `chinook_prose` Workload end to end (#266).

Offline: no key is set and no provider is called. The two fixture files were written by hand (`origin: authored_fixture`).
"""

import json
import shutil
from pathlib import Path

import pytest
from _chinook_helpers import episodes_file, import_agent, write_lines
from _study_helpers import EXAMPLES, run_json

PROSE = EXAMPLES / "chinook_prose"
FIXTURES = {name: PROSE / "fixtures" / f"answers-{name}.jsonl" for name in ("concise", "verbose")}


def jsonl(path) -> list:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def prose_study(tmp_path, name="prose"):
    study = Path(tmp_path) / name
    code, payload, err = run_json("init", "--workload", "chinook_prose", "--study", study)
    assert code == 0, (payload, err)
    return study, payload["references_id"]


def line(case_id="D01", **keys) -> dict:
    return {"case_id": case_id, "repeat": 0, "observation_status": "produced", "raw_answer": "Customer 12 has 7 invoices.", **keys}


def imported(tmp_path, study, lines, name="answers"):
    source = write_lines(Path(tmp_path) / f"{name}.jsonl", lines)
    population = episodes_file(tmp_path, [(item["case_id"], item["repeat"]) for item in lines], name=f"{name}-population.json")
    return import_agent(study, source, population, name)


def observation_set_record(study, attempt) -> dict:
    return json.loads((Path(study) / "attempts" / attempt["attempt_id"] / "observation_set.json").read_text(encoding="utf-8"))


def entries(study, attempt) -> list:
    return jsonl(Path(study) / "attempts" / attempt["attempt_id"] / "observations.jsonl")


def ok(result):
    code, payload, err = result
    assert code == 0, (payload, err)
    return payload


# --- criterion 1: usage and metadata normalized ---------------------------------------------------------------------------------

KNOWN = {"a": {"tokens": 10, "latency_seconds": 0.5, "cost_usd": 0.25}, "b": {"tokens": 5, "latency_seconds": 1.0, "cost_usd": 0.5}}
ONE_COST_NULL = {"a": {"tokens": 10, "latency_seconds": 0.5, "cost_usd": 0.25}, "b": {"tokens": 5, "latency_seconds": 1.0, "cost_usd": None}}
NESTED = {"conversation": {"id": "c-1", "turns": [1, 2]}, "flag": True}

NORMALIZED = {
    "usage with every value known": (
        {"usage": KNOWN},
        {"usage": {"latency_seconds": 1.5, "tokens": 15, "cost_usd": 0.75, "by_model": KNOWN}},
    ),
    "one model's cost_usd null": (
        {"usage": ONE_COST_NULL},
        {"usage": {"latency_seconds": 1.5, "tokens": 15, "cost_usd": None, "by_model": ONE_COST_NULL}},
    ),
    "usage absent": ({}, {}),
    "metadata nested object": ({"metadata": NESTED}, {"metadata": NESTED}),
    "metadata absent": ({}, {}),
}


@pytest.mark.parametrize("case", list(NORMALIZED))
def test_a_lines_usage_and_metadata_reach_the_normalized_entry_in_the_one_usage_shape(tmp_path, case):
    keys, expected = NORMALIZED[case]
    study, _ = prose_study(tmp_path)
    attempt = ok(imported(tmp_path, study, [line(**keys)]))["attempt"]
    [entry] = entries(study, attempt)
    for key in ("usage", "metadata"):
        if key in expected:
            assert entry[key] == expected[key]
        else:
            assert key not in entry


# --- criterion 2: LINE_FIELD_INVALID for the new keys ----------------------------------------------------------------------------

# JSON writes no infinity: a non-finite number is a literal beyond the float range (`1e309`), which the strict reader of a line refuses
# as LINE_NOT_JSON before its `usage` is read; the other rows are LINE_FIELD_INVALID with their field.
MALFORMED = {
    "usage not an object": ({"usage": [1]}, ("LINE_FIELD_INVALID", "usage")),
    "a model's value not an object": ({"usage": {"a": 3}}, ("LINE_FIELD_INVALID", "usage")),
    "tokens not an integer": ({"usage": {"a": {"tokens": 1.5, "latency_seconds": 1, "cost_usd": 0}}}, ("LINE_FIELD_INVALID", "usage")),
    "a negative number": ({"usage": {"a": {"tokens": 1, "latency_seconds": -1, "cost_usd": 0}}}, ("LINE_FIELD_INVALID", "usage")),
    "a non-finite number": ({"usage": {"a": {"tokens": 1, "latency_seconds": "INFINITE", "cost_usd": 0}}}, ("LINE_NOT_JSON", None)),
    "metadata not an object": ({"metadata": "x"}, ("LINE_FIELD_INVALID", "metadata")),
}


@pytest.mark.parametrize("case", list(MALFORMED))
def test_a_malformed_usage_or_metadata_is_refused_line_field_invalid_with_its_field_and_nothing_is_published(tmp_path, case):
    keys, (expected_code, field) = MALFORMED[case]
    study, _ = prose_study(tmp_path)
    source = Path(tmp_path) / "bad.jsonl"
    source.write_text(json.dumps(line(**keys)).replace('"INFINITE"', "1e309") + "\n", encoding="utf-8")
    code, payload, err = import_agent(study, source, episodes_file(tmp_path, [("D01", 0)]), "bad")
    error = payload.get("error", {})
    assert (code, error.get("code"), error.get("details", {}).get("field")) == (2, expected_code, field), (payload, err)
    assert not list(study.glob("attempts/*"))


# --- criterion 3: settings recorded ----------------------------------------------------------------------------------------------

SCALARS = {"model": "m-1", "temperature": 0.5, "max_turns": 3, "streaming": False, "seed": None}


def two_lines(first, second) -> list:
    one, two = line("D01"), line("D02")
    if first is not None:
        one["settings"] = first
    if second is not None:
        two["settings"] = second
    return [one, two]


RECORDED = {
    "the same map with each scalar type on every line": (two_lines(SCALARS, dict(SCALARS)), {"value": SCALARS, "origin": "declared"}),
    "absent on every line": (two_lines(None, None), {"value": None, "origin": "unknown"}),
    "absent on one line": (two_lines(SCALARS, None), {"value": None, "origin": "unknown"}),
    "two lines differing": (two_lines(SCALARS, {**SCALARS, "temperature": 0.7}), {"value": None, "origin": "unknown"}),
    "two lines differing only by type, 1 and true": (two_lines({"seed": 1}, {"seed": True}), {"value": None, "origin": "unknown"}),
    "two lines differing only by type, 1 and 1.0": (two_lines({"seed": 1}, {"seed": 1.0}), {"value": None, "origin": "unknown"}),
}


@pytest.mark.parametrize("case", list(RECORDED))
def test_settings_is_declared_when_every_line_holds_the_same_map_and_unknown_otherwise(tmp_path, case):
    lines, expected = RECORDED[case]
    study, _ = prose_study(tmp_path)
    record = observation_set_record(study, ok(imported(tmp_path, study, lines))["attempt"])
    assert record["provenance"]["settings"] == expected
    assert ("settings" in record["unknown_fields"]) == (expected["origin"] == "unknown")


@pytest.mark.parametrize("settings", [{"model": {"name": "m"}}, ["model", "m"]], ids=["a nested value", "not an object"])
def test_a_malformed_settings_is_refused_line_field_invalid_with_field_settings(tmp_path, settings):
    study, _ = prose_study(tmp_path)
    code, payload, err = imported(tmp_path, study, [line(settings=settings)])
    error = payload.get("error", {})
    assert (code, error.get("code"), error.get("details", {}).get("field")) == (2, "LINE_FIELD_INVALID", "settings"), (payload, err)
    assert not list(study.glob("attempts/*"))


# --- criterion 5: the free-text Workload end to end ------------------------------------------------------------------------------


def test_chinook_prose_end_to_end_init_two_imports_two_assessments_a_descriptive_comparison_and_status(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPOTRAIL_ANTHROPIC_API_KEY", raising=False)
    study, references = prose_study(tmp_path)
    dev = [case["case_id"] for case in jsonl(PROSE / "cases" / "chinook-prose-dev.jsonl")]
    population = episodes_file(tmp_path, [(case_id, 0) for case_id in dev])
    imports, assessments = {}, {}
    for name, source in FIXTURES.items():
        imports[name] = ok(import_agent(study, source, population, f"import-{name}"))
        assessments[name] = ok(
            run_json("assess", "--study", study, "--observations", imports[name]["observation_set_id"], "--scorer", "text_facts_v1", "--references", references)
        )["assessment"]
        assert assessments[name]["primary_criterion"] == "text_facts_success"
    comparison = ok(
        run_json("compare", "--study", study, "--control", assessments["concise"]["assessment_id"], "--candidate", assessments["verbose"]["assessment_id"])
    )["comparison"]
    assert comparison["comparability"]["status"] == "descriptive_only"
    descriptive = comparison["descriptive"]
    usages = {name: [item["usage"] for item in jsonl(source)] for name, source in FIXTURES.items()}
    for side, name in (("control", "concise"), ("candidate", "verbose")):
        by_model = [value for usage in usages[name] for value in usage.values()]
        assert descriptive[side]["tokens"] == sum(value["tokens"] for value in by_model)
        assert descriptive[side]["latency_seconds"] == pytest.approx(sum(value["latency_seconds"] for value in by_model))
    assert descriptive["control"]["cost"] == pytest.approx(sum(value["cost_usd"] for usage in usages["concise"] for value in usage.values()))
    assert descriptive["candidate"]["cost"] is None
    status = ok(run_json("status", "--study", study))
    listed = json.dumps(status)
    for value in [*(i["attempt"]["attempt_id"] for i in imports.values()), *(a["assessment_id"] for a in assessments.values()), comparison["comparison_id"]]:
        assert value in listed


# --- criterion 6: no reference text in a line -----------------------------------------------------------------------------------

REFERENCE_TEXTS = {r["case_id"]: r.get("reference_text") for r in jsonl(PROSE / "references" / "chinook-prose-references.jsonl")}
FIXTURE_LINES = [(name, item) for name, source in FIXTURES.items() for item in jsonl(source)]


@pytest.mark.parametrize(("name", "item"), FIXTURE_LINES, ids=[f"{name}-{item['case_id']}" for name, item in FIXTURE_LINES])
def test_no_fixture_line_answers_its_case_with_that_cases_reference_text(name, item):
    assert item["raw_answer"] != REFERENCE_TEXTS[item["case_id"]]
    assert item["origin"] == "authored_fixture"
