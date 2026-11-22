"""Ticket #154: `assess` records, for each lag feature its Configuration declares, the Metric of that feature used alone as the forecast.

The expected Metrics are computed in `tests/_single_feature_helpers.py` from the data file and the Study's memberships, never by `hypotrail`.
"""

import csv
import datetime
import hashlib
import io
import json
import math
from pathlib import Path

import pytest
from _architecture import SOURCE
from _assess_helpers import assess, construct, fresh_study, observation_set_id, references_id, rows_of
from _import_helpers import import_ml, ready
from _single_feature_helpers import (
    BIKE_DAY,
    FIELD,
    GENERATED,
    GENERATED_FEATURES,
    expected_maes,
    generated_examples,
    init_generated,
    item_dates,
    recorded_maes,
    ridge,
    run_blocked,
    series_of,
)
from _study_helpers import examples_copy, init_study, run_ml

MAE = "regression_mae_v1"
BIKE_FEATURES = [
    {"name": "lag_1", "kind": "lag", "period": 1},
    {"name": "lag_7", "kind": "lag", "period": 7},
    {"name": "mean_previous_7", "kind": "mean_previous", "period": 7},
]


def assessed(study, attempt, *more):
    code, payload, err = assess(study, observation_set_id(study, attempt), MAE, references_id(study), *more)
    assert code == 0, (payload, err)
    return payload["assessment"], err


