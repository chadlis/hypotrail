"""Shared by the Declared deviation tests (#155): the `deviation` command on the command line, and the records it writes."""

import json
import uuid
from pathlib import Path

from _study_helpers import run_cli, run_json

CODE = "COMPARISON_DEVIATION_DECLARED"
PENDING = "owner review of References pending"
FOLDER = "declared_deviations"


def seq(study) -> int:
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    return payload["write_sequence"]


def deviation(study, cited, *, text=PENDING, author="human", source=None, request_id=None, read_sequence=None, omit=()):
    """`deviation --json` on the command line: (exit code, the JSON object on stdout or None when it printed none, stderr).

    A call that names no `request_id` gets a new one, so two calls are two requests.
    """
    flags = [
        ("--study", study),
        ("--text", text),
        ("--author", author),
        ("--request-id", f"dv-{uuid.uuid4()}" if request_id is None else request_id),
        ("--read-sequence", seq(study) if read_sequence is None else read_sequence),
    ]
    if source is not None:
        flags.append(("--source", source))
    flags += [("--artifact", cited_id) for cited_id in cited]
    code, out, err = run_cli("deviation", *[part for flag, value in flags if flag not in omit for part in (flag, value)], "--json")
    return code, (json.loads(out) if out.strip() else None), err


def outcome(payload):
    """The error code of a refusal, "ok" for a record written or replayed, None when the command printed nothing."""
    if payload is None:
        return None
    return "ok" if payload.get("ok") else payload.get("error", {}).get("code")


def declare(study, cited, **fields) -> dict:
    """The record of a Declared deviation the command accepts."""
    code, payload, err = deviation(study, cited, **fields)
    assert (code, outcome(payload)) == (0, "ok"), (payload, err)
    return payload["declared_deviation"]


def files(study) -> list:
    folder = Path(study) / FOLDER
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def coded(record, code=CODE) -> list:
    """The warnings of a Comparison record that have `code`."""
    return [warning for warning in record["warnings"] if warning["code"] == code]
