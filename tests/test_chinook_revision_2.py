"""The larger Chinook Workload (#233): 92 Cases and References appended to the kit's, their review record, and Protocol revision 2.

The two writers' answers, the review record and the References are read from the repository; every SQL text runs on the locked
database through the SQL tool's own read-only path (`sql_tool.run_query`). No model is called.
"""

import json
import re
import unicodedata
from pathlib import Path

import pytest
from _agent_helpers import CHINOOK, DATABASE, REFERENCES, read_jsonl
from _chinook_helpers import FIXTURE, REVISION_ONE, fixture_population, import_agent, init_chinook, references_id, revision_one_examples
from _revision_helpers import entry_of, error_of, new_revision, snapshot_files, spec_of
from _run_agent_helpers import fixture
from _study_helpers import run_json

from hypotrail.agentic import sql_tool
from hypotrail.core.answer_scoring import score_object
from hypotrail.core.data import open_sqlite_readonly

DEV = CHINOOK / "cases" / "chinook-dev.jsonl"
PUBLIC_CHECK = CHINOOK / "cases" / "chinook-public-check.jsonl"
REVIEW = CHINOOK / "references" / "chinook-references-2.review.jsonl"
POOL = CHINOOK / "review" / "candidate-pool.jsonl"
SCHEMA_CODE = {"needs_clarification": "criterion_undefined", "not_answerable": "field_not_available"}
OUTCOMES = {"agreed", "settled_by_third_reader", "rewritten", "withdrawn"}
SETTLED = {"agreed", "settled_by_third_reader"}
NEW_QUALITIES = {"two_writers_agreed", "two_writers_third_reader"}


def lines_of(path) -> list[str]:
    return Path(path).read_text(encoding="utf-8").splitlines()


def header_and_candidates():
    header, *candidates = read_jsonl(REVIEW)
    assert header["record"] == "header" and all(line["record"] == "candidate" for line in candidates)
    return header, candidates


# --- append-only: the kit's lines are those of the frozen revision 1 -----------------------------------------------------------

KEPT_LINES = [
    ("cases/chinook-dev.jsonl", 8),
    ("cases/chinook-public-check.jsonl", 12),
    ("references/chinook-references.jsonl", 20),
]


@pytest.mark.parametrize(
    "relative, number", [(relative, number) for relative, count in KEPT_LINES for number in range(count)], ids=lambda value: str(value)
)
def test_each_kit_line_of_the_cases_and_references_files_is_byte_identical_to_the_frozen_revision_1(relative, number):
    live = (CHINOOK / relative).read_bytes().split(b"\n")
    frozen = (REVISION_ONE / relative).read_bytes().split(b"\n")
    assert len(frozen) == dict(KEPT_LINES)[relative] + 1 and frozen[-1] == b""  # the frozen file is the kit's, ending in a newline
    assert live[number] == frozen[number], (relative, number + 1)


def test_public_check_holds_its_twelve_cases_of_the_kit_and_nothing_more():
    assert (CHINOOK / "cases" / "chinook-public-check.jsonl").read_bytes() == (REVISION_ONE / "cases" / "chinook-public-check.jsonl").read_bytes()
    assert len(lines_of(PUBLIC_CHECK)) == 12


# --- the set ---------------------------------------------------------------------------------------------------------------------


def test_dev_holds_d01_to_d100_once_each_in_order():
    assert [case["case_id"] for case in read_jsonl(DEV)] == [f"D{number:02d}" for number in range(1, 101)]


def test_the_dev_references_count_76_12_12_by_status_or_80_10_10_with_the_fallback_written_in_the_review_record():
    dev = {case["case_id"] for case in read_jsonl(DEV)}
    counts = {status: 0 for status in ("answered", "needs_clarification", "not_answerable")}
    for reference in read_jsonl(REFERENCES):
        if reference["case_id"] in dev:
            counts[reference["status"]] += 1
    header, _ = header_and_candidates()
    if counts != {"answered": 76, "needs_clarification": 12, "not_answerable": 12}:
        assert counts == {"answered": 80, "needs_clarification": 10, "not_answerable": 10}
        assert "80 / 10 / 10" in header["split"] and "not used" not in header["split"]
    else:
        assert "76 / 12 / 12" in header["split"]


