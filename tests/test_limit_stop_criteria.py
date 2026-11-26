"""Owner decisions D1 and D2 of #8: Criteria of a limit-stopped Episode (#48 T3', #49 T6') and the refusal of
`public_check` Items by the agentic counting and rescoring entry points (#48 T4').

Seams: `projection.project_log` (status and Reason), `rescore.rescore_episodes` / `rescore_log` (Criteria),
`counts.tally` (counters), `fixture.run_fixture` (the execution). Inspect's mock model only.
"""

import json
import time

import pytest

from _agent_helpers import CHINOOK, MODEL, REFERENCES, WORKLOAD, ScriptedModel, read_jsonl

from hypotrail.agentic import counts, fixture, projection, rescore, runner
from hypotrail.agentic.limits import EpisodeLimits
from hypotrail.core.chinook_contract import CRITERIA
from hypotrail.core.errors import InvalidInputError
from inspect_ai.log import EvalSampleLimit, read_eval_log, write_eval_log
from inspect_ai.model import ModelOutput, ModelUsage

SCHEMA = json.loads((CHINOOK / "schemas" / "table-answer.schema.json").read_text())
REFS = {r["case_id"]: r for r in read_jsonl(REFERENCES)}
CASES = WORKLOAD.cases("dev", ["D03"])
# 1,500 output tokens per generation: the output budget (4,000) is crossed on the third; the large input is no part of it
OVER_BUDGET = ModelUsage(input_tokens=4000, output_tokens=1500, total_tokens=5500)


def run(tmp_path, model, *, limits=None):
    location = runner.run_episodes(
        CASES, workload=WORKLOAD, configuration="plain", model=runner.mock_model(model), repeats=1,
        log_dir=tmp_path, limits=limits,
    )
    return location


def verdict_of(location):
    (verdict,) = rescore.rescore_log(location, REFS, schema=SCHEMA, expected=[("D03", 0)], workload=WORKLOAD)
    return verdict


def states(verdict):
    return {c["name"]: (c["state"], c["score"], c["reason"]) for c in verdict["criteria"]}


def with_usage(model, usage):
    def call(input, tools, tool_choice, config):
        output = model(input, tools, tool_choice, config)
        output.usage = usage
        return output

    return call


def cut_answer(text='{"status": "answered", "colu'):
    """A model whose first reply is a final answer cut by the output cap."""

    def call(input, tools, tool_choice, config):
        output = ModelOutput.from_content(MODEL, text)
        output.choices[0].stop_reason = "max_tokens"
        return output

    return call


# --- T3': turn and token limits are the agent's own failure: every Criterion scored false -----------


def test_a_turn_limit_stop_scores_every_criterion_false_with_the_reason_turn_limit(tmp_path):
    verdict = verdict_of(run(tmp_path, ScriptedModel(CASES, always_call_tool=True)))
    assert (verdict["status"], verdict["reason"]) == ("failed", "turn_limit")
    assert states(verdict) == {name: ("scored", False, "turn_limit") for name in CRITERIA}


def test_a_token_limit_stop_scores_every_criterion_false_with_the_reason_token_limit(tmp_path):
    model = with_usage(ScriptedModel(CASES, always_call_tool=True), OVER_BUDGET)
    verdict = verdict_of(run(tmp_path, model))
    assert (verdict["status"], verdict["reason"]) == ("failed", "token_limit")
    assert states(verdict) == {name: ("scored", False, "token_limit") for name in CRITERIA}


# --- T3': the time limit is not attributable: every Criterion unscored ----------------------------


def test_a_time_limit_stop_leaves_every_criterion_unscored_with_the_reason_time_limit(tmp_path):
    inner = ScriptedModel(CASES)

    def slow(input, tools, tool_choice, config):
        time.sleep(1.5)
        return inner(input, tools, tool_choice, config)

    verdict = verdict_of(run(tmp_path, slow, limits=EpisodeLimits(time_seconds=1)))
    assert (verdict["status"], verdict["reason"]) == ("failed", "time_limit")
    assert states(verdict) == {name: ("unscored", None, "time_limit") for name in CRITERIA}


