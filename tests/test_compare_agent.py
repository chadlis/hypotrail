"""Ticket #72: `compare` on two Chinook Assessments aligns Episodes by Case and Repeat, keeps the Case x Repeat matrix of each side,
weighs every Case equally under full coverage, and refuses what makes the two sides incomparable."""

import json
from pathlib import Path

import pytest
from _agent_compare_helpers import REPEATS, answer_lines, compare, comparison_files, imported, keys_of, native
from _assess_helpers import rows_of, snapshot
from _chinook_helpers import FIXTURE_CASES, init_chinook
from _study_helpers import run_cli, run_json

from hypotrail.core import canonical, contracts
from hypotrail.core.chinook_contract import CRITERIA

PRIMARY = "contract_success"


@pytest.fixture
def study(tmp_path):
    return init_chinook(tmp_path)[0]


def refused(study, control, candidate, code, check, reason, *more):
    before = snapshot(study)
    exit_code, payload, err = compare(study, control, candidate, *more)
    assert exit_code == 3, (payload, err)
    error = payload["error"]
    assert set(error) == {"code", "message", "stage", "details"}
    assert (error["code"], error["stage"]) == (code, "compare")
    assert (error["details"]["check"], error["details"]["reason"]) == (check, reason)
    assert error["details"]["checks"][-1] == {"check": check, "passed": False, "reason": reason}
    assert snapshot(study) == before  # no Comparison, no file of any kind
    return error["details"]


def matrix_of(study, record):
    return json.loads((Path(study) / record["matrix_ref"]["path"]).read_text())


# --- AC1 and AC5: the alignment, the matrix, the aggregation per Case --------------------------------------------------------


@pytest.fixture
def plain_and_verify(tmp_path, study):
    """`plain` gets D01 right once out of three and everything else right; `verify` gets everything right."""
    _, plain = imported(tmp_path, study, "plain", answer_lines(wrong={("D01", 0), ("D01", 1)}))
    _, verify = imported(tmp_path, study, "verify", answer_lines())
    return study, plain, verify


def test_the_main_delta_is_the_primary_criterion_aggregated_per_case_then_weighed_equally(plain_and_verify):
    study, plain, verify = plain_and_verify
    code, payload, err = compare(study, plain, verify)
    assert code == 0, (payload, err)
    record = payload["comparison"]
    contracts.validate(record)
    assert record["primary_criterion"] == PRIMARY
    assert record["delta"]["metric"] == PRIMARY
    # plain: D01 1/3, the three other Cases 3/3: the mean of the four Case shares, not a count over 12 Episodes read as 12 Cases
    assert record["delta"]["control"] == pytest.approx((1 / 3 + 3) / 4)
    assert record["delta"]["candidate"] == 1.0
    assert record["delta"]["value"] == pytest.approx(1 - (1 / 3 + 3) / 4)
    assert record["delta"]["reason"] is None
    paired = {r["case_id"]: r for r in rows_of(Path(study) / record["paired_deltas_ref"]["path"])}
    assert set(paired) == set(FIXTURE_CASES)  # one row per Case, never one per Repeat
    assert float(paired["D01"]["control_share"]) == pytest.approx(1 / 3) and float(paired["D03"]["control_share"]) == 1.0
    assert paired["D01"]["repeats"] == str(REPEATS)
    assert "positive means the Candidate is better" in record["delta"]["definition"]


def test_no_binomial_interval_is_computed_over_episodes(plain_and_verify):
    study, plain, verify = plain_and_verify
    record = compare(study, plain, verify)[1]["comparison"]
    text = " ".join(record["limitations"])
    assert "no confidence interval" in text and "Repeats of a Case" in text

    def keys(value):
        if isinstance(value, dict):
            for key, inner in value.items():
                yield key
                yield from keys(inner)
        elif isinstance(value, list):
            for inner in value:
                yield from keys(inner)

    assert not [key for key in keys(record) if "interval" in key or "p_value" in key or "significance" in key]


