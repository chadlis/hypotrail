"""Ticket #71: `compare` writes a Comparison of two Assessments as Control and Candidate."""

import json
from pathlib import Path

import pytest
from _assess_helpers import rows_of
from _compare_helpers import assessed, compare, comparisons
from _study_helpers import run_cli

from hypotrail.core import artifacts, comparison, intervals
from hypotrail.ml.comparison import compare as library_compare

BIKE = Path(__file__).resolve().parent.parent / "examples" / "bike_day"


@pytest.fixture(scope="module")
def dev(tmp_path_factory):
    return assessed(tmp_path_factory.mktemp("dev"), "seasonal_7", "ridge_v1")


def test_a_strict_comparison_holds_what_the_spec_names_and_is_valid_against_the_contract(dev):
    study, _, a = dev
    code, payload, _ = compare(study, a["seasonal_7"]["assessment_id"], a["ridge_v1"]["assessment_id"])
    assert code == 0
    record = payload["comparison"]
    assert record["roles"] == {
        "control_assessment_id": a["seasonal_7"]["assessment_id"],
        "candidate_assessment_id": a["ridge_v1"]["assessment_id"],
    }
    assert record["comparability"]["status"] == "compatible"
    assert [(c["check"], c["passed"]) for c in record["comparability"]["checks"]] == [
        ("population", True), ("references", True), ("scorer", True), ("unit", True), ("items", True), ("mode", True), ("coverage", True),
    ]
    assert record["coverage"] == {"expected": 182, "control_scored": 182, "candidate_scored": 182, "paired": 182}
    assert record["limitations"]
    assert (study / "comparisons" / record["comparison_id"] / "comparison.json").is_file()
    assert record["comparison_id"] in comparisons(study)


def test_on_dev_the_per_date_differences_and_delta_mae_equal_the_library_comparison_within_1e_9(dev, tmp_path):
    study, attempts, a = dev
    _, payload, _ = compare(study, a["seasonal_7"]["assessment_id"], a["ridge_v1"]["assessment_id"])
    record = payload["comparison"]

    def predictions(config):
        return study / "attempts" / attempts[config]["attempt_id"] / "predictions.csv"

    library = library_compare(
        predictions("seasonal_7"), predictions("ridge_v1"), study / "artifacts" / "references.csv",
        study / "artifacts" / "memberships.csv", tmp_path / "out", BIKE,
    )
    assert record["delta"]["metric"] == "mae" and record["delta"]["unit"] == "rentals per day"
    assert abs(record["delta"]["value"] - library["delta_mae"]["value"]) < 1e-9
    assert round(record["delta"]["value"], 2) == 173.94  # positive: the Candidate is worse; no improvement is required
    paired = {r["row_id"]: r for r in rows_of(study / record["paired_deltas_ref"]["path"])}
    assert len(paired) == 182
    for difference in library["differences"]:
        got = paired[difference["row_id"]]
        assert abs(float(got["delta_abs_error"]) - difference["delta_abs_error"]) < 1e-9
        assert abs(float(got["control_abs_error"]) - difference["control_abs_error"]) < 1e-9
        assert abs(float(got["candidate_abs_error"]) - difference["candidate_abs_error"]) < 1e-9


def test_swapping_the_roles_flips_the_sign_of_the_delta(dev):
    study, _, a = dev
    _, forward, _ = compare(study, a["seasonal_7"]["assessment_id"], a["ridge_v1"]["assessment_id"])
    _, backward, _ = compare(study, a["ridge_v1"]["assessment_id"], a["seasonal_7"]["assessment_id"])
    assert backward["comparison"]["delta"]["value"] == pytest.approx(-forward["comparison"]["delta"]["value"])


# --- #154: a side that a lag feature of its own Configuration beats ---------------------------------------------------------------

SINGLE_FEATURE = "COMPARISON_SINGLE_FEATURE_BEATS"


def single_feature_warnings(record) -> list:
    return [w for w in record["warnings"] if w["code"] == SINGLE_FEATURE]