@pytest.mark.parametrize("case", read_jsonl(DEV) + read_jsonl(PUBLIC_CHECK), ids=lambda case: case["case_id"])
def test_every_case_of_both_partitions_has_exactly_one_reference(case):
    assert [r["case_id"] for r in read_jsonl(REFERENCES)].count(case["case_id"]) == 1


def test_every_reference_names_a_case_of_one_partition():
    cases = {case["case_id"] for case in read_jsonl(DEV) + read_jsonl(PUBLIC_CHECK)}
    assert {r["case_id"] for r in read_jsonl(REFERENCES)} <= cases


@pytest.mark.parametrize("case", read_jsonl(DEV)[8:], ids=lambda case: case["case_id"])
def test_each_new_case_has_the_keys_split_and_dataset_of_the_kits_cases(case):
    kit = read_jsonl(DEV)[0]
    assert set(case) == set(kit)
    assert (case["split"], case["dataset_id"], case["dataset_sha256"]) == ("dev", kit["dataset_id"], kit["dataset_sha256"])


# --- the review record ----------------------------------------------------------------------------------------------------------


def table_through_the_tool(sql):
    """(columns, rows) of `sql` through the SQL tool, or None when the tool refuses or truncates it."""
    result = sql_tool.run_query(DATABASE, sql)
    if result["error"] is not None or result["truncated"]:
        return None
    return {"columns": result["columns"], "rows": result["rows"]}


def table_outside_the_authorizer(sql):
    connection = open_sqlite_readonly(DATABASE)
    try:
        cursor = connection.execute(sql)
        return {"columns": [d[0] for d in cursor.description], "rows": [list(row) for row in cursor.fetchall()]}
    finally:
        connection.close()


def same_table(first, second):
    """Whether two tables are equal by `score_object`'s `exact_table` rules: columns in order, rows in order, tolerance 0."""
    reference = {"status": "answered", "reason_code": None, "unit": None, "numeric_absolute_tolerance": 0, **first}
    answer = {"status": "answered", "reason_code": None, "unit": None, "evidence": [], **second}
    components = score_object(answer, reference)["components"]
    return components["columns"] and components["rows"]


def test_the_review_record_has_a_header_then_one_line_per_candidate_of_the_pool_in_pool_order():
    header, candidates = header_and_candidates()
    pool = read_jsonl(POOL)
    assert [line["candidate_id"] for line in candidates] == [candidate["candidate_id"] for candidate in pool]
    assert [line["case"] for line in candidates] == pool
    assert "67 of the 82 answered SQL texts are byte-identical between the two writers" in header["shared_model"]


@pytest.mark.parametrize("line", header_and_candidates()[1], ids=lambda line: line["candidate_id"])
def test_each_review_line_says_whether_the_two_answers_agree_as_both_sql_texts_executed_again_say(line):
    """Both writers' SQL texts run again through the SQL tool, and the agreement is recomputed from the two answers.

    A line whose SQL texts the tool refuses carries both tables read outside the authorizer, which must be equal, and a rewritten
    `oracle_sql` that gives that same table through the tool.
    """
    a, b = line["writer_a"], line["writer_b"]
    assert line["outcome"] in OUTCOMES
    agree = a["status"] == b["status"] and a["reason_code"] == b["reason_code"]
    if a["status"] == b["status"] == "answered":
        table_a, table_b = table_through_the_tool(a["sql"]), table_through_the_tool(b["sql"])
        if table_a is None or table_b is None:
            outside = line["tables_outside_authorizer"]
            assert outside["writer_a"] == table_outside_the_authorizer(a["sql"])
            assert outside["writer_b"] == table_outside_the_authorizer(b["sql"])
            equal = same_table(outside["writer_a"], outside["writer_b"])
            assert outside["equal"] is equal
            assert table_through_the_tool(line["rewritten_oracle_sql"]) == outside["writer_a"]
        else:
            equal = same_table(table_a, table_b)
        assert line["tables_equal"] is equal
        agree = agree and equal
    else:
        assert line["tables_equal"] is None
    if line["outcome"] == "withdrawn":
        assert line["case_id"] is None and line["withdrawal_reason"]  # an ambiguous candidate is withdrawn with its reason
    elif agree:
        assert line["outcome"] == "agreed" and line["third_reader"] is None
    else:
        assert line["outcome"] != "agreed" and line["third_reader"] is not None


