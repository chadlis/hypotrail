"""Verification of the public datasets against their lock (`data verify`).

Standard library only. The order is fixed: the bytes of every selected dataset
are verified first, then the licence notices, and only then the content checks
(calendar, tables). Tampered bytes never reach a content check.
"""

import csv
import datetime
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from hypotrail.core.errors import IntegrityError, InvalidInputError

LOCK_NAME = "data-sources.lock.json"
CHECKS_NAME = "data-checks.json"


class DataCheckError(IntegrityError):
    """A content check failed on bytes that matched the lock."""

    def __init__(self, stage, message, details=None):
        super().__init__(
            "DATA_CHECK_FAILED", message, stage=stage, details=details
        )


def default_examples_dir() -> Path:
    """The `examples/` beside the source checkout; an install that is not a checkout has no such directory."""
    return Path(__file__).resolve().parents[3] / "examples"


def resolve_examples_dir(examples_dir: Path | str | None = None) -> Path:
    """The directory holding the Workloads, for every command that reads one (D-016 on chadlis/hypotrail#75).

    In this order: `--examples-dir` when it is given; otherwise the checkout's `examples/`, only if it exists and
    holds at least one Workload lock; otherwise a refusal that names the flag. No environment variable is read and no
    Workload is packaged in the wheel, so an install that is not a checkout finds the Workloads only through the flag.
    """
    if examples_dir is not None:
        return Path(examples_dir)
    default = default_examples_dir()
    if default.is_dir() and discover_workloads(default):
        return default
    if default.is_dir():
        fact = f"{default} exists but holds no Workload lock ({LOCK_NAME})"
    elif default.exists():
        fact = f"{default} exists but is not a directory"
    elif default.is_symlink():
        fact = f"{default} is a link whose target does not exist"
    else:
        fact = f"{default} does not exist"
    reason = f"{fact}; give the directory that holds the Workloads with --examples-dir DIR"
    raise InvalidInputError(
        "EXAMPLES_DIR_NOT_FOUND",
        f"no Workloads found: {reason}",
        stage="config",
        details={"examples_dir": str(default)},
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def open_sqlite_readonly(path: Path) -> sqlite3.Connection:
    """Open a SQLite file read-only (`mode=ro`) with extensions disabled."""
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.enable_load_extension(False)
    except AttributeError:  # this Python was built without extension loading
        pass
    return connection


# --- loading ------------------------------------------------------------------


def discover_workloads(examples_dir: Path) -> list[str]:
    return sorted(
        p.name for p in examples_dir.iterdir() if (p / LOCK_NAME).is_file()
    )


def _load_json(path: Path, what: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InvalidInputError(
            "FILE_NOT_FOUND",
            f"{what} not found: {path}",
            stage="config",
            details={"file": str(path)},
        ) from None
    except json.JSONDecodeError as error:
        raise InvalidInputError(
            "FILE_NOT_JSON",
            f"{what} is not valid JSON: {path}",
            stage="config",
            details={"file": str(path), "line": error.lineno},
        ) from None


def _load_workload(examples_dir: Path, name: str) -> dict:
    directory = examples_dir / name
    if not (directory / LOCK_NAME).is_file():
        raise InvalidInputError(
            "UNKNOWN_WORKLOAD",
            f"unknown workload: {name}",
            stage="config",
            details={"workload": name, "known": discover_workloads(examples_dir)},
        )
    lock = _load_json(directory / LOCK_NAME, "lock")
    checks = _load_json(directory / CHECKS_NAME, "data checks")
    by_dataset = {s["dataset_id"]: s for s in lock["sources"]}
    if checks.get("dataset_id") not in by_dataset:
        raise InvalidInputError(
            "CHECKS_WITHOUT_SOURCE",
            f"{CHECKS_NAME} names a dataset the lock does not list",
            stage="config",
            details={"workload": name, "dataset_id": checks.get("dataset_id")},
        )
    return {
        "name": name,
        "directory": directory,
        "source": by_dataset[checks["dataset_id"]],
        "checks": checks,
        "lock_sources": lock["sources"],
    }


# --- stages ---------------------------------------------------------------------


def _verify_bytes(workload: dict, *, skip_dataset: bool = False) -> None:
    for source in workload["lock_sources"]:
        if skip_dataset and source["dataset_id"] == workload["source"]["dataset_id"]:
            continue
        path = workload["directory"] / source["local_path"]
        details = {"workload": workload["name"], "file": source["local_path"]}
        if not path.is_file():
            raise IntegrityError(
                "DATA_MISSING",
                f"data file missing: {source['local_path']}",
                stage="integrity",
                details=details,
            )
        actual_size = path.stat().st_size
        actual_hash = sha256_file(path)
        if actual_size != source["size_bytes"] or actual_hash != source["sha256"]:
            raise IntegrityError(
                "DATA_INTEGRITY",
                f"{source['local_path']} does not match the lock "
                f"(expected sha256 {source['sha256']}, got {actual_hash})",
                stage="integrity",
                details={
                    **details,
                    "expected_sha256": source["sha256"],
                    "actual_sha256": actual_hash,
                    "expected_size_bytes": source["size_bytes"],
                    "actual_size_bytes": actual_size,
                },
            )


def _verify_licence(workload: dict) -> None:
    for source in workload["lock_sources"]:
        notice = workload["directory"] / source["notice"]
        details = {"workload": workload["name"], "file": source["notice"]}
        if not notice.is_file() or notice.stat().st_size == 0:
            raise IntegrityError(
                "LICENCE_NOTICE_MISSING",
                f"licence notice missing or empty: {source['notice']}",
                stage="licence",
                details=details,
            )
        expected = source.get("notice_sha256")
        if expected is not None and sha256_file(notice) != expected:
            raise IntegrityError(
                "LICENCE_NOTICE_CHANGED",
                f"{source['notice']} does not match the lock's notice_sha256",
                stage="licence",
                details={**details, "expected_sha256": expected},
            )


_NON_NEGATIVE_INTEGER = re.compile(r"[0-9]+")


def check_daily_series(path: Path, source: dict, spec: dict) -> dict:
    """One row per date from `date_min` to `date_max`, no gap, no duplicate."""
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != spec["columns"]:
            raise DataCheckError(
                "schema",
                f"columns differ from the declared ones: {reader.fieldnames}",
                {"expected": spec["columns"], "actual": reader.fieldnames},
            )
        rows = list(reader)

    key = source["native_key"]
    for position, row in enumerate(rows, 1):
        if row[key] is None:  # a short row: DictReader fills the missing cells with None
            raise DataCheckError(
                "calendar",
                f"{key} is missing on data row {position}",
                {"column": key, "row": position},
            )
    try:
        dates = [datetime.date.fromisoformat(row[key]) for row in rows]
    except ValueError as error:
        raise DataCheckError("calendar", f"unreadable date: {error}") from None

    first = datetime.date.fromisoformat(source["date_min"])
    last = datetime.date.fromisoformat(source["date_max"])
    expected_days = (last - first).days + 1
    if len(set(dates)) != len(dates):
        raise DataCheckError("calendar", "a date appears more than once")
    expected = [first + datetime.timedelta(days=i) for i in range(expected_days)]
    if dates != expected or len(rows) != source["rows"]:
        raise DataCheckError(
            "calendar",
            f"expected exactly one row per day from {first} to {last} "
            f"({source['rows']} rows), found {len(rows)}",
            {"rows": len(rows), "expected_rows": source["rows"]},
        )

    total, parts = spec["total_column"], spec["part_columns"]
    for row in rows:
        for column in [total, *parts]:
            if row[column] is None or not _NON_NEGATIVE_INTEGER.fullmatch(row[column]):
                raise DataCheckError(
                    "values",
                    f"{column} is not a non-negative integer on {row[key]}: "
                    f"{row[column]!r}",
                    {"date": row[key], "column": column},
                )
        if int(row[total]) != sum(int(row[p]) for p in parts):
            raise DataCheckError(
                "values",
                f"{total} != {' + '.join(parts)} on {row[key]}",
                {"date": row[key]},
            )
    return {
        "rows": len(rows),
        "date_min": dates[0].isoformat(),
        "date_max": dates[-1].isoformat(),
    }


def check_sqlite_tables(path: Path, source: dict, spec: dict) -> dict:
    """SQLite integrity is `ok` and every table has its declared row count."""
    connection = open_sqlite_readonly(path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise DataCheckError(
                "sqlite_integrity",
                f"SQLite integrity check returned {integrity!r}",
            )
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = {
            name: connection.execute(
                'SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"'
            ).fetchone()[0]
            for name in names
        }
    finally:
        connection.close()
    if counts != spec["table_row_counts"]:
        raise DataCheckError(
            "tables",
            "table row counts differ from the declared ones",
            {"expected": spec["table_row_counts"], "actual": counts},
        )
    return {"integrity_check": integrity, "table_row_counts": counts}


def _check_content(workload: dict) -> dict:
    source, spec = workload["source"], workload["checks"]
    path = workload["directory"] / source["local_path"]
    kind = spec["kind"]
    try:
        if kind == "daily_series":
            return check_daily_series(path, source, spec)
        if kind == "sqlite_tables":
            return check_sqlite_tables(path, source, spec)
    except DataCheckError as error:
        error.details.setdefault("workload", workload["name"])
        raise
    raise InvalidInputError(
        "UNKNOWN_CHECK_KIND",
        f"unknown data check kind: {kind}",
        stage="config",
        details={"workload": workload["name"], "kind": kind},
    )


def verify_workloads(examples_dir: Path, names: list[str] | None = None) -> list[dict]:
    """Verify the named Workloads (all of them by default)."""
    examples_dir = Path(examples_dir)
    if not examples_dir.is_dir():
        raise InvalidInputError(
            "EXAMPLES_DIR_NOT_FOUND",
            f"examples directory not found: {examples_dir}",
            stage="config",
            details={"examples_dir": str(examples_dir)},
        )
    if names is None:
        names = discover_workloads(examples_dir)
    if not names:
        raise InvalidInputError(
            "NO_WORKLOAD",
            f"no Workload to verify in {examples_dir}",
            stage="config",
            details={"examples_dir": str(examples_dir)},
        )
    workloads = [_load_workload(examples_dir, name) for name in names]
    for workload in workloads:
        _verify_bytes(workload)
    for workload in workloads:
        _verify_licence(workload)
    reports = []
    for workload in workloads:
        content = _check_content(workload)
        source = workload["source"]
        reports.append(
            {
                "workload": workload["name"],
                "dataset_id": source["dataset_id"],
                "status": "verified",
                "file": source["local_path"],
                "sha256": source["sha256"],
                "size_bytes": source["size_bytes"],
                "license": source["license"],
                "notice": source["notice"],
                "checks": content,
            }
        )
    return reports


def verify_workload_files(examples_dir: Path, name: str) -> None:
    """Check the bytes of the named Workload's other files against its lock, and its licence notices; the dataset is not opened.

    `verify_workloads` goes further and queries the content (the Chinook database is opened and its
    tables counted). A command that must never open the database, as `import agent` and `assess` must
    not, neither opens nor hashes it: `init` checked it, and the Study keeps a copy that every
    command reads back against its digest.
    """
    examples_dir = Path(examples_dir)
    if not examples_dir.is_dir():
        raise InvalidInputError(
            "EXAMPLES_DIR_NOT_FOUND",
            f"examples directory not found: {examples_dir}",
            stage="config",
            details={"examples_dir": str(examples_dir)},
        )
    workload = _load_workload(examples_dir, name)
    _verify_bytes(workload, skip_dataset=True)
    _verify_licence(workload)
