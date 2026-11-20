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


def test_coded_error_keeps_a_hypotrail_error_and_reports_any_other_exception_by_its_type_only():
    """R4-04: one function for `run_agent`, the CLI and the failure record of `run agent`."""
    from hypotrail.core.errors import EXIT_INFRASTRUCTURE, HypotrailError, coded_error

    own = HypotrailError("DATABASE_CHANGED", "changed", stage="run")
    assert coded_error(own) is own
    os_error = coded_error(OSError("disk gone sk-ant-secret"))
    other = coded_error(RuntimeError("provider down sk-ant-secret"))
    assert (os_error.code, os_error.exit_code, os_error.details) == ("INFRASTRUCTURE_FAILURE", EXIT_INFRASTRUCTURE, {"type": "OSError"})
    assert (other.code, other.exit_code, other.details) == ("UNEXPECTED_ERROR", EXIT_INFRASTRUCTURE, {"type": "RuntimeError"})
    assert "secret" not in repr(os_error.to_dict()) + repr(other.to_dict())
