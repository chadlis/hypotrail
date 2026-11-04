"""Rescoring a kept log: projection plus the core scoring function.

Neither the model nor any tool is run, and the Chinook file is not opened: the
frozen References are enough.
"""

from collections.abc import Iterable

from hypotrail.agentic.projection import project_log
from hypotrail.core.answer_scoring import score_answer


def rescore_log(location: str, references: dict[str, dict], *, expected: Iterable[tuple[str, int]]) -> list[dict]:
    """One verdict per expected (case_id, repeat); only produced Episodes are scored."""
    verdicts = []
    for episode in project_log(location, expected=expected):
        verdict = {"case_id": episode["case_id"], "repeat": episode["repeat"]}
        if episode["status"] == "produced" and episode["final_answer"] is not None:
            verdict.update(score_answer(episode["final_answer"], references[episode["case_id"]]))
        else:
            verdict.update({"parsed": None, "correct": None, "components": None})
        verdicts.append(verdict)
    return verdicts
