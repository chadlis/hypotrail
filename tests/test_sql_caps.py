"""Ticket #46: `query_readonly` bounds every query in time, instructions, rows and size,
flags what it cut, and leaves Inspect's event loop free."""

import json
import sqlite3
import time

import anyio
import pytest
from inspect_ai.model import ModelOutput

from _agent_helpers import CASES, DATABASE, MODEL, WORKLOAD, ScriptedModel

from hypotrail.agentic import cases as case_module
from hypotrail.agentic import limits as limits_module
from hypotrail.agentic import projection, runner, sql_tool
from hypotrail.agentic.sql_tool import QueryCaps

CONFIGURATION = "plain"
CROSS_JOIN = "SELECT count(*) FROM InvoiceLine, PlaylistTrack, Track"
CROSS_JOIN_LIKE = "SELECT count(*) FROM InvoiceLine, PlaylistTrack, Track WHERE (Track.Name || PlaylistTrack.PlaylistId || InvoiceLine.InvoiceLineId) LIKE '%zzz%'"
CROSS_JOIN_GLOB = "SELECT count(*) FROM InvoiceLine, PlaylistTrack, Track WHERE (Track.Name || PlaylistTrack.PlaylistId || InvoiceLine.InvoiceLineId) GLOB '*zzz*'"
OUT_OF_REACH_INSTRUCTIONS = 10**13
OUT_OF_REACH_SECONDS = 600.0


def test_the_default_caps_are_the_four_of_ag_04_and_the_declared_ceiling():
    assert QueryCaps().as_dict() == {
        "time_seconds": 1.0,
        "max_instructions": 100_000_000,
        "max_rows": 200,
        "max_bytes": 64 * 1024,
    }


# --- rows ---------------------------------------------------------------------------------


class CountingCursor(sqlite3.Cursor):
    fetched = 0

    def fetchone(self):
        row = super().fetchone()
        type(self).fetched += row is not None
        return row

    def fetchmany(self, size=None):
        rows = super().fetchmany(size) if size is not None else super().fetchmany()
        type(self).fetched += len(rows)
        return rows

    def fetchall(self):
        rows = super().fetchall()
        type(self).fetched += len(rows)
        return rows

    def __next__(self):
        row = super().__next__()
        type(self).fetched += 1
        return row


def test_more_than_200_rows_return_the_first_200_in_order_and_fetch_at_most_201():
    CountingCursor.fetched = 0
    result = sql_tool.run_query(
        DATABASE, "SELECT TrackId FROM Track ORDER BY TrackId", cursor_factory=CountingCursor
    )
    assert result["error"] is None
    assert result["truncated"] is True
    assert result["row_count"] == 200
    assert result["rows"] == [[i] for i in range(1, 201)]
    assert CountingCursor.fetched == 201


def test_exactly_200_rows_are_not_truncated():
    result = sql_tool.run_query(DATABASE, "SELECT TrackId FROM Track ORDER BY TrackId LIMIT 200")
    assert result["truncated"] is False
    assert result["row_count"] == 200


# --- size ---------------------------------------------------------------------------------


def test_a_result_over_64_kib_is_cut_to_at_most_64_kib_and_flagged():
    # 150 rows of about 1 KiB or more each: under 200 rows, over 64 KiB
    sql = "SELECT TrackId, " + " || ".join(["Name"] * 40) + " FROM Track LIMIT 150"
    full = sql_tool.run_query(DATABASE, sql, caps=QueryCaps(max_bytes=10**9))
    assert len(json.dumps(full["rows"])) > 64 * 1024  # the case is real
    result = sql_tool.run_query(DATABASE, sql)
    assert result["error"] is None
    assert result["truncated"] is True
    assert 0 < result["row_count"] < 150
    assert result["row_count"] == len(result["rows"])
    assert result["rows"] == full["rows"][: result["row_count"]]
    assert len(json.dumps({"columns": result["columns"], "rows": result["rows"]}).encode()) <= 64 * 1024


# --- time and instructions, witnessed apart (T1) ----------------------------------------------


def test_the_time_cap_alone_stops_a_costly_query_within_the_cap_plus_a_margin():
    caps = QueryCaps(time_seconds=0.3, max_instructions=OUT_OF_REACH_INSTRUCTIONS)
    started = time.monotonic()
    result = sql_tool.run_query(DATABASE, CROSS_JOIN, caps=caps)
    elapsed = time.monotonic() - started
    assert result["error"]["code"] == "TIME_LIMIT"
    assert result["rows"] == [] and result["row_count"] == 0
    assert elapsed < 0.3 + 1.5


def test_the_instruction_ceiling_alone_stops_a_costly_query():
    caps = QueryCaps(time_seconds=OUT_OF_REACH_SECONDS, max_instructions=5_000_000)
    started = time.monotonic()
    result = sql_tool.run_query(DATABASE, CROSS_JOIN, caps=caps)
    assert result["error"]["code"] == "INSTRUCTION_LIMIT"
    assert result["rows"] == [] and result["row_count"] == 0
    assert time.monotonic() - started < 10


