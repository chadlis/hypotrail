"""Trace quantitative English prose against values supplied by a Study read."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
import re


_SIGN = r"[-−–+]"
_SPACE = r"[ \u00a0\u202f\u2009]"
_BODY = (
    rf"[1-9]\d{{0,2}}(?:,\d{{3}})+(?:\.\d+)?|"
    rf"[1-9]\d{{0,2}}(?:{_SPACE}\d{{3}})+(?!\d|\.\d|,\d{{3}})(?:,\d+)?|"
    r"\d+(?:[.,]\d+)?|\.\d+"
)
_COMMA_GROUP = re.compile(r"[1-9]\d{0,2}(?:,\d{3})+(?:\.\d+)?")
_SCALE = {"k": 3, "K": 3, "M": 6, "x": 0, "×": 0, "thousand": 3, "million": 6, "bn": 9, "billion": 9, "trillion": 12}
_SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺"
_SUPERSCRIPT = str.maketrans(_SUPERSCRIPTS, "0123456789-+")
_POINTS = r"percentage[- ]points?|pp|p\.p\.|points?|pts?"
_RATE = rf"%|percent|per cent|‰|per mille|per mil|permille|{_POINTS}"
_EXPONENT = re.compile(r"(?P<sign>[-+−]?)(?P<digits>\d+)")
_DIGITS = re.compile(
    rf"(?<![\w.])(?P<sign>{_SIGN})?(?P<body>{_BODY})"
    r"(?:[eE](?P<exponent>[-+−]?\d+)"
    r"|\s?[x×*·]\s?10(?:\^\(?(?P<power>[-+−]?\d+)\)?"
    rf"|(?P<superscript>[{_SUPERSCRIPTS}]+))"
    r"|[ \u00a0\u202f\u2009-]?(?P<scale>(?i:thousands?|millions?|billions?|trillions?|bn)|[kKMx×])(?![\w-]))?"
    rf"(?:[ \u00a0\u202f\u2009-]?(?P<unit>(?i:{_RATE})))?(?![\w])"
)
_GLUED_DIGITS = re.compile(rf"(?<=[^\W\d_]{{2}})(?P<body>{_BODY})(?![\w])(?P<unit>\s?%)?")
_ODD_DIGITS = re.compile(
    rf"(?<![\w.]){_SIGN}?(?:0[xX][0-9a-fA-F]+(?!\w)|\d+(?:_\d+)+(?!\w)|"
    rf"\d+(?:[.,]\d+)?[{_SUPERSCRIPTS}]+|\d*[¼-¾⅐-⅟↉]|(?:\d+(?:[.,]\d+)?|\.\d+)[^\W\d_]\w*)"
)
_ORDINAL = re.compile(r"\d+(?:st|nd|rd|th)", re.IGNORECASE)
_RANGE_DASH = re.compile(r"\d[ \u00a0\u202f\u2009]*$")
_EXEMPT_BEFORE = re.compile(
    r"(?:\b(?:revisions?|rev\.?|steps?|pauses?|proposal|request|req-|expected-revision|"
    r"section|row|exit(?: code| status)?|exited with(?: code)?)|(?<!\w)(?:p_|§))\s*[#:=]?\s*$",
    re.IGNORECASE,
)
_EXEMPT_SPANS = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"
    r"|^\s*(?:#{1,6}\s+)?\d+[.)](?=\s)"
    r"|\brevision\s*[#:=]?\s*\d+(?:\s*(?:instead of|rather than|not|vs\.?|versus|to|->|→)"
    r"\s*(?:revision\s*)?\d+(?![.,]\d))+"
    r"|\brevisions\s*\d+(?:\s*(?:,|and|or|to|-|–)\s*\d+(?![.,]\d))+"
    r"|\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{8,}\b",
    re.IGNORECASE | re.MULTILINE,
)
_RULE_IDENTIFIER = re.compile(r"\b(?:threshold|capacity|share)\s*:\s*$", re.IGNORECASE)
_RESULT_ID_LEAD = re.compile(r"\b(?:results?(?:[ _-]?ids?)?|rids?|ids?|executions?(?:[ _-]?ids?)?)\s*[#:=]?\s*[`(\[]?\s*$", re.IGNORECASE)

_SMALL = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
)
_TENS = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_CARDINALS = {word: value for value, word in enumerate(_SMALL)}
for _value, _word in enumerate(_TENS, 2):
    _CARDINALS[_word] = _value * 10
    for _unit, _suffix in enumerate(_SMALL[1:10], 1):
        _CARDINALS[f"{_word}-{_suffix}"] = _CARDINALS[f"{_word} {_suffix}"] = _value * 10 + _unit
_CARDINALS.update({"hundred": 100, "a hundred": 100, "one hundred": 100, "dozen": 12, "a dozen": 12})
_FRACTIONS = {"half": 2, "halves": 2, "third": 3, "thirds": 3, "quarter": 4, "quarters": 4, "fifth": 5, "fifths": 5, "tenth": 10, "tenths": 10}
_COUNT_NOUNS = (
    "calls", "clients", "customers", "people", "persons", "contacts", "rows", "observations",
    "records", "columns", "features", "variables", "subscribers", "subscriptions", "members",
    "positives", "negatives", "cases", "renewals", "buyers", "accounts", "samples", "folds", "times",
    "percentage points", "percent", "per cent",
)
_FRACTION_BLOCKERS = {"first", "second", "last", "other", "next"}


def _alternatives(words: Iterable[str]) -> str:
    return "|".join(re.escape(word) for word in sorted(words, key=lambda word: (-len(word), word)))


_CARD = _alternatives(_CARDINALS)
_WORD = r"[^\W\d_][\w'’-]*"
_WORD_START = r"(?<![\w-])"
_WORD_END = r"(?![\w-])"
_WORD_RATIOS = re.compile(rf"{_WORD_START}(?P<numerator>{_CARD})(?:\s+{_WORD})?\s+(?:in|out of)\s+(?P<denominator>{_CARD}){_WORD_END}", re.IGNORECASE)
_WORD_DOZENS = re.compile(rf"{_WORD_START}(?:(?P<count>{_CARD}|a)\s+)?dozens?{_WORD_END}", re.IGNORECASE)
_WORD_SCALES = re.compile(
    rf"{_WORD_START}(?:(?:{_CARD}|a|an)\s+)(?:hundreds?|thousands?|millions?|billions?|trillions?)"
    rf"(?:[\s-]+(?:and\s+)?(?:{_CARD}|hundreds?|thousands?|millions?|billions?|trillions?))*{_WORD_END}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Number:
    start: int
    end: int
    value: Decimal | None
    tolerance: Decimal = Decimal("0.5")
    points: bool = False
    ratio: tuple[int, int] | None = None

    def matches(self, value: Decimal) -> bool:
        if self.value is None:
            return False
        if self.ratio:
            numerator, denominator = self.ratio
            return 0 < value <= 1 and round(numerator / value) == denominator
        return abs(value - self.value) <= self.tolerance


def _digit_number(text: str, match: re.Match) -> _Number:
    parts = match.groupdict()
    start, end = match.span()
    body = parts["body"]
    if _COMMA_GROUP.fullmatch(body):
        body = body.replace(",", "")
    else:
        body = re.sub(_SPACE, "", body).replace(",", ".")
    mantissa = Decimal(body)
    exponent = parts.get("exponent") or parts.get("power")
    if parts.get("superscript"):
        exponent = parts["superscript"].translate(_SUPERSCRIPT)
    if exponent:
        power = _EXPONENT.fullmatch(exponent)
        if not power:
            return _Number(start, end, None)
        digits = power["digits"].lstrip("0")
        if len(digits) > 3:
            return _Number(start, end, None)
        scale = int(digits or "0")
        if scale > 300:
            return _Number(start, end, None)
        if power["sign"] in {"-", "−"}:
            scale = -scale
    else:
        suffix = parts.get("scale") or "x"
        scale = _SCALE[suffix if suffix in _SCALE else suffix.lower().removesuffix("s")]
    sign = parts.get("sign")
    if sign == "–" and _RANGE_DASH.search(text[max(0, start - 16):start]):
        start = match.start("body")
    elif sign in {"-", "−", "–"}:
        mantissa = mantissa.copy_negate()
    unit = (parts.get("unit") or "").strip().lower()
    points = bool(re.fullmatch(_POINTS, unit))
    if unit in {"‰", "per mille", "per mil", "permille"}:
        scale -= 3
    elif unit:
        scale -= 2

    sign, digits, exponent = mantissa.as_tuple()
    quantum = exponent + scale
    if abs(quantum) > 300:
        return _Number(start, end, None)
    number = Decimal((sign, digits, quantum))
    return _Number(start, end, number, Decimal((0, (5,), quantum - 1)), points)


def _word_numbers(text: str, units: Iterable[str]) -> Iterable[_Number]:
    nouns = tuple(dict.fromkeys([*_COUNT_NOUNS, *(item.lower() for item in units if item)]))
    noun = _alternatives(nouns)
    counts = re.compile(rf"{_WORD_START}(?P<count>{_CARD}){_WORD_END}(?:\s+(?P<modifier>{_WORD}))?\s+(?P<noun>{noun})(?!\w)", re.IGNORECASE)
    fractions = re.compile(
        rf"{_WORD_START}(?:(?P<count>{_CARD}|a|an)\s+)?(?P<denominator>{_alternatives(_FRACTIONS)}){_WORD_END}"
        rf"(?=\s+(?:of|the|{noun})\b)",
        re.IGNORECASE,
    )
    for match in _WORD_SCALES.finditer(text):
        phrase = match[0].lower()
        if phrase not in _CARDINALS and (counts.match(text, match.start()) or re.match(rf"\s+(?:{_WORD}\s+)?(?:{noun})(?!\w)", text[match.end():], re.IGNORECASE)):
            yield _Number(*match.span(), None)
    for match in _WORD_RATIOS.finditer(text):
        numerator = _CARDINALS[match["numerator"].lower()]
        denominator = _CARDINALS[match["denominator"].lower()]
        if 0 < numerator <= denominator:
            yield _Number(*match.span(), Decimal(numerator) / denominator, ratio=(numerator, denominator))
    for match in fractions.finditer(text):
        before = text[max(0, match.start() - 12):match.start()].lower().split()
        if before and before[-1] in _FRACTION_BLOCKERS:
            continue
        numerator = _CARDINALS.get((match["count"] or "").lower(), 1)
        denominator = _FRACTIONS[match["denominator"].lower()]
        if 0 < numerator <= denominator:
            yield _Number(*match.span(), Decimal(numerator) / denominator, Decimal("0.02"))
    for match in _WORD_DOZENS.finditer(text):
        if match["count"] or match[0].lower() == "dozen":
            count = _CARDINALS.get((match["count"] or "").lower(), 1)
            yield _Number(*match.span(), Decimal(count * 12))
    for match in counts.finditer(text):
        word = match["count"].lower()
        modifier = (match["modifier"] or "").lower()
        if word == "one" or modifier in {"of", "in", "hundred"} or modifier in _CARDINALS:
            continue
        count = Decimal(_CARDINALS[word])
        noun = match["noun"].lower()
        if not modifier and noun in {"percent", "per cent", "percentage points"}:
            yield _Number(*match.span(), count.scaleb(-2), Decimal("0.005"), noun == "percentage points")
        else:
            yield _Number(*match.span("count"), count)


def _numbers(text: str, units: Iterable[str]) -> Iterable[_Number]:
    masked = _EXEMPT_SPANS.sub(lambda match: " " * len(match[0]), text)
    candidates = [
        *(_digit_number(masked, match) for match in _DIGITS.finditer(masked)),
        *(_digit_number(masked, match) for match in _GLUED_DIGITS.finditer(masked)),
        *(_Number(*match.span(), None) for match in _ODD_DIGITS.finditer(masked) if not _ORDINAL.fullmatch(match[0])),
        *_word_numbers(masked, units),
    ]
    end = 0
    for token in sorted(candidates, key=lambda item: (item.start, -item.end)):
        if token.start < end:
            continue
        end = token.end
        prefix = masked[max(0, token.start - 40):token.start]
        shown = text[token.start:token.end]
        if _EXEMPT_BEFORE.search(prefix) or _RULE_IDENTIFIER.search(prefix):
            continue
        if shown.isdigit() and len(shown) >= 6 and _RESULT_ID_LEAD.search(prefix):
            continue
        yield token


def _decimal_values(values: Iterable[int | float]) -> set[Decimal]:
    numbers = (Decimal(str(value)) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool))
    return {value for value in numbers if value.is_finite()}


def findings(
    text: str,
    values: Iterable[int | float],
    *,
    user_text: str = "",
    differences: Iterable[int | float] = (),
    units: Iterable[str] = (),
) -> list[dict]:
    """Report every quantitative occurrence that cannot be traced at its shown precision."""
    units = tuple(units)
    supplied = {token.value for token in _numbers(user_text, units) if token.value is not None}
    recorded = _decimal_values(values) | supplied
    differences = _decimal_values(differences) | supplied
    output = []
    for token in _numbers(text, units):
        if any(token.matches(value) for value in (differences if token.points else recorded)):
            continue
        shown = text[token.start:token.end]
        output.append({
            "code": "untraceable_number",
            "number": shown,
            "start": token.start,
            "end": token.end,
            "message": f'"{shown}" is not supported at this precision by the Study reads or the user text.',
        })
    return output