# --- T3' / #49 T6': an answer cut by the output cap is failed, kept in the trace, unscored -----------


def test_a_final_answer_cut_by_the_output_cap_is_failed_with_output_cap_and_its_text_kept(tmp_path):
    (episode,) = projection.project_log(run(tmp_path, cut_answer()), expected=[("D03", 0)])
    assert (episode["status"], episode["reason"]) == ("failed", "output_cap")
    assert episode["final_answer"] is None
    assert [s["text"] for s in episode["steps"] if s["kind"] == "final_answer"] == ['{"status": "answered", "colu']
    assert episode["steps"][0]["stop_reason"] == "max_tokens"


def test_a_cut_answer_has_every_criterion_unscored_with_output_cap(tmp_path):
    verdict = verdict_of(run(tmp_path, cut_answer()))
    assert states(verdict) == {name: ("unscored", None, "output_cap") for name in CRITERIA}


def test_a_complete_answer_is_still_produced(tmp_path):
    (episode,) = projection.project_log(run(tmp_path, ScriptedModel(CASES)), expected=[("D03", 0)])
    assert episode["status"] == "produced" and episode["reason"] is None


def with_recorded_limit(location, kind="token", limit=4_000):
    """The same kept log, with Inspect's record of a sample limit added to its only sample.

    Inspect drops the generation that crosses a limit, so a final answer and a recorded limit seldom
    meet in a log it writes itself; this makes them meet, in the log API's own format.
    """
    log = read_eval_log(location)
    log.samples[0].limit = EvalSampleLimit(type=kind, limit=limit)
    write_eval_log(log, location)
    return location


@pytest.mark.parametrize("kind", ["token", "time", "message"])
def test_a_cut_final_answer_is_output_cap_whatever_limit_is_recorded(tmp_path, kind):
    # D1: a final answer present in the state and cut by max_tokens is output_cap
    location = with_recorded_limit(run(tmp_path, cut_answer()), kind)
    (episode,) = projection.project_log(location, expected=[("D03", 0)])
    assert (episode["status"], episode["reason"]) == ("failed", "output_cap")
    assert [s["text"] for s in episode["steps"] if s["kind"] == "final_answer"] == ['{"status": "answered", "colu']
    assert states(verdict_of(location)) == {name: ("unscored", None, "output_cap") for name in CRITERIA}


def test_a_recorded_limit_decides_when_there_is_no_final_answer(tmp_path):
    model = with_usage(ScriptedModel(CASES, always_call_tool=True), OVER_BUDGET)
    (episode,) = projection.project_log(run(tmp_path, model), expected=[("D03", 0)])
    assert (episode["status"], episode["reason"]) == ("failed", "token_limit")


def test_the_generation_that_crosses_the_token_budget_leaves_no_final_answer_so_the_limit_decides(tmp_path):
    model = with_usage(cut_answer(), ModelUsage(input_tokens=1_000, output_tokens=4_001, total_tokens=5_001))
    (episode,) = projection.project_log(run(tmp_path, model), expected=[("D03", 0)])
    assert (episode["status"], episode["reason"], episode["final_answer"]) == ("failed", "token_limit", None)


def test_a_complete_final_answer_with_a_recorded_limit_stays_produced(tmp_path):
    location = with_recorded_limit(run(tmp_path, ScriptedModel(CASES)))
    (episode,) = projection.project_log(location, expected=[("D03", 0)])
    assert (episode["status"], episode["reason"]) == ("produced", None)


# --- all of them stay in the denominators, and the interim list is gone ---------------------------


