"""The table `checks-before-the-lock` of handbook chapter 04, read by name: one parser for every test that compares it with the code.

A row of the body is a `<tr>` with the attributes `data-command` (the check's name in the probe's table), `data-exit` and `data-code`,
in any order. A row that lacks one of them, or whose exit is not an integer, or that repeats a check, is an error of the table, not a row to skip.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

CHAPTER_04 = Path(__file__).resolve().parent.parent / "docs" / "handbook" / "chapters" / "04-study-and-attempts.html"
TABLE_ID = "checks-before-the-lock"
ATTRIBUTES = ("data-command", "data-exit", "data-code")


class _Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found, self.rows, self.errors = False, [], []
        self._inside, self._body = False, False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "table" and attributes.get("id") == TABLE_ID:
            self.found, self._inside = True, True
        elif self._inside and tag == "tbody":
            self._body = True
        elif self._inside and self._body and tag == "tr":
            missing = [name for name in ATTRIBUTES if attributes.get(name) is None]
            if missing or not re.fullmatch(r"\d+", attributes["data-exit"]):
                self.errors.append(f"line {self.getpos()[0]}: a row of the table `{TABLE_ID}` cannot be read ({missing or 'data-exit is not an integer'}): {attributes}")
            else:
                self.rows.append((attributes["data-command"], int(attributes["data-exit"]), attributes["data-code"]))

    def handle_endtag(self, tag):
        if tag == "table" and self._inside:
            self._inside = self._body = False
        elif tag == "tbody":
            self._body = False


def rows_of(text: str) -> dict:
    """{check: (exit code, error code)} of the table `checks-before-the-lock` in `text`."""
    parser = _Rows()
    parser.feed(text)
    assert parser.found, f"no table `{TABLE_ID}`"
    assert not parser.errors, parser.errors
    checks = [check for check, _, _ in parser.rows]
    assert len(checks) == len(set(checks)), f"a check appears twice in the table `{TABLE_ID}`: {sorted(c for c in set(checks) if checks.count(c) > 1)}"
    return {check: (exit_code, code) for check, exit_code, code in parser.rows}


def rows_of_chapter_04() -> dict:
    return rows_of(CHAPTER_04.read_text(encoding="utf-8"))
