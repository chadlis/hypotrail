"""`profile --study=DIR [--examples-dir DIR] --json`: the data profile of a Bike Study's `train` Items, read from the Study's own dataset copy
and memberships. It takes no lock and writes nothing. No model is called."""

import datetime
import json
import math
import shutil

import pytest
from _chinook_helpers import init_chinook
from _review_helpers import files, status
from _study_helpers import EXAMPLES, ROOT, examples_copy, init_study, run_cli
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform
from scipy.stats import spearmanr
from test_study_lock import held_by_another_process

from hypotrail.core import canonical
from hypotrail.core.figures import figures_of
from hypotrail.ml import profile as module
from hypotrail.ml.declaration import load_declaration
from hypotrail.ml.lags import compute_lags
from hypotrail.ml.series import read_target_series
from hypotrail.ml.table import read_table

FIXTURE = ROOT / "tests" / "fixtures" / "profile" / "bike_day"
# The Bike columns and their kinds on `train`, as chadlis/hypotrail#259 measured them on `day.csv`.
KINDS = {
    "instant": "numeric", "season": "categorical", "yr": "categorical", "mnth": "categorical", "holiday": "categorical",
    "weekday": "categorical", "workingday": "categorical", "weathersit": "categorical", "temp": "numeric", "atemp": "numeric",
    "hum": "numeric", "windspeed": "numeric", "casual": "numeric", "registered": "numeric",
}
FORBIDDEN = {"casual", "registered", "temp", "atemp", "hum", "windspeed", "weathersit"}


def read(study, *more):
    """(exit code, the object printed, stderr) of `profile --study=DIR --json`."""
    code, out, err = run_cli("profile", f"--study={study}", *more, "--json")
    return code, json.loads(out), err


@pytest.fixture(scope="module")
def bike(tmp_path_factory):
    study, _ = init_study(tmp_path_factory.mktemp("profile-bike"))
    return study


@pytest.fixture(scope="module")
def bike_read(bike):
    code, payload, err = read(bike)
    assert code == 0, (payload, err)
    return payload


def fixture_examples(tmp_path):
    """A copy of `examples/` whose Bike data file and lock are the fixture's: its `dev` and `public_check` rows differ in every column."""
    target = tmp_path / "fixture-examples"
    shutil.copytree(EXAMPLES, target)
    shutil.copyfile(FIXTURE / "data" / "day.csv", target / "bike_day" / "data" / "day.csv")
    shutil.copyfile(FIXTURE / "data-sources.lock.json", target / "bike_day" / "data-sources.lock.json")
    return target


# --- the measures ---------------------------------------------------------------------------------------------------------------


def test_bergsma_v_of_a_three_by_four_table_equals_the_value_worked_by_hand_and_a_single_row_gives_none():
    table = [[10, 5, 3, 2], [4, 8, 6, 2], [1, 2, 7, 10]]
    n = 60  # rows 20, 20, 20; columns 15, 15, 16, 14
    rows, cols = [20, 20, 20], [15, 15, 16, 14]
    chi2 = sum((table[i][j] - rows[i] * cols[j] / n) ** 2 / (rows[i] * cols[j] / n) for i in range(3) for j in range(4))
    phi2 = max(0.0, chi2 / n - (4 - 1) * (3 - 1) / (n - 1))
    r_tilde, k_tilde = 3 - (3 - 1) ** 2 / (n - 1), 4 - (4 - 1) ** 2 / (n - 1)
    by_hand = math.sqrt(phi2 / min(r_tilde - 1, k_tilde - 1))
    assert module.bergsma_v(table) == pytest.approx(by_hand, rel=1e-12, abs=0)
    assert module.bergsma_v([[3, 4, 5, 6]]) is None


def test_spearman_with_ties_equals_scipy_eta_equals_the_value_worked_by_hand_and_a_constant_column_or_nine_rows_give_null():
    x = [1, 2, 2, 3, 4, 4, 4, 5, 6, 7, 8]
    y = [2, 1, 3, 3, 5, 4, 6, 6, 8, 7, 9]
    value, reason = module.spearman(x, y)
    assert reason is None and value == spearmanr(x, y).statistic
    # eta of the ranks of [1, 2, 2, 3, 4, 4, 4, 5, 6, 7, 8] across a, a, a, b, b, b, b, c, c, c, c
    ranks = [1, 2.5, 2.5, 4, 6, 6, 6, 8, 9, 10, 11]
    groups = {"a": ranks[0:3], "b": ranks[3:7], "c": ranks[7:11]}
    mean = 6.0
    between = sum(len(g) * (sum(g) / len(g) - mean) ** 2 for g in groups.values())
    total = sum((r - mean) ** 2 for r in ranks)
    value, reason = module.eta(x, ["a"] * 3 + ["b"] * 4 + ["c"] * 4)
    assert reason is None and value == pytest.approx(math.sqrt(between / total), rel=1e-12, abs=0)
    assert module.spearman(x, [3] * 11) == (None, module.CONSTANT_COLUMN)
    assert module.eta(x, ["a"] * 11) == (None, module.CONSTANT_COLUMN)
    assert module.cramers_v(["a"] * 11, ["a", "b"] * 5 + ["a"]) == (None, module.CONSTANT_COLUMN)
    assert module.spearman(x[:9], y[:9]) == (None, module.TOO_FEW_ROWS)
    assert module.cramers_v(["a", "b"] * 4 + ["a"], ["a"] * 9) == (None, module.TOO_FEW_ROWS)