def test_each_side_keeps_its_full_case_by_repeat_matrix_with_every_criterion_state(plain_and_verify):
    study, plain, verify = plain_and_verify
    record = compare(study, plain, verify)[1]["comparison"]
    matrix = matrix_of(study, record)
    assert matrix["criteria"] == list(CRITERIA)
    for role, assessment in (("control", plain), ("candidate", verify)):
        side = matrix[role]
        assert side["assessment_id"] == assessment["assessment_id"]
        assert [c["case_id"] for c in side["cases"]] == sorted(FIXTURE_CASES)
        assert all([e["repeat"] for e in c["episodes"]] == list(range(REPEATS)) for c in side["cases"])
        kept = {(r["case_id"], int(r["repeat"]), r["criterion"]): r for r in rows_of(Path(study) / assessment["per_item_ref"]["path"])}
        for case in side["cases"]:
            for episode in case["episodes"]:
                assert set(episode["criteria"]) == set(CRITERIA)
                for name, cell in episode["criteria"].items():
                    row = kept[(case["case_id"], episode["repeat"], name)]
                    assert cell["state"] == row["state"] and cell["reason"] == (row["reason"] or None)
    d01 = next(c for c in matrix["control"]["cases"] if c["case_id"] == "D01")
    assert [e["criteria"][PRIMARY]["score"] for e in d01["episodes"]] == [False, False, True]


def test_the_secondary_criteria_have_their_own_deltas_beside_the_main_one(plain_and_verify):
    study, plain, verify = plain_and_verify
    record = compare(study, plain, verify)[1]["comparison"]
    assert [d["metric"] for d in record["secondary_deltas"]] == [name for name in CRITERIA if name != PRIMARY]
    exact = next(d for d in record["secondary_deltas"] if d["metric"] == "exact_table")
    assert exact["value"] == pytest.approx(1 - (1 / 3 + 3) / 4)  # the wrong rows are the wrong tables


def test_an_episode_that_is_not_scored_on_a_side_shows_in_the_coverage_and_the_main_delta_is_null_with_a_reason(tmp_path, study):
    _, plain = imported(tmp_path, study, "plain", answer_lines(failed={("D03", 2)}))
    _, verify = imported(tmp_path, study, "verify", answer_lines())
    code, payload, _ = compare(study, plain, verify)
    assert code == 0
    record = payload["comparison"]
    assert record["delta"]["value"] is None and record["delta"]["reason"] == "coverage_incomplete"
    assert record["delta"]["metric"] == PRIMARY
    assert record["coverage"]["expected"] == 12
    assert (record["coverage"]["control_scored"], record["coverage"]["candidate_scored"], record["coverage"]["paired"]) == (11, 12, 11)
    assert record["coverage"]["control_rate"] == pytest.approx(11 / 12) and record["coverage"]["candidate_rate"] == 1.0
    assert record["coverage"]["complete"] is False
    assert record["paired_deltas_ref"] is None  # no per-Case table hides the missing Episode
    failed = next(c for c in matrix_of(study, record)["control"]["cases"] if c["case_id"] == "D03")["episodes"][2]
    assert failed["execution_status"] == "failed" and failed["criteria"][PRIMARY]["state"] == "unscored"
    assert failed["criteria"][PRIMARY]["reason"] == "execution_failed"


def test_without_a_trace_a_correct_answered_episode_leaves_the_primary_unscored_so_the_delta_is_null(tmp_path, study):
    _, plain = imported(tmp_path, study, "plain", answer_lines(traced=False))
    _, verify = imported(tmp_path, study, "verify", answer_lines())
    record = compare(study, plain, verify)[1]["comparison"]
    assert record["delta"]["value"] is None and record["delta"]["reason"] == "coverage_incomplete"
    assert record["coverage"]["control_scored"] == 6  # D07 and D08 need no trace
    secondary = {d["metric"]: d for d in record["secondary_deltas"]}
    assert secondary["exact_table"]["value"] == 0.0 and secondary["evidence_link_valid"]["value"] is None


