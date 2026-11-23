"""Ticket #21: the handbook builds from chapter sources and its first chapter is true."""

import argparse
import ast
import html
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tomllib
import unittest.mock
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import pytest
from _checks_table import rows_of as rows_of_checks_table
from inspect_ai.log import read_eval_log, write_eval_log

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


def test_the_sheet_model_is_the_one_the_live_execution_recorded(page):
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

    for limit in current:
        by_attr = rows[limit]["cells"]
        label, witness = ENFORCEMENT[limit]
        assert by_attr["data-effective"] == shown(RUN["effective_limits"][limit]), limit
        assert by_attr["data-state"] == label, limit
        assert by_attr["data-witness"] == witness, limit  # the cell itself, compared with the code's witness for this key
        assert defines(by_attr["data-file"], witness), witness

    current_rows = table_rows(page, "current-limits", "data-limit")
    for limit, row in superseded.items():
        by_attr = row["cells"]
        replacement = row["attrs"]["data-replaced-by"]
        assert replacement in current_rows, limit  # the key it names is a current enforcement key with a row
        witness_file = current_rows[replacement]["cells"]["data-file"]
        assert defines(witness_file, ENFORCEMENT[replacement][1]), replacement  # and its witness test exists
        assert by_attr["data-effective"] == shown(RUN["effective_limits"][limit]), limit  # what the spike trace recorded, under its own key
        assert replacement in ENFORCEMENT
        assert "data-file" not in by_attr  # a superseded row claims no witness of its own
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


def defines(path, name):
    """Whether the test file at `path` (relative to the repository) defines a function called `name`."""
    return f"def {name}(" in (ROOT / path).read_text()


def shown(value):
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def test_the_current_limits_table_equals_the_episode_limits_their_states_and_witnesses(page):
    """The limits in force, listed once as a table, equal the code's limits, states and witnesses; the metering is a column."""
    from hypotrail.agentic.limits import ENFORCEMENT, TOKEN_BUDGET_METERING, EpisodeLimits

    rows = table_rows(page, "current-limits", "data-limit")
    limits = EpisodeLimits().as_dict()
    assert set(rows) == set(limits)
    for limit, row in rows.items():
        label, witness = ENFORCEMENT[limit]
        assert row["cells"]["data-value"] == shown(limits[limit]), limit
        assert row["cells"]["data-state"] == label, limit
        assert row["cells"]["data-witness"] == witness, limit
        assert defines(row["cells"]["data-file"], witness), (limit, witness)  # the table names the file
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
    """Each row of the table gives the inputs it covers; the helper is called with them and must return or raise what the row says."""
    from hypotrail.agentic.limits import TOKEN_BUDGET_KEYS, TOKEN_METERING_UNSUPPORTED, token_budget_fields

    def value(text):
        return None if text == "null" else int(text) if text.isdigit() else text

    rows = table_rows(page, "token-budget-keys", "data-metering")
    assert set(rows) == {"output", "all", "none", "other"}
    assert {row["cells"]["data-key"] for m, row in rows.items() if m in TOKEN_BUDGET_KEYS} == set(TOKEN_BUDGET_KEYS.values())
    inputs = {}
    for row in parse(page).tables["token-budget-keys"]:
        if "data-metering" in row["attrs"]:
            first = row["cells"][0]["attrs"]
            inputs[row["attrs"]["data-metering"]] = (value(first["data-limit"]), [value(t) for t in first["data-type"].split()])
    assert set(inputs) == set(rows)
    assert inputs["all"][1] == ["all", None]  # an explicit "all" and a missing type both reach the row
    for case, (limit, limit_types) in inputs.items():
        cells = rows[case]["cells"]
        key, recorded, refusal = (cells.get(k, "") for k in ("data-key", "data-recorded", "data-refusal"))  # absent: none
        for limit_type in limit_types:
            if refusal:
                with pytest.raises(InvalidInputError) as caught:
                    token_budget_fields(limit, limit_type)
                assert caught.value.code == refusal == TOKEN_METERING_UNSUPPORTED
                assert "data-key" not in cells and "data-recorded" not in cells
                continue
            returned = token_budget_fields(limit, limit_type)
            metering = returned.pop("token_budget_metering")
            assert recorded == ("null" if metering is None else metering), (case, limit_type)
            assert list(returned) == ([key] if key else []), (case, limit_type)
            if metering is not None:
                assert key == TOKEN_BUDGET_KEYS[metering], (case, limit_type)


def test_the_kept_logs_record_the_all_token_budget_under_the_earlier_key(page, tmp_path):
    """Both kept run.json files hold the 12,000 budget as total_tokens, requested and effective; a re-summary of each log gives the all-token key of the table, which chapter 03 links."""
    from hypotrail.agentic import live
    from hypotrail.agentic.limits import TOKEN_BUDGET_KEYS

    all_token_key = next(r["cells"]["data-key"] for r in table_rows(page, "token-budget-keys", "data-metering").values() if r["cells"].get("data-recorded") == "all")
    assert all_token_key in TOKEN_BUDGET_KEYS.values()
    for name in ("live-l12-plain", "live-l12-verify"):
        kept = json.loads((HANDBOOK / "traces" / name / "run.json").read_text())
        assert kept["requested_limits"]["total_tokens"] == 12000, name
        assert kept["effective_limits"]["total_tokens"] == 12000, name
        copy = tmp_path / name  # the kept trace is not touched
        shutil.copytree(HANDBOOK / "traces" / name / "inspect", copy / "inspect")
        again = live.summarize(
            location=str(next((copy / "inspect").glob("*.eval"))), out_dir=copy,
            model_id="anthropic/claude-sonnet-5-5", api_key="not-a-key-for-an-offline-summary",
            case_ids=["D03", "D05"], repeats=1,
        )
        assert again["effective_limits"][all_token_key] == 12000, name
        assert again["effective_limits"]["token_budget_metering"] == "all", name
        assert "total_tokens" not in again["effective_limits"], name
    paragraph = next(p for p in re.findall(r"<p>.*?</p>", page, re.S) if "under the earlier key <code>total_tokens</code>" in p)
    assert 'href="#token-budget-keys"' in paragraph and "requested_limits" in paragraph and "effective_limits" in paragraph
    assert f"<code>{all_token_key}</code>" not in paragraph  # the prose points to the row; it does not spell the key


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
        "both directories were made under the earlier 12,000 all-token budget",
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
        assert defines(f"tests/{filename}", name), (filename, name)

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


LIVE_L12B = {
    "live-l12b-plain": {"D03": (361, 10274), "D05": (400, 10501)},
    "live-l12b-verify": {"D03": (384, 10481), "D05": (393, 10631)},
}


def test_the_kept_second_attempts_figures_are_those_of_their_run_json(page):
    """Chapter 03 states each Episode's output and total tokens as the two kept live-l12b run.json files record them, and the null uses_tool_result with its Reason."""
    paragraph = next(p for p in re.findall(r"<p>.*?</p>", page, re.S) if "Four further Episodes were kept on 2026-11-07" in p)
    assert 'href="#current-limits"' in paragraph and "4000" not in paragraph and "4,000" not in paragraph  # the value is the row's
    for name, expected in LIVE_L12B.items():
        kept = json.loads((HANDBOOK / "traces" / name / "run.json").read_text())
        assert f'href="traces/{name}/run.json"' in paragraph and f'href="traces/{name}/projection.json"' in paragraph
        assert (HANDBOOK / "traces" / name / "projection.json").is_file()
        assert kept["model"] == "anthropic/claude-sonnet-5-5"
        assert [(c["case_id"], c["repeat"]) for c in kept["cases"]] == [("D03", 0), ("D05", 0)]
        assert (HANDBOOK / "traces" / name / kept["inspect_log"]).is_file()
        assert f'href="traces/{name}/{kept["inspect_log"]}"' in paragraph
        for episode in kept["episodes"]:
            assert (episode["status"], episode["model_calls"]) == ("produced", 3)
            assert episode["uses_tool_result"] is None and episode["uses_tool_result_reason"] == "answer_unreadable"
            assert (episode["output_tokens"], episode["total_tokens"]) == expected[episode["case_id"]]
        projection = json.loads((HANDBOOK / "traces" / name / "projection.json").read_text())
        for episode in projection:
            steps = episode["steps"]
            assert [s.get("function") or s["kind"] for s in steps if s["kind"] != "tool_result" and s["kind"] != "model_turn"] == ["describe_schema", "query_readonly", "final_answer"], (name, episode["case_id"])
            assert [s["kind"] for s in steps] == ["model_turn", "tool_call", "tool_result", "model_turn", "tool_call", "tool_result", "model_turn", "final_answer"], (name, episode["case_id"])
            results = [s for s in steps if s["kind"] == "tool_result"]
            assert results[1]["result"]["error"] is None and not results[1]["tool_error"], (name, episode["case_id"])
            if episode["case_id"] == "D03":
                sql = next(s["arguments"]["sql"] for s in steps if s.get("function") == "query_readonly")
                assert re.search(r"\bLIKE\b", sql), name
    assert "```json" in paragraph and "limits their <code>run.json</code> records" in paragraph and "under the current limits" not in paragraph
    for out, total in (v for e in LIVE_L12B.values() for v in e.values()):
        assert f"{out} and {total:,}" in paragraph


def test_chapter_03_says_where_requested_limits_come_from_in_each_case(page):
    """#57 T5: the run.json paragraph names request_source's two values as the code writes them, and no longer says the requested limits are read back."""
    from hypotrail.agentic import live

    paragraph = next(p for p in re.findall(r"<p>.*?</p>", page, re.S) if "<code>run.json</code> holds:" in p)
    rows = table_rows(page, "run-request-source", "data-request-source")
    assert set(rows) == {source.value for source in live.RequestSource}
    assert "<code>this_attempt</code>" not in paragraph and "#run-request-source" in paragraph
    # the table sits after the list its sentence introduces: "The cause is one of:" is followed by the reasons
    assert page.index("The cause is one of:") < page.index('id="uses-tool-result-reasons"') < page.index('id="run-request-source"')
    lead_in = page.index("<code>requested_limits</code> comes from")
    assert page.index('id="uses-tool-result-reasons"') < lead_in < page.index('id="run-request-source"')
    assert "<code>request_source</code>" in paragraph and "<code>tool_calls</code> null" in paragraph
    assert "the requested and effective limits read back from the log" not in paragraph
    assert "The effective limits are read back from the log and include the per-query caps" in paragraph


# --- #58: chapter 03's Criteria and wrapped-answer tables are pinned against the Scorer ---------------------------------


def _scorer_inputs():
    from hypotrail.core import chinook_contract

    chinook = ROOT / "examples" / "chinook"
    schema = json.loads((chinook / "schemas" / "table-answer.schema.json").read_text())
    reference = next(
        json.loads(line)
        for line in (chinook / "references" / "chinook-references.jsonl").read_text().splitlines()
        if json.loads(line)["case_id"] == "D03"
    )
    answer = {k: reference[k] for k in ("status", "reason_code", "columns", "rows", "unit")} | {"evidence": []}
    return chinook_contract, schema, reference, answer


def test_the_criteria_table_names_the_scorers_criteria_and_its_evidence_reasons(page):
    chinook_contract = _scorer_inputs()[0]
    rows = table_rows(page, "chinook-criteria", "data-criterion")
    assert tuple(rows) == chinook_contract.CRITERIA
    evidence = rows["evidence_link_valid"]["text"]
    for name in dir(chinook_contract):
        if name.startswith("EVIDENCE_"):
            assert getattr(chinook_contract, name) in evidence, name
    assert chinook_contract.INVALID_RESPONSE_FORMAT in evidence


def test_the_wrapped_answers_table_equals_what_the_scorer_does(page):
    chinook_contract, schema, reference, answer = _scorer_inputs()
    text = json.dumps(answer)
    # one object per kind of off-schema answer: an extra field keeps the six fields, a missing one loses a field
    off_objects = [json.dumps(answer | {"comment": "hi"}), json.dumps({k: v for k, v in answer.items() if k != "unit"})]
    shapes = {
        "exact_object": ["OBJ"],
        "wrapped": ["Voici. OBJ", "OBJ\nFin.", "```json\nOBJ\n```", "[OBJ]"],
        "non_json_wrapper": [
            '{"answer": OBJ, "note": NaN}',
            '{"answer": OBJ, "note": 1e999}',  # #61: a number that decodes to a non-finite float is a failed read too
            '{"answer": OBJ, "note": -1e999}',
            '{"answer": OBJ',
            "x {oops OBJ",
        ],
    }

    def holding(shape, obj):
        return shape.replace("OBJ", obj)

    # (raw answer, the object it holds): the valid object, and each off-schema object for the *_off_schema rows
    samples = {name: [(holding(sh, text), text) for sh in group] for name, group in shapes.items()}
    samples |= {f"{name}_off_schema": [(holding(sh, o), o) for sh in group for o in off_objects] for name, group in shapes.items()}
    samples["nothing_read"] = [
        (raw, None)
        for raw in (
            "The answer is 1297.",
            "1297",
            "[1297]",
            text + text,
            "```json\n" + text + "\n```\n```json\n" + text + "\n```",
            text.replace("1297", "1e999"),  # #61: a bare answer holding a non-finite literal reads nothing
            text.replace("1297", "9" * 4301),  # #61 B3: an integer beyond Python's parse limit reads nothing
        )
    ]
    for name, group in samples.items():
        if name.endswith("_off_schema"):
            # each off-schema row is exercised with an object that keeps the six fields and one that misses a field
            missing = [set(answer) <= set(json.loads(held)) for _, held in group]
            assert True in missing and False in missing, name
    rows = table_rows(page, "chinook-wrapped-answers", "data-answer")
    assert set(rows) == set(samples)
    kept = ("exact_table", "evidence_link_valid")
    for name, row in rows.items():
        attrs = row["attrs"]
        listed = set(attrs["data-false"].split())
        for raw, held in samples[name]:
            result = chinook_contract.score_episode(raw, reference, schema)
            by = {c["name"]: c for c in result["criteria"]}
            falsified = {n for n, c in by.items() if c["state"] == "scored" and c["score"] is False}
            if name == "nothing_read":
                assert listed == set(chinook_contract.CRITERIA) == falsified, raw
                # #61 A3: with the Reference absent or invalid, the Criterion named by data-without-reference is unscored
                # with the Reference's Reason (an Instrument failure), and the others stay false
                unscored = set(attrs["data-without-reference"].split())
                for absent in (None, {}):
                    gone = {c["name"]: c for c in chinook_contract.score_episode(raw, absent, schema)["criteria"]}
                    reason = chinook_contract.reference_problem(absent)
                    assert {n for n, c in gone.items() if c["state"] == "unscored"} == unscored, raw
                    assert all(gone[n]["reason"] == reason for n in unscored), raw
                    assert {n for n, c in gone.items() if c["score"] is False} == set(chinook_contract.CRITERIA) - unscored, raw
            elif not name.endswith("_off_schema"):
                assert falsified == listed, raw
            # the Criteria scored false with invalid_response_format are exactly the row's data-false list, except that
            # exact_table is false with it too exactly when the held object misses a field
            invalid = {n for n in falsified if by[n]["reason"] == chinook_contract.INVALID_RESPONSE_FORMAT}
            misses_a_field = held is not None and not set(answer) <= set(json.loads(held))
            assert invalid == listed | ({"exact_table"} if misses_a_field else set()), raw
            if name == "exact_object_off_schema":
                # an extra field keeps the six fields, so exact_table holds against the right Reference; a missing one fails it
                exact = by["exact_table"]
                if misses_a_field:
                    assert exact["score"] is False and exact["reason"] == chinook_contract.INVALID_RESPONSE_FORMAT, raw
                else:
                    assert exact["score"] is True, raw
            assert str(result["answer_read_from"]).replace("None", "null") == attrs["data-read-from"], raw
            if attrs["data-read-from"] == chinook_contract.READ_FROM_EMBEDDED_OBJECT:
                # "as for that object alone": exact_table and evidence_link_valid are those of the held object scored alone
                alone = {c["name"]: c for c in chinook_contract.score_episode(held, reference, schema)["criteria"]}
                assert [by[n] for n in kept] == [alone[n] for n in kept], raw
    # the three values of answer_read_from are exactly the rows' data-read-from
    assert {r["attrs"]["data-read-from"] for r in rows.values()} == {
        chinook_contract.READ_FROM_RAW_ANSWER,
        chinook_contract.READ_FROM_EMBEDDED_OBJECT,
        "null",
    }


def test_the_scorer_docstring_states_that_a_missing_reference_leaves_exact_table_unscored_when_nothing_is_read():
    """#61 A3 (D-012 on chadlis/hypotrail#75 item 20): the module docstring no longer says every Criterion is false for an answer nothing is read from."""
    doc = " ".join(_scorer_inputs()[0].__doc__.split())
    assert "has every Criterion scored false with this Reason, trace or not." not in doc
    assert "except `exact_table`, which is `unscored` with `reference_missing` or `reference_invalid` when the Reference is absent or unusable" in doc


def test_chapter_03_scores_a_non_json_wrapper_on_its_object_and_a_json_wrapper_as_the_one_object(page):
    """#58 T9'': the Scorer reads a non-JSON wrapper on the object it holds and a JSON wrapper as the one object, and the chapter states the JSON half once."""
    chinook_contract, schema, reference, answer = _scorer_inputs()
    text = json.dumps(answer)

    def exact_table(raw):
        result = chinook_contract.score_episode(raw, reference, schema)
        return result["answer_read_from"], next(c for c in result["criteria"] if c["name"] == "exact_table")["score"]

    assert exact_table('{"answer": ' + text + ', "note": NaN}') == (chinook_contract.READ_FROM_EMBEDDED_OBJECT, True)
    assert exact_table('{"answer": ' + text + ', "note": 1}') == (chinook_contract.READ_FROM_RAW_ANSWER, False)
    assert page.count("is itself the one object, and is judged as such") == 1
    assert "read on the whole wrapper, which lacks the six fields" in page


def test_chapter_03_refuses_a_number_that_decodes_to_a_non_finite_float_like_nan_and_states_the_integer_limit():
    """#61 AC7 (Tightened E), B3 (D-012 on chadlis/hypotrail#75 item 18): the chapter says what the Scorer does for both."""
    chapter = " ".join(re.sub(r"<[^>]+>", "", CHAPTER_03.read_text(encoding="utf-8")).split())
    assert "A number that decodes to a non-finite float, such as 1e999 or -1e999, is refused like NaN" in chapter
    assert "An integer of more than 4,300 digits, which Python refuses to read, leaves the answer unreadable" in chapter


def test_chapter_08_states_the_scorer_version_the_registry_holds():
    chinook_contract = _scorer_inputs()[0]
    chapter = " ".join(re.sub(r"<[^>]+>", "", (HANDBOOK / "chapters" / "08-agent-answers.html").read_text(encoding="utf-8")).split())
    assert f"chinook_contract_v1 at version {chinook_contract.SCORER_VERSION} and its config_digest" in chapter


def test_chapter_05_states_the_scorer_version_the_registry_holds_in_its_prose_too():
    """#61 Tightened E: "every chapter sentence that states the current version gives the new one"; chapter 05's prose said 2."""
    chinook_contract = _scorer_inputs()[0]
    chapter = " ".join(re.sub(r"<[^>]+>", "", (HANDBOOK / "chapters" / "05-assessments.html").read_text(encoding="utf-8")).split())
    assert f"chinook_contract_v1 is the Scorer of the agent Track (version {chinook_contract.SCORER_VERSION})" in chapter


def test_chapter_03_states_the_scorer_version_and_names_answer_read_from():
    chinook_contract = _scorer_inputs()[0]
    chapter = CHAPTER_03.read_text(encoding="utf-8")
    assert f"version is {chinook_contract.SCORER_VERSION}" in chapter
    assert "<code>answer_read_from</code>" in chapter
    for value in (chinook_contract.READ_FROM_RAW_ANSWER, chinook_contract.READ_FROM_EMBEDDED_OBJECT):
        assert f"<code>{value}</code>" in chapter
    assert "unscored</code> with <code>invalid_response_format</code>" not in chapter  # the corrected sentence (T6)


# --- chapter 02: the stage of a refusal at load and of a refusal when a date is shifted (#40, H4) -------------------


def test_the_refusal_stage_table_equals_the_code_and_stage_of_each_refusal(page, tmp_path):
    import copy
    import datetime

    from hypotrail.ml.declaration import load_declaration
    from hypotrail.ml.periods import Period

    bike = ROOT / "examples" / "bike_day"
    declaration = json.loads((bike / "workload.json").read_text(encoding="utf-8"))

    def load_refusal(name, edit):
        edited = copy.deepcopy(declaration)
        edit(edited)
        directory = tmp_path / name
        shutil.copytree(bike, directory)
        (directory / "workload.json").write_text(json.dumps(edited), encoding="utf-8")
        with pytest.raises(InvalidInputError) as caught:
            load_declaration(directory)
        return caught.value

    def rename(d):
        d["partitions"][""] = d["partitions"].pop("public_check")

    with pytest.raises(InvalidInputError) as shift:
        Period(10**6).earlier(datetime.date(2012, 1, 8))
    actual = {
        "load": load_refusal("load", lambda d: d.update(period_k=0)),
        "empty-name": load_refusal("empty", rename),
        "shift": shift.value,
    }
    rows = table_rows(page, "refusal-stages", "data-refusal")
    assert set(rows) == set(actual)
    for name, error in actual.items():
        assert rows[name]["cells"]["data-code"] == error.code, name
        assert rows[name]["cells"]["data-stage"] == error.stage, name
    assert rows["load"]["cells"]["data-stage"] != rows["shift"]["cells"]["data-stage"]


# --- chapter 04: the Study, the Attempt, the records, the request identity and the refusals (#64) -------------------


def attrs_of(page, table_id, attribute):
    """{key: the row's data attributes} of one table."""
    return {key: row["attrs"] for key, row in table_rows(page, table_id, attribute).items()}


def words(text):
    return set(text.split())


JOURNAL_FILE = re.compile(r"^write_journal/[0-9]{6}\.json$")


def generic_journal(path):
    """The write journal's entries are one row of chapter 04's `study-layout`, whatever their position."""
    return "write_journal/SEQ.json" if JOURNAL_FILE.match(path) else path


def without_the_journal(paths):
    """The files of a command, less the write journal's entries: they are listed once, in chapter 04's `study-layout` (chadlis/hypotrail#107)."""
    return {path for path in paths if not JOURNAL_FILE.match(path)}


def test_the_commands_table_equals_the_flags_the_parser_defines(page):
    from hypotrail.cli import build_parser

    parser = build_parser()

    def subparser(parent, name):
        action = next(a for a in parent._actions if getattr(a, "choices", None) and name in a.choices)
        return action.choices[name]

    parsers = {
        "init": subparser(parser, "init"),
        "run ml": subparser(subparser(parser, "run"), "ml"),
        "run agent": subparser(subparser(parser, "run"), "agent"),
        "import ml": subparser(subparser(parser, "import"), "ml"),
        "import agent": subparser(subparser(parser, "import"), "agent"),
        "report": subparser(parser, "report"),
        "status": subparser(parser, "status"),
        "recover": subparser(parser, "recover"),
    }
    rows = attrs_of(page, "study-commands", "data-command")
    assert set(rows) == set(parsers)
    for command, row in rows.items():
        options = {flag: a.required for a in parsers[command]._actions for flag in a.option_strings if flag not in ("-h", "--help")}
        assert words(row["data-required"]) == {flag for flag, required in options.items() if required}, command
        assert words(row["data-optional"]) == {flag for flag, required in options.items() if not required}, command


def test_the_layout_table_equals_the_files_init_and_run_ml_write(page, tmp_path):
    from _study_helpers import init_study, run_ml

    study, _ = init_study(tmp_path)
    after_init = {generic_journal(p.relative_to(study).as_posix()) for p in study.rglob("*") if p.is_file()}
    _, seasonal, _ = run_ml(study, "seasonal_7", "dev", "a")
    _, ridge, _ = run_ml(study, "ridge_v1", "dev", "b")
    ids = {seasonal["attempt"]["attempt_id"], ridge["attempt"]["attempt_id"]}
    everything = {generic_journal(p.relative_to(study).as_posix()) for p in study.rglob("*") if p.is_file()}
    generic = set()
    for path in everything:
        for attempt_id in ids:
            path = path.replace(attempt_id, "ATTEMPT_ID")
        generic.add(path)
    rows = attrs_of(page, "study-layout", "data-path")
    assert set(rows) == generic
    assert {path for path, row in rows.items() if row["data-written-by"].split()[0] == "init"} == after_init
    assert (study / "writer.lock").read_bytes() == b""  # taking the lock writes nothing to the Study


def test_the_status_table_equals_the_keys_status_reports_for_an_attempt(page, tmp_path):
    from _study_helpers import init_study, run_json, run_ml

    study, _ = init_study(tmp_path)
    run_ml(study, "seasonal_7", "dev", "a")
    _, listing, _ = run_json("status", "--study", study)
    (attempt,) = listing["attempts"]
    assert set(attrs_of(page, "status-fields", "data-field")) == set(attempt)
    assert set(attrs_of(page, "status-artifact-fields", "data-field")) == set(attempt["artifacts"][0])
    # `revisions` is chapter 10's; `freeze_records`, `exposures` and `check_informed` are chapter 12's
    assert set(listing) == {"ok", "study", "writer_alive", "revisions", "attempts", "freeze_records", "exposures", "check_informed", "write_sequence", "decisions", "declared_deviations", "assessments", "comparisons", "pending_decisions"}


def test_the_status_keys_table_equals_the_top_level_keys_status_reports_and_names_the_write_sequence(page, tmp_path):
    from _study_helpers import init_study, run_json

    study, _ = init_study(tmp_path)
    _, listing, _ = run_json("status", "--study", study)
    assert set(attrs_of(page, "status-keys", "data-field")) == set(listing) - {"ok"}
    assert "write_sequence" in attrs_of(page, "status-keys", "data-field")  # chadlis/hypotrail#107: the top-level key
    assert "decisions" in attrs_of(page, "status-keys", "data-field")  # chadlis/hypotrail#110: the decision history


def test_the_write_sequence_table_equals_the_commands_that_write_and_what_each_names(page, tmp_path):
    from test_write_sequence import WRITERS, entries, seq

    rows = attrs_of(page, "write-sequence-commands", "data-command")
    assert set(rows) == set(WRITERS)  # every command that writes to a Study, each once
    for number, (command, scenario) in enumerate(WRITERS.items()):
        folder = tmp_path / f"w{number}"
        folder.mkdir()
        study, act = scenario(folder)
        before, kept = seq(study), len(entries(study))
        code, payload, err = act()
        assert code == 0, (command, payload, err)
        assert seq(study) - before == int(rows[command]["data-advances"]), command
        added = entries(study)[kept:]
        assert [e["command"] for e in added] == [command, command]
        assert set(rows[command]["data-written"].split()) <= {item["kind"] for item in added[-1]["written"]}, command


def test_chapter_04_says_where_the_write_sequence_is_kept_what_an_entry_holds_and_the_outcomes_the_code_gives(page):
    from hypotrail.core import write_journal

    chapter = (HANDBOOK / "chapters" / "04-study-and-attempts.html").read_text(encoding="utf-8")
    assert f"<code>{write_journal.JOURNAL_DIR}/SEQ.json</code>" in chapter
    for outcome in (write_journal.COMPLETED, write_journal.REFUSED, write_journal.FAILED):
        assert f"<code>{outcome}</code>" in chapter, outcome
    assert "may gain values" in chapter and "shows <code>write_sequence</code> 0" in chapter
    assert "write_journal/SEQ.json" in attrs_of(page, "study-layout", "data-path")


def test_the_readme_names_the_write_sequence_a_study_keeps():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "write sequence" in readme and "`status`" in readme


def test_the_readme_names_the_read_sequence_option_and_the_refusal_of_a_stale_write():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "--read-sequence" in readme and "STUDY_CHANGED" in readme


def test_the_record_table_equals_the_required_and_optional_fields_of_the_contract_schema(page):
    from hypotrail.core import contracts

    definitions = contracts.schema()["$defs"]
    rows = attrs_of(page, "record-fields", "data-record")
    assert set(rows) == {"StudySpec", "AttemptManifest", "ObservationSet", "ArtifactRef"}
    for name, row in rows.items():
        definition = definitions[name]
        assert words(row["data-required"]) == set(definition["required"]), name
        assert words(row["data-optional"]) == set(definition["properties"]) - set(definition["required"]), name
        assert row["data-kind"] == definition["properties"].get("kind", {}).get("const", ""), name


def test_the_status_table_equals_the_attempt_and_item_statuses_of_the_code(page):
    from hypotrail.core import contracts
    from hypotrail.ml.run import ITEM_STATUSES

    rows = attrs_of(page, "statuses", "data-level")
    definitions = contracts.schema()["$defs"]
    assert words(rows["attempt"]["data-values"]) == set(definitions["AttemptManifest"]["properties"]["technical_status"]["enum"])
    assert words(rows["item"]["data-values"]) == set(ITEM_STATUSES) == set(definitions["ItemCounts"]["properties"])


def test_the_request_identity_table_equals_the_elements_the_code_compares(page):
    from hypotrail.core import requests

    effective = {
        "command": "c", "workload": "w", "configuration": {"id": "i", "declared": {}}, "partition": "p",
        "mode": "native_ml", "input_digests": {}, "effective_parameters": None,
    }
    environment = {"python": "3.13", "code_revision": {"commit": None, "dirty": False, "local_code_fingerprint": None}}
    rows = attrs_of(page, "request-identity", "data-element")
    in_identity = {element for element, row in rows.items() if row["data-in-identity"] == "yes"}
    assert in_identity == set(requests.ELEMENTS) == set(requests.identity(effective, environment))
    base = requests.identity(effective, environment)
    for element in set(rows) - in_identity:  # an element the table says is not in the identity changes nothing
        changed_effective = {**effective, "effective_parameters": {"x": 1}} if element == "effective_parameters" else effective
        changed_environment = {**environment, "python": "3.14"} if element == "python" else environment
        assert requests.differences(base, requests.identity(changed_effective, changed_environment)) == [], element
    assert "retry_of" not in requests.ELEMENTS


def test_the_exit_code_table_equals_the_constants_of_the_errors_module(page):
    from hypotrail.core import errors

    rows = attrs_of(page, "exit-codes", "data-exit")
    assert {row["data-name"]: int(code) for code, row in rows.items()} == {
        name: getattr(errors, name) for name in dir(errors) if name.startswith("EXIT_")
    }


WRITING_COMMANDS = ["init", "run ml", "run agent", "import ml", "import agent", "assess", "compare", "recover", "report", "decide"]


def test_every_writing_command_takes_read_sequence_and_every_table_that_lists_its_flags_says_so(page):
    # #108 Tightened B, E and G: the option is `--read-sequence`; `init` takes it for `--new-revision` only; no other flag is new.
    from hypotrail.cli import build_parser

    def flags(*path):
        node = build_parser()
        for name in path:
            node = next(a for a in node._actions if getattr(a, "choices", None) and name in a.choices).choices[name]
        return {flag for a in node._actions for flag in a.option_strings}

    paths = {c: c.split() for c in WRITING_COMMANDS}
    assert {c for c, path in paths.items() if "--read-sequence" in flags(*path)} == set(WRITING_COMMANDS)
    assert "--read-sequence" not in flags("status")
    assert "--request-id" not in flags("assess") | flags("compare") | flags("recover") | flags("init")
    tables = {"study-commands": [c for c in WRITING_COMMANDS if c not in ("assess", "compare", "decide")], "assess-command": ["assess"], "import-command": ["import ml"], "compare-command": ["compare"], "agent-import-command": ["import agent"]}
    for table, commands in tables.items():
        rows = attrs_of(page, table, "data-command")
        for command in commands:
            assert "--read-sequence" in words(rows[command]["data-optional"]), (table, command)
    assert "--read-sequence" in attrs_of(page, "run-agent-flags", "data-flag")
    # #109 Tightened A: `decide` requires it, and no other command does
    assert "--read-sequence" in words(attrs_of(page, "decide-command", "data-command")["decide"]["data-required"])
    init_row = table_rows(page, "study-commands", "data-command")["init"]["text"]
    assert "--read-sequence" in init_row and "--new-revision" in init_row.split("--read-sequence")[1]


def test_the_status_keys_row_for_write_sequence_counts_one_for_a_writer_killed_between_its_first_and_its_last_write(page, tmp_path):
    # R2-P-02, #107 Tightened B: a killed writer leaves its `begin` entry only
    from _study_helpers import run_json
    from test_run_ml import killed

    study, _ = killed(tmp_path, kill_at=4)
    assert run_json("status", "--study", study)[1]["write_sequence"] == 2 + 1  # `init`'s two entries and the `begin` entry of the killed `run ml`
    row = " ".join(table_rows(page, "status-keys", "data-field")["write_sequence"]["text"].split())
    assert "2 more for every command that writes" in row
    assert "1 more for a writer killed between its first and its last write" in row


def test_the_exit_code_six_meaning_covers_a_study_changed_after_it_was_read(page):
    rows = attrs_of(page, "exit-codes", "data-exit")
    assert "changed" in table_rows(page, "exit-codes", "data-exit")["6"]["text"].lower()
    assert rows["6"]["data-name"] == "EXIT_LOCK_OR_CONFLICT"


