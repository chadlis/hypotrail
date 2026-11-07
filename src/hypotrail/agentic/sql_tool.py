"""The read-only SQL tool of the Chinook agent.

The database path is fixed by the application when the tool is built; the model
supplies the SQL and nothing else. The file is opened read-only for each
execution, and a single statement is run with `execute`, never `executescript`.

SQLite decides what runs; this module never reads the SQL text. Three native
mechanisms do the work:

- the number of attached databases is limited to 0 (`mode=ro` covers the main
  database only);
- an authorizer holds the AG-03 allow-list: SELECT, reads of the tables the file
  itself declares (so never its system tables), and thirteen functions:
  `count`, `sum`, `avg`, `min`, `max`, `round`, `lower`, `upper`, `coalesce`,
  `ifnull`, `strftime`, `like` and `glob`. The last two are how SQLite reports
  the operators LIKE (also NOT LIKE and LIKE ... ESCAPE) and GLOB, added to the
  eleven of AG-03 by the owner's revision of 2026-11-07 (#51); they only compare
  text. `PRAGMA case_sensitive_like` stays refused, like every PRAGMA. Every
  other action is denied: writes, DDL, ATTACH, DETACH, PRAGMA, transactions,
  VACUUM, extension loading, any other function;
- `execute` accepts a single statement.

A refused or failed statement comes back as a structured tool error whose `code`
tells a denied action from a SQL error, from a call holding several statements,
and from a query stopped by a cap.

Four caps bound each query (`QueryCaps`, AG-04). SQLite's progress handler
watches the first two on every 1000 VM instructions; the other two apply to the
fetched rows:

- watched time: 1 s of wall clock, code `TIME_LIMIT`;
- an instruction ceiling, code `INSTRUCTION_LIMIT`. AG-04 gives no number. The
  declared default is 100,000,000 VM instructions: the 1 s time stays the
  spec's primary cap, and the ceiling is a machine-independent backstop set near
  it (about 0.7 s at the ~138M instructions per second measured here), about
  3,000 times the heaviest of the 16 oracle statements (~32,000). It does not
  refuse a read the time cap would allow on this machine. The value is recorded
  among the effective limits and changes only by a new value in the record;
- at most 200 rows returned, at most 201 fetched to detect more;
- at most 64 KiB of serialized content (the JSON of columns and rows).

A cap that is reached shows as `truncated: true` (rows, size) or as an error
naming the limit (time, instructions), with no rows. It is never turned into a
complete result.

The query runs in a worker thread, so Inspect's event loop stays free and the
Episode time limit keeps control. If the awaiting task is cancelled, the
progress handler sees a stop flag and interrupts the statement.
"""

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import anyio
from inspect_ai.tool import Tool, tool

from hypotrail.core.data import open_sqlite_readonly


DENIED_ACTION = "DENIED_ACTION"
SQL_ERROR = "SQL_ERROR"
MULTIPLE_STATEMENTS = "MULTIPLE_STATEMENTS"
TIME_LIMIT = "TIME_LIMIT"
INSTRUCTION_LIMIT = "INSTRUCTION_LIMIT"

PROGRESS_INTERVAL = 1000  # VM instructions between two calls of the progress handler


@dataclass(frozen=True)
class QueryCaps:
    time_seconds: float = 1.0
    max_instructions: int = 100_000_000
    max_rows: int = 200
    max_bytes: int = 64 * 1024

    def as_dict(self) -> dict:
        return asdict(self)

