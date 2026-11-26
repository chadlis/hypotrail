"""`text_facts_v1`: the Scorer of a prose answer against a `text-reference/1` Reference (#265).

One pure function, `score_text`, takes the raw answer text, the Reference record and the Workload's scoring config, and
gives five Criteria, each in state `scored`, `unscored` or `errored`, with a Reason for every non-score and every false:

- `identifiers_complete`: every expected identifier, normalised, is among those found in the text (`identifier_missing`);
- `no_unexpected_identifier`: every identifier found, normalised, is expected (`identifier_unexpected`);
- `facts_present`: every expected fact is found in the text (`fact_missing`). A number counts within its absolute
  tolerance, ignoring the currency signs `$ € £` and `,` thousands separators, and never through a `%`, nor from inside an
  identifier match or an ISO date; a date counts in ISO form; a text counts as a casefolded substring;
- `outcome_matches`: the answer's outcome is the Reference's `expected_outcome` (`outcome_mismatch`). The outcome is the
  one the Import line declares; otherwise the one the config's phrase rules recognise (`needs_clarification`, then
  `not_answerable`, else `answered`); without either it is `unscored` with `outcome_not_declared`;
- `text_facts_success`: the conjunction of the four, false as soon as one is false, otherwise the state and Reason of the
  first that is not scored, as `contract_success` of `chinook_contract_v1` is.

A Reference that is absent makes every Criterion `unscored` with `reference_missing`, one that does not read as
`text-reference/1`, or names an identifier kind the config does not declare, with `reference_invalid`; a raise inside the scoring makes every Criterion `errored` with
`scoring_failed` (`apply`). The raw answer is never altered. The identifier kinds, their patterns and normalisation, and
the phrase rules are data the Workload declares (`scoring/text-facts.json`, ADR 0002). Standard library only; Inspect's
scorers are not used (they are `async` functions of a `TaskState`, and this one must run where Inspect is absent).
"""

import datetime
import math
import re
from dataclasses import dataclass

SCORER_NAME = "text_facts_v1"
SCORER_VERSION = "1"
REFERENCE_VERSION_SHAPE = "text-reference/1"
CRITERIA = ("identifiers_complete", "no_unexpected_identifier", "facts_present", "outcome_matches", "text_facts_success")
PRIMARY = "text_facts_success"

OUTCOMES = ("answered", "needs_clarification", "not_answerable")
FACT_TYPES = ("integer", "decimal", "date", "text")

IDENTIFIER_MISSING = "identifier_missing"
IDENTIFIER_UNEXPECTED = "identifier_unexpected"
FACT_MISSING = "fact_missing"
OUTCOME_MISMATCH = "outcome_mismatch"
OUTCOME_NOT_DECLARED = "outcome_not_declared"
REFERENCE_MISSING = "reference_missing"
REFERENCE_INVALID = "reference_invalid"
SCORING_FAILED = "scoring_failed"
REASONS = (IDENTIFIER_MISSING, IDENTIFIER_UNEXPECTED, FACT_MISSING, OUTCOME_MISMATCH, OUTCOME_NOT_DECLARED, REFERENCE_MISSING, REFERENCE_INVALID, SCORING_FAILED)

CURRENCY_SIGNS = "$€£"
# A number not glued to a word, a dot or a dash before it (so the parts of an ISO date after its year are not numbers), with
# optional `,` thousands groups; one followed by `%` is skipped.
_NUMBER = re.compile(r"(?<![\w.\-])(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?![\d.,]*\d)(?!\s*%)")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_REFERENCE_KEYS = {"case_id", "reference_version", "expected_outcome", "expected_identifiers", "expected_facts", "as_of"}
_OPTIONAL_REFERENCE_KEYS = {"reference_text"}


class ReferenceInvalid(ValueError):
    """The record does not read as `text-reference/1`."""


@dataclass(frozen=True)
class Fact:
    fact_id: str
    type: str
    value: object
    tolerance: float


@dataclass(frozen=True)
class TextReference:
    case_id: str
    expected_outcome: str
    identifiers: tuple  # (kind, value) pairs as the Reference writes them
    facts: tuple
    reference_text: str | None


def _text(value) -> bool:
    return isinstance(value, str) and value != ""


