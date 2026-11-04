"""Ticket #19 (spike check 3): Episode limits, enforced by Inspect or named as not enforceable.

Unit of the turn limit: Inspect counts model generations. It checks after a
generation completes, so the generation that exceeds the limit is still made
(one provider call more than the limit) but is not kept in the transcript.
"""

import inspect
import time
from pathlib import Path

import anyio
import pytest
from inspect_ai import eval as inspect_eval
from inspect_ai.model import CachePolicy, ModelAPI, ModelOutput, ModelUsage, modelapi
from tenacity import wait_none

from _agent_helpers import CASES, DATABASE, MODEL, ScriptedModel

from hypotrail.agentic import cases as case_module
from hypotrail.agentic import limits as limits_module
from hypotrail.agentic import projection, runner
from hypotrail.agentic.limits import ENFORCEMENT, NOT_ENFORCEABLE, EpisodeLimits, read_back

D03 = ["D03"]


def cases(ids=D03):
    return case_module.load_cases(CASES, ids)


def run(tmp_path, script, *, ids=D03, repeats=1, limits=None, model=None, **overrides):
    location = runner.run_episodes(
        cases(ids),
        database=DATABASE,
        model=model or runner.mock_model(script),
        repeats=repeats,
        log_dir=tmp_path / "logs",
        limits=limits,
        **overrides,
    )
    expected = [(c, r) for c in ids for r in range(repeats)]
    return location, projection.project_log(location, expected=expected)


def kinds(episode):
    return [s["kind"] for s in episode["steps"]]


# --- turns and tool calls ------------------------------------------------------------


def test_the_turn_limit_stops_the_episode_at_the_configured_count(tmp_path):
    script = ScriptedModel(cases(), always_call_tool=True)
    _, (episode,) = run(tmp_path, script)

    assert episode["stopped_by_limit"] == {"type": "turn", "limit": 6.0}
    assert episode["final_answer"] is None
    # exactly 6 model turns kept, each with one executed tool call
    assert kinds(episode).count("model_turn") == 6
    assert kinds(episode).count("tool_call") == 6
    assert kinds(episode).count("tool_result") == 6
    assert "final_answer" not in kinds(episode)
    # finding: the 7th generation is still made, then discarded
    assert len(script.calls) == 7


def test_inspect_has_no_tool_call_limit():
    from inspect_ai import Task

    names = list(inspect.signature(inspect_eval).parameters) + list(inspect.signature(Task).parameters)
    assert not [n for n in names if "tool_call" in n or "max_tool" in n]
    assert "tool_calls" in NOT_ENFORCEABLE
    assert ENFORCEMENT["tool_calls"][0] == "not enforceable"


# --- time and tokens -------------------------------------------------------------------


def test_the_time_limit_stops_a_slow_episode(tmp_path):
    async def slow(input, tools, tool_choice, config):
        await anyio.sleep(5)
        return ModelOutput.from_content(MODEL, "never reached")

    started = time.monotonic()
    _, (episode,) = run(tmp_path, slow, limits=EpisodeLimits(time_seconds=1))

    assert time.monotonic() - started < 4
    assert episode["stopped_by_limit"] == {"type": "time", "limit": 1.0}
    assert episode["final_answer"] is None


def test_the_token_limit_stops_the_episode(tmp_path):
    script = ScriptedModel(cases(), always_call_tool=True)
    inner = script.__call__

    def with_usage(input, tools, tool_choice, config):
        output = inner(input, tools, tool_choice, config)
        output.usage = ModelUsage(input_tokens=4000, output_tokens=1000, total_tokens=5000)
        return output

    _, (episode,) = run(tmp_path, with_usage)

    assert episode["stopped_by_limit"] == {"type": "token", "limit": 12000.0}
    assert episode["final_answer"] is None
    assert kinds(episode).count("model_turn") < 6


# --- per-call output cap ------------------------------------------------------------------


def test_the_output_token_cap_reaches_every_model_call(tmp_path):
    seen = []
    script = ScriptedModel(cases())

    def spy(input, tools, tool_choice, config):
        seen.append(config.max_tokens)
        return script(input, tools, tool_choice, config)

    run(tmp_path, spy)
    assert seen == [1024, 1024]


# --- concurrency -------------------------------------------------------------------------------


def _concurrency_probe():
    state = {"now": 0, "max": 0}
    script = ScriptedModel(cases(["D03", "D05"]))

    async def probe(input, tools, tool_choice, config):
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        await anyio.sleep(0.05)
        state["now"] -= 1
        return script(input, tools, tool_choice, config)

    return state, probe


def test_one_episode_runs_at_a_time(tmp_path):
    state, probe = _concurrency_probe()
    run(tmp_path, probe, ids=["D03", "D05"], repeats=2)
    assert state["max"] == 1