def test_an_episode_present_on_one_side_only_is_never_dropped_it_shows_in_the_coverage(tmp_path, study):
    _, three = imported(tmp_path, study, "three", answer_lines(repeats=3), repeats=3)
    _, two = imported(tmp_path, study, "two", answer_lines(repeats=2), repeats=2)
    code, payload, _ = compare(study, three, two, "--factor", "repeats")
    assert code == 0, payload
    record = payload["comparison"]
    assert record["coverage"]["expected"] == 12 and record["coverage"]["only_control"] == 4 and record["coverage"]["only_candidate"] == 0
    assert record["coverage"]["paired"] == 8 and record["delta"]["value"] is None and record["delta"]["reason"] == "coverage_incomplete"
    population = json.loads((Path(study) / record["population_ref"]["path"]).read_text())
    assert [c for c, r in population["episodes"] if r == 2] == sorted(FIXTURE_CASES)  # the union is kept, nothing is intersected
    candidate = matrix_of(study, record)["candidate"]
    assert all([e["repeat"] for e in c["episodes"]] == [0, 1] for c in candidate["cases"])


# --- AC6: the two named rates of each side, the unknowns beside them, a null never shown as 0 --------------------------------


def test_the_two_named_rates_of_each_side_are_reported_with_the_unknowns_beside_them(plain_and_verify):
    study, plain, verify = plain_and_verify
    rates = compare(study, plain, verify)[1]["comparison"]["rates"]
    for side, assessment in (("control", plain), ("candidate", verify)):
        assert [m["id"] for m in rates[side]["metrics"]] == ["quality_among_scored", "confirmed_share_of_expected"]
        assert rates[side]["metrics"] == assessment["metrics"]
        assert rates[side]["unknowns"] == assessment["unknowns"]
        assert rates[side]["operational_errors"] == assessment["operational_errors"]
    assert rates["control"]["metrics"][0]["value"] == pytest.approx(10 / 12)


def test_a_null_rate_is_null_with_its_reason_never_zero(tmp_path, study):
    _, none = imported(tmp_path, study, "none", answer_lines(failed={key for key in keys_of()}))
    _, verify = imported(tmp_path, study, "verify", answer_lines())
    record = compare(study, none, verify)[1]["comparison"]
    quality, share = record["rates"]["control"]["metrics"]
    assert quality["value"] is None and quality["reason"] == "no_scored_episode" and quality["status"] == "unscored"
    assert share["value"] == 0.0 and share["denominator"] == 12  # a real zero: 0 confirmed of 12 expected
    assert record["rates"]["control"]["unknowns"]["unscored"] == 12 and record["rates"]["control"]["operational_errors"]["failed"] == 12
    assert record["delta"]["value"] is None and record["delta"]["reason"] == "coverage_incomplete"


# --- AC2 and AC3 on the checks: each refused with its own code, exit 3, and nothing written --------------------------------


def test_two_populations_of_different_cases_are_refused(tmp_path, study):
    _, full = imported(tmp_path, study, "full", answer_lines())
    smaller = [line for line in answer_lines() if line["case_id"] != "D08"]
    source = Path(tmp_path) / "smaller.jsonl"
    source.write_text("".join(json.dumps(line) + "\n" for line in smaller))
    from _chinook_helpers import episodes_file, import_agent

    code, payload, err = import_agent(study, source, episodes_file(tmp_path, keys_of(cases=["D01", "D03", "D07"]), name="p2.json"), "smaller")
    assert code == 0, (payload, err)
    from _agent_compare_helpers import assess, observation_set_of

    other = assess(study, observation_set_of(study, payload["attempt"]))
    details = refused(study, full, other, "COMPARISON_POPULATION_DIFFERS", "population", "population_differs")
    assert details["control"]["cases"] == sorted(FIXTURE_CASES) and details["candidate"]["cases"] == ["D01", "D03", "D07"]


def test_different_planned_repeats_are_refused_unless_the_request_declares_repeats_as_the_factor(tmp_path, study):
    _, three = imported(tmp_path, study, "three", answer_lines(repeats=3), repeats=3)
    _, two = imported(tmp_path, study, "two", answer_lines(repeats=2), repeats=2)
    details = refused(study, three, two, "COMPARISON_REPEATS_DIFFER", "repeats", "repeats_differ")
    assert details["control"]["repeats"]["D01"] == 3 and details["candidate"]["repeats"]["D01"] == 2
    code, payload, _ = compare(study, three, two, "--factor", "repeats")
    assert code == 0 and payload["comparison"]["declared_factor"] == "repeats"
    check = next(c for c in payload["comparison"]["comparability"]["checks"] if c["check"] == "repeats")
    assert check == {"check": "repeats", "passed": True, "reason": "declared_factor"}


