"""The `ridge_v1` Configuration of the temporal regression Track.

This is the Track's scikit-learn part: importing it loads scikit-learn and
NumPy, and nothing in the core imports it. scikit-learn owns the encoding, the
scaling and the fitting; this module only builds the table of inputs and wires
the declared estimators together. Everything it needs comes from the Workload's
declaration (`configurations.<id>` in `workload.json`): the lag features, the
calendar columns, the estimators' settings, the Partition to fit on and the
post-processing.

The lags are computed from dates (`hypotrail.ml.lags`), the calendar columns
are read from the verified data file as they are, and the Items of a Partition
come from `hypotrail.ml.memberships`, always in date order. The pipeline is
fitted once, on the declared fit Partition only. Predicting any other Partition
never fits anything.
"""

import csv
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
from hypotrail.ml.lags import compute_lags
from hypotrail.ml.memberships import derive_memberships, load_declaration
from hypotrail.ml.predictions import clip_below, write_predictions
from hypotrail.ml.series import read_target_series

PARAMETERS_NAME = "sklearn_params.json"
PREDICTED_PARTITION = "dev"


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="ridge", details=details)


@dataclass
class ModelInputs:
    row_ids: list
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
    try:
        configuration = declaration["configurations"][config_id]
    except KeyError:
        raise _refuse("CONFIGURATION_NOT_DECLARED", f"no configuration {config_id!r} is declared", config_id=config_id) from None
    return {"declaration": declaration, "configuration": configuration}


def _read_rows_by_date(workload_dir: Path, declaration: dict) -> dict:
    column = declaration["date_column"]
    with (Path(workload_dir) / declaration["data_file"]).open(newline="", encoding="utf-8") as handle:
        return {datetime.date.fromisoformat(row[column]): row for row in csv.DictReader(handle)}


def _columns(configuration: dict) -> list:
    return [f["name"] for f in configuration["lag_features"]] + list(configuration["calendar_columns"])


def build_inputs(workload_dir: Path, config_id: str, partition: str) -> ModelInputs:
    loaded = load_configuration(workload_dir, config_id)
    declaration, configuration = loaded["declaration"], loaded["configuration"]
    rows = _read_rows_by_date(workload_dir, declaration)
    target = read_target_series(workload_dir, declaration)
    lag_names = [f["name"] for f in configuration["lag_features"]]

    row_ids, lines = [], []
    for item in derive_memberships(workload_dir):
        if item["partition"] != partition:
            continue
        day = datetime.date.fromisoformat(item["date"])
        lags = compute_lags(target, day, configuration["lag_features"])
        calendar = [float(rows[day][c]) for c in configuration["calendar_columns"]]
        row_ids.append(item["row_id"])
        lines.append([lags[n] for n in lag_names] + calendar)
    matrix = np.array(lines, dtype=np.float64).reshape(len(lines), len(_columns(configuration)))
    return ModelInputs(row_ids, _columns(configuration), matrix)


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
    fit_partition = configuration["fit_partition"]
    inputs = build_inputs(workload_dir, config_id, fit_partition)
    target = read_target_series(workload_dir, declaration)
    y = np.array(
        [target[datetime.date.fromisoformat(r.removeprefix(f"{declaration['id_prefix']}:"))] for r in inputs.row_ids],
        dtype=np.float64,
    )
    pipeline = build_pipeline(configuration)
    pipeline.fit(inputs.matrix, y)
    return FittedConfiguration(
        Path(workload_dir), config_id, configuration, pipeline, inputs.columns, sorted(inputs.row_ids)
    )


def post_process(raw_values, configuration: dict) -> list[dict]:
    raw = [float(v) for v in raw_values]
    clipped, _ = clip_below(raw, configuration["post_processing"]["clip_min"])
    return [{"y_pred_raw": r, "y_pred": c} for r, c in zip(raw, clipped)]


def predict_partition(fitted: FittedConfiguration, partition: str) -> list[dict]:
    """Predict a Partition with the parameters already fitted; nothing is fitted here."""
    inputs = build_inputs(fitted.workload_dir, fitted.config_id, partition)
    raw = fitted.pipeline.predict(inputs.matrix)
    return [
        {"row_id": row_id, **values}
        for row_id, values in zip(inputs.row_ids, post_process(raw, fitted.configuration))
    ]


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


def write_outputs(workload_dir: Path, out_dir: Path, config_id: str = "ridge_v1") -> Path:
    """Fit on the declared fit Partition, predict `dev`, write `predictions.csv` and the parameters file."""
    fitted = fit_configuration(workload_dir, config_id)
    rows = predict_partition(fitted, PREDICTED_PARTITION)
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
