"""Reading Cases. A Case carries no expected answer; References live elsewhere."""

import json
from pathlib import Path

from hypotrail.agentic.prompt import render_user_message
from hypotrail.core.errors import InvalidInputError


def _refuse(code, message, path, **details):
    return InvalidInputError(code, message, stage="declaration", details={"file": str(path), **details})


def load_cases(path: Path, case_ids: list[str] | None = None) -> list[dict]:
    """Read Cases from a JSON Lines file, in file order or in `case_ids` order.

    The one reader of Cases files. It refuses a file that cannot be read (FILE_NOT_FOUND) and a line
    that is not a JSON object with a string `case_id` (FILE_NOT_JSON), then a `case_id` that appears on
    two lines of the file (CASE_ID_NOT_UNIQUE; GLOSSARY Item: a stable ID that never depends on file order).
    """
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, NotADirectoryError):
        raise _refuse("FILE_NOT_FOUND", f"Cases file not found: {path}", path) from None
    except (OSError, ValueError):
        raise _refuse("FILE_NOT_JSON", f"Cases file cannot be read as text: {path}", path) from None
    cases = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except ValueError:
            raise _refuse("FILE_NOT_JSON", f"Cases file {path} line {number} is not valid JSON", path, line=number) from None
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
            raise _refuse("FILE_NOT_JSON", f"Cases file {path} line {number} is not a Case object", path, line=number)
        cases.append(case)
    seen: set[str] = set()
    for case in cases:
        if case["case_id"] in seen:
            raise _refuse(
                "CASE_ID_NOT_UNIQUE",
                f"Cases file {path} lists the Case {case['case_id']!r} twice",
                path,
                case_id=case["case_id"],
            )
        seen.add(case["case_id"])
    if case_ids is None:
        return cases
    by_id = {case["case_id"]: case for case in cases}
    missing = [case_id for case_id in case_ids if case_id not in by_id]
    if missing:
        raise KeyError(f"unknown Case ids: {missing}")
    return [by_id[case_id] for case_id in case_ids]


def user_message(case: dict) -> str:
    """The user message for a Case: an allow-list of three fields."""
    return render_user_message(
        question=case["question"], columns=case["answer_columns"], unit=case["unit"]
    )
