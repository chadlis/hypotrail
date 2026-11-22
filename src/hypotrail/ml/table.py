"""The one reader of a Workload's data table, from the Workload's file or from the bytes of a copy of it.

Rows are keyed by date, never by position, so the order of the file changes nothing.
The date column and the data file come from the Workload's declaration.
"""

import csv
import datetime
import io
from pathlib import Path

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.declaration import Declaration, require_keys, typed


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="table", details=details)


def read_table(workload_dir: Path, declaration: Declaration, columns=()) -> dict:
    """The data rows keyed by date, in date order. `columns` must exist besides the date column."""
    typed(declaration, Declaration)
    require_keys(declaration, "data_file", "date_column")
    return table_of((Path(workload_dir) / declaration.data_file).read_bytes(), declaration, columns)


def table_of(data: bytes, declaration: Declaration, columns=()) -> dict:
    """`read_table` of the bytes of a data file, such as the copy of the dataset a Study keeps."""
    typed(declaration, Declaration)
    require_keys(declaration, "date_column")
    date_column = declaration.date_column
    rows = {}
    reader = csv.DictReader(io.StringIO(data.decode("utf-8"), newline=""))
    fieldnames = reader.fieldnames or []
    if date_column not in fieldnames:
        raise _refuse("DATE_COLUMN_MISSING", f"no column {date_column!r} in the data", column=date_column)
    for column in columns:
        if column not in fieldnames:
            raise _refuse("COLUMN_MISSING", f"no column {column!r} in the data", column=column)
    for row in reader:
        try:
            date = datetime.date.fromisoformat(row[date_column])
        except (ValueError, TypeError):
            raise _refuse(
                "UNREADABLE_DATE", f"unreadable date in column {date_column!r}", column=date_column
            ) from None
        if date in rows:
            raise _refuse("DUPLICATE_DATE", f"{date.isoformat()} appears more than once", date=date.isoformat())
        rows[date] = row
    return dict(sorted(rows.items()))
