"""Ticket #33: lags of a declared target, computed from dates."""

import csv
import datetime
import random
from pathlib import Path

import pytest

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.lags import compute_lags

ROOT = Path(__file__).resolve().parent.parent
DAY_CSV = ROOT / "examples" / "bike_day" / "data" / "day.csv"

FEATURES = [
    {"name": "lag_1", "kind": "lag", "period": 1},
    {"name": "lag_7", "kind": "lag", "period": 7},
    {"name": "mean_previous_7", "kind": "mean_previous", "period": 7},
]


def bike_rows():
    with DAY_CSV.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def values_by_date(rows, target="cnt"):
    return {datetime.date.fromisoformat(r["dteday"]): float(r[target]) for r in rows}


@pytest.mark.parametrize("position", [7, 8, 100, 365, 500, 730])
def test_lags_match_day_csv_at_chosen_dates(position):
    rows = bike_rows()  # day.csv lists one date per line, in order
    cnt = [float(r["cnt"]) for r in rows]
    day = datetime.date.fromisoformat(rows[position]["dteday"])

    lags = compute_lags(values_by_date(rows), day, FEATURES)

    assert lags["lag_1"] == cnt[position - 1]
    assert lags["lag_7"] == cnt[position - 7]
    assert lags["mean_previous_7"] == sum(cnt[position - 7 : position]) / 7


def test_known_values_from_the_first_days_of_the_file():
    # cnt of 2011-01-01..2011-01-08 as written in day.csv: 985 801 1349 1562 1600 1606 1510 959
    lags = compute_lags(values_by_date(bike_rows()), datetime.date(2011, 1, 8), FEATURES)
    assert lags == {"lag_1": 1510.0, "lag_7": 985.0, "mean_previous_7": 9413 / 7}


def test_row_order_does_not_change_the_lags():
    rows = bike_rows()
    shuffled = rows[:]
    random.Random(3).shuffle(shuffled)
    day = datetime.date(2012, 3, 5)
    assert compute_lags(values_by_date(shuffled), day, FEATURES) == compute_lags(
        values_by_date(rows), day, FEATURES
    )


def test_target_and_periods_are_parameters():
    start = datetime.date(2020, 1, 1)
    values = {start + datetime.timedelta(days=i): float(i * i) for i in range(10)}
    features = [
        {"name": "lag_3", "kind": "lag", "period": 3},
        {"name": "mean_previous_2", "kind": "mean_previous", "period": 2},
    ]
    lags = compute_lags(values, start + datetime.timedelta(days=6), features)
    assert lags == {"lag_3": 9.0, "mean_previous_2": (16.0 + 25.0) / 2}


def test_a_missing_day_is_refused_not_guessed():
    values = values_by_date(bike_rows())
    del values[datetime.date(2011, 1, 4)]
    with pytest.raises(InvalidInputError) as caught:
        compute_lags(values, datetime.date(2011, 1, 8), FEATURES)
    assert caught.value.code == "LAG_SOURCE_MISSING"


def test_an_unknown_feature_kind_is_refused():
    with pytest.raises(InvalidInputError) as caught:
        compute_lags({}, datetime.date(2011, 1, 8), [{"name": "x", "kind": "ewm", "period": 3}])
    assert caught.value.code == "UNKNOWN_FEATURE_KIND"
