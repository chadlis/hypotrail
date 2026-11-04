"""Metrics of a predictions CSV of the temporal regression Track, standard library only.

Targets come from the separate References artifact and are joined to the
predictions by `row_id`, never by position. Metrics use `y_pred`. They are
computed on `dev` only: a request on `public_check` is refused until the
Exposure journal exists (SPEC section 2; the slice keeps no such journal yet).
"""

import csv
import math
from pathlib import Path

from hypotrail.core.errors import InvalidInputError

UNIT = "rentals per day"
DIRECTION = "lower_is_better"
PRIMARY = "mae"


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="metrics", details=details)


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


def compute_metrics(predictions_path, references_path, memberships_path, *, partition: str = "dev") -> dict:
    if partition == "public_check":
        raise _refuse(
            "PUBLIC_CHECK_METRICS_REFUSED",
            "metrics on public_check are refused: no Exposure journal exists yet",
            partition=partition,
        )
    if partition != "dev":
        raise _refuse("PARTITION_NOT_SUPPORTED", f"metrics are computed on dev only, not {partition}", partition=partition)

    memberships = _unique_by_row_id(_read(memberships_path), "memberships")
    expected = {row_id for row_id, m in memberships.items() if m["partition"] == partition}
    predictions = _unique_by_row_id(_read(predictions_path), "predictions")
    if set(predictions) != expected:
        raise _refuse(
            "PREDICTIONS_DO_NOT_MATCH_PARTITION",
            f"predictions are not exactly the {len(expected)} Items of {partition}",
            partition=partition,
            missing=len(expected - set(predictions)),
            unexpected=len(set(predictions) - expected),
        )
    references = _unique_by_row_id(_read(references_path), "references")
    absent = sorted(expected - set(references))
    if absent:
        raise _refuse("REFERENCE_MISSING", f"no reference for {absent[0]}", row_id=absent[0])

    errors, by_month, clipped = [], {}, 0
    for row_id in sorted(expected):  # a fixed order, whatever the file order
        row = predictions[row_id]
        y_pred = _finite(row["y_pred"], row_id, "y_pred")
        y_raw = _finite(row["y_pred_raw"], row_id, "y_pred_raw")
        y_true = _finite(references[row_id]["y_true"], row_id, "y_true")
        error = y_pred - y_true
        errors.append(error)
        by_month.setdefault(memberships[row_id]["date"][:7], []).append(abs(error))
        if y_pred != y_raw:
            clipped += 1

    mae = math.fsum(abs(e) for e in errors) / len(errors)
    rmse = math.sqrt(math.fsum(e * e for e in errors) / len(errors))
    return {
        "partition": partition,
        "count": len(errors),
        "primary": PRIMARY,
        "metrics": {
            "mae": {"value": mae, "unit": UNIT, "direction": DIRECTION, "primary": True},
            "rmse": {"value": rmse, "unit": UNIT, "direction": DIRECTION, "primary": False},
            "mae_by_month": {
                "value": {m: math.fsum(v) / len(v) for m, v in sorted(by_month.items())},
                "unit": UNIT,
                "direction": DIRECTION,
                "primary": False,
            },
            "clipped_count": {"value": clipped, "unit": "values", "direction": None, "primary": False},
        },
    }
