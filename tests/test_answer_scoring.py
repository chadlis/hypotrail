"""Ticket #18: the scoring function, rescoring a kept log, and scorer crash vs execution failure."""

import builtins
import copy
import json
import math
import os
import sqlite3
from pathlib import Path

import pytest

from _agent_helpers import CASES, DATABASE, REFERENCES, WORKLOAD, ScriptedModel, read_jsonl

from inspect_ai.scorer import Score, Target, accuracy, scorer
from inspect_ai.solver import TaskState

from hypotrail.agentic import cases as case_module
from hypotrail.agentic import projection, rescore, runner, sql_tool
from hypotrail.core import answer_scoring

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "examples" / "chinook" / "schemas" / "table-answer.schema.json").read_text())
REFS = {r["case_id"]: r for r in read_jsonl(REFERENCES)}
SPIKE = ["D03", "D05"]


def spike_cases():
    return case_module.load_cases(CASES, SPIKE)


def correct_answer(case_id):
    ref = REFS[case_id]
    return {
        "status": ref["status"],
        "reason_code": ref["reason_code"],
        "columns": list(ref["columns"]),
        "rows": copy.deepcopy(ref["rows"]),
        "unit": ref["unit"],
        "evidence": [],
    }


def score(answer, case_id="D05", reference=None):
    text = answer if isinstance(answer, str) else json.dumps(answer)
    return answer_scoring.score_answer(text, reference or REFS[case_id])


# --- the scoring function, both ways ----------------------------------------------


@pytest.mark.parametrize("case_id", ["D03", "D05", "D07", "D08", "E10"])
def test_a_correct_answer_scores_correct_on_every_component(case_id):
    verdict = score(correct_answer(case_id), case_id)
    assert verdict["correct"] is True
    assert verdict["components"] == {
        "status": True,
        "reason_code": True,
        "columns": True,
        "rows": True,
        "unit": True,
    }


@pytest.mark.parametrize(
    "component,mutate",
    [
        ("status", lambda a: a.update(status="needs_clarification")),
        ("reason_code", lambda a: a.update(reason_code="field_not_available")),
        ("columns", lambda a: a.update(columns=list(reversed(a["columns"])))),
        ("columns", lambda a: a.update(columns=["artist", "album_count"])),
        ("rows", lambda a: a["rows"][0].__setitem__(1, 22)),
        ("rows", lambda a: a.update(rows=list(reversed(a["rows"])))),
        ("rows", lambda a: a["rows"].append(["Extra", 1])),
        ("rows", lambda a: a.update(rows=a["rows"][:2])),
        ("unit", lambda a: a.update(unit="ms")),
    ],
)
def test_an_answer_wrong_in_one_component_scores_incorrect_on_that_component(component, mutate):
    answer = correct_answer("D05")
    mutate(answer)
    verdict = score(answer, "D05")
    assert verdict["correct"] is False
    assert verdict["components"][component] is False


def test_no_string_to_number_conversion_and_no_bool_for_int():
    answer = correct_answer("D03")
    answer["rows"] = [["1297"]]
    assert score(answer, "D03")["components"]["rows"] is False
    answer["rows"] = [[True]]
    ref = {**REFS["D03"], "rows": [[1]]}
    assert score(answer, reference=ref)["components"]["rows"] is False


def test_null_stays_null():
    ref = {**REFS["D03"], "rows": [[None]]}
    assert score({**correct_answer("D03"), "rows": [[None]]}, reference=ref)["correct"] is True
    assert score({**correct_answer("D03"), "rows": [[0]]}, reference=ref)["correct"] is False


def test_non_finite_numbers_are_refused():
    ref = {**REFS["D03"], "rows": [[1297]]}
    for token in ("NaN", "Infinity", "-Infinity"):
        text = (
            '{"status": "answered", "reason_code": null, "columns": ["track_count"], '
            f'"rows": [[{token}]], "unit": "count", "evidence": []}}'
        )
        assert score(text, reference=ref)["correct"] is False


def test_the_absolute_tolerance_of_the_reference_is_applied():
    ref = REFS["E08"]
    assert ref["numeric_absolute_tolerance"] == 0.005

    def with_value(value):
        return {**correct_answer("E08"), "rows": [[value]]}

    assert score(with_value(283910.04), reference=ref)["correct"] is True
    assert score(with_value(283910.045), reference=ref)["correct"] is True
    assert score(with_value(283910.0451), reference=ref)["correct"] is False
    assert score(with_value(283910.036), reference=ref)["correct"] is True
    assert score(with_value(283910.03), reference=ref)["correct"] is False
    # other numbers are exact: tolerance 0
    assert score({**correct_answer("D03"), "rows": [[1298]]}, "D03")["correct"] is False


def test_an_answer_that_is_not_a_json_object_is_incorrect_without_looking_for_a_number():
    for text in ("The answer is 1297.", "```json\n{}\n```", "[1297]", "", "null"):
        verdict = score(text, "D03")
        assert verdict["correct"] is False
        assert verdict["parsed"] is False


