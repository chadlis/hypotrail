"""Ticket #33: the shared predictions writer takes a declared lower bound."""

import csv

from hypotrail.ml.predictions import write_predictions


def read(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_default_lower_bound_is_zero_and_raw_is_kept(tmp_path):
    path = write_predictions(tmp_path, "c", ["a", "b"], [-12.5, 310.25])
    rows = read(path)
    assert [(r["y_pred_raw"], r["y_pred"], r["config_id"]) for r in rows] == [
        ("-12.5", "0.0", "c"), ("310.25", "310.25", "c"),
    ]


def test_a_declared_lower_bound_replaces_the_default(tmp_path):
    rows = read(write_predictions(tmp_path, "c", ["a", "b", "c"], [-5.0, 50.0, 150.0], clip_min=100))
    assert [r["y_pred"] for r in rows] == ["100.0", "100.0", "150.0"]
    assert [r["y_pred_raw"] for r in rows] == ["-5.0", "50.0", "150.0"]
