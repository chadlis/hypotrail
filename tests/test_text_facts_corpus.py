"""The blind corpus of the block reader of `text_facts_v1` (#271): each row read directly, then every row through the real commands.

The rows are `tests/fixtures/text_facts_corpus/corpus.jsonl`, written blind to the code, and the rows a ruling of
`rulings.jsonl` adds; a row with a ruling holds the ruling's expectation instead of its own.
"""

import csv
import hashlib
import io
import json
import re
import shutil
from pathlib import Path

import pytest
from _chinook_helpers import episodes_file, import_agent, write_lines
from _study_helpers import EXAMPLES, run_json

from hypotrail.core import text_facts

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "fixtures" / "text_facts_corpus"
CONFIG = json.loads((EXAMPLES / "chinook_prose" / "scoring" / "text-facts.json").read_text(encoding="utf-8"))
KINDS = tuple(CONFIG["identifier_kinds"])


def jsonl(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


RULINGS = {ruling["row"]: ruling for ruling in jsonl(CORPUS / "rulings.jsonl")}
# The corpus rows, then the rows a ruling adds with their own question and answer.
ROWS = {row["row_id"]: row for row in jsonl(CORPUS / "corpus.jsonl")}
ROWS.update({row_id: ruling for row_id, ruling in RULINGS.items() if "answer" in ruling and row_id not in ROWS})


def expectation(row_id: str) -> tuple:
    """({kind: identifier set}, fact number set) the row must give, from its ruling when it has one."""
    source = ROWS[row_id]
    if row_id in RULINGS:
        ruling = RULINGS[row_id]
        assert {"identifiers", "fact_numbers"} <= set(ruling), f"the ruling of {row_id} states no expectation the reader can be held to"
        source = ruling
    identifiers = {kind: set(source["identifiers"].get(kind, [])) for kind in KINDS}
    return identifiers, {float(number) for number in source["fact_numbers"]}


def test_the_two_writer_files_are_kept_byte_for_byte_as_written():
    digests = {name: hashlib.sha256((CORPUS / name).read_bytes()).hexdigest() for name in ("writer-a.jsonl", "writer-b.jsonl")}
    assert digests == {
        "writer-a.jsonl": "863ef2ee8ab2847df611a89831a8cce947d9b415df3208c745cb63b949e5a1e0",
        "writer-b.jsonl": "0c90a03f67c3cfedc1a7f2f6db5215b672aff0cccd08b1512a038c73e800a454",
    }


# Every probe the brief lists, on a line that opens with "- R<round>-<n>".
PROBES = re.findall(r"(?m)^- (R[1-6]-[0-9]+) ", (CORPUS / "brief.md").read_text(encoding="utf-8"))
WRITER_PROBES = {name: {row["probe"] for row in jsonl(CORPUS / name)} for name in ("writer-a.jsonl", "writer-b.jsonl")}


def test_the_brief_lists_the_fifty_one_probes():
    assert len(PROBES) == len(set(PROBES)) == 51


@pytest.mark.parametrize("writer", list(WRITER_PROBES))
@pytest.mark.parametrize("probe", PROBES)
def test_each_probe_of_the_brief_is_a_row_of_each_writer_file(probe, writer):
    assert probe in WRITER_PROBES[writer]


@pytest.mark.parametrize("row_id", list(ROWS))
def test_each_corpus_row_gives_exactly_its_identifiers_per_kind_and_its_fact_numbers(row_id):
    answer = ROWS[row_id]["answer"]
    identifiers, numbers = expectation(row_id)
    found = text_facts.identifiers_in(answer, CONFIG)
    assert {kind: {value for k, value in found if k == kind} for kind in KINDS} == identifiers
    assert set(text_facts.fact_numbers(answer, CONFIG)) == numbers


# --- the corpus through init, import agent, assess and compare (D-170 on chadlis/hypotrail#75: "Test E2E fait foi") -------------


def corpus_reference(row_id: str) -> dict:
    """The test Reference of a row, derived from the row or its ruling and never edited by hand."""
    identifiers, numbers = expectation(row_id)
    facts = []
    for index, number in enumerate(sorted(numbers)):
        whole = number.is_integer()
        facts.append({"fact_id": f"n{index}", "type": "integer" if whole else "decimal", "value": int(number) if whole else number, "tolerance": 0, "rule": "corpus row"})
    return {
        "case_id": row_id,
        "reference_version": "text-facts-corpus/1",
        "expected_outcome": "answered",
        "expected_identifiers": [{"kind": kind, "value": value} for kind in KINDS for value in sorted(identifiers[kind])],
        "expected_facts": facts,
        "as_of": "2026-11-26",
    }


def corpus_workload(tmp_path) -> Path:
    """An examples folder whose `chinook_prose` holds one Case and one test Reference per corpus row, with its data manifest and scoring config."""
    examples = Path(tmp_path) / "examples"
    shutil.copytree(EXAMPLES, examples)
    prose = examples / "chinook_prose"
    declaration = json.loads((prose / "workload.json").read_text(encoding="utf-8"))
    declaration["cases"] = {"dev": "cases/corpus-dev.jsonl"}
    declaration["references"] = "references/corpus-references.jsonl"
    (prose / "workload.json").write_text(json.dumps(declaration, indent=2), encoding="utf-8")
    write_lines(prose / "cases" / "corpus-dev.jsonl", [{"case_id": r, "family": "corpus", "group": r, "question": ROWS[r]["question"]} for r in ROWS])
    write_lines(prose / "references" / "corpus-references.jsonl", [corpus_reference(r) for r in ROWS])
    return examples


def assessed(tmp_path, examples, study, references, name):
    lines = [{"case_id": r, "repeat": 0, "observation_status": "produced", "raw_answer": ROWS[r]["answer"], "outcome": "answered"} for r in ROWS]
    source = write_lines(Path(tmp_path) / f"{name}.jsonl", lines)
    population = episodes_file(tmp_path, [(r, 0) for r in ROWS], name=f"{name}-population.json")
    code, payload, err = import_agent(study, source, population, name, "--examples-dir", examples)
    assert code == 0, (payload, err)
    code, payload, err = run_json("assess", "--study", study, "--observations", payload["observation_set_id"], "--scorer", "text_facts_v1", "--references", references)
    assert code == 0, (payload, err)
    return payload["assessment"]


def test_every_corpus_row_through_init_import_agent_assess_and_compare_finds_its_identifiers_and_facts(tmp_path):
    study = Path(tmp_path) / "corpus"
    examples = corpus_workload(tmp_path)
    code, payload, err = run_json("init", "--workload", "chinook_prose", "--study", study, "--examples-dir", examples)
    assert code == 0, (payload, err)
    references = payload["references_id"]
    control = assessed(tmp_path, examples, study, references, "control")
    candidate = assessed(tmp_path, examples, study, references, "candidate")
    rows = {}
    for row in csv.DictReader(io.StringIO((study / control["per_item_ref"]["path"]).read_text(encoding="utf-8"))):
        rows.setdefault(row["case_id"], {})[row["criterion"]] = row["score"]
    held = ("identifiers_complete", "no_unexpected_identifier", "facts_present")
    failing = {r: {name: rows[r][name] for name in held if rows[r][name] != "true"} for r in ROWS if any(rows[r][name] != "true" for name in held)}
    assert failing == {}
    code, payload, err = run_json("compare", "--study", study, "--control", control["assessment_id"], "--candidate", candidate["assessment_id"])
    assert code == 0, (payload, err)
