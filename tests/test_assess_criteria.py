"""Ticket #66: the Criterion states, the counts and the Metrics of an Assessment."""

import pytest
from _assess_helpers import (
    assess,
    construct,
    construct_references,
    fresh_study,
    observation_set_id,
    observations_of,
    per_item,
    references_id,
    rows_of,
    snapshot,
)
from _study_helpers import EXAMPLES

from hypotrail.core import contracts

BIKE = EXAMPLES / "bike_day"


def test_every_expected_item_is_scored_with_its_absolute_error_and_the_counts_say_so(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    obs = observation_set_id(study, attempts["seasonal_7"])
    _, payload, _ = assess(study, obs, "regression_mae_v1", references_id(study))
    record = payload["assessment"]
    items = per_item(study, record)
    references = {r["row_id"]: float(r["y_true"]) for r in rows_of(study / "artifacts" / "references.csv")}
    predicted = {r["row_id"]: float(r["y_pred"]) for r in observations_of(study, attempts["seasonal_7"])}
    assert len(items) == len(predicted) > 0
    for row_id, row in items.items():
        assert row["state"] == "scored" and row["reason"] == "" and row["criterion"] == "absolute_error"
        assert float(row["value"]) == abs(predicted[row_id] - references[row_id])
    n = len(items)
    assert record["counts"] == {
        "expected": n, "attempted": n, "produced": n, "scored": n,
        "correct": None, "incorrect": None, "unscored": 0, "errored": 0,
    }
    assert set(record["counts"]) == set(contracts.schema()["$defs"]["Counts"]["properties"])


def test_a_failed_item_and_a_missing_item_are_unscored_with_their_own_reason_never_zero(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    attempt = attempts["seasonal_7"]
    first, second = (r["row_id"] for r in observations_of(study, attempt)[:2])

    def edit(rows):
        rows[0].update(status="failed", reason="stopped", y_pred_raw="", y_pred="")
        rows[1].update(status="missing", reason="not_predicted", y_pred_raw="", y_pred="")
        return rows

    obs = construct(study, attempt, edit)
    code, payload, err = assess(study, obs, "regression_mae_v1", references_id(study))
    assert code == 0, (payload, err)
    record = payload["assessment"]
    items = per_item(study, record)
    assert (items[first]["state"], items[first]["value"], items[first]["reason"]) == ("unscored", "", "item_failed")
    assert (items[second]["state"], items[second]["value"], items[second]["reason"]) == ("unscored", "", "item_missing")
    assert items[first]["execution_status"] == "failed" and items[second]["execution_status"] == "missing"
    counts = record["counts"]
    n = counts["expected"]
    assert counts["unscored"] == 2 and counts["errored"] == 0 and counts["scored"] == n - 2
    assert counts["produced"] == n - 2 and counts["attempted"] == n - 1  # a failed Item was attempted, a missing one not
    assert counts["correct"] is None and counts["incorrect"] is None
    metric = record["metrics"][0]
    assert metric["denominator"] == n - 2 and metric["status"] == "scored"
    scored = [float(r["value"]) for r in items.values() if r["state"] == "scored"]
    assert metric["value"] == pytest.approx(sum(scored) / len(scored), abs=1e-9)  # the two Items are left out, not counted as 0


def test_an_expected_item_absent_from_the_observation_set_is_missing(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    dropped = observations_of(study, attempts["seasonal_7"])[0]["row_id"]
    obs = construct(study, attempts["seasonal_7"], lambda rows: rows[1:])
    _, payload, _ = assess(study, obs, "regression_mae_v1", references_id(study))
    row = per_item(study, payload["assessment"])[dropped]
    assert (row["execution_status"], row["state"], row["reason"]) == ("missing", "unscored", "item_missing")
    assert payload["assessment"]["counts"]["expected"] == len(per_item(study, payload["assessment"]))


def test_a_missing_reference_is_unscored_with_reference_missing_and_an_unreadable_one_with_reference_invalid(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    obs = observation_set_id(study, attempts["seasonal_7"])
    dropped, broken = (r["row_id"] for r in observations_of(study, attempts["seasonal_7"])[:2])

    def edit(rows):
        kept = [r for r in rows if r["row_id"] != dropped]
        for r in kept:
            if r["row_id"] == broken:
                r["y_true"] = "n/a"
        return kept

    construct_references(study, edit)
    code, payload, err = assess(study, obs, "regression_mae_v1", references_id(study))
    assert code == 0, (payload, err)
    items = per_item(study, payload["assessment"])
    assert (items[dropped]["state"], items[dropped]["value"], items[dropped]["reason"]) == ("unscored", "", "reference_missing")
    assert (items[broken]["state"], items[broken]["value"], items[broken]["reason"]) == ("unscored", "", "reference_invalid")
    assert payload["assessment"]["counts"]["unscored"] == 2


def test_an_unreadable_prediction_is_unscored_and_an_error_too_large_to_be_finite_is_errored(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    ids = [r["row_id"] for r in observations_of(study, attempts["seasonal_7"])[:2]]

    def edit(rows):
        rows[0].update(y_pred="not a number")
        rows[1].update(y_pred="1e308")
        return rows

    obs = construct(study, attempts["seasonal_7"], edit)

    def huge(rows):  # |1e308 - (-1e308)| overflows
        for r in rows:
            if r["row_id"] == ids[1]:
                r["y_true"] = "-1e308"
        return rows

    construct_references(study, huge)
    code, payload, err = assess(study, obs, "regression_rmse_v1", references_id(study))
    assert code == 0, (payload, err)
    items = per_item(study, payload["assessment"])
    assert (items[ids[0]]["state"], items[ids[0]]["reason"]) == ("unscored", "prediction_invalid")
    assert (items[ids[1]]["state"], items[ids[1]]["value"], items[ids[1]]["reason"]) == ("errored", "", "scoring_failed")
    counts = payload["assessment"]["counts"]
    assert (counts["unscored"], counts["errored"]) == (1, 1)
    assert counts["scored"] + counts["unscored"] + counts["errored"] == counts["expected"]


def test_an_assessment_with_no_scored_item_has_a_null_metric_with_a_reason_never_zero(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7")

    def edit(rows):
        for r in rows:
            r.update(status="failed", reason="stopped", y_pred_raw="", y_pred="")
        return rows

    obs = construct(study, attempts["seasonal_7"], edit)
    code, payload, err = assess(study, obs, "regression_mae_v1", references_id(study))
    assert code == 0, (payload, err)
    metric = payload["assessment"]["metrics"][0]
    assert (metric["value"], metric["status"], metric["reason"], metric["denominator"]) == (None, "unscored", "no_scored_item", 0)
    assert payload["assessment"]["counts"]["scored"] == 0


def test_mae_then_rmse_make_two_assessments_of_the_same_observation_set_and_change_nothing_kept(tmp_path):
    study, attempts = fresh_study(tmp_path, "ridge_v1")
    obs = observation_set_id(study, attempts["ridge_v1"])
    attempt_folder = study / "attempts" / attempts["ridge_v1"]["attempt_id"]
    before = snapshot(attempt_folder)
    _, first, _ = assess(study, obs, "regression_mae_v1", references_id(study))
    mid = snapshot(study / "assessments" / first["assessment"]["assessment_id"])
    _, second, _ = assess(study, obs, "regression_rmse_v1", references_id(study))
    a, b = first["assessment"], second["assessment"]
    assert a["assessment_id"] != b["assessment_id"] and a["observation_set_id"] == b["observation_set_id"] == obs
    assert (a["metrics"][0]["id"], b["metrics"][0]["id"]) == ("mae", "rmse")
    assert a["scorer"]["config_digest"] != b["scorer"]["config_digest"]
    assert snapshot(attempt_folder) == before
    assert snapshot(study / "assessments" / a["assessment_id"]) == mid
    # the same Scorer again is a third Assessment, not a replacement
    _, third, _ = assess(study, obs, "regression_mae_v1", references_id(study))
    assert third["assessment"]["assessment_id"] not in (a["assessment_id"], b["assessment_id"])
    assert third["assessment"]["metrics"] == a["metrics"]
    assert len(list((study / "assessments").iterdir())) == 3


@pytest.mark.parametrize("config", ["seasonal_7", "ridge_v1"])
def test_the_metrics_equal_the_librarys_compute_metrics_on_the_same_files_within_1e_9(tmp_path, config):
    from hypotrail.ml.metrics import compute_metrics

    study, attempts = fresh_study(tmp_path, config)
    attempt = attempts[config]
    expected = compute_metrics(
        study / "attempts" / attempt["attempt_id"] / "predictions.csv",
        study / "artifacts" / "references.csv",
        study / "artifacts" / "memberships.csv",
        BIKE,
        partition="dev",
    )["metrics"]
    obs = observation_set_id(study, attempt)
    for scorer, key in (("regression_mae_v1", "mae"), ("regression_rmse_v1", "rmse")):
        _, payload, _ = assess(study, obs, scorer, references_id(study))
        metric = payload["assessment"]["metrics"][0]
        assert metric["id"] == key and metric["unit"] == expected[key]["unit"] and metric["direction"] == "lower_is_better"
        assert abs(metric["value"] - expected[key]["value"]) <= 1e-9
        assert metric["status"] == "scored" and metric["denominator"] == payload["assessment"]["counts"]["scored"]
