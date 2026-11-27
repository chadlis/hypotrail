"""The Criteria of every chinook_prose fixture answer and reference text, as pinned at 941ffd8 before the block reader (#271)."""

import json
from pathlib import Path

import pytest
from _study_helpers import EXAMPLES

from hypotrail.core import text_facts

PROSE = EXAMPLES / "chinook_prose"
PINNED = Path(__file__).resolve().parent / "fixtures" / "text_facts_fixture_criteria" / "criteria-941ffd8.jsonl"


def jsonl(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


CONFIG = json.loads((PROSE / "scoring" / "text-facts.json").read_text(encoding="utf-8"))
REFERENCES = {r["case_id"]: r for r in jsonl(PROSE / "references" / "chinook-prose-references.jsonl")}
ROWS = {(row["source"], row["case_id"]): row["criteria"] for row in jsonl(PINNED)}


def texts() -> dict:
    """{(source, case_id): (text, declared outcome)} of every fixture answer line and every reference text."""
    found = {}
    for path in sorted((PROSE / "fixtures").glob("*.jsonl")):
        for line in jsonl(path):
            found[(f"fixtures/{path.name}", line["case_id"])] = (line["raw_answer"], line.get("outcome"))
    for case_id, reference in REFERENCES.items():
        if "reference_text" in reference:
            found[("reference_text", case_id)] = (reference["reference_text"], None)
    return found


TEXTS = texts()


def test_the_pinned_table_has_one_row_per_fixture_line_and_reference_text():
    assert set(ROWS) == set(TEXTS) and len(ROWS) == 96


@pytest.mark.parametrize("key", sorted(TEXTS), ids=lambda key: f"{key[0]}:{key[1]}")
def test_each_fixture_line_gives_the_criteria_it_gave_at_941ffd8(key):
    text, outcome = TEXTS[key]
    criteria = text_facts.apply(text, REFERENCES[key[1]], CONFIG, outcome)["criteria"]
    assert {c["name"]: [c["state"], c["score"], c["reason"]] for c in criteria} == ROWS[key]
