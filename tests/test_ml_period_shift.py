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

from test_ml_declaration_schema import RIDGE, SEASONAL, at, workload_with

BIG = 1_000_000
CODE = "DECLARATION_VALUE_NOT_ALLOWED"


def refusal(run):
    with pytest.raises(InvalidInputError) as caught:
        run()
    return caught.value


def allow_big_lag(declaration, kind="lag"):
    declaration["allowed_target_features"].append({"name": "lag_big", "kind": kind, "period": BIG})


def test_a_seasonal_period_beyond_the_calendar_is_refused_with_its_key_and_path(tmp_path):
    def edit(d):
        allow_big_lag(d)
        at(d, SEASONAL)["period_k"] = BIG

    workload = workload_with(tmp_path, edit)
    error = refusal(lambda: write_seasonal_baseline(workload, tmp_path / "out", "seasonal_7", "dev"))
    assert (error.code, error.details["key"], error.details["path"]) == (
        CODE, "period_k", "configurations.seasonal_7.period_k",
    )
    assert not (tmp_path / "out").exists()
