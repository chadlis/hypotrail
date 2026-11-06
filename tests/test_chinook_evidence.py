"""Ticket #47: `evidence_link_valid` and contract success, scored from the projected trace."""

import copy
import json

import pytest

from _agent_helpers import CASES, CHINOOK, REFERENCES, WORKLOAD, ScriptedModel, read_jsonl

from hypotrail.agentic import cases as case_module
from hypotrail.agentic import projection, rescore, runner
from hypotrail.core import chinook_contract

SCHEMA = json.loads((CHINOOK / "schemas" / "table-answer.schema.json").read_text())
REFS = {r["case_id"]: r for r in read_jsonl(REFERENCES)}


def answer_for(case_id, evidence):
    ref = REFS[case_id]
    return {
        "status": ref["status"],
        "reason_code": ref["reason_code"],
        "columns": list(ref["columns"]),
        "rows": copy.deepcopy(ref["rows"]),
        "unit": ref["unit"],
        "evidence": evidence,
    }


def call(native, function="query_readonly"):
    return {"kind": "tool_call", "native_tool_call_id": native, "function": function, "arguments": {}}


def result(native, app, error=None, tool_error=None):
    body = {"columns": [], "rows": [], "row_count": 0, "truncated": False, "error": error, "tool_call_id": app}
    return {
        "kind": "tool_result",
        "native_tool_call_id": native,
        "app_tool_call_id": app,
        "result": body,
        "tool_error": tool_error,
    }


def final(text="{}"):
    return {"kind": "final_answer", "text": text}


def good_trace(app="hypotrail-aaa", native="call_1"):
    return [{"kind": "model_turn", "turn": 1}, call(native), result(native, app), {"kind": "model_turn", "turn": 2}, final()]


def score(answer, reference="D05", steps=None):
    text = answer if isinstance(answer, str) else json.dumps(answer)
    if isinstance(reference, str):
        reference = REFS[reference]
    return chinook_contract.score_episode(text, reference, SCHEMA, steps)


def criteria(verdict):
    return {c["name"]: c for c in verdict["criteria"]}


# --- evidence_link_valid: a valid link ---------------------------------------------


def test_a_cited_application_id_of_an_earlier_successful_call_is_a_valid_link():
    verdict = score(answer_for("D05", ["hypotrail-aaa"]), steps=good_trace())
    link = criteria(verdict)["evidence_link_valid"]
    assert (link["state"], link["score"], link["reason"]) == ("scored", True, None)


def link_of(evidence, steps, case_id="D05"):
    return criteria(score(answer_for(case_id, evidence), case_id, steps=steps))["evidence_link_valid"]


def assert_false(link):
    assert (link["state"], link["score"]) == ("scored", False)
    assert link["reason"]


# --- evidence_link_valid: every way a link is invalid ----------------------------------


def test_an_id_found_nowhere_in_the_trace_is_not_a_valid_link():
    assert_false(link_of(["hypotrail-zzz"], good_trace()))


def test_one_unknown_id_among_valid_ones_invalidates_the_link():
    assert_false(link_of(["hypotrail-aaa", "hypotrail-zzz"], good_trace()))


def test_the_id_of_a_call_with_a_structured_error_in_its_result_is_not_a_valid_link():
    error = {"code": "authorizer_denied", "type": "OperationalError", "message": "not authorized"}
    steps = [call("c1"), result("c1", "hypotrail-aaa", error=error), final()]
    assert_false(link_of(["hypotrail-aaa"], steps))


def test_the_id_of_a_call_with_an_inspect_level_tool_error_is_not_a_valid_link():
    steps = [call("c1"), result("c1", "hypotrail-aaa", tool_error={"type": "timeout"}), final()]
    assert_false(link_of(["hypotrail-aaa"], steps))


def test_an_id_whose_call_comes_after_the_final_answer_is_not_a_valid_link():
    steps = [{"kind": "model_turn", "turn": 1}, final(), call("c1"), result("c1", "hypotrail-aaa")]
    assert_false(link_of(["hypotrail-aaa"], steps))


def test_an_answered_status_with_empty_evidence_is_not_a_valid_link():
    assert_false(link_of([], good_trace()))


def test_an_application_id_whose_native_id_matches_no_tool_call_event_is_not_a_valid_link():
    steps = [call("c1"), result("c-other", "hypotrail-aaa"), final()]
    assert_false(link_of(["hypotrail-aaa"], steps))


