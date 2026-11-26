"""`text_facts_v1`: the Scorer of a prose answer against a `text-reference/1` Reference (#265).

One pure function, `score_text`, takes the raw answer text, the Reference record and the Workload's scoring config, and
gives five Criteria, each in state `scored`, `unscored` or `errored`, with a Reason for every non-score and every false:

- `identifiers_complete`: every expected identifier, normalised, is among those found in the text (`identifier_missing`).
  The text is read block by block (paragraphs, list items, table cells and headings; fenced code is ignored): an identifier
  found is a kind pattern's capture and each item an explicit joiner adds to it ("invoices 34, 155 and 166"), or the leading
  number of an item in a list under a lead-in that names one kind ("Invoices:" over "- 34");
- `no_unexpected_identifier`: every identifier found, normalised, is expected or allowed (`identifier_unexpected`); the
  optional `allowed_identifiers` of a Reference lists the records an answer may name beside the expected ones;
- `facts_present`: every expected fact is found in the text (`fact_missing`). A number counts within its absolute
  tolerance, ignoring the currency signs `$ € £` and `,` thousands separators, and never through a `%`, nor from a list
  marker, an identifier value, an ISO date and its time, or fenced code; a date counts in ISO form; a text counts as a
  casefolded substring of the raw answer;
- `outcome_matches`: the answer's outcome is the Reference's `expected_outcome` (`outcome_mismatch`). The outcome is the
  one the Import line declares; otherwise the one the config's phrase rules recognise (`needs_clarification`, then
  `not_answerable`, else `answered`); without either it is `unscored` with `outcome_not_declared`;
- `text_facts_success`: the conjunction of the four, false as soon as one is false, otherwise the state and Reason of the
  first that is not scored, as `contract_success` of `chinook_contract_v1` is.

A Reference that is absent makes every Criterion `unscored` with `reference_missing`, one that does not read as
`text-reference/1`, or names (as expected or allowed) an identifier kind the config does not declare, with `reference_invalid`; a raise inside the scoring makes every Criterion `errored` with
`scoring_failed` (`apply`). The raw answer is never altered. The identifier kinds, their patterns and normalisation, and
the phrase rules are data the Workload declares (`scoring/text-facts.json`, ADR 0002). Standard library only; Inspect's
scorers are not used (they are `async` functions of a `TaskState`, and this one must run where Inspect is absent).
"""

