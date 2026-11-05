"""Round 5, G1: a period that no date can apply is a coded refusal wherever dates are shifted.

A period between the span of the data and the span of the calendar passes the schema and every
semantic rule, so the only place that can refuse it is the shift of a date itself. Each case goes
through a public entry point, keeps the root `period_k` at 7, and asserts the code, the key and
that nothing is written.
"""

from pathlib import Path

import pytest

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.baselines import write_seasonal_baseline
from hypotrail.ml.memberships import write_memberships
from hypotrail.ml.ridge import write_outputs

from _ml_helpers import write_small_workload
from test_ml_declaration_schema import RIDGE, SEASONAL, at, workload_with

BIG = 1_000_000
CODE = "DECLARATION_VALUE_NOT_ALLOWED"


def refusal(run):
    with pytest.raises(InvalidInputError) as caught:
        run()
    return caught.value


@pytest.mark.parametrize("period", [BIG, 10**30])
def test_a_seasonal_period_beyond_the_calendar_is_refused_with_its_key_and_path(tmp_path, period):
    def edit(d):
        d["allowed_target_features"].append({"name": "lag_big", "kind": "lag", "period": period})
        at(d, SEASONAL)["period_k"] = period

    workload = workload_with(tmp_path, edit)
    error = refusal(lambda: write_seasonal_baseline(workload, tmp_path / "out", "seasonal_7", "dev"))
    assert (error.code, error.details["key"], error.details["path"]) == (
        CODE, "period_k", "configurations.seasonal_7.period_k",
    )
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("index, kind", [(0, "lag"), (2, "mean_previous")], ids=["lag", "mean_previous"])
def test_a_ridge_lag_period_beyond_the_calendar_is_refused_with_its_key_and_path(tmp_path, index, kind):
    def edit(d):
        big = {**d["allowed_target_features"][index], "period": BIG}
        d["allowed_target_features"][index] = big  # declared as allowed, so every semantic rule lets it through
        at(d, RIDGE)["lag_features"][index] = dict(big)

    workload = workload_with(tmp_path, edit)
    error = refusal(lambda: write_outputs(workload, tmp_path / "out", "ridge_v1", "dev"))
    assert (error.code, error.details["key"], error.details["path"]) == (
        CODE, "period", f"configurations.ridge_v1.lag_features.{index}.period",
    )
    assert not (tmp_path / "out").exists()


def test_a_root_period_beyond_the_data_is_the_warm_up_refusal_and_writes_nothing(tmp_path):
    # On real dates the data ends before the calendar does: the history is incomplete, and the
    # Partition that covers it is the cause named.
    workload = workload_with(tmp_path, lambda d: d.update(period_k=BIG))
    error = refusal(lambda: write_memberships(workload, tmp_path / "out"))
    assert error.code == "PARTITION_COVERS_WARMUP"
    assert not (tmp_path / "out").exists()


def test_a_root_period_beyond_the_calendar_is_refused_with_its_key_and_path(tmp_path):
    # Only a series that starts at the first date of the calendar can reach the end of it.
    csv_text = "day,visits\n" + "".join(f"0001-01-0{d},{d}\n" for d in range(1, 6))
    workload = write_small_workload(tmp_path / "w", csv_text, extra={
        "period_k": 10, "partitions": {"train": ["0001-01-02", "0001-01-05"]},
    })
    error = refusal(lambda: write_memberships(workload, tmp_path / "out"))
    assert (error.code, error.details["key"], error.details["path"]) == (CODE, "period_k", "period_k")
    assert not (tmp_path / "out").exists()