def study_refusals(tmp_path):
    """Provoke each refusal of the table; return {code: (exit code, stage, set of details keys)}."""
    from _study_helpers import examples_copy, init_study, run_json, run_ml

    from hypotrail.core import artifacts, canonical, contracts, lock

    found = {}

    def record_cli(code, payload, *_):
        error = payload["error"]
        found[error["code"]] = (code, error["stage"], set(error["details"]))

    def record_raised(call):
        with pytest.raises(Exception) as caught:
            call()
        error = caught.value
        found[error.code] = (error.exit_code, error.stage, set(error.details))

    study, _ = init_study(tmp_path, name="base")
    record_cli(*run_json("init", "--workload", "bike_day", "--study", study))  # STUDY_EXISTS
    record_cli(*run_json("run", "ml", "--study", tmp_path / "none", "--config", "seasonal_7", "--partition", "dev", "--request-id", "r"))
    record_cli(*run_json("init", "--workload", "bike_day", "--study", tmp_path / "elsewhere", "--examples-dir", examples_copy(tmp_path, edit=lambda d: d.update(track="x"), name="other-track")))
    from _chinook_helpers import init_chinook

    chinook, _ = init_chinook(tmp_path, name="chinook")
    record_cli(*run_ml(chinook, "seasonal_7", "dev", "r"))  # UNSUPPORTED_CAPABILITY: a command of the other Track
    record_cli(*run_ml(study, "seasonal_7", "dev", ""))
    record_cli(*run_ml(study, "seasonal_7", "dev", "r", "--retry-of", "nope"))
    record_cli(*run_json("run", "ml", "--study", study, "--config", "seasonal_7", "--partition", "dev"))
    _, first, _ = run_ml(study, "seasonal_7", "dev", "first")
    record_cli(*run_ml(study, "ridge_v1", "dev", "first"))  # REQUEST_CONFLICT
    record_cli(*run_ml(study, "seasonal_7", "dev", "stale", "--read-sequence", 0))  # STUDY_CHANGED
    record_cli(*run_ml(study, "seasonal_7", "dev", "ahead", "--read-sequence", 10**6))  # WRITE_SEQUENCE_AHEAD
    record_cli(*run_json("recover", "--study", study, "--attempt", first["attempt"]["attempt_id"]))  # ATTEMPT_TERMINAL
    record_cli(*run_json("recover", "--study", study, "--attempt", "none"))  # ATTEMPT_NOT_FOUND
    with lock.writer_lock(study):
        record_cli(*run_ml(study, "seasonal_7", "dev", "second"))  # STUDY_LOCKED
    with unittest.mock.patch.object(lock, "_load_fcntl", side_effect=ImportError):
        record_cli(*run_ml(study, "seasonal_7", "dev", "third"))  # LOCKING_UNAVAILABLE

    examples = examples_copy(tmp_path)
    flipped, _ = init_study(tmp_path, name="flipped", examples=examples)
    data_file = examples / "bike_day" / "data" / "day.csv"
    content = bytearray(data_file.read_bytes())
    content[len(content) // 2] ^= 1
    data_file.write_bytes(bytes(content))
    record_cli(*run_ml(flipped, "seasonal_7", "dev", "r", "--examples-dir", examples))  # DATA_INTEGRITY

    def shift(declaration):
        declaration["partitions"]["dev"][1] = "2012-06-29"
        declaration["partitions"]["public_check"][0] = "2012-06-30"

    record_cli(*run_ml(study, "seasonal_7", "dev", "new", "--examples-dir", examples_copy(tmp_path, edit=shift, name="shifted")))

    altered, _ = init_study(tmp_path, name="altered")
    (altered / "artifacts" / "memberships.csv").write_bytes(b"x")
    record_cli(*run_ml(altered, "seasonal_7", "dev", "r"))  # ARTIFACT_INTEGRITY
    gone, _ = init_study(tmp_path, name="gone")
    (gone / "artifacts" / "references.csv").unlink()
    record_cli(*run_ml(gone, "seasonal_7", "dev", "r"))  # ARTIFACT_MISSING

    record_raised(lambda: artifacts.publish_bytes(tmp_path, "../outside", b"x", media_type="text/plain", role="r"))
    artifacts.publish_bytes(tmp_path, "published.txt", b"one", media_type="text/plain", role="r")
    record_raised(lambda: artifacts.publish_bytes(tmp_path, "published.txt", b"two", media_type="text/plain", role="r"))
    record_raised(lambda: canonical.dumps({"mae": float("nan")}))
    record_raised(lambda: contracts.validate({"kind": "nothing"}))
    return found


def test_the_refusal_table_equals_the_code_exit_stage_and_details_of_each_refusal(page, tmp_path):
    rows = attrs_of(page, "study-codes", "data-code")
    found = study_refusals(tmp_path)
    assert words(rows["REQUEST_CONFLICT"]["data-details"]) == {"request_id", "attempt_id", "decision_id", "declared_deviation_id", "differs"}
    assert {"STUDY_CHANGED", "WRITE_SEQUENCE_AHEAD"} <= set(rows) and found["STUDY_CHANGED"][0] == 6 and found["WRITE_SEQUENCE_AHEAD"][1] == "sequence"
    assert set(rows) == set(found)
    for code, row in rows.items():
        exit_code, stage, details = found[code]
        assert int(row["data-exit"]) == exit_code, code
        assert row["data-stage"] == stage, code
        assert words(row["data-details"]) == details, code


def test_the_readme_and_chapter_02_no_longer_say_there_is_no_command_line_or_no_study():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "no command line yet" not in readme
    assert "There is no Study, run manifest" not in readme
    assert "`init`" in readme and "`run ml`" in readme
    chapter = (HANDBOOK / "chapters" / "02-temporal-regression-track.html").read_text(encoding="utf-8")
    assert "There is no command for this Track yet" not in chapter
    assert "<h3>No Study</h3>" not in chapter


# --- chapter 05: assess, the Scorer registry, the Criterion states and the Assessment record (#66) -------------------


def test_the_assess_command_table_equals_the_flags_the_parser_defines(page):
    from hypotrail.cli import build_parser

    action = next(a for a in build_parser()._actions if getattr(a, "choices", None) and "assess" in a.choices)
    options = {flag: a.required for a in action.choices["assess"]._actions for flag in a.option_strings if flag not in ("-h", "--help")}
    rows = attrs_of(page, "assess-command", "data-command")
    assert set(rows) == {"assess"}
    assert words(rows["assess"]["data-required"]) == {flag for flag, required in options.items() if required}
    assert words(rows["assess"]["data-optional"]) == {flag for flag, required in options.items() if not required}


def test_the_scorer_table_equals_the_registry(page):
    from hypotrail.core import scorers

    rows = attrs_of(page, "scorers", "data-scorer")
    assert set(rows) == set(scorers.REGISTRY)
    for scorer_id, row in rows.items():
        scorer = scorers.REGISTRY[scorer_id]
        assert (row["data-version"], row["data-domain"], row["data-criterion"], row["data-metric"]) == (
            scorer.version, scorer.domain, scorer.criterion or " ".join(scorer.criteria), scorer.metric_id or "",
        ), scorer_id


def test_the_reason_table_equals_the_state_and_reason_the_code_gives_each_case(page):
    from hypotrail.ml.assess import criterion

    cases = {
        "item_failed": criterion("failed", "", "1"),
        "item_missing": criterion("missing", "", "1"),
        "reference_missing": criterion("produced", "1", None),
        "reference_invalid": criterion("produced", "1", "n/a"),
        "prediction_invalid": criterion("produced", "n/a", "1"),
        "scoring_failed": criterion("produced", "1e308", "-1e308"),
    }
    rows = attrs_of(page, "criterion-reasons", "data-reason")
    assert set(rows) == set(cases)
    for reason, (state, value, found) in cases.items():
        assert (rows[reason]["data-state"], value, found) == (state, None, reason)
    assert criterion("produced", "3", "5") == ("scored", 2.0, None)


def test_the_assessment_record_tables_equal_the_contract_schema_and_a_numeric_loss_leaves_correct_and_incorrect_null(page, tmp_path):
    from _assess_helpers import assess, fresh_study, observation_set_id, references_id

    from hypotrail.core import contracts

    definitions = contracts.schema()["$defs"]
    rows = attrs_of(page, "assessment-fields", "data-record")
    assert set(rows) == {"Assessment", "Counts", "Metric"}
    for name, row in rows.items():
        assert words(row["data-required"]) == set(definitions[name]["required"]), name
        assert words(row["data-optional"]) == set(definitions[name]["properties"]) - set(definitions[name]["required"]), name
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    _, payload, _ = assess(study, observation_set_id(study, attempts["seasonal_7"]), "regression_mae_v1", references_id(study))
    record = payload["assessment"]
    assert set(record) - words(rows["Assessment"]["data-optional"]) == words(rows["Assessment"]["data-required"])
    assert record["counts"]["correct"] is None and record["counts"]["incorrect"] is None
    layout = attrs_of(page, "assessment-layout", "data-path")
    written = {
        p.relative_to(study).as_posix().replace(record["assessment_id"], "ASSESSMENT_ID")
        for p in (study / "assessments").rglob("*")
        if p.is_file()
    }
    assert set(layout) == written


def test_the_assess_refusal_table_equals_the_code_exit_stage_and_details_of_each_refusal(page, tmp_path):
    from _assess_helpers import assess, construct, fresh_study, observation_set_id, references_id

    study, attempts = fresh_study(tmp_path, "seasonal_7")
    attempt = attempts["seasonal_7"]
    refs = references_id(study)
    obs = observation_set_id(study, attempt)
    found = {}

    def record(result):
        code, payload, _ = result
        error = payload["error"]
        found[error["code"]] = (code, error["stage"], set(error["details"]))

    record(assess(study, obs, "nope", refs))
    record(assess(study, construct(study, attempt, lambda rows: rows, domain="agentic"), "regression_mae_v1", refs))
    record(assess(study, "nope", "regression_mae_v1", refs))
    record(assess(study, obs, "regression_mae_v1", "nope"))
    record(assess(study, construct(study, attempt, lambda rows: [*rows, rows[0]]), "regression_mae_v1", refs))
    record(assess(study, construct(study, attempt, lambda rows: rows, provenance={"partition": "train"}), "regression_mae_v1", refs))
    # ASSESSMENT_PUBLIC_CHECK_REFUSED is gone: inside a Study an Assessment of public_check Items is an Exposure (chapter 12)
    rows = attrs_of(page, "assess-codes", "data-code")
    assert set(rows) == set(found)
    for code, row in rows.items():
        exit_code, stage, details = found[code]
        assert int(row["data-exit"]) == exit_code, code
        assert row["data-stage"] == stage, code
        assert words(row["data-details"]) == details, code


# --- chapter 06: import ml, the mapping, the provenance fields and the refusals (#67) -----------------------------------


def test_the_import_command_table_equals_the_flags_the_parser_defines(page):
    from hypotrail.cli import build_parser

    parser = build_parser()
    action = next(a for a in parser._actions if getattr(a, "choices", None) and "import" in a.choices)
    sub = next(a for a in action.choices["import"]._actions if getattr(a, "choices", None) and "ml" in a.choices)
    options = {flag: a.required for a in sub.choices["ml"]._actions for flag in a.option_strings if flag not in ("-h", "--help")}
    rows = attrs_of(page, "import-command", "data-command")
    assert set(rows) == {"import ml"}
    assert words(rows["import ml"]["data-required"]) == {flag for flag, required in options.items() if required}
    assert words(rows["import ml"]["data-optional"]) == {flag for flag, required in options.items() if not required}


def test_the_mapping_table_equals_the_keys_the_code_accepts_and_what_each_does(page, tmp_path):
    from _import_helpers import export, import_ml, population_of, write_json
    from _study_helpers import init_study

    from hypotrail.ml import imports

    rows = attrs_of(page, "import-mapping", "data-key")
    assert set(rows) == set(imports.MAPPING_KEYS)
    for key, row in rows.items():
        assert (row["data-required"] == "yes") == imports.MAPPING_KEYS[key], key
        assert row["data-kind"] == ("column" if key in imports.COLUMN_KEYS else "claim"), key
    assert {k for k, r in rows.items() if r["data-kind"] == "claim" and r["data-required"] == "no"} == set(imports.CLAIM_KEYS)
    # the code refuses a key outside the table, and accepts a file with each optional key left out
    study, _ = init_study(tmp_path)
    source, digest = export(tmp_path)
    required = {"row_id": "day_key", "y_pred": "forecast_rentals", "dataset_sha256": digest}
    code, payload, _ = import_ml(study, source, write_json(tmp_path / "m.json", required), population_of(tmp_path, source), "ok")
    assert code == 0, payload


def test_the_producer_table_equals_the_fields_the_code_records_with_their_origin(page, tmp_path):
    from _import_helpers import import_ml, ready
    from _study_helpers import init_study

    from hypotrail.ml import imports

    rows = attrs_of(page, "import-producer", "data-field")
    assert {field: row["data-declared-by"] for field, row in rows.items()} == {f: k or "" for f, k in imports.PRODUCER_FIELDS.items()}
    study, _ = init_study(tmp_path)
    source, mapping, population, _ = ready(tmp_path)
    _, payload, _ = import_ml(study, source, mapping, population, "r")
    producer = payload["attempt"]["effective_config"]["producer"]
    assert set(producer) == set(rows)
    assert {entry["origin"] for entry in producer.values()} == {"unknown"}


def test_the_import_layout_table_equals_the_files_an_import_writes(page, tmp_path):
    from _import_helpers import import_ml, ready
    from _study_helpers import init_study

    study, _ = init_study(tmp_path)
    before = {p.relative_to(study).as_posix() for p in study.rglob("*") if p.is_file()}
    source, mapping, population, _ = ready(tmp_path)
    _, payload, _ = import_ml(study, source, mapping, population, "r")
    attempt_id = payload["attempt"]["attempt_id"]
    written = {
        p.relative_to(study).as_posix().replace(attempt_id, "ATTEMPT_ID").replace(f"source/{source.name}", "source/NAME")
        for p in study.rglob("*")
        if p.is_file()
    } - before
    written = without_the_journal(written)
    rows = attrs_of(page, "import-layout", "data-path")
    assert set(rows) == written
    roles = {ref["path"].replace(attempt_id, "ATTEMPT_ID").replace(f"source/{source.name}", "source/NAME"): ref["role"]
             for ref in [*payload["attempt"]["input_refs"], *payload["attempt"]["output_refs"]]}
    for path, row in rows.items():
        if path in roles:
            assert row["data-role"] == roles[path], path


def test_the_import_refusal_table_equals_the_code_exit_stage_and_details_of_each_refusal(page, tmp_path):
    from _import_helpers import FIELDS, export, import_ml, mapping_of, population_of, ready, rows_of, write_json, write_rows
    from _study_helpers import init_study

    study, _ = init_study(tmp_path)
    found = {}

    def record(result):
        code, payload, _ = result
        error = payload["error"]
        found[error["code"]] = (code, error["stage"], set(error["details"]))

    source, mapping, population, digest = ready(tmp_path)
    ids = [r["day_key"] for r in rows_of(source)]
    gone = tmp_path / "gone"
    record(import_ml(study, gone, mapping, population, "r"))
    record(import_ml(study, source, gone, population, "r"))
    record(import_ml(study, source, mapping, gone, "r"))
    pickle = tmp_path / "m.pkl"
    pickle.write_bytes(b"\x80\x04N.")
    record(import_ml(study, pickle, mapping, population, "r"))
    latin = tmp_path / "latin.csv"
    latin.write_bytes(b"day_key,forecast_rentals\n\xe9,1\n")
    record(import_ml(study, latin, mapping, population, "r"))
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    record(import_ml(study, empty, mapping, population, "r"))

    def with_mapping(content, name):
        return write_json(tmp_path / name, content)

    def with_mapping_text(text, name):
        (tmp_path / name).write_text(text, encoding="utf-8")
        return tmp_path / name

    base = {"row_id": "day_key", "y_pred": "forecast_rentals", "dataset_sha256": digest}
    record(import_ml(study, source, with_mapping([1], "m1.json"), population, "r"))
    record(import_ml(study, source, with_mapping({**base, "extra": "x"}, "m2.json"), population, "r"))
    record(import_ml(study, source, with_mapping({"row_id": "day_key", "y_pred": "forecast_rentals"}, "m3.json"), population, "r"))
    record(import_ml(study, source, with_mapping({**base, "y_pred": 1}, "m4.json"), population, "r"))
    record(import_ml(study, source, with_mapping({**base, "y_pred": "os.system"}, "m5.json"), population, "r"))
    record(import_ml(study, source, with_mapping({**base, "y_pred": "nope"}, "m6.json"), population, "r"))
    record(import_ml(study, source, with_mapping({**base, "dataset_sha256": "0" * 64}, "m7.json"), population, "r"))
    record(import_ml(study, source, with_mapping_text(json.dumps({**base, "row_id": 3})[:-1] + ', "row_id": "day_key"}', "m8.json"), population, "r"))
    record(import_ml(study, source, mapping, with_mapping_text(json.dumps({"item_ids": []})[:-1] + ', "item_ids": ' + json.dumps(ids) + "}", "p4.json"), "r"))
    record(import_ml(study, source, mapping, write_json(tmp_path / "p1.json", ["x"]), "r"))
    record(import_ml(study, source, mapping, write_json(tmp_path / "p2.json", {"item_ids": [*ids, "nope"]}), "r"))
    record(import_ml(study, source, mapping, write_json(tmp_path / "p3.json", {"item_ids": [*ids, "bike-day:2012-07-01"]}), "r"))
    rows = rows_of(source)
    for name, edit in {
        "ROW_ID_EMPTY": lambda r: [{**r[0], "day_key": ""}, *r[1:]],
        "ROW_ID_DUPLICATE": lambda r: [*r, r[0]],
        "ROW_ID_OUTSIDE_POPULATION": lambda r: [*r, {**r[0], "day_key": "bike-day:2030-01-01"}],
        "PREDICTION_NOT_FINITE": lambda r: [{**r[0], "forecast_rentals": "nan"}, *r[1:]],
        "POPULATION_ITEM_ABSENT": lambda r: r[1:],
    }.items():
        record(import_ml(study, write_rows(tmp_path / f"{name}.csv", edit(rows), FIELDS), mapping, population, "r"))
    table = attrs_of(page, "import-codes", "data-code")
    assert set(table) == set(found)
    for code, row in table.items():
        exit_code, stage, details = found[code]
        assert int(row["data-exit"]) == exit_code, code
        assert row["data-stage"] == stage, code
        assert words(row["data-details"]) == details, code


STRICT_JSON_WORDS = "NaN, a repeated key or an out-of-range number included"


def test_the_two_rows_of_a_document_that_is_not_json_say_that_nan_a_repeated_key_or_an_out_of_range_number_is_included_and_chapter_06_says_it_twice(page):
    rows = table_rows(page, "import-codes", "data-code")
    for code in ("MAPPING_INVALID", "POPULATION_INVALID"):
        assert STRICT_JSON_WORDS in plain_text(rows[code]["text"]), code
    assert plain_chapter("06-import.html").count(STRICT_JSON_WORDS) == 2


# --- chapter 07: compare, the comparability checks, strict against descriptive, the Comparison record (#71) ------------


def test_the_compare_command_table_equals_the_flags_the_parser_defines(page):
    from hypotrail.cli import build_parser

    action = next(a for a in build_parser()._actions if getattr(a, "choices", None) and "compare" in a.choices)
    options = {flag: a.required for a in action.choices["compare"]._actions for flag in a.option_strings if flag not in ("-h", "--help")}
    rows = attrs_of(page, "compare-command", "data-command")
    assert set(rows) == {"compare"}
    assert words(rows["compare"]["data-required"]) == {flag for flag, required in options.items() if required}
    assert words(rows["compare"]["data-optional"]) == {flag for flag, required in options.items() if not required}


def test_the_comparability_check_table_equals_the_checks_the_code_runs_in_order(page):
    from hypotrail.core import comparison

    rows = table_rows(page, "comparability-checks", "data-check")
    assert list(rows) == list(comparison.CHECKS)  # the table lists them in the order they run
    for check, row in rows.items():
        code, reason = comparison.REFUSALS[check]
        assert (row["attrs"]["data-code"], row["attrs"]["data-reason"]) == (code, reason), check


def test_the_comparison_record_tables_equal_the_contract_schema_and_the_layout_equals_the_files_written(page, tmp_path):
    from _compare_helpers import assessed, compare

    from hypotrail.core import contracts

    definitions = contracts.schema()["$defs"]
    rows = attrs_of(page, "comparison-fields", "data-record")
    assert set(rows) == {"Comparison"}
    assert words(rows["Comparison"]["data-required"]) == set(definitions["Comparison"]["required"])
    assert words(rows["Comparison"]["data-optional"]) == set(definitions["Comparison"]["properties"]) - set(definitions["Comparison"]["required"])
    study, _, a = assessed(tmp_path, "seasonal_7", "ridge_v1")
    _, payload, _ = compare(study, a["seasonal_7"]["assessment_id"], a["ridge_v1"]["assessment_id"])
    record = payload["comparison"]
    assert set(record) - words(rows["Comparison"]["data-optional"]) == words(rows["Comparison"]["data-required"])
    statuses = set(attrs_of(page, "comparison-statuses", "data-status"))
    assert statuses == set(definitions["Comparison"]["properties"]["comparability"]["properties"]["status"]["enum"])
    layout = attrs_of(page, "comparison-layout", "data-path")
    written = {
        p.relative_to(study).as_posix().replace(record["comparison_id"], "COMPARISON_ID")
        for p in (study / "comparisons").rglob("*")
        if p.is_file()
    }
    assert set(layout) == written


def comparisons_by_warning_code(tmp_path) -> dict:
    """{warning code: the status `compare` writes for a pair that holds it}, one pair for each code, on a Chinook Study and, for the single-feature warning and the Declared deviation's, a Bike Study."""
    from _agent_compare_helpers import answer_lines, compare, imported, native
    from _chinook_helpers import init_chinook
    from _compare_helpers import assessed

    study, _ = init_chinook(tmp_path, name="warnings")
    seeds = [imported(tmp_path, study, name, answer_lines())[0] for name in ("seed-a", "seed-b")]
    _, first = native(study, seeds[0])
    _, later = native(study, seeds[1])  # built from the later import: its Attempt started after the first one finished
    _, without_tools = native(study, seeds[0], tools=None)
    no_digests, without_cases = native(study, seeds[0])
    path = Path(study) / "attempts" / no_digests["attempt_id"] / "attempt.json"
    path.write_text(json.dumps({key: value for key, value in json.loads(path.read_text()).items() if key != "case_digests"}))
    _, imports = imported(tmp_path, study, "import", answer_lines())
    pairs = {
        "COMPARISON_DESCRIPTIVE_IMPORT": (first, imports),
        "COMPARISON_FACTOR_NOT_ESTABLISHED": (first, without_tools),
        "COMPARISON_CASES_NOT_ESTABLISHED": (first, without_cases),
        "COMPARISON_ORDER_NOT_ALTERNATED": (first, later),
    }
    bike, _, assessments = assessed(tmp_path / "bike", "seasonal_7", "ridge_v1")
    studies = dict.fromkeys(pairs, study)
    pairs["COMPARISON_SINGLE_FEATURE_BEATS"] = (assessments["seasonal_7"], assessments["ridge_v1"])
    studies["COMPARISON_SINGLE_FEATURE_BEATS"] = bike
    from _deviation_helpers import declare, references_of

    declare(bike, [references_of(bike)])  # it covers both sides of the Bike pair, which hold the single-feature warning too
    pairs["COMPARISON_DEVIATION_DECLARED"] = pairs["COMPARISON_SINGLE_FEATURE_BEATS"]
    studies["COMPARISON_DEVIATION_DECLARED"] = bike
    statuses = {}
    for code, (control, candidate) in pairs.items():
        exit_code, payload, err = compare(studies[code], control, candidate)
        assert exit_code == 0, (payload, err)
        assert code in [w["code"] for w in payload["comparison"]["warnings"]], code
        statuses[code] = payload["comparison"]["comparability"]["status"]
    return statuses


def test_the_warning_code_table_of_chapter_07_equals_the_warning_codes_and_what_compare_writes_for_a_pair_that_holds_each(page, tmp_path):
    from _agent_compare_helpers import warning_codes

    rows = attrs_of(page, "comparison-warnings", "data-code")
    assert set(rows) == set(warning_codes().values())  # both ways: a row for each code, a code for each row
    statuses = comparisons_by_warning_code(tmp_path)
    for code, row in rows.items():
        assert row["data-descriptive-only"] == ("yes" if statuses[code] == "descriptive_only" else "no"), code
        assert row["data-compatible"] == ("yes" if statuses[code] == "compatible" else "no"), code


def test_the_compare_refusal_table_equals_the_code_exit_stage_and_details_of_each_refusal(page, tmp_path):
    from _assess_helpers import construct
    from _compare_helpers import assessed, compare, forged

    study, attempts, a = assessed(tmp_path, "seasonal_7", "ridge_v1")
    control, candidate = a["seasonal_7"], a["ridge_v1"]
    found = {}

    def record(result):
        code, payload, _ = result
        error = payload["error"]
        found[error["code"]] = (code, error["stage"], set(error["details"]))

    def against(other):
        return compare(study, control["assessment_id"], other["assessment_id"])

    train = construct(study, attempts["ridge_v1"], lambda rows: rows, provenance={"partition": "train"})
    record(compare(study, control["assessment_id"], "nope"))
    record(against(forged(study, candidate, lambda r: r.update(observation_set_id="nope"))))
    record(against(forged(study, candidate, lambda r: r.update(observation_set_id=train))))
    both = [forged(study, a[c], lambda r, t=t: r.update(observation_set_id=t)) for c, t in (("seasonal_7", train), ("ridge_v1", train))]
    record(compare(study, both[0]["assessment_id"], both[1]["assessment_id"]))
    record(against(forged(study, candidate, lambda r: r["references_ref"].update(sha256="b" * 64))))
    record(against(forged(study, candidate, lambda r: r["scorer"].update(version="2"))))
    record(against(forged(study, candidate, lambda r: r["metrics"][0].update(unit="visits per day"))))
    record(against(forged(study, candidate, per_item=lambda rows: rows[:-1])))
    record(against(forged(study, candidate, per_item=lambda rows: [{**rows[0], "state": "unscored", "value": "", "reason": "item_failed"}, *rows[1:]])))
    scripted = construct(study, attempts["ridge_v1"], lambda rows: rows, mode="scripted_fixture")
    record(against(forged(study, candidate, lambda r: r.update(observation_set_id=scripted))))
    rows = attrs_of(page, "compare-codes", "data-code")
    assert set(rows) == set(found)
    for code, row in rows.items():
        exit_code, stage, details = found[code]
        assert int(row["data-exit"]) == exit_code, code
        assert row["data-stage"] == stage, code
        assert words(row["data-details"]) == details, code


# --- chapter 08: init for Chinook, import agent, assess with chinook_contract_v1 (#68) ---------------------------------


def _chinook_study_with_assessment(tmp_path):
    from _chinook_helpers import FIXTURE, fixture_population, import_agent, init_chinook, references_id
    from _study_helpers import run_json

    study, _ = init_chinook(tmp_path, name="chapter-08")
    _, imported, _ = import_agent(study, FIXTURE, fixture_population(tmp_path), "imp")
    attempt = imported["attempt"]
    folder = study / "attempts" / attempt["attempt_id"]
    observation_set = json.loads((folder / "observation_set.json").read_text())["observation_set_id"]
    _, assessed, _ = run_json(
        "assess", "--study", study, "--observations", observation_set, "--scorer", "chinook_contract_v1", "--references", references_id(study)
    )
    return study, attempt, assessed["assessment"]


def test_the_agent_study_layout_table_equals_the_files_init_writes_for_chinook(page, tmp_path):
    from _chinook_helpers import init_chinook

    study, _ = init_chinook(tmp_path)
    written = without_the_journal(p.relative_to(study).as_posix() for p in study.rglob("*") if p.is_file())
    rows = attrs_of(page, "agent-study-layout", "data-path")
    assert set(rows) == written


def test_the_agent_import_command_table_equals_the_flags_the_parser_defines(page):
    from hypotrail.cli import build_parser

    parser = build_parser()
    action = next(a for a in parser._actions if getattr(a, "choices", None) and "import" in a.choices)
    sub = next(a for a in action.choices["import"]._actions if getattr(a, "choices", None) and "agent" in a.choices)
    options = {flag: a.required for a in sub.choices["agent"]._actions for flag in a.option_strings if flag not in ("-h", "--help")}
    rows = attrs_of(page, "agent-import-command", "data-command")
    assert set(rows) == {"import agent"}
    assert words(rows["import agent"]["data-required"]) == {flag for flag, required in options.items() if required}
    assert words(rows["import agent"]["data-optional"]) == {flag for flag, required in options.items() if not required}


def test_the_line_key_table_equals_the_keys_a_line_may_hold_and_what_each_requires(page, tmp_path):
    from _chinook_helpers import fixture_lines, fixture_population, import_agent, init_chinook, write_lines

    from hypotrail.agentic import imports

    rows = attrs_of(page, "agent-line-keys", "data-key")
    assert {key: row["data-required"] for key, row in rows.items()} == imports.LINE_KEYS
    study, _ = init_chinook(tmp_path)
    population = fixture_population(tmp_path)
    for key, required in imports.LINE_KEYS.items():  # a key left out of every line: refused when it is required, accepted otherwise
        lines = [{k: v for k, v in line.items() if k != key} for line in fixture_lines()]
        code, payload, _ = import_agent(study, write_lines(tmp_path / f"{key}.jsonl", lines), population, f"without-{key}")
        refused = required == "always" or key == "final_answer"  # the fixture's lines carry final_answer, never raw_answer
        assert (code != 0) == refused, (key, payload)


def test_the_agent_producer_table_equals_the_fields_the_code_records_with_their_origin(page, tmp_path):
    from hypotrail.agentic import imports

    rows = attrs_of(page, "agent-producer", "data-field")
    declared = {field: ".".join(place) if place else "" for field, place in imports.PRODUCER_FIELDS.items()}
    assert {field: row["data-declared-by"] for field, row in rows.items()} == declared
    _, attempt, _ = _chinook_study_with_assessment(tmp_path)
    producer = attempt["effective_config"]["producer"]
    assert set(producer) == set(rows)
    assert {field for field, entry in producer.items() if entry["origin"] == "declared"} == {"file_origin", "file_mode"}


def test_the_agent_import_layout_table_equals_the_files_an_import_writes(page, tmp_path):
    from _chinook_helpers import FIXTURE

    study, attempt, _ = _chinook_study_with_assessment(tmp_path)
    folder = study / "attempts" / attempt["attempt_id"]
    written = {
        p.relative_to(study).as_posix().replace(attempt["attempt_id"], "ATTEMPT_ID").replace(f"source/{FIXTURE.name}", "source/NAME")
        for p in folder.rglob("*")
        if p.is_file()
    }
    rows = attrs_of(page, "agent-import-layout", "data-path")
    assert set(rows) == written
    roles = {
        ref["path"].replace(attempt["attempt_id"], "ATTEMPT_ID").replace(f"source/{FIXTURE.name}", "source/NAME"): ref["role"]
        for ref in [*attempt["input_refs"], *attempt["output_refs"]]
    }
    for path, row in rows.items():
        if path in roles:
            assert row["data-role"] == roles[path], path


def test_the_agent_import_refusal_table_equals_the_code_exit_stage_and_details_of_each_refusal(page, tmp_path):
    from _chinook_refusals import agent_import_refusals

    found = agent_import_refusals(tmp_path)
    table = attrs_of(page, "agent-import-codes", "data-code")
    assert set(table) == set(found)
    for code, row in table.items():
        exit_code, stage, details = found[code]
        assert int(row["data-exit"]) == exit_code, code
        assert row["data-stage"] == stage, code
        assert words(row["data-details"]) == details, code


def test_the_agent_counter_table_equals_the_counts_keys_of_the_contract_and_the_assessment_counts(page, tmp_path):
    from hypotrail.core import contracts

    _, _, record = _chinook_study_with_assessment(tmp_path)
    rows = attrs_of(page, "agent-counters", "data-key")
    assert set(rows) == set(contracts.schema()["$defs"]["Counts"]["properties"]) == set(record["counts"])
    counts = record["counts"]
    assert counts["scored"] == counts["correct"] + counts["incorrect"]
    assert {key: row["data-ticket-name"] for key, row in rows.items()} == {key: f"N_{key}" for key in rows}


def test_the_agent_rate_table_equals_the_two_named_rates_of_the_assessment(page, tmp_path):
    from hypotrail.agentic import assess as agent_assess

    _, _, record = _chinook_study_with_assessment(tmp_path)
    rows = attrs_of(page, "agent-rates", "data-rate")
    assert set(rows) == {agent_assess.QUALITY, agent_assess.CONFIRMED_SHARE} == {m["id"] for m in record["metrics"]}
    for metric in record["metrics"]:
        row = rows[metric["id"]]
        assert metric["denominator"] == record["counts"][row["data-denominator"]], metric["id"]
        assert metric["value"] == record["counts"][row["data-numerator"]] / metric["denominator"], metric["id"]
        assert metric["reason"] is None
    assert {row["data-null-reason"] for row in rows.values()} == {agent_assess.REASON_NO_SCORED, agent_assess.REASON_NO_EXPECTED}


def test_the_agent_assessment_field_table_equals_what_an_agent_assessment_adds_to_the_contract(page, tmp_path):
    from hypotrail.core import contracts

    _, _, record = _chinook_study_with_assessment(tmp_path)
    rows = attrs_of(page, "agent-assessment-fields", "data-field")
    definition = contracts.schema()["$defs"]["Assessment"]
    generic = {"rescoring", "study_revision", "recorded_at"}  # every Assessment has them: chapter 05 and chapter 10
    assert set(rows) | generic == set(record) - set(definition["required"])
    for field in rows:
        assert field in definition["properties"] and field not in definition["required"], field


def test_the_agent_assessment_layout_and_per_item_columns_equal_the_files_and_the_columns_written(page, tmp_path):
    from hypotrail.agentic import assess as agent_assess

    study, _, record = _chinook_study_with_assessment(tmp_path)
    written = {
        p.relative_to(study).as_posix().replace(record["assessment_id"], "ASSESSMENT_ID") for p in (study / "assessments").rglob("*") if p.is_file()
    }
    layout = attrs_of(page, "agent-assessment-layout", "data-path")
    assert set(layout) == written
    columns = table_rows(page, "agent-per-item-columns", "data-column")
    assert list(columns) == agent_assess.PER_ITEM_COLUMNS
    header = (study / record["per_item_ref"]["path"]).read_text().splitlines()[0].split(",")
    assert header == agent_assess.PER_ITEM_COLUMNS


def test_the_unproduced_reason_table_equals_the_reasons_of_a_failed_and_a_missing_episode(page):
    from hypotrail.agentic.unproduced import criteria_of_unproduced

    rows = attrs_of(page, "agent-unproduced", "data-status")
    assert set(rows) == {"failed", "missing"}
    for status, row in rows.items():
        criteria = criteria_of_unproduced({"status": status, "reason": None})
        assert {(c["state"], c["reason"]) for c in criteria} == {("unscored", row["data-reason"])}, status


def test_the_agent_assess_refusal_table_equals_the_code_exit_stage_and_details_of_each_refusal(page, tmp_path):
    from _chinook_helpers import episodes_file, import_agent, init_chinook, references_id, spec_of, write_lines
    from _study_helpers import run_json

    from hypotrail.core import canonical

    found = {}

    def record(result):
        code, payload, _ = result
        error = payload["error"]
        found[error["code"]] = (code, error["stage"], set(error["details"]))

    study, _ = init_chinook(tmp_path, name="refusals")
    keys = [("E01", 0), ("E11", 0)]
    source = write_lines(tmp_path / "public.jsonl", [{"case_id": c, "repeat": r, "observation_status": "missing"} for c, r in keys])
    _, imported, _ = import_agent(study, source, episodes_file(tmp_path, keys), "imp")
    folder = study / "attempts" / imported["attempt"]["attempt_id"]
    observation_set = json.loads((folder / "observation_set.json").read_text())["observation_set_id"]
    args = ("assess", "--study", study, "--observations", observation_set, "--scorer", "chinook_contract_v1")
    spec = spec_of(study)
    spec["artifacts"] = [e for e in spec["artifacts"] if e["ref"]["role"] != "answer_schema"]
    (study / "study.json").write_bytes(canonical.dumps(spec))
    record(run_json(*args, "--references", references_id(study)))
    rows = attrs_of(page, "agent-assess-codes", "data-code")
    assert set(rows) == set(found)
    for code, row in rows.items():
        exit_code, stage, details = found[code]
        assert int(row["data-exit"]) == exit_code, code
        assert row["data-stage"] == stage, code
        assert words(row["data-details"]) == details, code


def test_chapter_03_no_longer_lists_the_agent_import_and_assessment_as_not_built():
    text = CHAPTER_03.read_text(encoding="utf-8")
    assert "Scoring answers imported without a trace, the shares of the Assessment contract" not in text
    assert 'href="#agent-answers"' in text


# --- chapter 09: importing an Inspect log (#69) -----------------------------------------------------------------------------


def _log_import(tmp_path, *, metadata=None):
    from _chinook_helpers import episodes_file, import_agent, init_chinook
    from _log_helpers import SCRIPTED, scripted_log

    study, _ = init_chinook(tmp_path, name="chapter-09")
    log = scripted_log(tmp_path, ("D01", "D03"), metadata=SCRIPTED if metadata is None else metadata)
    code, payload, err = import_agent(study, log, episodes_file(tmp_path, [("D01", 0), ("D03", 0)]), "imp")
    assert code == 0, (payload, err)
    folder = study / "attempts" / payload["attempt"]["attempt_id"]
    return study, payload["attempt"], folder


def test_the_source_kind_table_equals_the_suffix_the_code_reads_as_a_log(page):
    from hypotrail.agentic import imports

    rows = attrs_of(page, "log-source-kinds", "data-suffix")
    assert {row["data-kind"]: suffix for suffix, row in rows.items()} == {"inspect_log": imports.LOG_SUFFIX, "jsonl": ""}
    assert imports.is_log(f"answers{imports.LOG_SUFFIX}") and not imports.is_log("answers.jsonl")


def test_the_log_observation_key_table_equals_the_keys_an_imported_episode_keeps(page, tmp_path):
    _, _, folder = _log_import(tmp_path)
    kept = [json.loads(line) for line in (folder / "observations.jsonl").read_text().splitlines()]
    rows = attrs_of(page, "log-observation-keys", "data-key")
    assert set(rows) == {key for entry in kept for key in entry}
    assert all(set(entry) == set(rows) for entry in kept)


def test_the_declared_table_equals_the_fields_the_import_records_with_their_origin_and_place(page, tmp_path):
    from hypotrail.agentic import imports, inspect_log

    _, attempt, folder = _log_import(tmp_path)
    rows = attrs_of(page, "log-declared", "data-field")
    assert {row["data-header"] for row in rows.values()} == set(inspect_log.HEADER_FIELDS)
    config = attempt["effective_config"]
    for field, row in rows.items():
        entry = config[row["data-under"]][field]
        assert entry["origin"] == "declared", field  # a scripted log states every one of them
    assert {f for f, r in rows.items() if r["data-under"] == "log"} == set(imports.LOG_FIELDS)
    observation_set = json.loads((folder / "observation_set.json").read_text())
    assert observation_set["provenance"]["log"] == config["log"]


def test_the_unknown_table_equals_the_producer_fields_a_log_does_not_establish(page, tmp_path):
    _, attempt, folder = _log_import(tmp_path)
    rows = attrs_of(page, "log-unknown", "data-field")
    producer = attempt["effective_config"]["producer"]
    assert set(rows) == {field for field, entry in producer.items() if entry["origin"] == "unknown"}
    assert set(json.loads((folder / "observation_set.json").read_text())["unknown_fields"]) == set(rows)


def test_the_log_import_refusal_table_equals_the_code_exit_stage_and_details_of_each_refusal(page, tmp_path, monkeypatch):
    from _log_helpers import agent_log_import_refusals

    found = agent_log_import_refusals(tmp_path, monkeypatch)
    table = attrs_of(page, "log-import-codes", "data-code")
    assert set(table) == set(found)
    for code, row in table.items():
        exit_code, stage, details = found[code]
        assert int(row["data-exit"]) == exit_code, code
        assert row["data-stage"] == stage, code
        assert words(row["data-details"]) == details, code


def test_the_chapters_that_said_a_log_import_was_not_built_point_to_chapter_09():
    for name in ("03-agentic-track.html", "06-import.html", "08-agent-answers.html"):
        text = (HANDBOOK / "chapters" / name).read_text(encoding="utf-8")
        assert 'href="#inspect-log-import"' in text, name
    assert "an import of Inspect logs" not in (HANDBOOK / "chapters" / "08-agent-answers.html").read_text(encoding="utf-8")


# --- chapter 10: revisions and corrected References (#70, #73 Tightened B4) --------------------------------------------


def _corrected_chinook_study(tmp_path, *, name="chapter-09", revisions=1):
    """(study, the files before the revisions, the files after): a Chinook Study given `revisions` corrected References sets."""
    from _chinook_helpers import init_chinook
    from _revision_helpers import corrected_chinook_references, new_revision, snapshot_files

    study, _ = init_chinook(tmp_path, name=name)
    before = set(snapshot_files(study))
    for number in range(revisions):
        examples = corrected_chinook_references(
            tmp_path, lambda records, n=number: records["D03"].update(rows=[[1300 + n]]), name=f"{name}-examples-{number}"
        )
        code, payload, err = new_revision(study, "--examples-dir", examples)
        assert code == 0, (payload, err)
    return study, before, set(snapshot_files(study))


def test_the_revision_layout_table_equals_the_files_a_new_revision_writes(page, tmp_path):
    study, before, after = _corrected_chinook_study(tmp_path, revisions=2)
    generic = set()
    for path in without_the_journal(after - before):
        path = re.sub(r"^revisions/[0-9]+/", "revisions/N/", path)
        generic.add(re.sub(r"-[0-9a-f]{16}\.", "-SHA16.", path))
    rows = attrs_of(page, "revision-layout", "data-path")
    assert set(rows) == generic | {"study.json"}  # study.json is the one file replaced, not added
    assert all(row["data-written-by"] == "init --new-revision" for row in rows.values())
    assert "study.json" in before and "revisions/1/study.json" in after


def test_the_revision_field_tables_equal_what_a_revision_adds_to_the_study_spec_and_what_status_reports(page, tmp_path):
    from _revision_helpers import spec_of

    from hypotrail.core import contracts
    from hypotrail.core.state import status

    study, _, _ = _corrected_chinook_study(tmp_path)
    spec_definition = contracts.schema()["$defs"]["StudySpec"]
    rows = attrs_of(page, "revision-fields", "data-field")
    in_study = {field for field, row in rows.items() if row["data-where"] == "study"}
    assert in_study == set(spec_definition["properties"]) - set(spec_definition["required"])
    assert in_study - {"check_informed"} <= set(spec_of(study))  # `check_informed` is written once the Study has had an Exposure (chapter 12)
    entry = spec_definition["properties"]["artifacts"]["items"]
    in_artifact = {field for field, row in rows.items() if row["data-where"] == "artifact"}
    assert in_artifact == set(entry["properties"]) - set(entry["required"]) and in_artifact <= set(spec_of(study)["artifacts"][0])
    (_, second) = status(study)["revisions"]
    assert set(attrs_of(page, "revision-status", "data-field")) == set(second)
    assert second["revision_number"] == 2 and second["previous_revision"] is not None


def command_forms(chapter, column):
    """The text of one cell, named by its column header, of the `INVALID_ARGUMENTS` row of a table, and the `hypotrail ...` forms its `code` elements give (`<command>` written out)."""
    raw = (HANDBOOK / "chapters" / chapter).read_text(encoding="utf-8")
    [table] = [t for t in re.findall(r"<table.*?</table>", raw, re.S) if '<tr data-code="INVALID_ARGUMENTS"' in t]
    headers = [plain_text(h) for h in re.findall(r"<th>(.*?)</th>", table, re.S)]
    row = re.search(r'<tr data-code="INVALID_ARGUMENTS".*?</tr>', table, re.S)[0]
    cell = re.findall(r"<td>(.*?)</td>", row, re.S)[headers.index(column)]
    return plain_text(cell), [html.unescape(form) for form in re.findall(r"<code>(hypotrail[^<]*)</code>", cell)]


def test_the_invalid_arguments_rows_of_chapters_04_and_10_give_the_command_forms_the_code_gives_and_no_other_text_holds_one(tmp_path):
    from _study_helpers import run_json

    text, forms = command_forms("04-study-and-attempts.html", "When")
    assert forms == ["hypotrail <command>", "hypotrail"] and "unknown flag" in text
    assert run_json("status")[1]["error"]["details"]["command"] == forms[0].replace("<command>", "status")
    assert run_json("status", "--study", tmp_path / "x", "--bogus")[1]["error"]["details"]["command"] == forms[1]
    _, forms10 = command_forms("10-revisions-and-rescoring.html", "details")
    assert forms10 == ["hypotrail <command>"]
    study = tmp_path / "none"
    for arguments in (["--new-revision", "--workload", "chinook"], []):
        details = run_json("init", "--study", study, *arguments)[1]["error"]["details"]
        assert details["command"] == forms10[0].replace("<command>", "init")
    for chapter in ("04-study-and-attempts.html", "10-revisions-and-rescoring.html"):
        assert html.unescape(plain_chapter(chapter)).count("hypotrail <command>") == 1, chapter


def test_chapter_14_says_that_the_folder_of_out_is_fsynced_in_the_sentence_that_says_the_page_is_renamed_and_chapter_04_keeps_its_sentence_on_publication():
    sentences = re.split(r"(?<=[.!?]) ", html.unescape(plain_chapter("14-report.html")))
    [renamed] = [sentence for sentence in sentences if "renamed onto" in sentence]
    assert "fsync" in renamed
    assert (
        "Publication is atomic (core/artifacts.py): the bytes go to a temporary file in the destination's folder, inside the Study, are flushed and fsynced, "
        "then renamed onto the final path; nothing appears under the final path before the rename."
    ) in html.unescape(plain_chapter("04-study-and-attempts.html"))


ORDER_ID = "assessment-order"


def table_of(raw, table_id):
    return re.search(rf'<table[^>]*id="{table_id}".*?</table>', raw, re.S)[0]


def test_chapter_10_states_the_order_of_the_later_assessment_once_and_the_other_places_link_to_it_without_restating_it():
    """A restatement is found by its spelling: `(recorded_at, id)` and `position 0`, each of which states one part of the order. A restatement spelled otherwise is outside this test."""
    chapters = {path.name: path.read_text(encoding="utf-8") for path in sorted((HANDBOOK / "chapters").glob("*.html"))}
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    texts = {name: html.unescape(plain_text(raw)) for name, raw in chapters.items()} | {"README.md": readme}
    ten = chapters["10-revisions-and-rescoring.html"]
    for spelling in ("(recorded_at, id)", "position 0"):
        assert [(name, text.count(spelling)) for name, text in texts.items() if spelling in text] == [("10-revisions-and-rescoring.html", 1)], spelling
    [statement] = re.findall(rf'<p id="{ORDER_ID}">(.*?)</p>', ten, re.S)
    assert all(spelling in html.unescape(plain_text(statement)) for spelling in ("(recorded_at, id)", "position 0"))
    link = f'href="#{ORDER_ID}"'
    assert link in chapters["14-report.html"] and link in chapters["17-decisions.html"]
    [later] = re.findall(r"<p>&quot;Later&quot; .*?</p>|<p>\"Later\" .*?</p>", chapters["17-decisions.html"], re.S)
    assert link in later
    for table_id, field in (("revision-record-fields", "recorded_at"), ("rescoring-fields", "earlier_assessment_id")):
        [row] = re.findall(rf'<tr data-field="{field}".*?</tr>', table_of(ten, table_id), re.S)
        assert link in row, field
    [recorded_at_row] = re.findall(r'<tr data-field="recorded_at".*?</tr>', table_of(ten, "revision-record-fields"), re.S)
    assert "orders Assessments" not in plain_text(recorded_at_row)
    [paragraph] = [p for p in re.findall(r"<p>.*?</p>", ten, re.S) if "Otherwise it names the latest one that does" in plain_text(p)]
    assert link in paragraph


def test_the_revision_refusal_table_equals_the_code_exit_stage_and_details_of_each_refusal(page, tmp_path):
    from _chinook_helpers import init_chinook
    from _revision_helpers import new_revision
    from _study_helpers import run_json

    found = {}

    def record(result):
        code, payload, _ = result
        error = payload["error"]
        found[error["code"]] = (code, error["stage"], set(error["details"]))

    study, _ = init_chinook(tmp_path, name="refusals")
    record(new_revision(study))  # PROTOCOL_UNCHANGED
    record(run_json("init", "--study", study, "--new-revision", "--workload", "chinook"))  # INVALID_ARGUMENTS, the widest details
    rows = attrs_of(page, "revision-codes", "data-code")
    assert set(rows) == set(found)
    for code, row in rows.items():
        exit_code, stage, details = found[code]
        assert int(row["data-exit"]) == exit_code, code
        assert row["data-stage"] == stage, code
        assert words(row["data-details"]) == details, code
    _, neither, _ = run_json("init", "--study", tmp_path / "none")
    assert neither["error"]["code"] == "INVALID_ARGUMENTS" and set(neither["error"]["details"]) <= words(rows["INVALID_ARGUMENTS"]["data-details"])


def test_the_rescoring_tables_equal_the_contract_schema_the_causes_of_the_code_and_a_rescoring_the_code_writes(page, tmp_path):
    from _chinook_helpers import FIXTURE, fixture_population, import_agent, init_chinook, references_id
    from _revision_helpers import corrected_chinook_references, new_revision
    from _study_helpers import run_json

    from hypotrail.core import contracts, rescoring

    study, _ = init_chinook(tmp_path, name="chapter-10-rescoring")
    _, imported, _ = import_agent(study, FIXTURE, fixture_population(tmp_path), "imp")
    folder = study / "attempts" / imported["attempt"]["attempt_id"]
    observation_set = json.loads((folder / "observation_set.json").read_text())["observation_set_id"]
    args = ("assess", "--study", study, "--observations", observation_set, "--scorer", "chinook_contract_v1")
    run_json(*args, "--references", references_id(study))
    corrected = corrected_chinook_references(tmp_path, lambda records: records["D03"].update(rows=[[1300]]))
    new_revision(study, "--examples-dir", corrected)
    _, payload, _ = run_json(*args, "--references", references_id(study))
    record = payload["assessment"]
    definition = contracts.schema()["$defs"]["Assessment"]["properties"]
    shape = definition["rescoring"]["anyOf"][1]

    fields = attrs_of(page, "rescoring-fields", "data-field")
    assert set(fields) == set(shape["properties"]) and set(record["rescoring"]) <= set(fields)
    assert {f for f, row in fields.items() if row["data-required"] == "yes"} == set(shape["required"])
    items = attrs_of(page, "rescoring-item-fields", "data-field")
    assert set(items) == set(shape["properties"]["changed_items"]["items"]["properties"]) == set(record["rescoring"]["changed_items"][0])
    verdict = attrs_of(page, "rescoring-verdict-fields", "data-field")
    assert set(verdict) == set(record["rescoring"]["changed_items"][0]["now"]) == {"state", "score", "reason"}

    causes = attrs_of(page, "rescoring-causes", "data-cause")
    assert tuple(causes) == rescoring.CAUSES  # the order is the order in which the first difference is the cause
    assert set(causes) == set(shape["properties"]["cause"]["enum"]) == set(shape["properties"]["other_changes"]["items"]["enum"])
    assert causes["references_version"]["data-compares"] == "references_ref.sha256"
    assert causes["scorer_version"]["data-compares"] == "scorer.version"
    assert causes["scorer_config_digest"]["data-compares"] == "scorer.config_digest"
    assert set(definition["study_revision"]["properties"]) == set(record["study_revision"])
    assert set(attrs_of(page, "revision-record-fields", "data-field")) == {"study_revision", "recorded_at", "rescoring"}


# --- chapter 11: comparing two agent Assessments (#72) ---------------------------------------------------------------------


def _agent_comparison(tmp_path):
    """(Study, Comparison record, the two Assessments) of two imports, so the files of a Comparison are all written."""
    from _agent_compare_helpers import answer_lines, compare, imported
    from _chinook_helpers import init_chinook

    study, _ = init_chinook(tmp_path, name="chapter-11")
    _, plain = imported(tmp_path, study, "plain", answer_lines())
    _, verify = imported(tmp_path, study, "verify", answer_lines(wrong={("D01", 0)}))
    _, payload, _ = compare(study, plain, verify)
    return study, payload["comparison"], (plain, verify)


def test_the_agent_check_table_equals_the_checks_the_code_runs_in_order_and_which_of_them_a_request_can_declare(page):
    from hypotrail.core import agent_comparison, comparison

    rows = table_rows(page, "agent-comparability-checks", "data-check")
    assert list(rows) == list(agent_comparison.AGENT_CHECKS)
    for check, row in rows.items():
        code, reason = comparison.REFUSALS[check]
        assert (row["attrs"]["data-code"], row["attrs"]["data-reason"]) == (code, reason), check
        assert (row["attrs"]["data-declarable"] == "yes") == (check in agent_comparison.FACTORS), check


def test_the_agent_reason_table_equals_the_reasons_the_code_records(page, tmp_path):
    from _agent_compare_helpers import answer_lines, compare, imported
    from _chinook_helpers import init_chinook

    from hypotrail.core import agent_comparison, comparison

    rows = attrs_of(page, "agent-check-reasons", "data-reason")
    assert set(rows) == {agent_comparison.REASON_DECLARED, agent_comparison.REASON_NOT_ESTABLISHED, comparison.REASON_PROVENANCE}
    study, _ = init_chinook(tmp_path, name="reasons")
    _, a = imported(tmp_path, study, "a", answer_lines())
    _, b = imported(tmp_path, study, "b", answer_lines(model="other"))
    found = {}
    for flags in ((), ("--factor", "model")):
        _, payload, _ = compare(study, a, b, *flags)
        for check in payload.get("comparison", {}).get("comparability", {}).get("checks", []):
            if check["reason"]:
                found[check["reason"]] = check["passed"]
    _, unknown = imported(tmp_path, study, "unknown", answer_lines(model=None, tool_use=None, mode=None))
    for check in compare(study, a, unknown)[1]["comparison"]["comparability"]["checks"]:
        if check["reason"]:
            found[check["reason"]] = check["passed"]
    assert set(found) == set(rows)
    for reason, passed in found.items():
        assert rows[reason]["data-passed"] == str(passed).lower(), reason


def test_the_agent_coverage_table_equals_the_keys_of_the_coverage_record_and_the_layout_equals_the_files_written(page, tmp_path):
    study, record, _ = _agent_comparison(tmp_path)
    assert set(attrs_of(page, "agent-coverage-keys", "data-key")) == set(record["coverage"])
    written = {
        p.relative_to(study).as_posix().replace(record["comparison_id"], "COMPARISON_ID") for p in (study / "comparisons").rglob("*") if p.is_file()
    }
    assert set(attrs_of(page, "agent-comparison-layout", "data-path")) == written
    assert set(record["descriptive"]["control"]) == set(contracts_schema_properties("DescriptiveMeasures"))


def contracts_schema_properties(name):
    from hypotrail.core import contracts

    return contracts.schema()["$defs"][name]["properties"]


def test_the_agent_refusal_table_equals_the_code_exit_stage_and_details_of_each_new_refusal(page, tmp_path):
    from _agent_compare_helpers import answer_lines, compare, imported, native
    from _chinook_helpers import init_chinook

    study, _ = init_chinook(tmp_path, name="chapter-11-refusals")
    found = {}

    def record(result):
        code, payload, _ = result
        error = payload["error"]
        found[error["code"]] = (code, error["stage"], set(error["details"]))

    seed, base = imported(tmp_path, study, "seed", answer_lines())
    _, two = imported(tmp_path, study, "two", answer_lines(repeats=2), repeats=2)
    _, tools = imported(tmp_path, study, "tools", answer_lines(tool_use="query_readonly"))
    _, model = imported(tmp_path, study, "model", answer_lines(model="other"))
    _, wide = native(study, seed, limits={"model_turns": 7})
    _, tight = native(study, seed, limits={"model_turns": 4})
    record(compare(study, base, two))
    record(compare(study, base, tools))
    record(compare(study, base, model))
    record(compare(study, wide, tight))
    rows = attrs_of(page, "agent-compare-codes", "data-code")
    assert set(rows) == set(found)
    for code, row in rows.items():
        exit_code, stage, details = found[code]
        assert int(row["data-exit"]) == exit_code, code
        assert row["data-stage"] == stage, code
        assert words(row["data-details"]) == details, code


def test_the_agent_comparison_chapter_names_the_delta_reason_and_the_status_codes_the_code_writes(page, tmp_path):
    from hypotrail.core import agent_comparison

    chapter = (HANDBOOK / "chapters" / "11-agent-comparison.html").read_text(encoding="utf-8")
    for name in (
        agent_comparison.REASON_COVERAGE,
        agent_comparison.WARNING_NOT_ESTABLISHED,
        agent_comparison.WARNING_CASES_NOT_ESTABLISHED,
        agent_comparison.DEFAULT_FACTOR,
        "COMPARISON_DESCRIPTIVE_IMPORT",
    ):
        assert f"<code>{name}</code>" in chapter, name
    assert set(agent_comparison.FACTORS) == {"configuration", "repeats", "tools", "model", "budgets"}


def test_the_paragraph_that_says_when_an_agent_comparison_is_descriptive_names_the_warning_of_a_side_with_no_case_content():
    from hypotrail.core import agent_comparison

    chapter = (HANDBOOK / "chapters" / "11-agent-comparison.html").read_text(encoding="utf-8")
    (paragraph,) = [p for p in re.findall(r"<p>.*?</p>", chapter, re.S) if "<code>descriptive_only</code>" in p and "<code>COMPARISON_FACTOR_NOT_ESTABLISHED</code>" in p]
    assert f"<code>{agent_comparison.WARNING_CASES_NOT_ESTABLISHED}</code>" in paragraph


def limit_cards(chapter) -> dict:
    """{data-limit: the card's text} of the cards after a chapter's "Limits" heading that carry a `data-limit`."""
    section = chapter.split('<p class="sub2">Limits</p>', 1)[1].split('<p class="sub2">', 1)[0]
    return {m[1]: plain_text(m[2]) for m in re.finditer(r'<div class="card"[^>]*\bdata-limit="([^"]+)"[^>]*>(.*?)</div>', section, re.S)}


def test_chapter_11_limits_state_that_a_compatible_comparison_can_hold_the_order_warning_and_the_two_limits_of_its_derivation():
    order = "COMPARISON_ORDER_NOT_ALTERNATED"
    cards = limit_cards((HANDBOOK / "chapters" / "11-agent-comparison.html").read_text(encoding="utf-8"))
    invariant = cards.get("compatible-with-warning", "")
    assert "compatible" in invariant and order in invariant, invariant
    overlap, imported = cards.get("order-overlap", ""), cards.get("order-import", "")
    assert order in overlap and "overlap" in overlap, overlap
    assert order in imported and "Import" in imported, imported


def test_the_readme_and_the_comparison_chapters_say_an_agent_comparison_exists():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    # R1-02: the README stays short; the agent Comparison's detail is in chapter 07.
    assert "`compare`" in readme and "of either Track" in readme
    chapter = (HANDBOOK / "chapters" / "07-comparison.html").read_text(encoding="utf-8")
    assert "Agent Comparisons, the alignment by Case and Repeat" not in chapter
    assert 'href="#agent-comparison"' in chapter


# --- chapter 12: the freeze record, the Exposure journal and check_informed (#73) -------------------------------------------


def _exposed_bike_study(tmp_path, *, name="chapter-12"):
    """(Study, files): a Bike Study with a freeze record, journal entries, and one record of each kind marked check_informed."""
    from _assess_helpers import assess, fresh_study, observation_set_id, references_id
    from _compare_helpers import compare
    from _revision_helpers import new_revision
    from _study_helpers import examples_copy, run_ml

    study, attempts = fresh_study(tmp_path / name, "seasonal_7", partition="public_check")
    _, first, _ = assess(study, observation_set_id(study, attempts["seasonal_7"]), "regression_mae_v1", references_id(study))
    changed = examples_copy(tmp_path / name, edit=lambda d: d["configurations"]["ridge_v1"]["ridge"].update(alpha=2.5))
    _, ridge, _ = run_ml(study, "ridge_v1", "public_check", "changed", "--examples-dir", changed)
    _, second, _ = assess(study, observation_set_id(study, ridge["attempt"]), "regression_mae_v1", references_id(study), "--examples-dir", changed)
    code, both, err = compare(study, first["assessment"]["assessment_id"], second["assessment"]["assessment_id"], "--examples-dir", changed)
    assert code == 0, (both, err)

    def corrected_day(table):
        row = next(r for r in table if r["dteday"] == "2012-03-15")
        row["cnt"], row["registered"] = str(int(row["cnt"]) + 1000), str(int(row["registered"]) + 1000)

    code, payload, err = new_revision(study, "--examples-dir", examples_copy(tmp_path / name, rows=corrected_day, name="revised"))
    assert code == 0, (payload, err)
    return study


def test_the_freeze_and_journal_field_tables_equal_the_contract_schema_and_the_records_the_code_writes(page, tmp_path):
    from _exposure_helpers import freezes, journal

    from hypotrail.core import contracts

    study = _exposed_bike_study(tmp_path)
    (freeze,) = freezes(study)
    definition = contracts.schema()["$defs"]["FreezeRecord"]["properties"]
    rows = attrs_of(page, "freeze-fields", "data-field")
    assert {f for f, row in rows.items() if row["data-where"] == "freeze"} == set(definition) == set(freeze)
    assert {f for f, row in rows.items() if row["data-where"] == "environment"} == set(definition["environment"]["properties"]) == set(freeze["environment"])
    assert {f for f, row in rows.items() if row["data-where"] == "code"} == set(definition["code"]["properties"]) == set(freeze["code"])
    entry_definition = contracts.schema()["$defs"]["ExposureEntry"]["properties"]
    entry_rows = attrs_of(page, "entry-fields", "data-field")
    assert set(entry_rows) == set(entry_definition) == set(journal(study)[0])


def test_the_exposure_layout_table_equals_the_files_an_exposure_writes(page, tmp_path):
    from _assess_helpers import assess, fresh_study, observation_set_id, references_id
    from _revision_helpers import snapshot_files

    study, attempts = fresh_study(tmp_path, "seasonal_7", partition="public_check")
    before = set(snapshot_files(study))
    assess(study, observation_set_id(study, attempts["seasonal_7"]), "regression_mae_v1", references_id(study))
    generic = set()
    for path in without_the_journal(set(snapshot_files(study)) - before):
        if path.startswith("assessments/"):
            continue  # an Assessment's own files are chapter 05's
        path = re.sub(r"^revisions/[0-9]+/", "revisions/N/", path)
        generic.add(re.sub(r"^exposures/[0-9]{6}-[0-9a-f-]{36}\.json$", "exposures/SEQ-ENTRY_ID.json", path))
    rows = attrs_of(page, "exposure-layout", "data-path")
    assert set(rows) == generic
    assert all(set(row["data-written-by"].split()) == {"assess", "compare", "report"} for row in rows.values())


def test_the_entry_point_table_equals_where_public_check_is_allowed_and_the_code_each_refusal_has(page, tmp_path):
    from _assess_helpers import assess, fresh_study, observation_set_id, references_id
    from _study_helpers import run_json

    from hypotrail.agentic import counts, rescore
    from hypotrail.agentic.declaration import load_workload
    from hypotrail.core.errors import HypotrailError
    from hypotrail.ml import comparison, metrics

    workload = load_workload(ROOT / "examples" / "chinook")
    calls = {
        "metrics.compute_metrics": lambda: metrics.compute_metrics("p.csv", "r.csv", "m.csv", tmp_path, partition="public_check"),
        "comparison.compare": lambda: comparison.compare("a.csv", "b.csv", "r.csv", "m.csv", tmp_path / "out", tmp_path, partition="public_check"),
        "rescore": lambda: rescore.rescore_episodes([{"case_id": "E01", "repeat": 0}], {}, schema={}, workload=workload),
        "counts.tally": lambda: counts.tally([{"case_id": "E01", "tool_error_codes": []}], workload=workload),
    }
    rows = attrs_of(page, "exposure-entry-points", "data-entry")
    assert set(rows) == {"assess", "compare", "report", "run ml", *calls}
    for entry, call in calls.items():
        assert rows[entry]["data-study"] == "no"
        with pytest.raises(HypotrailError) as refusal:
            call()
        assert refusal.value.code == rows[entry]["data-code"], entry
    study, attempts = fresh_study(tmp_path / "s", "seasonal_7", partition="public_check")  # `run ml` on public_check: allowed, no journal
    assert rows["run ml"]["data-writes"] == "" and not (study / "exposures").exists()
    _, payload, _ = assess(study, observation_set_id(study, attempts["seasonal_7"]), "regression_mae_v1", references_id(study))
    assert rows["assess"]["data-writes"] == "journal" and len(list((study / "exposures").glob("*.json"))) == 1
    assert rows["compare"]["data-writes"] == "journal" and rows["compare"]["data-study"] == rows["assess"]["data-study"] == "yes"
    only_outputs, _ = fresh_study(tmp_path / "r", "seasonal_7", partition="public_check")  # `report` shows them: one entry, with no Assessment
    assert run_json("report", "--study", only_outputs, "--out", tmp_path / "r.html")[0] == 0
    assert rows["report"]["data-writes"] == "journal" and rows["report"]["data-study"] == "yes" and len(list((only_outputs / "exposures").glob("*.json"))) == 1


def test_the_check_informed_table_equals_the_records_that_carry_the_mark_and_what_status_lists(page, tmp_path):
    from _study_helpers import run_json

    from hypotrail.core import contracts

    study = _exposed_bike_study(tmp_path)
    rows = attrs_of(page, "check-informed-marks", "data-record")
    definitions = contracts.schema()["$defs"]
    assert set(rows) == {name for name, d in definitions.items() if "check_informed" in d.get("properties", {})}
    _, report, _ = run_json("status", "--study", study)
    assert {m["kind"] for m in report["check_informed"]} == {row["data-kind"] for row in rows.values()}
    assert {m["kind"]: set(m) for m in report["check_informed"]}["revision"] == {"kind", "id", "revision_number"}


def test_the_exposure_status_table_equals_the_keys_status_reports(page, tmp_path):
    from _study_helpers import init_study, run_json

    study = _exposed_bike_study(tmp_path)
    _, report, _ = run_json("status", "--study", study)
    rows = attrs_of(page, "exposure-status", "data-field")
    assert {f for f, row in rows.items() if row["data-where"] == "status"} == {"freeze_records", "exposures", "check_informed"} <= set(report)
    assert {f for f, row in rows.items() if row["data-where"] == "exposures"} == set(report["exposures"])
    empty, _ = init_study(tmp_path / "empty")
    _, report, _ = run_json("status", "--study", empty)
    assert report["exposures"]["recorded_in_this_study"] == 0 and report["exposures"]["earlier_exposure"] == "unknown"


def test_the_exposure_refusal_table_equals_the_code_exit_stage_and_details_of_each_refusal(page, tmp_path):
    from _chinook_helpers import init_chinook
    from _exposure_helpers import assess_agent, correct_e01, edit_chinook_references, import_public

    study, _ = init_chinook(tmp_path)
    attempt = import_public(tmp_path, study, "imp")
    code, payload, _ = assess_agent(study, attempt, "--examples-dir", edit_chinook_references(tmp_path, correct_e01))
    error = payload["error"]
    rows = attrs_of(page, "exposure-codes", "data-code")
    assert set(rows) == {error["code"]}
    row = rows[error["code"]]
    assert (int(row["data-exit"]), row["data-stage"], words(row["data-details"])) == (code, error["stage"], set(error["details"]))


def test_the_readme_and_the_chapters_no_longer_say_public_check_waits_for_the_journal():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "no freeze or Exposure journal" not in readme.lower()
    assert "Exposure journal" in readme and "freeze record" in readme
    for name in sorted((HANDBOOK / "chapters").glob("*.html")):
        text = name.read_text(encoding="utf-8")
        for stale in ("until the Exposure journal exists", "until #9's Exposure journal", "No freeze, no Exposure", "ASSESSMENT_PUBLIC_CHECK_REFUSED"):
            assert stale not in text or name.name.startswith("12-"), (name.name, stale)
    for name in ("02-temporal-regression-track.html", "03-agentic-track.html", "05-assessments.html", "07-comparison.html", "08-agent-answers.html"):
        assert 'href="#freeze-exposure"' in (HANDBOOK / "chapters" / name).read_text(encoding="utf-8"), name


# --- #62: chapter 03's table of the fields of run.json is pinned against the code that writes them ----------------------


def _flattened(record):
    """The fields of a run record as the table names them: the dicts the table splits are split into `parent.child`."""
    split = {"engine", "reasoning", "output_cap", "limit_notes"}
    return {f"{k}.{c}" if k in split else k for k, v in record.items() for c in (v if k in split else [None])}


def _value(record, field):
    for part in field.split("."):
        record = record[part]
    return record


def _log_mutations():
    """For each field whose source is the log: how to change that value in a log written offline, and what the record must then say."""
    from inspect_ai.model import ModelCall

    def request(log):
        event = next(e for s in log.samples for e in s.events if e.event == "model")
        event.call = ModelCall(request={"max_tokens": 77, "thinking": {"type": "mutated"}, "temperature": 0.5}, response={})

    def served(log):
        log.samples[0].output.model = "served-mutated"

    def metadata(key):
        return lambda log: log.eval.metadata.update({key: "mutated"})

    def plan(log):
        log.eval.dataset.sample_ids = ["D03", "D05"]
        log.eval.config.epochs = 2

    def no_samples(log):
        log.samples = []

    def latency(log):
        log.samples[0].total_time = 12.5

    def effort(log):
        log.plan.config.reasoning_effort = "medium"

    def turns(log):
        log.eval.config.turn_limit = 5

    def cap(log):
        log.plan.config.max_tokens = 333

    return {
        "provider": (lambda log: setattr(log.eval, "model", "other/mutated"), lambda r: r["provider"] == "other"),
        "model": (lambda log: setattr(log.eval, "model", "other/mutated"), lambda r: r["model"] == "other/mutated"),
        "configuration": (metadata("configuration"), lambda r: r["configuration"] == "mutated"),
        "system_text": (metadata("system_text"), lambda r: r["system_text"] == "mutated"),
        "served_models": (served, lambda r: r["served_models"] == ["served-mutated"]),
        "request_parameters": (request, lambda r: r["request_parameters"] == {"thinking": {"type": "mutated"}, "temperature": 0.5, "max_tokens": 77}),
        "reasoning.sent": (request, lambda r: r["reasoning"]["sent"] == {"type": "mutated"}),
        "output_cap.sent": (request, lambda r: r["output_cap"]["sent"] == 77),
        "reasoning.setting": (effort, lambda r: r["reasoning"]["setting"] == "medium"),
        "reasoning.requested": (effort, lambda r: r["reasoning"]["requested"] == "medium"),
        "engine.version": (lambda log: log.eval.packages.update({"inspect_ai": "0.3.1"}), lambda r: r["engine"]["version"] == "0.3.1"),
        "effective_limits": (turns, lambda r: r["effective_limits"]["model_turns"] == 5),
        "requested_limits": (turns, lambda r: r["requested_limits"]["model_turns"] == 5),
        "output_cap.requested": (cap, lambda r: r["output_cap"]["requested"] == 333),
        "limit_notes.provider_calls": (turns, lambda r: r["limit_notes"]["provider_calls"] == "5 model turns allow 6 provider calls"),
        "cases": (plan, lambda r: r["cases"] == [{"case_id": c, "repeat": n} for c in ("D03", "D05") for n in (0, 1)]),
        "inspect_status": (lambda log: setattr(log, "status", "error"), lambda r: r["inspect_status"] == "error"),
        "episodes": (latency, lambda r: r["episodes"][0]["latency_seconds"] == 12.5),
        "tool_loop_observed": (no_samples, lambda r: r["tool_loop_observed"] is False),
    }


def test_chapter_03_run_record_table_matches_the_fields_the_code_writes_and_where_each_comes_from(page, tmp_path, monkeypatch):
    """#62 Tightened F: the rows are the fields written; a row sourced from the log follows a change of that value in a log; a row sourced from the re-summary appears only under `summarised_by`."""
    import platform
    import types

    from _record_helpers import live_record, make_log, resummary

    from hypotrail.agentic import live as agentic_live

    rows = table_rows(page, "run-record-fields", "data-field")
    mutations = _log_mutations()
    logs = {"baseline": make_log(tmp_path, "baseline")}
    for field in {f for f, (e, _) in mutations.items()}:
        logs[field] = make_log(tmp_path, field.replace(".", "-"), edit=mutations[field][0])
    hashes = {"before": "b" * 64, "after": "b" * 64}
    monkeypatch.setattr(platform, "python_version", lambda: "3.99.1")
    monkeypatch.setattr(platform, "platform", lambda *a, **k: "SummariserOS-1")
    monkeypatch.setattr(platform, "machine", lambda: "summ64")
    monkeypatch.setattr(agentic_live, "metadata", types.SimpleNamespace(version=lambda name: "9.9.9"))
    again = {k: resummary(out, location, database_sha256=hashes) for k, (out, location) in logs.items()}
    live = {k: live_record(tmp_path, monkeypatch, location, name=f"live-{n}") for n, (k, (out, location)) in enumerate(logs.items())}

    # the rows are the fields the code writes, in both kinds of record
    assert set(rows) == _flattened(live["baseline"]) == _flattened(again["baseline"])
    sources = {"run": {"log", "request", "run", "code", "null"}, "resummary": {"log", "code", "summarised_by"}}
    for field, row in rows.items():
        assert row["attrs"]["data-run"] in sources["run"] and row["attrs"]["data-resummary"] in sources["resummary"], field
        for column, record in (("data-run", live), ("data-resummary", again)):
            if row["attrs"][column] != "log":
                continue
            # a value the table says is the log's follows the log
            assert field in mutations, f"{field} is sourced from the log but no test changes it in a log"
            assert not mutations[field][1](record["baseline"]), (field, "the baseline already holds the mutated value")
            assert mutations[field][1](record[field]), (column, field)

    for field, row in rows.items():
        attrs = row["attrs"]
        if attrs["data-resummary"] == "summarised_by":
            key = attrs["data-summarised-key"]
            assert _value(again["baseline"], field) is None, field
            assert again["baseline"]["summarised_by"][key] is not None, field
            if field != "reasoning.note":
                assert _value(live["baseline"], field) is not None, field  # the Attempt's own value, in a record the Attempt writes
        if attrs["data-run"] == "null":
            assert live["baseline"][field] is None, field
    assert set(rows["summarised_by"]["attrs"]["data-keys"].split()) == set(again["baseline"]["summarised_by"])
    assert again["baseline"]["summarised_by"] == {
        "python": "3.99.1", "hardware": "SummariserOS-1", "machine": "summ64", "inspect_version": "9.9.9",
        "reasoning_note": agentic_live.REASONING_NOTE, "database_sha256_given_by_caller": hashes,
    }
    assert live["baseline"]["reasoning"]["note"] == agentic_live.REASONING_NOTE and live["baseline"]["python"] == "3.99.1"


def test_chapter_03_says_a_re_summary_keeps_the_logs_facts_and_that_the_licence_line_does_not_apply(page):
    """#62 and D-012 on chadlis/hypotrail#75 items 4, 7 and 9: the prose around the table of run.json fields."""
    paragraph = next(p for p in re.findall(r"<p>.*?</p>", page, re.S) if "Where each field of <code>run.json</code> comes from" in p)
    for text in ("<code>summarised_by</code>", "takes no model, Cases or Repeats from its caller", "calls no model and no tool", "the pinned Inspect's <code>EvalSpec</code> has no interpreter or platform field"):
        assert text in paragraph
    assert page.index('id="run-request-source"') < page.index("Where each field of <code>run.json</code> comes from") < page.index('id="run-record-fields"')
    assert "The model licence line of the specification's §3 does not apply to a remote provider: the record has no field for it." in page
    assert 'href="#run-record-fields"' in page


# --- chapter 13: `run agent` (#74) ------------------------------------------------------------------------------------------------


def run_agent_chapter() -> str:
    return (HANDBOOK / "chapters" / "13-run-agent.html").read_text(encoding="utf-8")


class _Linked(HTMLParser):
    """For each text chunk, whether it lies inside an `<a>` element, and that element's href."""

    def __init__(self):
        super().__init__()
        self.links, self.chunks = [], []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs).get("href"))

    def handle_endtag(self, tag):
        if tag == "a" and self.links:
            self.links.pop()

    def handle_data(self, data):
        self.chunks.append((data, list(self.links)))


