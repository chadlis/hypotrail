"""Ticket #32: seasonal_7 predictions on dev, and their metrics."""

import csv
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.baselines import write_seasonal_baseline
from hypotrail.ml.memberships import write_memberships
from hypotrail.ml.metrics import compute_metrics
from hypotrail.ml.predictions import clip_below, write_predictions
from hypotrail.ml.references import write_references

from hypotrail.ml.memberships import derive_memberships
from hypotrail.ml.ridge import write_outputs

from _ml_helpers import fit_probe, fitted_row_ids

ROOT = Path(__file__).resolve().parent.parent
BIKE = ROOT / "examples" / "bike_day"


def rows_of(path):
    with Path(path).open(newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h))


def bike_cnt():
    """Independent read of the verified day.csv: {iso date: cnt}."""
    return {r["dteday"]: int(r["cnt"]) for r in rows_of(BIKE / "data" / "day.csv")}


def dev_dates():
    d = date(2012, 1, 1)
    while d <= date(2012, 6, 30):
        yield d
        d += timedelta(days=1)


def metrics_of(out_dir, **kwargs):
    return compute_metrics(
        out_dir / "predictions.csv", out_dir / "references.csv", out_dir / "memberships.csv",
        kwargs.pop("workload", BIKE), **kwargs
    )


@pytest.fixture
def bike_outputs(tmp_path):
    write_memberships(BIKE, tmp_path)
    write_references(BIKE, tmp_path)
    write_seasonal_baseline(BIKE, tmp_path, "seasonal_7", "dev")
    return tmp_path


def test_seasonal_7_predicts_cnt_seven_days_earlier_for_each_dev_item(bike_outputs):
    """T06 (SPEC §10)."""
    predictions = rows_of(bike_outputs / "predictions.csv")
    cnt = bike_cnt()

    assert len(predictions) == 182
    assert [p["row_id"] for p in predictions] == [f"bike-day:{d.isoformat()}" for d in dev_dates()]
    for p in predictions:
        t = date.fromisoformat(p["row_id"].split(":")[1])
        assert float(p["y_pred_raw"]) == cnt[(t - timedelta(days=7)).isoformat()]
    # Written by hand from day.csv: cnt on 2012-01-01 is 2294, so 2012-01-08 predicts it.
    by_id = {p["row_id"]: p for p in predictions}
    assert float(by_id["bike-day:2012-01-08"]["y_pred"]) == 2294


def test_predictions_csv_has_the_four_columns_and_no_target(bike_outputs):
    predictions = rows_of(bike_outputs / "predictions.csv")

    header = (bike_outputs / "predictions.csv").read_text().splitlines()[0]
    assert header == "row_id,y_pred_raw,y_pred,config_id"
    assert {p["config_id"] for p in predictions} == {"seasonal_7"}
    assert all(p["y_pred"] == p["y_pred_raw"] for p in predictions)


def test_references_artifact_holds_row_id_and_y_true(bike_outputs):
    references = rows_of(bike_outputs / "references.csv")
    cnt = bike_cnt()

    assert list(references[0]) == ["row_id", "y_true"]
    assert len(references) == 358 + 182 + 184
    by_id = {r["row_id"]: r["y_true"] for r in references}
    assert int(by_id["bike-day:2012-03-05"]) == cnt["2012-03-05"]
    assert "bike-day:2011-01-03" not in by_id  # a warm-up day is not an Item


