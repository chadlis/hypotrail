"""Validate and discover JSON lesson packs without opening a Study."""

import os
import re
import stat
from collections import Counter, defaultdict
from functools import cache
from importlib import resources
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

from hypotrail.core import canonical
from hypotrail.core.comparison import DEV
from hypotrail.core.errors import InvalidInputError

PACKS_ENV = "HYPOTRAIL_LESSON_PACKS"
_ID = re.compile(r"[a-z][a-z0-9-]{2,40}")
_LESSON_ID = re.compile(r"[a-z][a-z0-9-]{2,60}")
_DIGIT = re.compile(r"[0-9]")
_SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:[0-9A-Za-z-]+)(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
_READING = FormatChecker()
_FORBIDDEN_SEGMENT = re.compile(r"reference|case|per_item|public_check|held_out")
# Exact leaves already shown by the panel, outside the paired per-item rows.
# P4 serves path text and does not use it to retrieve values.
_SHARED_PATHS = {
    "status": {
        "comparisons[].delta.value",
        "comparisons[].interval.lower",
        "comparisons[].interval.upper",
    },
    "figures": {
        "comparisons[].quartiles.median",
    },
}
_SAFE_PATHS = {track: _SHARED_PATHS for track in ("temporal_regression", "tool_using_agent")}


@_READING.checks("semver")
def _semver(value):
    if not isinstance(value, str):
        return False
    match = _SEMVER.fullmatch(value)
    if match is None:
        return False
    pre = match[4]
    return pre is None or all(
        not part.isdigit() or len(part) == 1 or not part.startswith("0")
        for part in pre.split(".")
    )


@_READING.checks("https-url")
def _https(value):
    if not isinstance(value, str) or re.search(r"[\s\\]", value):
        return False
    try:
        url = urlsplit(value)
        return (
            value.startswith("https://")
            and bool(url.hostname)
            and url.username is None
            and (url.port is None or url.port > 0)
        )
    except ValueError:
        return False


@cache
def _validator():
    schema = canonical.loads(resources.files(__package__).joinpath("lesson-pack.schema.json").read_bytes())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=_READING)


def _json(path):
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                return None
            return canonical.loads(file.read())
    except (OSError, InvalidInputError, ValueError):
        return None


def _diagnostic(rule, path, lesson_id=None):
    return {"rule": rule, "lesson_id": lesson_id, "path": path}


def _identifier(value, pattern):
    identifier = value.get("id") if isinstance(value, dict) else None
    return identifier if isinstance(identifier, str) and pattern.fullmatch(identifier) else None


def _schema_errors(manifest, content):
    errors = []
    for error in _validator().iter_errors({"manifest": manifest, "content": content}):
        at = list(error.absolute_path)
        filename, *path = at
        lesson_id = None
        if len(path) >= 2 and path[0] == "lessons" and isinstance(path[1], int):
            lesson_id = _identifier(content["lessons"][path[1]], _LESSON_ID)
        file = "pack.json" if filename == "manifest" else "lessons.json"
        errors.append(_diagnostic("SCHEMA", ".".join([file, *map(str, path)]), lesson_id))
    return errors


def _resolved(payload, path):
    values = [payload]
    for segment in path.split("."):
        key = segment.rstrip("[]")
        if not all(isinstance(value, dict) and key in value for value in values):
            return False
        values = [value[key] for value in values]
        for _ in range(segment.count("[]")):
            if not all(isinstance(value, list) for value in values):
                return False
            values = [entry for value in values for entry in value]
    return bool(values)


def _kept_reads(directory):
    reads = defaultdict(list)
    for path in sorted(directory.rglob("*.out")):
        match = re.search(r"(?:^|[.-])(status|figures)(?:[.-]|$)", path.name)
        if match is None:
            continue
        track = "tool_using_agent" if "chinook" in path.name else "temporal_regression"
        value = _json(path)
        if isinstance(value, dict) and value.get("ok") is not False:
            reads[track, match[1]].append(value)
    return reads


def _text_errors(text, path, lesson_id=None):
    values = text if isinstance(text, list) else [text]
    return [_diagnostic("DIGIT", path, lesson_id)] if any(_DIGIT.search(value) for value in values) else []


