"""`next_step` in `status --json`: what waits, judged by the core when the Study is read (`hypotrail.core.next_step`).

The journey's states are read on the Studies the driver makes (`journey_reads`, `tests/_journey_states.py`); the stop rule is read on
Studies made for it. The CLI is run in process, offline.
"""

import json

import pytest
from _assess_helpers import observation_set_id, references_id, snapshot
from _client_helpers import decide_at_sequence
from _compare_helpers import assessed
from _deviation_helpers import chinook_world, compare_ids, reassessed
from _journey_states import STATES, name_of
from _study_helpers import run_json, run_ml
from test_study_lock import held_by_another_process

KEYS = {"kind", "text", "ids", "context", "to_handle", "flagged", "answered"}
NO_LONGER_APPLIES = "Your Decision no longer applies."
PENDING = "pending"  # the ids of the read's pending decisions, in their order
NOTHING = (None, [], [], [], [], [])

# Each state of the journey, with its `next_step`: the kind; the ids (PENDING, or Decisions by their Write sequence); the context
# Decisions by Write sequence; the request ids of the Attempts to handle; the flagged Decisions by Write sequence; and each answered
# Decision with the one that answers it, both by Write sequence.
JOURNEY = {
    "01-init": NOTHING,
    "02-attempts": NOTHING,
    "03-assessments": NOTHING,
    "04-pending": ("decide", PENDING, [], [], [], []),
    "05-decided": NOTHING,
    "06-resume": NOTHING,
    "07-rescored": ("look_again", [13], [], [], [13], []),
    "08-result-changed": ("look_again", [13], [], [], [13], []),
    "09-new-compare": ("decide", PENDING, [13], [], [13], []),
    "10-proxy": (None, [], [], [], [], [(13, 29)]),
    **{name: ("decide", PENDING, [], [], [], [(13, 29)]) for name in ("11-study-changed", "12-public-check-run", "13-exposure", "14-exposure-report", "15-deviation", "16-deviation-withdrawn", "18-recovered")},
    "17-interrupted": ("decide", PENDING, [], ["killed"], [], [(13, 29)]),
    "19-two-interrupted": ("decide", PENDING, [], ["killed-2", "killed-3"], [], [(13, 29)]),
    "30-chinook-init": NOTHING,
    "31-chinook-scenarios": NOTHING,
    "32-chinook-import": NOTHING,
    "33-chinook-assessed": NOTHING,
}


def expected_of(read: dict, case: tuple) -> dict:
    kind, ids, context, to_handle, flagged, answered = case
    by_sequence = {decision["write_sequence"]: decision["decision_id"] for decision in read["decisions"]}
    attempts = {attempt["request_id"]: attempt["attempt_id"] for attempt in read["attempts"]}
    return {
        "kind": kind,
        "text": NO_LONGER_APPLIES if kind == "look_again" else None,
        "ids": [entry["comparison_id"] for entry in read["pending_decisions"]] if ids == PENDING else [by_sequence[n] for n in ids],
        "context": [by_sequence[n] for n in context],
        "to_handle": [attempts[request_id] for request_id in to_handle],
        "flagged": [by_sequence[n] for n in flagged],
        "answered": [{"decision": by_sequence[n], "by": by_sequence[m]} for n, m in answered],
    }


def test_every_state_of_the_journey_but_the_refused_read_has_its_next_step_listed():
    names = [name_of(number, name) for number, name, _ in STATES]
    assert sorted(JOURNEY) == sorted(name for name in names if name != "00-no-study")


@pytest.mark.parametrize("state", sorted(JOURNEY))
def test_next_step_on_each_state_of_the_journey_is_the_mockups_value_under_the_four_rules(journey_reads, state):
    code, out, _ = journey_reads[f"{state}.status"]
    assert code == 0, out
    read = json.loads(out)
    assert read["next_step"] == expected_of(read, JOURNEY[state])


def test_the_refused_read_of_state_00_holds_no_next_step(journey_reads):
    code, out, _ = journey_reads["00-no-study.status"]
    assert code == 2 and "next_step" not in json.loads(out)


# --- the stop rule: "the same two Configurations" ---------------------------------------------------------------------------------


def status(study) -> dict:
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    return payload


