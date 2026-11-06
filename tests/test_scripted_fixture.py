"""Ticket #48: the `scripted_fixture` Mode, its scenarios, the Criterion counts and the limit-stopped Episode.

Seams: `projection.project_log` (execution status of an Episode), `rescore.rescore_log` (Criteria of every
expected Episode), `counts.tally` (the counters per Criterion), `fixture.run_fixture` (the run and what it
writes). Inspect's mock model only: no network, no provider key.
"""

import pytest

from _agent_helpers import WORKLOAD, ScriptedModel

from hypotrail.agentic import projection, runner
from hypotrail.agentic.limits import EpisodeLimits


def run_script(tmp_path, script, *, case_ids=("D03",), limits=None):
    cases = WORKLOAD.cases("dev", list(case_ids))
    location = runner.run_episodes(
        cases,
        workload=WORKLOAD,
        configuration="plain",
        model=runner.mock_model(script),
        repeats=1,
        log_dir=tmp_path,
        limits=limits,
    )
    return projection.project_log(location, expected=[(c, 0) for c in case_ids])


# --- an Episode stopped by one of our limits before any final answer is failed ---------------------


def test_a_turn_limit_stop_before_any_final_answer_is_failed_with_a_reason_naming_the_limit(tmp_path):
    (episode,) = run_script(tmp_path, ScriptedModel(WORKLOAD.cases("dev", ["D03"]), always_call_tool=True))
    assert episode["status"] == "failed"
    assert episode["reason"] == "turn_limit"
    assert episode["final_answer"] is None


def test_a_time_limit_stop_before_any_final_answer_is_failed_with_a_reason_naming_the_limit(tmp_path):
    import time

    inner = ScriptedModel(WORKLOAD.cases("dev", ["D03"]))

    def slow(input, tools, tool_choice, config):
        time.sleep(1.5)
        return inner(input, tools, tool_choice, config)

    (episode,) = run_script(tmp_path, slow, limits=EpisodeLimits(time_seconds=1))
    assert episode["status"] == "failed"
    assert episode["reason"] == "time_limit"


# --- every expected Episode has a state for every Criterion, with a Reason for every non-score -----

import json

from _agent_helpers import CHINOOK, REFERENCES, read_jsonl

from hypotrail.agentic import rescore
from hypotrail.core.chinook_contract import CRITERIA

SCHEMA = json.loads((CHINOOK / "schemas" / "table-answer.schema.json").read_text())
REFS = {r["case_id"]: r for r in read_jsonl(REFERENCES)}


def rescored(tmp_path, script, *, case_ids, expected):
    cases = WORKLOAD.cases("dev", list(case_ids))
    location = runner.run_episodes(
        cases, workload=WORKLOAD, configuration="plain", model=runner.mock_model(script), repeats=1, log_dir=tmp_path
    )
    return rescore.rescore_log(location, REFS, schema=SCHEMA, expected=expected)


def states(verdict):
    return {c["name"]: (c["state"], c["score"], c["reason"]) for c in verdict["criteria"]}


def test_an_episode_failed_by_a_model_error_has_every_criterion_unscored_with_execution_failed(tmp_path):
    cases = WORKLOAD.cases("dev", ["D03", "D05"])
    script = ScriptedModel(cases, error_on=("D05", 1))
    d03, d05 = rescored(tmp_path, script, case_ids=["D03", "D05"], expected=[("D03", 0), ("D05", 0)])
    assert d05["status"] == "failed"
    assert states(d05) == {name: ("unscored", None, "execution_failed") for name in CRITERIA}
    assert d03["status"] == "produced"


def test_an_expected_episode_absent_from_the_log_is_missing_with_every_criterion_unscored(tmp_path):
    cases = WORKLOAD.cases("dev", ["D03"])
    (d03, d05) = rescored(
        tmp_path, ScriptedModel(cases), case_ids=["D03"], expected=[("D03", 0), ("D05", 0)]
    )
    assert d05["status"] == "missing"
    assert states(d05) == {name: ("unscored", None, "observation_missing") for name in CRITERIA}


# --- the counters per Criterion -----------------------------------------------------------------

from hypotrail.agentic import counts

COUNTERS = ("N_expected", "N_attempted", "N_produced", "N_scored", "N_correct", "N_incorrect", "N_unscored", "N_errored")