def test_seasonal_7_makes_no_fit_call_and_the_probe_does_fire_when_ridge_v1_is_produced(tmp_path):
    """T05 (SPEC §10)."""
    write_memberships(BIKE, tmp_path)
    with fit_probe(strict=True) as probe:
        write_seasonal_baseline(BIKE, tmp_path, "seasonal_7", "dev")
    assert probe.calls == []
    assert (tmp_path / "predictions.csv").exists()

    # Positive control: the same probe fires, on the 358 train Items only, when ridge_v1 is produced.
    with fit_probe() as probe:
        write_outputs(BIKE, tmp_path / "ridge", "ridge_v1", "dev")
    assert {"Pipeline.fit", "ColumnTransformer.fit_transform", "OneHotEncoder.fit", "StandardScaler.fit", "Ridge.fit"} <= set(probe.calls)
    train_ids = {m["row_id"] for m in derive_memberships(BIKE) if m["partition"] == "train"}
    assert len(train_ids) == 358
    assert fitted_row_ids(probe, BIKE, "ridge_v1") == train_ids


def test_metrics_match_an_independent_calculation(bike_outputs):
    """T06 (SPEC §10)."""
    cnt = bike_cnt()
    errors, by_month = [], {}
    for d in dev_dates():
        e = cnt[d.isoformat()] - cnt[(d - timedelta(days=7)).isoformat()]
        errors.append(e)
        by_month.setdefault(d.strftime("%Y-%m"), []).append(abs(e))
    expected_mae = sum(abs(e) for e in errors) / 182
    expected_rmse = math.sqrt(sum(e * e for e in errors) / 182)

    result = metrics_of(bike_outputs)

    assert result["partition"] == "dev"
    assert result["primary"] == "mae"
    assert result["metrics"]["mae"]["value"] == pytest.approx(expected_mae)
    assert result["metrics"]["rmse"]["value"] == pytest.approx(expected_rmse)
    assert sorted(result["metrics"]["mae_by_month"]["value"]) == [
        "2012-01", "2012-02", "2012-03", "2012-04", "2012-05", "2012-06"
    ]
    assert result["metrics"]["mae_by_month"]["value"] == pytest.approx(
        {m: sum(v) / len(v) for m, v in by_month.items()}
    )
    assert result["metrics"]["clipped_count"]["value"] == 0
    for name in ("mae", "rmse", "mae_by_month"):
        assert result["metrics"][name]["unit"] == "rentals per day"
        assert result["metrics"][name]["direction"] == "lower_is_better"
    assert result["metrics"]["mae"]["primary"] is True
    assert result["metrics"]["rmse"]["primary"] is False


def test_metrics_do_not_depend_on_the_row_order_of_predictions(bike_outputs):
    before = metrics_of(bike_outputs)
    path = bike_outputs / "predictions.csv"
    lines = path.read_text().splitlines()
    body = lines[1:]
    random.Random(7).shuffle(body)
    assert body != lines[1:]
    path.write_text("\n".join([lines[0], *body]) + "\n")

    assert metrics_of(bike_outputs) == before


def test_clipping_bounds_negative_raw_predictions():
    assert clip_below([-3.5, 0.0, 12.0, -0.1], 0) == [0.0, 0.0, 12.0, 0.0]


def test_the_clipped_count_reaches_the_metrics(tmp_path):
    write_memberships(BIKE, tmp_path)
    write_references(BIKE, tmp_path)
    ids = [f"bike-day:{d.isoformat()}" for d in dev_dates()]
    raw = [100.0] * 182
    raw[3], raw[40] = -5.0, -0.5
    write_predictions(tmp_path, "toy", ids, raw)

    rows = rows_of(tmp_path / "predictions.csv")
    assert float(rows[3]["y_pred_raw"]) == -5.0 and float(rows[3]["y_pred"]) == 0.0
    assert metrics_of(tmp_path)["metrics"]["clipped_count"]["value"] == 2


def test_metrics_on_public_check_are_refused(bike_outputs):
    with pytest.raises(InvalidInputError) as caught:
        metrics_of(bike_outputs, partition="public_check")
    assert caught.value.code == "PUBLIC_CHECK_METRICS_REFUSED"


def test_predictions_that_are_not_exactly_the_dev_items_are_refused(bike_outputs):
    path = bike_outputs / "predictions.csv"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n")  # one dev Item missing
    with pytest.raises(InvalidInputError) as caught:
        metrics_of(bike_outputs)
    assert caught.value.code == "PREDICTIONS_DO_NOT_MATCH_PARTITION"


