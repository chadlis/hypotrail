"""Scoring a predictions CSV of the Bike Track, standard library only."""

import csv
import math
from pathlib import Path

from hypotrail.core.errors import InvalidInputError


def _read_targets(targets_path: Path, date_column: str, target_column: str) -> dict:
    with Path(targets_path).open(newline="", encoding="utf-8") as handle:
        return {row[date_column]: int(row[target_column]) for row in csv.DictReader(handle)}


def mean_absolute_error_by_date(
    predictions_path: Path,
    targets_path: Path,
    *,
    prediction_date_column: str = "date",
    prediction_column: str = "y_pred",
    target_date_column: str = "dteday",
    target_column: str = "cnt",
) -> float:
    """Mean absolute error of daily predictions, in rentals per day.

    Each prediction is joined to its target by date, never by position. A date
    missing from the targets, or repeated in the predictions, is refused.
    Coverage of the population is not checked here.
    """
    targets = _read_targets(targets_path, target_date_column, target_column)
    errors = []
    seen = set()
    with Path(predictions_path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            date = row[prediction_date_column]
            if date in seen:
                raise InvalidInputError(
                    "DUPLICATE_DATE",
                    f"date predicted more than once: {date}",
                    stage="score",
                    details={"date": date},
                )
            seen.add(date)
            if date not in targets:
                raise InvalidInputError(
                    "UNKNOWN_DATE",
                    f"no target for date: {date}",
                    stage="score",
                    details={"date": date},
                )
            errors.append(abs(float(row[prediction_column]) - targets[date]))
    if not errors:
        raise InvalidInputError(
            "NO_PREDICTIONS", "the predictions file holds no row", stage="score"
        )
    # fsum makes the result independent of the row order.
    return math.fsum(errors) / len(errors)