@pytest.mark.parametrize(
    "factor,left,right,code,check,reason",
    [
        ("tools", {"tool_use": "describe_schema,query_readonly"}, {"tool_use": "query_readonly"}, "COMPARISON_TOOLS_DIFFER", "tools", "tools_differ"),
        ("model", {"model": "model-a"}, {"model": "model-b"}, "COMPARISON_MODEL_DIFFERS", "model", "model_differs"),
    ],
)
def test_a_difference_in_tools_or_model_is_refused_and_a_declared_factor_lets_it_through(tmp_path, study, factor, left, right, code, check, reason):
    _, control = imported(tmp_path, study, "control", answer_lines(**left))
    _, candidate = imported(tmp_path, study, "candidate", answer_lines(**right))
    refused(study, control, candidate, code, check, reason)
    status, payload, _ = compare(study, control, candidate, "--factor", factor)
    assert status == 0, payload
    record = payload["comparison"]
    assert record["declared_factor"] == factor
    assert next(c for c in record["comparability"]["checks"] if c["check"] == check) == {"check": check, "passed": True, "reason": "declared_factor"}


def test_a_difference_in_budgets_is_refused_between_native_attempts_and_a_declared_factor_lets_it_through(tmp_path, study):
    seed, _ = imported(tmp_path, study, "seed", answer_lines())
    _, tight = native(study, seed, limits={"model_turns": 4})
    _, wide = native(study, seed, limits={"model_turns": 6})
    details = refused(study, tight, wide, "COMPARISON_BUDGETS_DIFFER", "budgets", "budgets_differ")
    assert details["control"] == {"budgets": {"model_turns": 4}} and details["candidate"] == {"budgets": {"model_turns": 6}}
    code, payload, _ = compare(study, tight, wide, "--factor", "budgets")
    assert code == 0 and payload["comparison"]["declared_factor"] == "budgets"


def test_the_configuration_is_the_intentional_factor_of_a_chinook_comparison_and_is_recorded(tmp_path, study):
    seed, _ = imported(tmp_path, study, "seed", answer_lines())
    _, plain = native(study, seed, configuration="plain")
    _, verify = native(study, seed, configuration="verify")
    record = compare(study, plain, verify)[1]["comparison"]
    assert record["declared_factor"] == "configuration"
    assert record["comparability"]["status"] == "compatible"


def test_a_scripted_fixture_side_against_a_llm_live_side_is_refused_and_ranks_nothing(tmp_path, study):
    _, scripted = imported(tmp_path, study, "scripted", answer_lines(mode="scripted_fixture"))
    _, live = imported(tmp_path, study, "live", answer_lines(mode="llm_live"))
    details = refused(study, scripted, live, "COMPARISON_MODE_DIFFERS", "mode", "mode_differs")
    assert details["control"] == {"mode": "scripted_fixture"} and details["candidate"] == {"mode": "llm_live"}
    assert comparison_files(study) == []


def test_native_attempts_of_a_scripted_fixture_and_a_live_mode_are_refused_too(tmp_path, study):
    seed, _ = imported(tmp_path, study, "seed", answer_lines())
    _, scripted = native(study, seed, mode="scripted_fixture")
    _, live = native(study, seed, mode="llm_live")
    refused(study, scripted, live, "COMPARISON_MODE_DIFFERS", "mode", "mode_differs")


def test_two_references_or_two_scorers_are_refused_as_for_the_bike(tmp_path, study):
    from _compare_helpers import forged  # noqa: F401  (the bike's forging writes a bike per-Item file; here the record only changes)

    _, a = imported(tmp_path, study, "a", answer_lines())
    _, b = imported(tmp_path, study, "b", answer_lines())
    for edit, code, check, reason in (
        (lambda r: r["references_ref"].update(sha256="b" * 64), "COMPARISON_REFERENCES_DIFFER", "references", "references_differ"),
        (lambda r: r["scorer"].update(version="9"), "COMPARISON_SCORER_DIFFERS", "scorer", "scorer_differs"),
        (lambda r: r["metrics"][0].update(unit="visits"), "COMPARISON_UNIT_DIFFERS", "unit", "unit_differs"),
    ):
        refused(study, a, rewritten(study, b, edit), code, check, reason)


