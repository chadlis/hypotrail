"""Ticket #33: `ridge_v1` predictions on `dev`, fitted on `train` only, clipped at zero."""

import csv
import datetime
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from hypotrail.ml.memberships import derive_memberships
from hypotrail.ml.ridge import (
    build_inputs,
    fit_configuration,
    load_configuration,
    predict_partition,
    write_outputs,
)

from _ml_helpers import fit_probe, fitted_row_ids

ROOT = Path(__file__).resolve().parent.parent
BIKE = ROOT / "examples" / "bike_day"
CALENDAR = ["mnth", "weekday", "holiday", "workingday"]
LAGS = ["lag_1", "lag_7", "mean_previous_7"]


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def fitted():
    return fit_configuration(BIKE, "ridge_v1")


def copy_workload(tmp_path):
    target = tmp_path / "bike"
    shutil.copytree(BIKE, target)
    return target


# --- the pipeline ML-02 specifies -------------------------------------------------


def test_pipeline_is_the_one_ml_02_specifies(fitted):
    pipeline = fitted.pipeline
    assert isinstance(pipeline, Pipeline)
    preprocessor, ridge = (step for _, step in pipeline.steps)
    assert isinstance(preprocessor, ColumnTransformer)
    assert isinstance(ridge, Ridge)
    assert ridge.get_params()["alpha"] == 1.0
    assert ridge.get_params()["fit_intercept"] is True
    assert ridge.get_params()["solver"] == "svd"

    by_type = {type(t): (t, cols) for _, t, cols in preprocessor.transformers}
    encoder, encoder_columns = by_type[OneHotEncoder]
    scaler, scaler_columns = by_type[StandardScaler]
    assert encoder.handle_unknown == "ignore"
    assert encoder.sparse_output is False
    assert [fitted.columns[i] for i in encoder_columns] == CALENDAR
    assert [fitted.columns[i] for i in scaler_columns] == LAGS
    assert len(preprocessor.transformers) == 2  # no passthrough, no other column


def test_everything_is_float64(fitted):
    inputs = build_inputs(BIKE, fitted.config_id, "dev")
    assert inputs.matrix.dtype == np.float64
    assert fitted.pipeline.steps[-1][1].coef_.dtype == np.float64
    assert fitted.pipeline.steps[0][1].transformers[0][1].dtype == np.float64


# --- inputs: lags and calendar ----------------------------------------------------


def test_model_inputs_are_the_lags_and_the_verified_calendar_columns(fitted):
    rows = read_csv(BIKE / "data" / "day.csv")
    by_date = {r["dteday"]: i for i, r in enumerate(rows)}
    inputs = build_inputs(BIKE, fitted.config_id, "dev")

    assert inputs.columns == LAGS + CALENDAR  # no dteday, no weather, no other count
    assert len(inputs.row_ids) == 182
    for row_id, line in zip(inputs.row_ids, inputs.matrix):
        date = row_id.removeprefix("bike-day:")
        i = by_date[date]
        cnt = [float(r["cnt"]) for r in rows]
        assert line[0] == cnt[i - 1]
        assert line[1] == cnt[i - 7]
        assert line[2] == sum(cnt[i - 7 : i]) / 7
        assert list(line[3:]) == [float(rows[i][c]) for c in CALENDAR]


def test_calendar_is_read_from_the_file_not_recomputed_from_dteday(tmp_path):
    workload = copy_workload(tmp_path)
    path = workload / "data" / "day.csv"
    rows = read_csv(path)
    target = next(r for r in rows if r["dteday"] == "2012-03-05")
    target["mnth"], target["holiday"] = "11", "1"  # not what dteday would give
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    inputs = build_inputs(workload, "ridge_v1", "dev")
    line = inputs.matrix[inputs.row_ids.index("bike-day:2012-03-05")]
    assert line[inputs.columns.index("mnth")] == 11.0
    assert line[inputs.columns.index("holiday")] == 1.0


