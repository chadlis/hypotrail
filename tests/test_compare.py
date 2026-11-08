"""Ticket #71: `compare` writes a Comparison of two Assessments as Control and Candidate."""

from pathlib import Path

import pytest
from _assess_helpers import rows_of
from _compare_helpers import assessed, compare, comparisons

from hypotrail.ml.comparison import compare as library_compare

BIKE = Path(__file__).resolve().parent.parent / "examples" / "bike_day"


@pytest.fixture(scope="module")
def dev(tmp_path_factory):
    return assessed(tmp_path_factory.mktemp("dev"), "seasonal_7", "ridge_v1")


def test_a_strict_comparison_holds_what_the_spec_names_and_is_valid_against_the_contract(dev):
    study, _, a = dev
    code, payload, _ = compare(study, a["seasonal_7"]["assessment_id"], a["ridge_v1"]["assessment_id"])
    assert code == 0
    record = payload["comparison"]
    assert record["roles"] == {
        "control_assessment_id": a["seasonal_7"]["assessment_id"],
        "candidate_assessment_id": a["ridge_v1"]["assessment_id"],
    }
    assert record["comparability"]["status"] == "compatible"
    assert [(c["check"], c["passed"]) for c in record["comparability"]["checks"]] == [
        ("population", True), ("references", True), ("scorer", True), ("unit", True), ("items", True), ("mode", True), ("coverage", True),
    ]
    assert record["coverage"] == {"expected": 182, "control_scored": 182, "candidate_scored": 182, "paired": 182}
    assert record["limitations"]
    assert (study / "comparisons" / record["comparison_id"] / "comparison.json").is_file()
    assert record["comparison_id"] in comparisons(study)


def test_on_dev_the_per_date_differences_and_delta_mae_equal_the_library_comparison_within_1e_9(dev, tmp_path):
    study, attempts, a = dev
    _, payload, _ = compare(study, a["seasonal_7"]["assessment_id"], a["ridge_v1"]["assessment_id"])
    record = payload["comparison"]

    def predictions(config):
        return study / "attempts" / attempts[config]["attempt_id"] / "predictions.csv"

    library = library_compare(
        predictions("seasonal_7"), predictions("ridge_v1"), study / "artifacts" / "references.csv",
        study / "artifacts" / "memberships.csv", tmp_path / "out", BIKE,
    )
    assert record["delta"]["metric"] == "mae" and record["delta"]["unit"] == "rentals per day"
    assert abs(record["delta"]["value"] - library["delta_mae"]["value"]) < 1e-9
    assert round(record["delta"]["value"], 2) == 173.94  # positive: the Candidate is worse; no improvement is required
    paired = {r["row_id"]: r for r in rows_of(study / record["paired_deltas_ref"]["path"])}
    assert len(paired) == 182
    for difference in library["differences"]:
        got = paired[difference["row_id"]]
        assert abs(float(got["delta_abs_error"]) - difference["delta_abs_error"]) < 1e-9
        assert abs(float(got["control_abs_error"]) - difference["control_abs_error"]) < 1e-9
        assert abs(float(got["candidate_abs_error"]) - difference["candidate_abs_error"]) < 1e-9


def test_swapping_the_roles_flips_the_sign_of_the_delta(dev):
    study, _, a = dev
    _, forward, _ = compare(study, a["seasonal_7"]["assessment_id"], a["ridge_v1"]["assessment_id"])
    _, backward, _ = compare(study, a["ridge_v1"]["assessment_id"], a["seasonal_7"]["assessment_id"])
    assert backward["comparison"]["delta"]["value"] == pytest.approx(-forward["comparison"]["delta"]["value"])
