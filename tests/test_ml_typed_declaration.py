"""Ticket #40: `workload.json` is read once into typed, immutable objects; every computation starts from them.

Seams: `load_declaration` (the one loader), the `Period` that shifts a date itself, each computation that takes the
typed declaration (a raw `dict` is refused with a `TypeError`), and the entry points that must read the file once and
give the same outputs as on `main` `390fa15`.
"""

import csv
import dataclasses
import datetime
import json
from pathlib import Path

import pytest

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.baselines import write_seasonal_baseline
from hypotrail.ml.comparison import compare
from hypotrail.ml.configuration import declared_configuration, validate_configuration
from hypotrail.ml.declaration import Declaration, load_declaration, require_keys
from hypotrail.ml.lags import compute_lags
from hypotrail.ml.memberships import memberships_of, write_memberships
from hypotrail.ml.metrics import compute_metrics, declared_partition, declared_unit
from hypotrail.ml.periods import Period
from hypotrail.ml.references import write_references
from hypotrail.ml.ridge import build_pipeline, fit_configuration, inputs_of, predict_partition, write_outputs
from hypotrail.ml.series import read_target_series
from hypotrail.ml.table import read_table

from _ml_helpers import canonical_digest, write_small_workload

BIKE = Path(__file__).resolve().parent.parent / "examples" / "bike_day"
RAW = json.loads((BIKE / "workload.json").read_text(encoding="utf-8"))
DAY = datetime.date(2012, 1, 8)


# --- the loader ----------------------------------------------------------------------------


