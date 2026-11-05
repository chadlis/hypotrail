"""Ticket #16: an offline Inspect run with a scripted model, projected per Case x Repeat."""

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from _agent_helpers import CASES, DATABASE, MODEL, REFERENCES, WORKLOAD, ScriptedModel, oracle_sql, read_jsonl

from inspect_ai.log import read_eval_log

from hypotrail.agentic import cases as case_module
from hypotrail.agentic import projection, runner, sql_tool

ROOT = Path(__file__).resolve().parent.parent
SPIKE_CASE_IDS = ["D03", "D05"]
POISON = {"case_id": "POISON-ID", "split": "POISON-SPLIT", "family": "POISON-FAMILY"}


def spike_cases():
    return case_module.load_cases(CASES, SPIKE_CASE_IDS)


@pytest.fixture
def scripted_run(tmp_path):
    """Run 2 Cases x 2 Repeats offline; return (script, log location)."""
    script = ScriptedModel(spike_cases())
    location = runner.run_episodes(
        spike_cases(),
        workload=WORKLOAD,
        configuration="plain",
        model=runner.mock_model(script),
        repeats=2,
        log_dir=tmp_path / "logs",
    )
    return script, location


def expected_episodes():
    return [(c, r) for c in SPIKE_CASE_IDS for r in (0, 1)]


# --- check 1: every Case x Repeat is recovered through the public API ----------


def test_four_episodes_are_projected_once_each_with_the_expected_sequence(scripted_run):
    _, location = scripted_run
    episodes = projection.project_log(location, expected=expected_episodes())

    assert [(e["case_id"], e["repeat"]) for e in episodes] == expected_episodes()
    assert len({(e["case_id"], e["repeat"]) for e in episodes}) == 4
    for episode in episodes:
        assert episode["status"] == "produced"
        assert [step["kind"] for step in episode["steps"]] == [
            "model_turn",
            "tool_call",
            "tool_result",
            "model_turn",
            "final_answer",
        ]


def test_the_tool_result_in_the_log_equals_the_same_sql_run_directly(scripted_run):
    _, location = scripted_run
    for episode in projection.project_log(location, expected=expected_episodes()):
        steps = {s["kind"]: s for s in episode["steps"] if s["kind"] != "model_turn"}
        logged = steps["tool_result"]["result"]
        direct = sql_tool.run_query(DATABASE, steps["tool_call"]["arguments"]["sql"])
        for key in ("columns", "rows", "row_count", "truncated", "error"):
            assert logged[key] == direct[key]
        assert logged["tool_call_id"] != direct["tool_call_id"]  # a fresh application ID each time
        assert logged["row_count"] == len(logged["rows"]) > 0


def test_the_tool_call_id_comes_from_the_application_and_maps_to_the_native_event(scripted_run):
    _, location = scripted_run
    for episode in projection.project_log(location, expected=expected_episodes()):
        call = next(s for s in episode["steps"] if s["kind"] == "tool_call")
        result = next(s for s in episode["steps"] if s["kind"] == "tool_result")
        answer = json.loads(episode["final_answer"])
        assert result["native_tool_call_id"] == call["native_tool_call_id"]
        assert result["result"]["tool_call_id"] == result["app_tool_call_id"]
        assert result["app_tool_call_id"] != result["native_tool_call_id"]
        assert answer["evidence"] == [result["app_tool_call_id"]]


def test_an_episode_that_errors_is_still_one_record_marked_failed(tmp_path):
    script = ScriptedModel(spike_cases(), error_on=("D05", 2))
    location = runner.run_episodes(
        spike_cases(),
        workload=WORKLOAD,
        configuration="plain",
        model=runner.mock_model(script),
        repeats=2,
        log_dir=tmp_path / "logs",
    )
    episodes = projection.project_log(location, expected=expected_episodes())

    assert [(e["case_id"], e["repeat"]) for e in episodes] == expected_episodes()
    status = {(e["case_id"], e["repeat"]): e["status"] for e in episodes}
    assert status[("D05", 1)] == "failed"
    assert [s for k, s in status.items() if k != ("D05", 1)] == ["produced"] * 3
    failed = next(e for e in episodes if e["status"] == "failed")
    assert failed["final_answer"] is None


def test_an_expected_episode_absent_from_the_log_is_marked_missing(scripted_run):
    _, location = scripted_run
    episodes = projection.project_log(location, expected=expected_episodes() + [("D03", 2)])
    assert len(episodes) == 5
    assert episodes[-1]["status"] == "missing"
    assert (episodes[-1]["case_id"], episodes[-1]["repeat"]) == ("D03", 2)


# --- the scripted log cannot be taken for a live one ------------------------------