def test_chapter_13_names_the_case_digests_key_only_inside_a_link_to_the_attempt_manifest_table_of_chapter_04():
    """Every occurrence of the key's name in chapter 13 is inside a link to chapter 04's `record-fields`.

    Its limit: a paraphrase of the key that does not spell its name is outside what this test reads.
    """
    parser = _Linked()
    parser.feed(run_agent_chapter())
    occurrences = [links for data, links in parser.chunks for _ in range(data.count("case_digests"))]
    assert occurrences, "chapter 13 does not name case_digests"
    assert all("#record-fields" in links for links in occurrences), occurrences


def test_chapter_13_keeps_the_six_tables_it_had_and_gains_none_for_the_case_digests():
    ids = re.findall(r'<table[^>]*\bid="([^"]+)"', run_agent_chapter())
    assert sorted(ids) == sorted(["run-agent-flags", "run-agent-codes", "run-agent-config", "run-agent-digests", "run-agent-files", "adr-map-run-agent"])
    assert len(ids) == 6


def test_chapter_12_names_the_one_function_that_digests_a_configuration():
    """R1-07: the handbook says where the Configuration digest is computed; the function exists in the core."""
    from hypotrail.core import exposure

    chapter = " ".join(re.sub(r"<[^>]+>", "", (HANDBOOK / "chapters" / "12-freeze-and-exposure.html").read_text(encoding="utf-8")).split())
    assert callable(exposure.configuration_digest)
    assert "one function of the core, exposure.configuration_digest" in chapter and "so the two cannot drift" in chapter


