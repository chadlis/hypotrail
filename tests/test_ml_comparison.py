"""Ticket #36: the first Comparison on dev, seasonal_7 (Control) against ridge_v1 (Candidate)."""

import csv
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.baselines import write_seasonal_baseline
from hypotrail.ml.comparison import COMPARISON_NAME, compare
from hypotrail.ml.memberships import write_memberships
from hypotrail.ml.references import write_references
from hypotrail.ml.ridge import write_outputs

ROOT = Path(__file__).resolve().parent.parent
BIKE = ROOT / "examples" / "bike_day"


def rows_of(path):
    with Path(path).open(newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h))


def cnt_by_date():
    return {r["dteday"]: int(r["cnt"]) for r in rows_of(BIKE / "data" / "day.csv")}


def dev_dates():
    d = date(2012, 1, 1)
    while d <= date(2012, 6, 30):
        yield d
        d += timedelta(days=1)


@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    shared = tmp_path_factory.mktemp("shared")
    write_memberships(BIKE, shared)
    write_references(BIKE, shared)
    control = tmp_path_factory.mktemp("control")
    candidate = tmp_path_factory.mktemp("candidate")
    write_seasonal_baseline(BIKE, control)
    write_outputs(BIKE, candidate)
    return shared, control, candidate


@pytest.fixture
def dirs(shared, tmp_path):
    """Fresh copies of the two predictions directories, so a test may alter them."""
    shared_dir, control, candidate = shared
    copies = []
    for name, source in (("control", control), ("candidate", candidate)):
        target = tmp_path / name
        target.mkdir()
        (target / "predictions.csv").write_text((source / "predictions.csv").read_text())
        copies.append(target)
    return shared_dir, copies[0], copies[1], tmp_path / "out"


def run(dirs, **kwargs):
    shared_dir, control, candidate, out = dirs
    return compare(
        control / "predictions.csv", candidate / "predictions.csv",
        shared_dir / "references.csv", shared_dir / "memberships.csv", out, **kwargs
    )


def independent(predictions_path, cnt):
    """MAE, RMSE, MAE by month, clipped count and absolute error per row_id, from the raw files."""
    rows = rows_of(predictions_path)
    abs_err, sq, by_month, clipped = {}, [], {}, 0
    for r in rows:
        d = r["row_id"].split(":")[1]
        e = float(r["y_pred"]) - cnt[d]
        abs_err[r["row_id"]] = abs(e)
        sq.append(e * e)
        by_month.setdefault(d[:7], []).append(abs(e))
        clipped += float(r["y_pred"]) != float(r["y_pred_raw"])
    return {
        "mae": sum(abs_err.values()) / len(rows),
        "rmse": math.sqrt(sum(sq) / len(rows)),
        "by_month": {m: sum(v) / len(v) for m, v in by_month.items()},
        "clipped": clipped,
        "abs_err": abs_err,
        "n": len(rows),
    }


def test_comparison_metrics_and_delta_match_an_independent_calculation(dirs):
    result = run(dirs)
    cnt = cnt_by_date()
    control = independent(dirs[1] / "predictions.csv", cnt)
    candidate = independent(dirs[2] / "predictions.csv", cnt)

    assert control["n"] == candidate["n"] == 182
    for side, expected in (("control", control), ("candidate", candidate)):
        got = result[side]["metrics"]
        assert result[side]["count"] == 182
        assert got["mae"]["value"] == pytest.approx(expected["mae"])
        assert got["rmse"]["value"] == pytest.approx(expected["rmse"])
        assert got["mae_by_month"]["value"] == pytest.approx(expected["by_month"])
        assert got["clipped_count"]["value"] == expected["clipped"]
    assert result["delta_mae"]["value"] == pytest.approx(candidate["mae"] - control["mae"])
    diffs = {d["row_id"]: d["delta_abs_error"] for d in result["differences"]}
    assert len(diffs) == 182
    for row_id, value in diffs.items():
        assert value == pytest.approx(candidate["abs_err"][row_id] - control["abs_err"][row_id])
    assert result["delta_mae"]["value"] == pytest.approx(sum(diffs.values()) / 182)


def test_the_comparison_names_what_it_compares(dirs):
    result = run(dirs)

    assert result["control"]["config_id"] == "seasonal_7"
    assert result["candidate"]["config_id"] == "ridge_v1"
    assert result["mode"] == "native_ml"
    assert result["population"]["partition"] == "dev"
    assert result["population"]["count"] == 182
    assert result["population"]["row_ids"] == [f"bike-day:{d.isoformat()}" for d in dev_dates()]
    assert result["metric"] == {
        "name": "mae", "unit": "rentals per day", "direction": "lower_is_better"
    }
    assert result["delta_mae"]["unit"] == "rentals per day"


def test_the_comparison_is_written_to_the_output_directory(dirs):
    result = run(dirs)

    written = json.loads((dirs[3] / COMPARISON_NAME).read_text())
    assert written == json.loads(json.dumps(result))


def test_pairing_is_by_row_id_not_by_position(dirs):
    before = run(dirs)
    path = dirs[2] / "predictions.csv"
    lines = path.read_text().splitlines()
    body = lines[1:]
    random.Random(3).shuffle(body)
    assert body != lines[1:]
    path.write_text("\n".join([lines[0], *body]) + "\n")

    after = run(dirs)

    assert after["differences"] == before["differences"]
    assert after["delta_mae"] == before["delta_mae"]


def test_a_worse_candidate_still_gives_a_comparison_with_a_positive_delta(dirs):
    path = dirs[2] / "predictions.csv"
    rows = rows_of(path)
    with path.open("w", newline="") as h:
        w = csv.writer(h, lineterminator="\n")
        w.writerow(["row_id", "y_pred_raw", "y_pred", "config_id"])
        for r in rows:
            w.writerow([r["row_id"], 0, 0, "always_zero"])

    result = run(dirs)

    assert result["candidate"]["config_id"] == "always_zero"
    assert result["delta_mae"]["value"] > 0


def test_predictions_not_covering_the_same_dev_items_are_refused(dirs):
    path = dirs[2] / "predictions.csv"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n")  # the Candidate misses one dev Item

    with pytest.raises(InvalidInputError) as caught:
        run(dirs)

    assert caught.value.code == "COMPARISON_ITEMS_DIFFER"
    assert not (dirs[3] / COMPARISON_NAME).exists()


def test_a_comparison_on_public_check_is_refused(dirs):
    with pytest.raises(InvalidInputError) as caught:
        run(dirs, partition="public_check")

    assert caught.value.code == "PUBLIC_CHECK_COMPARISON_REFUSED"
    assert not (dirs[3] / COMPARISON_NAME).exists()