@pytest.mark.parametrize("field", ["status", "reason_code", "columns", "rows", "unit", "evidence"])
def test_an_answer_missing_a_required_field_is_malformed_even_when_the_reference_holds_null(field):
    answer = correct_answer("D03")
    del answer[field]
    # null in the Reference: a missing field, read as None, would otherwise match it
    reference = {**REFS["D03"], "reason_code": None, "unit": None}
    verdict = score(answer, reference=reference)
    assert verdict["parsed"] is False
    assert verdict["correct"] is False
    assert not any(verdict["components"].values())


def test_a_present_null_is_not_a_missing_field():
    reference = {**REFS["D03"], "reason_code": None, "unit": None}
    answer = {**correct_answer("D03"), "reason_code": None, "unit": None}
    assert score(answer, reference=reference)["correct"] is True


def test_a_missing_answer_is_incorrect():
    assert answer_scoring.score_answer(None, REFS["D03"])["correct"] is False


# --- #58 T1, T2', T3: the one JSON object an answer contains ---------------------------


OBJ = json.dumps({"a": 1, "b": {"c": [1, 2]}})
OTHER = json.dumps({"d": 2})


@pytest.mark.parametrize(
    "text",
    [
        "Prose before. " + OBJ,
        OBJ + " Prose after.",
        "```json\n" + OBJ + "\n```",
        "Before.\n\n" + OBJ + "\n\nAfter.",
        "[" + OBJ + "]",
        "A {stray brace} in prose, then " + OBJ,
    ],
)
def test_exactly_one_embedded_object_is_found_and_returned_as_its_own_text(text):
    assert answer_scoring.single_embedded_object(text) == OBJ


@pytest.mark.parametrize(
    "text",
    [
        '{"status": NaN, "x": ' + OBJ + "}",
        "A stray { in prose, then " + OBJ,
        "Prices are in {USD. " + OBJ,
        '{"truncated": [1, 2 then ' + OBJ,
        '{"status": "answered", "x": ' + OBJ,
        'He wrote "{" then ' + OBJ,
    ],
)
def test_a_failed_read_skips_only_its_brace_so_a_later_object_still_counts(text):
    assert answer_scoring.single_embedded_object(text) == OBJ


def test_a_failed_read_does_not_hide_a_nested_object_it_is_the_one_candidate():
    assert answer_scoring.single_embedded_object('{"status": NaN, "x": {"a": 1}}') == '{"a": 1}'


def test_a_balanced_stray_brace_pair_before_the_object_is_skipped():
    assert answer_scoring.single_embedded_object("Voir {approximatif} puis " + OBJ) == OBJ


def test_the_finder_returns_the_decoded_object_with_its_text():
    assert answer_scoring.find_embedded_object("x " + OBJ + " y") == (OBJ, json.loads(OBJ))
    assert answer_scoring.find_embedded_object("none") is None


def test_an_object_nested_in_the_candidate_is_not_another_candidate():
    assert answer_scoring.single_embedded_object("x " + OBJ) == OBJ  # OBJ holds a nested object


@pytest.mark.parametrize(
    "text",
    [
        "",
        "The answer is 1297.",
        "1297",
        '"a string"',
        "[1297]",
        "[1, [2, 3]]",
        "{not json}",
        '{"truncated": [1, 2',
        '{"rows": [[NaN]]}',
        '{"rows": [[Infinity]]}',
        '{"rows": [[-Infinity]]}',
    ],
)
def test_no_object_means_nothing_is_found(text):
    assert answer_scoring.single_embedded_object(text) is None


@pytest.mark.parametrize(
    "text",
    [
        OBJ + " " + OTHER,
        "```json\n" + OBJ + "\n" + OTHER + "\n```",
        "```json\n" + OBJ + "\n```\nthen\n```json\n" + OTHER + "\n```",
        OBJ + "\n" + OBJ,
        "[" + OBJ + ", " + OBJ + "]",
    ],
)
def test_two_objects_anywhere_mean_nothing_is_found(text):
    assert answer_scoring.single_embedded_object(text) is None


def test_a_value_that_is_not_text_finds_nothing():
    assert answer_scoring.single_embedded_object(None) is None
    assert answer_scoring.single_embedded_object(OBJ.encode()) is None


def test_parse_answer_still_reads_only_an_answer_that_is_exactly_one_object():
    assert answer_scoring.parse_answer(OBJ) == json.loads(OBJ)
    for text in ("x " + OBJ, "```json\n" + OBJ + "\n```", "[" + OBJ + "]"):
        assert answer_scoring.parse_answer(text) is None


# --- check 2: rescoring a kept log calls neither the model nor the tools ----------


