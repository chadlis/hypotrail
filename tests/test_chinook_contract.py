"""Ticket #45: the `chinook_contract_v1` Scorer, its Criteria and its Instrument failures."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from _agent_helpers import CASES, CHINOOK, DATABASE, REFERENCES, WORKLOAD, ScriptedModel, read_jsonl

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
    "missing field": json.dumps(_without("D03", "evidence")),
    "clarification with rows": json.dumps(
        _with("D08", rows=[[1]])
    ),
    "a json array": "[1297]",
}


WRAPPED = {
    "prose before": "Here you go: " + json.dumps(correct_answer("D03")),
    "prose after": json.dumps(correct_answer("D03")) + " Hope it helps.",
    "fenced object": "```json\n" + json.dumps(correct_answer("D03")) + "\n```",
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
    assert (exact["state"], exact["score"]) == ("scored", False)


@pytest.mark.parametrize("name", ["not json", "missing field", "a json array"])
def test_exact_table_false_for_an_unreadable_answer_carries_invalid_response_format(name):
    exact = criteria(score(MALFORMED[name], "D03"))["exact_table"]
    assert (exact["state"], exact["score"], exact["reason"]) == ("scored", False, "invalid_response_format")


def test_an_extra_field_makes_format_invalid_but_leaves_exact_table_to_the_comparison():
    result = score(json.dumps(_with("D03", comment="hi")), "D03")
    by = criteria(result)
    assert (by["format_valid"]["score"], by["format_valid"]["reason"]) == (False, "invalid_response_format")
    assert (by["exact_table"]["state"], by["exact_table"]["score"], by["exact_table"]["reason"]) == ("scored", True, None)
    assert (by["contract_success"]["score"], by["contract_success"]["reason"]) == (False, "invalid_response_format")


def test_an_extra_field_on_a_wrong_table_is_still_an_incorrect_table():
    wrong = _with("D03", comment="hi", rows=[[1]])
    exact = criteria(score(json.dumps(wrong), "D03"))["exact_table"]
    assert (exact["score"], exact["reason"]) == (False, None)


def test_the_scorer_does_not_alter_the_raw_answer():
    raw = WRAPPED["fenced object"]
    result = score(raw, "D03")
    assert result["raw_answer"] == raw


def test_an_object_with_prose_is_scored_as_that_object_not_by_picking_the_number():
    # #58 (was: not rescued): the one object is read whole; a number in the prose is never picked.
    raw = "The answer is 1298. " + json.dumps(correct_answer("D03")) + " Not 1296."
    assert criteria(score(raw, "D03"))["exact_table"]["score"] is True
    wrong = "The answer is 1297. " + json.dumps(_with("D03", rows=[[1298]]))
    assert criteria(score(wrong, "D03"))["exact_table"]["score"] is False


# --- #58: a wrapped answer keeps its format penalty, its content is scored on its one object -------------------------------


def wrapped_forms(obj):
    text = json.dumps(obj)
    return {
        "prose before": "Le top 3 est sans égalité. " + text,
        "prose after": text + "\n\nVoilà le résultat.",
        "fenced object": "Voici :\n```json\n" + text + "\n```",
        "array holding the object": "[" + text + "]",
    }


@pytest.mark.parametrize("form", ["prose before", "prose after", "fenced object"])
def test_a_wrapped_answer_keeps_its_format_penalty(form):
    """Criterion 1."""
    by = criteria(score(wrapped_forms(correct_answer("D03"))[form], "D03"))
    assert (by["format_valid"]["state"], by["format_valid"]["score"], by["format_valid"]["reason"]) == (
        "scored",
        False,
        "invalid_response_format",
    )
    assert (by["contract_success"]["state"], by["contract_success"]["score"], by["contract_success"]["reason"]) == (
        "scored",
        False,
        "invalid_response_format",
    )


@pytest.mark.parametrize("form", ["prose before", "prose after", "fenced object", "array holding the object"])
@pytest.mark.parametrize(
    "answer",
    [
        _with("D03"),  # a right table
        _with("D03", rows=[[1298]]),  # a wrong table
        _with("D03", comment="hi"),  # an extra field: format-invalid alone, table still compared
        _without("D03", "evidence"),  # a missing field: not a table
        _with("D03", status="needs_clarification"),  # a schema-invalid object (rows with a clarification)
    ],
    ids=["right", "wrong", "extra field", "missing field", "clarification with rows"],
)
def test_a_wrapped_answer_scores_exact_table_and_evidence_as_its_object_alone(answer, form):
    """Criterion 2: state, score, Reason and components equal those of the object alone."""
    alone = criteria(score(answer, "D03"))
    wrapped = criteria(score(wrapped_forms(answer)[form], "D03"))
    assert wrapped["exact_table"] == alone["exact_table"]
    assert wrapped["evidence_link_valid"] == alone["evidence_link_valid"]


def test_a_wrapped_right_table_is_exact_and_a_wrong_one_is_not():
    right = criteria(score(wrapped_forms(correct_answer("D03"))["prose before"], "D03"))["exact_table"]
    assert (right["state"], right["score"], right["reason"]) == ("scored", True, None)
    wrong = criteria(score(wrapped_forms(_with("D03", rows=[[1298]]))["fenced object"], "D03"))["exact_table"]
    assert (wrong["score"], wrong["reason"], wrong["components"]["rows"]) == (False, None, False)


def test_without_a_trace_a_wrapped_schema_valid_object_leaves_the_link_unscored():
    link = criteria(score(wrapped_forms(correct_answer("D03"))["prose before"], "D03"))["evidence_link_valid"]
    assert (link["state"], link["score"], link["reason"]) == ("unscored", None, "trace_missing")


@pytest.mark.parametrize("trace", [True, False])
def test_a_wrapped_object_that_is_not_schema_valid_scores_the_link_false_trace_or_not(trace):
    steps = [] if trace else None
    raw = wrapped_forms(_with("D03", comment="hi"))["prose after"]
    link = criteria(chinook_contract.score_episode(raw, REFS["D03"], SCHEMA, steps))["evidence_link_valid"]
    assert (link["state"], link["score"], link["reason"]) == ("scored", False, "invalid_response_format")


TWO = json.dumps(correct_answer("D03"))
NOTHING_READ = {
    "plain text": "The answer is 1297.",
    "a bare number": "1297",
    "an array without an object": "[1297]",
    "an array of arrays": "[[1297]]",
    "an empty answer": "",
    "two objects in prose": "A " + TWO + " B " + TWO,
    "two in one fence": "```json\n" + TWO + "\n" + TWO + "\n```",
    "one in each of two fences": "```json\n" + TWO + "\n```\nor\n```json\n" + TWO + "\n```",
    "the same object repeated": TWO + TWO,
    "two in an array": "[" + TWO + "," + TWO + "]",
    "a non-finite number": '{"status": "answered", "rows": [[NaN]]}',
    "a truncated object": TWO[:-5],
}


@pytest.mark.parametrize("name", sorted(NOTHING_READ))
@pytest.mark.parametrize("trace", [True, False])
def test_no_object_or_several_reads_nothing_and_every_criterion_is_false(name, trace):
    """Criterion 3."""
    steps = [] if trace else None
    result = chinook_contract.score_episode(NOTHING_READ[name], REFS["D03"], SCHEMA, steps)
    assert [(c["name"], c["state"], c["score"], c["reason"]) for c in result["criteria"]] == [
        (n, "scored", False, "invalid_response_format") for n in chinook_contract.CRITERIA
    ]
    assert result["answer_read_from"] is None


# --- #58 T4, T8: the record says what was scored ---------------------------------------------------------------------


def test_the_scorer_version_changes_because_the_same_answer_now_scores_differently():
    assert chinook_contract.SCORER_VERSION == "3"
    assert chinook_contract.SCORER_NAME == "chinook_contract_v1"
    assert score(correct_answer("D03"), "D03")["scorer"] == {"name": "chinook_contract_v1", "version": "3"}


def test_the_record_says_whether_the_answer_was_read_from_the_raw_answer_or_an_embedded_object():
    assert score(correct_answer("D03"), "D03")["answer_read_from"] == "raw_answer"
    # a malformed raw answer that is still exactly one object is read from the raw answer
    assert score(_with("D03", comment="hi"), "D03")["answer_read_from"] == "raw_answer"
    for raw in wrapped_forms(correct_answer("D03")).values():
        assert score(raw, "D03")["answer_read_from"] == "embedded_object"
    assert score("The answer is 1297.", "D03")["answer_read_from"] is None


def test_the_provenance_is_a_top_level_field_and_the_scorer_record_keeps_its_shape():
    result = score(wrapped_forms(correct_answer("D03"))["prose before"], "D03")
    assert set(result) == {"scorer", "raw_answer", "criteria", "answer_read_from"}
    assert set(result["scorer"]) == {"name", "version"}


def test_the_error_record_has_no_such_field_since_nobody_established_what_was_read():
    def broken(*args):
        raise ValueError("x")

    result = chinook_contract.apply_scorer(broken, correct_answer_text("D03"), REFS["D03"], SCHEMA)
    assert set(result) == {"scorer", "raw_answer", "criteria", "error_type"}


def test_a_verdict_carries_the_field_without_clashing_and_an_episode_without_answer_does_not():
    wrapped = wrapped_forms(correct_answer("D03"))["prose before"]
    episodes = [
        {"case_id": "D03", "repeat": 0, "status": "produced", "reason": None, "final_answer": wrapped, "steps": []},
        {"case_id": "D03", "repeat": 1, "status": "failed", "reason": "boom", "final_answer": None, "steps": []},
    ]
    produced, failed = rescore.rescore_episodes(episodes, REFS, schema=SCHEMA, workload=WORKLOAD)
    assert produced["answer_read_from"] == "embedded_object"
    assert produced["raw_answer"] == wrapped
    assert {"case_id", "repeat", "status", "reason", "tool_error_codes"} <= set(produced)
    assert "answer_read_from" not in failed


def test_a_wrapped_answer_stays_raw_in_the_record_and_nothing_is_written_back():
    """Criterion 6."""
    for raw in wrapped_forms(correct_answer("D03")).values():
        result = score(raw, "D03")
        assert result["raw_answer"] == raw
        assert result["raw_answer"] != json.dumps(correct_answer("D03"))  # not replaced by the object


def test_a_well_formed_answer_is_scored_as_before():
    """Criterion 4: the four Criteria of an answer that is exactly one object, on a right and a wrong table."""
    right = score(correct_answer("D03"), "D03")
    assert [(c["name"], c["state"], c["score"], c["reason"]) for c in right["criteria"]] == [
        ("exact_table", "scored", True, None),
        ("format_valid", "scored", True, None),
        ("evidence_link_valid", "unscored", None, "trace_missing"),
        ("contract_success", "unscored", None, "trace_missing"),
    ]
    wrong = score(_with("D03", rows=[[1298]]), "D03")
    assert [(c["name"], c["state"], c["score"], c["reason"]) for c in wrong["criteria"]] == [
        ("exact_table", "scored", False, None),
        ("format_valid", "scored", True, None),
        ("evidence_link_valid", "unscored", None, "trace_missing"),
        ("contract_success", "scored", False, None),
    ]
    # surrounding whitespace is not a wrapping
    assert score("\n " + json.dumps(correct_answer("D03")) + " \n", "D03")["answer_read_from"] == "raw_answer"


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
        workload=WORKLOAD,
        configuration="plain",
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
        kept_log, REFS, schema=SCHEMA, expected=expected, scorer=explodes_on_the_second_d05, workload=WORKLOAD
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
    verdicts = rescore.rescore_log(kept_log, REFS, schema=SCHEMA, expected=expected, workload=WORKLOAD)
    assert all(v["scorer"]["name"] == "chinook_contract_v1" for v in verdicts)
    assert all(v["status"] == "produced" for v in verdicts)
    assert all(criteria(v)["exact_table"]["score"] is True for v in verdicts)
    assert all(criteria(v)["format_valid"]["score"] is True for v in verdicts)


def test_a_missing_reference_in_a_rescoring_is_unscored_not_a_key_error(kept_log):
    refs = {k: v for k, v in REFS.items() if k != "D05"}
    verdicts = rescore.rescore_log(
        kept_log, refs, schema=SCHEMA, expected=[("D03", 0), ("D05", 0)], workload=WORKLOAD
    )
    assert criteria(verdicts[0])["exact_table"]["score"] is True
    assert criteria(verdicts[1])["exact_table"]["reason"] == "reference_missing"


# --- #61: a number that decodes to a non-finite float is refused, like the NaN token ----------------------------------------

NOT_FINITE_LITERALS = ["1e999", "-1e999", "1E999", "1.5e+400"]


def _answer_text_holding(placement, literal):
    """The raw text of a bare answer whose JSON holds `literal` (a number token) at `placement`."""
    base = json.dumps(correct_answer("D03"))
    if placement == "rows":
        return base.replace("[[1297]]", f"[[{literal}]]")
    if placement == "nested array":
        return base[:-1] + f', "note": [[1, [{literal}]]]}}'
    if placement == "unknown field":
        return base[:-1] + f', "extra": {literal}}}'
    raise AssertionError(placement)


def _states(result):
    return [(c["name"], c["state"], c["score"], c["reason"]) for c in result["criteria"]]


@pytest.mark.parametrize("trace", [True, False])
@pytest.mark.parametrize("placement", ["rows", "nested array", "unknown field"])
def test_a_bare_answer_holding_a_non_finite_literal_reads_nothing_and_every_criterion_is_false(placement, trace):
    """#61 AC1 (Tightened A): not read as an object; four Criteria false with the Reason, trace or not, nothing read from."""
    steps = [] if trace else None
    for literal in NOT_FINITE_LITERALS:
        raw = _answer_text_holding(placement, literal)
        result = chinook_contract.score_episode(raw, REFS["D03"], SCHEMA, steps)
        assert _states(result) == [(n, "scored", False, "invalid_response_format") for n in chinook_contract.CRITERIA], raw
        assert result["answer_read_from"] is None, raw


