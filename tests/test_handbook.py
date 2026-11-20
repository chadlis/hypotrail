"""Ticket #21: the handbook builds from chapter sources and its first chapter is true."""

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tomllib
import unittest.mock
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
    paragraph = next(p for p in re.findall(r"<p>.*?</p>", page, re.S) if "Two further Attempts were kept on 2026-11-07" in p)
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
        "non_json_wrapper": ['{"answer": OBJ, "note": NaN}', '{"answer": OBJ', "x {oops OBJ"],
    }

    def holding(shape, obj):
        return shape.replace("OBJ", obj)

    # (raw answer, the object it holds): the valid object, and each off-schema object for the *_off_schema rows
    samples = {name: [(holding(sh, text), text) for sh in group] for name, group in shapes.items()}
    samples |= {f"{name}_off_schema": [(holding(sh, o), o) for sh in group for o in off_objects] for name, group in shapes.items()}
    samples["nothing_read"] = [
        (raw, None)
        for raw in ("The answer is 1297.", "1297", "[1297]", text + text, "```json\n" + text + "\n```\n```json\n" + text + "\n```")
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


def test_the_commands_table_equals_the_flags_the_parser_defines(page):
    from hypotrail.cli import build_parser

    parser = build_parser()

    def subparser(parent, name):
        action = next(a for a in parent._actions if getattr(a, "choices", None) and name in a.choices)
        return action.choices[name]

    parsers = {
        "init": subparser(parser, "init"),
        "run ml": subparser(subparser(parser, "run"), "ml"),
        "import ml": subparser(subparser(parser, "import"), "ml"),
        "import agent": subparser(subparser(parser, "import"), "agent"),
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
    after_init = {p.relative_to(study).as_posix() for p in study.rglob("*") if p.is_file()}
    _, seasonal, _ = run_ml(study, "seasonal_7", "dev", "a")
    _, ridge, _ = run_ml(study, "ridge_v1", "dev", "b")
    ids = {seasonal["attempt"]["attempt_id"], ridge["attempt"]["attempt_id"]}
    everything = {p.relative_to(study).as_posix() for p in study.rglob("*") if p.is_file()}
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
    assert set(listing) == {"ok", "study", "writer_alive", "attempts"}


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
    public_study, public_attempts = fresh_study(tmp_path / "p", "seasonal_7", partition="public_check")
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
    record(assess(public_study, observation_set_id(public_study, public_attempts["seasonal_7"]), "regression_mae_v1", references_id(public_study)))
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

    base = {"row_id": "day_key", "y_pred": "forecast_rentals", "dataset_sha256": digest}
    record(import_ml(study, source, with_mapping([1], "m1.json"), population, "r"))
    record(import_ml(study, source, with_mapping({**base, "extra": "x"}, "m2.json"), population, "r"))
    record(import_ml(study, source, with_mapping({"row_id": "day_key", "y_pred": "forecast_rentals"}, "m3.json"), population, "r"))
    record(import_ml(study, source, with_mapping({**base, "y_pred": 1}, "m4.json"), population, "r"))
    record(import_ml(study, source, with_mapping({**base, "y_pred": "os.system"}, "m5.json"), population, "r"))
    record(import_ml(study, source, with_mapping({**base, "y_pred": "nope"}, "m6.json"), population, "r"))
    record(import_ml(study, source, with_mapping({**base, "dataset_sha256": "0" * 64}, "m7.json"), population, "r"))
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
    public = construct(study, attempts["ridge_v1"], lambda rows: rows, provenance={"partition": "public_check"})
    record(compare(study, control["assessment_id"], "nope"))
    record(against(forged(study, candidate, lambda r: r.update(observation_set_id="nope"))))
    record(against(forged(study, candidate, lambda r: r.update(observation_set_id=public))))
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
    written = {p.relative_to(study).as_posix() for p in study.rglob("*") if p.is_file()}
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
    assert set(rows) == set(record) - set(definition["required"])
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
    record(run_json(*args, "--references", references_id(study)))
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
