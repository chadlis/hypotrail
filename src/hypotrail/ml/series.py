"""The declared target series of a Workload: {date: value}, standard library only."""

from pathlib import Path

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.table import read_table


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="series", details=details)


def _number(cell: str, date: str, column: str):
    try:
        return int(cell)
    except ValueError:
        pass
    try:
        value = float(cell)
    except ValueError:
        raise _refuse("TARGET_NOT_A_NUMBER", f"target is not a number for {date}", date=date, column=column) from None
    if value != value or value in (float("inf"), float("-inf")):
        raise _refuse("TARGET_NOT_A_NUMBER", f"target is not finite for {date}", date=date, column=column)
    return value


def read_target_series(workload_dir: Path, declaration: dict) -> dict:
    """The declared target column keyed by date, in date order."""
    target_column = declaration.get("target_column")
    if target_column is None:
        raise _refuse("DECLARATION_INCOMPLETE", "declaration lacks 'target_column'", key="target_column")
    table = read_table(workload_dir, declaration, [target_column])
    return {date: _number(row[target_column], date.isoformat(), target_column) for date, row in table.items()}
