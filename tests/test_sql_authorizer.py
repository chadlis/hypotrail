"""Ticket #43: `query_readonly` runs only reads, decided by SQLite's authorizer allow-list."""

import ast
import hashlib
import sqlite3
from pathlib import Path

import pytest

from _agent_helpers import CASES, DATABASE, REFERENCES, ScriptedModel, read_jsonl

from hypotrail.agentic import cases as case_module
from hypotrail.agentic import projection, runner, sql_tool

DENIED = "DENIED_ACTION"
SQL_ERROR = "SQL_ERROR"
MULTIPLE = "MULTIPLE_STATEMENTS"

ORACLES = [r for r in read_jsonl(REFERENCES) if r.get("oracle_sql")]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --- valid reads return the exact result ------------------------------------------------------


def test_the_references_with_an_oracle_sql_are_the_sixteen_of_the_kit():
    assert len(ORACLES) == 16


@pytest.mark.parametrize("reference", ORACLES, ids=lambda r: r["case_id"])
def test_the_tool_returns_exactly_the_reference_columns_and_rows(reference):
    result = sql_tool.run_query(DATABASE, reference["oracle_sql"])
    assert result["error"] is None
    assert result["truncated"] is False
    assert result["columns"] == reference["columns"]
    assert result["rows"] == reference["rows"]
    assert result["row_count"] == len(reference["rows"])


def test_a_scripted_join_episode_projects_the_call_then_the_same_rows_with_the_tool_call_id(tmp_path):
    cases = case_module.load_cases(CASES, ["D03"])
    location = runner.run_episodes(
        cases,
        database=DATABASE,
        model=runner.mock_model(ScriptedModel(cases)),
        repeats=1,
        log_dir=tmp_path / "logs",
    )
    [episode] = projection.project_log(location, expected=[("D03", 0)])
    kinds = [s["kind"] for s in episode["steps"]]
    assert kinds.index("tool_call") + 1 == kinds.index("tool_result")
    result = next(s for s in episode["steps"] if s["kind"] == "tool_result")
    reference = next(r for r in ORACLES if r["case_id"] == "D03")
    assert result["result"]["rows"] == reference["rows"]
    assert result["result"]["error"] is None
    assert result["result"]["tool_call_id"] == result["app_tool_call_id"]


# --- refusals ---------------------------------------------------------------------------------

REFUSED_AS_DENIED = [
    "INSERT INTO Genre (GenreId, Name) VALUES (9999, 'x')",
    "UPDATE Genre SET Name = 'x'",
    "DELETE FROM Genre",
    "CREATE TABLE x (a)",
    "DROP TABLE Genre",
    "ALTER TABLE Genre ADD COLUMN x",
    "ATTACH DATABASE ':memory:' AS other",
    "DETACH DATABASE other",
    "PRAGMA user_version",
    "PRAGMA user_version = 3",
    "BEGIN",
    "COMMIT",
    "SAVEPOINT a",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM sqlite_schema",
    "SELECT load_extension('x')",
    "SELECT length(Name) FROM Genre",
    "SELECT abs(-1)",
    "VACUUM",
    "VACUUM INTO '{path}'",
    "WITH x AS (SELECT 1) DELETE FROM Genre",
    "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 3) SELECT i FROM n",
]


@pytest.mark.parametrize("statement", REFUSED_AS_DENIED)
def test_a_refused_statement_has_the_denied_code_and_leaves_the_file_unchanged(tmp_path, statement):
    before = sha(DATABASE)
    result = sql_tool.run_query(DATABASE, statement.format(path=tmp_path / "out.db"))
    assert result["error"]["code"] == DENIED
    assert result["columns"] == [] and result["rows"] == [] and result["row_count"] == 0
    assert list(tmp_path.iterdir()) == []
    assert sha(DATABASE) == before


def test_two_statements_in_one_call_have_their_own_code_and_leave_the_file_unchanged():
    before = sha(DATABASE)
    result = sql_tool.run_query(DATABASE, "SELECT 1; DROP TABLE Genre")
    assert result["error"]["code"] == MULTIPLE
    assert result["rows"] == []
    assert sha(DATABASE) == before


def test_a_sql_error_has_a_code_different_from_a_denied_action():
    for statement in ("SELEC 1", "SELECT * FROM NoSuchTable", "SELECT NoSuchColumn FROM Genre"):
        assert sql_tool.run_query(DATABASE, statement)["error"]["code"] == SQL_ERROR
    assert len({DENIED, SQL_ERROR, MULTIPLE}) == 3


