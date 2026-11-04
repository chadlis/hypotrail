"""The `predictions.csv` writer of the temporal regression Track.

Standard library only. One row per Item with the raw prediction and the
post-processed one; the Configuration that made them is named on every row.
"""

import csv
from pathlib import Path

PREDICTIONS_NAME = "predictions.csv"
COLUMNS = ["row_id", "y_pred_raw", "y_pred", "config_id"]


def clip_at(value: float, minimum: float) -> float:
    """The declared post-processing: `max(minimum, value)`, as a float."""
    return float(max(minimum, value))


def write_predictions(out_dir: Path, rows: list[dict], *, config_id: str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / PREDICTIONS_NAME
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "row_id": row["row_id"],
                "y_pred_raw": repr(float(row["y_pred_raw"])),
                "y_pred": repr(float(row["y_pred"])),
                "config_id": config_id,
            })
    return path