def test_an_assessment_under_scorer_version_two_does_not_compare_with_one_under_the_current_version(tmp_path, study):
    """#61 Tightened D: CMP-01 strict comparison needs the same Scorer version."""
    _, a = imported(tmp_path, study, "a", answer_lines())
    _, b = imported(tmp_path, study, "b", answer_lines())
    assert b["scorer"]["version"] == "3"
    refused(study, a, rewritten(study, b, lambda r: r["scorer"].update(version="2")), "COMPARISON_SCORER_DIFFERS", "scorer", "scorer_differs")


def rewritten(study, assessment, edit):
    """A new Assessment record that shares `assessment`'s per-Item file and whose record `edit` changes."""
    import uuid

    new_id = str(uuid.uuid4())
    folder = Path(study) / "assessments" / new_id
    folder.mkdir()
    record = json.loads(json.dumps(assessment))
    record["assessment_id"] = new_id
    edit(record)
    (folder / "assessment.json").write_bytes(canonical.dumps(record))
    return record


# --- AC7: public_check ------------------------------------------------------------------------------------------------------------


def test_a_comparison_of_a_dev_side_and_a_public_check_side_is_refused_as_two_populations_and_exposes_nothing(tmp_path, study):
    # #73 lifted the refusal of public_check inside a Study (tests/test_exposure.py); two Partitions are still not one population
    seed, assessment = imported(tmp_path, study, "seed", answer_lines())
    _, hidden = native(study, seed, partition="public_check", assessed=False)
    on_public = rewritten(study, assessment, lambda r: r.update(observation_set_id=hidden))
    before = snapshot(study)
    code, payload, _ = compare(study, assessment, on_public)
    assert (code, payload["error"]["code"], payload["error"]["stage"]) == (3, "COMPARISON_POPULATION_DIFFERS", "compare")
    assert snapshot(study) == before and not (Path(study) / "exposures").exists()


def test_a_partition_other_than_dev_is_refused(tmp_path, study):
    seed, assessment = imported(tmp_path, study, "seed", answer_lines())
    _, train = native(study, seed, partition="train", assessed=False)
    a = rewritten(study, assessment, lambda r: r.update(observation_set_id=train))
    b = rewritten(study, assessment, lambda r: r.update(observation_set_id=train))
    code, payload, _ = compare(study, a, b)
    assert (code, payload["error"]["code"]) == (2, "COMPARISON_PARTITION_NOT_DEV")


# --- what an Import says: descriptive, a warning, nothing hidden -------------------------------------------------------------------


def test_a_comparison_with_an_import_on_either_side_is_descriptive_with_a_warning_whatever_the_origin_of_its_fields(tmp_path, study):
    seed, _ = imported(tmp_path, study, "seed", answer_lines())
    _, own = native(study, seed)
    _, declared = imported(tmp_path, study, "declared", answer_lines())
    _, unknown = imported(tmp_path, study, "unknown", answer_lines(model=None, tool_use=None, mode=None))
    for control, candidate, role in ((own, declared, "candidate"), (unknown, own, "control"), (declared, unknown, "candidate")):
        code, payload, err = compare(study, control, candidate)
        assert code == 0, (payload, err)
        record = payload["comparison"]
        assert record["comparability"]["status"] == "descriptive_only"
        assert [w["code"] for w in record["warnings"]] == ["COMPARISON_DESCRIPTIVE_IMPORT"]
        assert role in record["warnings"][0]["message"] and record["warnings"][0]["message"] in record["limitations"]
        assert "COMPARISON_DESCRIPTIVE_IMPORT" in err
        assert record["delta"]["metric"] == PRIMARY  # descriptive, and still a delta on the primary Criterion


def test_a_factor_that_a_side_does_not_establish_is_not_checked_and_is_said(tmp_path, study):
    _, known = imported(tmp_path, study, "known", answer_lines())
    _, unknown = imported(tmp_path, study, "unknown", answer_lines(model=None, tool_use=None, mode=None))
    record = compare(study, known, unknown)[1]["comparison"]
    checks = {c["check"]: c for c in record["comparability"]["checks"]}
    for name in ("tools", "model", "budgets"):
        assert checks[name] == {"check": name, "passed": False, "reason": "not_established"}
    assert checks["population"]["passed"] is True and checks["repeats"]["passed"] is True
    assert checks["mode"] == {"check": "mode", "passed": False, "reason": "provenance_unverified"}