def test_seasonal_baseline_follows_the_declaration_not_bike(tmp_path):
    directory = tmp_path / "other"
    (directory / "data").mkdir(parents=True)
    start = date(2020, 1, 1)
    with (directory / "data" / "series.csv").open("w", newline="") as h:
        w = csv.writer(h)
        w.writerow(["day", "visits"])
        w.writerows(((start + timedelta(days=i)).isoformat(), i * i) for i in range(10))
    (directory / "workload.json").write_text(json.dumps({
        "schema_version": "workload/1", "data_file": "data/series.csv",
        "licence_notice": "none.md", "id_prefix": "shop-day", "date_column": "day",
        "target_column": "visits", "period_k": 3, "target_unit": "visits per day",
        "forbidden_features": [],
        "allowed_target_features": [{"name": "lag_3", "kind": "lag", "period": 3}],
        "configurations": {"seasonal_3": {"kind": "seasonal_baseline", "period_k": 3, "post_processing": {"clip_min": 0}}},
        "partitions": {"train": ["2020-01-04", "2020-01-07"], "dev": ["2020-01-08", "2020-01-10"]},
    }))
    out = tmp_path / "out"
    write_memberships(directory, out)
    write_seasonal_baseline(directory, out, "seasonal_3", "dev")

    rows = rows_of(out / "predictions.csv")
    assert [(r["row_id"], float(r["y_pred"]), r["config_id"]) for r in rows] == [
        ("shop-day:2020-01-08", 16.0, "seasonal_3"),  # index 7 looks back to index 4: 4*4
        ("shop-day:2020-01-09", 25.0, "seasonal_3"),
        ("shop-day:2020-01-10", 36.0, "seasonal_3"),
    ]


def copy_bike(tmp_path, edit):
    import shutil

    target = tmp_path / "bike"
    shutil.copytree(BIKE, target)
    path = target / "workload.json"
    declaration = json.loads(path.read_text(encoding="utf-8"))
    edit(declaration)
    path.write_text(json.dumps(declaration), encoding="utf-8")
    return target


def test_seasonal_7_is_a_declared_configuration():
    declared = json.loads((BIKE / "workload.json").read_text(encoding="utf-8"))["configurations"]["seasonal_7"]
    assert declared["period_k"] == 7
    assert declared["post_processing"] == {"clip_min": 0}


def test_seasonal_k_follows_the_declared_configuration(tmp_path):
    def edit(d):
        d["allowed_target_features"].append({"name": "lag_14", "kind": "lag", "period": 14})  # declared
        d["configurations"]["seasonal_7"].update(period_k=14)

    workload = copy_bike(tmp_path, edit)
    write_seasonal_baseline(workload, tmp_path / "out", "seasonal_7", "dev")

    by_id = {r["row_id"]: r for r in rows_of(tmp_path / "out" / "predictions.csv")}
    cnt = bike_cnt()
    assert float(by_id["bike-day:2012-03-05"]["y_pred"]) == cnt["2012-02-20"]  # 14 days earlier
    assert {r["config_id"] for r in by_id.values()} == {"seasonal_7"}  # the id is the declared key


def test_seasonal_clipping_is_the_declared_bound(tmp_path):
    def edit(d):
        d["configurations"]["seasonal_7"]["post_processing"]["clip_min"] = 5000

    write_seasonal_baseline(copy_bike(tmp_path, edit), tmp_path / "out", "seasonal_7", "dev")

    rows = rows_of(tmp_path / "out" / "predictions.csv")
    assert min(float(r["y_pred"]) for r in rows) == 5000.0
    assert any(float(r["y_pred_raw"]) < 5000 for r in rows)  # raw is kept


