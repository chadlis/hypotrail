"""Partitions and memberships of the temporal regression Track.

Reads a Workload's declarations (`workload.json`) and its daily series, derives
one Item per date and writes `memberships.csv`. It needs neither scikit-learn nor NumPy. Every
parameter comes from the declaration: the Partition date ranges, the period k
(a day is excluded when any of the k dates before it is absent from the data) and the columns.
Nothing is drawn at random and nothing depends on the order of the input rows.
The caller verifies the data against its lock first (`hypotrail.core.data`).
"""

import csv
import datetime
from pathlib import Path

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.declaration import DECLARATION_NAME, Declaration, load_declaration, require_keys, typed  # noqa: F401
from hypotrail.ml.table import read_table

MEMBERSHIPS_NAME = "memberships.csv"
COLUMNS = ["row_id", "date", "partition", "exclusion_reason"]
WARM_UP_REASON = "insufficient_history"


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="memberships", details=details)


def _partition_ranges(declaration: Declaration) -> list:
    ranges = []
    for partition in declaration.partitions:
        if partition.first > partition.last:
            raise _refuse("BAD_PARTITION_RANGE", f"range of {partition.name} ends before it starts", partition=partition.name)
        ranges.append((partition.first, partition.last, partition.name))
    ranges.sort()
    for (_, previous_last, previous), (first, _, name) in zip(ranges, ranges[1:]):
        if first <= previous_last:
            raise _refuse("PARTITIONS_OVERLAP", f"{previous} and {name} overlap", partitions=[previous, name])
    return ranges


def derive_memberships(workload_dir: Path) -> list[dict]:
    return memberships_of(workload_dir, load_declaration(workload_dir))


def memberships_of(workload_dir: Path, declaration: Declaration) -> list[dict]:
    """One row per date of the data, from a declaration already loaded."""
    typed(declaration, Declaration)
    require_keys(declaration, "data_file", "date_column", "id_prefix", "period_k")
    ranges = _partition_ranges(declaration)
    dates = list(read_table(workload_dir, declaration))
    present = set(dates)
    # A day has an incomplete history when any of the k dates before it is absent from the data.
    incomplete = {date for date in dates if any(earlier not in present for earlier in declaration.period_k.window(date))}
    for date in dates:
        if date not in incomplete:
            continue
        for first, last, name in ranges:
            if first <= date <= last:
                raise _refuse(
                    "PARTITION_COVERS_WARMUP",
                    f"Partition {name} covers the day {date.isoformat()}, whose history is incomplete",
                    partition=name,
                    date=date.isoformat(),
                )

    rows = []
    for date in dates:
        partition, reason = "", ""
        if date in incomplete:
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
            "row_id": f"{declaration.id_prefix}:{date.isoformat()}",
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