def test_a_native_side_that_does_not_record_a_factor_makes_the_comparison_descriptive(tmp_path, study):
    seed, _ = imported(tmp_path, study, "seed", answer_lines())
    _, full = native(study, seed)
    _, without_tools = native(study, seed, tools=None)
    record = compare(study, full, without_tools)[1]["comparison"]
    assert record["comparability"]["status"] == "descriptive_only"
    assert [w["code"] for w in record["warnings"]] == ["COMPARISON_FACTOR_NOT_ESTABLISHED"] and "tools" in record["warnings"][0]["message"]


def test_the_strict_path_of_two_native_attempts_is_compatible_and_carries_no_warning(tmp_path, study):
    seed, _ = imported(tmp_path, study, "seed", answer_lines(wrong={("D01", 0)}))
    _, plain = native(study, seed, configuration="plain")
    other, _ = imported(tmp_path, study, "other", answer_lines())
    _, verify = native(study, other, configuration="verify")
    code, payload, err = compare(study, plain, verify)
    assert code == 0 and err == ""
    record = payload["comparison"]
    assert record["comparability"]["status"] == "compatible" and record["warnings"] == []
    assert [(c["check"], c["passed"]) for c in record["comparability"]["checks"]] == [
        ("population", True), ("references", True), ("scorer", True), ("unit", True), ("repeats", True),
        ("tools", True), ("model", True), ("budgets", True), ("mode", True),
    ]
    assert record["delta"]["value"] == pytest.approx(1 - (2 / 3 + 3) / 4)
    assert record["delta"]["reason"] is None and record["coverage"]["complete"] is True


# --- the environment, descriptive measures, --json ---------------------------------------------------------------------------------


def test_different_code_environments_are_said_and_never_called_identical(tmp_path, study):
    seed, _ = imported(tmp_path, study, "seed", answer_lines())
    _, a = native(study, seed)
    _, b = native(study, seed, environment={"python": "3.0.0"})
    record = compare(study, a, b)[1]["comparison"]
    assert record["code_environment"]["same"] is False and record["code_environment"]["differs"] == ["python"]
    assert "not identical" in " ".join(record["limitations"])
    same = compare(study, a, a)[1]["comparison"]
    assert same["code_environment"]["same"] is True and "does not establish" in " ".join(same["limitations"])


def test_latency_and_calls_are_descriptive_and_tokens_and_cost_are_null_never_zero(plain_and_verify):
    study, plain, verify = plain_and_verify
    record = compare(study, plain, verify)[1]["comparison"]
    for side in ("control", "candidate"):
        measures = record["descriptive"][side]
        assert measures == {"latency_seconds": None, "model_calls": 18, "tool_calls": 6, "tokens": None, "cost": None}  # D01 and D03: two turns and one call per Repeat; D07 and D08: one turn
    assert "descriptive" in " ".join(record["limitations"])
    assert record["delta"]["metric"] == PRIMARY  # no cost or call count is compared in the delta


def test_calls_are_null_when_an_episode_keeps_no_trace(tmp_path, study):
    _, plain = imported(tmp_path, study, "plain", answer_lines(traced=False))
    _, verify = imported(tmp_path, study, "verify", answer_lines())
    record = compare(study, plain, verify)[1]["comparison"]
    assert record["descriptive"]["control"]["model_calls"] is None and record["descriptive"]["control"]["tool_calls"] is None
    assert record["descriptive"]["candidate"]["tool_calls"] == 6


def test_with_json_stdout_holds_one_object_and_the_diagnostics_go_to_stderr(plain_and_verify):
    study, plain, verify = plain_and_verify
    code, out, err = run_cli("compare", "--study", study, "--control", plain["assessment_id"], "--candidate", verify["assessment_id"], "--json")
    assert code == 0 and set(json.loads(out)) == {"ok", "comparison"} and "COMPARISON_DESCRIPTIVE_IMPORT" in err
    code, out, err = run_cli("compare", "--study", study, "--control", plain["assessment_id"], "--candidate", verify["assessment_id"], "--factor", "model", "--json")
    assert code == 0 and json.loads(out)["comparison"]["declared_factor"] == "model"
    code, out, err = run_cli("compare", "--study", study, "--control", plain["assessment_id"], "--candidate", "nope", "--json")
    error = json.loads(out)["error"]
    assert code == 2 and set(error) == {"code", "message", "stage", "details"} and error["code"] == "ASSESSMENT_NOT_FOUND"