@pytest.mark.parametrize("kind", ["turn", "token", "time", "cap"])
def test_a_limit_stopped_episode_has_a_state_for_every_criterion_and_stays_attempted(tmp_path, kind):
    if kind == "token":
        verdict = verdict_of(run(tmp_path, with_usage(ScriptedModel(CASES, always_call_tool=True), OVER_BUDGET)))
    elif kind == "turn":
        verdict = verdict_of(run(tmp_path, ScriptedModel(CASES, always_call_tool=True)))
    elif kind == "cap":
        verdict = verdict_of(run(tmp_path, cut_answer()))
    else:
        inner = ScriptedModel(CASES)

        def slow(input, tools, tool_choice, config):
            time.sleep(1.5)
            return inner(input, tools, tool_choice, config)

        verdict = verdict_of(run(tmp_path, slow, limits=EpisodeLimits(time_seconds=1)))
    assert [c["name"] for c in verdict["criteria"]] == list(CRITERIA)
    tally = counts.tally([verdict], criteria=CRITERIA, workload=WORKLOAD)
    assert "awaiting_criteria_decision" not in tally
    for name in CRITERIA:
        c = tally["criteria"][name]
        assert (c["N_expected"], c["N_attempted"], c["N_produced"]) == (1, 1, 0)
        assert c["N_scored"] + c["N_unscored"] + c["N_errored"] == 1


def test_an_output_budget_stop_counts_every_criterion_incorrect_and_a_time_stop_leaves_it_unscored(tmp_path):
    # T3: both stay expected and attempted and out of N_produced; the budget stop is scored false, the time stop is not
    token = verdict_of(run(tmp_path / "a", with_usage(ScriptedModel(CASES, always_call_tool=True), OVER_BUDGET)))
    inner = ScriptedModel(CASES)

    def slow(input, tools, tool_choice, config):
        time.sleep(1.5)
        return inner(input, tools, tool_choice, config)

    time_stop = verdict_of(run(tmp_path / "b", slow, limits=EpisodeLimits(time_seconds=1)))
    assert (token["reason"], time_stop["reason"]) == ("token_limit", "time_limit")
    tally = counts.tally([token, time_stop], criteria=CRITERIA, workload=WORKLOAD)["criteria"]
    for name in CRITERIA:
        c = tally[name]
        assert (c["N_expected"], c["N_attempted"], c["N_produced"]) == (2, 2, 0)
        assert (c["N_incorrect"], c["N_unscored"], c["N_correct"]) == (1, 1, 0)


def test_the_counters_tell_a_scored_false_stop_from_an_unscored_one(tmp_path):
    turn = verdict_of(run(tmp_path / "a", ScriptedModel(CASES, always_call_tool=True)))
    cap = verdict_of(run(tmp_path / "b", cut_answer()))
    c = counts.tally([turn, cap], criteria=CRITERIA, workload=WORKLOAD)["criteria"]["exact_table"]
    assert (c["N_incorrect"], c["N_unscored"], c["N_correct"]) == (1, 1, 0)


# --- the scripted execution: the budget-exhausted scenario shows Criteria scored false --------------------


@pytest.fixture(scope="module")
def fixture_execution(tmp_path_factory):
    out = tmp_path_factory.mktemp("d1d2-run")
    return out, fixture.run_fixture(workload_dir=CHINOOK, out_dir=out, configuration="plain")


def test_the_budget_exhausted_scenario_has_every_criterion_scored_false(fixture_execution):
    out, record = fixture_execution
    verdicts = {v["scenario_id"]: v for v in json.loads((out / "verdicts.json").read_text())["verdicts"]}
    assert states(verdicts["budget_exhausted"]) == {name: ("scored", False, "turn_limit") for name in CRITERIA}
    assert "awaiting_criteria_decision" not in record
    for name in CRITERIA:
        assert record["counts"][name]["N_scored"] + record["counts"][name]["N_unscored"] == 7


# --- T4' / D2: the counting and rescoring entry points refuse public_check Items ---------------------
#
# The refusal reads the Partition of each Item from the Workload declaration (R1-P4), never a label the
# caller passes: E01 is a public_check Case, D03 a dev Case, SCN-01 a technical scenario Case.

