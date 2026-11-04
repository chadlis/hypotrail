"""Partitions and memberships of the temporal regression Track.

Reads a Workload's declarations (`workload.json`) and its daily series, derives
one Item per date and writes `memberships.csv`. Standard library only. Every
parameter comes from the declaration: the Partition date ranges, the period k
(the first k days have no complete history and are excluded) and the columns.
Nothing is drawn at random and nothing depends on the order of the input rows.
The caller verifies the data against its lock first (`hypotrail.core.data`).
"""

import csv
import datetime
import json
from pathlib import Path

from hypotrail.core.errors import InvalidInputError

DECLARATION_NAME = "workload.json"
MEMBERSHIPS_NAME = "memberships.csv"
COLUMNS = ["row_id", "date", "partition", "exclusion_reason"]
WARM_UP_REASON = "insufficient_history"


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="memberships", details=details)


def load_declaration(workload_dir: Path) -> dict:
    path = Path(workload_dir) / DECLARATION_NAME
    try:
        declaration = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise _refuse("FILE_NOT_FOUND", f"declaration not found: {path}", file=str(path)) from None
    except json.JSONDecodeError:
        raise _refuse("FILE_NOT_JSON", f"declaration is not valid JSON: {path}", file=str(path)) from None
    for key in ("data_file", "id_prefix", "date_column", "period_k", "partitions"):
        if key not in declaration:
            raise _refuse("DECLARATION_INCOMPLETE", f"declaration lacks {key!r}", key=key)
    return declaration


def _partition_ranges(declaration: dict) -> list:
    ranges = []
    for name, bounds in declaration["partitions"].items():
        try:
            first, last = (datetime.date.fromisoformat(b) for b in bounds)
        except (ValueError, TypeError):
            raise _refuse("BAD_PARTITION_RANGE", f"unreadable date range for {name}", partition=name) from None
        if first > last:
            raise _refuse("BAD_PARTITION_RANGE", f"range of {name} ends before it starts", partition=name)
        ranges.append((first, last, name))
    ranges.sort()
    for (_, previous_last, previous), (first, _, name) in zip(ranges, ranges[1:]):
        if first <= previous_last:
            raise _refuse("PARTITIONS_OVERLAP", f"{previous} and {name} overlap", partitions=[previous, name])
    return ranges


def _read_dates(workload_dir: Path, declaration: dict) -> list:
    column = declaration["date_column"]
    with (Path(workload_dir) / declaration["data_file"]).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if column not in (reader.fieldnames or []):
            raise _refuse("DATE_COLUMN_MISSING", f"no column {column!r} in the data", column=column)
        try:
            dates = [datetime.date.fromisoformat(row[column]) for row in reader]
        except (ValueError, TypeError):
            raise _refuse("UNREADABLE_DATE", f"unreadable date in column {column!r}", column=column) from None
    if len(set(dates)) != len(dates):
        raise _refuse("DUPLICATE_DATE", "a date appears more than once")
    return sorted(dates)


def derive_memberships(workload_dir: Path) -> list[dict]:
    declaration = load_declaration(workload_dir)
    ranges = _partition_ranges(declaration)
    dates = _read_dates(workload_dir, declaration)
    warm_up = set(dates[: declaration["period_k"]])
    for date in dates[: declaration["period_k"]]:
        for first, last, name in ranges:
            if first <= date <= last:
                raise _refuse(
                    "PARTITION_COVERS_WARMUP",
                    f"Partition {name} covers the warm-up day {date.isoformat()}",
                    partition=name,
                    date=date.isoformat(),
                )

    rows = []
    for date in dates:
        partition, reason = "", ""
        if date in warm_up:
            reason = WARM_UP_REASON
        else:
            for first, last, name in ranges:
                if first <= date <= last:
                    partition = name
                    break
            else:
                raise _refuse(
                    "DATE_IN_NO_PARTITION",
                    f"{date.isoformat()} belongs to no declared Partition",
                    date=date.isoformat(),
                )
        rows.append({
            "row_id": f"{declaration['id_prefix']}:{date.isoformat()}",
            "date": date.isoformat(),
            "partition": partition,
            "exclusion_reason": reason,
        })
    return rows


def write_memberships(workload_dir: Path, out_dir: Path) -> Path:
    rows = derive_memberships(workload_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / MEMBERSHIPS_NAME
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path