def test_the_order_is_scipys_average_linkage_leaf_order_on_one_minus_the_absolute_association():
    names = ["a", "b", "c", "d", "e"]
    values = {("a", "b"): 0.9, ("a", "c"): -0.1, ("a", "d"): 0.3, ("a", "e"): None, ("b", "c"): 0.2, ("b", "d"): -0.85,
              ("b", "e"): 0.05, ("c", "d"): 0.4, ("c", "e"): 0.7, ("d", "e"): -0.6}
    matrix = [[0.0 if a == b else 1 - abs(values.get((a, b), values.get((b, a))) or 0) for b in names] for a in names]
    expected = [names[i] for i in leaves_list(linkage(squareform(matrix), "average"))]
    assert module.clustering_order(names, values) == expected


def test_the_lag_series_holds_no_dev_or_public_check_day_and_reads_none_of_their_cells():
    declaration = load_declaration(EXAMPLES / "bike_day")
    table = read_table(EXAMPLES / "bike_day", declaration, ["cnt"])
    memberships = [{"date": day.isoformat(), "partition": next((p.name for p in declaration.partitions if p.first <= day <= p.last), "")} for day in table]
    table[datetime.date(2012, 3, 1)] = {**table[datetime.date(2012, 3, 1)], "cnt": "not a number"}  # a dev day
    kept = module.lag_series(table, memberships, declaration)
    assert all(row["partition"] in ("", "train") for row in memberships if row["date"] in {day.isoformat() for day in kept})
    assert max(kept).isoformat() == "2011-12-31" and len(kept) == 365


# --- the read on a Bike Study ---------------------------------------------------------------------------------------------------


def test_a_fresh_bike_study_gives_358_train_items_the_band_the_target_series_the_14_columns_and_the_forbidden_marks(bike_read):
    payload = bike_read
    assert payload["ok"] is True and payload["items"] == 358 and payload["partition"] == "train"
    assert payload["workload_protocol"] == "same" and payload["revision_number"] == 1
    assert payload["band"] == [
        {"name": "train", "first": "2011-01-08", "last": "2011-12-31"},
        {"name": "dev", "first": "2012-01-01", "last": "2012-06-30"},
        {"name": "public_check", "first": "2012-07-01", "last": "2012-12-31"},
    ]
    series = payload["target"]["series"]
    assert len(series) == 358 and all("2011-01-08" <= point["date"] <= "2011-12-31" for point in series)
    assert payload["target"]["column"] == "cnt" and payload["target"]["figures"] == figures_of([point["value"] for point in series])
    assert {c["name"]: c["kind"] for c in payload["columns"]} == KINDS
    assert {c["name"] for c in payload["columns"] if not c["available"]} == FORBIDDEN
    assert all(c["unavailable"] == ("forbidden_feature" if c["name"] in FORBIDDEN else None) for c in payload["columns"])
    order = payload["associations"]["order"]
    assert sorted(order) == sorted(KINDS) and len(order) == len(set(order))
    pairs = payload["associations"]["pairs"]
    assert len(pairs) == 14 * 13 // 2 and all("cnt" not in (p["a"], p["b"]) for p in pairs)
    assert all(p["value"] is None and p["reason"] == "constant_column" for p in pairs if "yr" in (p["a"], p["b"]))
    assert all(p["flagged"] == (p["value"] is not None and abs(p["value"]) >= 0.8) for p in pairs)
    assert payload["associations"]["level"] == 0.8


def test_against_target_holds_one_entry_per_allowed_column_and_feature_lag_points_from_compute_lags_and_categorical_figures(bike, bike_read):
    entries = {e["name"]: e for e in bike_read["against_target"]}
    assert list(entries) == [*(n for n in KINDS if n not in FORBIDDEN), "lag_1", "lag_7", "mean_previous_7"]
    declaration = load_declaration(EXAMPLES / "bike_day")
    series = read_target_series(EXAMPLES / "bike_day", declaration)
    [lag_1] = [f for f in declaration.allowed_target_features if f.name == "lag_1"]
    target = {p["row_id"]: p for p in bike_read["target"]["series"]}
    for point in entries["lag_1"]["points"]:
        day = datetime.date.fromisoformat(target[point["row_id"]]["date"])
        assert point["feature"] == compute_lags(series, day, [lag_1])["lag_1"] and point["target"] == target[point["row_id"]]["value"]
    assert len(entries["lag_1"]["points"]) == 358 and entries["lag_1"]["measure"] == "spearman"
    season = entries["season"]
    assert season["points"] is None and season["measure"] == "eta"
    assert sum(v["count"] for v in season["values"]) == 358
    for value in season["values"]:
        assert value["figures"]["quartiles"]["min"] >= bike_read["target"]["figures"]["quartiles"]["min"]