def test_chapter_13_says_the_served_model_comes_from_the_outputs_not_from_the_eval_name():
    """R1-04: the handbook states where `served_model` comes from, as the code takes it."""
    text = " ".join(re.sub(r"<[^>]+>", "", run_agent_chapter()).split())
    assert "the one the provider reports in the Episodes' outputs (output.model" in text
    assert "The model the log reports." not in text and "mockllm/model in every test" not in text


def test_chapter_13_says_both_models_are_always_recorded_and_a_provider_prefix_alone_is_no_difference():
    """D-012 on chadlis/hypotrail#75 item 11: nothing is hidden because both names are always kept; the prefix is not a difference."""
    text = " ".join(re.sub(r"<[^>]+>", "", run_agent_chapter()).split())
    assert "are always recorded side by side" in text and "a provider prefix alone is not a difference" in text
    assert "when they differ, both are shown" not in text
    assert "The output without --json shows both names on its first line, as recorded" in text and "computes no flag from them" in text  # R3-02


def test_the_run_agent_flag_table_equals_the_parser_and_says_which_flags_belong_to_llm_live(page):
    from hypotrail.agentic import run
    from hypotrail.cli import build_parser

    parser = build_parser()
    run_parser = next(a for a in parser._actions if getattr(a, "choices", None) and "run" in a.choices).choices["run"]
    agent = next(a for a in run_parser._actions if getattr(a, "choices", None) and "agent" in a.choices).choices["agent"]
    options = {flag: action for action in agent._actions for flag in action.option_strings if flag not in ("-h", "--help")}
    rows = attrs_of(page, "run-agent-flags", "data-flag")
    assert set(rows) == set(options)
    for flag, row in rows.items():
        assert (row["data-required"] == "yes") == options[flag].required, flag
        assert (row["data-mode"] == "llm_live") == (flag in run.FLAGS_OF_LIVE.values()), flag
    assert set(run.FLAGS_OF_LIVE) == {"partition", "repeats", "model", "cases"}


def run_agent_refusals(tmp_path, monkeypatch):
    """Provoke each refusal of the table; return {case: (exit code, stage, set of details keys)}."""
    import sys

    from _chinook_helpers import chinook_examples, database_of, init_chinook
    from _exposure_helpers import edit_chinook_references
    from _run_agent_helpers import FAKE_KEY, agent, answering_with, fixture, live, live_args, patch_model
    from _study_helpers import init_study
    from test_study_lock import held_by_another_process

    from hypotrail.agentic import runner

    found = {}

    def record(case, result):
        code, payload, _ = result
        error = payload["error"]
        found[case] = (error["code"], code, error["stage"], set(error["details"]))

    patch_model(monkeypatch)
    study, _ = init_chinook(tmp_path, name="study")
    bike, _ = init_study(tmp_path, name="bike")
    record("request-id-empty", fixture(study, "plain", ""))
    record("other-track", fixture(bike, "plain", "r"))
    record("flag-of-the-other-mode", fixture(study, "plain", "r", "--partition", "dev"))
    for case, flag in (("partition-required", "--partition"), ("repeats-required", "--repeats"), ("model-required", "--model")):
        args = live_args("plain", "r")
        at = args.index(flag)
        del args[at : at + 2]
        record(case, agent(study, *args))
    record("configuration-not-declared", live(study, "nonesuch", "r"))
    no_scenarios = chinook_examples(tmp_path, edit=lambda declaration: declaration.pop("scenarios"), name="no-scenarios")
    record("scenarios-not-declared", fixture(study, "plain", "r", "--examples-dir", no_scenarios))
    record("partition-not-allowed", live(study, "plain", "r", partition="train"))
    record("repeats-out-of-bounds", live(study, "plain", "r", repeats=4))
    record("case-repeated", live(study, "plain", "r", cases=["D03", "D03"]))
    record("case-not-in-partition", live(study, "plain", "r", cases=["E01"]))
    with held_by_another_process(study):
        record("study-locked", live(study, "plain", "r"))
    first = live(study, "plain", "first")[1]["attempt"]
    record("retry-of-unknown", live(study, "plain", "r", "--retry-of", "nope"))
    record("request-conflict", live(study, "verify", "first"))
    examples = chinook_examples(tmp_path, name="altered-examples")
    altered, _ = init_chinook(tmp_path, name="altered", examples=examples)
    database_of(examples).write_bytes(database_of(examples).read_bytes() + b"x")
    record("data-integrity", live(altered, "plain", "r", "--examples-dir", examples))
    broken, _ = init_chinook(tmp_path, name="broken")
    (broken / "artifacts" / "memberships.csv").write_bytes(b"x")
    record("artifact-integrity", live(broken, "plain", "r"))
    corrected = edit_chinook_references(tmp_path, lambda records: records["D01"].update(rows=[[0]]), name="corrected")
    record("protocol-changed", live(study, "plain", "new", "--examples-dir", corrected))
    inspect_ai = sys.modules["inspect_ai"]
    monkeypatch.setitem(sys.modules, "inspect_ai", None)
    record("inspect-unavailable", live(study, "plain", "new"))
    sys.modules["inspect_ai"] = inspect_ai
    patch_model(monkeypatch, key=None)
    record("live-unavailable", live(study, "plain", "new"))
    patch_model(monkeypatch)
    real = runner.run_episodes

    def changes_the_database(path):
        def run(*args, **kwargs):
            location = real(*args, **kwargs)
            path.write_bytes(path.read_bytes() + b"\0")
            return location

        return run

    for case, make in (("database-changed-live", live), ("database-changed-fixture", fixture)):
        examples = chinook_examples(tmp_path, name=f"{case}-examples")
        changing, _ = init_chinook(tmp_path, name=case, examples=examples)
        monkeypatch.setattr(runner, "run_episodes", changes_the_database(database_of(examples)))
        record(case, make(changing, "plain", "r", "--examples-dir", examples))
    monkeypatch.setattr(runner, "run_episodes", real)
    patch_model(monkeypatch, answering_with(FAKE_KEY))
    leaky, _ = init_chinook(tmp_path, name="leaky")
    record("secret-in-output", live(leaky, "plain", "r"))
    early, _ = init_chinook(tmp_path, name="early")
    patch_model(monkeypatch)
    record("secret-in-output-before-running", live(early, "plain", FAKE_KEY))
    assert first["technical_status"] == "completed"
    return found


def test_the_run_agent_refusal_table_equals_the_code_exit_stage_and_details_of_each_refusal(page, tmp_path, monkeypatch):
    rows = attrs_of(page, "run-agent-codes", "data-case")
    found = run_agent_refusals(tmp_path, monkeypatch)
    assert set(rows) == set(found)
    for case, row in rows.items():
        code, exit_code, stage, details = found[case]
        assert row["data-code"] == code, case
        assert int(row["data-exit"]) == exit_code, case
        assert row["data-stage"] == stage, case
        assert words(row["data-details"]) == details, case


def test_the_run_agent_refusal_table_shows_in_its_details_cell_the_keys_of_its_data_details(page):
    """R4-03, ADR 0003: the table and its attributes agree, so a `warnings` key of the attributes is a word of the visible cell."""
    for row in parse(page).tables["run-agent-codes"]:
        if "data-case" in row["attrs"]:
            visible = words(re.sub(r"[,\s]+", " ", row["cells"][-1]["text"]).strip()) - {"none"}  # "none" is how an empty cell reads
            assert visible == words(row["attrs"]["data-details"]), row["attrs"]["data-case"]


@pytest.fixture
def run_agent_attempts(tmp_path, monkeypatch):
    """One scenario Attempt, one `llm_live` Attempt, and the `running` manifest of a third that was stopped before its terminal one."""
    from _chinook_helpers import init_chinook
    from _run_agent_helpers import fixture, live, ok, patch_model

    from hypotrail.core import artifacts

    study, _ = init_chinook(tmp_path)
    patch_model(monkeypatch)
    scenario = ok(fixture(study, "plain", "fixture"))
    native = ok(live(study, "plain", "live"))

    class Stopped(BaseException):
        pass

    real = artifacts.replace_bytes
    written = []

    def stop_at_the_terminal_manifest(study_path, relative, data):
        written.append(data)
        if len(written) == 2:
            raise Stopped
        return real(study_path, relative, data)

    monkeypatch.setattr(artifacts, "replace_bytes", stop_at_the_terminal_manifest)
    with pytest.raises(Stopped):
        live(study, "plain", "stopped")
    monkeypatch.setattr(artifacts, "replace_bytes", real)
    running = json.loads(written[0])
    return study, {"scripted_fixture": scenario, "llm_live": native}, running


def test_the_run_agent_config_and_digest_tables_equal_the_keys_a_running_and_a_terminal_manifest_hold(page, run_agent_attempts):
    study, attempts, running = run_agent_attempts
    config = attrs_of(page, "run-agent-config", "data-key")
    assert set(config) == set(attempts["llm_live"]["effective_config"]) == set(attempts["scripted_fixture"]["effective_config"])
    assert {key for key, row in config.items() if row["data-when"] == "running"} == set(running["effective_config"])
    assert running["technical_status"] == "running"
    digests = attrs_of(page, "run-agent-digests", "data-key")
    for mode, attempt in attempts.items():
        in_mode = {key for key, row in digests.items() if row["data-mode"] in ("both", mode)}
        assert in_mode == set(attempt["effective_config"]["input_digests"]), mode


def test_the_run_agent_file_table_equals_the_files_and_roles_an_attempt_of_each_mode_writes(page, run_agent_attempts):
    study, attempts, _ = run_agent_attempts
    rows = attrs_of(page, "run-agent-files", "data-path")
    for mode, attempt in attempts.items():
        folder = study / "attempts" / attempt["attempt_id"]
        on_disk = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
        on_disk = {"inspect/LOG.eval" if path.startswith("inspect/") else path for path in on_disk}
        expected = {path for path, row in rows.items() if row["data-mode"] in ("both", mode)}
        assert on_disk == expected, mode
        listed = {"input_refs": attempt["input_refs"][-1:], "output_refs": attempt["output_refs"]}
        for path, row in rows.items():
            if row["data-mode"] not in ("both", mode) or row["data-listed"] == "no":
                continue
            refs = [ref for ref in listed[row["data-listed"]] if ref["role"] == row["data-role"]]
            assert len(refs) == 1, (mode, path)
            relative = refs[0]["path"].removeprefix(f"attempts/{attempt['attempt_id']}/")
            assert ("inspect/LOG.eval" if relative.startswith("inspect/") else relative) == path, (mode, path)
        assert {ref["role"] for ref in attempt["output_refs"]} == {row["data-role"] for row in rows.values() if row["data-mode"] in ("both", mode) and row["data-listed"] == "output_refs"}


def test_the_readme_and_the_chapters_say_run_agent_records_a_native_attempt():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "`run agent`" in readme and "--mode scripted_fixture" in readme and "--mode llm_live" in readme
    for name, stale in (
        ("04-study-and-attempts.html", "no command runs the agent into a Study yet"),
        ("11-agent-comparison.html", "nothing yet runs the agent Track into a Study"),
        ("11-agent-comparison.html", "No native Chinook Attempt"),
    ):
        assert stale not in (HANDBOOK / "chapters" / name).read_text(encoding="utf-8"), (name, stale)
    for name in ("03-agentic-track.html", "04-study-and-attempts.html", "11-agent-comparison.html"):
        assert 'href="#run-agent"' in (HANDBOOK / "chapters" / name).read_text(encoding="utf-8"), name


def test_chapter_13_says_the_banner_the_code_writes():
    from hypotrail.agentic import fixture

    chapter = run_agent_chapter()
    assert f'"{fixture.BANNER}"' in chapter
    assert f'"{fixture.BANNER}"' in (HANDBOOK / "chapters" / "03-agentic-track.html").read_text(encoding="utf-8")
    assert "It was not run in this step" not in chapter


def test_chapter_13_describes_the_kept_paid_attempt_with_the_figures_its_run_json_records():
    """#80: the one paid Attempt (2026-11-20) is kept under traces/run-agent-live-plain and the chapter states what its run.json records."""
    kept = HANDBOOK / "traces" / "run-agent-live-plain"
    record = json.loads((kept / "run.json").read_text())
    manifest = json.loads((kept / "attempt.json").read_text())
    chapter = " ".join(re.sub(r"<[^>]+>", "", run_agent_chapter()).split())
    assert manifest["technical_status"] == "completed" and manifest["mode"] == "llm_live" and manifest["request_id"] == "live-check-1"
    assert record["model"] == "anthropic/claude-sonnet-5-5" and record["served_models"] == ["claude-sonnet-5-5"]
    assert f"anthropic/claude-sonnet-5-5 and the served_model the outputs report is claude-sonnet-5-5" in chapter
    for episode in record["episodes"]:
        assert episode["status"] == "produced" and episode["cost"] is None
        assert f"{episode['output_tokens']} output tokens and {episode['total_tokens']:,} total tokens" in chapter
    assert [e["case_id"] for e in record["episodes"]] == ["D03", "D05"]
    assert "The cost is not observable" in chapter and "docs/handbook/traces/run-agent-live-plain/" in chapter
    for name in ("attempt.json", "observation_set.json", "observations.jsonl", "population.json", "run.json"):
        assert (kept / name).is_file(), name
    assert (kept / record["inspect_log"]).is_file()
    assert f'href="traces/run-agent-live-plain/{record["inspect_log"]}"' in run_agent_chapter()


def plain_chapter(name):
    """A chapter as a reader reads it: its HTML tags removed and its whitespace collapsed."""
    return " ".join(re.sub(r"<[^>]+>", "", (HANDBOOK / "chapters" / name).read_text(encoding="utf-8")).split())


# #77, D-011 on chadlis/hypotrail#75 and Tightened B2: each phrase named a `spike live` or library-fixture execution an Attempt; each becomes its reword.
ATTEMPT_REWORDS = {
    "01-feasibility-spike.html": {
        "what the spike's own Attempt recorded": "what the spike's own execution recorded",
    },
    "03-agentic-track.html": {
        "before and after the Attempt, which must be equal": "before and after the library fixture's execution, which must be equal",
        "With no --case, the Attempt takes the two dev join Cases": "With no --case, the spike live execution takes the two dev join Cases",
        "The output is scanned for the key before the Attempt reports": "The output is scanned for the key before the execution reports",
        "Before any provider call, the Attempt asks Inspect's own request building": "Before any provider call, the execution asks Inspect's own request building",
        "the Attempt is refused with REASONING_NOT_EXPLICIT": "the execution is refused with REASONING_NOT_EXPLICIT",
        "the Cases of the Attempt": "the Cases of the execution",
        "the SHA-256 of the Chinook file before and after the Attempt;": "the SHA-256 of the Chinook file before and after the execution;",
        "the request the Attempt itself made": "the request of the execution that wrote the record",
    },
}


@pytest.mark.parametrize("name", sorted(ATTEMPT_REWORDS))
def test_no_chapter_calls_a_spike_live_or_library_fixture_execution_an_attempt(name):
    text = plain_chapter(name)
    for old, new in ATTEMPT_REWORDS[name].items():
        assert old not in text, old
        assert new in text, new


def test_the_new_chapter_03_sentence_and_the_readme_do_not_call_an_execution_or_an_attempt_the_word_run():
    """#77 Tightened B2 and GLOSSARY Attempt's avoid-list: "run" is not the noun for an execution or an Attempt."""
    chapter = plain_chapter("03-agentic-track.html")
    assert "run agent --mode scripted_fixture records the same scenarios as a scenario Attempt of a Study" in chapter
    # the README sentence that said "an opt-in paid live Attempt" was cut by D-039 on chadlis/hypotrail#75; the rule "run is not the noun" is guarded over the corpus by test_run_noun.py


def test_chapters_01_and_03_name_an_attempt_only_where_a_study_records_it():
    """#77 AC2: what is left of the word in chapters 01 and 03 is the generic line, the two commands that record an Attempt in a Study and the row that says a spike live execution is not one."""
    assert "Attempt" not in plain_chapter("01-feasibility-spike.html")
    text = plain_chapter("03-agentic-track.html")
    contexts = [text[max(0, m.start() - 30) : m.end() + 30] for m in re.finditer("Attempt", text)]
    assert len(contexts) == 5, contexts
    assert "to be checked on an Attempt." in contexts[0]  # the generic line
    assert "as a scenario Attempt of a Study" in text and "records a native Attempt of the llm_live Mode in a Study" in text
    # the this_attempt row names the Attempt of run agent, and says in its own words that a spike live execution is not one
    assert "llm_live Attempt (chapter 13)" in text and "a spike live execution is not an Attempt, since it records nothing in a Study" in text


def test_chapter_03_this_attempt_row_says_it_names_the_request_of_the_execution_that_wrote_the_record(page):
    """#77 D-011 on chadlis/hypotrail#75 C: the value keeps its name; its row says what it means, for a `spike live` execution and for a `run agent` Attempt."""
    rows = table_rows(page, "run-request-source", "data-request-source")
    text = rows["this_attempt"]["text"]
    assert "execution" in text and "the request the Attempt itself made" not in text
    assert "spike live" in text and "run agent" in text



# --- chapter 04: where the Workloads are found (#23, D-016 on chadlis/hypotrail#75) ------------------------------------------------------------------------


def _commands_taking_the_examples_flag():
    import argparse

    from hypotrail.cli import build_parser

    found = set()

    def walk(parser, path):
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    walk(child, [*path, name])
        if any("--examples-dir" in a.option_strings for a in parser._actions):
            found.add(" ".join(path))

    walk(build_parser(), [])
    return found


def test_the_workload_inputs_table_lists_exactly_what_the_resolver_reads(page):
    """D-016 on chadlis/hypotrail#75, #23: the resolver takes the flag and the checkout default, and reads no environment variable."""
    import inspect

    from hypotrail.core import data

    resolver = data.resolve_examples_dir
    rows = attrs_of(page, "workload-inputs", "data-input")
    assert set(rows) == {"--examples-dir", "checkout-default"}
    assert [rows[k]["data-order"] for k in ("--examples-dir", "checkout-default")] == ["1", "2"]
    assert list(inspect.signature(resolver).parameters) == ["examples_dir"]  # the flag's dest, and nothing else
    assert "default_examples_dir" in resolver.__code__.co_names  # the checkout default
    assert not {"environ", "getenv", "environb"} & set(resolver.__code__.co_names)  # no variable
    assert not {"environ", "getenv"} & set(data.default_examples_dir.__code__.co_names)
    assert "HYPOTRAIL_EXAMPLES_DIR" not in page.split('id="workload-inputs"')[1].split("</table>")[0]  # the table names no variable


def test_the_chapter_04_refusal_row_names_the_four_cases_the_resolver_observes_of_the_default_examples():
    # 10-R4-05, ADR 0003 (the handbook describes the behaviour): the same four facts as the resolver's messages.
    chapter = (HANDBOOK / "chapters" / "04-study-and-attempts.html").read_text(encoding="utf-8")
    row = " ".join(re.sub(r"<[^>]+>", " ", re.search(r'<tr data-code="EXAMPLES_DIR_NOT_FOUND".*?</tr>', chapter, re.S)[0]).split())
    for fact in ("does not exist", "a link whose target does not exist", "is not a directory", "holds no Workload lock"):
        assert fact in row, fact


def test_the_workload_commands_table_equals_the_commands_the_parser_gives_the_flag(page):
    rows = attrs_of(page, "workload-commands", "data-command")
    assert set(rows) == _commands_taking_the_examples_flag()


def test_the_workload_refusal_table_equals_the_code_exit_stage_and_details_of_the_refusal(page, monkeypatch, tmp_path):
    from hypotrail.core import data

    monkeypatch.setattr(data, "default_examples_dir", lambda: tmp_path / "no-such-checkout" / "examples")
    with pytest.raises(Exception) as caught:
        data.resolve_examples_dir(None)
    error = caught.value
    rows = attrs_of(page, "workload-refusal", "data-code")
    assert set(rows) == {error.code}
    row = rows[error.code]
    assert (int(row["data-exit"]), row["data-stage"], words(row["data-details"])) == (error.exit_code, error.stage, set(error.details))
    assert "--examples-dir" in error.message


def test_the_readme_states_the_supported_install_and_that_any_other_install_passes_the_flag():
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    assert "The supported install is a checkout with `uv sync`" in readme
    assert "any other install passes `--examples-dir`" in readme


# --- chapter 14: the Study report (#85) ----------------------------------------------------------------------------------------


def test_the_report_sections_table_equals_the_sections_the_code_renders_in_order(page):
    from hypotrail.report import render

    rows = attrs_of(page, "report-sections", "data-section")
    ordered = sorted(rows.items(), key=lambda item: int(item[1]["data-order"]))
    assert [int(row["data-order"]) for _, row in ordered] == list(range(1, len(render.SECTIONS) + 1))
    assert [(key, row["data-heading"]) for key, row in ordered] == list(render.SECTIONS)


def test_the_report_denial_table_lists_the_one_sentence_the_code_writes_that_names_readiness_safety_and_independence(page):
    from hypotrail.report import render

    rows = table_rows(page, "report-denials", "data-denial")
    assert [r["text"].strip() for r in rows.values()] == [render.DENIAL]


def test_the_report_refusal_table_equals_the_code_exit_stage_and_details_of_each_refusal(page, tmp_path):
    from _assess_helpers import fresh_study
    from _chinook_helpers import init_chinook
    from _report_helpers import report
    from _study_helpers import examples_copy

    from hypotrail.core import lock

    out = tmp_path / "out.html"
    dev, _ = fresh_study(tmp_path / "dev", "seasonal_7")
    public, _ = fresh_study(tmp_path / "public", "seasonal_7", partition="public_check")
    tampered, _ = fresh_study(tmp_path / "tampered", "seasonal_7")
    (tampered / "datasets" / "day.csv").write_bytes((tampered / "datasets" / "day.csv").read_bytes() + b"\n")
    refusals = {
        "STUDY_NOT_FOUND": [report(tmp_path / "nothing", out)],
        "REPORT_OUTPUT_INVALID": [report(dev, dev / "r.html"), report(dev, tmp_path), report(dev, tmp_path / "no-folder" / "r.html")],
        "ARTIFACT_INTEGRITY": [report(tampered, out)],
        "PROTOCOL_CHANGED": [report(public, out, "--examples-dir", examples_copy(tmp_path, rows=lambda t: t[0].update(cnt=str(int(t[0]["cnt"]) + 1))))],
    }
    with lock.writer_lock(public):
        refusals["STUDY_LOCKED"] = [report(public, out)]
    rows = attrs_of(page, "report-refusals", "data-code")
    assert set(rows) == set(refusals)  # a Study of either Track is reported: no refusal names a Track any more
    chinook, _ = init_chinook(tmp_path / "chinook")
    assert report(chinook, tmp_path / "chinook.html")[0] == 0
    for code, cases in refusals.items():
        for status, payload, _ in cases:
            error, row = payload["error"], rows[code]
            assert error["code"] == code
            assert (int(row["data-exit"]), row["data-stage"], words(row["data-details"])) == (status, error["stage"], set(error["details"])), code
    assert {payload["error"]["details"]["reason"] for _, payload, _ in refusals["REPORT_OUTPUT_INVALID"]} == {"inside_study", "is_directory", "no_folder"}
    assert not out.exists()


def test_the_readme_and_chapters_05_and_12_say_a_report_exists():
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    assert "There is no report yet" not in readme and "hypotrail report --study runs/bike --out" in readme and "`report/`" in readme
    for name in ("05-assessments.html", "12-freeze-and-exposure.html"):
        text = (HANDBOOK / "chapters" / name).read_text(encoding="utf-8")
        assert 'href="#report"' in text and "nothing summarises them yet" not in text and "are issue #10" not in text, name


def _chinook_page(tmp_path):
    """(page document, Attempt of a native llm_live execution, the cell lines of one matrix cell) of a Chinook Study rendered by `report`."""
    from _chinook_helpers import init_chinook
    from _report_helpers import doc_of, lines_of, report
    from _run_agent_helpers import ok, patch_model
    from _run_agent_helpers import live as live_through_mock

    study, _ = init_chinook(tmp_path)
    with pytest.MonkeyPatch.context() as mp:
        patch_model(mp)
        attempt = ok(live_through_mock(study, "plain", "live", cases=["D03"], repeats=1))
    from _agent_compare_helpers import assess, observation_set_of

    assessment = assess(study, observation_set_of(study, attempt))
    out = tmp_path / "page.html"
    assert report(study, out)[0] == 0
    doc = doc_of(out)
    cell = doc.cells(f"matrix-{assessment['assessment_id']}")[0][1]
    return doc, attempt, lines_of(cell)


def test_the_report_matrix_cell_table_equals_the_lines_the_code_writes_for_a_cell_and_the_criteria_it_renders(page, tmp_path):
    from hypotrail.core.chinook_contract import CRITERIA
    from hypotrail.report import render_agent

    rows = attrs_of(page, "report-matrix-cell", "data-line")
    ordered = [key for key, row in sorted(rows.items(), key=lambda item: int(item[1]["data-order"]))]
    assert tuple(ordered) == render_agent.CELL_LINES
    assert tuple(key for key in ordered if key in CRITERIA) == CRITERIA
    _, _, lines = _chinook_page(tmp_path)
    rendered = [line.split(":")[0] for line in lines]
    assert [name for name in rendered if name in CRITERIA] == list(CRITERIA)  # the cell of a real page holds these Criteria, in this order
    assert rendered[1] == "Execution" and rendered[-1] == "Trace" and lines[0].startswith("Case ")


def test_the_report_counter_columns_table_equals_the_columns_the_code_writes_per_criterion(page, tmp_path):
    from hypotrail.report import render_agent

    rows = attrs_of(page, "report-criteria-columns", "data-column")
    ordered = [key for key, row in sorted(rows.items(), key=lambda item: int(item[1]["data-order"]))]
    assert tuple(ordered) == render_agent.CRITERIA_COLUMNS
    doc, _, _ = _chinook_page(tmp_path)
    [name] = [t for t in doc.tables if t.startswith("criteria-")]
    assert tuple(c["text"] for c in doc.tables[name][0]) == render_agent.CRITERIA_COLUMNS


def test_the_report_live_fields_table_equals_the_rows_the_code_writes_for_a_live_attempt_and_the_banner_is_quoted(page, tmp_path):
    from hypotrail.agentic import fixture
    from hypotrail.report import render_agent

    rows = attrs_of(page, "report-live-fields", "data-field")
    ordered = [key for key, row in sorted(rows.items(), key=lambda item: int(item[1]["data-order"]))]
    assert tuple(ordered) == render_agent.LIVE_FIELDS
    doc, attempt, _ = _chinook_page(tmp_path)
    shown = []
    for name in (row[0] for row in doc.body(f"live-{attempt['attempt_id']}")):
        name = "Limit note, <name>" if name.startswith("Limit note, ") else name
        if name not in shown:
            shown.append(name)
    assert shown == list(render_agent.LIVE_FIELDS)
    chapter = (HANDBOOK / "chapters" / "14-report.html").read_text(encoding="utf-8")
    assert f'"{fixture.BANNER}"' in chapter and render_agent.SELF_CHECK_HEADING in chapter


def test_the_readme_and_chapters_say_the_report_covers_both_tracks():
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    assert "a Bike Study for now" not in readme and "the tool-using agent Track's report comes next" not in readme
    chapters = {name: (HANDBOOK / "chapters" / name).read_text(encoding="utf-8") for name in ("05-assessments.html", "12-freeze-and-exposure.html", "14-report.html")}
    assert "<code>report</code> (Bike)" not in chapters["12-freeze-and-exposure.html"] and "A report for Bike Studies" not in chapters["12-freeze-and-exposure.html"]
    assert "Bike Studies only" not in chapters["14-report.html"] and "the next ticket" not in chapters["14-report.html"]


# --- chapter 15: data fetch (#22) -----------------------------------------------------------------------------------


def test_the_data_fetch_flag_table_equals_the_parser(page):
    from hypotrail.cli import build_parser

    data = next(a for a in build_parser()._actions if getattr(a, "choices", None) and "data" in a.choices).choices["data"]
    fetch = next(a for a in data._actions if getattr(a, "choices", None) and "fetch" in a.choices).choices["fetch"]
    options = {flag: a.required for a in fetch._actions for flag in a.option_strings if flag not in ("-h", "--help")}
    rows = attrs_of(page, "data-fetch-flags", "data-flag")
    assert {flag: row["data-required"] == "true" for flag, row in rows.items()} == options


def test_the_data_fetch_refusal_table_equals_the_code_exit_stage_and_details_of_each_refusal(page, tmp_path):
    from _fetch_helpers import fetch_refusals

    found = fetch_refusals(tmp_path)
    rows = attrs_of(page, "data-fetch-refusals", "data-code")
    assert set(rows) == set(found)
    for code, cases in found.items():
        for status, error in cases:
            row = rows[code]
            assert (int(row["data-exit"]), row["data-stage"], words(row["data-details"])) == (status, error["stage"], set(error["details"])), code
    reasons = {code: {error["details"]["reason"] for _, error in cases if "reason" in error["details"]} for code, cases in found.items()}
    text = {code: row["text"] for code, row in table_rows(page, "data-fetch-refusals", "data-code").items()}
    for code, named in reasons.items():
        for reason in named:
            assert reason in text[code], (code, reason)  # each reason the code gives is named in its row


def test_the_data_fetch_chapter_states_the_generic_cap_and_that_a_file_is_re_acquired_by_removing_it_first(page):
    from hypotrail.core import fetch

    match = re.search(r"<code data-cap>(\d+) bytes</code>", page)
    assert match and int(match.group(1)) == fetch.GENERIC_CAP_BYTES
    chapter = " ".join(re.sub(r"<[^>]+>", " ", (HANDBOOK / "chapters" / "15-data-fetch.html").read_text(encoding="utf-8")).split())
    assert "To acquire a file again, remove it first." in chapter
    assert "never replaces a file" in chapter and "no automatic mirror" in chapter


def test_the_data_fetch_chapter_states_how_each_cut_transfer_ends_and_the_limit_where_the_lock_gives_no_size():
    # #22 Tightened K (D-020 on chadlis/hypotrail#75): a framed cut (Content-Length, chunked) and an unframed body shorter than the lock's size_bytes
    # are exit 4 (interrupted); an equal size with a wrong hash, a framed whole body that differs, and an unframed short body where
    # the lock gives no size (archive, notice) are exit 3 and name the verified bundle; the handbook states this limit.
    chapter = (HANDBOOK / "chapters" / "15-data-fetch.html").read_text(encoding="utf-8")
    cut = re.search(r"<p data-cut-transfers>(.*?)</p>", chapter, re.S)
    assert cut, "no paragraph states how a cut transfer ends"
    text = " ".join(re.sub(r"<[^>]+>", " ", cut[1]).split())
    for word in ("Content-Length", "chunked", "unframed", "size_bytes", "interrupted", "DOWNLOAD_FAILED", "DOWNLOAD_INTEGRITY", "data verify", "exit 4", "exit 3"):
        assert word in text, word
    assert "the framing http.client computed" in text and "+12" in text and "negative" in text and "ignores" in text  # #22 L
    assert "no usable Content-Length" not in text  # the command parses no header: the framing is http.client's
    assert "fewer bytes" in text and "equal size" in text and "no size" in text and "archive" in text and "notice" in text
    assert "is not used to call a short body a cut one" not in text