@pytest.mark.parametrize("reference", [None, {}])
def test_an_unusable_reference_leaves_exact_table_unscored_for_an_answer_holding_a_non_finite_literal(reference):
    """#61 Tightened A / A2: the Instrument failure is kept apart from the system's format failure."""
    reason = chinook_contract.reference_problem(reference)
    result = chinook_contract.score_episode(_answer_text_holding("rows", "1e999"), reference, SCHEMA, None)
    assert _states(result) == [
        ("exact_table", "unscored", None, reason),
        ("format_valid", "scored", False, "invalid_response_format"),
        ("evidence_link_valid", "scored", False, "invalid_response_format"),
        ("contract_success", "scored", False, "invalid_response_format"),
    ]
    assert result["answer_read_from"] is None


def test_an_answer_holding_a_non_finite_literal_still_reads_an_object_inside_it_as_a_wrapped_answer():
    """#61 Tightened A, B4: the unknown field holds an object; the answer is a wrapped answer scored on it."""
    raw = '{"status": "answered", "extra": 1e999, "inner": {"a": 1}}'
    result = chinook_contract.score_episode(raw, REFS["D03"], SCHEMA, None)
    assert result["answer_read_from"] == "embedded_object"
    by = criteria(result)
    assert (by["format_valid"]["score"], by["contract_success"]["score"]) == (False, False)
    assert (by["exact_table"]["score"], by["exact_table"]["reason"]) == (False, "invalid_response_format")


