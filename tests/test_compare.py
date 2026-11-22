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


# --- #154: a side that a lag feature of its own Configuration beats ---------------------------------------------------------------

SINGLE_FEATURE = "COMPARISON_SINGLE_FEATURE_BEATS"


def single_feature_warnings(record) -> list:
    return [w for w in record["warnings"] if w["code"] == SINGLE_FEATURE]


@pytest.mark.parametrize("ridge_is", ["candidate", "control"])
def test_a_side_beaten_by_its_own_lag_features_holds_one_warning_naming_the_side_and_the_features_also_in_limitations(dev, ridge_is):
    study, _, a = dev
    beaten = a["ridge_v1"]["single_feature_check"]["beating"]
    control, candidate = (a["seasonal_7"], a["ridge_v1"]) if ridge_is == "candidate" else (a["ridge_v1"], a["seasonal_7"])
    code, payload, err = compare(study, control["assessment_id"], candidate["assessment_id"])
    assert code == 0, (payload, err)
    record = payload["comparison"]
    warnings = single_feature_warnings(record)
    assert [w["code"] for w in record["warnings"]] == [SINGLE_FEATURE]
    message = warnings[0]["message"]
    assert f"The {ridge_is} of this Comparison" in message and a["ridge_v1"]["assessment_id"] in message
    assert [entry["feature"] for entry in beaten] == ["mean_previous_7", "lag_1", "lag_7"]
    assert all(f"{entry['feature']} ({entry['value']:.6g} rentals per day)" in message for entry in beaten), message
    assert message in record["limitations"]
    assert [c["check"] for c in record["comparability"]["checks"]] == ["population", "references", "scorer", "unit", "items", "mode", "coverage"]
    assert record["comparability"]["status"] == "compatible"


def test_two_flagged_sides_hold_two_warnings_one_naming_each_side(tmp_path):
    from _assess_helpers import assess, observation_set_id, references_id
    from _study_helpers import examples_copy, init_study, run_ml
    from test_single_feature import lag_1_only

    examples = examples_copy(tmp_path, edit=lag_1_only)
    study, _ = init_study(tmp_path, examples=examples)
    ids = {}
    for config in ("ridge_v1", "ridge_lag_1"):
        code, payload, err = run_ml(study, config, "dev", f"run-{config}", "--examples-dir", examples)
        assert code == 0, (payload, err)
        code, payload, err = assess(study, observation_set_id(study, payload["attempt"]), "regression_mae_v1", references_id(study))
        assert code == 0 and payload["assessment"]["single_feature_check"]["beating"], (payload, err)
        ids[config] = payload["assessment"]["assessment_id"]
    code, payload, err = compare(study, ids["ridge_v1"], ids["ridge_lag_1"])
    assert code == 0, (payload, err)
    messages = [w["message"] for w in single_feature_warnings(payload["comparison"])]
    assert len(messages) == 2
    assert "The control of this Comparison" in messages[0] and ids["ridge_v1"] in messages[0] and "mean_previous_7" in messages[0]
    assert "The candidate of this Comparison" in messages[1] and ids["ridge_lag_1"] in messages[1] and "mean_previous_7" not in messages[1]


def test_a_side_whose_field_is_empty_or_absent_adds_no_warning(dev, tmp_path):
    from _assess_helpers import assess, observation_set_id, references_id
    from _compare_helpers import forged

    study, attempts, a = dev
    code, payload, err = assess(study, observation_set_id(study, attempts["seasonal_7"]), "regression_mae_v1", references_id(study))
    assert code == 0 and payload["assessment"]["single_feature_check"] == {"computed": [], "beating": []}, (payload, err)
    code, both_empty, err = compare(study, a["seasonal_7"]["assessment_id"], payload["assessment"]["assessment_id"])
    assert code == 0 and both_empty["comparison"]["warnings"] == [], (both_empty, err)
    absent = [forged(study, a[c], lambda r: r.pop("single_feature_check")) for c in ("seasonal_7", "ridge_v1")]
    assert all("single_feature_check" not in record for record in absent)
    code, both_absent, err = compare(study, absent[0]["assessment_id"], absent[1]["assessment_id"])
    assert code == 0 and both_absent["comparison"]["warnings"] == [], (both_absent, err)


def test_the_status_line_of_compare_names_the_single_feature_warning_beside_the_status(dev):
    from _study_helpers import run_cli

    study, _, a = dev
    code, out, err = run_cli("compare", "--study", study, "--control", a["seasonal_7"]["assessment_id"], "--candidate", a["ridge_v1"]["assessment_id"])
    assert code == 0, err
    assert f"(compatible, with warning {SINGLE_FEATURE}): delta mae" in out, out