def test_the_error_is_structured_and_the_trace_keeps_it(tmp_path):
    cases = case_module.load_cases(CASES, ["D03"])
    script = ScriptedModel(cases)
    script.sql_by_question = {q: "DELETE FROM Genre" for q in script.sql_by_question}
    location = runner.run_episodes(
        cases,
        database=DATABASE,
        model=runner.mock_model(script),
        repeats=1,
        log_dir=tmp_path / "logs",
    )
    [episode] = projection.project_log(location, expected=[("D03", 0)])
    result = next(s for s in episode["steps"] if s["kind"] == "tool_result")["result"]
    assert result["error"]["code"] == DENIED
    assert result["tool_call_id"].startswith("hypotrail-")


# --- the allow-list is decided by SQLite, not by the text -------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "select count(*) from Genre",
        "-- a comment\nSELECT count(*) FROM Genre",
        "/* a comment */ SELECT count(*) FROM Genre",
        "WITH g AS (SELECT GenreId FROM Genre) SELECT count(*) FROM g",
        "SELECT count(*) FROM Genre;",
    ],
)
def test_a_valid_read_passes_whatever_its_case_or_leading_comment(statement):
    result = sql_tool.run_query(DATABASE, statement)
    assert result["error"] is None
    assert result["rows"] == [[25]]


@pytest.mark.parametrize(
    "expression",
    [
        "count(*)",
        "sum(Milliseconds)",
        "avg(Milliseconds)",
        "min(Milliseconds)",
        "max(Milliseconds)",
        "round(avg(Milliseconds), 1)",
        "lower(max(Name))",
        "upper(max(Name))",
        "coalesce(max(Composer), 'none')",
        "ifnull(max(Composer), 'none')",
        "max(strftime('%Y', '2020-05-06'))",
    ],
)
def test_each_allowed_function_works_through_the_tool(expression):
    result = sql_tool.run_query(DATABASE, f"SELECT {expression} FROM Track")
    assert result["error"] is None
    assert result["row_count"] == 1


@pytest.mark.parametrize("function", ["length(Name)", "abs(-1)", "typeof(1)", "date('now')"])
def test_a_function_outside_the_list_is_denied(function):
    result = sql_tool.run_query(DATABASE, f"SELECT {function} FROM Genre")
    assert result["error"]["code"] == DENIED


def test_the_tool_module_never_matches_the_sql_against_keywords():
    source = Path(sql_tool.__file__).read_text()
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(node.module)])
    }
    assert not imported & {"re", "fnmatch", "sqlparse", "shlex"}
    text_tests = {"startswith", "endswith", "match", "search", "fullmatch", "findall", "split", "find", "index"}
    called = {
        n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert not called & text_tests
    # the SQL is only ever handed on to `run_query` and, there, to `execute`
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and any(isinstance(a, ast.Name) and a.id == "sql" for a in node.args):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            assert name in {"execute", "run_query"}, name
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Compare)
                and any(isinstance(x, ast.Name) and x.id == "sql" for x in [n.left, *n.comparators])]


# --- any SQLite file ----------------------------------------------------------------------------


@pytest.fixture
def other_database(tmp_path):
    path = tmp_path / "other.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE Widget (id INTEGER PRIMARY KEY, label TEXT)")
    connection.execute("CREATE TABLE Gadget (id INTEGER PRIMARY KEY, widget_id INTEGER)")
    connection.executemany("INSERT INTO Widget VALUES (?, ?)", [(1, "a"), (2, "b")])
    connection.execute("INSERT INTO Gadget VALUES (1, 2)")
    connection.commit()
    connection.close()
    return path


def test_the_readable_tables_are_those_of_the_file_not_chinook_names(other_database):
    joined = sql_tool.run_query(
        other_database, "SELECT w.label FROM Widget w JOIN Gadget g ON g.widget_id = w.id"
    )
    assert joined["error"] is None and joined["rows"] == [["b"]]
    assert sql_tool.run_query(other_database, "SELECT * FROM Genre")["error"]["code"] == SQL_ERROR


def test_system_tables_stay_refused_on_another_file(other_database):
    for table in ("sqlite_master", "sqlite_schema", "sqlite_temp_master"):
        result = sql_tool.run_query(other_database, f"SELECT * FROM {table}")
        assert result["error"]["code"] == DENIED, table