def test_shuffling_the_rows_changes_no_input_and_no_prediction(tmp_path, fitted):
    workload = copy_workload(tmp_path)
    path = workload / "data" / "day.csv"
    rows = read_csv(path)
    random.Random(11).shuffle(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    assert build_inputs(workload, "ridge_v1", "dev").matrix.tolist() == build_inputs(
        BIKE, "ridge_v1", "dev"
    ).matrix.tolist()
    shuffled = predict_partition(fit_configuration(workload, "ridge_v1"), "dev")
    assert shuffled == predict_partition(fitted, "dev")


# --- fitting on train only (T05) --------------------------------------------------


def test_every_fit_receives_exactly_the_train_items():
    memberships = derive_memberships(BIKE)
    train_ids = {m["row_id"] for m in memberships if m["partition"] == "train"}
    assert len(train_ids) == 358

    with fit_probe() as probe:
        fitted = fit_configuration(BIKE, "ridge_v1")

    assert fitted.train_row_ids == sorted(train_ids)
    classes = {label.split(".")[0] for label in probe.calls}
    assert {"Pipeline", "ColumnTransformer", "OneHotEncoder", "StandardScaler", "Ridge"} <= classes
    assert fitted_row_ids(probe, BIKE, "ridge_v1") == train_ids  # no dev or public_check Item

    full_width = len(LAGS) + len(CALENDAR)
    for label, X in probe.inputs:
        assert X.shape[0] == 358, label
        cls_name = label.split(".")[0]
        if cls_name in ("Pipeline", "ColumnTransformer"):
            assert X.shape[1] == full_width, label
        elif cls_name == "OneHotEncoder":
            assert X.shape[1] == len(CALENDAR)
        elif cls_name == "StandardScaler":
            assert X.shape[1] == len(LAGS)
    # the inner estimators see the train rows in the same order as the pipeline
    pipeline_rows = next(X for c, X in probe.inputs if c == "Pipeline.fit")
    scaler_rows = next(X for c, X in probe.inputs if c.startswith("StandardScaler"))
    encoder_rows = next(X for c, X in probe.inputs if c.startswith("OneHotEncoder"))
    assert np.array_equal(scaler_rows, pipeline_rows[:, :3])
    assert np.array_equal(encoder_rows, pipeline_rows[:, 3:])


def test_predicting_dev_or_public_check_fits_nothing(fitted):
    before = fitted.pipeline.steps[-1][1].coef_.copy()

    with fit_probe(strict=True) as probe:
        dev = predict_partition(fitted, "dev")
        check = predict_partition(fitted, "public_check")

    assert probe.calls == []
    assert len(dev) == 182 and len(check) == 184
    assert np.array_equal(fitted.pipeline.steps[-1][1].coef_, before)


# --- predictions, post-processing, files ------------------------------------------


def test_dev_predictions_are_182_and_y_pred_is_the_clipped_raw(fitted, tmp_path):
    write_outputs(BIKE, tmp_path, "ridge_v1", "dev")
    rows = read_csv(tmp_path / "predictions.csv")

    assert list(rows[0]) == ["row_id", "y_pred_raw", "y_pred", "config_id"]
    assert len(rows) == 182
    dev_ids = {m["row_id"] for m in derive_memberships(BIKE) if m["partition"] == "dev"}
    assert {r["row_id"] for r in rows} == dev_ids
    assert {r["config_id"] for r in rows} == {"ridge_v1"}
    for r in rows:
        assert float(r["y_pred"]) == max(0.0, float(r["y_pred_raw"]))


def test_effective_parameters_are_recorded_next_to_the_predictions(tmp_path):
    predictions = write_outputs(BIKE, tmp_path, "ridge_v1", "dev")
    params_path = predictions.parent / "sklearn_params.json"
    params = json.loads(params_path.read_text(encoding="utf-8"))

    ridge = params["ridge"]
    assert ridge["class"] == "sklearn.linear_model.Ridge"
    assert ridge["params"]["alpha"] == 1.0
    assert ridge["params"]["solver"] == "svd"
    assert ridge["params"]["fit_intercept"] is True
    assert ridge["params"]["tol"] == 0.0001  # a default nobody declared is still recorded
    assert params["encoder"]["params"]["handle_unknown"] == "ignore"
    assert params["encoder"]["params"]["sparse_output"] is False
    assert params["scaler"]["params"]["with_mean"] is True


def test_effective_parameters_include_the_column_transformer_and_the_pipeline(tmp_path):
    predictions = write_outputs(BIKE, tmp_path, "ridge_v1", "dev")
    params = json.loads((predictions.parent / "sklearn_params.json").read_text(encoding="utf-8"))

    preprocessor = params["preprocessor"]
    assert preprocessor["class"] == "sklearn.compose.ColumnTransformer"
    assert preprocessor["params"]["remainder"] == "drop"  # a default nobody declared is still recorded
    assert preprocessor["params"]["verbose_feature_names_out"] is True
    pipeline = params["pipeline"]
    assert pipeline["class"] == "sklearn.pipeline.Pipeline"
    assert pipeline["params"]["memory"] is None
    assert pipeline["params"]["verbose"] is False


# --- the core stays free of scikit-learn ------------------------------------------


def test_importing_the_core_and_the_stdlib_ml_modules_loads_no_scikit_learn():
    code = (
        "import sys\n"
        "import hypotrail.core.data, hypotrail.ml.memberships, hypotrail.ml.lags, hypotrail.ml.predictions\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in {'sklearn', 'numpy'}))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"


# --- the Configuration and the Partition are parameters ----------------------------


def test_the_config_id_in_the_predictions_is_the_declared_key(tmp_path):
    workload = copy_workload(tmp_path)
    path = workload / "workload.json"
    declaration = json.loads(path.read_text(encoding="utf-8"))
    declaration["configurations"]["ridge_b"] = declaration["configurations"].pop("ridge_v1")
    path.write_text(json.dumps(declaration), encoding="utf-8")

    out = write_outputs(workload, tmp_path / "out", "ridge_b", "dev")

    assert {r["config_id"] for r in read_csv(out)} == {"ridge_b"}


def test_the_partition_to_predict_is_a_parameter(tmp_path):
    out = write_outputs(BIKE, tmp_path, "ridge_v1", "public_check")
    rows = read_csv(out)
    public_ids = {m["row_id"] for m in derive_memberships(BIKE) if m["partition"] == "public_check"}
    assert {r["row_id"] for r in rows} == public_ids and len(rows) == 184


def test_predict_partition_returns_raw_values_clipping_happens_when_predictions_are_written(fitted):
    rows = predict_partition(fitted, "dev")
    assert all(set(r) == {"row_id", "y_pred_raw"} for r in rows)


def test_the_declared_clip_bound_reaches_the_written_predictions(tmp_path):
    workload = copy_workload(tmp_path)
    path = workload / "workload.json"
    declaration = json.loads(path.read_text(encoding="utf-8"))
    declaration["configurations"]["ridge_v1"]["post_processing"]["clip_min"] = 3000
    path.write_text(json.dumps(declaration), encoding="utf-8")

    rows = read_csv(write_outputs(workload, tmp_path / "out", "ridge_v1", "dev"))

    assert min(float(r["y_pred"]) for r in rows) == 3000.0
    assert any(float(r["y_pred_raw"]) < 3000 for r in rows)
