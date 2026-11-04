"""Ticket #31: Partitions and memberships from the Workload's declared dates."""

import csv
import json
import random
import shutil
from collections import Counter
from pathlib import Path

import pytest

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.memberships import write_memberships

ROOT = Path(__file__).resolve().parent.parent
BIKE = ROOT / "examples" / "bike_day"


def read_memberships(out_dir):
    with (Path(out_dir) / "memberships.csv").open(newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h))


def test_bike_memberships_counts_and_warm_up(tmp_path):
    write_memberships(BIKE, tmp_path)
    rows = read_memberships(tmp_path)

    assert list(rows[0]) == ["row_id", "date", "partition", "exclusion_reason"]
    assert len(rows) == 731
    assert len({r["row_id"] for r in rows}) == 731
    assert Counter(r["partition"] for r in rows) == {
        "": 7, "train": 358, "dev": 182, "public_check": 184,
    }
    excluded = [r for r in rows if r["partition"] == ""]
    assert [r["date"] for r in excluded] == [f"2011-01-0{d}" for d in range(1, 8)]
    assert all(r["exclusion_reason"] == "insufficient_history" for r in excluded)
    assert all(r["exclusion_reason"] == "" for r in rows if r["partition"])
    by_date = {r["date"]: r for r in rows}
    assert by_date["2011-01-08"]["partition"] == "train"
    assert by_date["2011-12-31"]["partition"] == "train"
    assert by_date["2012-01-01"]["partition"] == "dev"
    assert by_date["2012-06-30"]["partition"] == "dev"
    assert by_date["2012-07-01"]["partition"] == "public_check"
    assert by_date["2012-12-31"]["partition"] == "public_check"
    assert by_date["2012-03-05"]["row_id"] == "bike-day:2012-03-05"


def make_workload(tmp_path, *, k, ranges, dates):
    """A Workload whose declarations differ from Bike's, with its own tiny data."""
    directory = tmp_path / "other"
    (directory / "data").mkdir(parents=True)
    with (directory / "data" / "series.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["day", "visits"])
        writer.writerows((d, i) for i, d in enumerate(dates))
    (directory / "workload.json").write_text(json.dumps({
        "schema_version": "workload/1",
        "data_file": "data/series.csv",
        "licence_notice": "licenses/none.md",
        "id_prefix": "shop-day",
        "date_column": "day",
        "target_column": "visits",
        "period_k": k,
        "partitions": ranges,
    }))
    return directory


DATES = [f"2020-03-{d:02d}" for d in range(1, 21)]
RANGES = {
    "train": ["2020-03-04", "2020-03-12"],
    "dev": ["2020-03-13", "2020-03-16"],
    "public_check": ["2020-03-17", "2020-03-20"],
}


def test_declarations_drive_the_output(tmp_path):
    workload = make_workload(tmp_path, k=3, ranges=RANGES, dates=DATES)
    out = tmp_path / "out"
    write_memberships(workload, out)
    rows = read_memberships(out)

    assert Counter(r["partition"] for r in rows) == {
        "": 3, "train": 9, "dev": 4, "public_check": 4,
    }
    assert [r["date"] for r in rows if r["partition"] == ""] == DATES[:3]
    assert rows[0]["row_id"] == "shop-day:2020-03-01"


def shuffle_rows(data, seed):
    lines = data.read_text().splitlines()
    body = lines[1:]
    random.Random(seed).shuffle(body)
    assert body != lines[1:]
    data.write_text("\n".join([lines[0], *body]) + "\n")


def test_reordering_the_input_changes_nothing(tmp_path):
    workload = make_workload(tmp_path, k=3, ranges=RANGES, dates=DATES)
    write_memberships(workload, tmp_path / "a")
    shuffle_rows(workload / "data" / "series.csv", 7)
    write_memberships(workload, tmp_path / "b")

    assert (tmp_path / "a" / "memberships.csv").read_bytes() == (
        tmp_path / "b" / "memberships.csv"
    ).read_bytes()


def test_bike_reordering_changes_nothing(tmp_path):
    workload = tmp_path / "bike"
    shutil.copytree(BIKE, workload)
    write_memberships(workload, tmp_path / "a")
    shuffle_rows(workload / "data" / "day.csv", 1)
    write_memberships(workload, tmp_path / "b")
    assert (tmp_path / "a" / "memberships.csv").read_bytes() == (
        tmp_path / "b" / "memberships.csv"
    ).read_bytes()


def test_a_date_outside_every_partition_is_refused(tmp_path):
    ranges = {**RANGES, "public_check": ["2020-03-17", "2020-03-19"]}
    workload = make_workload(tmp_path, k=3, ranges=ranges, dates=DATES)
    with pytest.raises(InvalidInputError) as error:
        write_memberships(workload, tmp_path / "out")
    assert error.value.code == "DATE_IN_NO_PARTITION"


def test_a_partition_covering_a_warm_up_date_is_refused(tmp_path):
    ranges = {**RANGES, "train": ["2020-03-03", "2020-03-12"]}
    workload = make_workload(tmp_path, k=3, ranges=ranges, dates=DATES)
    with pytest.raises(InvalidInputError) as error:
        write_memberships(workload, tmp_path / "out")
    assert error.value.code == "PARTITION_COVERS_WARMUP"
    assert error.value.details["partition"] == "train"
    assert error.value.details["date"] == "2020-03-03"


def test_overlapping_partitions_are_refused(tmp_path):
    ranges = {**RANGES, "dev": ["2020-03-12", "2020-03-16"]}
    workload = make_workload(tmp_path, k=3, ranges=ranges, dates=DATES)
    with pytest.raises(InvalidInputError) as error:
        write_memberships(workload, tmp_path / "out")
    assert error.value.code == "PARTITIONS_OVERLAP"


def test_adds_no_cli_command():
    from hypotrail import cli

    assert "memberships" not in Path(cli.__file__).read_text()


GAP_DATES = [d for d in DATES if d != "2020-03-10"]
GAP_RANGES = {
    "train": ["2020-03-04", "2020-03-09"],
    "dev": ["2020-03-14", "2020-03-16"],
    "public_check": ["2020-03-17", "2020-03-20"],
}


def test_a_day_is_excluded_when_any_of_its_k_previous_dates_is_absent(tmp_path):
    # 2020-03-10 is absent. With k=3, the three days after the gap lack a complete history,
    # wherever they stand in the file; the first three days of the file lack one too.
    workload = make_workload(tmp_path, k=3, ranges=GAP_RANGES, dates=GAP_DATES)
    out = tmp_path / "out"
    write_memberships(workload, out)
    rows = read_memberships(out)

    excluded = [r for r in rows if r["partition"] == ""]
    assert [r["date"] for r in excluded] == [
        "2020-03-01", "2020-03-02", "2020-03-03", "2020-03-11", "2020-03-12", "2020-03-13",
    ]
    assert all(r["exclusion_reason"] == "insufficient_history" for r in excluded)
    by_date = {r["date"]: r["partition"] for r in rows}
    assert by_date["2020-03-14"] == "dev"  # 03-11, 03-12, 03-13 all exist


def test_a_partition_covering_a_day_with_incomplete_history_after_a_gap_is_refused(tmp_path):
    ranges = {**GAP_RANGES, "train": ["2020-03-04", "2020-03-11"]}
    workload = make_workload(tmp_path, k=3, ranges=ranges, dates=GAP_DATES)
    with pytest.raises(InvalidInputError) as error:
        write_memberships(workload, tmp_path / "out")
    assert error.value.code == "PARTITION_COVERS_WARMUP"
    assert error.value.details["date"] == "2020-03-11"
