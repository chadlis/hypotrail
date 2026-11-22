"""The declared target series of a Workload, {date: value}, read from its data file or from the bytes of a copy of it."""

from pathlib import Path

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.declaration import Declaration, require_keys, typed
from hypotrail.ml.table import read_table, table_of


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


def target_series(data: bytes, declaration: Declaration) -> dict:
    """The declared target column of the bytes of a data file, keyed by date, in date order."""
    typed(declaration, Declaration)
    require_keys(declaration, "target_column")
    return _series(table_of(data, declaration, [declaration.target_column]), declaration.target_column)


def read_target_series(workload_dir: Path, declaration: Declaration) -> dict:
    """The declared target column of the Workload's data file, keyed by date, in date order."""
    typed(declaration, Declaration)
    require_keys(declaration, "target_column")
    return _series(read_table(workload_dir, declaration, [declaration.target_column]), declaration.target_column)


def _series(table: dict, target_column: str) -> dict:
    return {date: _number(row[target_column], date.isoformat(), target_column) for date, row in table.items()}
