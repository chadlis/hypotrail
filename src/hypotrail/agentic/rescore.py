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
from hypotrail.agentic.partitions import refuse_public_check
from hypotrail.agentic.unproduced import (  # noqa: F401  (re-exported: the names the callers and the tests know)
    AGENT_RESPONSIBLE,
    EXECUTION_FAILED,
    OBSERVATION_MISSING,
    STOPPED_BY_US,
    all_unscored,
    criteria_of_unproduced,
    criteria_for_limit_stop,
)

def _refuse_public_check(workload, case_ids) -> None:
    """Rescoring through these library functions takes no Study, so it refuses `public_check` Items (owner decision D2); `assess` does it inside a Study."""
    refuse_public_check(workload, case_ids, code="PUBLIC_CHECK_RESCORING_REFUSED", what="rescoring", stage="rescore")


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
    workload,
    scorer: Callable = score_episode,
) -> list[dict]:
    """One verdict per projected Episode, in the order given.

    Refuses `public_check` Items (owner decision D2), by the Partition the Workload declares for each Case.
    """
    _refuse_public_check(workload, [episode["case_id"] for episode in episodes])
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
            verdict.update({"scorer": None, "criteria": criteria_of_unproduced(episode)})
        verdicts.append(verdict)
    return verdicts


def rescore_log(
    location: str,
    references: dict[str, dict],
    *,
    schema: dict,
    expected: Iterable[tuple[str, int]],
    workload,
    scorer: Callable = score_episode,
) -> list[dict]:
    """One verdict per expected (case_id, repeat). Refuses `public_check` Items before the log is read.

    `schema` is the Workload's `table-answer/1` schema. A Case without a Reference
    in `references` is not an error: its `exact_table` is left `unscored`.
    """
    expected = list(expected)
    _refuse_public_check(workload, [case_id for case_id, _ in expected])
    return rescore_episodes(
        project_log(location, expected=expected), references, schema=schema, workload=workload, scorer=scorer
    )