@pytest.mark.parametrize("ridge_is", ["candidate", "control"])
def test_a_side_beaten_by_its_own_lag_features_holds_one_warning_naming_the_side_and_the_features_also_in_limitations(dev, ridge_is):
    study, _, a = dev
    beaten = a["ridge_v1"].get("single_feature_check", {}).get("beating", [])
    control, candidate = (a["seasonal_7"], a["ridge_v1"]) if ridge_is == "candidate" else (a["ridge_v1"], a["seasonal_7"])
    code, payload, err = compare(study, control["assessment_id"], candidate["assessment_id"])
    assert code == 0, (payload, err)
    record = payload["comparison"]
    warnings = single_feature_warnings(record)
    assert [w["code"] for w in record["warnings"]] == [SINGLE_FEATURE]
    message = warnings[0]["message"]
    assert f"The {ridge_is} of this Comparison" in message and a["ridge_v1"]["assessment_id"] in message
    assert [entry["feature"] for entry in beaten] == ["mean_previous_7", "lag_1", "lag_7"]
    assert all(f"{entry['feature']} ({entry['value']:.6g} rentals per day)" in message for entry in beaten), message
    assert message in record["limitations"]
    assert [c["check"] for c in record["comparability"]["checks"]] == ["population", "references", "scorer", "unit", "items", "mode", "coverage"]
    assert record["comparability"]["status"] == "compatible"


def test_two_flagged_sides_hold_two_warnings_one_naming_each_side(tmp_path):
    from _assess_helpers import assess, observation_set_id, references_id
    from _study_helpers import examples_copy, init_study, run_ml
    from test_single_feature import lag_1_only

    examples = examples_copy(tmp_path, edit=lag_1_only)
    study, _ = init_study(tmp_path, examples=examples)
    ids = {}
    for config in ("ridge_v1", "ridge_lag_1"):
        code, payload, err = run_ml(study, config, "dev", f"run-{config}", "--examples-dir", examples)
        assert code == 0, (payload, err)
        code, payload, err = assess(study, observation_set_id(study, payload["attempt"]), "regression_mae_v1", references_id(study))
        assert code == 0 and payload["assessment"]["single_feature_check"]["beating"], (payload, err)
        ids[config] = payload["assessment"]["assessment_id"]
    code, payload, err = compare(study, ids["ridge_v1"], ids["ridge_lag_1"])
    assert code == 0, (payload, err)
    messages = [w["message"] for w in single_feature_warnings(payload["comparison"])]
    assert len(messages) == 2
    assert "The control of this Comparison" in messages[0] and ids["ridge_v1"] in messages[0] and "mean_previous_7" in messages[0]
    assert "The candidate of this Comparison" in messages[1] and ids["ridge_lag_1"] in messages[1] and "mean_previous_7" not in messages[1]


def test_a_side_whose_field_is_empty_or_absent_adds_no_warning(dev, tmp_path):
    from _assess_helpers import assess, observation_set_id, references_id
    from _compare_helpers import forged

    study, attempts, a = dev
    code, payload, err = assess(study, observation_set_id(study, attempts["seasonal_7"]), "regression_mae_v1", references_id(study))
    assert code == 0 and payload["assessment"]["single_feature_check"] == {"computed": [], "beating": []}, (payload, err)
    code, both_empty, err = compare(study, a["seasonal_7"]["assessment_id"], payload["assessment"]["assessment_id"])
    assert code == 0 and both_empty["comparison"]["warnings"] == [], (both_empty, err)
    absent = [forged(study, a[c], lambda r: r.pop("single_feature_check", None)) for c in ("seasonal_7", "ridge_v1")]
    assert all("single_feature_check" not in record for record in absent)
    code, both_absent, err = compare(study, absent[0]["assessment_id"], absent[1]["assessment_id"])
    assert code == 0 and both_absent["comparison"]["warnings"] == [], (both_absent, err)


