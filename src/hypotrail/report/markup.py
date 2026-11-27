"""The page's building blocks: HTML that cannot be written by accident (chadlis/hypotrail#85).

Every value goes through `cell`, which HTML-escapes anything that is not already `Safe` (a fragment this package built
itself), in text and in attributes. A string that comes from outside the code is never turned into a link or a
resource: the only `href` is a relative path to a Study artifact (`Links`).
"""

import html
import json
import math
import os
import urllib.parse
from pathlib import Path

UNKNOWN = "unknown"


class Safe(str):
    """A fragment of HTML this module built itself: not escaped again."""


def esc(value) -> Safe:
    return Safe(html.escape(str(value), quote=True))


def cell(value) -> Safe:
    """A value as HTML: a `Safe` fragment as it is, anything else escaped."""
    return value if isinstance(value, Safe) else esc(value)


def tag(name: str, content="", **attributes) -> Safe:
    attrs = "".join(f' {key.rstrip("_").replace("_", "-")}="{esc(value)}"' for key, value in attributes.items())
    return Safe(f"<{name}{attrs}>{cell(content)}</{name}>")


def join(fragments) -> Safe:
    return Safe("".join(cell(f) for f in fragments))


def number(value, digits=6) -> Safe:
    """A number, or `unknown` for a null and for a value that is not a finite number: never 0, never NaN."""
    if value is None:
        return esc(UNKNOWN)
    if isinstance(value, int) and not isinstance(value, bool):
        return esc(str(value))
    if isinstance(value, float) and math.isfinite(value):
        return esc(format(value, f".{digits}g"))
    return esc(UNKNOWN)


INTERVAL_REASONS = {
    "resampling_not_declared": "no interval: the Workload of the Study's revision declares no resampling",
    "series_not_contiguous": "no interval: the population lists fewer days than its Partition, so the days are not one series",
    "too_few_units": "no interval: fewer than two units",
    "no_usable_resamples": "no interval",
}
INTERVAL_UNITS = {"case": "Cases", "item": "Items", "group": "groups", "entity": "entities"}


def interval(record: dict) -> Safe:
    """The interval of a Comparison: its bounds, level, unit with its count and blocks; "withheld" for a withheld delta; else why none."""
    entry = record.get("interval")
    if entry is None:
        return esc("no interval was recorded (a Comparison written before the interval)")
    if entry["reason"] == "delta_withheld":
        return esc("withheld")
    if entry["lower"] is None:
        parts = [INTERVAL_REASONS[entry["reason"]]]
    else:
        parts = [number(entry["lower"]), " to ", number(entry["upper"]), f", level {entry['level']:g}, over {entry['units']} {INTERVAL_UNITS[entry['unit']]}"]
        if entry["block_length"] is not None:
            parts.append(f", {entry['variant']} blocks of {entry['block_length']} days")
    if entry["unit"] == "entity":
        parts.append(f", {entry['usable_resamples']}/{entry['resamples']} usable draws, {entry['omitted_dates']} date omissions")
    return join(parts)


class Row(list):
    """A table row whose `<tr>` carries attributes: `Row(cells, data_attempt_id=...)`."""

    def __init__(self, cells=(), **attributes):
        super().__init__(cells)
        self.attributes = attributes


def table(table_id: str, headers, rows, *, numeric=()) -> Safe:
    head = join(tag("th", h) for h in headers)
    body = join(
        tag("tr", join(tag("td", c, class_="num") if i in numeric else tag("td", c) for i, c in enumerate(row)), **getattr(row, "attributes", {}))
        for row in rows
    )
    return tag("div", tag("table", join([tag("thead", tag("tr", head)), tag("tbody", body)]), id=table_id, class_="tbl"), class_="tblwrap")


def paragraph(text) -> Safe:
    return tag("p", text)


def sub(text) -> Safe:
    return tag("p", text, class_="sub2")


class Links:
    """Relative links from the page to Study artifacts, written from the directory of `--out`."""

    def __init__(self, study: Path, out: Path):
        self.study = Path(study).resolve()
        self.base = Path(out).resolve().parent

    def href(self, relative: str) -> str:
        link = urllib.parse.quote(Path(os.path.relpath(self.study / relative, self.base)).as_posix())
        return link if link.startswith("..") else f"./{link}"

    def artifact(self, ref: dict) -> Safe:
        return tag("a", ref["path"], href=self.href(ref["path"]))

    def file(self, relative: str, label=None) -> Safe:
        return tag("a", label or relative, href=self.href(relative))


def json_block(value) -> Safe:
    return tag("pre", json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False), class_="code")


def json_text(value) -> Safe:
    """A JSON value on one line, as `<code>` text."""
    return tag("code", json.dumps(value, sort_keys=True, ensure_ascii=False))


def scoped(manifest: dict, content, scenario_mode: str):
    """`content` marked as the page's writing for the Attempt of `manifest` when the Attempt is a scenario Attempt."""
    if manifest["mode"] != scenario_mode:
        return content
    return tag("div", content, data_attempt_id=manifest["attempt_id"])


def rescoring_note(rescoring: dict) -> Safe:
    """The note an Assessment under a corrected References set (or a changed Scorer) carries: the earlier Assessment, the recorded cause."""
    return tag(
        "div",
        join(
            [
                tag("b", "Differs from an earlier Assessment. "),
                f"This Assessment follows Assessment {rescoring['earlier_assessment_id']}, which stays shown above or below, unchanged. ",
                f"Recorded cause: {rescoring['cause']}",
                f" (also changed: {', '.join(rescoring['other_changes'])})" if rescoring.get("other_changes") else "",
                f". Criteria whose verdict changed: {len(rescoring['changed_items'])}.",
            ]
        ),
        class_="note",
    )
