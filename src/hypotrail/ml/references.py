"""The References artifact of the temporal regression Track: `references.csv` (`row_id`, `y_true`).

One row per Item (a date that belongs to a Partition), taken from the target
the Workload declares. Predictions never carry their own target; metrics join
this file by `row_id`.
"""

import csv
import datetime
from pathlib import Path

from hypotrail.ml.memberships import load_declaration, memberships_of
from hypotrail.ml.series import read_target_series

REFERENCES_NAME = "references.csv"
COLUMNS = ["row_id", "y_true"]


def write_references(workload_dir: Path, out_dir: Path) -> Path:
    declaration = load_declaration(workload_dir)
    series = read_target_series(workload_dir, declaration)
    rows = [
        {"row_id": m["row_id"], "y_true": series[datetime.date.fromisoformat(m["date"])]}
        for m in memberships_of(workload_dir, declaration)
        if m["partition"]
    ]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / REFERENCES_NAME
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path