def test_the_status_line_of_compare_names_the_single_feature_warning_beside_the_status(dev):
    from _study_helpers import run_cli

    study, _, a = dev
    code, out, err = run_cli("compare", "--study", study, "--control", a["seasonal_7"]["assessment_id"], "--candidate", a["ridge_v1"]["assessment_id"])
    assert code == 0, err
    assert f"(compatible, with warning {SINGLE_FEATURE}): delta mae" in out, out


# --- #155: a Declared deviation that covers a side ------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def four(tmp_path_factory):
    from _deviation_helpers import bike_world

    return bike_world(tmp_path_factory.mktemp("four"))


@pytest.fixture
def world(four, tmp_path):
    import shutil

    study, attempts, assessments = four
    shutil.copytree(study, tmp_path / "study")
    return tmp_path / "study", attempts, assessments


@pytest.mark.parametrize("roles", [("control",), ("candidate",), ("control", "candidate")], ids=["the Control's Attempt", "the Candidate's", "both"])
def test_a_declaration_that_cites_a_sides_attempt_puts_one_warning_naming_the_side_its_id_and_its_text_in_the_comparison(world, roles):
    from _deviation_helpers import a_declaration_covers_the_sides_whose_attempt_it_cites

    a_declaration_covers_the_sides_whose_attempt_it_cites(world, roles)


def test_a_declaration_that_cites_the_references_set_covers_both_sides_and_its_warning_names_both(world):
    from _deviation_helpers import a_references_citation_covers_both_sides

    a_references_citation_covers_both_sides(world)


def test_a_comparison_of_two_other_attempts_of_the_study_holds_no_warning_for_a_declaration_that_cites_an_attempt(world):
    from _deviation_helpers import a_declaration_covers_no_other_side

    a_declaration_covers_no_other_side(world)


def test_two_declarations_that_cover_one_comparison_give_one_warning_each_in_the_order_of_their_write_sequence(world):
    from _deviation_helpers import two_declarations_give_one_warning_each_in_the_order_of_their_write_sequence

    two_declarations_give_one_warning_each_in_the_order_of_their_write_sequence(world)


def test_a_withdrawal_covers_no_side_and_no_warning_names_it_or_the_declaration_it_withdrew(world):
    from _deviation_helpers import a_withdrawal_gives_no_coverage

    a_withdrawal_gives_no_coverage(world)


def test_a_comparison_written_before_a_declaration_or_a_withdrawal_is_not_updated_and_a_new_compare_writes_another(world):
    from _deviation_helpers import a_comparison_is_not_updated_and_a_new_compare_is_the_remedy

    a_comparison_is_not_updated_and_a_new_compare_is_the_remedy(world)


def test_a_declaration_that_cites_the_earlier_references_set_does_not_cover_a_side_scored_against_the_corrected_one(tmp_path):
    from _deviation_helpers import a_corrected_references_set_is_not_covered, bike_world, reassessed, references_of
    from _revision_helpers import new_revision
    from _study_helpers import examples_copy

    def corrected_day(table):
        row = next(r for r in table if r["dteday"] == "2012-03-15")
        row["cnt"], row["registered"] = str(int(row["cnt"]) + 1000), str(int(row["registered"]) + 1000)

    study, attempts, earlier = bike_world(tmp_path, count=2)
    earlier_set = references_of(study)
    code, payload, err = new_revision(study, "--examples-dir", examples_copy(tmp_path, rows=corrected_day, name="revised"))
    assert code == 0, (payload, err)
    assert references_of(study) != earlier_set
    a_corrected_references_set_is_not_covered(earlier_set, earlier, reassessed(study, attempts, "regression_mae_v1"), study)


