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
    post_process,
    predict_partition,
    write_outputs,
)

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


class FitSpy:
    """Hooks every fit entry point the pipeline calls and records what it receives."""

    TARGETS = [
        (Pipeline, ("fit", "fit_transform", "fit_predict")),
        (ColumnTransformer, ("fit", "fit_transform")),
        (OneHotEncoder, ("fit", "fit_transform", "partial_fit")),
        (StandardScaler, ("fit", "fit_transform", "partial_fit")),
        (Ridge, ("fit",)),
    ]

    def __init__(self, monkeypatch):
        self.calls = []
        for cls, names in self.TARGETS:
            for name in names:
                original = getattr(cls, name, None)
                if original is None:
                    continue
                monkeypatch.setattr(cls, name, self._wrap(cls.__name__, name, original))

    def _wrap(self, cls_name, name, original):
        def spy(estimator, X, *args, **kwargs):
            self.calls.append((cls_name, name, np.array(X, copy=True)))
            return original(estimator, X, *args, **kwargs)

        return spy


def test_every_fit_receives_exactly_the_train_items(monkeypatch):
    memberships = derive_memberships(BIKE)
    train_ids = {m["row_id"] for m in memberships if m["partition"] == "train"}
    assert len(train_ids) == 358
    other = {m["row_id"] for m in memberships if m["partition"] != "train"}

    # The identity of a received row is read back from the inputs of all Items.
    columns = None
    owner = {}
    for partition in ("train", "dev", "public_check"):
        inputs = build_inputs(BIKE, "ridge_v1", partition)
        columns = inputs.columns
        for row_id, line in zip(inputs.row_ids, inputs.matrix):
            assert line.tobytes() not in owner  # rows are told apart by their values
            owner[line.tobytes()] = row_id

    spy = FitSpy(monkeypatch)
    fitted = fit_configuration(BIKE, "ridge_v1")

    assert fitted.train_row_ids == sorted(train_ids)
    classes = {name for name, _, _ in spy.calls}
    assert {"Pipeline", "ColumnTransformer", "OneHotEncoder", "StandardScaler", "Ridge"} <= classes

    full_width = len(columns)
    for cls_name, method, X in spy.calls:
        assert X.shape[0] == 358, (cls_name, method)
        if cls_name in ("Pipeline", "ColumnTransformer"):
            assert X.shape[1] == full_width
            seen = {owner[line.tobytes()] for line in X}
            assert seen == train_ids and not (seen & other), (cls_name, method)
        elif cls_name == "OneHotEncoder":
            assert X.shape[1] == len(CALENDAR)
        elif cls_name == "StandardScaler":
            assert X.shape[1] == len(LAGS)
    # the inner estimators see the train rows in the same order as the pipeline
    pipeline_rows = next(X for c, m, X in spy.calls if c == "Pipeline")
    scaler_rows = next(X for c, m, X in spy.calls if c == "StandardScaler")
    encoder_rows = next(X for c, m, X in spy.calls if c == "OneHotEncoder")
    assert np.array_equal(scaler_rows, pipeline_rows[:, :3])
    assert np.array_equal(encoder_rows, pipeline_rows[:, 3:])


def test_predicting_dev_or_public_check_fits_nothing(fitted, monkeypatch):
    spy = FitSpy(monkeypatch)
    before = fitted.pipeline.steps[-1][1].coef_.copy()

    dev = predict_partition(fitted, "dev")
    check = predict_partition(fitted, "public_check")

    assert spy.calls == []
    assert len(dev) == 182 and len(check) == 184
    assert np.array_equal(fitted.pipeline.steps[-1][1].coef_, before)


# --- predictions, post-processing, files ------------------------------------------


def test_dev_predictions_are_182_and_y_pred_is_the_clipped_raw(fitted, tmp_path):
    write_outputs(BIKE, tmp_path)
    rows = read_csv(tmp_path / "predictions.csv")

    assert list(rows[0]) == ["row_id", "y_pred_raw", "y_pred", "config_id"]
    assert len(rows) == 182
    dev_ids = {m["row_id"] for m in derive_memberships(BIKE) if m["partition"] == "dev"}
    assert {r["row_id"] for r in rows} == dev_ids
    assert {r["config_id"] for r in rows} == {"ridge_v1"}
    for r in rows:
        assert float(r["y_pred"]) == max(0.0, float(r["y_pred_raw"]))


def test_clipping_zeroes_a_negative_raw_prediction_and_keeps_the_raw_value():
    config = load_configuration(BIKE, "ridge_v1")["configuration"]
    processed = post_process([-250.5, 0.0, 17.0], config)
    assert processed == [
        {"y_pred_raw": -250.5, "y_pred": 0.0},
        {"y_pred_raw": 0.0, "y_pred": 0.0},
        {"y_pred_raw": 17.0, "y_pred": 17.0},
    ]


def test_clipping_is_a_declared_setting_not_a_constant(tmp_path):
    workload = copy_workload(tmp_path)
    path = workload / "workload.json"
    declaration = json.loads(path.read_text(encoding="utf-8"))
    declaration["configurations"]["ridge_v1"]["post_processing"]["clip_min"] = 100
    path.write_text(json.dumps(declaration), encoding="utf-8")

    config = load_configuration(workload, "ridge_v1")["configuration"]
    assert post_process([-5.0, 50.0, 150.0], config)[0:3] == [
        {"y_pred_raw": -5.0, "y_pred": 100.0},
        {"y_pred_raw": 50.0, "y_pred": 100.0},
        {"y_pred_raw": 150.0, "y_pred": 150.0},
    ]
    declared = json.loads((BIKE / "workload.json").read_text(encoding="utf-8"))
    assert declared["configurations"]["ridge_v1"]["post_processing"] == {"clip_min": 0}


def test_effective_parameters_are_recorded_next_to_the_predictions(tmp_path):
    predictions = write_outputs(BIKE, tmp_path)
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


# --- the core stays free of scikit-learn ------------------------------------------


def test_importing_the_core_and_the_stdlib_ml_modules_loads_no_scikit_learn():
    code = (
        "import sys\n"
        "import hypotrail.core.data, hypotrail.ml.memberships, hypotrail.ml.lags, hypotrail.ml.predictions\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in {'sklearn', 'numpy'}))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"