def test_an_episode_absent_from_the_log_is_expected_but_not_attempted(tmp_path):
    cases = WORKLOAD.cases("dev", ["D03", "D05"])
    verdicts = rescored(
        tmp_path, ScriptedModel(cases, error_on=("D05", 1)), case_ids=["D03", "D05"],
        expected=[("D03", 0), ("D05", 0), ("D07", 0)],
    )
    # D03 produced, D05 failed by a model error, D07 absent from the log
    for name in CRITERIA:
        c = counts.tally(verdicts)["criteria"][name]
        assert (c["N_expected"], c["N_attempted"], c["N_produced"]) == (3, 2, 1)
        assert c["N_attempted"] != c["N_expected"]
        # every expected Episode is in exactly one state
        assert c["N_scored"] + c["N_unscored"] + c["N_errored"] == c["N_expected"]
        assert c["N_scored"] == c["N_correct"] + c["N_incorrect"]
        assert (c["N_unscored"], c["N_errored"]) == (2, 0)


def test_a_limit_stopped_episode_stays_in_expected_and_attempted_and_out_of_produced(tmp_path):
    verdicts = rescored(
        tmp_path, ScriptedModel(WORKLOAD.cases("dev", ["D03"]), always_call_tool=True),
        case_ids=["D03"], expected=[("D03", 0)],
    )
    assert verdicts[0]["status"] == "failed"
    for name in CRITERIA:
        c = counts.tally(verdicts)["criteria"][name]
        assert (c["N_expected"], c["N_attempted"], c["N_produced"]) == (1, 1, 0)


# --- the scripted_fixture run: six scenarios (+ one absent), each with its own outcome -------------

from hypotrail.agentic import fixture

BANNER = "simulation, no LLM evaluated"


@pytest.fixture(scope="module")
def fixture_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("fixture-run")
    record = fixture.run_fixture(workload_dir=CHINOOK, out_dir=out)
    return out, record


def verdicts_by_scenario(out):
    document = json.loads((out / "verdicts.json").read_text())
    return {v["scenario_id"]: v for v in document["verdicts"]}


def criteria_of(verdict):
    return {c["name"]: (c["state"], c["score"], c["reason"]) for c in verdict["criteria"]}


def test_a_good_result_is_produced_with_every_criterion_scored_true(fixture_run):
    verdict = verdicts_by_scenario(fixture_run[0])["good_result"]
    assert verdict["status"] == "produced"
    assert criteria_of(verdict) == {name: ("scored", True, None) for name in CRITERIA}


def test_a_wrong_result_is_produced_with_exact_table_and_contract_success_false(fixture_run):
    criteria = criteria_of(verdicts_by_scenario(fixture_run[0])["wrong_result"])
    assert verdicts_by_scenario(fixture_run[0])["wrong_result"]["status"] == "produced"
    assert criteria["exact_table"][:2] == ("scored", False)
    assert criteria["contract_success"][:2] == ("scored", False)
    assert criteria["format_valid"] == ("scored", True, None)


def test_an_invalid_format_answer_fails_format_valid_with_its_reason_and_keeps_the_raw_answer(fixture_run):
    verdict = verdicts_by_scenario(fixture_run[0])["invalid_format"]
    assert verdict["status"] == "produced"
    assert criteria_of(verdict)["format_valid"] == ("scored", False, "invalid_response_format")
    assert verdict["raw_answer"] == "There are 25 genres in the catalogue."


def test_a_recovered_tool_error_is_scored_as_usual_and_its_code_is_counted_apart(fixture_run):
    out, record = fixture_run
    verdict = verdicts_by_scenario(out)["recovered_tool_error"]
    assert verdict["status"] == "produced"
    assert criteria_of(verdict) == {name: ("scored", True, None) for name in CRITERIA}
    assert verdict["tool_error_codes"] == ["SQL_ERROR"]
    episodes = json.loads((out / "projection.json").read_text())["episodes"]
    trace = next(e for e in episodes if e["case_id"] == verdict["case_id"])["steps"]
    assert [s["result"]["error"]["code"] for s in trace if s["kind"] == "tool_result" and s["result"]["error"]] == [
        "SQL_ERROR"
    ]
    assert record["tool_errors"] == {"total": 1, "by_code": {"SQL_ERROR": 1}}


