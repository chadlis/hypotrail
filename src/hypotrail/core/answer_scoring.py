"""Scoring one Chinook answer against its frozen Reference.

Standard library only: this is the one scoring function, whatever produced the
answer. It compares status, reason, columns (in order), rows (in order) and unit.
There is no conversion from a string to a number, a boolean is not an integer,
NULL stays NULL, non-finite numbers are refused (the tokens `NaN`, `Infinity` and `-Infinity`, and a
literal such as `1e999` that decodes to infinity), and no number is picked out of
prose. An answer missing one of the six required fields is malformed. The
Reference's absolute tolerance applies to numbers; it is 0 for exact comparison.
"""

import json
import math
from decimal import Decimal
from typing import NamedTuple

COMPONENTS = ("status", "reason_code", "columns", "rows", "unit")
REQUIRED_FIELDS = (*COMPONENTS, "evidence")


def _refuse_constant(name):
    raise ValueError(f"non-finite number: {name}")


def _refuse_overflow(literal):
    """A number literal with a fraction or an exponent, as a float; a literal that overflows is refused.

    An integer literal is never passed here, so an integer too large for a double stays an integer.
    """
    value = float(literal)
    if not math.isfinite(value):
        raise ValueError(f"non-finite number: {literal}")
    return value


def parse_answer(text):
    """The answer as a dict, or None when it is not exactly one JSON object."""
    if not isinstance(text, str):
        return None
    try:
        value = json.loads(text, parse_constant=_refuse_constant, parse_float=_refuse_overflow)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


class EmbeddedObject(NamedTuple):
    """The one JSON object an answer contains: the exact slice it was read from, and its decoded dict."""

    text: str
    value: dict


def find_embedded_object(text):
    """The one JSON object an answer contains, as an `EmbeddedObject`, or None.

    The text is scanned left to right. At each `{` the standard decoder tries to read one value
    (refusing `NaN`, `Infinity`, `-Infinity` and a number literal that decodes to infinity, as `parse_answer` does); a read that gives an
    object is a candidate and the scan resumes after its last character, so an object nested in a
    candidate is not another one. A failed read (a stray brace, a truncated object, a non-finite
    number, an integer beyond Python's parse limit) skips only its `{`: an object that decodes further on, even inside the text of a failed
    read, is a candidate.
    Numbers, strings and arrays are never candidates, and a Markdown fence needs no special case.
    Exactly one candidate is returned, with the exact slice of `text` it was read from; none, or
    several, give None. Nothing is converted or picked out of prose.
    """
    if not isinstance(text, str):
        return None
    decoder = json.JSONDecoder(parse_constant=_refuse_constant, parse_float=_refuse_overflow)
    found = None
    position = text.find("{")
    while position != -1:
        try:
            value, end = decoder.raw_decode(text, position)
        except ValueError:
            position = text.find("{", position + 1)
            continue
        if isinstance(value, dict):
            if found is not None:
                return None
            found = EmbeddedObject(text[position:end], value)
        position = text.find("{", end)
    return found


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


def score_object(answer, reference: dict) -> dict:
    """Compare an answer already decoded (a dict, or None when nothing was read) with a Reference record.

    An answer that is not a dict, or that lacks one of the six required fields, is malformed:
    `parsed` is False and every component is False.
    """
    # An answer without a required field is malformed, whatever the Reference holds:
    # a missing field must not read as the null a Reference may hold (AG-08).
    if answer is None or any(field not in answer for field in REQUIRED_FIELDS):
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

