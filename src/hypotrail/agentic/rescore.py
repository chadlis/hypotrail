"""Rescoring a kept log: projection plus the `chinook_contract_v1` Scorer.

The Scorer is given the Episode's projected steps (plain records), so it can check the
evidence link; it never sees an Inspect object.

Neither the model nor any tool is run, and the Chinook file is not opened: the
frozen References are enough. Every expected Episode gets a verdict with a state for every
Criterion and a Reason for every non-score (CMP-03):

- `produced` with an answer: scored by the Scorer;
- `failed` by an execution error: every Criterion `unscored`, Reason `execution_failed`;
- `missing` from the log: every Criterion `unscored`, Reason `observation_missing`;
- `failed` at one of our limits before any final answer: see `criteria_for_limit_stop`.

Neither a failed nor a missing Episode is ever scored false.
"""

from collections.abc import Callable, Iterable

from hypotrail.agentic.projection import project_log
from hypotrail.core.chinook_contract import CRITERIA, apply_scorer, score_episode

EXECUTION_FAILED = "execution_failed"
OBSERVATION_MISSING = "observation_missing"


def _all_unscored(reason: str) -> list[dict]:
    return [{"name": name, "state": "unscored", "score": None, "reason": reason} for name in CRITERIA]


def criteria_for_limit_stop(episode: dict) -> list[dict] | None:
    """The Criteria of an Episode stopped by one of our limits (turns, time, tokens) before a final answer.

    PENDING OWNER DECISION D1 (chadlis/hypotrail#48, Tightened T3). Until the owner decides what
    state these Criteria take, and whether an answer cut by the output cap is `failed` or
    `produced`, this returns None: "not decided", neither a state nor an empty list. The Episode
    itself is settled and does not wait: it is `failed`, its Reason names the limit, and it stays
    in N_expected and N_attempted. D1 plugs in here, and only here.
    """
    return None


def _criteria_of_unproduced(episode: dict) -> list[dict] | None:
    if episode["status"] == "missing":
        return _all_unscored(OBSERVATION_MISSING)
    if episode["stopped_by_limit"] is not None:
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
) -> list[dict]:
    """One verdict per projected Episode, in the order given."""
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
) -> list[dict]:
    """One verdict per expected (case_id, repeat).

    `schema` is the Workload's `table-answer/1` schema. A Case without a Reference
    in `references` is not an error: its `exact_table` is left `unscored`.
    """
    return rescore_episodes(project_log(location, expected=expected), references, schema=schema, scorer=scorer)
