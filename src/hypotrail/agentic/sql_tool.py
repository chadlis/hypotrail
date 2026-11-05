"""The read-only SQL tool of the Chinook agent.

The database path is fixed by the application when the tool is built; the model
supplies the SQL and nothing else. The file is opened read-only for each
execution, and a single statement is run with `execute`, never `executescript`.

SQLite decides what runs; this module never reads the SQL text. Three native
mechanisms do the work:

- the number of attached databases is limited to 0 (`mode=ro` covers the main
  database only);
- an authorizer holds the AG-03 allow-list: SELECT, reads of the tables the file
  itself declares (so never its system tables), and the functions `count`,
  `sum`, `avg`, `min`, `max`, `round`, `lower`, `upper`, `coalesce`, `ifnull`
  and `strftime`. Every other action is denied: writes, DDL, ATTACH, DETACH,
  PRAGMA, transactions, VACUUM, extension loading, any other function;
- `execute` accepts a single statement.

A refused or failed statement comes back as a structured tool error whose `code`
tells a denied action from a SQL error and from a call holding several
statements. Row, size and time caps are another ticket.
"""

import json
import sqlite3
import uuid
from pathlib import Path

from inspect_ai.tool import Tool, tool

from hypotrail.core.data import open_sqlite_readonly


DENIED_ACTION = "DENIED_ACTION"
SQL_ERROR = "SQL_ERROR"
MULTIPLE_STATEMENTS = "MULTIPLE_STATEMENTS"

ALLOWED_FUNCTIONS = frozenset(
    {"count", "sum", "avg", "min", "max", "round", "lower", "upper", "coalesce", "ifnull", "strftime"}
)


def declared_tables(connection: sqlite3.Connection) -> frozenset[str]:
    """The tables the file itself declares, read before the authorizer is installed."""
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"
    )
    return frozenset(name for (name,) in rows)


class _Authorizer:
    """SQLite's authorizer callback. It remembers that it denied something, because
    SQLite reports a denied function as a plain SQL error, not as an authorization one."""

    def __init__(self, tables: frozenset[str]):
        self.tables = tables
        self.denied = False

    def __call__(self, action, arg1, arg2, database, trigger):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and database in (None, "main") and arg1 in self.tables:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and arg2 and arg2.lower() in ALLOWED_FUNCTIONS:
            return sqlite3.SQLITE_OK
        self.denied = True
        return sqlite3.SQLITE_DENY


def restrict_connection(connection: sqlite3.Connection) -> _Authorizer:
    """No attached database and no action off the allow-list, on this connection."""
    authorizer = _Authorizer(declared_tables(connection))
    connection.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    connection.set_authorizer(authorizer)
    return authorizer


def _error(error: Exception, authorizer: _Authorizer) -> dict:
    if authorizer.denied:
        code = DENIED_ACTION
    elif isinstance(error, sqlite3.ProgrammingError):
        code = MULTIPLE_STATEMENTS
    else:
        code = SQL_ERROR
    return {"code": code, "type": type(error).__name__, "message": str(error)}


def run_query(database: Path, sql: str) -> dict:
    """Run one statement and return the tool result.

    The `tool_call_id` is minted here: Inspect exposes no public way to read its
    own tool-call ID while a tool runs. The projection keeps the mapping to the
    native event.
    """
    result = {
        "columns": [],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "error": None,
        "tool_call_id": f"hypotrail-{uuid.uuid4().hex}",
    }
    connection = open_sqlite_readonly(database)
    authorizer = None
    try:
        authorizer = restrict_connection(connection)
        cursor = connection.execute(sql)
        result["columns"] = [d[0] for d in cursor.description or []]
        result["rows"] = [list(row) for row in cursor.fetchall()]
        result["row_count"] = len(result["rows"])
    except (sqlite3.Error, ValueError) as error:
        result["error"] = _error(error, authorizer)
    finally:
        connection.close()
    return result


@tool
def query_readonly(database: Path) -> Tool:
    async def execute(sql: str) -> str:
        """Run one read-only SQL SELECT statement on the Chinook database.

        Args:
            sql: A single SQL SELECT statement.
        """
        return json.dumps(run_query(database, sql), default=str)

    return execute


__all__ = ["open_sqlite_readonly", "query_readonly", "run_query"]