@pytest.fixture
def kept_log(tmp_path):
    script = ScriptedModel(spike_cases())
    return runner.run_episodes(
        spike_cases(),
        workload=WORKLOAD,
        configuration="plain",
        model=runner.mock_model(script),
        repeats=2,
        log_dir=tmp_path / "logs",
    )


def _forbid(monkeypatch):
    calls = []

    def fail(name):
        def inner(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"{name} was called during rescoring")

        return inner

    from inspect_ai.model import Model

    monkeypatch.setattr(Model, "generate", fail("Model.generate"))
    monkeypatch.setattr(sql_tool, "run_query", fail("run_query"))
    monkeypatch.setattr(sql_tool, "open_sqlite_readonly", fail("open_sqlite_readonly"))
    monkeypatch.setattr(sqlite3, "connect", fail("sqlite3.connect"))

    real_open, real_os_open = builtins.open, os.open

    def guarded_open(file, *args, **kwargs):
        if "Chinook_Sqlite" in os.fspath(file):
            calls.append("open(chinook)")
            raise AssertionError("the Chinook file was opened during rescoring")
        return real_open(file, *args, **kwargs)

    def guarded_os_open(path, *args, **kwargs):
        if "Chinook_Sqlite" in os.fspath(path):
            calls.append("os.open(chinook)")
            raise AssertionError("the Chinook file was opened during rescoring")
        return real_os_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(os, "open", guarded_os_open)
    return calls


def test_rescoring_a_kept_log_twice_gives_identical_verdicts_and_calls_nothing(
    kept_log, monkeypatch
):
    expected = [(c, r) for c in SPIKE for r in (0, 1)]
    calls = _forbid(monkeypatch)

    first = rescore.rescore_log(kept_log, REFS, schema=SCHEMA, expected=expected, workload=WORKLOAD)
    second = rescore.rescore_log(kept_log, REFS, schema=SCHEMA, expected=expected, workload=WORKLOAD)

    assert first == second
    assert [(v["case_id"], v["repeat"]) for v in first] == expected
    assert all(
        {c["name"]: c["score"] for c in v["criteria"]} == {
                "exact_table": True,
                "format_valid": True,
                "evidence_link_valid": True,
                "contract_success": True,
            }
        for v in first
    )
    assert all(v["scorer"]["name"] == "chinook_contract_v1" for v in first)
    assert calls == []


def test_the_scoring_function_imports_nothing_from_inspect():
    source = Path(answer_scoring.__file__).read_text()
    assert "inspect" not in source.lower().replace("inspection", "")
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "import hypotrail.core.answer_scoring, sys; print('inspect_ai' in sys.modules)"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"


# --- check 5: a scorer crash is not an execution failure ------------------------------


@scorer(metrics=[accuracy()])
def exploding_scorer():
    """A throwaway Inspect scorer, defined here only, that raises on one Case."""

    async def score(state: TaskState, target: Target):
        if state.sample_id == "D05":
            raise RuntimeError("model generate failed in the tool loop")
        return Score(value="C")

    return score


def run_with(tmp_path, *, scorer_, error_on=None, error_message="scripted model failure"):
    script = ScriptedModel(spike_cases(), error_on=error_on, error_message=error_message)
    return runner.run_episodes(
        spike_cases(),
        workload=WORKLOAD,
        configuration="plain",
        model=runner.mock_model(script),
        repeats=1,
        log_dir=tmp_path / "logs",
        scorer=scorer_,
    )


def test_a_scorer_crash_and_an_execution_failure_project_differently(tmp_path):
    expected = [("D03", 0), ("D05", 0)]
    crashed = projection.project_log(
        run_with(tmp_path / "a", scorer_=exploding_scorer()), expected=expected
    )
    # the execution failure carries misleading text on purpose: it names the scorer
    failed = projection.project_log(
        run_with(
            tmp_path / "b",
            scorer_=exploding_scorer(),
            error_on=("D05", 1),
            error_message="scorers span: score() raised",
        ),
        expected=expected,
    )

    d03_a, d05_crash = crashed
    d03_b, d05_fail = failed
    assert d03_a["status"] == d03_b["status"] == "produced"

    # the scorer crash: execution produced an answer, the Criterion errored
    assert d05_crash["status"] == "produced"
    assert d05_crash["final_answer"] is not None
    assert d05_crash["criteria"] == [
        {"name": "exploding_scorer", "state": "errored", "reason": "scoring_failed"}
    ]
    # the execution failure: no answer, the Item failed, no Criterion was reached
    assert d05_fail["status"] == "failed"
    assert d05_fail["final_answer"] is None
    assert d05_fail["reason"] == "execution_failed"
    assert d05_fail["criteria"] == []


def test_the_projection_never_reads_error_text():
    source = Path(projection.__file__).read_text()
    for forbidden in ("traceback", ".error.message", "error.message", "'message'", '"message"'):
        assert forbidden not in source, forbidden
    for word in ("RuntimeError", "scorer exploded", "generate failed", "scripted model failure"):
        assert word not in source, word