def test_the_default_caps_stop_the_costly_query_with_a_code_naming_a_limit_in_bounded_time():
    started = time.monotonic()
    result = sql_tool.run_query(DATABASE, CROSS_JOIN)
    assert result["error"]["code"] in {"TIME_LIMIT", "INSTRUCTION_LIMIT"}
    assert result["rows"] == [] and result["row_count"] == 0
    assert time.monotonic() - started < 1.0 + 1.5


# --- the caps bound a LIKE or GLOB query (#51) ------------------------------------------------


@pytest.mark.parametrize("sql", [CROSS_JOIN_LIKE, CROSS_JOIN_GLOB], ids=["like", "glob"])
def test_a_pattern_query_over_the_instruction_ceiling_is_stopped_with_that_code(sql):
    caps = QueryCaps(time_seconds=OUT_OF_REACH_SECONDS, max_instructions=5_000_000)
    result = sql_tool.run_query(DATABASE, sql, caps=caps)
    assert result["error"]["code"] == "INSTRUCTION_LIMIT"
    assert result["rows"] == [] and result["row_count"] == 0


@pytest.mark.parametrize("sql", [CROSS_JOIN_LIKE, CROSS_JOIN_GLOB], ids=["like", "glob"])
def test_a_pattern_query_over_the_time_cap_is_stopped_with_that_code(sql):
    caps = QueryCaps(time_seconds=0.3, max_instructions=OUT_OF_REACH_INSTRUCTIONS)
    started = time.monotonic()
    result = sql_tool.run_query(DATABASE, sql, caps=caps)
    assert result["error"]["code"] == "TIME_LIMIT"
    assert result["rows"] == [] and result["row_count"] == 0
    assert time.monotonic() - started < 0.3 + 1.5


def test_a_like_query_matching_more_than_200_rows_returns_200_and_is_flagged():
    result = sql_tool.run_query(DATABASE, "SELECT TrackId FROM Track WHERE Name LIKE '%a%' ORDER BY TrackId")
    assert result["error"] is None
    assert result["truncated"] is True
    assert result["row_count"] == 200


def test_a_like_result_over_64_kib_is_cut_and_flagged():
    sql = "SELECT TrackId, " + " || ".join(["Name"] * 40) + " FROM Track WHERE Name LIKE '%a%' LIMIT 150"
    full = sql_tool.run_query(DATABASE, sql, caps=QueryCaps(max_bytes=10**9))
    assert len(json.dumps(full["rows"])) > 64 * 1024  # the case is real
    result = sql_tool.run_query(DATABASE, sql)
    assert result["error"] is None
    assert result["truncated"] is True
    assert 0 < result["row_count"] < 150
    assert len(json.dumps({"columns": result["columns"], "rows": result["rows"]}).encode()) <= 64 * 1024


# --- the event loop stays free -----------------------------------------------------------------


def test_a_coroutine_beside_a_slow_query_makes_progress_before_the_query_ends():
    caps = QueryCaps(time_seconds=1.5, max_instructions=OUT_OF_REACH_INSTRUCTIONS)
    ticks_when_query_ended = []

    async def main():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await anyio.sleep(0.05)
                ticks += 1

        async with anyio.create_task_group() as group:
            group.start_soon(ticker)
            tool = sql_tool.query_readonly(DATABASE, caps)
            result = json.loads(await tool(sql=CROSS_JOIN))
            ticks_when_query_ended.append(ticks)
            group.cancel_scope.cancel()
        return result

    result = anyio.run(main)
    assert result["error"]["code"] == "TIME_LIMIT"
    assert ticks_when_query_ended[0] >= 10


def test_the_episode_time_limit_stops_an_episode_whose_query_outlasts_it(tmp_path):
    caps = QueryCaps(time_seconds=OUT_OF_REACH_SECONDS, max_instructions=OUT_OF_REACH_INSTRUCTIONS)

    def costly(input, tools, tool_choice, config):
        return ModelOutput.for_tool_call(MODEL, "query_readonly", {"sql": CROSS_JOIN})

    cases = case_module.load_cases(CASES, ["D03"])
    started = time.monotonic()
    location = runner.run_episodes(
        cases,
        workload=WORKLOAD,
        configuration=CONFIGURATION,
        model=runner.mock_model(costly),
        repeats=1,
        log_dir=tmp_path / "logs",
        limits=limits_module.EpisodeLimits(time_seconds=1),
        query_caps=caps,
    )
    [episode] = projection.project_log(location, expected=[("D03", 0)])
    assert time.monotonic() - started < 8
    assert episode["stopped_by_limit"] == {"type": "time", "limit": 1.0}
    assert episode["final_answer"] is None


# --- effective limits ------------------------------------------------------------------------------


def test_the_attempt_records_the_four_caps_next_to_the_episode_limits(tmp_path):
    cases = case_module.load_cases(CASES, ["D03"])
    caps = QueryCaps(time_seconds=2.0, max_instructions=7_000_000, max_rows=150, max_bytes=2048)
    location = runner.run_episodes(
        cases,
        workload=WORKLOAD,
        configuration=CONFIGURATION,
        model=runner.mock_model(ScriptedModel(cases)),
        repeats=1,
        log_dir=tmp_path / "logs",
        query_caps=caps,
    )
    effective = limits_module.read_back(location)
    assert effective["query_caps"] == caps.as_dict()
    assert effective["model_turns"] == 6