def test_the_loader_returns_a_typed_declaration_whose_values_cannot_be_changed():
    declaration = load_declaration(BIKE)
    assert isinstance(declaration, Declaration)
    assert (declaration.id_prefix, declaration.target_unit, declaration.period_k.days) == ("bike-day", "rentals per day", 7)
    assert [p.name for p in declaration.partitions] == ["train", "dev", "public_check"]
    assert declaration.partitions[1].first == datetime.date(2012, 1, 1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        declaration.id_prefix = "other"
    with pytest.raises(TypeError):
        declaration.configurations["seasonal_7"] = None
    ridge = declaration.configurations["ridge_v1"]
    assert isinstance(ridge.lag_features, tuple) and isinstance(declaration.forbidden_features, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ridge.ridge.alpha = 2.0


def test_a_declaration_without_the_optional_keys_loads_with_them_absent(tmp_path):
    workload = write_small_workload(tmp_path / "w", "day,visits\n2020-01-01,1\n2020-01-02,2\n2020-01-03,3\n")
    raw = json.loads((workload / "workload.json").read_text(encoding="utf-8"))
    for key in ("configurations", "forbidden_features", "allowed_target_features", "target_unit", "period_k"):
        del raw[key]
    (workload / "workload.json").write_text(json.dumps(raw), encoding="utf-8")
    declaration = load_declaration(workload)
    assert declaration.configurations is None and declaration.period_k is None and declaration.target_unit is None
    with pytest.raises(InvalidInputError) as caught:
        require_keys(declaration, "period_k")
    assert (caught.value.code, caught.value.details["key"]) == ("DECLARATION_INCOMPLETE", "period_k")


def test_every_entry_point_reads_the_file_once(tmp_path, monkeypatch):
    write_memberships(BIKE, tmp_path)
    write_references(BIKE, tmp_path)
    write_seasonal_baseline(BIKE, tmp_path / "c", "seasonal_7", "dev")
    write_outputs(BIKE, tmp_path / "k", "ridge_v1", "dev")
    reads = []
    original = Path.read_text

    def counting(self, *args, **kwargs):
        if self.name == "workload.json":
            reads.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)
    predictions = tmp_path / "c" / "predictions.csv"
    entry_points = {
        "memberships": lambda: write_memberships(BIKE, tmp_path / "m"),
        "references": lambda: write_references(BIKE, tmp_path / "r"),
        "seasonal_baseline": lambda: write_seasonal_baseline(BIKE, tmp_path / "s", "seasonal_7", "dev"),
        "ridge": lambda: write_outputs(BIKE, tmp_path / "o", "ridge_v1", "dev"),
        "fit and predict": lambda: predict_partition(fit_configuration(BIKE, "ridge_v1"), "public_check"),
        "metrics": lambda: compute_metrics(predictions, tmp_path / "references.csv", tmp_path / "memberships.csv", BIKE),
        "comparison": lambda: compare(
            predictions, tmp_path / "k" / "predictions.csv", tmp_path / "references.csv",
            tmp_path / "memberships.csv", tmp_path / "cmp", BIKE,
        ),
    }
    for name, run in entry_points.items():
        reads.clear()
        run()
        assert len(reads) == 1, name


# --- no module indexes the raw dictionary --------------------------------------------------

COMPUTATIONS = {
    "require_keys": lambda d: require_keys(d, "data_file"),
    "read_table": lambda d: read_table(BIKE, d),
    "read_target_series": lambda d: read_target_series(BIKE, d),
    "memberships_of": lambda d: memberships_of(BIKE, d),
    "declared_configuration": lambda d: declared_configuration(d, "seasonal_7"),
    "validate_configuration": lambda d: validate_configuration(d, "ridge_v1"),
    "declared_unit": declared_unit,
    "declared_partition": lambda d: declared_partition(d, "dev"),
    "inputs_of": lambda d: inputs_of(BIKE, d, "ridge_v1", "dev"),
}


@pytest.mark.parametrize("name", sorted(COMPUTATIONS))
def test_a_computation_takes_the_typed_declaration_and_refuses_a_raw_dict(name):
    COMPUTATIONS[name](load_declaration(BIKE))
    with pytest.raises(TypeError):
        COMPUTATIONS[name](RAW)


def test_the_features_and_the_configuration_of_the_pipeline_are_typed_too():
    ridge = load_declaration(BIKE).configurations["ridge_v1"]
    assert compute_lags({DAY - datetime.timedelta(days=d): float(d) for d in range(1, 8)}, DAY, ridge.lag_features)
    assert build_pipeline(ridge)
    with pytest.raises(TypeError):
        compute_lags({}, DAY, RAW["configurations"]["ridge_v1"]["lag_features"])
    with pytest.raises(TypeError):
        build_pipeline(RAW["configurations"]["ridge_v1"])


# --- a period shifts a date itself ---------------------------------------------------------


def test_a_period_shifts_a_date_back_and_lists_the_dates_of_its_window_nearest_first():
    period = load_declaration(BIKE).period_k
    assert period.earlier(DAY) == datetime.date(2012, 1, 1)
    assert list(Period(3).window(DAY)) == [datetime.date(2012, 1, d) for d in (7, 6, 5)]


def test_two_periods_of_the_same_length_are_equal_wherever_they_are_declared():
    declaration = load_declaration(BIKE)
    in_a_lag = declaration.configurations["ridge_v1"].lag_features[1].period
    assert in_a_lag.days == 7 and in_a_lag == declaration.period_k
    assert in_a_lag.path != declaration.period_k.path


def test_a_shift_no_date_can_apply_is_refused_naming_the_declared_period_and_not_as_a_load_refusal():
    period = Period(10**6, key="period", path="configurations.x.lag_features.0.period")
    with pytest.raises(InvalidInputError) as caught:
        period.earlier(DAY)
    error = caught.value
    assert (error.code, error.stage) == ("DECLARATION_VALUE_NOT_ALLOWED", "periods")
    assert error.details == {
        "key": "period", "path": "configurations.x.lag_features.0.period", "days": 10**6, "date": "2012-01-08",
    }


def test_the_memberships_shift_refusal_reports_the_declared_period_k_not_the_loop_offset(tmp_path):
    csv_text = "day,visits\n" + "".join(f"0001-01-0{d},{d}\n" for d in range(1, 6))
    workload = write_small_workload(tmp_path / "w", csv_text, extra={
        "period_k": 10, "partitions": {"train": ["0001-01-02", "0001-01-05"]},
    })
    with pytest.raises(InvalidInputError) as caught:
        write_memberships(workload, tmp_path / "out")
    assert caught.value.details["days"] == 10  # the loop reached an offset of 2 when the calendar ran out
    assert set(caught.value.details) == {"key", "path", "days", "date"}


def test_a_load_time_refusal_and_a_shift_refusal_of_the_same_code_differ_by_their_stage(tmp_path):
    from test_ml_declaration_schema import setter, workload_with

    with pytest.raises(InvalidInputError) as load:
        load_declaration(workload_with(tmp_path, setter(("period_k",), 0)))
    assert (load.value.code, load.value.stage) == ("DECLARATION_VALUE_NOT_ALLOWED", "declaration")
    with pytest.raises(InvalidInputError) as shift:
        Period(10**6, key="period_k", path="period_k").earlier(DAY)
    assert shift.value.code == load.value.code and shift.value.stage != load.value.stage


# --- the same outputs as on main 390fa15 ---------------------------------------------------

# canonical_digest of each artifact of the unmodified Bike declaration, computed on `main` 390fa15
MAIN_DIGESTS = {
    "memberships": "606429b9043742e27f54fb38a6baf733a523fe869735cd7d1d8c6c888b82db46",
    "references": "26709efc7b1cd1a63eceeede76bb6b1a77bd624daece59a4f9e042e69ac27659",
    "seasonal predictions": "7fc78c464b56c61bafbbd750ad8003a31ceadb6fdd11d18c5265e7daf284da2e",
    "ridge predictions": "b4443f3c1450173bfb9d64ea20ad71db0ed431e1b93b279e300f7be499b20f2b",
    "seasonal metrics": "8fecfeb5824e1da965ea518563df218cf3c3e06d1d3afa0bf1c25a94b16227e0",
    "ridge metrics": "71059b329f32f97d93f40beffc9e08ba0f6d1a94743640fd376b75fc19dc127f",
    "comparison": "97df08fee759576412da69cb3d6a31aea5cca6b0a5f941200bf27b378040ba6b",
}


def test_the_unmodified_bike_declaration_gives_the_digests_of_main(tmp_path):
    write_memberships(BIKE, tmp_path)
    write_references(BIKE, tmp_path)
    write_seasonal_baseline(BIKE, tmp_path / "c", "seasonal_7", "dev")
    write_outputs(BIKE, tmp_path / "k", "ridge_v1", "dev")
    comparison = compare(
        tmp_path / "c" / "predictions.csv", tmp_path / "k" / "predictions.csv",
        tmp_path / "references.csv", tmp_path / "memberships.csv", tmp_path / "o", BIKE,
    )

    def metrics(side):
        return compute_metrics(
            tmp_path / side / "predictions.csv", tmp_path / "references.csv", tmp_path / "memberships.csv", BIKE
        )

    assert {
        "memberships": canonical_digest(tmp_path / "memberships.csv"),
        "references": canonical_digest(tmp_path / "references.csv"),
        "seasonal predictions": canonical_digest(tmp_path / "c" / "predictions.csv"),
        "ridge predictions": canonical_digest(tmp_path / "k" / "predictions.csv"),
        "seasonal metrics": canonical_digest(metrics("c")),
        "ridge metrics": canonical_digest(metrics("k")),
        "comparison": canonical_digest(comparison),
    } == MAIN_DIGESTS
    with (tmp_path / "memberships.csv").open(newline="", encoding="utf-8") as handle:
        assert len(list(csv.reader(handle))) == 732  # the header and 731 days