def test_the_human_line_names_the_primary_delta_and_the_coverage(plain_and_verify):
    study, plain, verify = plain_and_verify
    code, out, _ = run_cli("compare", "--study", study, "--control", plain["assessment_id"], "--candidate", verify["assessment_id"])
    assert code == 0 and PRIMARY in out and "12 of 12" in out


def test_a_factor_is_refused_on_a_study_that_declares_none(tmp_path):
    from _compare_helpers import assessed

    study, _, a = assessed(tmp_path, "seasonal_7", "ridge_v1")
    code, payload, _ = run_json("compare", "--study", study, "--control", a["seasonal_7"]["assessment_id"], "--candidate", a["ridge_v1"]["assessment_id"], "--factor", "model")
    assert (code, payload["error"]["code"]) == (2, "UNSUPPORTED_CAPABILITY")


def test_an_unknown_factor_is_refused_by_the_parser(plain_and_verify):
    study, plain, verify = plain_and_verify
    code, _, err = run_cli("compare", "--study", study, "--control", plain["assessment_id"], "--candidate", verify["assessment_id"], "--factor", "colour", "--json")
    assert code == 2


# --- Inspect logs written offline --------------------------------------------------------------------------------------------------


def test_two_inspect_logs_of_plain_and_verify_compare_with_their_declared_budgets_checked(tmp_path, study):
    from _agent_compare_helpers import assess, observation_set_of
    from _chinook_helpers import episodes_file, import_agent
    from _log_helpers import scripted_log

    sides = {}
    for configuration in ("plain", "verify"):
        log = scripted_log(tmp_path, ("D01", "D03"), repeats=2, name=f"logs-{configuration}", configuration=configuration)
        code, payload, err = import_agent(study, log, episodes_file(tmp_path, keys_of(2, ["D01", "D03"]), name=f"{configuration}-p.json"), configuration)
        assert code == 0, (payload, err)
        sides[configuration] = assess(study, observation_set_of(study, payload["attempt"]))
    code, payload, err = compare(study, sides["plain"], sides["verify"])
    assert code == 0, (payload, err)
    record = payload["comparison"]
    checks = {c["check"]: c for c in record["comparability"]["checks"]}
    assert checks["budgets"] == {"check": "budgets", "passed": True, "reason": None}  # both headers state the same limits
    assert checks["model"]["passed"] is True and checks["tools"]["reason"] == "not_established"
    assert record["comparability"]["status"] == "descriptive_only"
    assert record["descriptive"]["control"]["tool_calls"] == 4 and isinstance(record["descriptive"]["control"]["tokens"], int)  # the log states its tokens (R1-11)
    assert record["coverage"]["expected"] == 4 and record["delta"]["metric"] == PRIMARY


# --- the module's place ------------------------------------------------------------------------------------------------------------


def test_the_agent_comparison_is_a_core_module_that_imports_no_track_and_no_inspect():
    source = (Path(__file__).resolve().parent.parent / "src" / "hypotrail" / "core" / "agent_comparison.py").read_text()
    for forbidden in ("inspect_ai", "hypotrail.agentic", "hypotrail.ml", "sklearn", "numpy"):
        assert f"import {forbidden}" not in source and f"from {forbidden}" not in source, forbidden


def test_two_imports_do_not_claim_a_shared_code_environment(tmp_path, study):
    # R1-13 (#72 Tightened C, ID-03): an Import records the importer's environment, not its producer's.
    _, a = imported(tmp_path, study, "a", answer_lines())
    _, b = imported(tmp_path, study, "b", answer_lines())
    record = compare(study, a, b)[1]["comparison"]
    assert record["code_environment"]["same"] is None and "import_sides" not in record["code_environment"]
    text = " ".join(record["limitations"])
    assert "record the same code environment" not in text and "importer" in text and "not established" in text