def test_a_withdrawn_declaration_covers_nothing_and_a_new_declaration_of_the_same_attempt_has_a_new_id_and_covers_it(world):
    from _deviation_helpers import compare_ids, declare, ids_named

    study, attempts, assessments = world
    first = declare(study, [attempts[0]])
    declare(study, [first["declared_deviation_id"]], text="the review is done")
    again = declare(study, [attempts[0]])
    assert again["declared_deviation_id"] != first["declared_deviation_id"]
    assert ids_named(compare_ids(study, assessments[0], assessments[1])) == [again["declared_deviation_id"]]


def test_a_comparison_written_after_a_withdrawal_holds_no_warning_for_it_and_the_earlier_files_and_the_withdrawal_are_as_recorded(world):
    import json

    from _deviation_helpers import CODE, compare_ids, declare, files
    from _study_helpers import sha256

    study, attempts, assessments = world
    declared = declare(study, [attempts[0]])
    [declaration_file] = files(study)
    kept = sha256(declaration_file)
    before = compare_ids(study, assessments[0], assessments[1])
    before_file = study / "comparisons" / before["comparison_id"] / "comparison.json"
    kept_comparison = sha256(before_file)
    withdrawal = declare(study, [declared["declared_deviation_id"]], text="the review is done", author="proxy")
    after = compare_ids(study, assessments[0], assessments[1])
    assert [w["code"] for w in before["warnings"]] == [CODE] and [w["code"] for w in after["warnings"]] == []
    assert sha256(declaration_file) == kept and sha256(before_file) == kept_comparison
    recorded = json.loads(files(study)[1].read_text(encoding="utf-8"))
    assert recorded == withdrawal
    assert (recorded["cited_ids"], recorded["author"], recorded["text"]) == ([declared["declared_deviation_id"]], "proxy", "the review is done")


def test_without_json_the_status_line_of_compare_names_the_declared_deviation_code_beside_the_status_and_stderr_holds_its_warning(world):
    import json

    from _deviation_helpers import CODE, declare
    from _study_helpers import run_cli

    study, attempts, assessments = world
    declare(study, [attempts[0]])
    code, out, err = run_cli("compare", "--study", study, "--control", assessments[0], "--candidate", assessments[1])
    assert code == 0, (out, err)
    (line,) = [line for line in out.splitlines() if line.startswith("Comparison ")]
    record = json.loads((study / "comparisons" / line.split()[1] / "comparison.json").read_text(encoding="utf-8"))
    assert line.startswith(f"Comparison {record['comparison_id']} ({record['comparability']['status']}") and CODE in line.split("):")[0], line
    (warning,) = [w for w in record["warnings"] if w["code"] == CODE]
    assert f"{CODE}: {warning['message']}" in err.splitlines()


# --- the interval over days, by circular blocks ---------------------------------------------------------------------------------


def stored(study, record) -> dict:
    return json.loads((Path(study) / "comparisons" / record["comparison_id"] / "comparison.json").read_text())


def deltas_in_date_order(study, record) -> list:
    """The `delta_abs_error` column of the record's paired deltas, ordered by the dates of the Study's memberships."""
    dates = {row["row_id"]: row["date"] for row in rows_of(Path(study) / "artifacts" / "memberships.csv")}
    rows = rows_of(Path(study) / record["paired_deltas_ref"]["path"])
    return [float(row["delta_abs_error"]) for row in sorted(rows, key=lambda row: dates[row["row_id"]])]


def test_a_dev_comparison_holds_an_interval_over_its_182_days_by_circular_blocks_of_7_from_its_paired_deltas_in_date_order(dev):
    study, _, a = dev
    record = stored(study, compare(study, a["seasonal_7"]["assessment_id"], a["ridge_v1"]["assessment_id"])[1]["comparison"])
    declared = json.loads((Path(study) / "study.json").read_text())["resampling"]
    bounds = intervals.circular_block_interval(deltas_in_date_order(study, record), length=7, seed=declared["seed"])
    assert record["interval"] == {
        "unit": "item",
        "units": 182,
        "method": "percentile_bootstrap",
        "variant": "circular",
        "block_length": 7,
        "seed": declared["seed"],
        "level": 0.95,
        "resamples": 2000,
        "reason": None,
        "lower": bounds["lower"],
        "upper": bounds["upper"],
    }
    assert record["limitations"][0] == comparison.LIMITATION_BLOCKS.format(length=7)


