"""Fill legacy English templates with text and values cited to Study records."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Literal, TypedDict


FORMATS = ("int", "pct0", "pct1", "pct2", "f1", "f2", "f3", "f4", "auto", "pts0", "pts1", "pts2")
_PATH_SEGMENT = re.compile(r"\[([^\]]+)\]|([^.\[\]]+)")
_TOKEN = re.compile(r"\{\{(r|slot|fact):([^{}|]+?)(?:\|([^{}]*))?\}\}|(?<!\{)\{([A-Za-z_]\w*)\}(?!\})")


class Unavailable(Enum):
    """The two legacy readings for a value the resolver cannot cite."""

    MISSING = "Not executed yet."
    STALE = "Stale, not cited."


@dataclass(frozen=True)
class CitedValue:
    """A value authorized by the resolver, with its path in the cited record."""

    value: int | float
    path: str
    record_id: str
    format: str = "auto"


class TextSegment(TypedDict):
    text: str


class CitedSegment(TextSegment):
    value: int | float
    path: str
    record_id: str
    format: str


Segment = TextSegment | CitedSegment
ReferenceKind = Literal["slot", "r"]
Resolver = Callable[[ReferenceKind, str, str], CitedValue | Unavailable]
NamedValue = str | CitedValue | Unavailable


def parse_path(path: str) -> list[str]:
    """Split a legacy dotted path, keeping bracketed keys as single segments."""
    if not isinstance(path, str) or not path:
        raise ValueError("A cited number needs a value path.")
    segments = []
    end = 0
    for match in _PATH_SEGMENT.finditer(path):
        if match.start() != end and path[end:match.start()] != ".":
            raise ValueError(f"Malformed value path {path!r}.")
        segments.append(match[1] if match[1] is not None else match[2])
        end = match.end()
    if end != len(path) or not segments:
        raise ValueError(f"Malformed value path {path!r}.")
    return segments


def fmt_number(value: int | float, fmt: str = "auto") -> str:
    """Format a finite number with the legacy English formats."""
    if fmt not in FORMATS:
        raise ValueError(f"Unknown number format {fmt!r}.")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (
        isinstance(value, float) and not math.isfinite(value)
    ):
        raise ValueError("A cited value must be a finite number.")
    if fmt == "int":
        return f"{round(value):,}"
    if fmt.startswith("pct"):
        return f"{100 * value:.{int(fmt[3:])}f}%"
    if fmt.startswith("pts"):
        return f"{100 * value:.{int(fmt[3:])}f}"
    if fmt.startswith("f"):
        return f"{value:.{int(fmt[1:])}f}"
    if isinstance(value, int) or value.is_integer():
        return f"{int(value):,}"
    if abs(value) >= 100:
        return f"{value:,.1f}"
    if abs(value) >= 1:
        return f"{value:.2f}"
    return f"{value:.3f}"


def _reference(kind: ReferenceKind, raw: str, slots: Collection[str]) -> tuple[str, str]:
    if kind == "slot":
        # A legacy slot can itself include a colon, as in eda.rate_by:origin.
        slot = max((slot for slot in slots if raw.startswith(slot + ":")), key=len, default="")
        key, _, path = raw.partition(slot + ":" if slot else ":")
        if slot:
            key = slot
    else:
        key, _, path = raw.partition(".")
    if not key:
        raise ValueError(f"A cited number needs a {kind} identifier.")
    parse_path(path)
    return key, path


def _append_text(segments: list[Segment], text: str) -> None:
    if text:
        if segments and "record_id" not in segments[-1]:
            segments[-1]["text"] += text
        else:
            segments.append({"text": text})


def fill(
    template: str,
    resolver: Resolver,
    *,
    slots: Collection[str] = (),
    facts: Mapping[str, str] | None = None,
    values: Mapping[str, NamedValue] | None = None,
) -> list[Segment]:
    """Fill a template via the caller's eligible records, without reading a Study.

    The resolver receives the token kind, legacy identifier and legacy path.
    A cited segment uses the path and record ID the resolver supplies. Known
    slot names disambiguate colons in the legacy grammar. An unavailable value
    replaces the entire text with the first such value's message in template order.
    """
    facts = facts if facts is not None else {}
    values = values if values is not None else {}
    segments: list[Segment] = []
    end = 0
    for match in _TOKEN.finditer(template):
        _append_text(segments, template[end:match.start()])
        end = match.end()
        kind, raw, argument, name = match.groups()
        if kind == "fact":
            _append_text(segments, facts.get(raw.strip(), argument or ""))
            continue
        if name is not None:
            resolved = values.get(name, Unavailable.MISSING)
            format_override = None
        else:
            key, path = _reference(kind, raw.strip(), slots)
            resolved = resolver(kind, key, path)
            format_override = argument or "auto"
        if isinstance(resolved, Unavailable):
            return [{"text": resolved.value}]
        if isinstance(resolved, str):
            _append_text(segments, resolved)
        else:
            if not resolved.record_id or not resolved.path:
                raise ValueError("A cited value needs a record ID and path.")
            fmt = format_override or resolved.format
            segments.append({"text": fmt_number(resolved.value, fmt), "value": resolved.value,
                             "path": resolved.path, "record_id": resolved.record_id, "format": fmt})
    _append_text(segments, template[end:])
    return segments
