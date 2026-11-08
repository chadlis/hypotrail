"""The declared target series of a Workload: {date: value}."""

from pathlib import Path

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.declaration import Declaration, require_keys, typed
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


def read_target_series(workload_dir: Path, declaration: Declaration) -> dict:
    """The declared target column keyed by date, in date order."""
    typed(declaration, Declaration)
    require_keys(declaration, "target_column")
    target_column = declaration.target_column
    table = read_table(workload_dir, declaration, [target_column])
    return {date: _number(row[target_column], date.isoformat(), target_column) for date, row in table.items()}
