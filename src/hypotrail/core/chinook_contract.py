"""The `chinook_contract_v1` Scorer: Criteria for one Chinook answer.

Standard library plus `jsonschema`; it does not depend on the agent extra (ADR 0001). It turns one
Episode's raw final answer and its Reference into two Criteria, `exact_table` and
`format_valid`, each in state `scored`, `unscored` or `errored`. Every abnormal
outcome carries a Reason:

- `invalid_response_format`: the raw answer is not one JSON object valid against the
  Workload's `table-answer/1` schema. `format_valid` is scored false; this counts
  against the evaluated system.
- `reference_missing` / `reference_invalid`: the Reference is absent or unusable.
  `exact_table` is `unscored`. This is an Instrument failure.
- `scoring_failed`: the scoring machinery raised. Every Criterion is `errored` and
  the exception's type is kept in `error_type`. This is an Instrument failure.

The raw answer is never altered. Nothing here reads a file, calls a model or a tool.
"""

import math

from jsonschema import Draft202012Validator

from hypotrail.core.answer_scoring import COMPONENTS, parse_answer, score_answer

SCORER_NAME = "chinook_contract_v1"
SCORER_VERSION = "1"
CRITERIA = ("exact_table", "format_valid")

INVALID_RESPONSE_FORMAT = "invalid_response_format"
REFERENCE_MISSING = "reference_missing"
REFERENCE_INVALID = "reference_invalid"
SCORING_FAILED = "scoring_failed"


def _criterion(name, state, score=None, reason=None, **extra):
    return {"name": name, "state": state, "score": score, "reason": reason, **extra}


def _scorer_record():
    return {"name": SCORER_NAME, "version": SCORER_VERSION}


def reference_problem(reference):
    """The Reason a Reference cannot be used, or None when it can."""
    if reference is None:
        return REFERENCE_MISSING
    if not isinstance(reference, dict):
        return REFERENCE_INVALID
    for field in ("status", "reason_code", "columns", "rows", "unit"):
        if field not in reference:
            return REFERENCE_INVALID
    rows = reference["rows"]
    if not isinstance(reference["columns"], list):
        return REFERENCE_INVALID
    if not isinstance(rows, list) or not all(isinstance(row, list) for row in rows):
        return REFERENCE_INVALID
    tolerance = reference.get("numeric_absolute_tolerance", 0)
    if (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or not math.isfinite(tolerance)
        or tolerance < 0
    ):
        return REFERENCE_INVALID
    return None


def _format_valid(raw_answer, schema):
    answer = parse_answer(raw_answer)
    if answer is not None and Draft202012Validator(schema).is_valid(answer):
        return _criterion("format_valid", "scored", True)
    return _criterion("format_valid", "scored", False, INVALID_RESPONSE_FORMAT)


def _exact_table(raw_answer, reference, format_ok):
    problem = reference_problem(reference)
    if problem is not None:
        return _criterion("exact_table", "unscored", None, problem)
    if not format_ok:
        # A malformed answer is never a correct table, as in the spike's rule that a
        # missing field makes every component false; format_valid carries the Reason.
        components = {name: False for name in COMPONENTS}
        return _criterion("exact_table", "scored", False, components=components)
    verdict = score_answer(raw_answer, reference)
    return _criterion("exact_table", "scored", verdict["correct"], components=verdict["components"])


def score_episode(raw_answer, reference, schema) -> dict:
    """The Criteria of one Episode's raw final answer. Pure; may raise."""
    format_valid = _format_valid(raw_answer, schema)
    exact_table = _exact_table(raw_answer, reference, format_valid["score"])
    return {
        "scorer": _scorer_record(),
        "raw_answer": raw_answer,
        "criteria": [exact_table, format_valid],
    }


def apply_scorer(scorer, raw_answer, reference, schema) -> dict:
    """Apply a Scorer to one Episode; a crash errors this Episode's Criteria only.

    The exception's type is kept in `error_type` (a structured field); its message is
    never kept or read.
    """
    try:
        return scorer(raw_answer, reference, schema)
    except Exception as error:
        return {
            "scorer": _scorer_record(),
            "raw_answer": raw_answer,
            "criteria": [_criterion(name, "errored", None, SCORING_FAILED) for name in CRITERIA],
            "error_type": type(error).__name__,
        }


def counts_against_system(result) -> bool:
    """True when some Criterion is scored false: Instrument failures never count."""
    return any(c["state"] == "scored" and c["score"] is False for c in result["criteria"])