def test_the_read_writes_nothing_keeps_the_write_sequence_and_answers_while_another_writer_holds_the_lock(bike):
    before, sequence = files(bike), status(bike)["write_sequence"]
    code, payload, err = read(bike)
    assert code == 0 and payload["write_sequence"] == sequence, (payload, err)
    assert files(bike) == before and status(bike)["write_sequence"] == sequence
    with held_by_another_process(bike):
        code, payload, err = read(bike)
    assert code == 0 and payload["ok"] is True, (payload, err)
    assert files(bike) == before


def test_two_studies_whose_data_differ_only_on_dev_and_public_check_days_give_the_same_profile(bike, bike_read, tmp_path):
    examples = fixture_examples(tmp_path)
    other, _ = init_study(tmp_path, examples=examples, name="fixture-study")
    code, payload, err = read(other, f"--examples-dir={examples}")
    assert code == 0, (payload, err)
    assert canonical.dumps(payload) == canonical.dumps(bike_read)


def test_a_non_number_in_a_dev_cell_of_the_target_is_never_read_and_the_profile_equals_the_one_without_it(tmp_path):
    def planted(rows):
        [row] = [row for row in rows if row["dteday"] == "2012-03-01"]  # a dev day
        row["temp"] = "not a number"

    # `temp` is a column no data check reads, so a Study can keep the planted cell; the read is then given `temp` as its target.
    target_temp = examples_copy(tmp_path, edit=lambda d: d.update(target_column="temp"), name="target-temp")
    reads = []
    for name, rows in (("clean", None), ("planted", planted)):
        examples = examples_copy(tmp_path, rows=rows, name=f"examples-{name}")
        study, _ = init_study(tmp_path, examples=examples, name=f"study-{name}")
        code, payload, err = read(study, f"--examples-dir={target_temp}")
        assert code == 0, (name, payload, err)
        reads.append(payload)
    assert canonical.dumps(reads[1]) == canonical.dumps(reads[0])


def test_a_chinook_study_is_refused_with_unsupported_capability_and_nothing_is_written(tmp_path):
    study, _ = init_chinook(tmp_path)
    before = files(study)
    code, payload, err = read(study)
    assert (code, payload.get("error", {}).get("code")) == (2, "UNSUPPORTED_CAPABILITY"), payload
    assert files(study) == before


def test_a_changed_forbidden_list_gives_differs_and_the_same_values_and_a_missing_target_column_is_refused(bike, bike_read, tmp_path):
    changed = examples_copy(tmp_path, edit=lambda d: d["forbidden_features"].remove("temp"), name="changed")
    code, payload, err = read(bike, f"--examples-dir={changed}")
    assert code == 0 and payload["workload_protocol"] == "differs", (payload, err)
    assert payload["items"] == bike_read["items"] and payload["target"] == bike_read["target"]
    assert [c["distribution"] for c in payload["columns"]] == [c["distribution"] for c in bike_read["columns"]]
    assert [c["name"] for c in payload["columns"] if c["name"] == "temp" and c["available"]] == ["temp"]
    missing = examples_copy(tmp_path, edit=lambda d: d.update(target_column="nonesuch"), name="missing")
    code, payload, err = read(bike, f"--examples-dir={missing}")
    assert (code, payload.get("error", {}).get("code")) == (2, "COLUMN_MISSING"), payload


def test_a_forbidden_feature_the_studys_data_does_not_hold_is_refused_with_column_missing_naming_it(bike, tmp_path):
    missing = examples_copy(tmp_path, edit=lambda d: d["forbidden_features"].append("nonesuch"), name="forbidden-missing")
    code, payload, err = read(bike, f"--examples-dir={missing}")
    error = payload.get("error", {})
    assert (code, error.get("code"), error.get("details", {}).get("column")) == (2, "COLUMN_MISSING", "nonesuch"), payload


def test_no_key_of_the_object_names_a_p_value_or_significance_and_the_text_says_neither(bike, bike_read):
    def keys(value):
        if isinstance(value, dict):
            return set(value) | {k for item in value.values() for k in keys(item)}
        return {k for item in value for k in keys(item)} if isinstance(value, list) else set()

    assert [k for k in keys(bike_read) if "p_value" in k or "significance" in k] == []
    code, text, err = run_cli("profile", f"--study={bike}")
    assert code == 0 and "p-value" not in text and "significant" not in text, err
    assert len(text.splitlines()) == 6