def _iso_date(value) -> bool:
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _fact(entry) -> Fact:
    if not isinstance(entry, dict) or not set(entry) <= {"fact_id", "type", "value", "tolerance", "rule"}:
        raise ReferenceInvalid("a fact is an object of fact_id, type, value, tolerance and rule")
    if not _text(entry.get("fact_id")) or entry.get("type") not in FACT_TYPES or not _text(entry.get("rule")):
        raise ReferenceInvalid("a fact names its fact_id, a known type and its rule")
    kind, value = entry["type"], entry.get("value")
    numeric = kind in ("integer", "decimal")
    if kind == "integer" and not (isinstance(value, int) and not isinstance(value, bool)):
        raise ReferenceInvalid("an integer fact holds an integer")
    if kind == "decimal" and not _number(value):
        raise ReferenceInvalid("a decimal fact holds a finite number")
    if kind == "date" and not _iso_date(value):
        raise ReferenceInvalid("a date fact holds an ISO date")
    if kind == "text" and not _text(value):
        raise ReferenceInvalid("a text fact holds a non-empty string")
    tolerance = entry.get("tolerance", 0)
    if "tolerance" in entry and not numeric:
        raise ReferenceInvalid("only a numeric fact has a tolerance")
    if not _number(tolerance) or tolerance < 0:
        raise ReferenceInvalid("a tolerance is a non-negative number")
    return Fact(entry["fact_id"], kind, value, float(tolerance))


def read_reference(record) -> TextReference:
    """The typed `text-reference/1` value of one Reference record; `ReferenceInvalid` when it does not read as one."""
    if not isinstance(record, dict):
        raise ReferenceInvalid("a Reference is a JSON object")
    keys = set(record)
    if not _REFERENCE_KEYS <= keys or not keys <= _REFERENCE_KEYS | _OPTIONAL_REFERENCE_KEYS:
        raise ReferenceInvalid("a Reference holds exactly the keys of text-reference/1")
    if not _text(record["case_id"]) or not _text(record["reference_version"]) or not _iso_date(record["as_of"]):
        raise ReferenceInvalid("case_id, reference_version and an ISO as_of date")
    if record["expected_outcome"] not in OUTCOMES:
        raise ReferenceInvalid("expected_outcome is one of the three outcomes")
    identifiers = record["expected_identifiers"]
    if not isinstance(identifiers, list) or not all(
        isinstance(i, dict) and set(i) == {"kind", "value"} and _text(i["kind"]) and _text(i["value"]) for i in identifiers
    ):
        raise ReferenceInvalid("expected_identifiers is a list of {kind, value}")
    if not isinstance(record["expected_facts"], list):
        raise ReferenceInvalid("expected_facts is a list")
    reference_text = record.get("reference_text")
    if "reference_text" in record and not _text(reference_text):
        raise ReferenceInvalid("reference_text, when present, is a non-empty string")
    return TextReference(
        record["case_id"],
        record["expected_outcome"],
        tuple((i["kind"], i["value"]) for i in identifiers),
        tuple(_fact(entry) for entry in record["expected_facts"]),
        reference_text,
    )


def reference_problem(record) -> str | None:
    """`reference_missing`, `reference_invalid`, or None for a Reference that reads as `text-reference/1`."""
    if record is None:
        return REFERENCE_MISSING
    try:
        read_reference(record)
    except ReferenceInvalid:
        return REFERENCE_INVALID
    return None


# --- the parts of a text the Criteria read ------------------------------------------------------------------------------------


def normalised(kind_config: dict, value: str) -> str:
    """An identifier as the config's normalisation of its kind gives it: the listed separators removed, leading zeros stripped, casefolded."""
    for separator in kind_config.get("separators", []):
        value = value.replace(separator, "")
    if kind_config.get("strip_leading_zeros", False):
        value = value.lstrip("0") or "0"
    if kind_config.get("casefold", False):
        value = value.casefold()
    return value


def identifiers_in(text: str, config: dict) -> set:
    """Every (kind, normalised value) the config's patterns find in the text, each pattern's one capture group being the value."""
    found = set()
    for kind, kind_config in config["identifier_kinds"].items():
        for match in re.finditer(kind_config["pattern"], text):
            found.add((kind, normalised(kind_config, match.group(1))))
    return found