def test_a_missing_reference_leaves_the_criteria_that_need_it_unscored_not_false(fixture_run):
    criteria = criteria_of(verdicts_by_scenario(fixture_run[0])["missing_reference"])
    assert criteria["exact_table"] == ("unscored", None, "reference_missing")
    assert criteria["contract_success"] == ("unscored", None, "reference_missing")
    assert criteria["format_valid"] == ("scored", True, None)
    assert criteria["evidence_link_valid"] == ("scored", True, None)


def test_a_budget_exhausted_episode_is_failed_with_the_limit_named_and_no_answer(fixture_run):
    verdict = verdicts_by_scenario(fixture_run[0])["budget_exhausted"]
    assert verdict["status"] == "failed"
    assert verdict["reason"] == "turn_limit"
    assert verdict.get("raw_answer") is None


# --- real tools, shared code ----------------------------------------------------------------------

import hashlib
import sqlite3

from _agent_helpers import DATABASE


def episodes_of(out):
    return json.loads((out / "projection.json").read_text())["episodes"]


def test_each_scenario_calls_the_real_tools_and_every_tool_result_equals_the_same_sql_run_directly(fixture_run):
    out, _ = fixture_run
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    checked = 0
    for episode in episodes_of(out):
        calls = {s["native_tool_call_id"]: s for s in episode["steps"] if s["kind"] == "tool_call"}
        for step in (s for s in episode["steps"] if s["kind"] == "tool_result"):
            sql = calls[step["native_tool_call_id"]]["arguments"]["sql"]
            try:
                cursor = connection.execute(sql)
            except sqlite3.Error:
                assert step["result"]["error"]["code"] == "SQL_ERROR"
                continue
            assert step["result"]["columns"] == [d[0] for d in cursor.description]
            assert step["result"]["rows"] == [list(row) for row in cursor.fetchall()]
            checked += 1
    assert checked >= 6
    # every scenario that is run made at least one real call
    assert all(any(s["kind"] == "tool_call" for s in e["steps"]) for e in episodes_of(out) if e["status"] != "missing")


def test_the_verdicts_are_those_a_rescoring_of_the_kept_log_gives(fixture_run):
    out, record = fixture_run
    written = json.loads((out / "verdicts.json").read_text())["verdicts"]
    scenarios = fixture.load_scenarios(WORKLOAD)
    references = {s["case"]["case_id"]: s["reference"] for s in scenarios if "reference" in s}
    again = rescore.rescore_log(
        str(out / record["inspect_log"]), references, schema=SCHEMA,
        expected=[(s["case"]["case_id"], 0) for s in scenarios],
    )
    assert [{k: v for k, v in w.items() if k != "scenario_id"} for w in written] == again


# --- counts ---------------------------------------------------------------------------------------


def test_at_least_six_scenarios_run_and_a_seventh_is_absent_from_the_log(fixture_run):
    _, record = fixture_run
    statuses = {s["scenario_id"]: s["status"] for s in record["scenarios"]}
    assert statuses == {
        "good_result": "produced", "wrong_result": "produced", "invalid_format": "produced",
        "recovered_tool_error": "produced", "budget_exhausted": "failed", "missing_reference": "produced",
        "absent_from_log": "missing",
    }


def test_each_criterion_has_distinct_denominators_and_every_scenario_moves_a_different_combination(fixture_run):
    out, record = fixture_run
    for name in CRITERIA:
        c = record["counts"][name]
        assert set(c) == set(COUNTERS)
        assert (c["N_expected"], c["N_attempted"], c["N_produced"]) == (7, 6, 5)
        assert c["N_attempted"] != c["N_expected"]
        assert c["N_scored"] == c["N_correct"] + c["N_incorrect"]
    # the scenarios that produced an answer, each seen through the counters it moves
    def moves(scenario):
        v = verdicts_by_scenario(out)[scenario]
        return tuple((c["state"], c["score"]) for c in v["criteria"])

    produced = ["good_result", "wrong_result", "invalid_format", "recovered_tool_error", "missing_reference"]
    combos = {s: moves(s) for s in produced}
    # recovered_tool_error is scored like the good result; its difference is the tool error count
    assert combos["recovered_tool_error"] == combos["good_result"]
    others = [s for s in produced if s != "recovered_tool_error"]
    assert len({combos[s] for s in others}) == len(others)
    # the counters over every scenario: budget_exhausted (turn limit) is scored false on every Criterion
    settled = json.loads((out / "verdicts.json").read_text())["verdicts"]
    t = counts.tally(settled)
    exact = t["criteria"]["exact_table"]
    # good_result and recovered_tool_error correct; wrong_result and invalid_format incorrect;
    # missing_reference (reference_missing) and absent_from_log (observation_missing) unscored
    assert (exact["N_correct"], exact["N_incorrect"], exact["N_unscored"], exact["N_errored"]) == (2, 3, 2, 0)  # + budget_exhausted: scored false
    assert t["criteria"]["format_valid"]["N_incorrect"] == 2
    assert t["criteria"]["format_valid"]["N_correct"] == 4
    # invalid_format is scored false (invalid_response_format); only absent_from_log is unscored
    link = t["criteria"]["evidence_link_valid"]
    assert (link["N_incorrect"], link["N_unscored"]) == (2, 1)  # + budget_exhausted: scored false


