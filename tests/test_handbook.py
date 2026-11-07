"""Ticket #21: the handbook builds from chapter sources and its first chapter is true."""

import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from html.parser import HTMLParser
from pathlib import Path

import pytest

from hypotrail.core.errors import InvalidInputError

ROOT = Path(__file__).resolve().parent.parent
HANDBOOK = ROOT / "docs" / "handbook"
BUILT = HANDBOOK / "handbook.html"
RUN = json.loads((HANDBOOK / "traces" / "live-spike" / "run.json").read_text())


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    out = tmp_path_factory.mktemp("handbook") / "handbook.html"
    # the build script is run with the standard library only (isolated mode)
    result = subprocess.run(
        [sys.executable, "-I", str(HANDBOOK / "build.py"), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return out.read_text(encoding="utf-8")


class Cells(HTMLParser):
    """Collects the text of every element carrying one of the data attributes we read."""

    def __init__(self):
        super().__init__()
        self.stack, self.tables, self.links = [], {}, []
        self._table = self._row = self._cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])
        if tag == "table":
            self._table = self.tables.setdefault(attrs.get("id", f"t{len(self.tables)}"), [])
        elif tag == "tr" and self._table is not None:
            self._row = {"attrs": attrs, "cells": []}
            self._table.append(self._row)
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {"attrs": attrs, "text": ""}
            self._row["cells"].append(self._cell)

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._cell = None
        elif tag == "tr":
            self._row = None
        elif tag == "table":
            self._table = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data


def parse(page):
    cells = Cells()
    cells.feed(page)
    return cells


# --- build ------------------------------------------------------------------------------------------


def test_the_handbook_builds_with_only_the_standard_library_into_one_page(page):
    assert page.startswith("<!doctype html>")
    assert page.count("<html") == 1
    for placeholder in ("{{TITLE}}", "{{TOC}}", "{{SECTIONS}}"):
        assert placeholder not in page
    assert 'id="feasibility-spike"' in page and 'href="#feasibility-spike"' in page


def test_the_page_loads_no_external_resource(page):
    assert not re.search(r"https?:", page)
    assert not re.search(r"""(?:src|href|action|poster|data)\s*=\s*["']\s*//""", page)
    assert not re.search(r"""url\(\s*["']?\s*(?:https?:)?//""", page)
    assert "@import" not in page
    assert not re.search(r"<link\b[^>]*\brel\s*=\s*[\"']?(?:stylesheet|preconnect|preload)", page)
    for src in re.findall(r"<(?:script|img|iframe|source|audio|video)\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)", page):
        assert not src.startswith(("http", "//")), src


def test_the_page_opens_in_light_mode_for_every_viewer(page):
    assert re.search(r"<html\b[^>]*\bdata-mode=\"light\"", page)
    assert "prefers-color-scheme" not in page
    # the initial script only honours an explicit ?mode= or a mode the reader stored
    head_script = re.search(r"<script>\(function\(\)\{var q=.*?</script>", page, re.S).group(0)
    assert 'getAttribute("data-mode")==="light"?"light":"dark"' in head_script
    # a toggle exists for the reader
    assert 'data-m="dark"' in page and 'data-m="light"' in page


def test_the_committed_handbook_is_the_current_build(page):
    assert BUILT.read_text(encoding="utf-8") == page


def test_the_build_refuses_a_chapter_without_its_header(tmp_path):
    spec = importlib.util.spec_from_file_location("handbook_build", HANDBOOK / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "01-bad.html").write_text("<p>no header</p>")
    with pytest.raises(SystemExit, match="first line"):
        module.build(tmp_path)


# --- the chapter ----------------------------------------------------------------------------------------


def test_the_chapter_is_in_english_links_adr_0001_and_does_not_teach(page):
    assert '<html lang="en"' in page
    cells = parse(page)
    adr = [link for link in cells.links if link.endswith("0001-core-independent-of-inspect.md")]
    assert adr, "ADR 0001 is not linked"
    assert (HANDBOOK / adr[0]).resolve().is_file()
    # the Inspect boundary is described next to the link
    assert re.search(r"core never imports Inspect.{0,80}ADR 0001", page, re.S)


