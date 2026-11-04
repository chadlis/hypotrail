"""The read-only SQL tool of the Chinook agent.

The database path is fixed by the application when the tool is built; the model
supplies the SQL and nothing else. The file is opened read-only for each
execution, and a single statement is run with `execute`, never `executescript`.

`mode=ro` covers the main database only, so `VACUUM INTO '/path'` and
`ATTACH DATABASE '/path'` could still write a file. Two native SQLite mechanisms
close that, with no inspection of the SQL text: the number of attached databases
is limited to 0, and a minimal authorizer allows only the actions that read
(SELECT, READ, FUNCTION, RECURSIVE) and denies every other one, ATTACH and
DETACH among them. A denied statement comes back as a structured tool error.

This is not the AG-03 allow-list. The full allow-list (reads on the eleven
tables, the permitted functions, refusing PRAGMA, transactions and system
tables) and the row, size and time caps belong to the agentic Track slice
(issue #8), not to this spike.
"""

import json
import sqlite3
import uuid
from pathlib import Path

from inspect_ai.tool import Tool, tool

from hypotrail.core.data import open_sqlite_readonly


_ALLOWED_ACTIONS = frozenset(
    {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_RECURSIVE,
    }
)


def _authorize(action, arg1, arg2, database, trigger):
    """SQLite's authorizer callback: read actions pass, every other action is denied."""
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def restrict_connection(connection: sqlite3.Connection) -> None:
    """No attached database and no action but reads, on this connection."""
    connection.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    connection.set_authorizer(_authorize)


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
    try:
        restrict_connection(connection)
        cursor = connection.execute(sql)
        result["columns"] = [d[0] for d in cursor.description or []]
        result["rows"] = [list(row) for row in cursor.fetchall()]
        result["row_count"] = len(result["rows"])
    except (sqlite3.Error, ValueError) as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)}
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