def _check_rules(manifest, lessons, kept=None):
    errors = []
    evaluator_station = _validator().schema["$defs"]["evaluatorStationId"]["const"]
    for index, station in enumerate(manifest["stations"]):
        path = f"pack.json.stations.{index}"
        for key in ("title", "purpose"):
            errors.extend(_text_errors(station[key], f"{path}.{key}"))
        if station["chat"] == (station["id"] == evaluator_station):
            errors.append(_diagnostic("CHAT_FLAG", f"{path}.chat"))

    seen = set()
    for index, lesson in enumerate(lessons):
        lesson_id, track = lesson["id"], lesson["track"]
        at = f"lessons.json.lessons.{index}"
        if track not in manifest["tracks"]:
            errors.append(_diagnostic("SCHEMA", f"{at}.track", lesson_id))
        if lesson_id in seen:
            errors.append(_diagnostic("DUPLICATE_LESSON_ID", f"{at}.id", lesson_id))
        seen.add(lesson_id)
        if lesson["station"] == evaluator_station:
            errors.append(_diagnostic("HELD_OUT_LESSON", f"{at}.station", lesson_id))
        for key in ("title", "why_this_step", "how_to_do_it", "how_to_read", "pitfalls", "question"):
            if key in lesson:
                errors.extend(_text_errors(lesson[key], f"{at}.{key}", lesson_id))
        for path_index, entry in enumerate(lesson["key_paths"]):
            read, path = entry["read"], entry["path"]
            location = f"{at}.key_paths.{path_index}.path"
            if _FORBIDDEN_SEGMENT.search(path) or path not in _SAFE_PATHS[track][read]:
                errors.append(_diagnostic("FORBIDDEN_PATH", location, lesson_id))
            elif kept is not None and not any(_resolved(payload, path) for payload in kept[track, read]):
                errors.append(_diagnostic("UNRESOLVED_PATH", location, lesson_id))
    return errors


def _is_directory(path):
    try:
        return path.is_dir()
    except (OSError, ValueError):
        return False


def _read_pack(directory, kept=None):
    entry = {"id": None, "path": str(directory), "valid": False, "reason": None}
    if not _is_directory(directory):
        entry["reason"] = "NOT_A_DIRECTORY"
        return entry, [_diagnostic("SCHEMA", "pack.json")]
    manifest_path = directory / "pack.json"
    try:
        manifest_path.lstat()
    except (OSError, ValueError):
        entry["reason"] = "MANIFEST_MISSING"
        return entry, [_diagnostic("SCHEMA", "pack.json")]

    manifest, content = _json(manifest_path), _json(directory / "lessons.json")
    entry["id"] = _identifier(manifest, _ID)
    errors = _schema_errors(manifest, content)
    if not errors:
        errors = _check_rules(manifest, content["lessons"], kept)
    if errors:
        entry["reason"] = "SCHEMA" if any(error["rule"] == "SCHEMA" for error in errors) else "CHECK_FAILED"
        return entry, errors
    return {**entry, "valid": True, "manifest": manifest, "lessons": content["lessons"]}, []


def check(directory, kept_directory):
    """Return typed diagnostics, without file contents."""
    _, errors = _read_pack(directory, _kept_reads(kept_directory))
    return errors


def discover(environ):
    """Read pack metadata and valid pack contents in the explicit directory order."""
    paths = environ.get(PACKS_ENV, "").split(os.pathsep)
    entries = [_read_pack(Path(path))[0] for path in paths if path]
    counts = Counter(entry["id"] for entry in entries if entry["id"] is not None)
    for index, entry in enumerate(entries):
        if counts[entry["id"]] > 1:
            entries[index] = {"id": entry["id"], "path": entry["path"], "valid": False, "reason": "DUPLICATE_PACK_ID"}
    return entries


def station_marks(status):
    """Use only dev Assessments and the presence of a Comparison or Decision."""
    dev_observations = {
        attempt["observation_set_id"]
        for attempt in status["attempts"]
        if attempt["partition"] == DEV and attempt["observation_set_id"] is not None
    }
    dev_assessments = sum(
        assessment.get("observation_set_id") in dev_observations for assessment in status["assessments"]
    )
    return {
        "baseline": dev_assessments >= 1,
        "iterate": dev_assessments >= 2,
        "compare_decide": bool(status["comparisons"] or status["decisions"]),
    }


def pack_read(entries, track):
    """Return public metadata and the first valid matching pack's text."""
    packs, stations, lessons = [], [], []
    selected = False
    for entry in entries:
        manifest = entry.get("manifest", {})
        packs.append({
            "id": entry["id"], "version": manifest.get("version"), "title": manifest.get("title"),
            "language": manifest.get("language"), "licence": manifest.get("licence"),
            "valid": entry["valid"], "reason": entry["reason"],
        })
        if not selected and entry["valid"] and track in manifest["tracks"]:
            source = f"{manifest['id']}@{manifest['version']}"
            stations = [{**station, "has_records": None} for station in manifest["stations"]]
            lessons = [{**lesson, "source": source} for lesson in entry["lessons"] if lesson["track"] == track]
            selected = True
    return {"packs": packs, "stations": stations, "lessons": lessons}
