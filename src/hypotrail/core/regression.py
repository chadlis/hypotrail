"""Scoring a predictions CSV of the Bike Track, standard library only."""

import csv
import math
from pathlib import Path

from hypotrail.core.errors import InvalidInputError


def _number(cell, *, column: str, date: str, integer: bool = False) -> float:
    """A finite number from a CSV cell, or an InvalidInputError naming the date.

    An integer too large for a float counts as not finite: it could not be compared.
    """
    details = {"date": date, "column": column}
    if cell is None or not cell.strip():
        raise InvalidInputError(
            "EMPTY_CELL", f"empty {column} for date: {date}", stage="score", details=details
        )
    try:
        value = int(cell) if integer else float(cell)
    except ValueError:
        # int() also refuses "nan" and "inf", which is the refusal wanted here.
        raise InvalidInputError(
            "NOT_A_NUMBER", f"{column} is not a number for date: {date}", stage="score", details=details
        ) from None
    try:
        finite = math.isfinite(value)
    except OverflowError:  # an integer beyond the largest float
        finite = False
    if not finite:
        raise InvalidInputError(
            "NON_FINITE_NUMBER", f"{column} is not finite for date: {date}", stage="score", details=details
        )
    return value


def _read_targets(targets_path: Path, date_column: str, target_column: str) -> dict:
    targets = {}
    with Path(targets_path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            date = row[date_column]
            if date in targets:
                raise InvalidInputError(
                    "DUPLICATE_DATE",
                    f"date present more than once in the targets: {date}",
                    stage="score",
                    details={"date": date},
                )
            targets[date] = _number(row[target_column], column=target_column, date=date, integer=True)
    return targets


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
    missing from the targets, or repeated in the predictions or in the targets,
    is refused, and so are errors too large for their mean to be finite.
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
            predicted = _number(row[prediction_column], column=prediction_column, date=date)
            error = abs(predicted - targets[date])
            if not math.isfinite(error):  # finite cells, but their difference overflows
                raise InvalidInputError(
                    "NON_FINITE_ERROR",
                    f"the error is too large to be a finite number for date: {date}",
                    stage="score",
                    details={"date": date},
                )
            errors.append(error)
    if not errors:
        raise InvalidInputError(
            "NO_PREDICTIONS", "the predictions file holds no row", stage="score"
        )
    # fsum makes the result independent of the row order.
    try:
        return math.fsum(errors) / len(errors)
    except OverflowError:  # every error is finite, their sum is not
        raise InvalidInputError(
            "NON_FINITE_ERROR",
            "the errors are too large for their mean to be a finite number",
            stage="score",
        ) from None