# The eleven functions of AG-03 and, added by the owner's revision of 2026-11-07 (#51), `like`
# and `glob`: SQLite's authorizer reports the operators LIKE and GLOB under these names.
ALLOWED_FUNCTIONS = frozenset(
    {
        "count", "sum", "avg", "min", "max", "round", "lower", "upper", "coalesce", "ifnull", "strftime",
        "like", "glob",
    }
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


class _Watcher:
    """SQLite's progress handler: stops the statement at a cap or when asked to."""

    def __init__(self, caps: QueryCaps, stop: threading.Event | None):
        self.caps = caps
        self.stop = stop
        self.started = time.monotonic()
        self.instructions = 0
        self.reason = None

    def __call__(self):
        self.instructions += PROGRESS_INTERVAL
        if self.stop is not None and self.stop.is_set():
            self.reason = "stopped"
        elif self.instructions > self.caps.max_instructions:
            self.reason = INSTRUCTION_LIMIT
        elif time.monotonic() - self.started > self.caps.time_seconds:
            self.reason = TIME_LIMIT
        return 1 if self.reason else 0


def _error(error: Exception, authorizer: _Authorizer, watcher: _Watcher) -> dict:
    if watcher.reason in (TIME_LIMIT, INSTRUCTION_LIMIT):
        code = watcher.reason
    elif authorizer.denied:
        code = DENIED_ACTION
    elif isinstance(error, sqlite3.ProgrammingError):
        code = MULTIPLE_STATEMENTS
    else:
        code = SQL_ERROR
    return {"code": code, "type": type(error).__name__, "message": str(error)}


def _within_size(columns: list, rows: list, max_bytes: int) -> list:
    """The longest prefix of the rows whose serialized content fits `max_bytes`."""
    size = len(json.dumps({"columns": columns, "rows": []}, default=str).encode())
    kept = []
    for row in rows:
        size += len(json.dumps(row, default=str).encode()) + 2  # separator
        if size > max_bytes:
            break
        kept.append(row)
    return kept


def schema_description(database: Path) -> dict:
    """The tables of the file with their columns, types and foreign keys, read from SQLite itself.

    The application reads the schema (`PRAGMA` on a read-only connection); the model supplies
    nothing. It holds no row, no Reference and no oracle SQL.
    """
    connection = open_sqlite_readonly(database)
    try:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        tables = []
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            tables.append(
                {
                    "name": name,
                    "columns": [
                        {"name": c[1], "type": c[2], "not_null": bool(c[3]), "primary_key_position": c[5]}
                        for c in connection.execute(f"PRAGMA table_info({quoted})")
                    ],
                    "foreign_keys": [
                        {"from": f[3], "table": f[2], "to": f[4]}
                        for f in connection.execute(f"PRAGMA foreign_key_list({quoted})")
                    ],
                }
            )
        return {"tables": tables}
    finally:
        connection.close()


def run_query(
    database: Path,
    sql: str,
    caps: QueryCaps = QueryCaps(),
    *,
    stop: threading.Event | None = None,
    cursor_factory: type = sqlite3.Cursor,
) -> dict:
    """Run one statement under the caps and return the tool result.

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
    watcher = _Watcher(caps, stop)
    try:
        authorizer = restrict_connection(connection)
        connection.set_progress_handler(watcher, PROGRESS_INTERVAL)
        cursor = connection.cursor(cursor_factory)
        cursor.execute(sql)
        columns = [d[0] for d in cursor.description or []]
        fetched = [list(row) for row in cursor.fetchmany(caps.max_rows + 1)]
        rows = fetched[: caps.max_rows]
        truncated = len(fetched) > caps.max_rows
        fitting = _within_size(columns, rows, caps.max_bytes)
        truncated = truncated or len(fitting) < len(rows)
        result.update(columns=columns, rows=fitting, row_count=len(fitting), truncated=truncated)
    except (sqlite3.Error, ValueError) as error:
        result["error"] = _error(error, authorizer, watcher)
    finally:
        connection.close()
    return result


@tool
def describe_schema(database: Path) -> Tool:
    async def execute() -> str:
        """Describe the database: its tables, their columns and types, and their foreign-key relations."""
        return json.dumps(schema_description(database))

    return execute


@tool
def query_readonly(database: Path, caps: QueryCaps = QueryCaps()) -> Tool:
    async def execute(sql: str) -> str:
        """Run one read-only SQL SELECT statement on the Chinook database.

        Args:
            sql: A single SQL SELECT statement.
        """
        stop = threading.Event()
        try:
            result = await anyio.to_thread.run_sync(
                lambda: run_query(database, sql, caps, stop=stop), abandon_on_cancel=True
            )
        finally:
            stop.set()  # a cancelled await interrupts the statement
        return json.dumps(result, default=str)

    return execute


__all__ = [
    "QueryCaps",
    "describe_schema",
    "open_sqlite_readonly",
    "query_readonly",
    "run_query",
    "schema_description",
]
