"""The `chinook_contract_v1` Scorer: Criteria for one Chinook answer.

Standard library plus `jsonschema`; it does not depend on the agent extra (ADR 0001). It turns one
Episode's raw final answer, its Reference and, when there is one, the Episode's projected
steps (plain records) into four Criteria, `exact_table`, `format_valid`,
`evidence_link_valid` and `contract_success`, each in state `scored`, `unscored` or
`errored`. Every abnormal outcome carries a Reason:

- `evidence_link_valid` is scored false, with a Reason, when a cited ID is unknown to the
  trace, designates a call that failed (a tool-level error or a structured `error` in
  the result), comes after the final answer, or has a native ID matching no tool-call event;
  or when an `answered` answer cites nothing. Without a trace it is `unscored`
  (`trace_missing`).
- `contract_success`: for `answered`, `exact_table` AND `format_valid` AND
  `evidence_link_valid`; for the other statuses, `format_valid` and the exact status and
  reason, with no tool call required. It is false as soon as one dependency is false; only
  otherwise does an `unscored` or `errored` dependency give its state and Reason.

- `invalid_response_format`: the raw answer is not one JSON object valid against the
  Workload's `table-answer/1` schema. `format_valid` and `contract_success` are scored
  false; this counts against the evaluated system. What `exact_table` and
  `evidence_link_valid` read depends on the answer (owner decision of 2026-11-07, #58):
  an answer that is exactly one JSON object is read as it is; an answer that is not, but
  contains exactly one JSON object (prose before or after it, a Markdown fence around it),
  is judged as that object alone; an answer from which nothing is read (no JSON object, or
  more than one) has every Criterion scored false with this Reason, trace or not. An extra
  field alone makes `format_valid` false and leaves `exact_table` to the comparison. A
  wrapped answer with one object, without a trace, has `evidence_link_valid` `unscored`
  (`trace_missing`) when that object alone is schema-valid, and scored false with this
  Reason, trace or not, when it is not.
- `reference_missing` / `reference_invalid`: the Reference is absent or unusable.
  `exact_table` is `unscored`. This is an Instrument failure.
- `scoring_failed`: the scoring machinery raised. Every Criterion is `errored` and
  the exception's type is kept in `error_type`. This is an Instrument failure.

The raw answer is never altered. The record says what `exact_table` and `evidence_link_valid`
were scored on, in its top-level `answer_read_from`: `"raw_answer"`, `"embedded_object"` or
`None` (nothing read). A `scoring_failed` record has no such field: nobody established what was read.
Nothing here reads a file, calls a model or a tool.
"""

import math

from jsonschema import Draft202012Validator

from hypotrail.core.answer_scoring import find_embedded_object, parse_answer, score_object

SCORER_NAME = "chinook_contract_v1"
SCORER_VERSION = "2"
CRITERIA = ("exact_table", "format_valid", "evidence_link_valid", "contract_success")

READ_FROM_RAW_ANSWER = "raw_answer"
READ_FROM_EMBEDDED_OBJECT = "embedded_object"

INVALID_RESPONSE_FORMAT = "invalid_response_format"
REFERENCE_MISSING = "reference_missing"
REFERENCE_INVALID = "reference_invalid"
SCORING_FAILED = "scoring_failed"
TRACE_MISSING = "trace_missing"
EVIDENCE_MISSING = "evidence_missing"
EVIDENCE_UNKNOWN_ID = "evidence_unknown_id"
EVIDENCE_CALL_FAILED = "evidence_call_failed"
EVIDENCE_AFTER_FINAL_ANSWER = "evidence_after_final_answer"
EVIDENCE_NO_NATIVE_EVENT = "evidence_no_native_event"


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


def _read_answer(raw_answer):
    """What the content Criteria read: (where from, the object read).

    The raw answer's own object when it is exactly one JSON object; else the one object it
    contains; else nothing (`None`, `None`). The raw text is decoded here once.
    """
    answer = parse_answer(raw_answer)
    if answer is not None:
        return READ_FROM_RAW_ANSWER, answer
    found = find_embedded_object(raw_answer)
    if found is not None:
        return READ_FROM_EMBEDDED_OBJECT, found[1]
    return None, None


def _format_valid(object_valid, read_from):
    """Valid only when the raw answer is itself the object and the object is schema-valid."""
    if read_from == READ_FROM_RAW_ANSWER and object_valid:
        return _criterion("format_valid", "scored", True)
    return _criterion("format_valid", "scored", False, INVALID_RESPONSE_FORMAT)


def _exact_table(answer, reference):
    """`answer` is the object `_read_answer` chose, or None when nothing was read."""
    problem = reference_problem(reference)
    if problem is not None:
        return _criterion("exact_table", "unscored", None, problem)
    verdict = score_object(answer, reference)
    if not verdict["parsed"]:
        # Not one JSON object with the six fields: never a correct table. It is the system's
        # failure, so it is scored false with its Reason, as format_valid is.
        return _criterion("exact_table", "scored", False, INVALID_RESPONSE_FORMAT, components=verdict["components"])
    return _criterion("exact_table", "scored", verdict["correct"], components=verdict["components"])