def test_seasonal_baseline_of_an_undeclared_configuration_is_refused(tmp_path):
    with pytest.raises(InvalidInputError) as caught:
        write_seasonal_baseline(BIKE, tmp_path, "seasonal_9", "dev")
    assert caught.value.code == "CONFIGURATION_NOT_DECLARED"
    assert not (tmp_path / "predictions.csv").exists()


def test_seasonal_k_the_workload_does_not_declare_is_refused(tmp_path):
    workload = copy_bike(tmp_path, lambda d: d["configurations"]["seasonal_7"].update(period_k=14))
    with pytest.raises(InvalidInputError) as caught:
        write_seasonal_baseline(workload, tmp_path / "out", "seasonal_7", "dev")
    assert caught.value.code == "TARGET_TRANSFORMATION_NOT_ALLOWED"
    assert caught.value.details["config_id"] == "seasonal_7"
    assert not (tmp_path / "out" / "predictions.csv").exists()


@pytest.mark.parametrize("k", [0, -7])
def test_seasonal_k_that_reaches_date_t_or_later_is_refused(tmp_path, k):
    workload = copy_bike(tmp_path, lambda d: d["configurations"]["seasonal_7"].update(period_k=k))
    with pytest.raises(InvalidInputError) as caught:
        write_seasonal_baseline(workload, tmp_path / "out", "seasonal_7", "dev")
    assert caught.value.code == "TARGET_FEATURE_NOT_PAST"
    assert caught.value.details["config_id"] == "seasonal_7"


def test_the_metric_unit_is_declared_in_the_workload(tmp_path, bike_outputs):
    assert json.loads((BIKE / "workload.json").read_text(encoding="utf-8"))["target_unit"] == "rentals per day"

    workload = copy_bike(tmp_path, lambda d: d.update(target_unit="visits per day"))
    metrics = metrics_of(bike_outputs, workload=workload)["metrics"]

    for name in ("mae", "rmse", "mae_by_month"):
        assert metrics[name]["unit"] == "visits per day"


def test_a_workload_without_a_unit_is_refused(tmp_path, bike_outputs):
    workload = copy_bike(tmp_path, lambda d: d.pop("target_unit"))
    with pytest.raises(InvalidInputError) as caught:
        metrics_of(bike_outputs, workload=workload)
    assert caught.value.code == "DECLARATION_INCOMPLETE"
    assert caught.value.details == {"key": "target_unit", "path": ""}


@pytest.mark.parametrize("partition", ["train", "nowhere"])
def test_metrics_are_computed_on_dev_only(tmp_path, partition):
    write_memberships(BIKE, tmp_path)
    write_references(BIKE, tmp_path)
    write_seasonal_baseline(BIKE, tmp_path, "seasonal_7", "dev")

    with pytest.raises(InvalidInputError) as caught:
        metrics_of(tmp_path, partition=partition)

    assert caught.value.code == "METRICS_PARTITION_NOT_DEV"
    assert caught.value.details == {"partition": partition}


def test_a_workload_that_declares_no_dev_partition_is_refused(tmp_path, bike_outputs):
    workload = copy_bike(tmp_path, lambda d: d["partitions"].pop("dev"))
    with pytest.raises(InvalidInputError) as caught:
        metrics_of(bike_outputs, workload=workload)
    assert caught.value.code == "PARTITION_NOT_DECLARED"


def test_a_workload_with_only_a_baseline_still_needs_a_train_partition(tmp_path):
    def edit(d):
        d["partitions"] = {"dev": ["2011-01-08", "2012-06-30"], "public_check": ["2012-07-01", "2012-12-31"]}
        del d["configurations"]["ridge_v1"]

    workload = copy_bike(tmp_path, edit)
    with pytest.raises(InvalidInputError) as caught:
        write_seasonal_baseline(workload, tmp_path / "out", "seasonal_7", "dev")
    assert caught.value.code == "TRAIN_PARTITION_NOT_DECLARED"
    assert not (tmp_path / "out").exists()
