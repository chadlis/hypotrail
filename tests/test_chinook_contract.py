"""Ticket #45: the `chinook_contract_v1` Scorer, its Criteria and its Instrument failures."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from _agent_helpers import CASES, CHINOOK, DATABASE, REFERENCES, ScriptedModel, read_jsonl

from hypotrail.agentic import cases as case_module
from hypotrail.agentic import rescore, runner
from hypotrail.core import chinook_contract

SCHEMA = json.loads((CHINOOK / "schemas" / "table-answer.schema.json").read_text())
REFS = {r["case_id"]: r for r in read_jsonl(REFERENCES)}
SPIKE = ["D03", "D05"]


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


def score(answer, reference="D05", schema=SCHEMA):
    text = answer if isinstance(answer, str) else json.dumps(answer)
    if isinstance(reference, str):
        reference = REFS[reference]
    return chinook_contract.score_episode(text, reference, schema)


def criteria(result):
    return {c["name"]: c for c in result["criteria"]}


# --- exact_table ---------------------------------------------------------------------


def test_a_correct_answer_scores_exact_table_and_format_valid_true():
    result = score(correct_answer("D05"))
    assert criteria(result)["exact_table"]["state"] == "scored"
    assert criteria(result)["exact_table"]["score"] is True
    assert criteria(result)["format_valid"]["state"] == "scored"
    assert criteria(result)["format_valid"]["score"] is True
    assert criteria(result)["format_valid"]["reason"] is None


def test_exact_table_names_the_component_that_differs():
    answer = correct_answer("D05")
    answer["unit"] = "ms"
    exact = criteria(score(answer))["exact_table"]
    assert exact["score"] is False
    assert exact["components"]["unit"] is False
    assert exact["components"]["rows"] is True


def test_the_tolerance_comes_from_the_reference_on_e08():
    ref = REFS["E08"]
    assert ref["numeric_absolute_tolerance"] == 0.005

    def verdict(value, reference):
        answer = {**correct_answer("E08"), "rows": [[value]]}
        return criteria(score(answer, reference))["exact_table"]["score"]

    assert verdict(283910.045, ref) is True
    assert verdict(283910.0451, ref) is False


def test_another_tolerance_in_the_reference_changes_the_verdict():
    wide = {**REFS["E08"], "numeric_absolute_tolerance": 0.5}
    tight = {**REFS["E08"], "numeric_absolute_tolerance": 0}
    answer = {**correct_answer("E08"), "rows": [[283910.3]]}
    assert criteria(score(answer, wide))["exact_table"]["score"] is True
    assert criteria(score(answer, tight))["exact_table"]["score"] is False


def test_every_other_number_is_exact():
    answer = {**correct_answer("D03"), "rows": [[1298]]}
    assert criteria(score(answer, "D03"))["exact_table"]["score"] is False


# --- format_valid ---------------------------------------------------------------------


def _with(case_id, **changes):
    return {**correct_answer(case_id), **changes}


def _without(case_id, field):
    answer = correct_answer(case_id)
    del answer[field]
    return answer


MALFORMED = {
    "not json": "The answer is 1297.",
    "fenced object": "```json\n" + json.dumps(correct_answer("D03")) + "\n```",
    "prose around": "Here you go: " + json.dumps(correct_answer("D03")) + " Hope it helps.",
    "missing field": json.dumps(_without("D03", "evidence")),
    "extra field": json.dumps(_with("D03", comment="hi")),
    "clarification with rows": json.dumps(
        _with("D08", rows=[[1]])
    ),
    "a json array": "[1297]",
}


@pytest.mark.parametrize("name", sorted(MALFORMED))
def test_a_malformed_answer_is_format_invalid_with_its_reason_and_never_exact(name):
    case_id = "D08" if name == "clarification with rows" else "D03"
    raw = MALFORMED[name]
    result = score(raw, case_id)
    format_valid = criteria(result)["format_valid"]
    assert format_valid["state"] == "scored"
    assert format_valid["score"] is False
    assert format_valid["reason"] == "invalid_response_format"
    exact = criteria(result)["exact_table"]
    assert exact["state"] == "scored"
    assert exact["score"] is False


def test_the_scorer_does_not_alter_the_raw_answer():
    raw = MALFORMED["fenced object"]
    result = score(raw, "D03")
    assert result["raw_answer"] == raw


def test_an_object_with_prose_is_not_rescued_by_picking_the_number():
    raw = MALFORMED["prose around"]
    assert criteria(score(raw, "D03"))["exact_table"]["score"] is False


# --- Reference problems ---------------------------------------------------------------------


def test_a_missing_reference_leaves_exact_table_unscored_and_format_is_still_judged():
    result = score(correct_answer("D03"), None)
    exact = criteria(result)["exact_table"]
    assert (exact["state"], exact["score"], exact["reason"]) == (
        "unscored",
        None,
        "reference_missing",
    )
    assert criteria(result)["format_valid"]["score"] is True
    assert all(c["score"] is not False for c in result["criteria"] if c["name"] == "exact_table")


@pytest.mark.parametrize("broken", ["no rows", "rows not a list", "empty", "not a dict", "bad tolerance"])
def test_an_invalid_reference_leaves_exact_table_unscored_with_a_reason(broken):
    reference = copy.deepcopy(REFS["D03"])
    if broken == "no rows":
        del reference["rows"]
    elif broken == "rows not a list":
        reference["rows"] = "1297"
    elif broken == "empty":
        reference = {}
    elif broken == "not a dict":
        reference = ["x"]
    else:
        reference["numeric_absolute_tolerance"] = "0.005"
    exact = criteria(score(correct_answer("D03"), reference))["exact_table"]
    assert exact["state"] == "unscored"
    assert exact["score"] is None
    assert exact["reason"] == "reference_invalid"


# --- a crash of the machinery ---------------------------------------------------------------------


def test_a_crash_inside_the_scorer_leaves_every_criterion_errored_with_the_exception_type():
    def broken(answer, reference, schema, steps):
        raise ZeroDivisionError("secret message that must not be parsed")

    result = chinook_contract.apply_scorer(
        broken, correct_answer_text("D03"), REFS["D03"], SCHEMA
    )
    assert [(c["name"], c["state"], c["score"], c["reason"]) for c in result["criteria"]] == [
        ("exact_table", "errored", None, "scoring_failed"),
        ("format_valid", "errored", None, "scoring_failed"),
        ("evidence_link_valid", "errored", None, "scoring_failed"),
        ("contract_success", "errored", None, "scoring_failed"),
    ]
    assert result["error_type"] == "ZeroDivisionError"
    assert result["scorer"] == {"name": "chinook_contract_v1", "version": chinook_contract.SCORER_VERSION}


def correct_answer_text(case_id):
    return json.dumps(correct_answer(case_id))


# --- three situations, three outcomes ---------------------------------------------------------------------


def test_missing_reference_scorer_crash_and_malformed_answer_are_three_distinct_outcomes():
    text = correct_answer_text("D03")

    missing = chinook_contract.apply_scorer(chinook_contract.score_episode, text, None, SCHEMA)

    def crash(*args):
        raise RuntimeError("boom")

    crashed = chinook_contract.apply_scorer(crash, text, REFS["D03"], SCHEMA)
    malformed = chinook_contract.apply_scorer(
        chinook_contract.score_episode, "```json\n" + text + "\n```", REFS["D03"], SCHEMA
    )

    got = {
        "missing": (criteria(missing)["exact_table"]["state"], criteria(missing)["exact_table"]["reason"]),
        "crashed": (criteria(crashed)["exact_table"]["state"], criteria(crashed)["exact_table"]["reason"]),
        "malformed": (
            criteria(malformed)["format_valid"]["state"] + ":" + str(criteria(malformed)["format_valid"]["score"]),
            criteria(malformed)["format_valid"]["reason"],
        ),
    }
    assert got == {
        "missing": ("unscored", "reference_missing"),
        "crashed": ("errored", "scoring_failed"),
        "malformed": ("scored:False", "invalid_response_format"),
    }
    # only the malformed answer counts against the evaluated system
    assert [chinook_contract.counts_against_system(r) for r in (missing, crashed, malformed)] == [
        False,
        False,
        True,
    ]


# --- name, version, determinism, no Inspect ---------------------------------------------------------------------


def test_the_output_records_the_scorer_name_and_version_and_is_deterministic():
    first = score(correct_answer("D05"))
    second = score(correct_answer("D05"))
    assert first == second
    assert first["scorer"]["name"] == "chinook_contract_v1"
    assert isinstance(first["scorer"]["version"], str) and first["scorer"]["version"]


def test_the_scorer_module_imports_no_inspect():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import hypotrail.core.chinook_contract, sys; print('inspect_ai' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"
    assert "inspect" not in Path(chinook_contract.__file__).read_text().lower().replace("inspection", "")


# --- T1: a crash is caught where the core applies the Scorer to one Episode ---------------------------------------------------------------------


@pytest.fixture
def kept_log(tmp_path):
    cases = case_module.load_cases(CASES, SPIKE)
    return runner.run_episodes(
        cases,
        database=DATABASE,
        model=runner.mock_model(ScriptedModel(cases)),
        repeats=2,
        log_dir=tmp_path / "logs",
    )


def test_a_core_scorer_crash_on_one_episode_errors_only_that_episode(kept_log):
    expected = [(c, r) for c in SPIKE for r in (0, 1)]

    d05_calls = []

    def explodes_on_the_second_d05(answer, reference, schema, steps):
        if reference["case_id"] == "D05":
            d05_calls.append(1)
            if len(d05_calls) == 2:
                raise KeyError("lost")
        return chinook_contract.score_episode(answer, reference, schema, steps)

    verdicts = rescore.rescore_log(
        kept_log, REFS, schema=SCHEMA, expected=expected, scorer=explodes_on_the_second_d05
    )
    by_key = {(v["case_id"], v["repeat"]): v for v in verdicts}
    broken = [v for v in verdicts if v["criteria"][0]["state"] == "errored"]
    assert len(broken) == 1
    bad = broken[0]
    assert (bad["case_id"], bad["repeat"]) == ("D05", 1)
    # 1. affected Criteria errored with scoring_failed
    assert {(c["state"], c["reason"]) for c in bad["criteria"]} == {("errored", "scoring_failed")}
    # 2. exception type kept as a structured field
    assert bad["error_type"] == "KeyError"
    # 3. the other Episodes are still scored
    others = [v for k, v in by_key.items() if v is not bad]
    assert len(others) == 3
    assert all(criteria(v)["exact_table"]["score"] is True for v in others)
    # 4. execution status stays produced
    assert bad["status"] == "produced"


def test_rescoring_a_kept_log_goes_through_the_scorer_and_records_it(kept_log):
    expected = [(c, r) for c in SPIKE for r in (0, 1)]
    verdicts = rescore.rescore_log(kept_log, REFS, schema=SCHEMA, expected=expected)
    assert all(v["scorer"]["name"] == "chinook_contract_v1" for v in verdicts)
    assert all(v["status"] == "produced" for v in verdicts)
    assert all(criteria(v)["exact_table"]["score"] is True for v in verdicts)
    assert all(criteria(v)["format_valid"]["score"] is True for v in verdicts)


def test_a_missing_reference_in_a_rescoring_is_unscored_not_a_key_error(kept_log):
    refs = {k: v for k, v in REFS.items() if k != "D05"}
    verdicts = rescore.rescore_log(
        kept_log, refs, schema=SCHEMA, expected=[("D03", 0), ("D05", 0)]
    )
    assert criteria(verdicts[0])["exact_table"]["score"] is True
    assert criteria(verdicts[1])["exact_table"]["reason"] == "reference_missing"
