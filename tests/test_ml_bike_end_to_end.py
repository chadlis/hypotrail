"""The real `examples/bike_day`, verified against its lock, then run through the ML Track."""

import csv
import shutil
from pathlib import Path

import pytest

from hypotrail.core import data
from hypotrail.core.errors import IntegrityError
from hypotrail.ml.baselines import write_seasonal_baseline
from hypotrail.ml.comparison import compare
from hypotrail.ml.memberships import write_memberships
from hypotrail.ml.references import write_references
from hypotrail.ml.ridge import write_outputs

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
BIKE = EXAMPLES / "bike_day"


def rows_of(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_the_verified_bike_workload_gives_memberships_and_dev_predictions_of_both_configurations(tmp_path):
    """T06 (SPEC §10)."""
    reports = data.verify_workloads(EXAMPLES, ["bike_day"])
    assert [(r["workload"], r["status"]) for r in reports] == [("bike_day", "verified")]

    write_memberships(BIKE, tmp_path)
    write_references(BIKE, tmp_path)
    write_seasonal_baseline(BIKE, tmp_path / "control", "seasonal_7", "dev")
    write_outputs(BIKE, tmp_path / "candidate", "ridge_v1", "dev")

    memberships = rows_of(tmp_path / "memberships.csv")
    dev_ids = {m["row_id"] for m in memberships if m["partition"] == "dev"}
    assert len(memberships) == 731 and len(dev_ids) == 182
    for directory, config_id in (("control", "seasonal_7"), ("candidate", "ridge_v1")):
        predictions = rows_of(tmp_path / directory / "predictions.csv")
        assert {p["row_id"] for p in predictions} == dev_ids
        assert {p["config_id"] for p in predictions} == {config_id}

    comparison = compare(
        tmp_path / "control" / "predictions.csv", tmp_path / "candidate" / "predictions.csv",
        tmp_path / "references.csv", tmp_path / "memberships.csv", tmp_path / "out", BIKE,
    )
    assert comparison["population"]["count"] == 182


def test_a_bike_table_that_no_longer_matches_its_lock_is_refused_before_anything_is_derived(tmp_path):
    examples = tmp_path / "examples"
    shutil.copytree(EXAMPLES, examples)
    day = examples / "bike_day" / "data" / "day.csv"
    day.write_text(day.read_text(encoding="utf-8").replace("2294", "2295", 1), encoding="utf-8")

    with pytest.raises(IntegrityError):
        data.verify_workloads(examples, ["bike_day"])
