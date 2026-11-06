"""Owner decisions D1 and D2 of #8: Criteria of a limit-stopped Episode (#48 T3', #49 T6') and the refusal of
`public_check` Items by the agentic counting and rescoring entry points (#48 T4').

Seams: `projection.project_log` (status and Reason), `rescore.rescore_episodes` / `rescore_log` (Criteria),
`counts.tally` (counters), `fixture.run_fixture` (the run). Inspect's mock model only.
"""

import json
import time

import pytest

from _agent_helpers import CHINOOK, MODEL, REFERENCES, WORKLOAD, ScriptedModel, read_jsonl

from hypotrail.agentic import counts, fixture, projection, rescore, runner
from hypotrail.agentic.limits import EpisodeLimits
from hypotrail.core.chinook_contract import CRITERIA
from hypotrail.core.errors import InvalidInputError
from inspect_ai.model import ModelOutput, ModelUsage

SCHEMA = json.loads((CHINOOK / "schemas" / "table-answer.schema.json").read_text())
REFS = {r["case_id"]: r for r in read_jsonl(REFERENCES)}
CASES = WORKLOAD.cases("dev", ["D03"])


def run(tmp_path, model, *, limits=None):
    location = runner.run_episodes(
        CASES, workload=WORKLOAD, configuration="plain", model=runner.mock_model(model), repeats=1,
        log_dir=tmp_path, limits=limits,
    )
    return location


def verdict_of(location):
    (verdict,) = rescore.rescore_log(location, REFS, schema=SCHEMA, expected=[("D03", 0)])
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
    model = with_usage(ScriptedModel(CASES, always_call_tool=True), ModelUsage(input_tokens=4000, output_tokens=1000, total_tokens=5000))
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


def test_a_sample_limit_decides_over_the_output_cap_when_both_apply(tmp_path):
    # the final call is cut at max_tokens and its usage also exhausts the token budget
    model = with_usage(cut_answer(), ModelUsage(input_tokens=11_000, output_tokens=1_024, total_tokens=12_024))
    location = run(tmp_path, model)
    (episode,) = projection.project_log(location, expected=[("D03", 0)])
    assert (episode["status"], episode["reason"]) == ("failed", "token_limit")
    assert states(verdict_of(location)) == {name: ("scored", False, "token_limit") for name in CRITERIA}


# --- all of them stay in the denominators, and the interim list is gone ---------------------------


@pytest.mark.parametrize("kind", ["turn", "time", "cap"])
def test_a_limit_stopped_episode_has_a_state_for_every_criterion_and_stays_attempted(tmp_path, kind):
    if kind == "turn":
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
    tally = counts.tally([verdict])
    assert "awaiting_criteria_decision" not in tally
    for name in CRITERIA:
        c = tally["criteria"][name]
        assert (c["N_expected"], c["N_attempted"], c["N_produced"]) == (1, 1, 0)
        assert c["N_scored"] + c["N_unscored"] + c["N_errored"] == 1


def test_the_counters_tell_a_scored_false_stop_from_an_unscored_one(tmp_path):
    turn = verdict_of(run(tmp_path / "a", ScriptedModel(CASES, always_call_tool=True)))
    cap = verdict_of(run(tmp_path / "b", cut_answer()))
    c = counts.tally([turn, cap])["criteria"]["exact_table"]
    assert (c["N_incorrect"], c["N_unscored"], c["N_correct"]) == (1, 1, 0)


# --- the scripted run: the budget-exhausted scenario shows Criteria scored false --------------------


@pytest.fixture(scope="module")
def fixture_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("d1d2-run")
    return out, fixture.run_fixture(workload_dir=CHINOOK, out_dir=out)


def test_the_budget_exhausted_scenario_has_every_criterion_scored_false(fixture_run):
    out, record = fixture_run
    verdicts = {v["scenario_id"]: v for v in json.loads((out / "verdicts.json").read_text())["verdicts"]}
    assert states(verdicts["budget_exhausted"]) == {name: ("scored", False, "turn_limit") for name in CRITERIA}
    assert "awaiting_criteria_decision" not in record
    for name in CRITERIA:
        assert record["counts"][name]["N_scored"] + record["counts"][name]["N_unscored"] == 7


# --- T4' / D2: the counting and rescoring entry points refuse public_check Items ---------------------


def test_rescore_episodes_refuses_public_check_before_any_computation():
    with pytest.raises(InvalidInputError) as caught:
        rescore.rescore_episodes([{"not": "even looked at"}], {}, schema=SCHEMA, partition="public_check")
    assert caught.value.code == "PUBLIC_CHECK_RESCORING_REFUSED"


def test_rescore_log_refuses_public_check_before_the_log_is_read():
    with pytest.raises(InvalidInputError) as caught:
        rescore.rescore_log("no/such/log.eval", {}, schema=SCHEMA, expected=[("D03", 0)], partition="public_check")
    assert caught.value.code == "PUBLIC_CHECK_RESCORING_REFUSED"


def test_tally_refuses_public_check_before_any_computation():
    with pytest.raises(InvalidInputError) as caught:
        counts.tally([{"not": "even looked at"}], partition="public_check")
    assert caught.value.code == "PUBLIC_CHECK_COUNTS_REFUSED"


def test_another_partition_is_refused_with_its_own_code():
    with pytest.raises(InvalidInputError) as caught:
        counts.tally([], partition="train")
    assert caught.value.code == "COUNTS_PARTITION_NOT_DEV"


def test_dev_and_scenario_runs_are_unaffected(tmp_path):
    verdict = verdict_of(run(tmp_path, ScriptedModel(CASES)))
    assert verdict["status"] == "produced"
    assert counts.tally([verdict], partition="dev")["criteria"]["exact_table"]["N_expected"] == 1


def test_scoring_one_answer_against_one_reference_stays_allowed():
    from hypotrail.core.chinook_contract import score_episode

    result = score_episode("not json", REFS["D03"], SCHEMA)
    assert {c["name"] for c in result["criteria"]} >= {"format_valid", "exact_table"}