def _without_raw(result):
    return {k: v for k, v in result.items() if k != "raw_answer"}


def test_a_wrapper_holding_an_overflowing_literal_scores_as_the_same_wrapper_holding_nan():
    """#61 AC2: same Criteria, same Reasons, same answer_read_from; only the `{` of the failed read is skipped."""
    obj = json.dumps(correct_answer("D03"))
    templates = [
        '{"answer": ' + obj + ', "note": X}',  # the right table inside a wrapper that fails
        '{"answer": ' + obj + ', "note": [X]}',
        'Voici : {"v": X} puis ' + obj,  # a failed candidate before the object
        '{"note": X, "inner": ' + obj + "}",  # the object sits inside the text of a failed read
        '{"rows": [[X]]} ' + obj,
        '{"answer": ' + obj + ', "note": X',  # truncated wrapper
    ]
    for template in templates:
        for token, literal in (("NaN", "1e999"), ("-Infinity", "-1e999")):
            for steps in (None, []):
                expected = chinook_contract.score_episode(template.replace("X", token), REFS["D03"], SCHEMA, steps)
                got = chinook_contract.score_episode(template.replace("X", literal), REFS["D03"], SCHEMA, steps)
                assert _without_raw(got) == _without_raw(expected), template
    right = chinook_contract.score_episode(templates[0].replace("X", "1e999"), REFS["D03"], SCHEMA)
    assert right["answer_read_from"] == "embedded_object" and criteria(right)["exact_table"]["score"] is True