def test_every_relative_link_of_the_handbook_resolves():
    for link in parse(BUILT.read_text(encoding="utf-8")).links:
        if link.startswith("#"):
            continue
        assert (HANDBOOK / link).resolve().exists(), link


# --- the environment sheet ------------------------------------------------------------------------------------


def sheet(page):
    out = {}
    for table in parse(page).tables.values():
        for row in table:
            for cell in row["cells"]:
                if "data-sheet" in cell["attrs"]:
                    out[cell["attrs"]["data-sheet"]] = cell["text"].strip()
    return out


def test_the_sheet_versions_equal_the_lock_and_the_interpreter_minor_and_record_sqlite(page):
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    locked = {p["name"]: p["version"] for p in lock["package"]}
    values = sheet(page)
    for name in ("numpy", "scikit-learn", "inspect-ai", "anthropic"):
        assert values[name] == locked[name], name
    # The patch level and the SQLite build belong to the machine that wrote the
    # sheet, not to the repository: only the Python minor is compared, and SQLite
    # is checked to be recorded and well formed.
    v = sys.version_info
    assert values["python"].split(".")[:2] == [str(v.major), str(v.minor)]
    assert re.fullmatch(r"\d+\.\d+\.\d+(\.\d+)?", values["sqlite"]), values["sqlite"]


def test_the_sheet_model_is_the_one_the_live_run_recorded(page):
    values = sheet(page)
    assert values["model"] == RUN["model"] == "anthropic/claude-sonnet-5-5"
    assert values["served-model"] == RUN["served_models"][0]
    assert values["hardware"] == RUN["hardware"]
    assert RUN["engine"]["version"] == values["inspect-ai"]


def test_the_sheet_limits_are_the_effective_values_with_their_state(page):
    """T1'': a two-way check. The non-superseded rows plus the keys that superseded rows name are the current enforcement keys."""
    from hypotrail.agentic.limits import ENFORCEMENT

    rows = table_rows(page, "effective-limits", "data-limit")
    superseded = {limit: row for limit, row in rows.items() if row["cells"]["data-state"] == "superseded"}
    current = set(rows) - set(superseded)
    named = {row["attrs"]["data-replaced-by"] for row in superseded.values()}
    assert current | named == set(ENFORCEMENT)
    assert not current & named  # a replacing key has no row of its own: the superseded row stands for it
    assert superseded, "the spike's 12,000 all-token budget is shown as superseded"
    tests_source = (ROOT / "tests" / "test_limits.py").read_text()

    for limit in current:
        by_attr = rows[limit]["cells"]
        label, witness = ENFORCEMENT[limit]
        assert by_attr["data-effective"] == shown(RUN["effective_limits"][limit]), limit
        assert by_attr["data-state"] == label, limit
        assert f"<code>{witness}</code>" in page, witness
        assert f"def {witness}(" in tests_source

    for limit, row in superseded.items():
        by_attr = row["cells"]
        replacement = row["attrs"]["data-replaced-by"]
        assert by_attr["data-effective"] == shown(RUN["effective_limits"][limit]), limit  # what the spike trace recorded, under its own key
        assert replacement in ENFORCEMENT
        assert f"def {ENFORCEMENT[replacement][1]}(" in tests_source
        text = row["text"]
        assert f"{replacement}" in text and "#50" in text and "chapter 03" in text, limit


def test_the_spike_report_no_longer_lists_the_token_budget_as_shown_enforced(page):
    """T4: check 3 agrees with the amended sheet."""
    check = next(r for r in parse(page).tables["spike-report"] if r["attrs"].get("data-check") == "3")
    outcome = check["cells"][2]["text"]
    assert "Turns, tokens, concurrency" not in outcome
    assert "superseded by #50" in outcome and "chapter 03" in outcome


CHAPTER_03 = HANDBOOK / "chapters" / "03-agentic-track.html"


def table_rows(page, table_id, attribute):
    """The rows of one table keyed by a data attribute of the row, each with its cells' data attributes."""
    rows = {}
    for row in parse(page).tables[table_id]:
        if attribute in row["attrs"]:
            rows[row["attrs"][attribute]] = {
                "attrs": row["attrs"],
                "text": " ".join(c["text"] for c in row["cells"]),
                "cells": {k: c["text"].strip() for c in row["cells"] for k in c["attrs"]},
            }
    return rows


