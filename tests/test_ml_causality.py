"""Ticket #35 (SPEC ML-05, T04): changing `cnt` at t or later changes neither the prediction for t
nor the parameters `ridge_v1` fitted on `train`.

Every run starts from a table on disk: the changed `day.csv` is written into a fresh copy of the
Workload, and lags, Partitions, fit and prediction are all recomputed from it. Nothing is edited
after the features are built and no fitted pipeline is reused. "Unchanged" means exactly equal.
Predictions at `public_check` dates are made here, and no metric is computed on that Partition.
"""

import csv
import datetime
import shutil
from pathlib import Path

import numpy as np
import pytest

import hypotrail.ml.metrics as metrics
from hypotrail.ml.baselines import write_seasonal_baseline
from hypotrail.ml.memberships import derive_memberships
from hypotrail.ml.ridge import fit_configuration, predict_partition

ROOT = Path(__file__).resolve().parent.parent
BIKE = ROOT / "examples" / "bike_day"

# First, middle and last date of each of `dev` and `public_check`.
DATES = [
    "2012-01-01", "2012-04-01", "2012-06-30",
    "2012-07-01", "2012-10-01", "2012-12-31",
]


def altered(value: int) -> int:
    return value * 3 + 1000  # never equal to the original


def make_workload(tmp_path: Path, name: str, change_from=None, only=None) -> Path:
    """A copy of the Workload whose `cnt` is changed.

    `change_from=t` changes `cnt` at t and at every later date; `only=d` changes a single date.
    """
    target = tmp_path / name
    (target / "data").mkdir(parents=True)
    shutil.copy(BIKE / "workload.json", target / "workload.json")
    with (BIKE / "data" / "day.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields, rows = reader.fieldnames, list(reader)
    for row in rows:
        hit = (change_from is not None and row["dteday"] >= change_from) or row["dteday"] == only
        if hit:
            row["cnt"] = str(altered(int(row["cnt"])))
    with (target / "data" / "day.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return target


def partition_of(workload: Path, day: str) -> str:
    return next(m["partition"] for m in derive_memberships(workload) if m["date"] == day)


def seasonal_prediction(workload: Path, day: str, out_dir: Path) -> dict:
    write_seasonal_baseline(workload, out_dir, partition=partition_of(workload, day))
    with (out_dir / "predictions.csv").open(newline="", encoding="utf-8") as handle:
        rows = {r["row_id"]: r for r in csv.DictReader(handle)}
    row = rows[f"bike-day:{day}"]
    return {"y_pred_raw": row["y_pred_raw"], "y_pred": row["y_pred"]}


def ridge_run(workload: Path, day: str) -> tuple[dict, dict]:
    """Fit on `train` from this table, predict the Partition of `day`; return (prediction, fitted state)."""
    fitted = fit_configuration(workload, "ridge_v1")
    rows = {r["row_id"]: r for r in predict_partition(fitted, partition_of(workload, day))}
    row = rows[f"bike-day:{day}"]
    pre = fitted.pipeline.named_steps["preprocessor"]
    scaler = pre.named_transformers_["scaler"]
    encoder = pre.named_transformers_["encoder"]
    ridge = fitted.pipeline.named_steps["ridge"]
    state = {
        "train_row_ids": fitted.train_row_ids,
        "coef": ridge.coef_,
        "intercept": ridge.intercept_,
        "scaler_mean": scaler.mean_,
        "scaler_var": scaler.var_,
        "scaler_scale": scaler.scale_,
        "encoder_categories": encoder.categories_,
    }
    return {"y_pred_raw": row["y_pred_raw"], "y_pred": row["y_pred"]}, state


def assert_state_equal(left: dict, right: dict):
    assert left.keys() == right.keys()
    assert left["train_row_ids"] == right["train_row_ids"]
    for key in ("coef", "intercept", "scaler_mean", "scaler_var", "scaler_scale"):
        assert np.array_equal(left[key], right[key]), key
    assert len(left["encoder_categories"]) == len(right["encoder_categories"])
    for a, b in zip(left["encoder_categories"], right["encoder_categories"]):
        assert np.array_equal(a, b)


@pytest.fixture(autouse=True)
def no_metric_is_computed(monkeypatch):
    """AC3: the only metric entry point fails if this test ever calls it."""
    def refuse(*args, **kwargs):
        raise AssertionError("a metric was computed in the causality test")
    monkeypatch.setattr(metrics, "compute_metrics", refuse)


@pytest.fixture(scope="module")
def original_ridge(tmp_path_factory):
    original = make_workload(tmp_path_factory.mktemp("orig"), "orig")
    return {day: ridge_run(original, day) for day in DATES}


def test_the_dates_cover_dev_and_public_check():
    assert {partition_of(BIKE, d) for d in DATES} == {"dev", "public_check"}


@pytest.mark.parametrize("day", DATES)
def test_seasonal_7_prediction_for_t_ignores_cnt_from_t_on(tmp_path, day):
    original = make_workload(tmp_path, "orig")
    changed = make_workload(tmp_path, "changed", change_from=day)
    assert seasonal_prediction(original, day, tmp_path / "a") == seasonal_prediction(changed, day, tmp_path / "b")


@pytest.mark.parametrize("day", DATES)
def test_ridge_v1_prediction_for_t_and_train_parameters_ignore_cnt_from_t_on(tmp_path, original_ridge, day):
    changed = make_workload(tmp_path, "changed", change_from=day)
    prediction, state = ridge_run(changed, day)
    original_prediction, original_state = original_ridge[day]
    assert prediction == original_prediction
    assert_state_equal(state, original_state)


# --- controls: the harness is sensitive, so "unchanged" means something -----------


def test_control_changing_cnt_the_day_before_t_changes_the_ridge_prediction(tmp_path, original_ridge):
    day = "2012-04-01"
    before = (datetime.date.fromisoformat(day) - datetime.timedelta(days=1)).isoformat()
    changed = make_workload(tmp_path, "changed", only=before)
    assert ridge_run(changed, day)[0] != original_ridge[day][0]


def test_control_changing_cnt_seven_days_before_t_changes_the_seasonal_prediction(tmp_path):
    day = "2012-04-01"
    week = (datetime.date.fromisoformat(day) - datetime.timedelta(days=7)).isoformat()
    original = make_workload(tmp_path, "orig")
    changed = make_workload(tmp_path, "changed", only=week)
    assert seasonal_prediction(original, day, tmp_path / "a") != seasonal_prediction(changed, day, tmp_path / "b")


def test_control_changing_cnt_in_train_changes_the_fitted_parameters(tmp_path, original_ridge):
    changed = make_workload(tmp_path, "changed", only="2011-06-15")
    _, state = ridge_run(changed, "2012-04-01")
    assert not np.array_equal(state["coef"], original_ridge["2012-04-01"][1]["coef"])