def test_the_readme_install_block_has_the_data_fetch_line_and_says_how_a_clean_install_acquires_the_data():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = readme.split("```")[1]
    assert re.search(r"^uv run python -m hypotrail data fetch --lock \S+ --dest \S+", block, re.M)
    flat = " ".join(readme.split())
    assert "acquires it with `data fetch`" in flat and "to acquire it again, remove it first" in flat


# --- #87: the record of the T24 walk (clean install, README path) -------------------------------------

WALK = HANDBOOK / "walk-t24.html"
README_ID_FLAGS = ("--observations", "--references", "--control", "--candidate")


class WalkSteps(HTMLParser):
    """Reads the steps of the walk record: kind, exit code, command and output of each `li.step`."""

    def __init__(self):
        super().__init__()
        self.steps, self._step, self._into = [], None, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "li" and "data-step" in attrs:
            exit_code = attrs.get("data-exit")
            self._step = {"kind": attrs["data-kind"], "exit": None if exit_code is None else int(exit_code), "command": None, "output": None}
            self.steps.append(self._step)
        elif tag == "pre" and self._step is not None:
            for field in ("command", "output"):
                if f"data-{field}" in attrs:
                    self._into = field
                    self._step[field] = ""

    def handle_endtag(self, tag):
        if tag == "pre":
            self._into = None
        elif tag == "li":
            self._step = None

    def handle_data(self, data):
        if self._into is not None:
            self._step[self._into] += data


def walk_steps(text=None):
    parser = WalkSteps()
    parser.feed(WALK.read_text(encoding="utf-8") if text is None else text)
    return parser.steps


def readme_path(readme_text=None):
    """The commands of the README's install block: comments and `[optional]` parts removed."""
    block = (readme_text or (ROOT / "README.md").read_text(encoding="utf-8")).split("```")[1]
    lines = (re.sub(r"\s+#.*$", "", line).strip() for line in block.splitlines())
    return [re.sub(r"\s*\[[^\]]*\]", "", line) for line in lines if line]


def same_command(written, recorded):
    """The recorded command is the README's, each ID placeholder (`OBSERVATION_SET_ID`) filled by one token."""
    words, filled = written.split(), recorded.split()
    return len(words) == len(filled) and all(re.fullmatch(r"[A-Z]+(?:_[A-Z]+)*_ID", word) or word == token for word, token in zip(words, filled))


def walk_removed_commands(text=None):
    """The commands the record names as removed from the README's path after the walk (`<code data-removed-command>`)."""
    page = WALK.read_text(encoding="utf-8") if text is None else text
    return [html.unescape(command) for command in re.findall(r"<code data-removed-command>(.*?)</code>", page, re.S)]


def walk_problems(steps, path, removed=None):
    """What is wrong with a walk record against the README's path; an empty list when it holds.

    A recorded README command that is no longer in the path is accepted only when the record names it as removed
    (`removed`, by default read from the record); a command that is in the path is never excused.
    """
    removed = walk_removed_commands() if removed is None else removed
    removed = [re.sub(r"\s*\[[^\]]*\]", "", command) for command in removed]  # an optional part is no part of the path, as in readme_path
    problems = [f"the removed command is still in the README path: {command}" for command in removed if command in path]
    paid = [command for command in path if "--mode llm_live" in command]
    ran = [command for command in path if command not in paid]
    not_run = [step for step in steps if step["kind"] == "not-run"]
    if [step["command"] for step in not_run if "llm_live" in step["command"]] != paid:
        problems.append("the paid README commands are not listed as not run, as written")
    if any(step["exit"] is not None or step["output"] is not None for step in not_run):
        problems.append("a command listed as not run carries an exit code or an output")
    recorded = [step["command"] for step in steps if step["kind"] == "readme"]
    recorded = [command for command in recorded if not any(same_command(written, command) for written in removed)]  # named as removed by the record
    if len(recorded) != len(ran) or not all(same_command(written, command) for written, command in zip(ran, recorded)):
        problems.append("the recorded README commands, in order, are not the commands of the README's path")
    for index, step in enumerate(steps):
        if step["kind"] == "not-run":
            continue
        if step["exit"] is None or not step["output"]:
            problems.append(f"step {index + 1} keeps no exit code or no output")
        before = "\n".join(earlier["output"] or "" for earlier in steps[:index])
        for flag in README_ID_FLAGS:
            for value in re.findall(rf"{flag} (\S+)", step["command"]):
                if value not in before:
                    problems.append(f"step {index + 1}: {flag} {value} is in no output of an earlier step")
        for study in re.findall(r"--study (\S+)", step["command"]):
            if " init --workload " in step["command"]:
                continue  # the command that creates the Study
            if not any(re.search(rf"\binit --workload \S+ --study {re.escape(study)}$", earlier["command"] or "") for earlier in steps[:index]):
                problems.append(f"step {index + 1}: the Study {study} was not created by an earlier init")
    return problems


