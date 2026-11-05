"""The counters per Criterion, over the verdicts of one scripted or live run (CMP-03).

For each Criterion: N_expected (every expected Episode), N_attempted (all but those `missing`
from the log), N_produced (those with an answer), then N_scored, N_correct, N_incorrect,
N_unscored and N_errored over the Criterion states, with N_scored = N_correct + N_incorrect.
Tool errors are counted apart, by structured code, never as Criterion states.

An Episode whose Criteria are not decided yet (`criteria` is None, see
`rescore.criteria_for_limit_stop`) is counted in N_expected and N_attempted like any other, and
is listed in `awaiting_criteria_decision`, so it cannot drop silently out of a denominator.
The shares of CMP-04 and CMP-05 and the Assessment contract belong to #9.
"""

from collections import Counter

from hypotrail.core.chinook_contract import CRITERIA


def _counters(verdicts: list[dict], name: str) -> dict:
    states = Counter()
    for verdict in verdicts:
        for criterion in verdict["criteria"] or []:
            if criterion["name"] == name:
                key = criterion["state"]
                if key == "scored":
                    key = "correct" if criterion["score"] is True else "incorrect"
                states[key] += 1
    return {
        "N_expected": len(verdicts),
        "N_attempted": sum(v["status"] != "missing" for v in verdicts),
        "N_produced": sum(v["status"] == "produced" for v in verdicts),
        "N_scored": states["correct"] + states["incorrect"],
        "N_correct": states["correct"],
        "N_incorrect": states["incorrect"],
        "N_unscored": states["unscored"],
        "N_errored": states["errored"],
    }


def tally(verdicts: list[dict], criteria: tuple[str, ...] = CRITERIA) -> dict:
    tool_errors = Counter(code for v in verdicts for code in v["tool_error_codes"])
    return {
        "criteria": {name: _counters(verdicts, name) for name in criteria},
        "tool_errors": {"total": sum(tool_errors.values()), "by_code": dict(sorted(tool_errors.items()))},
        "awaiting_criteria_decision": [
            [v["case_id"], v["repeat"]] for v in verdicts if v["criteria"] is None
        ],
    }
