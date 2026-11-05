"""Rescoring a kept log: projection plus the `chinook_contract_v1` Scorer.

The Scorer is given the Episode's projected steps (plain records), so it can check the
evidence link; it never sees an Inspect object.

Neither the model nor any tool is run, and the Chinook file is not opened: the
frozen References are enough. Only Episodes the log shows as `produced` with an
answer are scored here; how a `failed` or `missing` Episode is scored is not decided
(ticket #48), so such an Episode carries `criteria: None`.
"""

from collections.abc import Callable, Iterable

from hypotrail.agentic.projection import project_log
from hypotrail.core.chinook_contract import apply_scorer, score_episode


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
    verdicts = []
    for episode in project_log(location, expected=expected):
        verdict = {
            "case_id": episode["case_id"],
            "repeat": episode["repeat"],
            "status": episode["status"],
        }
        if episode["status"] == "produced" and episode["final_answer"] is not None:
            reference = references.get(episode["case_id"])
            verdict.update(apply_scorer(scorer, episode["final_answer"], reference, schema, episode["steps"]))
        else:
            verdict.update({"scorer": None, "criteria": None})
        verdicts.append(verdict)
    return verdicts
