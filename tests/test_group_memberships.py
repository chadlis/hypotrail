"""The group map of a Study: `memberships.csv` gains a `group` column when a Case of the Workload declares one, and under the `group`
resampling unit a Case without `group` is refused at `init` and `init --new-revision` before anything is written."""

import csv
import io
import json
import shutil
from pathlib import Path

import pytest
from _revision_helpers import corrected_chinook_references, new_revision, snapshot_files, spec_of
from _study_helpers import EXAMPLES, examples_copy, run_json, sha256

from hypotrail.core.errors import EXIT_INVALID_INPUT

PROSE_CASES = {"dev": "cases/chinook-prose-dev.jsonl", "public_check": "cases/chinook-prose-public-check.jsonl"}
# The bytes of `memberships.csv` at main 01f53b2, before the group column existed.
MEMBERSHIPS_AT_MAIN = {
    "chinook": "580cd77bff2a04f5951f8f3ad510f7f6cf4ef42776cb33287ac91b2d4889d490",
    "bike_day": "204bf1f9317286f8ea0d572d3606fd7d15d4b1e04a5df4d6b14c81a94c7d024b",
}


def jsonl(path) -> list:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path, records) -> None:
    Path(path).write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def prose_copy(tmp_path, *, name, cases=None, references=None) -> Path:
    """A private copy of `examples/` whose chinook_prose Cases (`cases`, by Partition) or References (`references`) may be edited."""
    target = Path(tmp_path) / name
    shutil.copytree(EXAMPLES, target)
    for partition, relative in PROSE_CASES.items():
        if cases is not None:
            path = target / "chinook_prose" / relative
            records = jsonl(path)
            cases(partition, records)
            write_jsonl(path, records)
    if references is not None:
        path = target / "chinook_prose" / "references" / "chinook-prose-references.jsonl"
        records = jsonl(path)
        references(records)
        write_jsonl(path, records)
    return target


def memberships_of(study) -> Path:
    """The memberships file of the Study's current revision."""
    entry = next(e for e in spec_of(study)["artifacts"] if e["ref"]["role"] == "memberships")
    return Path(study) / entry["ref"]["path"]


def expected_prose_rows() -> list:
    rows = [(case["case_id"], partition, case["group"]) for partition, relative in PROSE_CASES.items() for case in jsonl(EXAMPLES / "chinook_prose" / relative)]
    return [list(row) for row in sorted(rows)]


def init(workload, study, *more):
    code, payload, err = run_json("init", "--workload", workload, "--study", study, *more)
    assert code == 0, (payload, err)


def one_more_fact(records):
    records[0]["as_of"] = "2026-11-27"


def revised(tmp_path, workload, study):
    """`init --new-revision` of `study` against a copy of `examples/` whose Protocol for `workload` changed."""
    if workload == "chinook":
        examples = corrected_chinook_references(tmp_path, lambda records: records["D03"].update(rows=[[1300]], reference_version="chinook-references/2"))
    elif workload == "bike_day":

        def corrected_day(table):
            row = next(r for r in table if r["dteday"] == "2012-03-15")
            row["cnt"], row["registered"] = str(int(row["cnt"]) + 1000), str(int(row["registered"]) + 1000)

        examples = examples_copy(tmp_path, rows=corrected_day, name="corrected-day")
    else:
        examples = prose_copy(tmp_path, name="corrected-prose", references=one_more_fact)
    code, payload, err = new_revision(study, "--examples-dir", examples)
    assert code == 0, (payload, err)
    assert spec_of(study)["revision_number"] == 2


@pytest.mark.parametrize("entry", ["init", "init --new-revision"])
def test_chinook_prose_memberships_hold_case_id_partition_and_group(tmp_path, entry):
    study = Path(tmp_path) / "prose"
    init("chinook_prose", study)
    if entry == "init --new-revision":
        revised(tmp_path, "chinook_prose", study)
    rows = list(csv.reader(io.StringIO(memberships_of(study).read_text(encoding="utf-8"))))
    assert rows[0] == ["case_id", "partition", "group"]
    assert rows[1:] == expected_prose_rows()


@pytest.mark.parametrize("entry", ["init", "init --new-revision"])
@pytest.mark.parametrize("workload", ["chinook", "bike_day"])
def test_a_workload_whose_cases_declare_no_group_keeps_the_bytes_of_its_memberships(tmp_path, workload, entry):
    study = Path(tmp_path) / workload
    init(workload, study)
    if entry == "init --new-revision":
        revised(tmp_path, workload, study)
    assert sha256(memberships_of(study)) == MEMBERSHIPS_AT_MAIN[workload]
    assert "group" not in memberships_of(study).read_text(encoding="utf-8").splitlines()[0].split(",")


def without_group_on_d02(partition, records):
    if partition == "dev":
        del next(r for r in records if r["case_id"] == "D02")["group"]


def check_refused(payload, code):
    assert code == EXIT_INVALID_INPUT == 2, payload
    error = payload["error"]
    assert (error["code"], error["stage"], error["details"]) == ("CASE_GROUP_MISSING", "declaration", {"case_id": "D02"})


def test_init_refuses_a_case_without_group_under_the_group_unit_and_writes_nothing(tmp_path):
    examples = prose_copy(tmp_path, name="no-group", cases=without_group_on_d02)
    study = Path(tmp_path) / "refused"
    code, payload, _ = run_json("init", "--workload", "chinook_prose", "--study", study, "--examples-dir", examples)
    check_refused(payload, code)
    assert not study.exists() or not any(study.iterdir())


def test_init_new_revision_refuses_a_case_without_group_under_the_group_unit_and_leaves_the_study_unchanged(tmp_path):
    study = Path(tmp_path) / "prose"
    init("chinook_prose", study)
    before = snapshot_files(study)
    examples = prose_copy(tmp_path, name="no-group", cases=without_group_on_d02)
    code, payload, _ = new_revision(study, "--examples-dir", examples)
    check_refused(payload, code)
    assert snapshot_files(study) == before