@pytest.mark.parametrize("literal", ["1e308", "-1e308", "5e-324", "9" * 309, "-" + "9" * 309])
def test_a_finite_number_is_read_as_before_and_is_never_a_scoring_failure(literal):
    """#61 AC3 (Tightened B2): an integer too large for a double is an integer, not an overflow."""
    raw = _answer_text_holding("rows", literal)
    result = chinook_contract.score_episode(raw, REFS["D03"], SCHEMA, None)
    assert "error_type" not in result
    assert result["answer_read_from"] == "raw_answer"
    by = criteria(result)
    assert (by["format_valid"]["score"], by["format_valid"]["reason"]) == (True, None)
    assert (by["exact_table"]["state"], by["exact_table"]["score"], by["exact_table"]["reason"]) == ("scored", False, None)
    assert by["exact_table"]["components"]["rows"] is False


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_the_three_tokens_stay_refused(token):
    result = chinook_contract.score_episode(_answer_text_holding("rows", token), REFS["D03"], SCHEMA, None)
    assert _states(result) == [(n, "scored", False, "invalid_response_format") for n in chinook_contract.CRITERIA]
    assert result["answer_read_from"] is None


def test_an_integer_beyond_pythons_parse_limit_leaves_the_answer_unreadable_unless_an_object_is_readable_inside():
    """#61 B3 / B4 / D-012 item 18."""
    huge = "9" * 4301
    result = chinook_contract.score_episode(_answer_text_holding("rows", huge), REFS["D03"], SCHEMA, None)
    assert _states(result) == [(n, "scored", False, "invalid_response_format") for n in chinook_contract.CRITERIA]
    assert result["answer_read_from"] is None
    inside = '{"extra": ' + huge + ', "inner": {"a": 1}}'
    assert chinook_contract.score_episode(inside, REFS["D03"], SCHEMA, None)["answer_read_from"] == "embedded_object"
    # 4,300 digits is Python's own limit: an integer of that length is still read
    assert chinook_contract.score_episode(_answer_text_holding("rows", "9" * 4300), REFS["D03"], SCHEMA)["answer_read_from"] == "raw_answer"


def test_the_answer_schema_is_unchanged():
    """#61 AC6 (D-012 item 2): the bytes of `table-answer/1` are part of every Chinook Protocol digest."""
    import hashlib

    digest = hashlib.sha256((CHINOOK / "schemas" / "table-answer.schema.json").read_bytes()).hexdigest()
    assert digest == "72377e13ba30c890b0abcefadc71de08d95c73a0438b4acbc366a7c1651c0f14"
