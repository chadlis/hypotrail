"""Ticket #33: the predictions.csv writer, shared in format with seasonal_7 (#32)."""

import csv

from hypotrail.ml.predictions import COLUMNS, clip_at, write_predictions


def test_predictions_file_has_the_agreed_columns_and_keeps_raw_and_clipped(tmp_path):
    rows = [
        {"row_id": "bike-day:2012-01-01", "y_pred_raw": -12.5, "y_pred": 0.0},
        {"row_id": "bike-day:2012-01-02", "y_pred_raw": 310.25, "y_pred": 310.25},
    ]
    path = write_predictions(tmp_path, rows, config_id="ridge_v1")

    assert path == tmp_path / "predictions.csv"
    assert COLUMNS == ["row_id", "y_pred_raw", "y_pred", "config_id"]
    with path.open(newline="", encoding="utf-8") as handle:
        written = list(csv.DictReader(handle))
    assert written[0] == {
        "row_id": "bike-day:2012-01-01", "y_pred_raw": "-12.5", "y_pred": "0.0", "config_id": "ridge_v1",
    }
    assert [r["config_id"] for r in written] == ["ridge_v1", "ridge_v1"]


def test_clip_at_zero_keeps_the_raw_value_apart():
    assert clip_at(-3.2, 0) == 0.0
    assert clip_at(4.5, 0) == 4.5
