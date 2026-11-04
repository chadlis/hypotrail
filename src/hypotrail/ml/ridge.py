"""The `ridge_v1` Configuration of the temporal regression Track.

This is the Track's scikit-learn part: importing it loads scikit-learn and
NumPy, and nothing in the core imports it. scikit-learn owns the encoding, the
scaling and the fitting; this module only builds the table of inputs and wires
the declared estimators together. Everything it needs comes from the Workload's
declaration (`configurations.<id>` in `workload.json`): the lag features, the
calendar columns, the estimators' settings, the post-processing. The
Partition to fit on is the Workload's, not the Configuration's.

The lags are computed from dates (`hypotrail.ml.lags`), the calendar columns
are read from the verified data file as they are, and the Items of a Partition
come from `hypotrail.ml.memberships`, always in date order. The pipeline is
fitted once, on the declared fit Partition only. Predicting any other Partition
never fits anything.
"""

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.configuration import declared_configuration, validate_configuration
from hypotrail.ml.lags import compute_lags
from hypotrail.ml.memberships import derive_memberships, load_declaration
from hypotrail.ml.predictions import write_predictions
from hypotrail.ml.series import read_target_series
from hypotrail.ml.table import read_table

PARAMETERS_NAME = "sklearn_params.json"


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="ridge", details=details)


@dataclass
class ModelInputs:
    row_ids: list
    dates: list
    columns: list
    matrix: np.ndarray


@dataclass
class FittedConfiguration:
    workload_dir: Path
    config_id: str
    configuration: dict
    pipeline: Pipeline
    columns: list
    train_row_ids: list


def load_configuration(workload_dir: Path, config_id: str) -> dict:
    declaration = load_declaration(workload_dir)
    configuration = declared_configuration(declaration, config_id)
    validate_configuration(declaration, config_id, configuration)
    return {"declaration": declaration, "configuration": configuration}


def _columns(configuration: dict) -> list:
    return [f["name"] for f in configuration["lag_features"]] + list(configuration["calendar_columns"])


def build_inputs(workload_dir: Path, config_id: str, partition: str) -> ModelInputs:
    loaded = load_configuration(workload_dir, config_id)
    declaration, configuration = loaded["declaration"], loaded["configuration"]
    rows = read_table(workload_dir, declaration, configuration["calendar_columns"])
    target = read_target_series(workload_dir, declaration)
    lag_names = [f["name"] for f in configuration["lag_features"]]

    row_ids, dates, lines = [], [], []
    for item in derive_memberships(workload_dir):
        if item["partition"] != partition:
            continue
        day = datetime.date.fromisoformat(item["date"])
        lags = compute_lags(target, day, configuration["lag_features"])
        calendar = [float(rows[day][c]) for c in configuration["calendar_columns"]]
        row_ids.append(item["row_id"])
        dates.append(day)
        lines.append([lags[n] for n in lag_names] + calendar)
    matrix = np.array(lines, dtype=np.float64).reshape(len(lines), len(_columns(configuration)))
    return ModelInputs(row_ids, dates, _columns(configuration), matrix)


def build_pipeline(configuration: dict) -> Pipeline:
    columns = _columns(configuration)
    encoder, scaler, ridge = configuration["encoder"], configuration["scaler"], configuration["ridge"]
    preprocessor = ColumnTransformer([
        (
            "encoder",
            OneHotEncoder(handle_unknown=encoder["handle_unknown"], sparse_output=encoder["sparse_output"]),
            [columns.index(c) for c in encoder["columns"]],
        ),
        ("scaler", StandardScaler(), [columns.index(c) for c in scaler["columns"]]),
    ])
    return Pipeline([
        ("preprocessor", preprocessor),
        ("ridge", Ridge(alpha=ridge["alpha"], fit_intercept=ridge["fit_intercept"], solver=ridge["solver"])),
    ])


def fit_configuration(workload_dir: Path, config_id: str) -> FittedConfiguration:
    """Fit the declared pipeline once, on the declared fit Partition's Items."""
    loaded = load_configuration(workload_dir, config_id)
    declaration, configuration = loaded["declaration"], loaded["configuration"]
    fit_partition = declaration["fit_partition"]
    inputs = build_inputs(workload_dir, config_id, fit_partition)
    target = read_target_series(workload_dir, declaration)
    y = np.array([target[day] for day in inputs.dates], dtype=np.float64)
    pipeline = build_pipeline(configuration)
    pipeline.fit(inputs.matrix, y)
    return FittedConfiguration(
        Path(workload_dir), config_id, configuration, pipeline, inputs.columns, sorted(inputs.row_ids)
    )


def predict_partition(fitted: FittedConfiguration, partition: str) -> list[dict]:
    """Raw predictions of a Partition with the parameters already fitted; nothing is fitted here.

    Clipping is applied once, when the predictions are written (`predictions.write_predictions`).
    """
    inputs = build_inputs(fitted.workload_dir, fitted.config_id, partition)
    raw = fitted.pipeline.predict(inputs.matrix)
    return [{"row_id": row_id, "y_pred_raw": float(value)} for row_id, value in zip(inputs.row_ids, raw)]


def _dotted_class(cls) -> str:
    public = [part for part in cls.__module__.split(".") if not part.startswith("_")]
    return ".".join(public + [cls.__qualname__])


def _json_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, type):
        return f"{value.__module__}.{value.__qualname__}"
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return repr(value)


def effective_parameters(fitted: FittedConfiguration) -> dict:
    preprocessor = fitted.pipeline.named_steps["preprocessor"]
    estimators = {
        "pipeline": fitted.pipeline,
        "preprocessor": preprocessor,
        "encoder": preprocessor.named_transformers_["encoder"],
        "scaler": preprocessor.named_transformers_["scaler"],
        "ridge": fitted.pipeline.named_steps["ridge"],
    }
    return {
        name: {
            "class": _dotted_class(type(estimator)),
            "params": {k: _json_value(v) for k, v in estimator.get_params(deep=False).items()},
        }
        for name, estimator in estimators.items()
    }


def write_outputs(workload_dir: Path, out_dir: Path, config_id: str, partition: str) -> Path:
    """Fit on the declared fit Partition, predict `partition`, write `predictions.csv` and the parameters file."""
    fitted = fit_configuration(workload_dir, config_id)
    rows = predict_partition(fitted, partition)
    path = write_predictions(
        out_dir,
        config_id,
        [r["row_id"] for r in rows],
        [r["y_pred_raw"] for r in rows],
        clip_min=fitted.configuration["post_processing"]["clip_min"],
    )
    (path.parent / PARAMETERS_NAME).write_text(
        json.dumps(effective_parameters(fitted), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path
