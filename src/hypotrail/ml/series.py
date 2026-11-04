"""The declared target series of a Workload: {date: value}, standard library only."""

import csv
import datetime
from pathlib import Path

from hypotrail.core.errors import InvalidInputError


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="series", details=details)


def _number(cell: str, date: str):
    try:
        return int(cell)
    except ValueError:
        pass
    try:
        value = float(cell)
    except ValueError:
        raise _refuse("TARGET_NOT_A_NUMBER", f"target is not a number for {date}", date=date) from None
    if value != value or value in (float("inf"), float("-inf")):
        raise _refuse("TARGET_NOT_A_NUMBER", f"target is not finite for {date}", date=date)
    return value


def read_target_series(workload_dir: Path, declaration: dict) -> dict:
    """The declared target column keyed by date, in date order."""
    date_column = declaration["date_column"]
    target_column = declaration.get("target_column")
    if target_column is None:
        raise _refuse("DECLARATION_INCOMPLETE", "declaration lacks 'target_column'", key="target_column")
    series = {}
    with (Path(workload_dir) / declaration["data_file"]).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for column in (date_column, target_column):
            if column not in (reader.fieldnames or []):
                raise _refuse("COLUMN_MISSING", f"no column {column!r} in the data", column=column)
        for row in reader:
            try:
                date = datetime.date.fromisoformat(row[date_column])
            except (ValueError, TypeError):
                raise _refuse("UNREADABLE_DATE", f"unreadable date in column {date_column!r}") from None
            if date in series:
                raise _refuse("DUPLICATE_DATE", f"{date.isoformat()} appears more than once")
            series[date] = _number(row[target_column], date.isoformat())
    return dict(sorted(series.items()))