def test_the_id_of_a_call_made_in_another_episode_is_not_a_valid_link():
    other = good_trace(app="hypotrail-bbb", native="call_9")
    mine = good_trace(app="hypotrail-aaa", native="call_1")
    assert_false(link_of(["hypotrail-bbb"], mine))
    assert link_of(["hypotrail-bbb"], other)["score"] is True


# --- evidence_link_valid: when it cannot be judged ---------------------------------------


def test_without_a_trace_evidence_link_valid_stays_unscored():
    link = criteria(score(answer_for("D05", ["hypotrail-aaa"])))["evidence_link_valid"]
    assert (link["state"], link["score"], link["reason"]) == ("unscored", None, "trace_missing")


@pytest.mark.parametrize("raw", ["not json", "[1]", json.dumps({"status": "answered"})])
@pytest.mark.parametrize("trace", [True, False])
def test_a_malformed_answer_scores_evidence_link_valid_false_with_invalid_response_format(raw, trace):
    link = criteria(score(raw, steps=good_trace() if trace else None))["evidence_link_valid"]
    assert (link["state"], link["score"], link["reason"]) == ("scored", False, "invalid_response_format")


def test_a_well_formed_answer_without_a_trace_still_leaves_the_link_unscored():
    link = criteria(score(answer_for("D05", ["hypotrail-aaa"])))["evidence_link_valid"]
    assert (link["state"], link["score"], link["reason"]) == ("unscored", None, "trace_missing")


# --- contract success --------------------------------------------------------------------


def contract(verdict):
    c = criteria(verdict)["contract_success"]
    return c["state"], c["score"], c["reason"]


def clarification(**changes):
    ref = REFS["D08"]
    base = {
        "status": ref["status"],
        "reason_code": ref["reason_code"],
        "columns": [],
        "rows": [],
        "unit": None,
        "evidence": [],
    }
    return {**base, **changes}


def test_an_answered_exact_table_with_a_valid_link_is_a_contract_success():
    verdict = score(answer_for("D05", ["hypotrail-aaa"]), steps=good_trace())
    assert contract(verdict) == ("scored", True, None)


def test_an_exact_table_with_no_valid_evidence_is_exact_but_not_a_contract_success():
    verdict = score(answer_for("D05", []), steps=good_trace())
    assert criteria(verdict)["exact_table"]["score"] is True
    assert criteria(verdict)["evidence_link_valid"]["score"] is False
    assert contract(verdict)[:2] == ("scored", False)


def test_an_inexact_table_with_a_valid_link_is_not_a_contract_success():
    answer = {**answer_for("D05", ["hypotrail-aaa"]), "unit": "ms"}
    verdict = score(answer, steps=good_trace())
    assert contract(verdict)[:2] == ("scored", False)


@pytest.mark.parametrize("steps", [None, [], good_trace()], ids=["no trace", "empty trace", "a trace"])
def test_a_clarification_with_the_right_status_and_reason_succeeds_whether_or_not_a_tool_was_called(steps):
    verdict = score(clarification(), "D08", steps=steps)
    assert contract(verdict) == ("scored", True, None)


def test_a_clarification_that_cites_a_valid_call_still_succeeds():
    verdict = score(clarification(evidence=["hypotrail-aaa"]), "D08", steps=good_trace())
    assert contract(verdict) == ("scored", True, None)


def test_the_wrong_status_does_not_succeed():
    verdict = score(clarification(), "D05", steps=good_trace())
    assert contract(verdict)[:2] == ("scored", False)
    ref = REFS["D08"]
    other = {"status": "not_answerable", "reason_code": "field_not_available"}
    assert ref["status"] == "needs_clarification"
    verdict = score(clarification(**other), "D08", steps=good_trace())
    assert contract(verdict)[:2] == ("scored", False)


def test_the_right_status_with_the_wrong_reason_does_not_succeed():
    wrong = clarification(reason_code="field_not_available")
    verdict = score(wrong, "D08", steps=good_trace())
    assert criteria(verdict)["format_valid"]["score"] is False  # the schema ties the reason to the status
    assert contract(verdict)[:2] == ("scored", False)


def test_a_wrong_reason_that_the_schema_accepts_does_not_succeed():
    reference = {**REFS["D08"], "reason_code": "field_not_available", "status": "not_answerable"}
    answer = clarification(status="not_answerable", reason_code="field_not_available")
    assert contract(score(answer, reference, steps=[]))[:2] == ("scored", True)
    reference = {**reference, "reason_code": "criterion_undefined"}
    verdict = score(answer, reference, steps=[])
    assert criteria(verdict)["exact_table"]["components"]["reason_code"] is False
    assert contract(verdict)[:2] == ("scored", False)