def numbers_in(text: str) -> list:
    """The numbers of the text, read without its currency signs and `,` thousands separators; a number before `%` is not one."""
    for sign in CURRENCY_SIGNS:
        text = text.replace(sign, " ")
    return [float(match.replace(",", "")) for match in _NUMBER.findall(text)]


def without_identifiers_and_dates(text: str, config: dict) -> str:
    """The text with every identifier match, of any configured kind, and every ISO date blanked to spaces, so their numbers are not read as numbers."""
    spans = [match.span() for kind_config in config["identifier_kinds"].values() for match in re.finditer(kind_config["pattern"], text)]
    spans += [match.span() for match in _ISO_DATE.finditer(text)]
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def fact_found(fact: Fact, text: str, numbers: list) -> bool:
    if fact.type in ("integer", "decimal"):
        return any(abs(number - fact.value) <= fact.tolerance for number in numbers)
    if fact.type == "date":
        return fact.value in text
    return fact.value.casefold() in text.casefold()


def recognised_outcome(text: str, config: dict) -> str | None:
    """The outcome the config's phrase rules recognise, `answered` when none matches; None when the config declares no phrase rule."""
    phrases = config.get("outcome_phrases") or {}
    if not any(phrases.get(outcome) for outcome in OUTCOMES[1:]):
        return None
    folded = text.casefold()
    for outcome in ("needs_clarification", "not_answerable"):
        if any(phrase.casefold() in folded for phrase in phrases.get(outcome, [])):
            return outcome
    return "answered"


# --- the Criteria ---------------------------------------------------------------------------------------------------------------


def _criterion(name, state, score=None, reason=None):
    return {"name": name, "state": state, "score": score, "reason": reason}


def _boolean(name, holds: bool, reason: str):
    return _criterion(name, "scored", holds, None if holds else reason)


def _all(state: str, reason: str) -> list:
    return [_criterion(name, state, None, reason) for name in CRITERIA]


def _success(parts: list) -> dict:
    failed = next((p for p in parts if p["state"] == "scored" and p["score"] is False), None)
    if failed is not None:
        return _criterion(PRIMARY, "scored", False, failed["reason"])
    for state in ("errored", "unscored"):
        gap = next((p for p in parts if p["state"] == state), None)
        if gap is not None:
            return _criterion(PRIMARY, state, None, gap["reason"])
    return _criterion(PRIMARY, "scored", True)


def score_text(raw_answer: str, reference_record, config: dict, declared_outcome: str | None = None) -> dict:
    """The five Criteria of one prose answer. Pure; may raise (an unreadable config, a bad pattern)."""
    problem = reference_problem(reference_record)
    if problem is not None:
        return {"criteria": _all("unscored", problem)}
    reference = read_reference(reference_record)
    kinds = config["identifier_kinds"]
    if any(kind not in kinds for kind, _ in reference.identifiers):
        return {"criteria": _all("unscored", REFERENCE_INVALID)}
    expected = {(kind, normalised(kinds[kind], value)) for kind, value in reference.identifiers}
    found = identifiers_in(raw_answer, config)
    numbers = numbers_in(without_identifiers_and_dates(raw_answer, config))
    outcome = declared_outcome if declared_outcome is not None else recognised_outcome(raw_answer, config)
    if outcome is None:
        outcome_matches = _criterion("outcome_matches", "unscored", None, OUTCOME_NOT_DECLARED)
    else:
        outcome_matches = _boolean("outcome_matches", outcome == reference.expected_outcome, OUTCOME_MISMATCH)
    parts = [
        _boolean("identifiers_complete", expected <= found, IDENTIFIER_MISSING),
        _boolean("no_unexpected_identifier", found <= expected, IDENTIFIER_UNEXPECTED),
        _boolean("facts_present", all(fact_found(fact, raw_answer, numbers) for fact in reference.facts), FACT_MISSING),
        outcome_matches,
    ]
    return {"criteria": [*parts, _success(parts)]}


def apply(raw_answer: str, reference_record, config: dict, declared_outcome: str | None = None) -> dict:
    """`score_text` of one Episode; a raise errors this Episode's Criteria only, its type kept and its message never read."""
    try:
        return score_text(raw_answer, reference_record, config, declared_outcome)
    except Exception as error:
        return {"criteria": _all("errored", SCORING_FAILED), "error_type": type(error).__name__}
