"""Scoring one Chinook answer against its frozen Reference.

Standard library only: this is the one scoring function, whatever produced the
answer. It compares status, reason, columns (in order), rows (in order) and unit.
There is no conversion from a string to a number, a boolean is not an integer,
NULL stays NULL, non-finite numbers are refused, and no number is picked out of
prose. The Reference's absolute tolerance applies to numbers; it is 0 for exact
comparison.
"""

import json
import math
from decimal import Decimal

COMPONENTS = ("status", "reason_code", "columns", "rows", "unit")


def _refuse_constant(name):
    raise ValueError(f"non-finite number: {name}")


def parse_answer(text):
    """The answer as a dict, or None when it is not exactly one JSON object."""
    if not isinstance(text, str):
        return None
    try:
        value = json.loads(text, parse_constant=_refuse_constant)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _same_cell(expected, actual, tolerance):
    if expected is None or actual is None:
        return expected is None and actual is None
    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(expected, bool) and isinstance(actual, bool) and expected == actual
    if _is_number(expected):
        if not _is_number(actual):
            return False
        if isinstance(actual, float) and not math.isfinite(actual):
            return False
        return abs(Decimal(str(expected)) - Decimal(str(actual))) <= Decimal(str(tolerance))
    return isinstance(expected, str) and isinstance(actual, str) and expected == actual


def _same_rows(expected, actual, tolerance):
    if not isinstance(actual, list) or len(actual) != len(expected):
        return False
    for expected_row, actual_row in zip(expected, actual):
        if not isinstance(actual_row, list) or len(actual_row) != len(expected_row):
            return False
        if not all(_same_cell(e, a, tolerance) for e, a in zip(expected_row, actual_row)):
            return False
    return True


def score_answer(answer_text, reference: dict) -> dict:
    """Compare an answer (raw text) with a Reference record."""
    answer = parse_answer(answer_text)
    if answer is None:
        return {
            "parsed": False,
            "correct": False,
            "components": {name: False for name in COMPONENTS},
        }
    tolerance = reference.get("numeric_absolute_tolerance", 0)
    components = {
        "status": answer.get("status") == reference["status"],
        "reason_code": answer.get("reason_code") == reference["reason_code"],
        "columns": answer.get("columns") == reference["columns"],
        "rows": _same_rows(reference["rows"], answer.get("rows"), tolerance),
        "unit": answer.get("unit") == reference["unit"],
    }
    return {"parsed": True, "correct": all(components.values()), "components": components}