def test_every_new_case_is_the_case_id_of_exactly_one_settled_review_line_whose_case_is_the_cases_files_line():
    _, candidates = header_and_candidates()
    for case in read_jsonl(DEV)[8:]:
        [line] = [line for line in candidates if line["case_id"] == case["case_id"]]
        assert line["outcome"] in SETTLED, case["case_id"]
        assert {key: case[key] for key in line["case"] if key != "candidate_id"} == {
            key: value for key, value in line["case"].items() if key != "candidate_id"
        }
    named = [line["case_id"] for line in candidates if line["case_id"] is not None]
    assert sorted(named) == sorted(case["case_id"] for case in read_jsonl(DEV)[8:])


def new_references():
    return [r for r in read_jsonl(REFERENCES) if r["reference_version"] == "chinook-references/2"]


@pytest.mark.parametrize("reference", new_references(), ids=lambda reference: reference["case_id"])
def test_each_new_reference_is_the_table_of_its_oracle_sql_and_the_settled_status_of_its_review_line(reference):
    """The status is the settled one; the `reason_code` is the code the Workload's answer schema fixes for that status, not the writers'
    own code, which the review record keeps whole."""
    _, candidates = header_and_candidates()
    [line] = [line for line in candidates if line["case_id"] == reference["case_id"]]
    settled = line["writer_a"] if line["third_reader"] is None else line["third_reader"]["answer"]
    assert reference["status"] == settled["status"]
    assert reference["reason_code"] == SCHEMA_CODE.get(reference["status"])
    if reference["status"] == "answered":
        assert reference["oracle_sql"] == line.get("rewritten_oracle_sql", settled["sql"])
        assert table_through_the_tool(reference["oracle_sql"]) == {"columns": reference["columns"], "rows": reference["rows"]}
        assert reference["unit"] == line["case"]["unit"]
    else:
        assert (reference["oracle_sql"], reference["columns"], reference["rows"], reference["unit"]) == (None, [], [], None)


def test_each_new_reference_has_the_keys_of_the_kits_and_names_the_two_writers_review_as_its_quality():
    kit = read_jsonl(REFERENCES)[0]
    for reference in new_references():
        assert set(reference) == set(kit), reference["case_id"]
        assert reference["review_required_before_live"] is True, reference["case_id"]
        assert reference["reference_quality"] in NEW_QUALITIES, reference["case_id"]
        assert reference["reference_quality"] != "sql_executed_and_anchor_checked", reference["case_id"]


TWO_DECIMALS = re.compile(r"\b2 decimal places\b|\bdeux décimales\b")


def all_cases():
    return {case["case_id"]: case for case in read_jsonl(DEV) + read_jsonl(PUBLIC_CHECK)}


def test_every_reference_whose_question_asks_for_two_decimals_carries_half_a_unit_of_the_second_decimal_as_its_tolerance():
    cases = all_cases()
    asking = [r for r in read_jsonl(REFERENCES) if TWO_DECIMALS.search(cases[r["case_id"]]["question"])]
    assert "E08" in {r["case_id"] for r in asking}
    assert {r["case_id"]: r["numeric_absolute_tolerance"] for r in asking} == {r["case_id"]: 0.005 for r in asking}


def folded(text):
    """`text` compared without case and without accents: casefolded, with its combining marks removed."""
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(c))


def fold_collation(first, second):
    return (folded(first) > folded(second)) - (folded(first) < folded(second))


def outer_order_by_folded(sql):
    """`sql` with each term of its last ORDER BY compared without case and accents (a collation applies to text only)."""
    match = list(re.finditer(r"\bORDER\s+BY\b", sql, re.I))[-1]
    head, tail = sql[: match.end()], sql[match.end():]
    limit = re.search(r"\bLIMIT\b", tail, re.I)
    clause, rest = (tail[: limit.start()], tail[limit.start():]) if limit else (tail, "")
    terms = []
    for term in clause.split(","):
        direction = re.search(r"\s+(ASC|DESC)\s*$", term, re.I)
        expression = term[: direction.start()] if direction else term.rstrip()
        terms.append(f"{expression} COLLATE FOLD{direction.group(0) if direction else ''}")
    return head + ",".join(terms) + " " + rest


