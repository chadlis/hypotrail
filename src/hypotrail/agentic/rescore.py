"""Rescoring a kept log: projection plus the `chinook_contract_v1` Scorer.

The Scorer is given the Episode's projected steps (plain records), so it can check the
evidence link; it never sees an Inspect object.

Neither the model nor any tool is run, and the Chinook file is not opened: the
frozen References are enough. Every expected Episode gets a verdict with a state for every
Criterion and a Reason for every non-score (CMP-03):

- `produced` with an answer: scored by the Scorer;
- `failed` by an execution error: every Criterion `unscored`, Reason `execution_failed`;
- `missing` from the log: every Criterion `unscored`, Reason `observation_missing`;
- `failed` at one of our limits, or by the output cap: see `criteria_for_limit_stop`.

A missing Episode, and one that failed by an execution error, a time limit or the output cap, is never
scored false. Only the agent's own `turn_limit` and `token_limit` are (owner decision D1).
"""

from collections.abc import Callable, Iterable

from hypotrail.agentic.projection import project_log
from hypotrail.core.chinook_contract import CRITERIA, apply_scorer, score_episode
from hypotrail.ml.partitions import require_dev

EXECUTION_FAILED = "execution_failed"
OBSERVATION_MISSING = "observation_missing"


AGENT_RESPONSIBLE = ("turn_limit", "token_limit")
STOPPED_BY_US = AGENT_RESPONSIBLE + ("time_limit", "output_cap")


def _require_dev(partition: str) -> None:
    """Until #9's Exposure journal exists, rescoring is on `dev` (or scenario) Items only, as #7 does for metrics."""
    require_dev(
        partition,
        public_check_code="PUBLIC_CHECK_RESCORING_REFUSED",
        not_dev_code="RESCORING_PARTITION_NOT_DEV",
        what="rescoring",
        stage="rescore",
    )


def _all_unscored(reason: str) -> list[dict]:
    return [{"name": name, "state": "unscored", "score": None, "reason": reason} for name in CRITERIA]


def _scored_false(reason: str) -> list[dict]:
    return [{"name": name, "state": "scored", "score": False, "reason": reason} for name in CRITERIA]


def criteria_for_limit_stop(episode: dict) -> list[dict]:
    """The Criteria of an Episode `failed` at one of our limits, by who is responsible for the stop (owner decision D1).

    - `turn_limit`, `token_limit`: the agent's own failure, every Criterion scored false;
    - `time_limit` (wall time mixes agent and provider latency), `output_cap` (our setting):
      every Criterion `unscored`, an Instrument failure never held against the system.
    The Reason is kept on every Criterion, so a rescoring can revise the choice.
    """
    reason = episode["reason"]
    if reason in AGENT_RESPONSIBLE:
        return _scored_false(reason)
    return _all_unscored(reason)


def _criteria_of_unproduced(episode: dict) -> list[dict]:
    if episode["status"] == "missing":
        return _all_unscored(OBSERVATION_MISSING)
    if episode["reason"] in STOPPED_BY_US:
        return criteria_for_limit_stop(episode)
    return _all_unscored(EXECUTION_FAILED)


def _tool_error_codes(steps: list[dict]) -> list[str]:
    """The structured code of every tool call that failed, in order: counted apart from Criteria."""
    codes = []
    for step in steps:
        if step["kind"] != "tool_result":
            continue
        body = step["result"]
        if step["tool_error"] is not None:
            codes.append(step["tool_error"]["type"])
        elif isinstance(body, dict) and body.get("error") is not None:
            codes.append(body["error"]["code"])
    return codes


def rescore_episodes(
    episodes: list[dict],
    references: dict[str, dict],
    *,
    schema: dict,
    scorer: Callable = score_episode,
    partition: str = "dev",
) -> list[dict]:
    """One verdict per projected Episode, in the order given. Refuses `public_check` Items (owner decision D2)."""
    _require_dev(partition)
    verdicts = []
    for episode in episodes:
        verdict = {
            "case_id": episode["case_id"],
            "repeat": episode["repeat"],
            "status": episode["status"],
            "reason": episode["reason"],
            "tool_error_codes": _tool_error_codes(episode["steps"]),
        }
        if episode["status"] == "produced" and episode["final_answer"] is not None:
            reference = references.get(episode["case_id"])
            verdict.update(apply_scorer(scorer, episode["final_answer"], reference, schema, episode["steps"]))
        else:
            verdict.update({"scorer": None, "criteria": _criteria_of_unproduced(episode)})
        verdicts.append(verdict)
    return verdicts


def rescore_log(
    location: str,
    references: dict[str, dict],
    *,
    schema: dict,
    expected: Iterable[tuple[str, int]],
    scorer: Callable = score_episode,
    partition: str = "dev",
) -> list[dict]:
    """One verdict per expected (case_id, repeat). Refuses `public_check` Items before the log is read.

    `schema` is the Workload's `table-answer/1` schema. A Case without a Reference
    in `references` is not an error: its `exact_table` is left `unscored`.
    """
    _require_dev(partition)
    return rescore_episodes(
        project_log(location, expected=expected), references, schema=schema, scorer=scorer, partition=partition
    )