def on_disk(study, record) -> dict:
    return json.loads((Path(study) / "assessments" / record["assessment_id"] / "assessment.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bike_ridge(tmp_path_factory):
    """(Study, Attempt, Assessment, stderr): `ridge_v1` run on Bike `dev` and assessed with MAE through the command line."""
    study, attempts = fresh_study(tmp_path_factory.mktemp("bike-ridge"), "ridge_v1")
    record, err = assessed(study, attempts["ridge_v1"])
    return study, attempts["ridge_v1"], record, err


def test_ridge_v1_on_bike_dev_records_its_three_lag_features_each_with_the_mae_of_the_feature_alone_and_all_three_beat_it(bike_ridge):
    study, _, record, _ = bike_ridge
    expected = expected_maes(study, "dev", BIKE_FEATURES)
    assert {name: round(value, 2) for name, value in expected.items()} == {"mean_previous_7": 823.88, "lag_1": 900.60, "lag_7": 1090.79}
    kept = on_disk(study, record)
    computed = recorded_maes(kept)
    assert set(computed) == {"lag_1", "lag_7", "mean_previous_7"}  # the three lag features of ridge_v1, none of its four calendar columns
    assert computed == pytest.approx(expected, abs=1e-9)
    beating = kept[FIELD]["beating"]
    assert [entry["feature"] for entry in beating] == ["mean_previous_7", "lag_1", "lag_7"]  # every one that beats, not only the best
    assert recorded_maes(kept, "beating") == pytest.approx(expected, abs=1e-9)
    assert kept["metrics"][0]["value"] == pytest.approx(1264.73, abs=0.005)


def test_on_a_flagged_assessment_assess_exits_0_and_its_metric_counts_and_per_item_file_are_the_ones_computed_from_the_outputs(bike_ridge):
    study, attempt, record, _ = bike_ridge
    assert recorded_maes(record, "beating")  # the Assessment is flagged
    predictions = {r["row_id"]: float(r["y_pred"]) for r in rows_of(Path(study) / "attempts" / attempt["attempt_id"] / "observations.csv")}
    truth = {r["row_id"]: float(r["y_true"]) for r in rows_of(Path(study) / "artifacts" / "references.csv")}
    errors = {row_id: abs(predictions[row_id] - truth[row_id]) for row_id in sorted(predictions)}
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["row_id", "execution_status", "criterion", "state", "value", "reason"])
    for row_id, error in errors.items():
        writer.writerow([row_id, "produced", "absolute_error", "scored", repr(error), ""])
    assert record["per_item_ref"]["sha256"] == hashlib.sha256(out.getvalue().encode("utf-8")).hexdigest()
    assert record["counts"] == {"expected": 182, "attempted": 182, "produced": 182, "scored": 182, "correct": None, "incorrect": None, "unscored": 0, "errored": 0}
    assert record["metrics"] == [{
        "id": "mae", "value": math.fsum(errors.values()) / len(errors), "unit": "rentals per day", "direction": "lower_is_better",
        "denominator": 182, "status": "scored", "reason": None,
    }]


# --- the series reader ------------------------------------------------------------------------------------------------------


def test_the_series_reader_takes_the_bytes_of_day_csv_and_the_bike_declaration_with_no_path_and_imports_no_numpy():
    expected = {day.isoformat(): int(value) for day, value in series_of(BIKE_DAY).items()}
    assert len(expected) == 731
    body = """
        from hypotrail.ml import series
        from hypotrail.ml.declaration import declaration_of

        data, declaration = open(sys.argv[2], "rb").read(), open(sys.argv[3], "rb").read()
        found = series.target_series(data, declaration_of(declaration, "workload.json"))
        RESULT = {"series": {day.isoformat(): value for day, value in found.items()}, "types": sorted({type(v).__name__ for v in found.values()})}
    """
    result = run_blocked(["numpy"], body, BIKE_DAY, BIKE_DAY.parent.parent / "workload.json")
    assert result["series"] == expected and list(result["series"]) == sorted(expected)
    assert result["types"] == ["int"] and result["loaded"] == []


# --- over the Items the Assessment scored, with lags.compute_lags ----------------------------------------------------------


def test_with_one_item_not_scored_each_feature_is_scored_over_the_items_the_assessment_scored_with_its_denominator(bike_ridge):
    study, attempt, _, _ = bike_ridge
    failed = []

    def fail_first(rows):
        failed.append(rows[0]["row_id"])
        return [{**rows[0], "status": "failed", "reason": "constructed", "y_pred_raw": "", "y_pred": ""}, *rows[1:]]

    code, payload, err = assess(study, construct(study, attempt, fail_first), MAE, references_id(study))
    assert code == 0, (payload, err)
    record = payload["assessment"]
    assert record["metrics"][0]["denominator"] == 181
    scored = set(item_dates(study, "dev")) - set(failed)
    assert recorded_maes(record) == pytest.approx(expected_maes(study, "dev", BIKE_FEATURES, row_ids=scored), abs=1e-9)
    assert [entry["metric"]["denominator"] for entry in record[FIELD]["computed"]] == [181, 181, 181]


def test_the_forecasts_are_computed_by_lags_compute_lags_for_the_scored_items_with_the_declared_features(bike_ridge, monkeypatch):
    from hypotrail.ml import lags

    study, attempt, _, _ = bike_ridge
    calls, original = [], lags.compute_lags

    def probe(values, day, features):
        calls.append((day, tuple(f.name for f in features)))
        return original(values, day, features)

    monkeypatch.setattr(lags, "compute_lags", probe)
    record, _ = assessed(study, attempt)
    assert recorded_maes(record)
    assert sorted(day for day, _ in calls) == sorted(item_dates(study, "dev").values())
    assert {names for _, names in calls} == {("lag_1", "lag_7", "mean_previous_7")}


# --- only the Configuration's own lag features, in the target's unit ------------------------------------------------------


def lag_1_only(declaration):
    ridge = json.loads(json.dumps(declaration["configurations"]["ridge_v1"]))
    ridge["lag_features"] = [{"name": "lag_1", "kind": "lag", "period": 1}]
    ridge["scaler"]["columns"] = ["lag_1"]
    declaration["configurations"]["ridge_lag_1"] = ridge


def test_a_configuration_that_declares_lag_1_only_computes_lag_1_only_although_mean_previous_7_is_allowed_and_would_beat_it(tmp_path):
    examples = examples_copy(tmp_path, edit=lag_1_only)
    study, _ = init_study(tmp_path, examples=examples)
    code, payload, err = run_ml(study, "ridge_lag_1", "dev", "lag-1-only", "--examples-dir", examples)
    assert code == 0, (payload, err)
    record, _ = assessed(study, payload["attempt"])
    expected = expected_maes(study, "dev", BIKE_FEATURES)
    assert [entry["feature"] for entry in record[FIELD]["computed"]] == ["lag_1"]
    assert recorded_maes(record) == pytest.approx({"lag_1": expected["lag_1"]}, abs=1e-9)
    assert [entry["feature"] for entry in record[FIELD]["beating"]] == ["lag_1"]
    assert expected["mean_previous_7"] < record["metrics"][0]["value"]  # allowed, not declared: it would beat the Assessment too


def test_the_kinds_treated_as_in_the_targets_unit_are_the_kinds_of_target_feature_in_the_workload_schema_both_ways():
    from hypotrail.ml import single_features

    schema = json.loads((SOURCE / "hypotrail" / "ml" / "workload.schema.json").read_text(encoding="utf-8"))
    kinds = set(schema["$defs"]["target_feature"]["properties"]["kind"]["enum"])
    assert set(single_features.IN_TARGET_UNIT) == kinds


# --- every Configuration, and an optional field -----------------------------------------------------------------------------


def test_an_assessment_record_without_the_field_validates_against_the_contract_schema(bike_ridge):
    from hypotrail.core import contracts
    from hypotrail.core.errors import HypotrailError

    _, _, record, _ = bike_ridge
    assert FIELD in record
    try:
        contracts.validate({key: value for key, value in record.items() if key != FIELD})
    except HypotrailError as error:
        pytest.fail(f"an Assessment record without {FIELD} does not validate: {error}")


@pytest.fixture(scope="module")
def bike_seasonal_and_import(tmp_path_factory):
    """(Study, seasonal_7 Attempt, Import Attempt): both on Bike `dev`, not yet assessed."""
    base = tmp_path_factory.mktemp("seasonal-import")
    study, attempts = fresh_study(base, "seasonal_7")
    source, mapping, population, _ = ready(base)
    code, payload, err = import_ml(study, source, mapping, population, "import-a")
    assert code == 0, (payload, err)
    return study, attempts["seasonal_7"], payload["attempt"]


def test_seasonal_7_which_declares_no_lag_feature_records_the_field_present_and_empty(bike_seasonal_and_import):
    study, seasonal, _ = bike_seasonal_and_import
    record, _ = assessed(study, seasonal)
    assert on_disk(study, record).get(FIELD) == {"computed": [], "beating": []}


def test_an_assessment_of_an_import_exits_0_and_records_no_field(bike_seasonal_and_import):
    study, _, imported = bike_seasonal_and_import
    record, _ = assessed(study, imported)
    assert FIELD not in on_disk(study, record)


# --- the values come from the Study's copy, the columns from the declaration the Attempt keeps -------------------------------


def rewrite_rows(path, change):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames, rows = reader.fieldnames, list(reader)
    for row in rows:
        change(row)
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def bike_copy_ridge(tmp_path):
    """(Study, examples copy, Attempt): `ridge_v1` run on `dev` from a copy of `examples/`, not yet assessed."""
    examples = examples_copy(tmp_path)
    study, _ = init_study(tmp_path, examples=examples)
    code, payload, err = run_ml(study, "ridge_v1", "dev", "ridge-dev", "--examples-dir", examples)
    assert code == 0, (payload, err)
    return study, examples, payload["attempt"]


def test_every_target_of_the_workloads_data_file_changed_after_run_ml_leaves_the_three_maes_unchanged(bike_copy_ridge):
    study, examples, attempt = bike_copy_ridge
    rewrite_rows(examples / "bike_day" / "data" / "day.csv", lambda row: row.update(cnt=str(int(row["cnt"]) * 3 + 1000)))
    record, _ = assessed(study, attempt, "--examples-dir", examples)
    assert recorded_maes(record) == pytest.approx(expected_maes(study, "dev", BIKE_FEATURES), abs=1e-9)


def test_the_target_column_renamed_in_the_workloads_declaration_after_run_ml_leaves_the_three_maes_unchanged(bike_copy_ridge):
    study, examples, attempt = bike_copy_ridge
    path = examples / "bike_day" / "workload.json"
    declaration = json.loads(path.read_text(encoding="utf-8"))
    declaration["target_column"] = "registered"
    path.write_text(json.dumps(declaration), encoding="utf-8")
    record, _ = assessed(study, attempt, "--examples-dir", examples)
    assert recorded_maes(record) == pytest.approx(expected_maes(study, "dev", BIKE_FEATURES), abs=1e-9)


def test_without_the_studys_copy_of_the_dataset_seasonal_7_and_an_import_are_assessed_with_exit_0(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    source, mapping, population, _ = ready(tmp_path)
    code, payload, err = import_ml(study, source, mapping, population, "import-a")
    assert code == 0, (payload, err)
    (study / "datasets" / "day.csv").unlink()
    for attempt in (attempts["seasonal_7"], payload["attempt"]):
        record, _ = assessed(study, attempt)
        assert on_disk(study, record) == record


# --- a small generated Workload ---------------------------------------------------------------------------------------------

GENERATED_PARTITIONS = {"train": ["2020-01-08", "2020-04-30"], "dev": ["2020-05-01", "2020-05-31"], "public_check": ["2020-06-01", "2020-06-30"]}


def weekly_with_trend(days=182, first=datetime.date(2020, 1, 1)) -> list:
    """A weekday pattern on a trend of 3 visits a day: lag_7 is always 21 short, which a Ridge on lag_7 and the weekday fits away."""
    pattern = [0, 40, 80, 120, 160, 300, 260]
    return [200 + pattern[(first + datetime.timedelta(days=i)).weekday()] + 3 * i for i in range(days)]


def generated_maes(study, examples, row_ids=None) -> dict:
    data = examples / GENERATED / "data" / "series.csv"
    return expected_maes(study, "dev", GENERATED_FEATURES, data_file=data, date_column="day", target_column="visits", row_ids=row_ids)


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    """(Study, examples, Attempt): a Ridge on the three lag features and the weekday, run on `dev` of the generated Workload."""
    base = tmp_path_factory.mktemp("generated")
    examples = generated_examples(base, weekly_with_trend(), first="2020-01-01", partitions=GENERATED_PARTITIONS, configurations={"fit": ridge(GENERATED_FEATURES)})
    study = init_generated(examples, base / "study")
    code, payload, err = run_ml(study, "fit", "dev", "fit-dev", "--examples-dir", examples)
    assert code == 0, (payload, err)
    return study, examples, payload["attempt"]


def test_where_the_ridge_fits_better_than_any_single_feature_every_feature_is_computed_and_none_beats_the_assessment(generated):
    study, examples, attempt = generated
    record, _ = assessed(study, attempt, "--examples-dir", examples)
    expected = generated_maes(study, examples)
    assert record["metrics"][0]["value"] < min(expected.values())
    assert recorded_maes(record) == pytest.approx(expected, abs=1e-9)
    assert record[FIELD]["beating"] == []


def test_a_feature_whose_metric_equals_the_assessments_is_not_recorded_as_beating_it(generated):
    study, examples, attempt = generated
    values = series_of(examples / GENERATED / "data" / "series.csv", "day", "visits")
    dates = item_dates(study, "dev")

    def lag_7_as_prediction(rows):
        return [{**row, "y_pred_raw": repr(values[dates[row["row_id"]] - datetime.timedelta(days=7)]), "y_pred": repr(values[dates[row["row_id"]] - datetime.timedelta(days=7)])} for row in rows]

    code, payload, err = assess(study, construct(study, attempt, lag_7_as_prediction), MAE, references_id(study))
    assert code == 0, (payload, err)
    record = payload["assessment"]
    computed = recorded_maes(record)
    assert computed["lag_7"] == record["metrics"][0]["value"]  # the same Metric, exactly
    assert "lag_7" not in recorded_maes(record, "beating")
    assert recorded_maes(record, "beating") == {name: value for name, value in computed.items() if value < record["metrics"][0]["value"]}


def test_a_declared_feature_that_needs_a_date_the_series_lacks_leaves_the_field_absent_with_exit_0_and_one_line_on_stderr(tmp_path):
    from _report_helpers import edit_manifest

    # dev comes first, so its first Item, 2020-01-02, has no value seven days earlier; a Ridge on lag_1 runs on it
    partitions = {"dev": ["2020-01-02", "2020-01-15"], "train": ["2020-01-16", "2020-03-31"], "public_check": ["2020-04-01", "2020-04-30"]}
    lag_1, lag_7 = GENERATED_FEATURES[0], GENERATED_FEATURES[1]
    examples = generated_examples(tmp_path, weekly_with_trend(121), first="2020-01-01", partitions=partitions, configurations={"lag_1": ridge([lag_1])}, period_k=1)
    study = init_generated(examples, tmp_path / "study")
    code, payload, err = run_ml(study, "lag_1", "dev", "lag-1-dev", "--examples-dir", examples)
    assert code == 0, (payload, err)
    attempt = payload["attempt"]
    # the Attempt's recorded Configuration declares lag_7 too, whose source is missing, beside lag_1, whose sources all exist
    edit_manifest(study, attempt["attempt_id"], lambda m: m["effective_config"]["configuration"]["declared"].update(lag_features=[lag_1, lag_7]))
    code, payload, err = assess(study, observation_set_id(study, attempt), MAE, references_id(study))
    assert code == 0, (payload, err)
    assert FIELD not in on_disk(study, payload["assessment"])
    lines = err.splitlines()
    assert len(lines) == 1 and all(text in lines[0] for text in ("LAG_SOURCE_MISSING", "lag_7", "2020-01-02")), err


# --- the exposure rules: what is read on dev, and when on public_check --------------------------------------------------------


def from_public_check_on(row):
    if row["dteday"] >= "2012-07-01":  # every target of public_check, and its parts, so that the copy still verifies
        row.update(cnt=str(int(row["cnt"]) * 3 + 1000), casual=str(int(row["casual"]) * 3 + 1000), registered=str(int(row["registered"]) * 3))


def test_with_every_public_check_target_changed_the_three_dev_maes_are_unchanged(tmp_path):
    examples = examples_copy(tmp_path, rows=lambda rows: [from_public_check_on(row) for row in rows])
    study, _ = init_study(tmp_path, examples=examples)
    code, payload, err = run_ml(study, "ridge_v1", "dev", "ridge-dev", "--examples-dir", examples)
    assert code == 0, (payload, err)
    record, _ = assessed(study, payload["attempt"], "--examples-dir", examples)
    assert recorded_maes(record) == pytest.approx(expected_maes(study, "dev", BIKE_FEATURES), abs=1e-9)  # from the unchanged day.csv


@pytest.fixture(scope="module")
def bike_public(tmp_path_factory):
    """(Study, Attempt): `ridge_v1` run on Bike `public_check`, not yet assessed."""
    study, attempts = fresh_study(tmp_path_factory.mktemp("bike-public"), "ridge_v1", partition="public_check")
    return study, attempts["ridge_v1"]


@pytest.mark.parametrize("partition", ["dev", "public_check"])
def test_the_series_given_to_compute_lags_holds_only_dates_before_the_last_scored_items_date(bike_ridge, bike_public, partition, monkeypatch):
    from hypotrail.ml import lags

    study, attempt = (bike_ridge[0], bike_ridge[1]) if partition == "dev" else bike_public
    latest, original = [], lags.compute_lags

    def probe(values, day, features):
        latest.append(max(values))
        return original(values, day, features)

    monkeypatch.setattr(lags, "compute_lags", probe)
    record, _ = assessed(study, attempt)
    last = max(item_dates(study, partition).values())
    assert recorded_maes(record) and latest
    assert max(latest) < last, (max(latest), last)


def order_probes(monkeypatch, order):
    """Wrap `exposure.record` and the series reader so that each appends to `order`: when the record returns, when the parse is called."""
    from hypotrail.core import exposure
    from hypotrail.ml import series

    record, parse = exposure.record, series.target_series

    def recorded(*args, **kwargs):
        result = record(*args, **kwargs)
        order.append("exposure.record returned")
        return result

    def parsed(*args, **kwargs):
        order.append("series parsed")
        return parse(*args, **kwargs)

    monkeypatch.setattr(exposure, "record", recorded)
    monkeypatch.setattr(series, "target_series", parsed)


def test_on_public_check_the_copy_is_parsed_after_exposure_record_returns_and_the_journal_gains_one_entry(bike_public, monkeypatch):
    from _exposure_helpers import journal

    study, attempt = bike_public
    before, order = journal(study), []
    order_probes(monkeypatch, order)
    record, _ = assessed(study, attempt)
    assert recorded_maes(record)
    added = journal(study)[len(before):]
    assert len(added) == 1 and added[0]["assessment_ids"] == [record["assessment_id"]]
    assert order == ["exposure.record returned", "series parsed"]


def test_when_the_exposure_is_refused_with_protocol_changed_the_copy_is_never_parsed(bike_public, tmp_path, monkeypatch):
    study, attempt = bike_public
    changed = examples_copy(tmp_path, edit=lambda d: d.update(target_unit="rides per day"))
    order = []
    order_probes(monkeypatch, order)
    code, payload, err = assess(study, observation_set_id(study, attempt), MAE, references_id(study), "--examples-dir", changed)
    assert (code, payload["error"]["code"]) == (3, "PROTOCOL_CHANGED"), (payload, err)
    assert "series parsed" not in order


# --- a damaged copy of the dataset or of workload.json is refused before any write ---------------------------------------------


def removed(path):
    path.unlink()


def one_byte_changed(path):
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 1
    path.write_bytes(bytes(data))


def truncated(path):
    path.write_bytes(b"")


def kept_declaration(study, attempt) -> Path:
    """The copy of `workload.json` the Attempt keeps, as its manifest names it."""
    manifest = json.loads((Path(study) / "attempts" / attempt["attempt_id"] / "attempt.json").read_text(encoding="utf-8"))
    return Path(study) / next(ref["path"] for ref in manifest["input_refs"] if ref["role"] == "workload_declaration")


COPIES = {"dataset": lambda study, attempt: Path(study) / "datasets" / "day.csv", "workload.json": kept_declaration}


@pytest.mark.parametrize("partition", ["dev", "public_check"])
@pytest.mark.parametrize("damage, code", [(removed, "ARTIFACT_MISSING"), (one_byte_changed, "ARTIFACT_INTEGRITY"), (truncated, "ARTIFACT_INTEGRITY")])
@pytest.mark.parametrize("kept", list(COPIES))
def test_a_damaged_copy_of_the_dataset_or_of_workload_json_is_refused_with_its_code_before_any_write_and_an_intact_one_is_assessed(
    tmp_path, kept, partition, damage, code
):
    from _exposure_helpers import journal
    from test_write_sequence import seq, tree_without_lock

    study, attempts = fresh_study(tmp_path, "ridge_v1", partition=partition)
    attempt = attempts["ridge_v1"]
    copy = COPIES[kept](study, attempt)
    intact = copy.read_bytes()
    damage(copy)
    files, sequence = tree_without_lock(study), seq(study)
    exit_code, payload, err = assess(study, observation_set_id(study, attempt), MAE, references_id(study))
    assert exit_code == 3 and (payload["error"]["code"], payload["error"]["stage"]) == (code, "artifact"), (payload, err)
    assert not (study / "assessments").exists() and journal(study) == [] and not list(study.glob("revisions/*/freeze.json"))
    assert tree_without_lock(study) == files and seq(study) == sequence
    copy.write_bytes(intact)
    record, _ = assessed(study, attempt)
    assert recorded_maes(record) == pytest.approx(expected_maes(study, partition, BIKE_FEATURES), abs=1e-9)
    assert len(journal(study)) == (1 if partition == "public_check" else 0)


@pytest.mark.parametrize("damage", [removed, one_byte_changed, truncated])
def test_with_the_kept_copy_of_workload_json_damaged_seasonal_7_and_an_import_are_assessed_with_exit_0(tmp_path, damage):
    """`seasonal_7` declares no lag feature and an Import no Configuration: neither reads a copy of `workload.json`."""
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    source, mapping, population, _ = ready(tmp_path)
    code, payload, err = import_ml(study, source, mapping, population, "import-a")
    assert code == 0, (payload, err)
    damage(kept_declaration(study, attempts["seasonal_7"]))  # the one copy of workload.json this Study keeps
    found = {}
    for name, attempt in (("seasonal_7", attempts["seasonal_7"]), ("import", payload["attempt"])):
        code, assessment, _ = assess(study, observation_set_id(study, attempt), MAE, references_id(study))
        found[name] = (code, assessment.get("error", {}).get("code"))
    assert found == {"seasonal_7": (0, None), "import": (0, None)}, found


def test_with_no_declared_kind_in_the_targets_unit_prepare_reads_no_copy_and_refuses_nothing_with_workload_json_damaged(tmp_path, monkeypatch):
    from hypotrail.core import artifacts
    from hypotrail.core.errors import HypotrailError
    from hypotrail.ml import single_features

    study, attempts = fresh_study(tmp_path, "ridge_v1")
    attempt = attempts["ridge_v1"]
    one_byte_changed(kept_declaration(study, attempt))
    folder = study / "attempts" / attempt["attempt_id"]
    manifest = json.loads((folder / "attempt.json").read_text(encoding="utf-8"))
    population_ref = json.loads((folder / "observation_set.json").read_text(encoding="utf-8"))["population_ref"]
    reads, verified = [], artifacts.read_verified

    def spied(study, ref):
        reads.append(ref["path"])
        return verified(study, ref)

    monkeypatch.setattr(artifacts, "read_verified", spied)
    monkeypatch.setattr(single_features, "IN_TARGET_UNIT", frozenset())
    try:
        prepared = single_features.prepare(study, manifest, population_ref)
    except HypotrailError as error:
        prepared = error
    assert (reads, prepared) == ([], single_features.Prepared(())), (reads, prepared)


# --- what assess still does not do ------------------------------------------------------------------------------------------


def test_assess_computes_the_check_on_bike_dev_in_an_interpreter_where_sklearn_and_numpy_cannot_be_imported(bike_ridge):
    study, attempt, _, _ = bike_ridge
    body = """
        import contextlib, io
        from hypotrail import cli

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["assess", "--study", sys.argv[2], "--observations", sys.argv[3], "--scorer", "regression_mae_v1", "--references", sys.argv[4], "--json"])
        RESULT = {"code": code, "assessment": json.loads(out.getvalue()).get("assessment")}
    """
    result = run_blocked(["sklearn", "numpy"], body, study, observation_set_id(study, attempt), references_id(study))
    assert result["code"] == 0 and result["loaded"] == []
    assert recorded_maes(result["assessment"]) == pytest.approx(expected_maes(study, "dev", BIKE_FEATURES), abs=1e-9)


def test_the_docstring_of_ml_assess_no_longer_says_it_predicts_nothing_and_names_the_dataset_and_the_lag_features():
    from hypotrail.ml import assess as module

    text = " ".join(module.__doc__.split())
    assert "predicts nothing" not in text
    assert "dataset" in text and "lag feature" in text