def shown(value):
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def test_the_current_limits_table_equals_the_episode_limits_their_states_and_witnesses(page):
    """R1-S1, R2-S4, R2-P7: the limits in force once, as a table compared with the code; the metering is a column."""
    from hypotrail.agentic.limits import ENFORCEMENT, TOKEN_BUDGET_METERING, EpisodeLimits

    rows = table_rows(page, "current-limits", "data-limit")
    limits = EpisodeLimits().as_dict()
    assert set(rows) == set(limits)
    for limit, row in rows.items():
        label, witness = ENFORCEMENT[limit]
        assert row["cells"]["data-value"] == shown(limits[limit]), limit
        assert row["cells"]["data-state"] == label, limit
        assert row["cells"]["data-witness"] == witness, limit
        witness_file = ROOT / row["cells"]["data-file"]  # the table names the file; the witness is looked for there only
        assert f"def {witness}(" in witness_file.read_text(), (limit, witness)
    # the metering belongs to the budget alone
    assert {limit for limit, row in rows.items() if "data-metering" in row["cells"]} == {"output_token_budget"}
    assert rows["output_token_budget"]["cells"]["data-metering"] == TOKEN_BUDGET_METERING


def test_the_superseded_spike_row_names_a_key_that_has_a_row_in_the_current_limits_table(page):
    superseded = [
        row["attrs"]["data-replaced-by"]
        for row in parse(page).tables["effective-limits"]
        if "data-replaced-by" in row["attrs"]
    ]
    assert superseded
    assert set(superseded) <= set(table_rows(page, "current-limits", "data-limit"))


def test_the_budget_key_table_equals_what_token_budget_fields_returns_or_raises(page):
    """R3-S1, R3-S6: one row per case of the helper, each compared with what it returns or raises."""
    from hypotrail.agentic.limits import TOKEN_BUDGET_KEYS, TOKEN_METERING_UNSUPPORTED, token_budget_fields

    # the arguments (limit, limit type in the log) of each row
    cases = {"output": (1, "output"), "all": (1, None), "none": (None, None), "other": (1, "input")}
    rows = table_rows(page, "token-budget-keys", "data-metering")
    assert set(rows) == set(cases)
    assert {row["cells"]["data-key"] for m, row in rows.items() if m in TOKEN_BUDGET_KEYS} == set(TOKEN_BUDGET_KEYS.values())
    for case, (limit, limit_type) in cases.items():
        cells = rows[case]["cells"]
        if case == "other":
            with pytest.raises(InvalidInputError) as caught:
                token_budget_fields(limit, limit_type)
            assert caught.value.code == cells["data-refusal"] == TOKEN_METERING_UNSUPPORTED
            assert cells["data-key"] == "" and cells["data-recorded"] == ""
            continue
        assert cells["data-refusal"] == ""
        returned = token_budget_fields(limit, limit_type)
        metering = returned.pop("token_budget_metering")
        assert cells["data-recorded"] == ("null" if metering is None else metering), case
        assert list(returned) == ([cells["data-key"]] if cells["data-key"] else []), case
        if metering is not None:
            assert cells["data-key"] == TOKEN_BUDGET_KEYS[metering], case


def test_the_kept_logs_record_the_all_token_budget_under_the_earlier_key(page):
    """R3-P4: the kept run.json files say total_tokens; a re-summary of their logs gives total_token_budget, as chapter 03 says."""
    from hypotrail.agentic.limits import TOKEN_BUDGET_KEYS, ALL_METERING

    for name in ("live-l12-plain", "live-l12-verify"):
        kept = json.loads((HANDBOOK / "traces" / name / "run.json").read_text())
        assert kept["effective_limits"]["total_tokens"] == 12000, name
    assert TOKEN_BUDGET_KEYS[ALL_METERING] == "total_token_budget"
    assert "under the earlier key <code>total_tokens</code>" in page and "<code>total_token_budget</code>" in page


