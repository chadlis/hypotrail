"""Reading Cases. A Case carries no expected answer; References live elsewhere."""

import json
from pathlib import Path

from hypotrail.agentic.prompt import render_model_input


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


def model_input(case: dict) -> tuple[str, str]:
    """The (system, user) texts for a Case: an allow-list of three fields."""
    return render_model_input(
        question=case["question"], columns=case["answer_columns"], unit=case["unit"]
    )