@pytest.mark.parametrize(
    "raw", ["The answer is 1297.", "```json\n" + json.dumps(answer_for("D05", ["hypotrail-aaa"])) + "\n```"]
)
def test_a_malformed_answer_never_succeeds(raw):
    verdict = score(raw, steps=good_trace())
    assert contract(verdict)[:2] == ("scored", False)
    assert contract(verdict)[2] == "invalid_response_format"


# --- T1: false wins over unscored and errored ----------------------------------------------


def test_a_malformed_answer_with_a_missing_reference_is_a_contract_failure():
    verdict = score("The answer is 1297.", None, steps=good_trace())
    assert criteria(verdict)["exact_table"]["state"] == "unscored"
    assert contract(verdict)[:2] == ("scored", False)


def test_an_answered_status_with_an_invalid_link_and_a_missing_reference_is_a_contract_failure():
    verdict = score(answer_for("D05", []), None, steps=good_trace())
    assert contract(verdict)[:2] == ("scored", False)


def test_a_well_formed_answer_with_valid_evidence_and_a_missing_reference_is_unscored():
    verdict = score(answer_for("D05", ["hypotrail-aaa"]), None, steps=good_trace())
    assert contract(verdict) == ("unscored", None, "reference_missing")


def test_an_answered_status_without_a_trace_and_with_a_reference_is_unscored_for_want_of_a_trace():
    verdict = score(answer_for("D05", ["hypotrail-aaa"]))
    assert contract(verdict) == ("unscored", None, "trace_missing")


def test_a_crash_of_the_scorer_errors_the_contract_success_too():
    def broken(*args, **kwargs):
        raise ZeroDivisionError

    result = chinook_contract.apply_scorer(broken, "{}", REFS["D05"], SCHEMA)
    assert contract(result) == ("errored", None, "scoring_failed")


def test_contract_success_counts_against_the_system_only_when_scored_false():
    failing = score(answer_for("D05", []), steps=good_trace())
    unscored = score(answer_for("D05", ["hypotrail-aaa"]), None, steps=good_trace())
    assert chinook_contract.counts_against_system(failing) is True
    assert chinook_contract.counts_against_system(unscored) is False


# --- through a real kept log: projection, then the Scorer ------------------------------------


SPIKE = ["D03", "D05"]


@pytest.fixture
def episodes(tmp_path):
    cases = case_module.load_cases(CASES, SPIKE)
    location = runner.run_episodes(
        cases,
        workload=WORKLOAD,
        configuration="plain",
        model=runner.mock_model(ScriptedModel(cases)),
        repeats=2,
        log_dir=tmp_path / "logs",
    )
    expected = [(c, r) for c in SPIKE for r in (0, 1)]
    return location, {
        (e["case_id"], e["repeat"]): e for e in projection.project_log(location, expected=expected)
    }


def app_id(episode):
    return next(s["app_tool_call_id"] for s in episode["steps"] if s["kind"] == "tool_result")


def test_the_scripted_episodes_cite_a_call_that_maps_to_a_native_tool_event(episodes):
    _, by_key = episodes
    for episode in by_key.values():
        verdict = score(episode["final_answer"], episode["case_id"], steps=episode["steps"])
        assert contract(verdict) == ("scored", True, None)


def test_the_id_of_another_case_or_another_repeat_is_not_a_valid_link(episodes):
    _, by_key = episodes
    mine = by_key[("D05", 0)]
    for other in (("D03", 0), ("D05", 1)):
        foreign = app_id(by_key[other])
        assert foreign != app_id(mine)
        assert_false(link_of([foreign], mine["steps"]))


def test_rescoring_a_kept_log_carries_the_new_criteria(episodes):
    location, _ = episodes
    expected = [(c, r) for c in SPIKE for r in (0, 1)]
    verdicts = rescore.rescore_log(location, REFS, schema=SCHEMA, expected=expected, workload=WORKLOAD)
    assert all(contract(v) == ("scored", True, None) for v in verdicts)


def test_the_scorer_reads_only_plain_records(episodes):
    _, by_key = episodes
    steps = by_key[("D05", 0)]["steps"]
    assert json.loads(json.dumps(steps)) == steps  # plain data: no Inspect object in it
