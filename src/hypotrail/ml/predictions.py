"""The predictions artifact, shared by every Configuration of the temporal regression Track.

`predictions.csv` holds `row_id`, `y_pred_raw`, `y_pred` and `config_id`, and
never a target: the References are a separate artifact (`references.py`).
`y_pred` is `y_pred_raw` bounded below at zero (SPEC ML-03).
"""

import csv
from pathlib import Path

PREDICTIONS_NAME = "predictions.csv"
COLUMNS = ["row_id", "y_pred_raw", "y_pred", "config_id"]


def clip_below(raw_values, minimum=0) -> tuple[list, int]:
    """max(minimum, raw) for each value, and the number of values that were raised."""
    clipped = [float(minimum) if value < minimum else value for value in raw_values]
    return clipped, sum(1 for value in raw_values if value < minimum)


def clip_non_negative(raw_values) -> tuple[list, int]:
    """max(0, raw) for each value, and the number of values that were raised to 0."""
    return clip_below(raw_values, 0)


def write_predictions(out_dir: Path, config_id: str, row_ids, raw_values, *, clip_min=0) -> Path:
    """`clip_min` is the Configuration's declared lower bound (default 0, SPEC ML-03)."""
    row_ids, raw_values = list(row_ids), list(raw_values)
    if len(row_ids) != len(raw_values):
        raise ValueError("row_ids and raw_values differ in length")
    clipped, _ = clip_below(raw_values, clip_min)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / PREDICTIONS_NAME
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(COLUMNS)
        for row_id, raw, value in zip(row_ids, raw_values, clipped):
            writer.writerow([row_id, raw, value, config_id])
    return path