import datetime
import itertools
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
# A number not glued to a letter, a digit, `_`, a dot or a dash before it, with optional `,` thousands groups and a decimal
# part; one followed by `%` is skipped.
_NUMBER = re.compile(r"(?<![\w.\-])(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?![\d.,]*\d)(?!\s*%)")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# An ISO date, with the time "HH:MM" or "HH:MM:SS" that may follow it after a space or a "T": none of its parts is a number.
_DATE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?")
# D-163 on chadlis/hypotrail#75, item 2, verbatim: "number(s) of", "count of" or "total", followed by the plural, with any
# whitespace between them, makes the number a count and not an id.
_COUNT_BEFORE = re.compile(r"(?i)\b(?:numbers?\s+of|count\s+of|total)\s+\Z")
_PLURAL_LABEL = re.compile(r"[^\W\d_]+s\b")
# What may stand between a count phrase's plural and its number.
_COPULA = re.compile(r"(?i):|=|\b(?:is|are|was)\b")
# An item is a number, with "#" before it or not, that is not a date, an amount, a time or a percentage.
_ITEM = r"#?(?P<value>[0-9](?:[0-9_]*[0-9])?)\b(?![.,:/-][0-9])(?!\s*%)"
# The next item of a list: ",", ";", "&", "and" or "or", also ", and" and ", or", with whitespace around that may hold a line
# break. A bare space or a line break alone joins nothing.
_JOINED_NEXT = re.compile(r"(?i)\s*(?:,\s*(?:(?:and|or)\b\s*)?|;\s*|&\s*|(?<!\S)(?:and|or)\b\s*)" + _ITEM)
_LEADING_ITEM = re.compile(r"\s*" + _ITEM)
_TRAILING_COUNT = re.compile(r"(?i)\s+in\s+(?:total|all)\b")
# A pattern's capture that is an amount (a decimal part follows it) or the year of an ISO date is no identifier.
_NOT_AN_IDENTIFIER = re.compile(r"\.[0-9]|-[0-9]{2}-[0-9]{2}")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# The blocks of an answer, modelled on CommonMark 0.31.2 and GFM pipe tables.
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
_LIST_ITEM = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>[-*+]|[0-9]{1,9}[.)])[ \t]+(?P<rest>.*)$")
_HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+(?P<text>.*?))?(?:[ \t]+#+)?[ \t]*$")
_MARKUP_LINE = re.compile(r"^[ \t]*(?:-+|=+|\*+|_+)[ \t]*$")
_DELIMITER_CELL = re.compile(r"^[ \t]*:?-+:?[ \t]*$")
# An emphasis `_` run is removed at a word boundary only, never between two letters or digits.
_UNDERSCORES = re.compile(r"_+")
_REFERENCE_KEYS = {"case_id", "reference_version", "expected_outcome", "expected_identifiers", "expected_facts", "as_of"}
_OPTIONAL_REFERENCE_KEYS = {"reference_text", "allowed_identifiers"}


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
    allowed: tuple = ()  # (kind, value) pairs an answer may name without their being expected


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


def _identifier_list(value) -> bool:
    return isinstance(value, list) and all(
        isinstance(i, dict) and set(i) == {"kind", "value"} and _text(i["kind"]) and _text(i["value"]) for i in value
    )


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
    if not _identifier_list(identifiers):
        raise ReferenceInvalid("expected_identifiers is a list of {kind, value}")
    allowed = record.get("allowed_identifiers", [])
    if not _identifier_list(allowed):
        raise ReferenceInvalid("allowed_identifiers, when present, is a list of {kind, value}")
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
        tuple((i["kind"], i["value"]) for i in allowed),
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


class _Block:
    """One block of the answer: its text with the markup removed, and for a list item the item it is nested in and its list."""

    __slots__ = ("text", "item", "parent", "list_id")

    def __init__(self, text: str, item: bool = False, parent=None, list_id: int = -1):
        self.text, self.item, self.parent, self.list_id = text, item, parent, list_id


def _without_markup(text: str) -> str:
    """The text without inline code backticks, `*` and the `_` runs that do not stand between two letters or digits."""
    text = text.replace("`", "").replace("*", "")

    def underscores(run):
        before, after = run.string[run.start() - 1 : run.start()], run.string[run.end() : run.end() + 1]
        inside = before.isalnum() and after.isalnum()
        return run.group(0) if inside else ""

    return _UNDERSCORES.sub(underscores, text)


def _cells(line: str) -> list:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return line.split("|")


def _table_starts(lines: list, index: int) -> bool:
    if index + 1 >= len(lines) or "|" not in lines[index] or "|" not in lines[index + 1]:
        return False
    delimiter = _cells(lines[index + 1])
    return len(delimiter) == len(_cells(lines[index])) and all(_DELIMITER_CELL.match(cell) for cell in delimiter)


def _opens_block(lines: list, index: int) -> bool:
    line = lines[index]
    return bool(_FENCE.match(line) and not _not_a_fence(line)) or bool(_HEADING.match(line)) or bool(_LIST_ITEM.match(line)) or bool(_MARKUP_LINE.match(line)) or _table_starts(lines, index)


def _not_a_fence(line: str) -> bool:
    match = _FENCE.match(line)
    return match.group(1)[0] == "`" and "`" in match.group(2)


def _blocks(text: str) -> list:
    """The blocks of the text in order; fenced code gives none, and a list item knows its parent item and its list."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks, open_items, current = [], [], None  # open_items: (block, indent, content column) from the outermost
    pieces = []
    next_list = itertools.count()

    def close():
        nonlocal current
        if current is not None:
            current.text = _without_markup("\n".join(pieces))
            blocks.append(current)
        current = None
        pieces.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        fence = _FENCE.match(line)
        if fence and not _not_a_fence(line):
            close()
            run = fence.group(1)
            index += 1
            while index < len(lines) and not re.match(rf"^[ \t]*{re.escape(run[0])}{{{len(run)},}}[ \t]*$", lines[index]):
                index += 1
            index += 1
            continue
        if line.strip() == "":
            close()
            index += 1
            continue
        item = _LIST_ITEM.match(line)
        if item:
            close()
            indent = len(item.group("indent").expandtabs(4))
            sibling = None
            while open_items and open_items[-1][1] >= indent:
                sibling = open_items.pop()
            parent = open_items[-1][0] if open_items else None
            list_id = sibling[0].list_id if sibling is not None and sibling[0].parent is parent else next(next_list)
            current = _Block("", True, parent, list_id)
            pieces.append(item.group("rest"))
            open_items.append((current, indent, len(line) - len(item.group("rest"))))
            index += 1
            continue
        heading = _HEADING.match(line)
        if heading or _MARKUP_LINE.match(line):
            close()
            open_items.clear()
            if heading:
                blocks.append(_Block(_without_markup(heading.group("text") or "")))
            index += 1
            continue
        if _table_starts(lines, index):
            close()
            open_items.clear()
            rows = [lines[index]]
            index += 2
            while index < len(lines) and lines[index].strip() != "" and not _opens_block(lines, index):
                rows.append(lines[index])
                index += 1
            blocks.extend(_Block(_without_markup(cell.strip())) for row in rows for cell in _cells(row))
            continue
        if current is not None:
            pieces.append(line.strip())
            index += 1
            continue
        indent = len(line) - len(line.lstrip())
        while open_items and indent < open_items[-1][2]:
            open_items.pop()
        current = _Block("")
        pieces.append(line.strip())
        index += 1
    close()
    return blocks


def _captures(pattern: str, text: str):
    """The matches of a kind's pattern in the text whose capture is neither an amount nor the year of an ISO date."""
    return [m for m in re.finditer(pattern, text) if not _NOT_AN_IDENTIFIER.match(text, m.end(1))]


def _plain(text: str) -> str:
    """The text with its currency signs and its ISO dates (and the time after one) blanked to spaces."""
    for sign in CURRENCY_SIGNS:
        text = text.replace(sign, " ")
    return _DATE_TIME.sub(lambda date: " " * len(date.group(0)), text)


def _count_numbers(text: str, plain: str, config: dict) -> set:
    """The (start, end) of the number of each count phrase of the block: a fact, never an identifier, and no list goes on from it."""
    spans = set()
    for kind_config in config["identifier_kinds"].values():
        for match in re.finditer(kind_config["pattern"], text):
            plural = _PLURAL_LABEL.match(text, match.start())
            if plural is None or not _COUNT_BEFORE.search(text[: match.start()]):
                continue
            copula = _COPULA.search(text, plural.end())
            number = _NUMBER.search(plain, copula.end()) if copula else None
            spans.add(number.span(1) if number else match.span(1))
    return spans


def _lead_in_kind(text: str, config: dict) -> str | None:
    """The kind a lead-in names without a value, when it names exactly one and is no count phrase; None otherwise."""
    if not text.rstrip().endswith(":"):
        return None
    last = _SENTENCE_END.split(text.strip())[-1]
    named = []
    for kind, kind_config in config["identifier_kinds"].items():
        word = re.search(rf"(?i)\b{re.escape(kind)}s?\b", last)
        if word is not None and not _captures(kind_config["pattern"], last):
            named.append((kind, word))
    if len(named) != 1:
        return None
    kind, word = named[0]
    return None if _COUNT_BEFORE.search(last[: word.start()]) else kind


def _read_block(block: _Block, config: dict, label: str | None):
    """(identifiers, numbers) of one block; `label` is the kind of the lead-in whose list holds this item, if any."""
    text, kinds = block.text, config["identifier_kinds"]
    plain = _plain(text)
    counts = _count_numbers(text, plain, config)
    found, values = [], []

    def follow(kind, end):
        while (item := _JOINED_NEXT.match(text, end)) is not None:
            if item.span("value") in counts or _TRAILING_COUNT.match(text, item.end()):
                return
            found.append((kind, normalised(kinds[kind], item.group("value"))))
            values.append(item.span("value"))
            end = item.end()

    if label is not None and (leading := _LEADING_ITEM.match(text)) is not None:
        found.append((label, normalised(kinds[label], leading.group("value"))))
        values.append(leading.span("value"))
        follow(label, leading.end())
    for kind, kind_config in kinds.items():
        for match in _captures(kind_config["pattern"], text):
            if match.span(1) in counts:
                continue
            found.append((kind, normalised(kind_config, match.group(1))))
            values.append(match.span(1))
            follow(kind, match.end())
    chars = list(plain)
    for start, end in values:
        chars[start:end] = " " * (end - start)
    numbers = [float(number.replace(",", "")) for number in _NUMBER.findall("".join(chars))]
    return found, numbers


def _reading(text: str, config: dict):
    """(identifiers, numbers) of the whole text, read block by block: no reading crosses a block boundary."""
    blocks = _blocks(text)
    labels = {}
    for index, block in enumerate(blocks[:-1]):
        kind = _lead_in_kind(block.text, config)
        following = blocks[index + 1]
        if kind is None or not following.item or (block.item and following.parent is not block):
            continue
        labels.update({id(b): kind for b in blocks if b.item and b.list_id == following.list_id})
    identifiers, numbers = [], []
    for block in blocks:
        found, read = _read_block(block, config, labels.get(id(block)))
        identifiers += found
        numbers += read
    return identifiers, numbers


def identifiers_in(text: str, config: dict) -> set:
    """Every (kind, normalised value) the text names: a pattern's capture and the list after it, and the items of a labelled list."""
    return set(_reading(text, config)[0])


def fact_numbers(text: str, config: dict) -> list:
    """The numbers of the text that `facts_present` reads: every number outside fenced code, list markers, identifier values and ISO dates."""
    return _reading(text, config)[1]


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
    if any(kind not in kinds for kind, _ in reference.identifiers + reference.allowed):
        return {"criteria": _all("unscored", REFERENCE_INVALID)}
    expected = {(kind, normalised(kinds[kind], value)) for kind, value in reference.identifiers}
    allowed = {(kind, normalised(kinds[kind], value)) for kind, value in reference.allowed}
    identifiers, numbers = _reading(raw_answer, config)
    found = set(identifiers)
    outcome = declared_outcome if declared_outcome is not None else recognised_outcome(raw_answer, config)
    if outcome is None:
        outcome_matches = _criterion("outcome_matches", "unscored", None, OUTCOME_NOT_DECLARED)
    else:
        outcome_matches = _boolean("outcome_matches", outcome == reference.expected_outcome, OUTCOME_MISMATCH)
    parts = [
        _boolean("identifiers_complete", expected <= found, IDENTIFIER_MISSING),
        _boolean("no_unexpected_identifier", found <= expected | allowed, IDENTIFIER_UNEXPECTED),
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
