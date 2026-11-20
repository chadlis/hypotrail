"""Ticket #71: a Comparison is refused, with its own code and Reason, and writes nothing; never a hidden intersection."""

import pytest
from _assess_helpers import construct, snapshot
from _compare_helpers import assessed, compare, forged


@pytest.fixture
def fresh(tmp_path):
    study, attempts, a = assessed(tmp_path, "seasonal_7", "ridge_v1")
    return study, attempts, a["seasonal_7"], a["ridge_v1"]


def refused(study, control, candidate, code, check, reason):
    before = snapshot(study)
    exit_code, payload, err = compare(study, control["assessment_id"], candidate["assessment_id"])
    assert exit_code == 3, (payload, err)
    error = payload["error"]
    assert set(error) == {"code", "message", "stage", "details"}
    assert (error["code"], error["stage"]) == (code, "compare")
    assert (error["details"]["check"], error["details"]["reason"]) == (check, reason)
    assert error["details"]["checks"][-1] == {"check": check, "passed": False, "reason": reason}
    assert snapshot(study) == before  # no Comparison, no file of any kind
    return error["details"]


def test_two_populations_are_refused(fresh):
    study, attempts, control, candidate = fresh
    other = construct(study, attempts["ridge_v1"], lambda rows: rows, provenance={"partition": "train"})
    train = forged(study, candidate, lambda r: r.update(observation_set_id=other))
    details = refused(study, control, train, "COMPARISON_POPULATION_DIFFERS", "population", "population_differs")
    assert details["control"]["partition"] == "dev" and details["candidate"]["partition"] == "train"


def test_two_references_sets_are_refused(fresh):
    study, _, control, candidate = fresh
    other = forged(study, candidate, lambda r: r["references_ref"].update(sha256="b" * 64))
    details = refused(study, control, other, "COMPARISON_REFERENCES_DIFFER", "references", "references_differ")
    assert details["candidate"] == {"references_sha256": "b" * 64}


@pytest.mark.parametrize("field,value", [("id", "regression_rmse_v1"), ("version", "2"), ("config_digest", "c" * 64)])
def test_two_scorers_or_two_versions_or_digests_of_one_scorer_are_refused(fresh, field, value):
    study, _, control, candidate = fresh
    other = forged(study, candidate, lambda r: r["scorer"].update({field: value}))
    details = refused(study, control, other, "COMPARISON_SCORER_DIFFERS", "scorer", "scorer_differs")
    assert details["candidate"][field] == value


def test_two_units_are_refused(fresh):
    study, _, control, candidate = fresh
    other = forged(study, candidate, lambda r: r["metrics"][0].update(unit="visits per day"))
    details = refused(study, control, other, "COMPARISON_UNIT_DIFFERS", "unit", "unit_differs")
    assert details["control"] == {"unit": "rentals per day"} and details["candidate"] == {"unit": "visits per day"}


def test_items_that_differ_by_one_are_refused_with_the_counts_on_each_side_and_no_intersection(fresh):
    study, _, control, candidate = fresh
    other = forged(study, candidate, per_item=lambda rows: rows[:-1])
    details = refused(study, control, other, "COMPARISON_ITEMS_DIFFER", "items", "items_differ")
    assert details["control"] == {"items": 182, "only_here": 1}
    assert details["candidate"] == {"items": 181, "only_here": 0}


def test_items_are_aligned_by_row_id_not_by_position(fresh):
    study, _, control, candidate = fresh
    shuffled = forged(study, candidate, per_item=lambda rows: list(reversed(rows)))
    code, payload, _ = compare(study, control["assessment_id"], shuffled["assessment_id"])
    assert code == 0
    _, plain, _ = compare(study, control["assessment_id"], candidate["assessment_id"])
    assert payload["comparison"]["delta"]["value"] == plain["comparison"]["delta"]["value"]


def test_an_item_not_scored_on_one_side_is_refused_rather_than_dropped_from_the_pairs(fresh):
    study, _, control, candidate = fresh

    def lose_one(rows):
        rows[0].update(state="unscored", value="", reason="item_failed")
        return rows

    other = forged(study, candidate, per_item=lose_one)
    details = refused(study, control, other, "COMPARISON_COVERAGE_INSUFFICIENT", "coverage", "coverage_insufficient")
    assert details["control"] == {"expected": 182, "scored": 182} and details["candidate"] == {"expected": 182, "scored": 181}


def test_a_comparison_of_a_dev_side_and_a_public_check_side_is_refused_as_two_populations_and_exposes_nothing(fresh):
    # #73 lifted the refusal of public_check inside a Study (tests/test_exposure.py); two Partitions are still not one population
    study, attempts, control, candidate = fresh
    hidden = construct(study, attempts["ridge_v1"], lambda rows: rows, provenance={"partition": "public_check"})
    on_public = forged(study, candidate, lambda r: r.update(observation_set_id=hidden))
    before = snapshot(study)
    code, payload, _ = compare(study, control["assessment_id"], on_public["assessment_id"])
    assert (code, payload["error"]["code"], payload["error"]["details"]["check"]) == (3, "COMPARISON_POPULATION_DIFFERS", "population")
    assert snapshot(study) == before and not (study / "exposures").exists()


def test_a_comparison_of_a_partition_other_than_dev_is_refused(fresh):
    study, attempts, control, candidate = fresh
    sides = []
    for config, assessment in (("seasonal_7", control), ("ridge_v1", candidate)):
        train = construct(study, attempts[config], lambda rows: rows, provenance={"partition": "train"})
        sides.append(forged(study, assessment, lambda r, train=train: r.update(observation_set_id=train)))
    code, payload, _ = compare(study, sides[0]["assessment_id"], sides[1]["assessment_id"])
    assert (code, payload["error"]["code"]) == (2, "COMPARISON_PARTITION_NOT_DEV")


def test_an_unknown_assessment_is_refused_and_its_id_is_never_a_path(fresh):
    study, _, control, _ = fresh
    code, payload, _ = compare(study, control["assessment_id"], "../nope")
    assert (code, payload["error"]["code"], payload["error"]["stage"]) == (2, "ASSESSMENT_NOT_FOUND", "compare")
    assert payload["error"]["details"] == {"role": "candidate", "assessment_id": "../nope"}


def test_two_modes_of_production_that_are_not_an_import_are_refused(fresh):
    study, attempts, control, candidate = fresh
    scripted = construct(study, attempts["ridge_v1"], lambda rows: rows, mode="scripted_fixture")
    other = forged(study, candidate, lambda r: r.update(observation_set_id=scripted))
    details = refused(study, control, other, "COMPARISON_MODE_DIFFERS", "mode", "mode_differs")
    assert details["control"] == {"mode": "native_ml"} and details["candidate"] == {"mode": "scripted_fixture"}