def _link_problem(cited, steps):
    """The Reason one cited application ID does not designate a usable call, or None."""
    end = next((i for i, s in enumerate(steps) if s.get("kind") == "final_answer"), len(steps))
    matches = [
        (i, s)
        for i, s in enumerate(steps)
        if s.get("kind") == "tool_result" and s.get("app_tool_call_id") == cited
    ]
    if not matches:
        return EVIDENCE_UNKNOWN_ID
    index, step = matches[0]
    body = step.get("result")
    if step.get("tool_error") is not None or (isinstance(body, dict) and body.get("error") is not None):
        return EVIDENCE_CALL_FAILED
    if index > end:
        return EVIDENCE_AFTER_FINAL_ANSWER
    native = step.get("native_tool_call_id")
    if not any(
        s.get("kind") == "tool_call" and s.get("native_tool_call_id") == native
        for s in steps[:index]
    ):
        return EVIDENCE_NO_NATIVE_EVENT
    return None


def _evidence_link_valid(answer, format_ok, steps):
    """Do the IDs the answer cites designate successful calls of this Episode, made earlier?

    Read from the projected steps only. `answer` is the object read (the raw answer, or the one
    object a wrapped answer contains; None when nothing is read) and `format_ok` whether that
    object alone is valid against the schema. An answer from which nothing is read, or an object
    that is not valid, has no usable `evidence`: it is scored false with `invalid_response_format`,
    trace or not. Without a trace a schema-valid object's link cannot be judged (`trace_missing`),
    a wrapped answer's included.
    """
    if not format_ok:
        return _criterion("evidence_link_valid", "scored", False, INVALID_RESPONSE_FORMAT)
    if steps is None:
        return _criterion("evidence_link_valid", "unscored", None, TRACE_MISSING)
    cited = answer["evidence"]
    if answer["status"] == "answered" and not cited:
        return _criterion("evidence_link_valid", "scored", False, EVIDENCE_MISSING)
    for identifier in cited:
        problem = _link_problem(identifier, steps)
        if problem is not None:
            return _criterion("evidence_link_valid", "scored", False, problem)
    return _criterion("evidence_link_valid", "scored", True)


def _dependencies(answer, exact_table, format_valid, evidence_link_valid):
    """The Criteria (or components of one) that contract success depends on."""
    if answer is None or format_valid["score"] is not True:
        return [format_valid]
    if answer["status"] == "answered":
        return [exact_table, format_valid, evidence_link_valid]
    # needs_clarification / not_answerable: the exact status and reason, no tool call.
    if exact_table["state"] != "scored":
        return [format_valid, exact_table]
    components = exact_table["components"]
    return [
        format_valid,
        _criterion("status", "scored", components["status"]),
        _criterion("reason_code", "scored", components["reason_code"]),
    ]


def _contract_success(answer, exact_table, format_valid, evidence_link_valid):
    """True only when every dependency is true; false as soon as one is false (AG-08, AG-09).

    A dependency that is `errored` or `unscored` gives its state and Reason only when
    no dependency is false: an answer that already fails is not rescued by a gap elsewhere.
    """
    deps = _dependencies(answer, exact_table, format_valid, evidence_link_valid)
    failed = next((d for d in deps if d["state"] == "scored" and d["score"] is False), None)
    if failed is not None:
        return _criterion("contract_success", "scored", False, failed["reason"])
    for state in ("errored", "unscored"):
        gap = next((d for d in deps if d["state"] == state), None)
        if gap is not None:
            return _criterion("contract_success", state, None, gap["reason"])
    return _criterion("contract_success", "scored", True)


def score_episode(raw_answer, reference, schema, steps=None) -> dict:
    """The Criteria of one Episode's raw final answer. Pure; may raise."""
    read_from, read = _read_answer(raw_answer)
    object_valid = read is not None and Draft202012Validator(schema).is_valid(read)
    format_valid = _format_valid(object_valid, read_from)
    exact_table = _exact_table(read, reference)
    evidence_link_valid = _evidence_link_valid(read, object_valid, steps)
    # contract success depends on the raw answer alone: a wrapped answer is not a success
    raw_object = read if read_from == READ_FROM_RAW_ANSWER else None
    contract_success = _contract_success(raw_object, exact_table, format_valid, evidence_link_valid)
    return {
        "scorer": _scorer_record(),
        "raw_answer": raw_answer,
        "answer_read_from": read_from,
        "criteria": [exact_table, format_valid, evidence_link_valid, contract_success],
    }


def apply_scorer(scorer, raw_answer, reference, schema, steps=None) -> dict:
    """Apply a Scorer to one Episode; a crash errors this Episode's Criteria only.

    The exception's type is kept in `error_type` (a structured field); its message is
    never kept or read.
    """
    try:
        return scorer(raw_answer, reference, schema, steps)
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