def test_the_compare_line_gives_the_bounds_the_level_and_the_items_in_blocks_of_7_days(dev):
    study, _, a = dev
    code, out, _ = run_cli("compare", "--study", study, "--control", a["seasonal_7"]["assessment_id"], "--candidate", a["ridge_v1"]["assessment_id"])
    assert code == 0 and "0.95 interval [" in out and "over 182 Items in blocks of 7 days" in out
    assert "significan" not in out.lower() and "p-value" not in out.lower()


def test_the_days_are_ordered_by_the_dates_of_the_memberships_not_by_the_spelling_of_their_ids(tmp_path):
    ids = {"day:c": "2012-01-01", "day:a": "2012-01-02", "day:b": "2012-01-03", "day:z": "2011-12-31"}
    lines = ["row_id,date,partition,exclusion_reason", *(f"{row_id},{date},dev," for row_id, date in ids.items()), "day:w,2011-01-01,,insufficient_history"]
    ref = artifacts.publish_bytes(tmp_path, "artifacts/memberships.csv", ("\n".join(lines) + "\n").encode(), media_type="text/csv", role="memberships")
    spec = {"artifacts": [{"artifact_id": "memberships", "ref": ref}]}
    assert comparison.date_order(tmp_path, spec, "dev", sorted(ids)) == ["day:z", "day:c", "day:a", "day:b"]
    assert comparison.date_order(tmp_path, spec, "dev", ["day:a", "day:b", "day:c"]) is None  # a day of the Partition is missing


def test_a_comparison_of_imports_whose_population_lists_fewer_days_than_the_partition_holds_no_bounds_series_not_contiguous(tmp_path):
    from _assess_helpers import assess, init_study, observation_set_id, references_id
    from _import_helpers import FIELDS, export, import_ml, mapping_of, write_json, write_rows
    from _import_helpers import rows_of as import_rows

    study, _ = init_study(tmp_path)
    source, digest = export(tmp_path)
    rows = import_rows(source)
    kept = rows[:50] + rows[51:]  # one day of the Partition left out
    subset = write_rows(tmp_path / "gap.csv", kept, FIELDS)
    population = write_json(tmp_path / "gap.json", {"item_ids": [row["day_key"] for row in kept]})
    sides = []
    for name in ("first", "second"):
        code, payload, err = import_ml(study, subset, mapping_of(tmp_path, digest, name=f"{name}-mapping.json"), population, name)
        assert code == 0, (payload, err)
        code, payload, err = assess(study, observation_set_id(study, payload["attempt"]), "regression_mae_v1", references_id(study))
        assert code == 0, (payload, err)
        sides.append(payload["assessment"])
    record = stored(study, compare(study, sides[0]["assessment_id"], sides[1]["assessment_id"])[1]["comparison"])
    interval = record["interval"]
    assert (interval["lower"], interval["upper"], interval["units"], interval["reason"]) == (None, None, None, "series_not_contiguous")
    assert (record["delta"]["value"], record["comparability"]["status"], record["coverage"]["paired"]) == (0.0, "descriptive_only", 181)
    assert record["limitations"][0] == comparison.LIMITATION_DEPENDENCE


def test_a_bike_comparison_whose_delta_is_withheld_holds_an_interval_with_no_bounds_and_reason_delta_withheld(tmp_path):
    from _client_helpers import bike_withheld_study

    study = bike_withheld_study(tmp_path)
    [path] = (Path(study) / "comparisons").glob("*/comparison.json")
    record = json.loads(path.read_text())
    assert record["delta"]["value"] is None
    assert (record["interval"]["lower"], record["interval"]["upper"], record["interval"]["reason"]) == (None, None, "delta_withheld")
    assert record["limitations"][0] == comparison.LIMITATION_DEPENDENCE