# --- Mode, banner, model, business Cases ------------------------------------------------------------

from inspect_ai.log import read_eval_log


def test_every_artifact_names_the_mode_and_carries_the_banner(fixture_run):
    out, record = fixture_run
    assert (record["mode"], record["banner"]) == ("scripted_fixture", BANNER)
    for name in ("run.json", "projection.json", "verdicts.json"):
        document = json.loads((out / name).read_text())
        assert (document["mode"], document["banner"]) == ("scripted_fixture", BANNER), name
    # the Inspect log header carries them too
    header = read_eval_log(str(out / record["inspect_log"]), header_only=True)
    assert (header.eval.metadata["mode"], header.eval.metadata["banner"]) == ("scripted_fixture", BANNER)
    # nothing else was written outside the Inspect log
    assert {p.name for p in out.iterdir()} == {"run.json", "projection.json", "verdicts.json", "inspect"}


def test_the_recorded_model_is_inspects_mock_model_and_no_record_names_a_provider_model(fixture_run):
    out, record = fixture_run
    assert (record["model"], record["provider"]) == ("mockllm/model", "mockllm")
    assert {e["model"] for e in episodes_of(out)} == {"mockllm/model"}
    text = "".join((out / n).read_text().lower() for n in ("run.json", "projection.json", "verdicts.json"))
    for provider in ("anthropic", "openai", "claude", "gpt-", "gemini"):
        assert provider not in text, provider


def test_the_scenario_episodes_are_never_outputs_of_the_twenty_business_cases(fixture_run):
    out, record = fixture_run
    business = {c["case_id"] for partition in ("dev", "public_check") for c in WORKLOAD.cases(partition)}
    assert len(business) == 20
    run_ids = {e["case_id"] for e in episodes_of(out)}
    assert run_ids and run_ids.isdisjoint(business)
    assert record["business_case_outputs"] == 0
    assert set(counts_case_ids(record)).isdisjoint(business)


def counts_case_ids(record):
    return [s["case_id"] for s in record["scenarios"]]


# --- limits, hash, offline ------------------------------------------------------------------------------


def test_the_run_records_the_effective_limits_the_unenforceable_tool_call_limit_and_the_seven_calls(fixture_run):
    _, record = fixture_run
    effective = record["effective_limits"]
    assert effective["model_turns"] == 6 and effective["time_seconds"] == 60
    assert effective["query_caps"] == {"time_seconds": 1.0, "max_instructions": 100_000_000, "max_rows": 200, "max_bytes": 65536}
    assert effective["tool_calls"] is None
    assert "no limit on the number of tool calls" in record["limits_not_enforceable"]["tool_calls"]
    assert record["provider_calls_allowed"]["provider_calls"] == 7
    assert "6-turn limit allows 7 provider calls" in record["provider_calls_allowed"]["note"]


def test_the_run_records_the_chinook_hash_before_and_after_and_they_are_equal(fixture_run):
    _, record = fixture_run
    expected = hashlib.sha256(DATABASE.read_bytes()).hexdigest()
    assert record["database"]["sha256_before"] == record["database"]["sha256_after"] == expected
    assert record["database"]["unchanged"] is True


def test_the_scenario_scripts_are_data_and_the_workload_holds_no_python():
    path = WORKLOAD.scenarios_path
    assert path.suffix == ".json" and isinstance(json.loads(path.read_text()), dict)
    assert not [p for p in CHINOOK.rglob("*.py")]