def test_the_concurrency_probe_would_see_parallel_episodes(tmp_path):
    state, probe = _concurrency_probe()
    run(tmp_path, probe, ids=["D03", "D05"], repeats=2, limits=EpisodeLimits(concurrency=4))
    assert state["max"] > 1


# --- response cache ------------------------------------------------------------------------------


def test_the_response_cache_is_off(tmp_path, monkeypatch):
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path / "cache"))
    script = ScriptedModel(cases())
    run(tmp_path, script, repeats=2)
    first_generates = [c for c in script.calls if c[-1][0] == "user"]
    assert len(first_generates) == 2  # two identical requests both reached the model


def test_the_cache_probe_would_see_a_cache_hit(tmp_path, monkeypatch):
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path / "cache"))
    script = ScriptedModel(cases())
    # the same request in both repeats: the policy must not key the cache by epoch
    run(tmp_path, script, repeats=2, cache=CachePolicy(per_epoch=False))
    first_generates = [c for c in script.calls if c[-1][0] == "user"]
    assert len(first_generates) == 1  # the second identical request was served from the cache


# --- retries ------------------------------------------------------------------------------------------


def test_an_errored_episode_is_not_retried(tmp_path):
    script = ScriptedModel(cases(), error_on=("D03", 1))
    _, (episode,) = run(tmp_path, script)
    assert episode["status"] == "failed"
    assert len([c for c in script.calls if c[-1][0] == "user"]) == 1


def test_the_retry_probe_would_see_a_retried_episode(tmp_path):
    script = ScriptedModel(cases(), error_on=("D03", 1))
    _, (episode,) = run(tmp_path, script, limits=EpisodeLimits(sample_retries=1))
    assert episode["status"] == "produced"
    assert len([c for c in script.calls if c[-1][0] == "user"]) == 2


class Transient(Exception):
    pass


@modelapi(name="hypotrail_flaky")
class FlakyProvider(ModelAPI):
    """Test-only provider: fails once with a retryable error, then answers."""

    calls = 0

    def __init__(self, model_name, base_url=None, api_key=None, config=None, **model_args):
        super().__init__(model_name, base_url, api_key, [], config)

    async def generate(self, input, tools, tool_choice, config):
        FlakyProvider.calls += 1
        if FlakyProvider.calls == 1:
            raise Transient("try again")
        return ModelOutput.from_content("hypotrail_flaky/model", "done")

    def should_retry(self, ex):
        return isinstance(ex, Transient)

    def retry_wait(self):
        return wait_none()


def _flaky(tmp_path, limits):
    from inspect_ai.model import get_model

    FlakyProvider.calls = 0
    _, (episode,) = run(tmp_path, None, limits=limits, model=get_model("hypotrail_flaky/model"))
    return episode, FlakyProvider.calls


def test_a_transient_model_error_is_not_retried(tmp_path):
    episode, calls = _flaky(tmp_path, EpisodeLimits())
    assert calls == 1
    assert episode["status"] == "failed"


def test_the_transport_retry_probe_would_see_a_retry(tmp_path):
    episode, calls = _flaky(tmp_path, EpisodeLimits(transport_retries=1))
    assert calls == 2
    assert episode["status"] == "produced"


# --- read back -------------------------------------------------------------------------------------------


def test_every_limit_is_read_back_from_the_log(tmp_path):
    script = ScriptedModel(cases())
    location, _ = run(tmp_path, script)
    effective = read_back(location)
    assert effective == {
        "model_turns": 6,
        "tool_calls": None,
        "time_seconds": 60,
        "total_tokens": 12000,
        "max_output_tokens": 1024,
        "concurrency": 1,
        "max_connections": 1,
        "response_cache": False,
        "sample_retries": 0,
        "transport_retries": 0,
    }


def test_every_limit_has_a_label_and_a_witness_that_exists():
    assert set(ENFORCEMENT) == set(EpisodeLimits().as_dict())
    source = Path(__file__).read_text()
    for limit, (label, witness) in ENFORCEMENT.items():
        assert label in {"shown enforced", "configured, not witnessed", "not enforceable"}, limit
        assert f"def {witness}(" in source, witness


def test_the_limit_values_are_the_ag_11_proposals():
    assert EpisodeLimits().as_dict() == {
        "model_turns": 6,
        "tool_calls": 8,
        "time_seconds": 60,
        "total_tokens": 12000,
        "max_output_tokens": 1024,
        "concurrency": 1,
        "response_cache": False,
        "sample_retries": 0,
        "transport_retries": 0,
    }
    assert limits_module.eval_options(EpisodeLimits())["turn_limit"] == 6