def rows_with_folded_order(sql):
    connection = open_sqlite_readonly(DATABASE)
    try:
        connection.create_collation("FOLD", fold_collation)
        return [list(row) for row in connection.execute(outer_order_by_folded(sql)).fetchall()]
    finally:
        connection.close()


def ordered_by_text(reference):
    sql = reference["oracle_sql"] or ""
    return re.search(r"\bORDER\s+BY\b", sql, re.I) is not None and any(isinstance(cell, str) for row in reference["rows"] for cell in row)


@pytest.mark.parametrize(
    "reference", [r for r in new_references() if r["status"] == "answered" and ordered_by_text(r)], ids=lambda reference: reference["case_id"]
)
def test_each_new_reference_ordered_with_text_has_the_same_rows_under_binary_and_case_and_accent_insensitive_order(reference):
    """The scorer compares rows in order, and a question that fixes no text sort rule leaves case and accents open; such a question must
    have the same rows either way, or state the rule."""
    question = all_cases()[reference["case_id"]]["question"].lower()
    if "case-sensitive" in question or "binary order" in question:
        return
    assert rows_with_folded_order(reference["oracle_sql"]) == reference["rows"], reference["case_id"]


# --- revision 2 for a Study made before -----------------------------------------------------------------------------------------


def kit_study(tmp_path):
    """A Chinook Study made by `init` on the frozen revision-1 Workload, with one Import assessed under revision 1."""
    examples = revision_one_examples(tmp_path)
    study, _ = init_chinook(tmp_path, examples=examples)
    code, payload, err = import_agent(study, FIXTURE, fixture_population(tmp_path), "kit-import", "--examples-dir", examples)
    assert code == 0, (payload, err)
    folder = Path(study) / "attempts" / payload["attempt"]["attempt_id"]
    observations = json.loads((folder / "observation_set.json").read_text(encoding="utf-8"))["observation_set_id"]
    code, payload, err = run_json(
        "assess", "--study", study, "--observations", observations, "--scorer", "chinook_contract_v1", "--references", references_id(study),
        "--examples-dir", examples,
    )
    assert code == 0, (payload, err)
    return study, payload["assessment"]["assessment_id"]


def test_a_study_of_revision_1_refuses_run_agent_and_import_agent_under_the_new_workload_and_writes_nothing(tmp_path):
    study, _ = kit_study(tmp_path)
    before = snapshot_files(study)
    for name, result in (
        ("run agent", fixture(study, "plain", "after-run")),
        ("import agent", import_agent(study, FIXTURE, fixture_population(tmp_path, name="again.json"), "after-import")),
    ):
        code, payload, _ = result
        assert (code, error_of(payload)["code"]) == (3, "PROTOCOL_CHANGED"), name
        assert snapshot_files(study) == before, name


def test_init_new_revision_under_the_new_workload_makes_revision_2_and_keeps_revision_1_and_its_artifacts_byte_identical(tmp_path):
    study, _ = kit_study(tmp_path)
    first = spec_of(study)
    first_bytes = (Path(study) / "study.json").read_bytes()
    before = snapshot_files(study)
    code, payload, err = new_revision(study)
    assert code == 0, (payload, err)
    second = spec_of(study)
    assert second["revision_number"] == 2 and second["previous_revision"] == first["revision"]
    assert (Path(study) / "revisions" / "1" / "study.json").read_bytes() == first_bytes
    after = snapshot_files(study)
    assert {path: after[path] for path in before if path != "study.json"} == {path: d for path, d in before.items() if path != "study.json"}
    old, new = entry_of(first, "references"), entry_of(second, "references")
    assert (old["version"], new["version"]) == (1, 2) and old["ref"]["path"] != new["ref"]["path"]
    assert old["ref"]["path"] in after and new["ref"]["path"] in after
    assert (Path(study) / new["ref"]["path"]).read_bytes() == REFERENCES.read_bytes()


def test_an_assessment_recorded_under_revision_1_is_unchanged_on_disk_after_revision_2(tmp_path):
    study, assessment = kit_study(tmp_path)
    folder = Path(study) / "assessments" / assessment
    kept = snapshot_files(folder)
    assert kept
    code, payload, err = new_revision(study)
    assert code == 0, (payload, err)
    assert snapshot_files(folder) == kept
