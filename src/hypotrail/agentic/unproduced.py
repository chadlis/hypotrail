"""The Criteria of an Episode that produced no answer: `failed` or `missing`.

Shared by the rescoring of a kept Inspect log (`rescore`) and by `assess` of an imported Observation
set, so one rule decides both. It imports neither Inspect nor the log projection.
"""

from hypotrail.core.chinook_contract import CRITERIA

EXECUTION_FAILED = "execution_failed"
OBSERVATION_MISSING = "observation_missing"


AGENT_RESPONSIBLE = ("turn_limit", "token_limit", "cost_limit")
STOPPED_BY_US = AGENT_RESPONSIBLE + ("time_limit", "output_cap")


def all_unscored(reason: str) -> list[dict]:
    return [{"name": name, "state": "unscored", "score": None, "reason": reason} for name in CRITERIA]


def scored_false(reason: str) -> list[dict]:
    return [{"name": name, "state": "scored", "score": False, "reason": reason} for name in CRITERIA]


def criteria_for_limit_stop(episode: dict) -> list[dict]:
    """The Criteria of an Episode `failed` at one of our limits, by who is responsible for the stop (owner decision D1).

    - `turn_limit`, `token_limit`, `cost_limit`: the agent's own failure, every Criterion scored false. Of `cost_limit`,
      D-146 on chadlis/hypotrail#75: "It joins `AGENT_RESPONSIBLE` in `unproduced.py:13`: every Criterion scored false,
      reason kept.";
    - `time_limit` (wall time mixes agent and provider latency), `output_cap` (our setting):
      every Criterion `unscored`, an Instrument failure never held against the system.
    The Reason is kept on every Criterion, so a rescoring can revise the choice.
    """
    reason = episode["reason"]
    if reason in AGENT_RESPONSIBLE:
        return scored_false(reason)
    return all_unscored(reason)


def criteria_of_unproduced(episode: dict) -> list[dict]:
    if episode["status"] == "missing":
        return all_unscored(OBSERVATION_MISSING)
    if episode["reason"] in STOPPED_BY_US:
        return criteria_for_limit_stop(episode)
    return all_unscored(EXECUTION_FAILED)
