"""Reading Cases. A Case carries no expected answer; References live elsewhere."""

import json
from pathlib import Path

from hypotrail.agentic.prompt import render_user_message


def load_cases(path: Path, case_ids: list[str] | None = None) -> list[dict]:
    """Read Cases from a JSON Lines file, in file order or in `case_ids` order."""
    cases = [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
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