PUBLIC = "E01"
assert WORKLOAD.partition_of(PUBLIC) == "public_check" and WORKLOAD.partition_of("D03") == "dev"


def refused(call):
    with pytest.raises(InvalidInputError) as caught:
        call()
    return caught.value


def test_rescore_episodes_refuses_a_public_check_item_before_any_computation():
    error = refused(lambda: rescore.rescore_episodes([{"case_id": PUBLIC}], {}, schema=SCHEMA, workload=WORKLOAD))
    assert error.code == "PUBLIC_CHECK_RESCORING_REFUSED"
    assert error.details["partition"] == "public_check" and error.details["case_ids"] == [PUBLIC]


def test_one_public_check_item_among_dev_items_refuses_the_whole_call():
    episodes = [{"case_id": "D03"}, {"case_id": PUBLIC}, {"case_id": "D05"}]
    error = refused(lambda: rescore.rescore_episodes(episodes, {}, schema=SCHEMA, workload=WORKLOAD))
    assert (error.code, error.details["case_ids"]) == ("PUBLIC_CHECK_RESCORING_REFUSED", [PUBLIC])


def test_rescore_log_refuses_a_public_check_item_before_the_log_is_read():
    error = refused(
        lambda: rescore.rescore_log("no/such/log.eval", {}, schema=SCHEMA, expected=[("D03", 0), (PUBLIC, 0)], workload=WORKLOAD)
    )
    assert error.code == "PUBLIC_CHECK_RESCORING_REFUSED"


def test_tally_refuses_a_public_check_verdict_before_any_computation():
    error = refused(lambda: counts.tally([{"case_id": "D03"}, {"case_id": PUBLIC}], criteria=CRITERIA, workload=WORKLOAD))
    assert error.code == "PUBLIC_CHECK_COUNTS_REFUSED"


def test_the_refusal_does_not_depend_on_a_partition_label_because_there_is_none_to_pass():
    import inspect

    for function in (rescore.rescore_episodes, rescore.rescore_log, counts.tally):
        assert "partition" not in inspect.signature(function).parameters, function.__name__


def test_dev_scenario_and_unlisted_items_are_not_refused(tmp_path):
    verdict = verdict_of(run(tmp_path, ScriptedModel(CASES)))
    assert verdict["status"] == "produced"
    for case_id in ("D03", "SCN-01", "NOT-A-CASE"):
        assert counts.tally([{**verdict, "case_id": case_id}], criteria=CRITERIA, workload=WORKLOAD)["criteria"]["exact_table"]["N_expected"] == 1
    assert rescore.rescore_episodes([], {}, schema=SCHEMA, workload=WORKLOAD) == []


def test_a_workload_with_only_a_dev_partition_refuses_nothing_it_does_not_hold(tmp_path):
    verdict = verdict_of(run(tmp_path / "run", ScriptedModel(CASES)))
    import shutil

    from hypotrail.agentic.declaration import load_workload

    target = tmp_path / "chinook"
    shutil.copytree(CHINOOK, target, ignore=shutil.ignore_patterns("data"))
    declaration = json.loads((target / "workload.json").read_text())
    del declaration["cases"]["public_check"]
    (target / "workload.json").write_text(json.dumps(declaration))
    dev_only = load_workload(target)
    assert dev_only.partition_of(PUBLIC) is None
    assert counts.tally([{**verdict, "case_id": PUBLIC}], criteria=CRITERIA, workload=dev_only)["criteria"]["exact_table"]["N_expected"] == 1


def test_scoring_one_answer_against_one_reference_stays_allowed():
    from hypotrail.core.chinook_contract import score_episode

    result = score_episode("not json", REFS["D03"], SCHEMA)
    assert {c["name"] for c in result["criteria"]} >= {"format_valid", "exact_table"}