def decision_ids(study) -> list:
    return [decision["decision_id"] for decision in status(study)["decisions"]]


def bike_decided(tmp_path):
    """A Bike Study with seasonal_7 and ridge_v1 assessed on dev, compared and decided, then both Observation sets assessed again: the
    Decision no longer applies. (study, {config: Attempt}, the new Assessment ids, Control first)."""
    study, attempts, assessments = assessed(tmp_path, "seasonal_7", "ridge_v1")
    comparison = compare_ids(study, assessments["seasonal_7"]["assessment_id"], assessments["ridge_v1"]["assessment_id"])["comparison_id"]
    decide_at_sequence(study, "Keep the Control", "first", comparison)
    again = reassessed(study, [attempts["seasonal_7"]["attempt_id"], attempts["ridge_v1"]["attempt_id"]], "regression_mae_v1")
    return study, attempts, again


def assessed_run(study, config, partition, request_id) -> str:
    code, payload, err = run_ml(study, config, partition, request_id)
    assert code == 0, (payload, err)
    code, assessment, err = run_json(
        "assess", "--study", study, "--observations", observation_set_id(study, payload["attempt"]), "--scorer", "regression_mae_v1",
        "--references", references_id(study),
    )
    assert code == 0, (assessment, err)
    return assessment["assessment"]["assessment_id"]


def answer(study, control, candidate, request_id) -> None:
    decide_at_sequence(study, "Keep the Candidate", request_id, compare_ids(study, control, candidate)["comparison_id"])


def stop_rule_of(study) -> tuple:
    step = status(study)["next_step"]
    return step["flagged"], step["answered"]


def test_a_decision_that_no_longer_applies_stops_being_flagged_once_a_later_applying_decision_answers_a_comparison_of_the_same_two_configurations(tmp_path):
    study, _, again = bike_decided(tmp_path)
    first = decision_ids(study)
    assert stop_rule_of(study) == (first, [])
    answer(study, *again, "second")
    [first, second] = decision_ids(study)
    assert stop_rule_of(study) == ([], [{"decision": first, "by": second}])


def test_a_decision_that_no_longer_applies_stays_flagged_when_the_later_decision_answers_a_comparison_of_two_other_configurations(tmp_path):
    study, _, again = bike_decided(tmp_path)
    other = assessed_run(study, "seasonal_7", "dev", "seasonal-again")  # seasonal_7 against seasonal_7: not seasonal_7 and ridge_v1
    answer(study, again[0], other, "second")
    [first, _] = decision_ids(study)
    assert stop_rule_of(study) == ([first], [])


def test_two_comparisons_of_imports_are_never_of_the_same_two_configurations_each_import_being_only_itself(tmp_path):
    study, attempts, assessments = chinook_world(tmp_path, count=4)
    decide_at_sequence(study, "Keep the Control", "first", compare_ids(study, assessments[0], assessments[1])["comparison_id"])
    reassessed(study, attempts[:2], "chinook_contract_v1")
    answer(study, assessments[2], assessments[3], "second")
    [first, _] = decision_ids(study)
    assert stop_rule_of(study) == ([first], [])


def test_the_same_two_declared_configurations_on_dev_then_on_public_check_are_the_same_two_configurations(tmp_path):
    study, _, _ = bike_decided(tmp_path)
    control = assessed_run(study, "seasonal_7", "public_check", "check-seasonal_7")
    candidate = assessed_run(study, "ridge_v1", "public_check", "check-ridge_v1")
    answer(study, control, candidate, "second")
    [first, second] = decision_ids(study)
    assert stop_rule_of(study) == ([], [{"decision": first, "by": second}])


# --- computed when the Study is read, never stored -------------------------------------------------------------------------------


def test_next_step_is_computed_never_stored_status_writes_nothing_takes_no_lock_keeps_the_write_sequence_and_reads_the_same_twice(tmp_path):
    study, _, _ = bike_decided(tmp_path)
    before, sequence = snapshot(study), status(study)["write_sequence"]
    with held_by_another_process(study):
        first = status(study)
    second = status(study)
    assert snapshot(study) == before
    assert first["write_sequence"] == second["write_sequence"] == sequence
    assert set(first["next_step"]) == KEYS
    assert first["next_step"] == second["next_step"] and first["next_step"]["kind"] == "look_again"