def test_chapter_03_names_the_output_budget_by_its_metering_and_points_to_its_row(page):
    """Criterion 7, read with the table rule: the limit-stop row and the live-command text carry the metering and a link to the row."""
    link = 'href="#limit-output_token_budget"'
    assert 'id="limit-output_token_budget"' in page
    live_text = next(p for p in re.findall(r"<p>.*?</p>", page, re.S) if "<code>spike live</code> runs one declared" in p)
    for place in (page[page.index("<tr><td>Turn limit;") :].split("</tr>", 1)[0], live_text):
        assert 'TokenLimit(type="output")' in place and link in place
    for text in (
        "<code>token_limit</code> means that budget, whose value is the row of the table of current limits",
        "input history and the cached tokens resent at every call no longer weigh on the budget",
        "both Attempts were made under the earlier 12,000 all-token budget",
    ):
        assert text in page, text
    assert "Turn limit, total token budget" not in page
    # the prose around the table does not restate the value
    assert "4,000" not in CHAPTER_03.read_text(encoding="utf-8")


def test_the_reason_table_equals_the_codes_of_a_null_uses_tool_result(page):
    from hypotrail.agentic import live

    rows = table_rows(page, "uses-tool-result-reasons", "data-reason")
    assert set(rows) == {live.NO_FINAL_ANSWER, live.NO_TOOL_RESULT, live.ANSWER_UNREADABLE}
    chapter = CHAPTER_03.read_text(encoding="utf-8")
    assert "<code>uses_tool_result_reason</code>" in chapter


# --- the report -----------------------------------------------------------------------------------------------------


def test_the_report_has_the_six_checks_the_live_line_and_existing_witnesses(page):
    table = parse(page).tables["spike-report"]
    rows = {r["attrs"]["data-check"]: r for r in table if "data-check" in r["attrs"]}
    assert set(rows) == {"1", "2", "3", "4", "5", "6", "live"}
    for key, row in rows.items():
        outcome = row["cells"][2]["text"].strip()
        assert outcome, key
    assert "Not run: no adapter built" in rows["6"]["cells"][2]["text"]

    witnesses = re.findall(r"tests/(test_\w+\.py)::(test_\w+)", page)
    assert len(witnesses) >= 5
    for filename, name in witnesses:
        assert f"def {name}(" in (ROOT / "tests" / filename).read_text(), (filename, name)

    live = rows["live"]["cells"][2]["text"]
    if RUN["tool_loop_observed"]:
        assert "LIVE_NOT_VALIDATED" not in live
        assert RUN["model"] in live
    else:
        assert "LIVE_NOT_VALIDATED" in live


# --- ticket #51: the allow-list is a table compared with the code --------------------------------------------


def test_the_allow_list_table_equals_the_allowed_functions_and_no_other_chapter_lists_them(page):
    from hypotrail.agentic.sql_tool import ALLOWED_FUNCTIONS

    assert set(table_rows(page, "sql-allow-list", "data-function")) == set(ALLOWED_FUNCTIONS)
    chapter = CHAPTER_03.read_text(encoding="utf-8")
    statement = chapter[chapter.index("<b>Allowed:</b>") :].split("</li>", 1)[0]
    assert "#51" in statement and "AG-03" in statement
    for path in sorted((HANDBOOK / "chapters").glob("*.html")):
        text = path.read_text(encoding="utf-8")
        assert "eleven functions" not in text, path.name
        if path != CHAPTER_03:
            # chapter 01 points to chapter 03 instead of listing the functions
            assert not all(f"<code>{name}</code>" in text for name in ALLOWED_FUNCTIONS), path.name
    assert "eleven functions" not in BUILT.read_text(encoding="utf-8")


def test_the_agentic_chapter_describes_the_five_token_fields_of_the_run_record(page):
    chapter = CHAPTER_03.read_text(encoding="utf-8")
    from hypotrail.agentic.live import TOKEN_FIELDS

    for field in TOKEN_FIELDS:
        assert f"<code>{field}</code>" in chapter, field
    assert "includes the provider's cache reads and writes" in chapter or "include the provider's cache reads and writes" in chapter
    assert "an all-token limit is checked against" in chapter
    assert "so a 0 there may not be the provider's count" in chapter
    assert "not a cost" in chapter
    assert "before the record kept the cache figures" in chapter and "15,736" in chapter
    assert "15,736" in page
