"""Refusals of the ML Track's readers carry a code and, where known, the column or date (ADR 0002 stage errors)."""

import pytest

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.memberships import derive_memberships
from hypotrail.ml.predictions import write_predictions
from hypotrail.ml.series import read_target_series
from hypotrail.ml.memberships import load_declaration

from _ml_helpers import write_small_workload

GOOD = "day,visits\n2020-01-01,1\n2020-01-02,2\n2020-01-03,3\n"


def series_error(workload):
    with pytest.raises(InvalidInputError) as caught:
        read_target_series(workload, load_declaration(workload))
    return caught.value


def memberships_error(workload):
    with pytest.raises(InvalidInputError) as caught:
        derive_memberships(workload)
    return caught.value


def test_series_duplicate_date_names_the_date(tmp_path):
    error = series_error(write_small_workload(tmp_path, GOOD + "2020-01-02,9\n"))
    assert error.code == "DUPLICATE_DATE"
    assert error.details == {"date": "2020-01-02"}


def test_series_unreadable_date_names_the_column(tmp_path):
    error = series_error(write_small_workload(tmp_path, GOOD + "not-a-date,9\n"))
    assert error.code == "UNREADABLE_DATE"
    assert error.details["column"] == "day"


def test_series_missing_column_names_it(tmp_path):
    error = series_error(write_small_workload(tmp_path, "day,other\n2020-01-01,1\n"))
    assert error.code == "COLUMN_MISSING"
    assert error.details["column"] == "visits"


def test_series_target_not_a_number_names_the_date_and_column(tmp_path):
    error = series_error(write_small_workload(tmp_path, GOOD + "2020-01-04,abc\n"))
    assert error.code == "TARGET_NOT_A_NUMBER"
    assert error.details == {"date": "2020-01-04", "column": "visits"}


def test_memberships_duplicate_date_names_the_date(tmp_path):
    error = memberships_error(write_small_workload(tmp_path, GOOD + "2020-01-02,9\n"))
    assert error.code == "DUPLICATE_DATE"
    assert error.details == {"date": "2020-01-02"}


def test_memberships_unreadable_date_names_the_column(tmp_path):
    error = memberships_error(write_small_workload(tmp_path, GOOD + "not-a-date,9\n"))
    assert error.code == "UNREADABLE_DATE"
    assert error.details["column"] == "day"


def test_predictions_of_different_lengths_are_refused_with_a_code(tmp_path):
    with pytest.raises(InvalidInputError) as caught:
        write_predictions(tmp_path, "c", ["a", "b"], [1.0])
    assert caught.value.code == "PREDICTIONS_LENGTH_MISMATCH"
    assert caught.value.details == {"row_ids": 2, "raw_values": 1}