def test_the_log_records_inspects_mock_model(scripted_run):
    _, location = scripted_run
    assert read_eval_log(location).eval.model == MODEL
    for episode in projection.project_log(location, expected=expected_episodes()):
        assert episode["model"] == MODEL
        assert episode["provider"] == "mockllm"


# --- the read-only tool -----------------------------------------------------------


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO Genre (GenreId, Name) VALUES (9999, 'x')",
        "DELETE FROM Track",
        "DROP TABLE Track",
        "CREATE TABLE x (a)",
        "SELECT 1; DROP TABLE Track",
    ],
)
def test_a_write_statement_through_the_tool_fails_and_the_file_is_unchanged(statement):
    before = sha(DATABASE)
    result = sql_tool.run_query(DATABASE, statement)
    assert result["error"] is not None
    assert result["rows"] == [] and result["columns"] == []
    assert sha(DATABASE) == before


@pytest.mark.parametrize(
    "template",
    [
        "VACUUM INTO '{path}'",
        "ATTACH DATABASE '{path}' AS other",
        "ATTACH '{path}' AS other; SELECT 1",
        "DETACH DATABASE other",
    ],
)
def test_the_tool_cannot_create_a_file_through_vacuum_into_or_attach(tmp_path, template):
    target = tmp_path / "written.db"
    before = sha(DATABASE)
    result = sql_tool.run_query(DATABASE, template.format(path=target))
    assert isinstance(result["error"], dict)
    assert set(result["error"]) == {"type", "message"}
    assert result["rows"] == [] and result["columns"] == []
    assert list(tmp_path.iterdir()) == []
    assert sha(DATABASE) == before


def test_the_tools_connection_allows_no_attached_database_and_reads_still_work():
    connection = sql_tool.open_sqlite_readonly(DATABASE)
    try:
        sql_tool.restrict_connection(connection)
        assert connection.getlimit(sqlite3.SQLITE_LIMIT_ATTACHED) == 0
        assert connection.execute("SELECT count(*) FROM Genre").fetchone()[0] > 0
    finally:
        connection.close()


def test_load_extension_fails_on_the_tools_connection():
    result = sql_tool.run_query(DATABASE, "SELECT load_extension('does-not-exist')")
    assert result["error"] is not None


def test_the_tool_never_uses_executescript_and_takes_no_path_from_the_model():
    import ast

    from inspect_ai.tool import ToolDef

    tree = ast.parse(Path(sql_tool.__file__).read_text())
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "executescript" not in called
    assert "execute" in called
    # the model supplies the SQL only: the database path is fixed by the application

    definition = ToolDef(sql_tool.query_readonly(DATABASE))
    assert list(definition.parameters.properties) == ["sql"]


def test_each_execution_opens_its_own_connection(monkeypatch):
    opened = []
    real = sql_tool.open_sqlite_readonly

    def spy(path):
        connection = real(path)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sql_tool, "open_sqlite_readonly", spy)
    sql_tool.run_query(DATABASE, "SELECT 1")
    sql_tool.run_query(DATABASE, "SELECT 1")
    assert len(opened) == 2 and opened[0] is not opened[1]


# What the model is sent is tested in test_agent_task.py (ticket #44).


# --- structure ----------------------------------------------------------------------


def test_the_projection_reads_the_log_only_through_the_public_api():
    source = Path(projection.__file__).read_text()
    assert "from inspect_ai.log import" in source and "read_eval_log" in source
    for forbidden in ("zipfile", "open(", "json.load(", "read_bytes", "read_text"):
        assert forbidden not in source, forbidden


def test_no_core_module_imports_inspect():
    program = (
        "import importlib, pkgutil, sys, hypotrail.core as core\n"
        "for m in pkgutil.walk_packages(core.__path__, 'hypotrail.core.'):\n"
        "    importlib.import_module(m.name)\n"
        "import hypotrail.cli\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in {'inspect_ai', 'sklearn', 'numpy', 'anthropic'}))\n"
    )
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"
    for path in (ROOT / "src" / "hypotrail" / "core").glob("*.py"):
        assert "inspect_ai" not in path.read_text(), path.name


def test_the_scripted_model_never_loads_a_tiktoken_vocabulary(monkeypatch):
    """SPEC DATA-03: a scripted run needs no download, even through a proxy that hides it from the guard."""
    import asyncio

    import tiktoken
    from inspect_ai.model import ChatMessageUser, ModelOutput

    from hypotrail.agentic.runner import mock_model

    def refuse(*args, **kwargs):
        raise AssertionError("tiktoken vocabulary requested")

    monkeypatch.setattr(tiktoken, "get_encoding", refuse)
    model = mock_model(lambda *a, **k: ModelOutput.from_content(MODEL, "ok"))
    output = asyncio.run(model.generate([ChatMessageUser(content="hello there")]))

    assert output.usage.input_tokens >= 1