def test_the_t24_walk_record_keeps_the_commands_of_the_readme_path_with_the_ids_they_were_filled_from():
    # #87 Tightened B: a record written without running the commands (IDs from elsewhere, an output missing, a command
    # not run) or left behind by a change to the README's commands fails; the paid commands are listed, never run.
    steps = walk_steps()
    assert walk_problems(steps, readme_path()) == []
    assert any(step["kind"] == "not-run" and "spike live" in step["command"] for step in steps)  # the paid command of the README's prose
    assert "spike live" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_t24_walk_record_names_the_walker_the_commit_and_that_an_agent_walked():
    # #87 C1: who walked, on which commit, in which environment.
    fields = dict(re.findall(r'<dd data-field="([a-z-]+)">(.*?)</dd>', WALK.read_text(encoding="utf-8"), re.S))
    assert re.search(r"<code>[0-9a-f]{40}</code>", fields["commit"])
    assert "slice-builder" in fields["walker"] and "claude.ai/code/session_" in fields["walker"]
    assert "not by the owner" in fields["executed-by"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", fields["date"])
    assert all(fields[name].strip() for name in ("os", "python", "uv"))


def _root_tokens(css, selector):
    """The `--name: value` declarations of the first `selector{...}` rule of a style block."""
    body = css.split(selector + "{", 1)[1].split("}", 1)[0]
    return dict(re.findall(r"(--[a-z0-9-]+):([^;]+);?", body))


def _rule_declarations(css, selector):
    """Every declaration (custom properties and others) of the first `selector{...}` rule, by name."""
    body = css.split(selector + "{", 1)[1].split("}", 1)[0]
    return {name.strip(): value.strip() for name, _, value in (part.partition(":") for part in body.split(";")) if name.strip()}


def test_the_t24_walk_record_follows_the_handbooks_mode_rule_light_by_default_with_the_templates_tokens_switch_and_scripts():
    # D-021 on chadlis/hypotrail#75 (B), #1 amendment "light mode by default": `data-mode="light"`, the template's base and
    # light token blocks for the tokens the page uses, its `.mode` switch (markup and CSS) and its two small scripts, all as in template.html.
    page = WALK.read_text(encoding="utf-8")
    template = (HANDBOOK / "template.html").read_text(encoding="utf-8")
    assert re.search(r'<html[^>]*\bdata-mode="light"', page) and "prefers-color-scheme" not in page
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    base, light = _root_tokens(style, ":root"), _root_tokens(style, ':root[data-mode="light"]')
    charter_base, charter_light = _root_tokens(template, ":root"), _root_tokens(template, ':root[data-mode="light"]')
    assert base and light
    assert all(charter_base.get(name) == value for name, value in base.items()), "a base token that is not the template's"
    page_rule, template_rule = _rule_declarations(style, ':root[data-mode="light"]'), _rule_declarations(template, ':root[data-mode="light"]')
    assert page_rule and all(template_rule.get(name) == value for name, value in page_rule.items()), "a light declaration that is not the template's"
    assert page_rule.get("color-scheme") == "light"  # the whole light rule, not only its tokens: removing color-scheme fails
    used = set(re.findall(r"var\((--[a-z0-9-]+)\)", style))
    assert set(base) == used, ("declared and unused", set(base) - used, "used and undeclared", used - set(base))  # every declared token is used
    assert set(light) == used & set(charter_light) and 'data-mode="light"' in style
    switch = re.search(r'<div class="mode".*?</div>', template, re.S)[0]
    assert switch in page and page.index(switch) < page.index("<main>")  # the template's switch markup
    css = [line for line in template.split("<style>", 1)[1].split("</style>", 1)[0].splitlines() if line.startswith(".mode")]
    assert len(css) == 4 and all(line in style for line in css)  # the template's .mode rules
    scripts = re.findall(r"<script>.*?</script>", template, re.S)
    assert len(scripts) == 2 and all(script in page for script in scripts)  # `?mode=` and localStorage `doc-mode`, then the switch handler
    assert "?mode=" not in page.replace(scripts[0], "") and 'localStorage.getItem("doc-mode")' in scripts[0]
WALKED_REMOVED_COMMAND = "uv run python -m hypotrail compare --study runs/chinook --control ASSESSMENT_ID --candidate ASSESSMENT_ID [--factor model]"  # as README.md had it at 2d1583f, the commit walked


def test_the_readme_path_carries_no_command_it_says_is_refused_and_the_walk_record_names_the_removed_command_as_it_stood():
    # 10-R1-04, #87 C5: the walk saw the Chinook `compare` line refused (D7, COMPARISON_POPULATION_DIFFERS, exit 3). The README moves it out
    # of the code block into a sentence that names no Assessment that does not exist; the record names the removal, exactly as the
    # command stood at the walked commit, as a correction made after the walk, and marks D7's old wording.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block, after = readme.split("```")[1], readme.split("```", 2)[2]
    assert "compare --study runs/chinook" not in block and "COMPARISON_POPULATION_DIFFERS" not in block
    sentence = next(part for part in re.split(r"\n\n", after) if "compare --study runs/chinook" in part)
    assert "two agent Assessments over the same Cases" in sentence and "makes none" in sentence
    assert "Campaign" not in sentence and "`plain`" not in sentence  # the live Campaign did not run: no Assessment of it exists to name
    page = WALK.read_text(encoding="utf-8")
    corrections = re.search(r'<h2 id="corrections">.*?(?=<h2 )', page, re.S)[0]
    assert 'data-corrections="none"' not in corrections and "Campaign" not in corrections
    assert "10-R1-04" in corrections and "after the walk" in corrections and "D7" in corrections and "removed" in corrections
    assert walk_removed_commands() == [WALKED_REMOVED_COMMAND]
    assert any(same_command(re.sub(r"\s*\[[^\]]*\]", "", WALKED_REMOVED_COMMAND), step["command"]) for step in walk_steps() if step["kind"] == "readme")
    d7 = re.search(r'<li data-difficulty="D7">.*?</li>', page, re.S)[0]
    assert "wording before the correction" in d7
    assert walk_problems(walk_steps(), readme_path()) == []


def test_the_removed_command_is_the_line_the_readme_had_at_the_commit_the_walk_ran():
    walked = subprocess.run(["git", "show", "2d1583f:README.md"], cwd=ROOT, capture_output=True, text=True)
    if walked.returncode != 0:
        pytest.skip("the walked commit 2d1583f is not in this clone; the fixed copy WALKED_REMOVED_COMMAND is what the other test reads")
    line = next(line for line in walked.stdout.splitlines() if "compare --study runs/chinook" in line)
    assert re.sub(r"\s+#.*$", "", line).strip() == WALKED_REMOVED_COMMAND


def test_the_walk_check_excuses_a_missing_readme_command_only_when_the_record_names_it_as_removed():
    # #87 B stays strict: it ignores no README command in general.
    steps, path = walk_steps(), readme_path()
    removed = walk_removed_commands()
    assert walk_problems(steps, path, removed=[]) != []  # the record would not name the Chinook compare: the check fails
    status = next(command for command in path if " status " in command)
    shorter = [command for command in path if command != status]
    assert walk_problems(steps, shorter) != []  # another command missing from the README, not named by the record
    assert walk_problems(steps, path + removed) != []  # a command the record names as removed that is back in the path
    assert walk_problems(steps, path, removed=removed) == []


def test_the_walk_record_says_only_d3_was_handed_back_to_89_for_triage_which_was_open_on_the_record_date_with_no_code_or_readme_label():
    # 10-R1-05, #87 C5: #89 is `needs-triage` and asks whether the code or the README changes, so the record labels D3 neither. D3 says what
    # #89 says (`status --json` lists the References id, but it comes last in the path).
    text = WALK.read_text(encoding="utf-8")
    record_date = re.search(r'<dd data-field="date">(.*?)</dd>', text, re.S)[1]  # the record's own date, read from the record
    intro = re.search(r'<h2 id="difficulties">.*?</h2>\s*<p>(.*?)</p>', text, re.S)[1]
    assert "Only D3 was handed back" in intro and "chadlis/hypotrail#89 for triage" in intro and f"triage was open when this record was written ({record_date})" in intro and "triage is open" not in intro  # dated: the test never reads #89
    assert "defect" not in intro and not re.search(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[^.]*#89", intro, re.I) and "<a " not in intro
    d3 = re.search(r'<li data-difficulty="D3">.*?</li>', text, re.S)[0]
    assert "handed back to chadlis/hypotrail#89 for triage" in d3 and "defect" not in d3 and "says nothing untrue" not in d3
    assert "no README command prints either" not in d3
    assert "<code>status --json</code> lists the References id" in d3 and "comes last in the path" in d3
    handed = [d for d in re.findall(r'<li data-difficulty="(D\d+)">', text) if "handed back" in re.search(rf'<li data-difficulty="{d}">.*?</li>', text, re.S)[0]]
    assert handed == ["D3"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "status --study runs/bike --json" in readme.split("```")[1].strip().splitlines()[-1]  # D3: it comes last in the path


def test_what_the_walk_record_says_of_the_readme_is_in_the_readme_it_describes():
    # 10-R1-05 consistency pass: a quotation of the README in the record is in the README; the paid commands are the two not run.
    text = WALK.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    d6 = re.search(r'<li data-difficulty="D6">.*?</li>', text, re.S)[0]
    assert "self-check" not in d6 and "the scenarios: mock model, no key" in d6 and "the scenarios: mock model, no key" in readme
    claim = re.search(r"<p>Steps are numbered.*?</p>", text, re.S)[0]
    assert "Two commands of the README are paid and were not run" in claim and "spike live" in claim and "spike live" in readme
    assert len([step for step in walk_steps() if step["kind"] == "not-run"]) == 2
def test_the_walk_record_hands_difficulty_d3_back_to_issue_89_in_plain_text_without_a_closing_keyword():
    # 10-R1-05, #87 C5: D3 is handed back to #89 for triage, named in plain text; no keyword closes the issue.
    text = WALK.read_text(encoding="utf-8")
    d3 = re.search(r'<li data-difficulty="D3">.*?</li>', text, re.S)[0]
    assert "chadlis/hypotrail#89" in d3 and "<a " not in d3
    assert not re.search(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[^.]*#89", d3, re.I)


# --- #88: the acceptance grid T01-T24 (chapter 16), its statuses and the handbook's completeness -------------------------

ACCEPTANCE_IDS = [f"T{n:02d}" for n in range(1, 25)]
OFFLINE_IDS = [test for test in ACCEPTANCE_IDS if test != "T20"]  # SPEC §10: T01-T19 and T21-T24 found OFFLINE_ACCEPTED
GRID_CELLS = ("data-what", "data-expected", "data-reason")


class Grid(HTMLParser):
    """Reads the grid chapter: the rows of `acceptance-grid`, the rows of `acceptance-status`, the campaign's command lines."""

    def __init__(self):
        super().__init__()
        self.rows, self.statuses, self.campaign = [], {}, {}
        self._table = self._row = self._status = None
        self._open = []  # the elements whose text is being kept: (tag, where it goes, under which key)

    def _keep(self, tag, target, key):
        self._open.append((tag, target, key))
        if key is None:
            target.append("")
        else:
            target[key] = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self._table = attrs.get("id")
        elif tag == "tr" and self._table == "acceptance-grid" and "data-test" in attrs:
            self._row = {
                "test": attrs["data-test"], "proof": attrs.get("data-proof"), "exit": attrs.get("data-exit"),
                "what": None, "expected": None, "reason": None, "nodes": [], "walk": [], "kept": [], "command": None, "output": None,
            }
            self.rows.append(self._row)
        elif tag == "tr" and self._table == "acceptance-status" and "data-status" in attrs:
            self._status = self.statuses.setdefault(attrs["data-status"], {"attrs": attrs, "text": ""})
        elif tag == "td" and self._row is not None:
            for name in GRID_CELLS:
                if name in attrs:
                    self._keep(tag, self._row, name[len("data-"):])
        elif tag == "td" and self._status is not None:
            self._keep(tag, self._status, "text")
        elif tag == "code" and self._row is not None and "data-node" in attrs:
            self._keep(tag, self._row["nodes"], None)
        elif tag == "code" and "data-campaign" in attrs:
            self._keep(tag, self.campaign, attrs["data-campaign"])
        elif tag == "pre" and self._row is not None:
            for field in ("command", "output"):
                if f"data-{field}" in attrs:
                    self._keep(tag, self._row, field)
        elif tag == "a" and self._row is not None and "data-walk" in attrs:
            self._row["walk"].append(attrs.get("href"))
        elif tag == "a" and self._row is not None and "data-kept" in attrs:
            self._row["kept"].append(attrs.get("href"))

    def handle_endtag(self, tag):
        if self._open and self._open[-1][0] == tag:
            self._open.pop()
        if tag == "tr":
            self._row = self._status = None
        elif tag == "table":
            self._table = None

    def handle_data(self, data):
        for _, target, key in self._open:
            if key is None:
                target[-1] += data
            else:
                target[key] += data


def grid_of(text):
    grid = Grid()
    grid.feed(text)
    return grid


@pytest.fixture(scope="module")
def collected():
    """The node IDs the whole suite collects (a collection only: no test of the suite is run by this)."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    return {line.split(" ")[0] for line in result.stdout.splitlines() if "::" in line}


def node_is_collected(node, collected):
    return node in collected or any(item.startswith(node + "[") for item in collected)


def node_declares(node, test_id):
    """Whether the test function a node ID names carries `test_id` (T05, not T050) in its name or its docstring."""
    path, *scopes = node.split("::")
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    body = tree.body
    for scope in scopes[:-1]:
        body = next(item for item in body if isinstance(item, ast.ClassDef) and item.name == scope).body
    function = next(item for item in body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == scopes[-1])
    return re.search(rf"(?<![A-Za-z0-9]){test_id}(?![0-9])", f"{function.name}\n{ast.get_docstring(function) or ''}") is not None


def row_faults(row, collected):
    """What is wrong with a row of the grid itself, before anything is said about whether its proof passes."""
    faults = []
    if row["proof"] not in {"pytest", "command", "walk", "not-run"}:
        return [f"{row['test']}: proof kind {row['proof']!r}"]
    if not (row["what"] or "").strip() or not (row["expected"] or "").strip():
        faults.append(f"{row['test']}: no text of what it does or of its expected result")
    if row["proof"] == "not-run":
        if not (row["reason"] or "").strip():
            faults.append(f"{row['test']}: not run, with no reason")
    elif (row["reason"] or "").strip():
        faults.append(f"{row['test']}: a proof and a not-run reason together")
    if row["proof"] == "pytest":
        if not row["nodes"]:
            faults.append(f"{row['test']}: a pytest proof that names no node")
        for node in row["nodes"]:
            if not node_is_collected(node, collected):
                faults.append(f"{row['test']}: {node} is not collected by the suite")
            elif not node_declares(node, row["test"]):
                faults.append(f"{row['test']}: {node} does not declare {row['test']} in its name or its docstring")
    if row["proof"] == "command" and not (row["command"] or "").strip():
        faults.append(f"{row['test']}: a command proof with no command")
    if row["proof"] == "walk" and not row["walk"]:
        faults.append(f"{row['test']}: a walk proof that links no record")
    return faults


WALK_FIELDS = ("walker", "executed-by", "date", "commit")


def walk_row_problems(text=None, steps=None, path=None):
    """#88 K, the T24 row: why the walk record does not pass as T24's proof; an empty list when it does.

    The record exists and passes #87 B's test, and holds what T24 expects (SPEC §10: the walker identified, a failure and a limit
    found, the difficulties recorded). A difficulty that is recorded does not fail the row; one that kept the walker from finding
    the failure or the limit shows as an empty failure or limit below, and does.
    """
    if text is None:
        if not WALK.is_file():
            return ["the walk record does not exist"]
        text = WALK.read_text(encoding="utf-8")
    problems = [f"#87 B: {problem}" for problem in walk_problems(walk_steps(text) if steps is None else steps, readme_path() if path is None else path)]
    fields = dict(re.findall(r'<dd data-field="([a-z-]+)">(.*?)</dd>', text, re.S))
    for name in WALK_FIELDS:
        if not re.sub(r"<[^>]+>", "", fields.get(name, "")).strip():
            problems.append(f"the walker is not identified: no {name}")
    failure = re.search(r'<h3 id="failure">.*?<blockquote data-found="failure">(.*?)</blockquote>', text, re.S)
    if not failure or not re.sub(r"<[^>]+>", "", failure.group(1)).strip():
        problems.append("no failure found")
    limit = re.search(r'<h3 id="limit">[^<]*</h3>(.*?)<h2 id="difficulties">', text, re.S)
    if not limit or not re.sub(r"<[^>]+>", "", limit.group(1)).strip():
        problems.append("no limit found")
    difficulties = re.search(r'<ol class="diffs" id="walk-difficulties">(.*?)</ol>', text, re.S)
    if not difficulties or not re.search(r'<li data-difficulty="D\d+">', difficulties.group(1)):
        problems.append("the difficulties are not recorded")
    return problems


def proof_problems(row, collected, walk_text=None):
    """Why a row's proof does not pass (K); an empty list when it does. A row marked not run never passes."""
    if row["proof"] == "not-run":
        return ["not run"]
    problems = row_faults(row, collected)
    if row["proof"] == "command":
        if row["exit"] != "0" or not (row["output"] or "").strip():
            problems.append("the recorded output does not show exit 0")
    if row["proof"] == "walk":
        problems += walk_row_problems(walk_text)
    return problems


def held_back_by(rows, collected, walk_text=None):
    return [row["test"] for row in rows if row["test"] in OFFLINE_IDS and proof_problems(row, collected, walk_text)]


def chapter_16():
    return (HANDBOOK / "chapters" / "16-acceptance-grid.html").read_text(encoding="utf-8")


# --- #99: T20's proof is the Campaign of #98, kept whole; LIVE_ACCEPTED is conditional, computed from it ----------------------

CAMPAIGN_DIR = HANDBOOK / "traces" / "campaign-public-check"
CONDITIONAL_WORDS = "References E01–E10 reviewed by proxy, owner review pending"  # D-025 on chadlis/hypotrail#75, condition 3, verbatim
JOIN_SEQUENCE = ("model_turn", "tool_call", "tool_result", "model_turn", "final_answer")  # SPEC AG-10


def plain_text(markup):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def row_html(page, test_id):
    return re.search(rf'<tr data-test="{test_id}".*?</tr>', page, re.S)[0]


def kept_campaign(kept_dir):
    """The kept command output and, per Configuration, the Attempt folder with its run record, manifest and observations."""
    output = json.loads((kept_dir / "command-output.json").read_text(encoding="utf-8"))
    attempts = {}
    for folder in sorted((kept_dir / "study" / "attempts").iterdir()):
        run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        attempt = json.loads((folder / "attempt.json").read_text(encoding="utf-8"))
        lines = (folder / "observations.jsonl").read_text(encoding="utf-8").splitlines()
        attempts[run["configuration"]] = {"id": folder.name, "folder": folder, "run": run, "attempt": attempt, "observations": [json.loads(line) for line in lines if line.strip()]}
    return output, attempts


def kept_commands(kept_dir):
    """What each Campaign command left in `commands/`: its exit status line, stdout, stderr and, for the two invocations, start and end."""
    kept = {}
    for exit_file in sorted((kept_dir / "commands").glob("*.exit")):
        name = exit_file.stem
        match = re.fullmatch(rf"{re.escape(name)} exit (\d+)", exit_file.read_text(encoding="utf-8").strip())
        entry = {"exit": int(match[1]) if match else None}
        for key, suffix in (("out", "out"), ("err", "err"), ("start", "start"), ("end", "end")):
            path = kept_dir / "commands" / f"{name}.{suffix}"
            entry[key] = path.read_text(encoding="utf-8") if path.is_file() else None
            if key in ("start", "end") and entry[key] is not None:
                entry[key] = entry[key].strip()
        kept[name] = entry
    return kept


def flat_limits(limits):
    flat = {}
    for key, value in limits.items():
        if isinstance(value, dict):
            flat.update({f"{key}.{inner}": inner_value for inner, inner_value in value.items()})
        elif value is not None:  # `tool_calls` is null: Inspect has no such limit, the chapter says so in words
            flat[key] = value
    return flat


def limit_text(value):
    return str(value).lower() if isinstance(value, bool) else str(value)


def join_episode(attempt):
    """The Episode that stands for the Configuration's join trace: Case E02, or E06 if E02 has none produced (D-027 on chadlis/hypotrail#75, item 7)."""
    for case in ("E02", "E06"):
        produced = [o for o in attempt["observations"] if o["case_id"] == case and o["status"] == "produced"]
        if produced:
            return case, min(produced, key=lambda o: o["repeat"])
    return None, None


def has_sequence(trace, sequence):
    kinds = iter(step["kind"] for step in trace)
    return all(kind in kinds for kind in sequence)


def campaign_proof_problems(row, text, kept_dir=CAMPAIGN_DIR, base=HANDBOOK):
    """#99 A, K, I and #98's conditions: why T20's row is not proven by the kept Campaign; an empty list when it is.

    `row` is the grid's row, `text` its plain text. The row is a command proof with exit 0, every file it names exists, the kept
    outputs hold 72 Episodes (36 per Attempt) and each recorded exit is 0, no Attempt has all its Episodes failed, the row shows
    the commands as recorded, the statuses, the tools actually called, the effective limits and the times, and it names one
    Episode per Configuration on a join Case whose trace holds the sequence of AG-10.
    """
    problems = []
    if row["proof"] != "command" or row["exit"] != "0" or not (row["command"] or "").strip() or not (row["output"] or "").strip():
        problems.append("the row is not a command proof with exit 0 and its recorded output")
    if not row["kept"]:
        problems.append("the row names no kept file")
    problems += [f"the row names {href}, which does not exist" for href in row["kept"] if not (base / href).resolve().is_file()]
    try:
        output, attempts = kept_campaign(kept_dir)
    except (OSError, ValueError, KeyError) as error:
        return problems + [f"the kept outputs cannot be read: {error}"]
    steps = {command["step"]: command for command in output["commands"]}  # the index: the argv of each command
    try:
        files = kept_commands(kept_dir)  # the commands' own captured output: exit, stdout and times are read from here (93-R1-08)
    except OSError as error:
        return problems + [f"the kept commands cannot be read: {error}"]
    missing = sorted({"init", "plain", "verify", "assess-plain", "assess-verify", "compare", "report"} - set(files))
    if missing:
        problems.append(f"no kept output for {missing}")
    if not files or any(entry["exit"] != 0 for entry in files.values()):
        problems.append(f"a recorded exit is not 0: {sorted(name for name, entry in files.items() if entry['exit'] != 0)}")
    if sorted(attempts) != ["plain", "verify"]:
        return problems + [f"the kept Attempts are {sorted(attempts)}, not plain and verify"]
    for config, attempt in attempts.items():
        if len(attempt["observations"]) != 36:
            problems.append(f"{config}: {len(attempt['observations'])} Episodes, not 36")
        if not any(o["status"] == "produced" for o in attempt["observations"]):
            problems.append(f"{config}: every Episode failed, so no model-tool loop is shown (K)")
    episodes = [o for attempt in attempts.values() for o in attempt["observations"]]
    if len(episodes) != 72:
        problems.append(f"{len(episodes)} Episodes, not 72")
    flat_row = " ".join(text.split())
    for step, name in (("run-plain", "plain"), ("run-verify", "verify")):
        command, kept = steps.get(step), files.get(name)
        if command is None or kept is None:
            problems.append(f"{step}: no recorded command")
            continue
        if " ".join(command["argv"].split()) not in " ".join((row["command"] or "").split()):
            problems.append(f"{step}: its recorded command line is not in the row")
        if " ".join((kept["out"] or "").split()) not in " ".join((row["output"] or "").split()) or not (kept["out"] or "").strip():
            problems.append(f"{step}: its recorded output is not in the row")
        for stamp in (kept["start"], kept["end"]):
            if not stamp or stamp not in flat_row:
                problems.append(f"{step}: the time {stamp} is not in the row")
    if f"{len(episodes)} Episodes" not in flat_row:
        problems.append("the row does not state the number of Episodes")
    for status, count in Counter(o["status"] for o in episodes).items():
        if f"{count} {status}" not in flat_row:
            problems.append(f"the row does not state {count} {status}")
    calls = Counter()
    for attempt in attempts.values():
        for o in attempt["observations"]:
            calls.update(step["function"] for step in o["trace"] if step["kind"] == "tool_call")
    if not calls:
        problems.append("no tool was called in any Episode")
    problems += [f"the row does not state {function} {count}" for function, count in sorted(calls.items()) if f"{function} {count}" not in flat_row]
    limits = {config: flat_limits(attempt["run"]["effective_limits"]) for config, attempt in attempts.items()}
    if limits["plain"] != limits["verify"]:
        problems.append("the two Attempts do not record the same effective limits")
    problems += [f"the row does not state the limit {key} {limit_text(value)}" for key, value in limits["plain"].items() if f"{key} {limit_text(value)}" not in flat_row]
    served = {attempt["attempt"]["effective_config"]["served_model"] for attempt in attempts.values()}
    if len(served) != 1:
        problems.append(f"the Attempts were served by different models: {sorted(served)}")
    problems += [f"the row does not name the served model {model}" for model in served if model not in flat_row]
    for config, attempt in attempts.items():  # 93-R1-02, #98 Tightened A: the model every sample of the kept Inspect log reports is the served model
        logs = sorted((attempt["folder"] / "inspect").glob("*.eval"))
        if len(logs) != 1:
            problems.append(f"{config}: {len(logs)} Inspect logs, not 1")
            continue
        samples = read_eval_log(str(logs[0])).samples or []
        reported = {sample.output.model for sample in samples}
        if len(samples) != 36:
            problems.append(f"{config}: the Inspect log holds {len(samples)} Episodes (Inspect samples × epochs), not 36")
        if reported != served:
            problems.append(f"{config}: the Episodes (Inspect samples × epochs) of the Inspect log report {sorted(reported)}, not the served model {sorted(served)}")
    for config, attempt in attempts.items():
        case, episode = join_episode(attempt)
        if episode is None:
            problems.append(f"{config}: no produced Episode on E02 or E06")
        elif not has_sequence(episode["trace"], JOIN_SEQUENCE):
            problems.append(f"{config}: the trace of {case} Repeat {episode['repeat']} has no model, tool, model, final answer sequence")
        else:
            for name in (attempt["id"], f"{case} Repeat {episode['repeat']}"):
                if name not in flat_row:
                    problems.append(f"the row does not name {name}")
    for name in ("chadlis/hypotrail#93", "7057388641", "chadlis/hypotrail#95", "7057075785", "order not alternated (AG-12 of the L1 specification"):
        if name not in flat_row:
            problems.append(f"the row does not name {name}")
    return problems


def live_value(page, kept_dir=CAMPAIGN_DIR):
    """#99 B and J, 93-R1-07: `conditional` when T20's row has a passing proof, the spike's report is cited as evidence, the
    LIVE_ACCEPTED row states in `data-owner-review` that the owner's review of the References is pending (only the owner lifts it:
    D-025 on chadlis/hypotrail#75, condition 3) and the row names the AG-12 deviation of D-028 on chadlis/hypotrail#75; `pending` otherwise."""
    rows = {row["test"]: row for row in grid_of(page).rows}
    proof = campaign_proof_problems(rows["T20"], plain_text(row_html(page, "T20")), kept_dir)
    evidence = re.search(r'<tr data-status="LIVE_ACCEPTED".*?</tr>', page, re.S)[0]
    spike_cited = 'href="#feasibility-spike"' in evidence
    owner_pending = re.search(r'<tr data-status="LIVE_ACCEPTED"[^>]*\sdata-owner-review="([^"]*)"', evidence) is not None and re.search(r'data-owner-review="([^"]*)"', evidence)[1] == "pending"
    text = plain_text(evidence)
    deviation = all(part in text for part in ("AG-12", "not alternated", "D-028"))
    return "conditional" if not proof and spike_cited and owner_pending and deviation else "pending"


def test_the_grid_has_exactly_one_row_per_test_T01_to_T24_each_with_what_it_does_its_expected_result_and_a_proof_or_a_reason(page):
    # #88 C1: the rows are exactly T01-T24, in order, once each; a row has its text and either a proof or a "not run" reason.
    rows = grid_of(page).rows
    assert [row["test"] for row in rows] == ACCEPTANCE_IDS
    for row in rows:
        assert (row["what"] or "").strip() and (row["expected"] or "").strip(), row["test"]
        assert (row["proof"] == "not-run") == bool((row["reason"] or "").strip()), row["test"]


def test_every_pytest_node_a_row_names_is_collected_by_the_suite_and_declares_that_rows_test(page, collected):
    # #88 A: a collected but unrelated test fails the grid unless it declares the row.
    assert [fault for row in grid_of(page).rows for fault in row_faults(row, collected)] == []


def test_a_row_naming_a_test_that_is_not_collected_or_does_not_declare_it_is_a_fault(collected):
    # #88 A, the witness of the witness: a node that exists and passes but is about another row, and a node that does not exist.
    unrelated = "tests/test_data_verify.py::test_both_datasets_verify_with_no_workload_given"
    row = {"test": "T02", "proof": "pytest", "exit": None, "what": "w", "expected": "e", "reason": None, "nodes": [unrelated], "walk": [], "command": None, "output": None}
    assert node_is_collected(unrelated, collected)
    assert row_faults(row, collected) == [f"T02: {unrelated} does not declare T02 in its name or its docstring"]
    assert row_faults({**row, "nodes": ["tests/test_data_verify.py::test_nothing_like_it"]}, collected) == [
        "T02: tests/test_data_verify.py::test_nothing_like_it is not collected by the suite"
    ]
    assert node_declares("tests/test_report_agent.py::test_T22_markup_in_a_scenarios_final_answer_is_shown_as_the_same_characters_and_the_rest_of_the_page_is_intact", "T22")
    assert not node_declares("tests/test_report_agent.py::test_T22_markup_in_a_scenarios_final_answer_is_shown_as_the_same_characters_and_the_rest_of_the_page_is_intact", "T2")


def grid_row(test, proof="pytest", **fields):
    return {"test": test, "proof": proof, "exit": None, "what": "w", "expected": "e", "reason": None, "nodes": [], "walk": [], "kept": [], "command": None, "output": None, **fields}


def test_a_row_marked_not_run_holds_offline_accepted_back_and_a_command_row_passes_only_with_exit_0(collected):
    # #88 B and K: OFFLINE_ACCEPTED is computed from the rows; a not-run row among T01-T19 and T21-T24 holds it back, T20 does not.
    declared = "tests/test_data_verify.py::test_a_flipped_byte_is_refused_with_the_integrity_code_naming_the_file"
    ok = grid_row("T01", nodes=[declared])
    assert held_back_by([ok], collected) == []
    assert held_back_by([grid_row("T05", "not-run", reason="r")], collected) == ["T05"]
    assert held_back_by([grid_row("T20", "not-run", reason="r")], collected) == []
    assert held_back_by([grid_row("T01", "command", command="x", output="o", exit="0")], collected) == []
    assert held_back_by([grid_row("T01", "command", command="x", output="o", exit="1")], collected) == ["T01"]
    assert held_back_by([grid_row("T01", "command", command="x", output="", exit="0")], collected) == ["T01"]
    assert held_back_by([grid_row("T01", nodes=[])], collected) == ["T01"]


def test_the_status_table_has_the_three_statuses_each_with_its_own_value_and_offline_accepted_is_the_one_the_rows_compute(page, collected):
    # #88 B: LIVE_ACCEPTED conditional since #99 (not LIVE_NOT_VALIDATED), USABILITY_REVIEW_PENDING open, OFFLINE_ACCEPTED computed from the rows.
    grid = grid_of(page)
    statuses = {name: row["attrs"] for name, row in grid.statuses.items()}
    assert set(statuses) == {"OFFLINE_ACCEPTED", "LIVE_ACCEPTED", "USABILITY_REVIEW_PENDING"}
    assert statuses["LIVE_ACCEPTED"]["data-value"] == "conditional"
    assert statuses["USABILITY_REVIEW_PENDING"]["data-value"] == "open"
    held = held_back_by(grid.rows, collected)
    assert statuses["OFFLINE_ACCEPTED"]["data-value"] == ("pending" if held else "reached")
    assert statuses["OFFLINE_ACCEPTED"].get("data-held-by", "").split() == held
    assert all("LIVE_NOT_VALIDATED" not in row["text"] for row in grid.statuses.values())
    for name, row in grid.statuses.items():  # each status has its own evidence, none derived from another
        assert row["text"].strip(), name
    assert "T20" in grid.statuses["LIVE_ACCEPTED"]["text"] and "T20" not in grid.statuses["OFFLINE_ACCEPTED"]["text"]
    assert "T01" in grid.statuses["OFFLINE_ACCEPTED"]["text"] and "T24" in grid.statuses["OFFLINE_ACCEPTED"]["text"]


def test_T20_is_proven_by_the_kept_campaign_and_its_row_cites_the_spike_report_and_the_live_traces(page):
    # #99 A: T20's row is a command proof; its files exist, the kept outputs hold 72 Episodes and every recorded exit is 0.
    rows = {row["test"]: row for row in grid_of(page).rows}
    assert rows["T20"]["proof"] == "command" and rows["T20"]["exit"] == "0"
    assert campaign_proof_problems(rows["T20"], plain_text(row_html(page, "T20"))) == []
    text = plain_text(chapter_16())
    assert 'href="#feasibility-spike"' in chapter_16()
    assert "docs/handbook/traces/live-spike" in text and "docs/handbook/traces/run-agent-live-plain" in text
    assert "does not really test the join" not in text and "LEFT JOIN" not in text  # 93-R1-06: the critique stays in the inspection comment on #93
    assert "7057388641" in text  # and the row still names that comment


def test_a_row_is_not_T20_s_proof_when_a_file_is_missing_an_exit_is_not_0_a_count_is_off_or_an_Attempt_failed_whole(tmp_path):
    # #99 A and K, the witness of the witness: each guard of the proof turns it red on its own, on a copy of the kept outputs.
    page = BUILT.read_text(encoding="utf-8")
    row, text = grid_of(page).rows[19], plain_text(row_html(page, "T20"))
    assert row["test"] == "T20"

    def broken(change):
        copy = tmp_path / f"copy-{len(list(tmp_path.iterdir()))}"
        shutil.copytree(CAMPAIGN_DIR, copy, ignore=shutil.ignore_patterns("report.html"))
        change(copy)
        return campaign_proof_problems(row, text, copy)

    assert campaign_proof_problems(row, text) == []
    assert campaign_proof_problems({**row, "kept": row["kept"] + ["traces/campaign-public-check/nothing.json"]}, text) == [
        "the row names traces/campaign-public-check/nothing.json, which does not exist"
    ]
    assert campaign_proof_problems({**row, "kept": []}, text) == ["the row names no kept file"]
    assert campaign_proof_problems({**row, "exit": "1"}, text) == ["the row is not a command proof with exit 0 and its recorded output"]
    no_output = campaign_proof_problems({**row, "output": ""}, text)
    assert no_output[0] == "the row is not a command proof with exit 0 and its recorded output" and "run-plain: its recorded output is not in the row" in no_output

    def exit_1(copy):  # the exit the command left in commands/, not the index's copy of it
        (copy / "commands" / "plain.exit").write_text("plain exit 1\n")

    assert broken(exit_1) == ["a recorded exit is not 0: ['plain']"]

    def drop_an_episode(copy):
        path = next((copy / "study" / "attempts").glob("*/observations.jsonl"))
        lines = path.read_text().splitlines()
        path.write_text("\n".join(lines[:-1]) + "\n")

    dropped = broken(drop_an_episode)
    assert any("Episodes, not 36" in problem for problem in dropped) and any("not 72" in problem for problem in dropped)

    def all_failed(copy):  # every Episode of the verify Attempt failed: no model-tool loop is shown for that Configuration
        for folder in (copy / "study" / "attempts").iterdir():
            if json.loads((folder / "run.json").read_text())["configuration"] == "verify":
                lines = [json.loads(line) for line in (folder / "observations.jsonl").read_text().splitlines()]
                for line in lines:
                    line["status"] = "failed"
                (folder / "observations.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")

    failed = broken(all_failed)
    assert any("every Episode failed" in problem for problem in failed)

    def no_tool_called(copy):
        for path in (copy / "study" / "attempts").glob("*/observations.jsonl"):
            lines = [json.loads(line) for line in path.read_text().splitlines()]
            for line in lines:
                line["trace"] = [step for step in line["trace"] if step["kind"] not in ("tool_call", "tool_result")]
            path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

    assert "no tool was called in any Episode" in broken(no_tool_called)

    def another_model_in_one_sample(copy):  # one sample of a copied Inspect log reports another model, written through Inspect's own API
        path = next((copy / "study" / "attempts").glob("*/inspect/*.eval"))
        log = read_eval_log(str(path))
        log.samples[0].output.model = "claude-other"
        write_eval_log(log, str(path))

    reported = broken(another_model_in_one_sample)
    assert len(reported) == 1 and "the Episodes (Inspect samples × epochs) of the Inspect log report ['claude-other', 'claude-sonnet-5-5'], not the served model ['claude-sonnet-5-5']" in reported[0]  # 93-R2-01, GLOSSARY Inspect mapping

    def another_limit(copy):
        path = next((copy / "study" / "attempts").glob("*/run.json"))
        run = json.loads(path.read_text())
        run["effective_limits"]["model_turns"] = 7
        path.write_text(json.dumps(run))

    assert "the two Attempts do not record the same effective limits" in broken(another_limit)


def test_the_live_accepted_value_is_conditional_and_computed_from_T20_the_spike_report_and_the_owners_pending_review(page, tmp_path):
    # #99 B and J: `conditional` when T20's row passes, the spike's report is cited and the owner's review is pending; `pending` otherwise.
    value = grid_of(page).statuses["LIVE_ACCEPTED"]["attrs"]["data-value"]
    assert value == live_value(page) == "conditional"
    assert 'data-owner-review="pending"' in re.search(r'<tr data-status="LIVE_ACCEPTED".*?</tr>', page, re.S)[0]  # the state lives in the chapter, not in the test
    not_run = page.replace(row_html(page, "T20"), row_html(page, "T20").replace('data-proof="command"', 'data-proof="not-run"', 1))
    assert not_run != page and live_value(not_run) == "pending"
    no_spike = re.sub(r'(<tr data-status="LIVE_ACCEPTED".*?)href="#feasibility-spike"(.*?</tr>)', r"\1\2", page, count=1, flags=re.S)
    assert no_spike != page and live_value(no_spike) == "pending"
    done = page.replace('data-owner-review="pending"', 'data-owner-review="done"', 1)
    assert done != page and live_value(done) == "pending"
    no_attribute = page.replace(' data-owner-review="pending"', "", 1)
    assert no_attribute != page and live_value(no_attribute) == "pending"
    no_deviation = re.sub(r'(<tr data-status="LIVE_ACCEPTED".*?)AG-12(.*?</tr>)', r"\1the order\2", page, count=1, flags=re.S)
    assert no_deviation != page and live_value(no_deviation) == "pending"
    copy = tmp_path / "campaign"
    shutil.copytree(CAMPAIGN_DIR, copy, ignore=shutil.ignore_patterns("report.html"))
    (copy / "commands" / "plain.exit").write_text("plain exit 1\n")
    assert live_value(page, kept_dir=copy) == "pending"


def conditional_words_missing(text):
    """Sentences holding LIVE_ACCEPTED without the conditional words beside them (D-025 on chadlis/hypotrail#75, condition 3; #99)."""
    return [s for s in split_sentences(text) if "LIVE_ACCEPTED" in s and CONDITIONAL_WORDS not in s]


def test_every_statement_of_live_accepteds_value_holds_the_conditional_words_beside_it(page):
    # #99 C3: the status table's row, the rest of the handbook and the README. The bare-pending test of #88 still passes beside it.
    assert conditional_words_missing("<p>LIVE_ACCEPTED is conditional.</p>") == ["LIVE_ACCEPTED is conditional."]
    assert conditional_words_missing(f"<p>LIVE_ACCEPTED is conditional: {CONDITIONAL_WORDS}.</p>") == []
    row = " ".join(re.sub(r"<[^>]+>", " ", re.search(r'<tr data-status="LIVE_ACCEPTED".*?</tr>', page, re.S)[0]).split())
    assert CONDITIONAL_WORDS in row and "conditional" in row
    sources = {"README.md": (ROOT / "README.md").read_text(encoding="utf-8")}
    for path in sorted((HANDBOOK / "chapters").glob("*.html")):
        text = path.read_text(encoding="utf-8")
        sources[path.name] = re.sub(r'<table class="tbl" id="acceptance-status">.*?</table>', "", text, flags=re.S)
    assert {name: conditional_words_missing(text) for name, text in sources.items() if conditional_words_missing(text)} == {}
    assert "LIVE_ACCEPTED" in sources["README.md"] and "LIVE_ACCEPTED" in sources["16-acceptance-grid.html"]


def split_sentences(text):
    """The sentences and the cells of a text with its markup removed, one per element that holds text."""
    blocks = re.split(r"</(?:p|li|td|th|h\d|pre|div|dd|dt|blockquote)>|<br\s*/?>|\n\s*\n", text)
    sentences = []
    for block in blocks:
        plain = " ".join(re.sub(r"<[^>]+>", " ", block).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").split())
        sentences += [s for s in re.split(r"(?<=[.!?;])\s+", plain) if s]
    return sentences


def bare_live_accepted(text):
    """Sentences or cells that hold LIVE_ACCEPTED without "pending" (D-015 on chadlis/hypotrail#75 condition 3)."""
    return [s for s in split_sentences(text) if "LIVE_ACCEPTED" in s and not re.search(r"(?<![A-Za-z_])pending(?![A-Za-z_])", s, re.I)]


def test_no_sentence_or_cell_outside_the_status_table_holds_live_accepted_without_pending():
    # #88 C: the README and every handbook chapter's source; a sentence like "LIVE_ACCEPTED is reached once the Campaign runs" fails.
    assert bare_live_accepted("<p>LIVE_ACCEPTED is reached once the Campaign runs.</p>") == ["LIVE_ACCEPTED is reached once the Campaign runs."]
    assert bare_live_accepted("<p>LIVE_ACCEPTED is pending. LIVE_ACCEPTED is reached.</p>") == ["LIVE_ACCEPTED is reached."]
    assert bare_live_accepted("<table><tr><td>LIVE_ACCEPTED</td><td>pending</td></tr></table>") == ["LIVE_ACCEPTED"]
    assert bare_live_accepted("<p>LIVE_ACCEPTED and USABILITY_REVIEW_PENDING are kept apart.</p>") == ["LIVE_ACCEPTED and USABILITY_REVIEW_PENDING are kept apart."]
    sources = {"README.md": (ROOT / "README.md").read_text(encoding="utf-8")}
    for path in sorted((HANDBOOK / "chapters").glob("*.html")):
        text = path.read_text(encoding="utf-8")
        sources[path.name] = re.sub(r'<table class="tbl" id="acceptance-status">.*?</table>', "", text, flags=re.S)
    assert {name: bare_live_accepted(text) for name, text in sources.items() if bare_live_accepted(text)} == {}
    assert "LIVE_ACCEPTED" in sources["README.md"] and "LIVE_ACCEPTED" in sources["16-acceptance-grid.html"]  # the check reads what it is about


def readme_status():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    return text.split("## Status", 1)[1].split("\n## ", 1)[0]


def test_the_readme_status_states_the_three_statuses_as_the_grid_has_them_links_the_grid_and_where_to_look_names_it(page):
    # #88 C9 (the README's criterion) and E: USABILITY_REVIEW_PENDING is open; nothing says the README path is usable by a third party.
    grid = grid_of(page)
    status = " ".join(readme_status().split())
    values = {name: row["attrs"]["data-value"] for name, row in grid.statuses.items()}
    assert f"`OFFLINE_ACCEPTED` {values['OFFLINE_ACCEPTED']}" in status
    assert values["LIVE_ACCEPTED"] == "conditional"
    assert f"`LIVE_ACCEPTED` {values['LIVE_ACCEPTED']}: {CONDITIONAL_WORDS}" in status  # #99 C3: the grid's value, in the grid's words
    assert "`USABILITY_REVIEW_PENDING` open" in status
    assert "docs/handbook/handbook.html#acceptance-grid" in status
    where = (ROOT / "README.md").read_text(encoding="utf-8").split("## Where to look", 1)[1]
    assert "acceptance grid" in where.lower() and "handbook.html#acceptance-grid" in where
    assert "documented for after the owner's review" not in where and "documented for after" not in where  # #99 C9: the Campaign ran
    for text in (status, " ".join(re.sub(r"<[^>]+>", " ", chapter_16()).split())):
        for sentence in split_sentences(text):
            if re.search(r"third part(?:y|ies)", sentence):
                assert re.search(r"\bnot\b|\bpending\b|\buntil\b|\bbefore\b|\bnever\b", sentence), sentence
    assert 'data-status="USABILITY_REVIEW_PENDING"' in page and "another person" in " ".join(page.split())


def test_the_grid_links_the_walk_record_of_t24_and_the_t24_row_passes_by_k(page):
    # #88 K and #87 E: the T24 row's proof is the walk record, linked from the grid.
    row = {row["test"]: row for row in grid_of(page).rows}["T24"]
    assert row["proof"] == "walk" and row["walk"] == ["walk-t24.html"]
    assert walk_row_problems() == []


def test_the_t24_row_fails_when_the_record_is_missing_unwalked_or_has_no_failure_or_no_limit_and_survives_a_recorded_difficulty():
    # #88 K: a recorded difficulty does not fail the row; one that kept the walker from the failure or the limit does.
    text = WALK.read_text(encoding="utf-8")
    assert walk_row_problems(text) == []
    extra = text.replace('<li data-difficulty="D9">', '<li data-difficulty="D10"><b>D10.</b> a difficulty that was recorded and changed nothing.</li>\n<li data-difficulty="D9">')
    assert extra != text and walk_row_problems(extra) == []
    no_failure = re.sub(r'(<blockquote data-found="failure">).*?(</blockquote>)', r"\1\2", text, flags=re.S)
    assert walk_row_problems(no_failure) == ["no failure found"]
    no_limit = re.sub(r'(<h3 id="limit">[^<]*</h3>).*?(<h2 id="difficulties">)', r"\1\2", text, flags=re.S)
    assert walk_row_problems(no_limit) == ["no limit found"]
    no_walker = text.replace('data-field="walker"', 'data-field="nobody"')
    assert walk_row_problems(no_walker) == ["the walker is not identified: no walker"]
    no_difficulties = text.replace("data-difficulty=", "data-nothing=")
    assert walk_row_problems(no_difficulties) == ["the difficulties are not recorded"]
    unwalked = [step for step in walk_steps(text) if step["kind"] != "readme"]
    assert any(problem.startswith("#87 B:") for problem in walk_row_problems(text, steps=unwalked))
    assert walk_row_problems(text, path=readme_path()[:-1]) != []


def test_the_acceptance_grid_names_the_control_configuration_plain_not_baseline_as_a_role():
    # 10-R1-02, GLOSSARY Control (_Avoid_: baseline as a role): the limit on the order of the Configurations names `plain` and `verify`.
    chapter = (HANDBOOK / "chapters" / "16-acceptance-grid.html").read_text(encoding="utf-8")
    assert 'data-open-point="order"' not in chapter  # #99 C7 (D-028 on chadlis/hypotrail#75): the open point is settled; it is a limit now
    point = re.search(r'<span data-limit="order">(.*?)</span>', chapter, re.S)[1]
    assert "order of <code>plain</code> and <code>verify</code>" in point
    assert "baseline" not in point


def test_chapter_16s_order_limit_says_the_kept_comparison_predates_the_order_warning_that_one_written_now_would_hold():
    point = plain_text(re.search(r'<span data-limit="order">(.*?)</span>', chapter_16(), re.S)[1])
    kept = sorted(p.name for p in (HANDBOOK / "traces" / "campaign-public-check" / "study" / "comparisons").iterdir())
    assert [name[:8] for name in kept] == ["4dd96c89"]
    assert "4dd96c89" in point and "predates" in point and "COMPARISON_ORDER_NOT_ALTERNATED" in point, point


CAMPAIGN_PLACEHOLDER = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*\b")


def campaign_argv(line):
    """A documented command line as the parser takes it: the program removed, each placeholder filled with itself in lower case."""
    words = CAMPAIGN_PLACEHOLDER.sub(lambda match: match.group(0).lower(), line).split()
    assert words[:5] == ["uv", "run", "python", "-m", "hypotrail"], line
    return words[5:]


def test_every_campaign_command_the_grid_documents_parses_with_the_clis_parser_with_its_required_flags(page):
    # #88 D: the two `run agent` invocations, `assess` of each, `compare` and `report`; a line missing a required flag fails.
    from hypotrail.cli import build_parser

    lines = grid_of(page).campaign
    assert list(lines) == ["run-plain", "run-verify", "assess-plain", "assess-verify", "compare", "report"]
    parsed = {name: build_parser().parse_args(campaign_argv(" ".join(line.split()))) for name, line in lines.items()}
    for config in ("plain", "verify"):
        run = parsed[f"run-{config}"]
        assert (run.mode, run.config, run.partition, run.repeats, run.model) == ("llm_live", config, "public_check", 3, "anthropic/claude-sonnet-5-5")
    assert parsed["run-plain"].request_id != parsed["run-verify"].request_id
    assert all(parsed[name].scorer == "chinook_contract_v1" for name in ("assess-plain", "assess-verify"))
    assert parsed["assess-plain"].observations != parsed["assess-verify"].observations
    assert lines["run-plain"].split() != lines["run-verify"].split()
    for name in ("run-plain", "run-verify"):  # the one flags the Campaign must not carry: another Configuration and a cache or a retry knob
        assert "--cases" not in lines[name] and "--retry-of" not in lines[name]
    for name, line in lines.items():  # a line missing one of its required flags is refused by the parser
        for flag in re.findall(r"--[a-z-]+", line):
            argv = campaign_argv(" ".join(line.split()))
            index = argv.index(flag)
            required = {a.dest for a in _command_parser(argv)._actions if a.required}
            if flag.lstrip("-").replace("-", "_") in required:
                with pytest.raises(InvalidInputError):
                    build_parser().parse_args(argv[:index] + argv[index + 2:])


def _command_parser(argv):
    from hypotrail.cli import build_parser

    parser = build_parser()
    for word in argv:
        action = next((a for a in parser._actions if getattr(a, "choices", None) and word in a.choices), None)
        if action is None:
            return parser
        parser = action.choices[word]
    return parser


def test_in_the_campaigns_comparison_plain_is_the_control_and_verify_the_candidate(page):
    # #88 H (D-017 on chadlis/hypotrail#75 item 9, AG-06: `verify` adds the instruction).
    from hypotrail.cli import build_parser

    lines = grid_of(page).campaign
    compare = build_parser().parse_args(campaign_argv(" ".join(lines["compare"].split())))
    assert "plain" in compare.control and "verify" not in compare.control
    assert "verify" in compare.candidate and "plain" not in compare.candidate
    assert compare.factor is None  # the Configuration is the declared factor of an agent Comparison


def test_the_grid_states_what_the_campaign_was_the_conditions_it_ran_under_its_dates_commit_exits_and_the_limit_on_the_order(page):
    # #88 C4 and C5, brought up to date by #99 C7: 72 Episodes, the same model and limits, cache off, retries zero; what happened, not what was planned.
    text = plain_text(chapter_16())
    for part in (
        "12 Cases", "3 Repeats", "2 Configurations", "72 Episodes", "public_check", "the same model and limits", "response cache off", "retries at zero",
        "Inspect logs and Observation sets kept whole", "no further paid invocation", "USD 30", "five paid live invocations per slice",
        "D-025", "conditions 1 to 5", "chadlis/hypotrail#95", "7057075785", "holds", "chadlis/hypotrail#96", "D-028",
        "2026-11-21", "f696f58", "exited 0",
        "order not alternated (AG-12 of the L1 specification", "case_index + repeat_index", "confounded with the time block", "back to back",
        "T20 is not proven by an Attempt whose Episodes all failed",
    ):
        assert part in text, part
    assert "A second Campaign with alternation" in text and "rerun" not in text and "A repeat of the Campaign" not in text  # 93-R1-11, GLOSSARY Repeat (_Avoid_: retry, copy) and Attempt (_Avoid_: run)
    for stale in (  # the wording of the plan, pinned by #88 and replaced by #99 C7
        "only after the owner's review of the References", "No command of this grid was run against a real model", "is not alternated Episode by Episode",
        "owner-decision gate", "for after the owner's review", "Open point", "did not run",
    ):
        assert stale not in text, stale
    kept = json.loads((CAMPAIGN_DIR / "command-output.json").read_text())
    assert kept["commit"] in text and all(command["exit_code"] == 0 for command in kept["commands"])
    for command in kept["commands"]:
        if command["started_at"]:
            assert command["started_at"] in text and command["finished_at"] in text


def kept_exit(name):
    """The exit status a kept `commands/NAME.exit` file records: "NAME exit N"."""
    return int(re.fullmatch(rf"{name} exit (\d+)", (CAMPAIGN_DIR / "commands" / f"{name}.exit").read_text(encoding="utf-8").strip())[1])


def test_chapter_16_says_what_the_rehearsal_covered_and_that_the_paid_invocations_proved_the_uv_launcher(page):
    # 93-R1-01, D-029 on chadlis/hypotrail#75: the rehearsal at f696f58 ran the hypotrail arguments under the test interpreter, not `uv run`.
    match = re.search(r'<p data-rehearsal="launcher">(.*?)</p>', chapter_16(), re.S)
    assert match, "no paragraph says what the rehearsal covered"
    text = plain_text(match[1])
    for part in (
        "rehearsal that ran before the Campaign", "f696f58", "every hypotrail argument of the paid lines", "under the test interpreter",
        "with the provider patched", "uv run launcher was not rehearsed", "paid invocations themselves proved the launcher",
        "both exited 0", "commands/plain.exit", "commands/verify.exit",
    ):
        assert part in text, part
    assert kept_exit("plain") == kept_exit("verify") == 0  # what the paragraph says of the two files is what they hold


INDEX_FILE = {"run-plain": "plain", "run-verify": "verify"}  # an index step whose commands/ file has another name


def index_problems(kept_dir=CAMPAIGN_DIR):
    """Where an entry of the index `command-output.json` differs from the file the command itself left in `commands/`."""
    index = json.loads((kept_dir / "command-output.json").read_text(encoding="utf-8"))
    files = kept_commands(kept_dir)
    problems = []
    if {INDEX_FILE.get(c["step"], c["step"]) for c in index["commands"]} != set(files):
        problems.append("the index and commands/ do not hold the same commands")
    for command in index["commands"]:
        name = INDEX_FILE.get(command["step"], command["step"])
        kept = files.get(name)
        if kept is None:
            continue
        for key, value in (("stdout", kept["out"]), ("stderr", kept["err"]), ("exit_code", kept["exit"]), ("started_at", kept["start"]), ("finished_at", kept["end"])):
            if command[key] != value:
                problems.append(f"{command['step']}: {key} {command[key]!r} is not {value!r}, what commands/ holds")
    return problems


COMMIT_TIMES = {"067e917": "2026-11-21T04:36:35+00:00", "c5c1b08": "2026-11-21T05:35:16+00:00"}  # literal: a shallow CI checkout has no history to ask


def kept_times():
    """The start of the first and the end of the last paid invocation (HH:MM:SS), read from the files; commands/ holds times for these two only."""
    folder = CAMPAIGN_DIR / "commands"
    assert sorted(path.name for path in folder.glob("*.start")) + sorted(path.name for path in folder.glob("*.end")) == ["plain.start", "verify.start", "plain.end", "verify.end"]
    assert not [path.name for path in folder.iterdir() if path.suffix not in (".out", ".err", ".exit", ".start", ".end") and path.name != "commit.txt"]  # no argv file
    first = (folder / "plain.start").read_text(encoding="utf-8").strip()
    last = (folder / "verify.end").read_text(encoding="utf-8").strip()
    return {"first": first[11:19], "last": last[11:19]}


def test_the_literal_commit_times_chapter_16_gives_are_those_of_git_where_history_is_available():
    # 93-R1-08, round 4: the index (067e917) and the captures (c5c1b08) were committed about one hour apart, after the invocations.
    for commit, stamp in COMMIT_TIMES.items():
        done = subprocess.run(["git", "log", "-1", "--format=%cI", commit], cwd=ROOT, capture_output=True, text=True)
        if done.returncode != 0 or not done.stdout.strip():
            pytest.skip("no git history here (a shallow checkout): the literal time stays")
        assert done.stdout.strip() == stamp, commit


def test_every_stdout_stderr_exit_and_time_of_the_index_equals_the_file_the_command_left_in_commands(tmp_path):
    # 93-R1-08 (structural): `command-output.json` is an index assembled after the invocations; `commands/` is the output itself.
    assert index_problems() == []
    copy = tmp_path / "campaign"
    shutil.copytree(CAMPAIGN_DIR, copy, ignore=shutil.ignore_patterns("report.html", "study"))
    index = json.loads((copy / "command-output.json").read_text())
    index["commands"][3]["exit_code"] = 1  # one altered exit in a copied index
    (copy / "command-output.json").write_text(json.dumps(index))
    assert index_problems(copy) == ["assess-plain: exit_code 1 is not 0, what commands/ holds"]
    index["commands"][3]["exit_code"] = 0
    index["commands"][1]["stdout"] += "x"
    (copy / "command-output.json").write_text(json.dumps(index))
    assert [problem.split(":")[0] for problem in index_problems(copy)] == ["run-plain"]
    (copy / "commands" / "report.exit").unlink()
    assert "the index and commands/ do not hold the same commands" in index_problems(copy)


def test_chapter_16_says_the_index_was_assembled_by_the_agent_that_drove_the_slice_from_the_files_of_commands(page):
    # the index is not the commands' own output; "the drive" is named for a reader of the handbook (ADR 0003).
    text = plain_text(chapter_16())
    for part in (
        "command-output.json is an index", "assembled after the invocations from the files in commands/", "the agent that drove the slice (.claude/skills/drive/)",
        "stdout, stderr and exit status of each command", "commands/ of the kept folder holds the shell's captures, unedited", "it carries the argv of each command",
        "tied to the invocations only by commit c5c1b08", "#93's state comment, written at the time", "no digest was posted at run time",  # D-030 on chadlis/hypotrail#75, item 3
    ):
        assert part in text, part
    for part in (  # 93-R1-08, round 4: what commands/ does not hold, who has times, and how long after the invocations the files were committed
        "start and end times for the two paid invocations only (plain.start, plain.end, verify.start, verify.end), none for the other five commands",
        "commands/ holds no argv", "assembled after the invocations", "The full argv strings are recorded only in command-output.json",
        "the state comment of #93, last edited at 04:37:01Z, records the --config and --request-id of each paid invocation", "each run.json records the Configuration, the model and the effective limits",
        f"The two paid invocations ran from {kept_times()['first']}Z (plain.start) to {kept_times()['last']}Z (verify.end) on 2026-11-21", "committed at 04:36:35Z (067e917)", "captures at 05:35:16Z (c5c1b08), about one hour later",
    ):
        assert part in text, part
    assert "times of each command" not in text and "and times" not in text and "the only record of the argv" not in text and "ran between" not in text
    assert "assembled by the drive" not in text and "assembled_by" not in (CAMPAIGN_DIR / "command-output.json").read_text(encoding="utf-8")
    assert all(f'href="traces/campaign-public-check/commands/{name}.exit"' in chapter_16() for name in ("plain", "verify"))


def test_chapter_16_says_where_the_served_model_of_each_episode_is_recorded(page):
    # 93-R1-02, #98 Tightened A: the per-Episode record is the kept Inspect log, read through Inspect's log API (ADR 0001); run.json has the summary.
    text = plain_text(chapter_16())
    for part in (
        "The served model of each Episode is recorded in the kept Inspect log, in the output.model of its Inspect sample at its epoch, read through Inspect's log API",
        "served_models in run.json is the per-Attempt summary",
    ):
        assert part in text, part


AG_12_SOURCE = "AG-12 of the L1 specification"


def test_the_ag_12_deviation_names_its_source_in_chapter_16_and_the_readme_next_to_the_pending_owner_review():
    # 93-R3-01: AG-12 is an ID of the L1 specification (SPEC-LOT-1.md, in the kit linked from chadlis/hypotrail#1), which this repository does not hold.
    # D-028 on chadlis/hypotrail#75 asks for the deviation named next to the pending owner review.
    for name, text in (("16-acceptance-grid.html", plain_text(chapter_16())), ("README.md", " ".join((ROOT / "README.md").read_text(encoding="utf-8").split()))):
        assert [m.start() for m in re.finditer("AG-12", text) if not text.startswith(AG_12_SOURCE, m.start())] == [], name
        assert AG_12_SOURCE in text and "SPEC-LOT-1.md" in text and "chadlis/hypotrail#1" in text, name
    status = " ".join(readme_status().split())
    words = status.index(CONDITIONAL_WORDS)
    assert 0 < status.index(AG_12_SOURCE) - words < len(CONDITIONAL_WORDS) + 120  # next to the pending owner review
    assert len(readme_status().split()) <= 200
    assert "The handbook gives each capability in detail." in " ".join(readme_status().split())  # 93-R4-01, within the cap


def test_the_E07_paragraph_says_how_E07_was_resolved_and_links_the_re_review_verdict(page):
    # #99 C7: D-025 on chadlis/hypotrail#75, option B, #94's Case text, #95's verdict "holds".
    paragraph = re.search(r'<p data-e07="resolution">(.*?)</p>', chapter_16(), re.S)[1]
    text = plain_text(paragraph)
    for part in ("D-025", "chadlis/hypotrail#94", "four-character text", "chadlis/hypotrail#95", "7057075785", "holds"):
        assert part in text, part
    # 93-R1-05, D-015 on chadlis/hypotrail#75, point (2): no Reference answer is pasted into the chapter's account of E07.
    reference = next(json.loads(line) for line in (CAMPAIGN_DIR / "study" / "artifacts" / "chinook-references.jsonl").read_text().splitlines() if '"case_id": "E07"' in line)
    cells = {str(cell) for row in reference["rows"] for cell in row}
    assert cells and {cell for cell in cells if re.search(rf"(?<![\w.]){re.escape(cell)}(?![\w.])", text)} == set()
    assert "every E07 answer gave the years as text and matched the Reference" in text


def integer_year_answers(kept_dir):
    """The (Configuration, Repeat) of every kept E07 answer whose year cell is an integer, not text."""
    found = []
    _, attempts = kept_campaign(kept_dir)
    for config, attempt in attempts.items():
        for observation in attempt["observations"]:
            if observation["case_id"] != "E07":
                continue
            raw, decoder = observation["raw_answer"] or "", json.JSONDecoder()
            for index in (m.start() for m in re.finditer(r"\{", raw)):
                try:
                    answer, _ = decoder.raw_decode(raw[index:])
                except ValueError:
                    continue
                if isinstance(answer, dict) and "year" in (answer.get("columns") or []):
                    column = answer["columns"].index("year")
                    if any(isinstance(row[column], int) and not isinstance(row[column], bool) for row in answer["rows"]):
                        found.append((config, observation["repeat"]))
                    break
    return found


def e07_note_problems(chapter, kept_dir=CAMPAIGN_DIR):
    """#99 C, D (D-026 on chadlis/hypotrail#75, item 4): the note on an integer-year answer exists exactly when one occurs in the kept Observation sets."""
    note = re.search(r'<p data-note="e07-integer-year">(.*?)</p>', chapter, re.S)
    occurs = integer_year_answers(kept_dir)
    if not occurs:
        return ["a note on an integer-year answer, though none occurred"] if note else []
    if not note:
        return [f"{len(occurs)} integer-year answers occurred and the chapter has no note"]
    text = plain_text(note[1])
    problems = [f"the note lacks \"{part}\"" for part in ("table-answer.schema.json", "format_valid", "exact_table", "type") if part not in text]
    if "format failure" in text:
        problems.append("the note uses the phrase \"format failure\"")
    return problems


def test_the_E07_note_is_written_exactly_when_an_integer_year_answer_occurs_in_the_kept_observation_sets(page, tmp_path):
    # #99 C (D-026 on chadlis/hypotrail#75, item 4; D-025 on chadlis/hypotrail#75, addendum 1): what the kept answers hold decides. They hold none, so there is no note, and the chapter says so.
    assert integer_year_answers(CAMPAIGN_DIR) == []
    assert e07_note_problems(chapter_16()) == []
    assert "no E07 answer of the Campaign has an integer year" in plain_text(re.search(r'<p data-e07="resolution">(.*?)</p>', chapter_16(), re.S)[1])
    # the witness of the witness: one integer year in a copy of the kept answers makes the note necessary, and a note without one is refused.
    copy = tmp_path / "campaign"
    shutil.copytree(CAMPAIGN_DIR, copy, ignore=shutil.ignore_patterns("report.html"))
    path = next(copy.glob("study/attempts/*/observations.jsonl"))
    lines = path.read_text().splitlines()
    path.write_text("\n".join(line.replace('[\\"2009\\",83]', "[2009,83]") for line in lines) + "\n")
    assert integer_year_answers(copy) != [] and e07_note_problems(chapter_16(), copy) == [f"{len(integer_year_answers(copy))} integer-year answers occurred and the chapter has no note"]
    good = '<p data-note="e07-integer-year">An integer year passes <code>format_valid</code> (table-answer.schema.json allows numbers in cells) and fails <code>exact_table</code>: its type differs from the text cell.</p>'
    assert e07_note_problems(good, copy) == []
    assert e07_note_problems(good.replace("format_valid", "validity"), copy) == ["the note lacks \"format_valid\""]
    assert e07_note_problems(good.replace("fails", "is a format failure and fails"), copy) == ["the note uses the phrase \"format failure\""]
    assert e07_note_problems(good) == ["a note on an integer-year answer, though none occurred"]


def test_no_chapter_or_the_readme_calls_the_campaign_later_work_or_waiting_for_the_owners_review_and_chapter_13_says_where_it_is_kept():
    # #99 C8 and C9.
    sources = {"README.md": (ROOT / "README.md").read_text(encoding="utf-8")}
    sources.update({path.name: path.read_text(encoding="utf-8") for path in sorted((HANDBOOK / "chapters").glob("*.html"))})
    stale = re.compile(r"campaign[^.]{0,120}(?:later work|wait for the owner|waits? for the owner)|later work[^.]{0,120}campaign", re.I)
    assert {name: [plain_text(m[0]) for m in stale.finditer(re.sub(r"\s+", " ", text))] for name, text in sources.items() if stale.search(re.sub(r"\s+", " ", text))} == {}
    chapter_13 = plain_text(sources["13-run-agent.html"])
    assert "traces/campaign-public-check" in chapter_13 and "72-Episode Campaign" in chapter_13
    assert "traces/campaign-public-check" in sources["README.md"]


# --- #88 I: the handbook is complete for the milestone: every command, record and refusal, with the report and the grid ---------


def parser_commands():
    """Every command the parser defines, a command that has sub-commands standing for its leaves (`run agent`, `data fetch`)."""
    from hypotrail.cli import build_parser

    names = []

    def walk(parser, prefix):
        subparsers = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        if not subparsers:
            names.append(prefix)
        for action in subparsers:
            for name, child in action.choices.items():
                walk(child, f"{prefix} {name}".strip())

    walk(build_parser(), "")
    return names


def test_the_commands_the_parser_defines_equal_the_rows_of_the_commands_index_and_each_is_described_in_the_chapter_it_names(page):
    # #88 I: a command added to the parser without its handbook row fails; so does a row whose chapter does not describe it.
    rows = attrs_of(page, "commands-index", "data-command")
    assert sorted(rows) == sorted(parser_commands())
    assert len(parser_commands()) == 15
    assert rows["decide"]["data-chapter"] == "decisions"  # #109 Tightened H: the new chapter describes it
    assert rows["deviation"]["data-chapter"] == "decisions"
    for command, row in rows.items():
        section = re.search(rf'<section id="{re.escape(row["data-chapter"])}".*?</section>', page, re.S)
        assert section, command
        assert f"hypotrail {command}" in section.group(0), (command, row["data-chapter"])


RECORD_TABLES = {  # each record definition of the contract schema: where the handbook lists its fields
    "ArtifactRef": ("record", "record-fields"),
    "StudySpec": ("record", "record-fields"),
    "AttemptManifest": ("record", "record-fields"),
    "ObservationSet": ("record", "record-fields"),
    "ItemCounts": ("record", "item-counts-fields"),
    "Metric": ("record", "assessment-fields"),
    "Counts": ("record", "assessment-fields"),
    "Assessment": ("record", "assessment-fields"),
    "Comparison": ("record", "comparison-fields"),
    "DescriptiveMeasures": ("record", "comparison-parts"),
    "Delta": ("record", "comparison-parts"),
    "FreezeRecord": ("field", "freeze-fields", "freeze"),
    "ExposureEntry": ("field", "entry-fields", None),
    "WriteJournalBegin": ("record", "write-journal-fields"),
    "WriteJournalEnd": ("record", "write-journal-fields"),
    "DecisionRecord": ("record", "decision-fields"),
    "DeclaredDeviationRecord": ("record", "deviation-fields"),
}


def handbook_fields(page, name):
    """The fields the handbook's table of a record lists (required and optional), or None when it has no table of it."""
    how = RECORD_TABLES[name]
    if how[0] == "record":
        row = attrs_of(page, how[1], "data-record").get(name)
        return None if row is None else words(row["data-required"]) | words(row["data-optional"])
    rows = attrs_of(page, how[1], "data-field")
    return {field for field, row in rows.items() if how[2] is None or row.get("data-where") == how[2]}


def test_each_record_definition_of_the_contract_schema_has_a_handbook_table_of_its_fields_equal_to_the_schemas(page):
    # #88 I: a record definition added to the schema without its handbook table fails.
    from hypotrail.core import contracts

    definitions = contracts.schema()["$defs"]
    assert set(definitions) == set(RECORD_TABLES)
    for name, definition in definitions.items():
        assert handbook_fields(page, name) == set(definition["properties"]), name


def raised_codes(root):
    """The error codes the code raises: a literal first argument of an `...Error(...)` call, or the literal a call gives a helper
    that passes its own `code` parameter to one (`_refuse("DUPLICATE_DATE", ...)`)."""
    code = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")

    def called(node):
        return node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""

    def literal(node):
        return isinstance(node, ast.Constant) and isinstance(node.value, str) and code.fullmatch(node.value)

    trees = [ast.parse(path.read_text(encoding="utf-8")) for path in sorted(Path(root).rglob("*.py"))]
    helpers = {
        function.name
        for tree in trees
        for function in ast.walk(tree)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for call in ast.walk(function)
        if isinstance(call, ast.Call) and called(call).endswith("Error") and call.args and isinstance(call.args[0], ast.Name)
        and call.args[0].id in [a.arg for a in function.args.posonlyargs + function.args.args + function.args.kwonlyargs]
    }
    found = set()
    for tree in trees:
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            if called(call).endswith("Error") and call.args and literal(call.args[0]):
                found.add(call.args[0].value)
            if called(call) in helpers:
                found |= {a.value for a in call.args + [k.value for k in call.keywords] if literal(a)}
    return found


def codes_in_table_rows(page):
    rows = re.findall(r"<tr[^>]*>.*?</tr>", page, re.S)
    return {code for row in rows for code in re.findall(r"<code>([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)</code>", row)}


def test_every_error_code_the_code_raises_has_a_row_in_a_handbook_table(page):
    # #88 I: a code added without its handbook row fails (a row is a table row that shows the code in a `code` element).
    raised = raised_codes(ROOT / "src" / "hypotrail")
    assert {"DATA_INTEGRITY", "DUPLICATE_DATE", "STUDY_LOCKED", "DOWNLOAD_FAILED", "UNEXPECTED_ERROR"} <= raised  # the scan reads direct and helper-raised codes
    assert len(raised) > 140
    assert sorted(raised - codes_in_table_rows(page)) == []


def test_the_scan_of_raised_codes_sees_a_code_raised_directly_or_through_a_helper_and_a_code_without_a_row_is_found(tmp_path):
    # #88 I, the witness of the witness: a new code is seen, whichever way it is raised, and is missing from a table that lacks it.
    (tmp_path / "module.py").write_text(
        "from hypotrail.core.errors import InvalidInputError\n"
        "def _refuse(code, message):\n    return InvalidInputError(code, message, stage='x')\n"
        "def one():\n    raise InvalidInputError('A_NEW_CODE', 'm', stage='x')\n"
        "def two():\n    raise _refuse('ANOTHER_NEW_CODE', 'm')\n"
        "def three():\n    return 'NOT_A_RAISED_CODE'\n",
        encoding="utf-8",
    )
    assert raised_codes(tmp_path) == {"A_NEW_CODE", "ANOTHER_NEW_CODE"}
    assert codes_in_table_rows("<table><tr><td><code>A_NEW_CODE</code></td></tr></table><p><code>ANOTHER_NEW_CODE</code></p>") == {"A_NEW_CODE"}


EXIT_OF_CLASS = {"InvalidInputError": 2, "IntegrityError": 3, "HypotrailError": 4}
LIBRARY_CODE_TABLES = ("data-verify-codes", "spike-live-codes", "ml-library-codes", "unexpected-codes", "exposure-basis-code")


def raise_sites(root):
    """{code: {(exit, stage)}} of the places the code raises it: a direct `...Error("CODE", ...)` call or a call to a helper of its own
    module that passes `code` on (`_refuse("CODE", ...)`); a stage given by a module constant is read from it."""
    code = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")

    def called(node):
        return node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""

    sites = {}
    for path in sorted(Path(root).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                     for t in n.targets if isinstance(t, ast.Name)}

        def where(call):
            keywords = {k.arg: k.value for k in call.keywords}
            stage = keywords.get("stage")
            stage = constants.get(stage.id) if isinstance(stage, ast.Name) else getattr(stage, "value", None)
            exit_code = keywords.get("exit_code")
            return (exit_code.value if isinstance(exit_code, ast.Constant) else EXIT_OF_CLASS.get(called(call)), stage)

        helpers = {}
        for function in ast.walk(tree):
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parameters = [a.arg for a in function.args.posonlyargs + function.args.args + function.args.kwonlyargs]
                for call in ast.walk(function):
                    if isinstance(call, ast.Call) and called(call).endswith("Error") and call.args and isinstance(call.args[0], ast.Name) and call.args[0].id in parameters:
                        helpers[function.name] = where(call)
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            if called(call).endswith("Error") and call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str) and code.fullmatch(call.args[0].value):
                sites.setdefault(call.args[0].value, set()).add(where(call))
            elif called(call) in helpers:
                for argument in call.args + [k.value for k in call.keywords]:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str) and code.fullmatch(argument.value):
                        sites.setdefault(argument.value, set()).add(helpers[called(call)])
    return sites


def test_the_exit_and_stage_of_each_row_of_the_library_refusal_tables_are_those_of_the_places_the_code_raises_it(page):
    # #88 I: the rows added for the codes no other table had state the exit code and the stage(s) the code gives; none is left to memory.
    sites = raise_sites(ROOT / "src" / "hypotrail")
    seen = 0
    for table_id in LIBRARY_CODE_TABLES:
        for code, row in attrs_of(page, table_id, "data-code").items():
            assert {(int(row["data-exit"]), stage) for stage in row["data-stage"].split()} == sites[code], code
            seen += 1
    assert seen == 7 + 5 + 17 + 2 + 1


# --- #109: `decide` and the decision record (chapter 17) ---------------------------------------------------------------------------------


def chapter_text(name):
    return (HANDBOOK / "chapters" / name).read_text(encoding="utf-8")


def test_the_decide_command_table_equals_the_flags_the_parser_defines(page):
    from hypotrail.cli import build_parser

    parser = build_parser()
    decide = next(a for a in parser._actions if getattr(a, "choices", None) and "decide" in a.choices).choices["decide"]
    options = {flag: a.required for a in decide._actions for flag in a.option_strings if flag not in ("-h", "--help")}
    row = attrs_of(page, "decide-command", "data-command")["decide"]
    assert words(row["data-required"]) == {flag for flag, required in options.items() if required}
    assert words(row["data-optional"]) == {flag for flag, required in options.items() if not required}
    assert words(row["data-required"]) >= {"--study", "--question", "--option", "--author", "--artifact", "--request-id", "--read-sequence"}
    assert words(row["data-optional"]) >= {"--source", "--json"}


def _decided(tmp_path, name="chapter-17"):
    """(Study, the files it holds before and after one `decide`, the record it wrote)."""
    from _study_helpers import init_study, run_json, run_ml

    study, _ = init_study(tmp_path, name=name)
    _, attempt, _ = run_ml(study, "seasonal_7", "dev", "held")
    before = {p.relative_to(study).as_posix() for p in study.rglob("*") if p.is_file()}
    code, payload, err = run_json(
        "decide", "--study", study, "--question", "Which Configuration do we keep?", "--option", "ridge_v1", "--author", "proxy",
        "--source", "a rule", "--artifact", attempt["attempt"]["attempt_id"], "--request-id", "d-1", "--read-sequence", 4,
    )
    assert code == 0, (payload, err)
    after = {p.relative_to(study).as_posix() for p in study.rglob("*") if p.is_file()}
    return study, before, after, payload["decision"]


def test_the_decision_record_table_equals_the_contract_schema_and_the_fields_the_code_writes(page, tmp_path):
    from hypotrail.core import contracts

    definition = contracts.schema()["$defs"]["DecisionRecord"]
    row = attrs_of(page, "decision-fields", "data-record")["DecisionRecord"]
    assert words(row["data-required"]) == set(definition["required"])
    assert words(row["data-optional"]) == set(definition["properties"]) - set(definition["required"])
    assert row["data-kind"] == "decision" == definition["properties"]["kind"]["const"]
    _, _, _, record = _decided(tmp_path)
    assert set(record) == words(row["data-required"]) | words(row["data-optional"])
    assert set(attrs_of(page, "decision-field-meaning", "data-field")) == set(definition["properties"])


def test_the_decision_layout_table_equals_the_files_decide_writes(page, tmp_path):
    study, before, after, record = _decided(tmp_path)
    added = {path.replace(record["decision_id"], "DECISION_ID") for path in after - before}
    added = {re.sub(r"decisions/[0-9]{6}-", "decisions/SEQ-", path) for path in added}
    rows = attrs_of(page, "decision-layout", "data-path")
    assert {path for path in added if path.startswith("decisions/")} == set(rows) == {"decisions/SEQ-DECISION_ID.json"}
    assert {path for path in added if not path.startswith("decisions/")} == {"write_journal/000005.json", "write_journal/000006.json"}  # chapter 04's row
    assert "write_journal/SEQ.json" in attrs_of(page, "study-layout", "data-path")
    assert "decide" in rows["decisions/SEQ-DECISION_ID.json"]["data-written-by"].split()


def decide_refusals(tmp_path):
    """Provoke each refusal of the table with `decide`; return {code: (exit code, stage, set of details keys)}."""
    from _study_helpers import init_study, run_json, run_ml

    from hypotrail.core import lock

    found = {}
    study, _ = init_study(tmp_path, name="chapter-17-refusals")
    _, attempt, _ = run_ml(study, "seasonal_7", "dev", "held")
    cited = attempt["attempt"]["attempt_id"]

    def call(*, study=study, cited=cited, omit=(), **fields):
        values = {"question": "Q?", "option": "o", "author": "human", "request_id": "d-1", "read_sequence": 2 + 2, **fields}
        flags = [("--study", study), ("--question", values["question"]), ("--option", values["option"]), ("--author", values["author"]),
                 ("--request-id", values["request_id"]), ("--read-sequence", values["read_sequence"]), ("--artifact", cited)]
        code, payload, err = run_json("decide", *[x for flag, value in flags if flag not in omit for x in (flag, value)])
        error = payload["error"]
        found[error["code"]] = (code, error["stage"], set(error["details"]))

    call(omit=("--artifact",))  # INVALID_ARGUMENTS
    call(request_id="")  # REQUEST_ID_EMPTY
    call(study=tmp_path / "none")  # STUDY_NOT_FOUND
    call(question="")  # DECISION_FIELD_EMPTY
    with lock.writer_lock(study):
        call()  # STUDY_LOCKED
    call(request_id="held")  # REQUEST_CONFLICT: the request_id of the Attempt
    call(read_sequence=0)  # STUDY_CHANGED
    call(read_sequence=10**6)  # WRITE_SEQUENCE_AHEAD
    call(cited="unknown")  # CITED_ID_NOT_FOUND
    code, payload, err = run_json(
        "decide", "--study", study, "--question", "Q?", "--option", "o", "--author", "human", "--artifact", cited, "--request-id", "d-ok", "--read-sequence", 4
    )
    assert code == 0, (payload, err)
    [file] = sorted((study / "decisions").glob("*.json"))
    record = json.loads(file.read_text(encoding="utf-8"))
    del record["option"]
    file.write_text(json.dumps(record), encoding="utf-8")
    call(request_id="d-ok", read_sequence=6)  # CONTRACT_VIOLATION when the record is read for a replay
    return found


def test_the_decide_refusal_table_equals_the_code_exit_stage_and_details_of_each_refusal(page, tmp_path):
    found = decide_refusals(tmp_path)
    rows = attrs_of(page, "decide-codes", "data-code")
    assert {"DECISION_FIELD_EMPTY", "CITED_ID_NOT_FOUND"} <= set(rows)
    assert set(rows) == set(found)
    for code, row in rows.items():
        exit_code, stage, details = found[code]
        assert int(row["data-exit"]) == exit_code, code
        assert row["data-stage"] == stage, code
        assert words(row["data-details"]) == details, code
    assert found["DECISION_FIELD_EMPTY"] == (2, "decision", {"field"})
    assert found["CITED_ID_NOT_FOUND"] == (2, "decision", {"ids"})
    assert set(rows) == {
        "INVALID_ARGUMENTS", "REQUEST_ID_EMPTY", "DECISION_FIELD_EMPTY", "STUDY_NOT_FOUND", "STUDY_LOCKED",
        "REQUEST_CONFLICT", "STUDY_CHANGED", "WRITE_SEQUENCE_AHEAD", "CITED_ID_NOT_FOUND", "CONTRACT_VIOLATION",
    }  # `decide` gains no refusal: the ten codes of the table at `7db697f`


def prose_of(chapter: str) -> str:
    """A chapter without its tables and code blocks: what is left is the prose around them, which does not restate them."""
    return re.sub(r"<pre.*?</pre>", "", re.sub(r"<table.*?</table>", "", chapter, flags=re.S), flags=re.S)


# Two sentences, each quoted from its own source: the first names the two exceptions, the second exempts their flags from the prose guard.
THE_TWO_FLAGS_OF_TIGHTENED_M = (
    "\"Chapter 04's order paragraph names these two exceptions.\" (chadlis/hypotrail#108, Tightened M); "
    "\"The prose guard test exempts those two flags, citing Tightened M.\" (D-041 on chadlis/hypotrail#75, item 2)"
)
# R2-S-01, R2-S-02: the handbook rule of the drive skill, "The prose around such a table does not restate it", checked over the whole class.
# A word the prose of a section must use to explain what its tables do not say; each is named by a table (a code, a flag or a key) and has its reason.
PROSE_MAY_NAME = {
    "--read-sequence": "the option chapter 04's read-sequence section is about; it is also the flag of chapter 17's decide row",
    "--json": "the output mode whose shape chapter 17 describes and whose `status --json` chapter 17 says what it lists and does not list",
    "write_sequence": "the number the section explains; a table names it as a key, no table says what advances it or what a record's copy is",
    "read_sequence": "chapter 17 says how a record's read_sequence relates to its write_sequence (always one less), which no table says",
    "request_id": "the identity of a replay and of the one namespace, which the sections explain; the tables only name it as a key",
    "decision_id": "chapter 17 says a decision is cited by this id; the tables only name it as a key",
    "revision": "chapter 17 says when the revision of a decision is read (under the lock, after the sequence check), which no table says",
    "revision_number": "chapter 17 says it is not citable, so that one revision never appears under two ids (#109 asks for it); no table says so",
    "outcome": "chapter 04 says which values the outcome of an end entry takes and when; the table only names the key",
    "--factor": THE_TWO_FLAGS_OF_TIGHTENED_M,
    "--out": THE_TWO_FLAGS_OF_TIGHTENED_M,
    "failed": "a value of outcome, in chapter 04's account of how each command ends; the item-counts table also has a `failed` key",
}


def tables_with_data_attributes(*chapters):
    """The codes, reasons, keys and flags the tables with data attributes of the chapters list, and the numbers their rows advance the sequence by."""
    listed, advances = set(), set()
    for chapter in chapters:
        for table in re.findall(r"<table.*?</table>", chapter, re.S):
            for row in re.findall(r"<tr ([^>]*data-[^>]*)>", table):
                attributes = dict(re.findall(r'data-([a-z-]+)="([^"]*)"', row))
                listed.update(attributes[name] for name in ("code", "reason", "field") if name in attributes)
                listed.update(word for name in ("required", "optional", "details") for word in attributes.get(name, "").split())
                listed.update(word for word in attributes.get("command", "").split() if word.startswith("--"))  # the flag a row names beside its command
                if "advances" in attributes:
                    advances.add(attributes["advances"])
    return listed, advances


def words_in_code(prose):
    """The words of every <code> element of `prose`, as a reader sees them (a flag with its dash, a path whole). An element of more than three words is a sample of output, not a name."""
    text = [html.unescape(re.sub(r"<[^>]+>", "", code)) for code in re.findall(r"<code>(.*?)</code>", prose, re.S)]
    return {word.strip(".,;:()[]{}\"'") for each in text if len(each.split()) <= 3 for word in each.split()} - {""}


def sections_whose_prose_leaves_the_tables_to_state_the_rules():
    """Chapter 17 and chapter 04's write-sequence section: the sections whose rules (codes, flags, keys, advances) live in tables with data attributes.

    A section belongs here when a table of it states a rule that its prose could repeat; the prose of such a section only says what no table says."""
    chapter_04, chapter_17 = chapter_text("04-study-and-attempts.html"), chapter_text("17-decisions.html")
    write_sequence = chapter_04.split('<p class="sub2">The Write sequence</p>')[1].split('<p class="sub2">Exit codes and refusals</p>')[0]
    return {"chapter 04, the write sequence": write_sequence, "chapter 17": chapter_17}


def test_the_prose_of_chapter_17_and_chapter_04_write_sequence_section_names_none_of_the_codes_flags_or_keys_the_tables_list():
    listed, advances = tables_with_data_attributes(chapter_text("04-study-and-attempts.html"), chapter_text("17-decisions.html"))
    assert {"STUDY_CHANGED", "REQUEST_CONFLICT", "--read-sequence", "request_id", "applies"} <= listed  # the collection reads the tables
    assert advances == {"2"}
    assert set(PROSE_MAY_NAME) <= listed, set(PROSE_MAY_NAME) - listed  # an entry that no table lists is not an exception to anything
    used = set().union(*(words_in_code(prose_of(section)) for section in sections_whose_prose_leaves_the_tables_to_state_the_rules().values()))
    assert set(PROSE_MAY_NAME) <= used, set(PROSE_MAY_NAME) - used  # the list stays what the prose needs
    for name, section in sections_whose_prose_leaves_the_tables_to_state_the_rules().items():
        prose = prose_of(section)
        assert sorted((listed & words_in_code(prose)) - set(PROSE_MAY_NAME)) == [], name
        assert [n for n in advances if re.search(rf"advances? (the (write )?sequence )?by ({n}|two)\b", " ".join(re.sub(r"<[^>]+>", "", prose).split()))] == [], name


def chapter_04_order_paragraph():
    chapter = chapter_text("04-study-and-attempts.html")
    return chapter, next(p for p in re.findall(r"<p>.*?</p>", chapter, re.S) if "The refusals come in this order" in p)


def test_chapter_04_order_paragraph_names_compare_factor_and_report_out_by_command():
    _, paragraph = chapter_04_order_paragraph()
    assert "<code>compare --factor</code>" in paragraph and "<code>report --out</code>" in paragraph


def test_chapter_04_order_paragraph_points_to_the_table_of_checks_before_the_lock_that_the_chapter_holds():
    chapter, paragraph = chapter_04_order_paragraph()
    assert "before the lock" in paragraph and "table of checks before the lock" in paragraph
    assert 'id="checks-before-the-lock"' in chapter


def test_chapter_04_order_paragraph_names_none_of_the_codes_of_the_table_of_checks_before_the_lock():
    chapter, paragraph = chapter_04_order_paragraph()
    rows = rows_of_checks_table(chapter)
    assert rows
    for check, (_, code) in rows.items():
        assert code not in paragraph, check


def test_chapter_04_order_paragraph_states_no_count_of_the_checks_or_rows_of_the_table():
    _, paragraph = chapter_04_order_paragraph()
    assert not re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+) (checks|rows)\b", paragraph)


def test_chapter_04_order_paragraph_says_the_table_lists_the_checks_beyond_this_general_order_that_read_more_than_the_arguments():
    _, paragraph = chapter_04_order_paragraph()
    assert "beyond this general order" in paragraph and "read more than the arguments" in paragraph


def test_chapter_04_gives_the_modes_by_the_values_the_glossary_defines():
    chapter = chapter_text("04-study-and-attempts.html")
    assert "<code>scripted_fixture</code> Mode" in chapter and "<code>llm_live</code> Mode" in chapter
    assert not re.search(r"scripted fixture Mode|the live Mode", chapter)


def test_chapter_04_table_gives_the_commands_that_take_the_read_sequence_as_the_parser_defines_them(page):
    # R1-S-02: the commands are a column of `write-sequence-commands`, not a list in prose
    from hypotrail.cli import build_parser

    rows = attrs_of(page, "write-sequence-commands", "data-command")
    given = {command: row.get("data-read-sequence") for command, row in rows.items()}
    assert set(given.values()) <= {"none", "optional", "required"}, given
    assert {c for c, v in given.items() if v == "none"} == {"init"}  # `init` that creates a Study is refused the option (tests/test_stale_sequence.py)

    def option(*path):
        node = build_parser()
        for name in path:
            node = next(a for a in node._actions if getattr(a, "choices", None) and name in a.choices).choices[name]
        return next((a for a in node._actions if "--read-sequence" in a.option_strings), None)

    for command, value in given.items():
        if value == "none":
            continue
        action = option(*[word for word in command.split() if not word.startswith("--")])
        assert action is not None, command
        assert ("required" if action.required else "optional") == value, command
    assert given["decide"] == "required" and given["report"] == "optional"


def test_chapter_04_prose_does_not_restate_the_write_sequence_tables_or_list_the_commands_that_take_the_read_sequence():
    # R1-S-02, the handbook rule of the drive skill: "The prose around such a table does not restate it."
    chapter = chapter_text("04-study-and-attempts.html")
    prose = prose_of(chapter)
    assert "advances the sequence by 2" not in prose  # `write-sequence-commands`
    assert "<code>phase</code>" not in prose  # `write-journal-fields`
    reading = next(p for p in re.findall(r"<p>.*?</p>", prose, re.S) if "Reading the sequence before a write" in p)
    assert not [c for c in ("run ml", "run agent", "import ml", "import agent", "assess", "compare") if f"<code>{c}</code>" in reading]
    assert "<code>decision_id</code>" in chapter and "one <code>request_id</code> namespace" in chapter
    assert 'data-command="decide"' in chapter  # its row in `write-sequence-commands` and in `commands-index`


def test_chapter_17_says_status_lists_the_assessments_and_comparisons_and_no_observation_set_and_names_the_citable_kinds():
    chapter = " ".join(re.sub(r"<[^>]+>", " ", chapter_text("17-decisions.html")).split())
    for kind in ("Attempt", "Observation set", "Assessment", "Comparison", "Study artifact", "revision", "freeze record", "Exposure entry", "decision", "Declared deviation"):
        assert kind in chapter, kind
    assert "revision_number" in chapter and "not citable" in chapter
    assert "status --json" in chapter
    assert "lists no Observation set, Assessment or Comparison" not in chapter
    assert "lists no Observation set" in chapter


def section_holding(chapter: str, table_id: str) -> str:
    """The section of a chapter, from the `sub2` heading before the table `table_id` to the next `sub2` heading."""
    before, after = chapter.split(f'id="{table_id}"', 1)
    return before.rsplit('<p class="sub2">', 1)[1] + after.split('<p class="sub2">', 1)[0]


def test_the_chapter_04_section_of_the_status_keys_table_tells_a_client_to_ignore_a_key_it_does_not_know():
    section = plain_text(section_holding(chapter_text("04-study-and-attempts.html"), "status-keys"))
    sentences = [s for s in re.split(r"(?<=\.)\s+", section) if "ignore" in s and "does not know" in s]
    assert len(sentences) == 1, sentences


def test_the_readme_names_decide_in_its_status_and_gives_its_command_after_the_walked_path_with_the_required_options():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    status = readme.split("## Status\n", 1)[1].split("\n## ", 1)[0]
    assert "`decide`" in status
    block, after = readme.split("```")[1], readme.split("```", 2)[2]
    assert "decide" not in block  # the block is the path the T24 walk record keeps: a command is not added to it without a walk
    sentence = next(part for part in re.split(r"\n\n", after) if "`decide` records one decision" in part)
    for flag in ("--study", "--question", "--option", "--author", "--artifact", "--request-id", "--read-sequence"):
        assert flag in sentence, flag


# --- #110: the decision history in `status --json` (chapter 17) ---------------------------------------------------------------------------


def _history(tmp_path, name="chapter-17-history"):
    """(the rows `status --json` lists, the reasons they hold) for a Study with one decision of each kind of reason, and one that applies."""
    from _assess_helpers import assess, observation_set_id, references_id
    from _study_helpers import examples_copy, init_study, run_json, run_ml
    from _revision_helpers import new_revision

    def corrected_day(table):
        row = next(r for r in table if r["dteday"] == "2012-03-15")
        row["cnt"], row["registered"] = str(int(row["cnt"]) + 1000), str(int(row["registered"]) + 1000)

    study, _ = init_study(tmp_path, name=name)
    _, run, _ = run_ml(study, "seasonal_7", "dev", "held")
    attempt = run["attempt"]
    observations, references = observation_set_id(study, attempt), references_id(study)
    _, first, _ = assess(study, observations, "regression_mae_v1", references)
    _, ridge_run, _ = run_ml(study, "ridge_v1", "dev", "ridge")
    _, ridge, _ = assess(study, observation_set_id(study, ridge_run["attempt"]), "regression_mae_v1", references)
    code, compared, err = run_json("compare", "--study", study, "--control", first["assessment"]["assessment_id"], "--candidate", ridge["assessment"]["assessment_id"])
    assert code == 0, (compared, err)

    def decide(request_id, cited):
        flags = ["--study", study, "--question", "Which Configuration do we keep?", "--option", "ridge_v1", "--author", "human", "--request-id", request_id]
        sequence = run_json("status", "--study", study)[1]["write_sequence"]
        code, payload, err = run_json("decide", *flags, "--read-sequence", sequence, *[x for each in cited for x in ("--artifact", each)])
        assert code == 0, (payload, err)
        return payload["decision"]

    on_an_attempt = decide("d-1", [attempt["attempt_id"]])
    decide("d-2", [first["assessment"]["assessment_id"]])
    decide("d-3", [on_an_attempt["decision_id"]])
    decide("d-4", [compared["comparison"]["comparison_id"]])
    code, again, err = assess(study, observations, "regression_mae_v1", references)
    assert code == 0, (again, err)  # d-2 is superseded, and d-4 is reached through the Comparison's Control
    shutil.rmtree(study / "assessments" / ridge["assessment"]["assessment_id"])  # d-4's Comparison names a Candidate no longer held
    next(p for p in (study / "decisions").glob(f"*-{on_an_attempt['decision_id']}.json")).unlink()  # d-3 cites an id no longer held
    code, payload, err = new_revision(study, "--examples-dir", examples_copy(tmp_path, rows=corrected_day, name="revised"))
    assert code == 0, (payload, err)  # every decision made before it is outdated for the revision
    listing = run_json("status", "--study", study)[1]
    assert "decisions" in listing, "status --json lists no decisions"
    rows = listing["decisions"]
    return rows, {reason["reason"] for row in rows for reason in row["reasons"]}


def test_the_decision_history_table_equals_the_keys_status_reports_for_a_decision(page, tmp_path):
    from hypotrail.core import contracts

    rows, _ = _history(tmp_path)
    keys = set(attrs_of(page, "decision-history-keys", "data-field"))
    assert keys == set(rows[0]) == set(contracts.schema()["$defs"]["DecisionRecord"]["properties"]) | {"applies", "reasons", "evidence_change"}
    assert len(keys) == 15
    assert all(set(row) == keys for row in rows)


def test_the_decision_reasons_table_equals_the_reason_codes_constant_and_the_reasons_status_reports_and_the_keys_of_each_reason(page, tmp_path):
    from hypotrail.core import decisions

    rows, reasons = _history(tmp_path)
    table = attrs_of(page, "decision-reasons", "data-reason")
    assert set(table) == reasons == set(decisions.REASON_CODES)
    assert len(decisions.REASON_CODES) == len(set(decisions.REASON_CODES)) == 5
    assert {"compared_assessment_superseded", "compared_assessment_not_held"} <= reasons
    assert {tuple(sorted(reason)) for row in rows for reason in row["reasons"]} == {("id", "reason")}


def test_chapter_17_no_longer_says_the_rule_reads_three_things_and_defines_the_hop_where_it_first_uses_the_word():
    text = plain_text(chapter_text("17-decisions.html"))
    assert "these three things and nothing else" not in text
    sentences = [s for s in re.split(r"(?<=[.:])\s+", text) if re.search(r"\bhop\b", s)]
    assert sentences, "chapter 17 does not use the word hop"
    assert "from a cited Comparison to its two Assessments" in sentences[0], sentences[0]


def test_chapter_17_gives_the_rule_of_still_applies_in_its_table_and_what_the_table_does_not_say_in_words(page):
    chapter = " ".join(re.sub(r"<[^>]+>", " ", chapter_text("17-decisions.html")).split())
    table = " ".join(re.sub(r"<[^>]+>", " ", re.search(r'<table[^>]*id="decision-reasons".*?</table>', chapter_text("17-decisions.html"), re.S)[0]).split())
    assert "A Decision no longer applies when" in chapter
    for part in ("A cited id is no longer held by the Study", "differs from the Decision's revision", "later Assessment of the same Observation set and Scorer id"):
        assert part in table, part
    assert "never stored" in chapter and "any version" in chapter and "write journal" in chapter
    assert "later Decision on the same question" in chapter
    assert "does not list decisions yet" not in chapter and "does not list the decisions" not in chapter
    assert "Decisions: 4 recorded, 1 no longer applies" in chapter


def test_chapter_17_prose_does_not_restate_the_decide_command_the_history_keys_or_the_reasons_tables(page):
    # R1-S-01, the handbook rule of the drive skill: "The prose around such a table does not restate it."
    prose = prose_of(chapter_text("17-decisions.html"))
    row = attrs_of(page, "decide-command", "data-command")["decide"]
    flags = (words(row["data-required"]) | words(row["data-optional"])) - {"--json"}
    assert [flag for flag in flags if flag in prose] == []  # `decide-command`: which flags there are, and whether each is required
    assert "<code>applies</code>" not in prose and "<code>reasons</code>" not in prose  # `decision-history-keys`
    assert "two keys that are not in the record" not in prose
    assert [name for name in attrs_of(page, "decision-reasons", "data-reason") if name in prose] == []  # `decision-reasons`


def test_the_readme_status_keeps_the_claims_the_slice_dropped():
    # R1-P-02, D-039 on chadlis/hypotrail#75: no ticket asked to weaken these claims
    status = " ".join(readme_status().split())
    for claim in ("end to end", "SQLite", "self-contained", "writes a Comparison of two Assessments of either Track"):
        assert claim in status, claim


def test_the_readme_status_names_the_study_whose_state_and_decision_history_status_shows():
    # R2-P-03: "its state" had no Study before it (the nearest noun was a Comparison)
    assert "`status` shows a Study's state and decision history" in " ".join(readme_status().split())


def test_the_readme_names_the_decision_history_in_the_status_command():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    line = next(l for l in readme.splitlines() if "hypotrail status --study" in l)
    assert "decisions" in line and "still applies" in line


CHANGED_BY_THE_WRITE_SEQUENCE_AND_DECISIONS = [
    "04-study-and-attempts.html",
    "05-assessments.html",
    "06-import.html",
    "07-comparison.html",
    "08-agent-answers.html",
    "13-run-agent.html",
    "14-report.html",
    "17-decisions.html",
]


@pytest.mark.parametrize("chapter", CHANGED_BY_THE_WRITE_SEQUENCE_AND_DECISIONS)
def test_every_chapter_that_the_write_sequence_and_decisions_changed_links_the_panel_cli_adr_in_its_adr_table(chapter):
    # #111: the chapters #107 to #110 changed (`git diff 607740c 0e81949 --stat -- docs/handbook/chapters`)
    text = (HANDBOOK / "chapters" / chapter).read_text(encoding="utf-8")
    heading = '<p class="sub2">Which ADR explains what</p>'
    assert heading in text, f"{chapter} has no \"Which ADR explains what\" table"
    table = text.split(heading, 1)[1].split("</table>", 1)[0]
    adr = sorted((ROOT / "docs" / "adr").glob("0004-*.md"))
    assert len(adr) == 1, "there is no ADR 0004"
    assert f'<a href="../adr/{adr[0].name}">0004</a>' in table, f"{chapter}: its ADR table has no row that links {adr[0].name}"


def test_chapter_04_read_sequence_paragraph_says_a_command_given_no_option_behaves_as_before():
    # R4-P-01 (#108 "when it is not given, the command behaves exactly as today"): one sentence on direct use, no row of a table restated
    chapter = chapter_text("04-study-and-attempts.html")
    paragraph = next(p for p in re.findall(r"<p>.*?</p>", chapter, re.S) if "Reading the sequence before a write" in p)
    sentence = "A command for which the table makes the option optional, given none, behaves as it did before the option existed"  # R5-P-01 narrowed it
    assert sentence in " ".join(paragraph.replace("<code>", "").replace("</code>", "").split())


def test_chapter_13_lead_points_to_the_order_paragraph_of_chapter_04_where_run_agent_differs_from_run_ml():
    # R4-P-02 (#108 Tightened L): `run agent` does not have "the same order of checks" as `run ml`; chapter 04's order paragraph says where it differs
    lead = re.search(r'<p class="lead">.*?</p>', chapter_text("13-run-agent.html"), re.S).group(0)
    assert "the same order of checks" not in lead
    assert 'order paragraph of <a href="#study-and-attempts">chapter 04</a>, where <code>run agent</code> differs from <code>run ml</code>' in lead


def test_chapter_04_read_sequence_paragraph_leaves_decide_and_the_journal_out_of_the_as_before_sentence():
    # R5-P-01, R5-S-05 (#108 "when it is not given, the command behaves exactly as today" is for the commands that take the option as an option; `decide` requires it)
    chapter = chapter_text("04-study-and-attempts.html")
    paragraph = next(p for p in re.findall(r"<p>.*?</p>", chapter, re.S) if "Reading the sequence before a write" in p)
    text = " ".join(re.sub(r"<[^>]+>", "", paragraph).split())
    assert "A command given no --read-sequence behaves as it did before the option existed." not in text  # it covered `decide`
    sentence = next(s for s in re.split(r"(?<=\.) ", text) if "before the option existed" in s)
    assert "optional" in sentence and "table" in sentence  # limited to the commands the table makes optional, without restating a row
    assert "journal entries" in sentence and "all the same" in sentence  # a command given no option still appends its entries


def test_chapter_13_order_section_holds_the_read_sequence_steps_between_the_request_identity_and_the_data_check():
    # R5-P-02 (#108 Tightened L): the sequence argument check, then the stale-sequence refusal straight after the request identity, before `DATA_INTEGRITY`
    chapter = chapter_text("13-run-agent.html")
    section = chapter.split('<p class="sub2">The order</p>')[1].split("</ol>", 1)[0]
    steps = re.findall(r"<li>(.*?)</li>", section, re.S)
    index = lambda *needles: next((i for i, s in enumerate(steps) if all(n in s for n in needles)), -1)  # -1: no such step
    identity = index("The request is identified")
    stale = index("STUDY_CHANGED", "WRITE_SEQUENCE_AHEAD")
    data = index("DATA_INTEGRITY", "ARTIFACT_INTEGRITY")
    assert stale != -1, "the list has no stale-sequence step"
    assert identity + 1 == stale and stale + 1 == data
    assert "--read-sequence" in steps[0] and "INVALID_ARGUMENTS" in steps[0]  # the argument check of the value is among the flag checks, before the lock
    first = steps[0]
    assert "argument alone" in first, "step 1 does not say the read-sequence check looks at the argument alone"
    assert first.index("--read-sequence") < first.index("declaration"), "step 1 names the read-sequence check after the declaration checks"  # run.py runs it first, before the Study and declaration reads
    assert first.index("INVALID_ARGUMENTS") < first.index("declaration")


def test_chapter_04_order_paragraph_says_only_the_data_and_artifact_checks_of_run_agent_come_after_the_comparison():
    # R5-P-03 (#108 Tightened L): for `run agent`, `DATA_INTEGRITY` and the `ARTIFACT_*` codes fall in step (6); the others keep their place, named by no code here (a table gives the codes)
    chapter = chapter_text("04-study-and-attempts.html")
    paragraph = next(p for p in re.findall(r"<p>.*?</p>", chapter, re.S) if "The refusals come in this order" in p)
    text = " ".join(re.sub(r"<[^>]+>", "", paragraph).split())
    assert "in run agent, whose identity reads its input bytes directly, only the data check and the artifact checks come after the comparison" in text
    assert "the others keep their place, before the lock or before the identity" in text
    assert "DATA_INTEGRITY" not in paragraph and "ARTIFACT_" not in paragraph  # the refusals table gives them


# --- #154: the single-feature check (chapters 05 and 07) ---------------------------------------------------------------------------------


def test_chapter_05s_list_item_of_what_assess_reads_back_against_its_digest_names_the_dataset_copy_and_when_it_is_read():
    items = [plain_text(item) for item in re.findall(r"<li>.*?</li>", chapter_text("05-assessments.html"), re.S)]
    found = [item for item in items if "read back against its digest" in item]
    assert len(found) == 1, found
    assert "dataset" in found[0] and "lag feature" in found[0], found[0]


def test_predicts_nothing_is_said_of_compare_in_chapter_07_and_in_no_other_chapter():
    saying = sorted(path.name for path in (HANDBOOK / "chapters").glob("*.html") if "predicts nothing" in plain_chapter(path.name))
    assert saying == ["07-comparison.html"]


def test_the_assess_refusal_table_of_chapter_05_gains_no_row(page):
    assert set(attrs_of(page, "assess-codes", "data-code")) == {
        "SCORER_NOT_REGISTERED", "UNSUPPORTED_CAPABILITY", "OBSERVATION_SET_NOT_FOUND", "REFERENCES_NOT_FOUND", "OBSERVATIONS_INVALID", "ASSESSMENT_PARTITION_NOT_DEV",
    }


# --- #155: the Declared deviation (chapters 04, 07, 11 and 17, and the README) -------------------------------------------------------


def _deviation_study(tmp_path, name="chapter-17-deviation"):
    """(Study, the files it holds before and after one Declared deviation, the record it wrote)."""
    from _deviation_helpers import declare
    from _study_helpers import init_study, run_ml

    study, _ = init_study(tmp_path, name=name)
    _, attempt, _ = run_ml(study, "seasonal_7", "dev", "held")
    before = {p.relative_to(study).as_posix() for p in study.rglob("*") if p.is_file()}
    record = declare(study, [attempt["attempt"]["attempt_id"]], request_id="dv-1")
    after = {p.relative_to(study).as_posix() for p in study.rglob("*") if p.is_file()}
    return study, before, after, record


def test_the_declared_deviation_record_table_of_chapter_17_equals_the_contract_schema_and_the_fields_the_command_writes(page, tmp_path):
    from hypotrail.core import contracts

    definition = contracts.schema()["$defs"]["DeclaredDeviationRecord"]
    section = re.search(r'<section id="decisions".*?</section>', page, re.S)[0]
    row = attrs_of(section, "deviation-fields", "data-record")["DeclaredDeviationRecord"]
    assert words(row["data-required"]) == set(definition["required"])
    assert words(row["data-optional"]) == set(definition["properties"]) - set(definition["required"])
    assert row["data-kind"] == "declared_deviation" == definition["properties"]["kind"]["const"]
    _, before, after, record = _deviation_study(tmp_path)
    assert set(record) == words(row["data-required"]) | words(row["data-optional"])
    added = {re.sub(r"declared_deviations/[0-9]{6}-", "declared_deviations/SEQ-", path.replace(record["declared_deviation_id"], "DEVIATION_ID")) for path in after - before}
    assert set(attrs_of(section, "deviation-layout", "data-path")) == {path for path in added if path.startswith("declared_deviations/")}


def deviation_refusals(tmp_path):
    """Provoke each refusal of the `deviation` command; return {code: (exit code, stage, set of details keys)}."""
    from _deviation_helpers import declare, deviation, references_of
    from _study_helpers import init_study, run_json, run_ml

    from hypotrail.core import lock

    found = {}
    study, _ = init_study(tmp_path, name="chapter-17-deviation-refusals")
    _, attempt, _ = run_ml(study, "seasonal_7", "dev", "held")
    cited = attempt["attempt"]["attempt_id"]
    code, payload, err = run_json("assess", "--study", study, "--observations", json.loads((study / "attempts" / cited / "observation_set.json").read_text())["observation_set_id"],
                                  "--scorer", "regression_mae_v1", "--references", references_of(study))
    assessment = payload["assessment"]["assessment_id"]
    declared = declare(study, [cited], request_id="dv-held")["declared_deviation_id"]
    other = declare(study, [references_of(study)])["declared_deviation_id"]
    withdrawn = declare(study, [cited])["declared_deviation_id"]
    withdrawal = declare(study, [withdrawn], text="withdrawn")["declared_deviation_id"]

    def call(ids=(cited,), **fields):
        code, payload, err = deviation(fields.pop("study", study), list(ids), **fields)
        error = payload["error"]
        found[error["code"]] = (code, error["stage"], set(error["details"]))

    call(omit=("--artifact",))  # INVALID_ARGUMENTS
    call(request_id="")  # REQUEST_ID_EMPTY
    call(text="")  # DEVIATION_TEXT_EMPTY
    call(study=tmp_path / "none", read_sequence=0)  # STUDY_NOT_FOUND
    with lock.writer_lock(study):
        call()  # STUDY_LOCKED
    call(request_id="held")  # REQUEST_CONFLICT: the request_id of the Attempt
    call(read_sequence=0)  # STUDY_CHANGED
    call(read_sequence=10**6)  # WRITE_SEQUENCE_AHEAD
    call(ids=["unknown"])  # CITED_ID_NOT_FOUND
    call(ids=[declared, cited])  # DEVIATION_CITES_A_MIX
    call(ids=[declared, other])  # DEVIATION_CITES_SEVERAL_DEVIATIONS
    call(ids=[withdrawal])  # DEVIATION_CITES_A_WITHDRAWAL
    call(ids=[assessment])  # CITED_KIND_NOT_CITABLE
    call(ids=[withdrawn])  # DEVIATION_ALREADY_WITHDRAWN
    [file] = [p for p in sorted((study / "declared_deviations").glob("*.json")) if declared in p.name]
    record = json.loads(file.read_text(encoding="utf-8"))
    del record["text"]
    file.write_text(json.dumps(record), encoding="utf-8")
    call(request_id="dv-held", read_sequence=0)  # CONTRACT_VIOLATION when the record is read for a replay; `status` would refuse it too
    return found


def test_the_deviation_refusal_table_of_chapter_17_equals_the_code_exit_stage_and_details_of_each_refusal_and_the_codes_the_command_raises(page, tmp_path):
    found = deviation_refusals(tmp_path)
    section = re.search(r'<section id="decisions".*?</section>', page, re.S)[0]
    rows = attrs_of(section, "deviation-codes", "data-code")
    assert set(rows) == set(found)
    for code, row in rows.items():
        exit_code, stage, details = found[code]
        assert (int(row["data-exit"]), row["data-stage"], words(row["data-details"])) == (exit_code, stage, details), code
    (tmp_path / "module").mkdir()
    shutil.copy(ROOT / "src" / "hypotrail" / "core" / "deviations.py", tmp_path / "module")  # the codes the command's own module raises
    raised = raised_codes(tmp_path / "module")
    assert raised and raised <= set(rows), raised - set(rows)


def test_the_declared_deviation_keys_table_of_chapter_17_equals_the_keys_status_reports_for_a_declared_deviation(page, tmp_path):
    from _study_helpers import run_json

    from hypotrail.core import contracts

    study, _, _, _ = _deviation_study(tmp_path)
    [row] = run_json("status", "--study", study)[1]["declared_deviations"]
    section = re.search(r'<section id="decisions".*?</section>', page, re.S)[0]
    keys = set(attrs_of(section, "deviation-row-keys", "data-field"))
    assert keys == set(row) == set(contracts.schema()["$defs"]["DeclaredDeviationRecord"]["properties"]) | {"withdrawn", "withdrawn_by"}


def test_the_readme_sentence_that_lists_the_commands_names_every_leaf_command_of_the_parser_but_spike_live():
    """`spike` is the parser of the "feasibility spike entry points" (`cli.py`), not a product command, so the sentence does not name `spike live`."""
    line = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[6]
    sentence = next(part for part in re.split(r"(?<=\.)\s+", line) if part.startswith("`init` creates a Study"))
    named = set(re.findall(r"`([^`]+)`", sentence))
    assert named == set(parser_commands()) - {"spike live"}, (sorted(named - set(parser_commands())), sorted(set(parser_commands()) - named))


def test_the_sentences_of_chapters_04_and_17_that_state_the_one_request_id_namespace_name_attempts_decisions_and_declared_deviations():
    for name in ("04-study-and-attempts.html", "17-decisions.html"):
        sentences = [s for s in re.split(r"(?<=\.)\s+", plain_text(chapter_text(name))) if "one request_id namespace" in s]
        assert len(sentences) == 1, (name, sentences)
        assert all(kind in sentences[0] for kind in ("Attempts", "Decisions", "Declared deviations")), (name, sentences[0])


def chapter_17_limit(limit) -> str:
    return limit_cards(chapter_text("17-decisions.html")).get(limit, "")


def test_chapter_17_states_that_a_corrected_references_set_has_a_new_artifact_id_and_is_not_covered():
    card = chapter_17_limit("corrected-references-not-covered")
    assert "artifact_id" in card and "corrected" in card, card


def test_chapter_17_states_that_a_comparison_is_not_updated_and_that_a_new_compare_is_the_remedy_which_for_public_check_appends_an_exposure_entry():
    card = chapter_17_limit("comparison-not-updated")
    assert all(part in card for part in ("not updated", "compare", "public_check", "Exposure")), card


def test_chapter_17_states_the_redo_path_and_the_departure_from_inspects_uninvalidate_samples():
    redo, departure = chapter_17_limit("redo-is-a-new-declaration"), chapter_17_limit("departure-from-inspect")
    assert "new declaration" in redo and "new ID" in redo, redo
    assert "uninvalidate_samples" in departure, departure


def test_a_chapter_states_that_a_decision_citing_a_withdrawn_declared_deviation_still_applies():
    chapters = [path.read_text(encoding="utf-8") for path in sorted((HANDBOOK / "chapters").glob("*.html"))]
    found = [card for chapter in chapters if '<p class="sub2">Limits</p>' in chapter for limit, card in limit_cards(chapter).items() if limit == "withdrawal-keeps-decisions-applying"]
    assert len(found) == 1 and "withdrawn" in found[0] and "applies" in found[0], found


def test_chapter_11_limit_that_a_compatible_comparison_can_hold_a_warning_names_the_declared_deviation_code_beside_the_order_code():
    invariant = limit_cards((HANDBOOK / "chapters" / "11-agent-comparison.html").read_text(encoding="utf-8")).get("compatible-with-warning", "")
    assert "compatible" in invariant and "COMPARISON_ORDER_NOT_ALTERNATED" in invariant and "COMPARISON_DEVIATION_DECLARED" in invariant, invariant


# --- #162: `evidence_change` in `status --json` (chapter 17) ---------------------------------------------------------------------------------

# "one with non-empty `rescoring.changed_items` gives "result changed";", "one with a non-null `rescoring` and none with changed Items gives "evidence
# rescored";", "all with `rescoring: null` gives "repeated, nothing changed"." (D-077 on chadlis/hypotrail#75, Q3)
EVIDENCE_PHRASES = {"result_changed": "result changed", "evidence_rescored": "evidence rescored", "repeated": "repeated, nothing changed"}


def _evidence_history(tmp_path):
    """The Decision rows of a Bike Study whose three Decisions read the three states: a repeat, a rescore that changed no Item, a changed Item."""
    from _assess_helpers import observation_set_id
    from _review_helpers import TRACKS, decide, status
    from _study_helpers import run_ml

    track = TRACKS["bike"]
    study, control, candidate, _ = track.compared(tmp_path / "base")
    code, payload, err = run_ml(study, "seasonal_7", "dev", "a-third-attempt")
    assert code == 0, (payload, err)
    third = track.assess_again(study, {"observation_set_id": observation_set_id(study, payload["attempt"])})
    decisions = [decide(study, [assessment["assessment_id"]], request_id=f"d-{n}")["decision_id"] for n, assessment in enumerate((control, candidate, third))]
    track.assess_again(study, control)  # a repeat
    track.revise_no_assessed_item(study, tmp_path)
    track.assess_again(study, candidate)  # rescored, no Item changed
    track.revise_an_assessed_item(study, tmp_path)
    track.assess_again(study, third)  # an Item changed
    rows = {row["decision_id"]: row for row in status(study)["decisions"]}
    return [rows[decision_id] for decision_id in decisions]


def test_the_evidence_states_table_lists_the_three_states_status_gives_each_with_its_phrase(page, tmp_path):
    rows = attrs_of(page, "evidence-states", "data-code")
    given = [row["evidence_change"]["state"] for row in _evidence_history(tmp_path)]
    assert given == ["repeated", "evidence_rescored", "result_changed"]
    assert set(rows) == set(given) == set(EVIDENCE_PHRASES)
    for code, row in rows.items():
        assert row["data-phrase"] == EVIDENCE_PHRASES[code], code


def evidence_key_rows(page) -> dict:
    """{the object a row is about: its keys} of the table `evidence-keys`, each row carrying `data-field` and `data-of`."""
    table = re.search(r'<table[^>]*id="evidence-keys".*?</table>', page, re.S)[0]
    found: dict = {}
    for attributes in re.findall(r"<tr ([^>]*data-field[^>]*)>", table):
        values = dict(re.findall(r'data-([a-z-]+)="([^"]*)"', attributes))
        found.setdefault(values["of"], set()).add(values["field"])
    return found


def test_the_evidence_keys_table_lists_the_keys_of_evidence_change_of_a_line_and_of_a_metrics_entry(page, tmp_path):
    change = next(row["evidence_change"] for row in _evidence_history(tmp_path) if row["evidence_change"]["state"] == "result_changed")
    assert evidence_key_rows(page) == {"evidence_change": set(change), "line": set(change["lines"][0]), "metrics": set(change["lines"][0]["metrics"][0])}
    assert (len(change), len(change["lines"][0]), len(change["lines"][0]["metrics"][0])) == (2, 7, 3)


def test_chapter_17_has_a_limit_card_that_a_later_assessment_without_rescoring_counts_as_a_repeat():
    card = chapter_17_limit("no-rescoring-is-a-repeat")
    assert "rescoring" in card and "repeat" in card, card


def test_chapter_17_has_a_limit_card_that_names_the_two_causes_of_a_null_latest():
    card = chapter_17_limit("latest-null-two-causes")
    assert "latest" in card and "holds no Metric" in card and "value is null" in card, card


@pytest.mark.parametrize("word", ["label", "evidence", "line", "anchor", "reached"])
def test_chapter_17_defines_in_bold_each_word_of_the_evidence_change_it_uses(word):
    chapter = chapter_text("17-decisions.html")
    if not re.search(rf"\b{word}\b", plain_text(chapter), re.I):
        return
    sentences = [s for s in re.split(r"(?<=[.])\s+", chapter) if re.search(rf"<b>{word}</b>", s, re.I)]
    assert len(sentences) == 1, (word, sentences)


# --- #163: the pending decisions in `status --json` (chapter 17) -------------------------------------------------------------------------------


def test_the_pending_keys_table_lists_the_keys_of_an_entry_of_its_question_and_of_an_option(page, tmp_path):
    from _review_helpers import TRACKS, status

    study, _, _, _ = TRACKS["bike"].compared(tmp_path / "base")
    [entry] = status(study)["pending_decisions"]
    table = re.search(r'<table[^>]*id="pending-keys".*?</table>', page, re.S)[0]
    found: dict = {}
    for attributes in re.findall(r"<tr ([^>]*data-field[^>]*)>", table):
        values = dict(re.findall(r'data-([a-z-]+)="([^"]*)"', attributes))
        found.setdefault(values["of"], set()).add(values["field"])
    assert found == {"entry": set(entry), "question": set(entry["question"]), "option": set(entry["options"][0])}
    assert (len(entry), len(entry["question"]), len(entry["options"][0])) == (5, 2, 3)


def test_the_pending_question_table_gives_the_identifier_and_the_text_of_the_question_and_of_each_option_the_core_holds(page):
    from hypotrail.core import decisions

    rows = attrs_of(page, "pending-question", "data-code")
    expected = {decisions.PENDING_QUESTION["id"]: decisions.PENDING_QUESTION["text"], **{option["id"]: option["text"] for option in decisions.PENDING_OPTIONS}}
    assert {code: html.unescape(row["data-text"]) for code, row in rows.items()} == expected
    assert len(rows) == 4


def test_chapter_17_gives_the_three_conditions_of_a_pending_decision_in_its_prose():
    prose = plain_text(prose_of(chapter_text("17-decisions.html")))
    [sentence] = [s for s in re.split(r"(?<=[.])\s+", prose) if "is pending when" in s]
    for part in ("current revision", "no later Assessment", "no Decision that applies cites it"):
        assert part in sentence, (part, sentence)


def test_chapter_17_says_decide_records_the_question_and_option_as_given_and_checks_neither_and_drops_the_declared_question_sentence():
    card = plain_text(re.search(r'<div class="card"[^>]*><h3>Free text, no declared question</h3>.*?</div>', chapter_text("17-decisions.html"), re.S)[0])
    assert "as given" in card and "checks neither" in card, card
    assert "declares no question with options yet" not in plain_text(chapter_text("17-decisions.html"))


# --- the VS Code client (chapter 18): its tables against `clients/vscode/contract.json`, the manifest and the workflow -------------

CLIENT = ROOT / "clients" / "vscode"
CLIENT_CHAPTER = "18-vscode-client.html"
# The data attributes that hold a row's value; the others name the row.
CLIENT_VALUE_ATTRIBUTES = ("data-value", "data-command", "data-version", "data-outcome", "data-cause", "data-option", "data-title")


def client_rows(page, table_id):
    """The data attributes of each row of one table of the page, in order."""
    return [row["attrs"] for row in parse(page).tables.get(table_id, []) if any(k.startswith("data-") for k in row["attrs"])]


def client_items(page, table_id):
    """{data-item: data-value} of one table whose rows name their item; an item given twice keeps a list of its values."""
    items = {}
    for attrs in client_rows(page, table_id):
        items.setdefault(attrs["data-item"], []).append(attrs["data-value"])
    return {item: values[0] if len(values) == 1 else values for item, values in items.items()}


def client_contract():
    return json.loads((CLIENT / "contract.json").read_text(encoding="utf-8"))


def client_job_lines():
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    return workflow.split("\n  client:\n", 1)[1].splitlines() if "\n  client:\n" in workflow else []


def test_the_client_chapter_tables_equal_contract_json_the_manifest_and_the_workflow_both_ways(page):
    contract = client_contract()
    manifest = json.loads((CLIENT / "package.json").read_text(encoding="utf-8"))
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert client_items(page, "client-read") == {
        "program": contract["program"],
        "first-arguments": " ".join(contract["first_arguments"]),
        "read": " ".join(contract["read_arguments"]),
        "read-limit-ms": str(contract["read_timeout_ms"]),
        "output-limit-bytes": str(contract["max_buffer_bytes"]),
    }
    assert [row["data-outcome"] for row in client_rows(page, "client-outcomes")] == contract["outcomes"]
    assert [row["data-cause"] for row in client_rows(page, "client-causes")] == contract["no_answer_causes"]
    assert client_items(page, "client-walk") == {
        "depth": str(contract["walk_depth"]),
        "max-folders": str(contract["walk_max_folders"]),
        "skip": contract["walk_skipped"],
        "no-study": contract["no_study_message"],
    }
    versions = {row["data-tool"]: row["data-version"] for row in client_rows(page, "client-versions")}
    assert versions == {"node": re.search(r'node-version: "([^"]+)"', "\n".join(client_job_lines()))[1], "vscode": manifest["engines"]["vscode"]}
    tooling = client_items(page, "client-tooling")
    assert set(tooling) == {"directory", "test", "compile"}
    assert tooling["directory"] == "clients/vscode/" and (ROOT / tooling["directory"] / "package.json").is_file()
    assert tooling["test"] == "npm test" and "test" in manifest["scripts"]
    assert tooling["compile"] == "npm run compile" and "compile" in manifest["scripts"]
    steps = {row["data-step"]: row["data-command"] for row in client_rows(page, "client-install")}
    assert steps == {"1": "uv sync --locked --all-extras", "2": f"npm ci && {tooling['compile']}", "3": "Developer: Install Extension from Location..."}
    assert f"      - run: {steps['1']}\n" in workflow and "      - run: npm ci" in client_job_lines()


def test_the_client_chapter_prose_states_no_value_of_its_tables(page):
    chapter = chapter_text(CLIENT_CHAPTER)
    values = {attrs[name] for table in re.findall(r'<table[^>]*id="(client-[a-z-]+)"', chapter) for attrs in client_rows(page, table) for name in CLIENT_VALUE_ATTRIBUTES if name in attrs}
    assert {"uv", "30000", "no_json", "^1.95.0", "npm test", "decide", "--source", "read_sequence", "outcome unknown", "hypotrail.openPanel", "enableForms=false", "base-uri 'none'", "This Hypotrail link is not valid."} <= values  # the collection reads the tables
    prose = html.unescape(plain_text(prose_of(chapter)))
    assert sorted(v for v in values if re.search(rf"(?<![\w-]){re.escape(v)}(?![\w-])", prose)) == []


def test_the_client_chapter_write_tables_equal_contract_json_and_the_decide_options_the_parser_defines_both_ways(page):
    from hypotrail.cli import build_parser

    contract = client_contract()
    commands = {row["data-command"]: row["data-kind"] for row in client_rows(page, "client-commands")}
    assert commands == {**{c: "read" for c in contract["reads"]}, **{c: "write" for c in contract["writes"]}}
    rows = client_rows(page, "client-decide-options")
    assert [row["data-option"] for row in rows] == contract["decide_options"]
    assert [row["data-option"] for row in rows if row["data-passed"] == "optional"] == contract["decide_optional_options"]
    assert {row["data-passed"] for row in rows} == {"always", "optional"}
    parser = build_parser()
    decide = next(a for a in parser._actions if getattr(a, "choices", None) and "decide" in a.choices).choices["decide"]
    options = {flag: a.required for a in decide._actions for flag in a.option_strings if flag not in ("-h", "--help")}
    assert {row["data-option"] for row in rows} == set(options)
    assert {row["data-option"] for row in rows if row["data-passed"] == "always"} == {flag for flag, required in options.items() if required} | {"--json"}
    assert client_items(page, "client-write") == {"write-limit-ms": str(contract["write_timeout_ms"]), "no-answer-words": contract["write_no_answer_words"]}
    assert [row["data-value"] for row in client_rows(page, "client-missing")] == contract["client_refusal_fields"]


def test_the_client_chapter_panel_and_link_tables_equal_the_manifest_and_contract_json_both_ways(page):
    contract = client_contract()
    manifest = json.loads((CLIENT / "package.json").read_text(encoding="utf-8"))
    commands = [{"command": row["data-command"], "title": row["data-title"]} for row in client_rows(page, "client-command")]
    assert commands == manifest["contributes"]["commands"]
    assert [row["data-option"] for row in client_rows(page, "client-panel-options")] == contract["panel_options"]
    assert [row["data-value"] for row in client_rows(page, "client-csp")] == contract["csp_directives"]
    assert client_items(page, "client-links") == {
        "form": contract["link_forms"],
        "decision-id": contract["link_decision_id"],
        "max-path": str(contract["link_max_path"]),
        "refusal": contract["link_refusal"],
    }


def test_the_client_budget_table_equals_the_constants_of_the_counting_test_both_ways(page):
    import test_client_line_budget as counting

    items = {}
    for attrs in client_rows(page, "client-budget"):
        items.setdefault(attrs["data-item"], []).append(attrs["data-value"])
    assert items == {
        "budget": [str(counting.BUDGET)],
        "counted": list(counting.COUNTED_KINDS),
        "tests": [counting.TEST_FOLDER],
        "refused": list(counting.REFUSED_KINDS),
        "generated": [counting.GENERATED_FOLDER],
    }


def test_the_line_budget_section_prose_states_neither_3000_nor_3_000():
    chapter = chapter_text(CLIENT_CHAPTER)
    assert '<p class="sub2">The line budget</p>' in chapter
    section = chapter.split('<p class="sub2">The line budget</p>', 1)[1].split('<p class="sub2">', 1)[0]
    prose = plain_text(prose_of(section))
    assert "client-budget" in section and prose
    assert "3000" not in prose and "3,000" not in prose


def test_the_client_chapter_has_one_section_on_the_panels_content_found_by_its_id(page):
    chapter = chapter_text(CLIENT_CHAPTER)
    assert chapter.count('id="panel-content"') == 1
    assert re.search(r'<p class="sub2" id="panel-content">[^<]+</p>', chapter)
    assert page.count('id="panel-content"') == 1


# --- the panel's recorded Decisions (chapter 18): the phrases of the states and the word of a null value ---------------------------

# The tables of chapter 18 on what the panel shows of a recorded Decision, each with the entries of `clients/vscode/contract.json` its rows
# carry in `data-entry`.
PANEL_DECISION_TABLES = {"panel-evidence-phrases": lambda contract: contract["evidence_phrases"], "panel-no-value": lambda contract: [contract["no_value"]]}


def test_the_evidence_phrases_of_contract_json_equal_the_table_of_states_of_chapter_17_both_ways(page):
    rows = client_rows(page, "evidence-states")
    assert len(rows) == 3
    assert [f"{row['data-code']}={row['data-phrase']}" for row in rows] == client_contract()["evidence_phrases"]


def test_the_panel_decision_tables_of_chapter_18_equal_contract_json_both_ways(page):
    contract = client_contract()
    for table, entries in PANEL_DECISION_TABLES.items():
        assert [row["data-entry"] for row in client_rows(page, table)] == entries(contract), table


def test_no_row_of_the_panel_decision_tables_carries_an_attribute_of_the_l24_value_attributes(page):
    for table in PANEL_DECISION_TABLES:
        rows = client_rows(page, table)
        assert rows, table
        for row in rows:
            assert sorted(set(row) & set(CLIENT_VALUE_ATTRIBUTES)) == [], (table, row)


def test_the_prose_of_chapter_18_names_each_panel_decision_table_by_one_link_to_its_id(page):
    prose = prose_of(chapter_text(CLIENT_CHAPTER))
    for table in PANEL_DECISION_TABLES:
        assert prose.count(f'href="#{table}"') == 1, table
        assert page.count(f'id="{table}"') == 1, table


# The table of chapter 18 that holds the word of a withheld delta, with the entry of contract.json it equals.
PANEL_WITHHELD_TABLE = ("panel-withheld", "withheld")


def test_the_panel_withheld_table_of_chapter_18_equals_contract_json_both_ways(page):
    table, key = PANEL_WITHHELD_TABLE
    assert [row["data-entry"] for row in client_rows(page, table)] == [client_contract()[key]]


def test_no_row_of_the_panel_withheld_table_carries_an_attribute_of_the_l24_value_attributes(page):
    rows = client_rows(page, PANEL_WITHHELD_TABLE[0])
    assert rows
    for row in rows:
        assert sorted(set(row) & set(CLIENT_VALUE_ATTRIBUTES)) == [], row


def test_the_prose_of_chapter_18_names_the_panel_withheld_table_by_one_link_to_its_id(page):
    table = PANEL_WITHHELD_TABLE[0]
    assert prose_of(chapter_text(CLIENT_CHAPTER)).count(f'href="#{table}"') == 1
    assert page.count(f'id="{table}"') == 1


# --- recording a Decision from the panel (chapter 18): the names of the messages and the author's value -----------------------------

# The tables of chapter 18 on how the panel records a Decision, each with the entries of `clients/vscode/contract.json` its rows carry in
# `data-entry`.
PANEL_WRITE_TABLES = {"panel-messages": lambda contract: contract["messages"], "panel-author": lambda contract: [contract["decide_author"]]}


def test_the_panel_write_tables_of_chapter_18_equal_contract_json_both_ways(page):
    contract = client_contract()
    for table, entries in PANEL_WRITE_TABLES.items():
        assert [row["data-entry"] for row in client_rows(page, table)] == entries(contract), table


def test_no_row_of_the_panel_write_tables_carries_an_attribute_of_the_l24_value_attributes(page):
    for table in PANEL_WRITE_TABLES:
        rows = client_rows(page, table)
        assert rows, table
        for row in rows:
            assert sorted(set(row) & set(CLIENT_VALUE_ATTRIBUTES)) == [], (table, row)


def test_the_prose_of_chapter_18_names_each_panel_write_table_by_one_link_to_its_id(page):
    prose = prose_of(chapter_text(CLIENT_CHAPTER))
    for table in PANEL_WRITE_TABLES:
        assert prose.count(f'href="#{table}"') == 1, table
        assert page.count(f'id="{table}"') == 1, table


# --- the links of the panel (chapter 18): the part each kind of number links to, the statuses shown and the key paths read ----------

# The tables of chapter 18 on the panel's links and on what the panel reads, each with the entries of `clients/vscode/contract.json` its
# rows carry in `data-entry`.
PANEL_LINK_TABLES = {
    "panel-number-links": lambda contract: contract["number_links"],
    "panel-statuses": lambda contract: contract["statuses"],
    "panel-key-paths": lambda contract: contract["key_paths"],
}


def test_the_panel_link_tables_of_chapter_18_equal_contract_json_both_ways(page):
    contract = client_contract()
    for table, entries in PANEL_LINK_TABLES.items():
        assert [row["data-entry"] for row in client_rows(page, table)] == entries(contract), table


def test_no_row_of_the_panel_link_tables_carries_an_attribute_of_the_l24_value_attributes(page):
    for table in PANEL_LINK_TABLES:
        rows = client_rows(page, table)
        assert rows, table
        for row in rows:
            assert sorted(set(row) & set(CLIENT_VALUE_ATTRIBUTES)) == [], (table, row)


def test_the_prose_of_chapter_18_names_each_panel_link_table_by_one_link_to_its_id(page):
    prose = prose_of(chapter_text(CLIENT_CHAPTER))
    for table in PANEL_LINK_TABLES:
        assert prose.count(f'href="#{table}"') == 1, table
        assert page.count(f'id="{table}"') == 1, table


# --- the panel's style, the guard of its layout and its own words (chapter 18) -----------------------------------------------------

# The tables of chapter 18 on the panel's colours, the bounds of the guard of its layout and its own words, each with the entries of
# `clients/vscode/contract.json` its rows carry in `data-entry`.
PANEL_STYLE_TABLES = {
    "panel-guard-bounds": lambda contract: contract["guard_bounds"],
    "panel-colour-forms": lambda contract: contract["colour_forms"],
    "panel-labels": lambda contract: contract["labels"],
}


def test_the_panel_style_bounds_and_label_tables_of_chapter_18_equal_contract_json_both_ways(page):
    contract = client_contract()
    for table, entries in PANEL_STYLE_TABLES.items():
        assert [row["data-entry"] for row in client_rows(page, table)] == entries(contract), table


def test_no_row_of_the_panel_style_bounds_and_label_tables_carries_an_attribute_of_the_l24_value_attributes(page):
    for table in PANEL_STYLE_TABLES:
        rows = client_rows(page, table)
        assert rows, table
        for row in rows:
            assert sorted(set(row) & set(CLIENT_VALUE_ATTRIBUTES)) == [], (table, row)


def test_the_prose_of_chapter_18_names_each_panel_style_bounds_and_label_table_by_one_link_to_its_id(page):
    prose = prose_of(chapter_text(CLIENT_CHAPTER))
    for table in PANEL_STYLE_TABLES:
        assert prose.count(f'href="#{table}"') == 1, table
        assert page.count(f'id="{table}"') == 1, table
