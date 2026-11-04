"""Metrics of a predictions CSV of the temporal regression Track, standard library only.

Targets come from the separate References artifact and are joined to the
predictions by `row_id`, never by position. Metrics use `y_pred`. The unit is the
one the Workload declares (`target_unit`). A request on `public_check` is refused
until the Exposure journal exists (SPEC section 2; the slice keeps no such journal yet).
"""

import csv
import math
from pathlib import Path

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.memberships import load_declaration
from hypotrail.ml.partitions import PUBLIC_CHECK

DIRECTION = "lower_is_better"
PRIMARY = "mae"


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="metrics", details=details)


def refuse_public_check(partition: str, code: str, what: str, stage: str = "metrics") -> None:
    """The one guard of `public_check`: a metric or a Comparison there is refused, whatever the caller."""
    if partition == PUBLIC_CHECK:
        raise InvalidInputError(
            code,
            f"{what} on {PUBLIC_CHECK} is refused: no Exposure journal exists yet",
            stage=stage,
            details={"partition": partition},
        )


def declared_unit(declaration: dict) -> str:
    if "target_unit" not in declaration:
        raise _refuse("DECLARATION_INCOMPLETE", "declaration lacks 'target_unit'", key="target_unit")
    return declaration["target_unit"]


def declared_partition(declaration: dict, partition: str) -> None:
    if partition not in declaration["partitions"]:
        raise _refuse("PARTITION_NOT_DECLARED", f"the Workload declares no Partition {partition!r}", partition=partition)


def _read(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _unique_by_row_id(rows, source):
    by_id = {}
    for row in rows:
        if row["row_id"] in by_id:
            raise _refuse("DUPLICATE_ROW_ID", f"{row['row_id']} appears twice in {source}", row_id=row["row_id"])
        by_id[row["row_id"]] = row
    return by_id


def _finite(cell, row_id, column):
    try:
        value = float(cell)
    except (TypeError, ValueError):
        raise _refuse("NOT_A_NUMBER", f"{column} is not a number for {row_id}", row_id=row_id) from None
    if not math.isfinite(value):
        raise _refuse("NON_FINITE_NUMBER", f"{column} is not finite for {row_id}", row_id=row_id)
    return value


def read_by_row_id(path, source) -> dict:
    """The rows of a CSV file keyed by `row_id`; a repeated id is refused."""
    return _unique_by_row_id(_read(path), source)


def score_items(predictions: dict, references: dict, memberships: dict, partition: str) -> list[dict]:
    """The Items of `partition`, scored once, in row_id order. Inputs are dicts keyed by `row_id`.

    Predictions must be exactly the Partition's Items, and each needs a reference.
    """
    expected = {row_id for row_id, m in memberships.items() if m["partition"] == partition}
    if set(predictions) != expected:
        raise _refuse(
            "PREDICTIONS_DO_NOT_MATCH_PARTITION",
            f"predictions are not exactly the {len(expected)} Items of {partition}",
            partition=partition,
            missing=len(expected - set(predictions)),
            unexpected=len(set(predictions) - expected),
        )
    absent = sorted(expected - set(references))
    if absent:
        raise _refuse("REFERENCE_MISSING", f"no reference for {absent[0]}", row_id=absent[0])

    items = []
    for row_id in sorted(expected):  # a fixed order, whatever the file order
        row = predictions[row_id]
        y_pred = _finite(row["y_pred"], row_id, "y_pred")
        y_raw = _finite(row["y_pred_raw"], row_id, "y_pred_raw")
        y_true = _finite(references[row_id]["y_true"], row_id, "y_true")
        error = y_pred - y_true
        items.append({
            "row_id": row_id,
            "month": memberships[row_id]["date"][:7],
            "error": error,
            "abs_error": abs(error),
            "clipped": y_pred != y_raw,
        })
    return items


def summarise(items: list[dict], partition: str, unit: str) -> dict:
    """MAE, RMSE, MAE by month and the clipped count of scored Items."""
    by_month = {}
    for item in items:
        by_month.setdefault(item["month"], []).append(item["abs_error"])
    mae = math.fsum(i["abs_error"] for i in items) / len(items)
    rmse = math.sqrt(math.fsum(i["error"] ** 2 for i in items) / len(items))
    return {
        "partition": partition,
        "count": len(items),
        "primary": PRIMARY,
        "metrics": {
            "mae": {"value": mae, "unit": unit, "direction": DIRECTION, "primary": True},
            "rmse": {"value": rmse, "unit": unit, "direction": DIRECTION, "primary": False},
            "mae_by_month": {
                "value": {m: math.fsum(v) / len(v) for m, v in sorted(by_month.items())},
                "unit": unit,
                "direction": DIRECTION,
                "primary": False,
            },
            "clipped_count": {"value": sum(i["clipped"] for i in items), "unit": "values", "direction": None, "primary": False},
        },
    }


def compute_metrics(predictions_path, references_path, memberships_path, workload_dir, *, partition: str = "dev") -> dict:
    refuse_public_check(partition, "PUBLIC_CHECK_METRICS_REFUSED", "metrics")
    declaration = load_declaration(workload_dir)
    declared_partition(declaration, partition)
    unit = declared_unit(declaration)
    memberships = read_by_row_id(memberships_path, "memberships")
    predictions = read_by_row_id(predictions_path, "predictions")
    references = read_by_row_id(references_path, "references")
    return summarise(score_items(predictions, references, memberships, partition), partition, unit)
