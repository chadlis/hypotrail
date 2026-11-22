"""`status --json` says what happened to the evidence of a recorded Decision: `evidence_change`.

"The label is computed over the later Assessments of the same Observation set and Scorer id" and "A later Assessment counts as rescored or changed
only when its `rescoring.earlier_assessment_id` is the cited Assessment or one later than it." (D-077 on chadlis/hypotrail#75, Q3). The key sits
beside `applies` and `reasons`, which keep their meaning. Nothing is stored. No model is called.
"""

import json
from pathlib import Path

import pytest
from _report_tracks import TRACKS as REPORT_TRACKS
from _review_helpers import (
    TRACKS,
    assessment_file,
    comparison_file,
    compare,
    copy_of,
    decide,
    decision_row,
    exposure_count,
    files,
    status,
)

from hypotrail.core import canonical, contracts

EVIDENCE_KEYS = {"state", "lines"}
LINE_KEYS = {"assessment_id", "comparison_id", "role", "latest_assessment_id", "state", "changed_item_count", "metrics"}
METRIC_KEYS = {"id", "cited", "latest"}


@pytest.fixture(scope="module")
def compared(tmp_path_factory):
    """{track: (Study, {"control", "candidate", "comparison"})}: a Comparison of two Assessments of revision 1, built once per module."""
    built = {}
    for name, track in TRACKS.items():
        study, control, candidate, comparison = track.compared(tmp_path_factory.mktemp(f"evidence-{name}"))
        built[name] = (study, {"control": control, "candidate": candidate, "comparison": comparison})
    return built


def copy(compared, name, tmp_path):
    study, ids = compared[name]
    return copy_of(study, tmp_path / name / "study"), dict(ids)


def read(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rewrite(path, edit) -> dict:
    record = read(path)
    edit(record)
    contracts.validate(record)
    Path(path).write_bytes(canonical.dumps(record))
    return record


def line_of(row, assessment_id) -> dict:
    [line] = [line for line in row["evidence_change"]["lines"] if line["assessment_id"] == assessment_id]
    return line


def assert_line_shape(study, line):
    """The key sets of a line and of its `metrics` entries, and each `cited` and `latest` read from the two records on disk."""
    assert set(line) == LINE_KEYS
    anchor, latest = read(assessment_file(study, line["assessment_id"])), read(assessment_file(study, line["latest_assessment_id"]))
    assert [entry["id"] for entry in line["metrics"]] == [metric["id"] for metric in anchor["metrics"]]
    for entry, metric in zip(line["metrics"], anchor["metrics"]):
        assert set(entry) == METRIC_KEYS
        assert entry["cited"] == metric["value"]
        assert entry["latest"] == next(m["value"] for m in latest["metrics"] if m["id"] == metric["id"])


def read_twice(study, decision_id) -> dict:
    """The Decision's row of the second of two reads, each read leaving every file of the Study as it was and the Write sequence the same."""
    before = files(study)
    first = status(study)
    assert files(study) == before
    second = status(study)
    assert files(study) == before
    assert first["write_sequence"] == second["write_sequence"]
    return next(row for row in second["decisions"] if row["decision_id"] == decision_id)


# --- the key: null when nothing cited or reached has a later Assessment ------------------------------------------------------------


@pytest.mark.parametrize("cites", ["an Assessment", "a Comparison alone", "an Attempt alone"])
def test_a_decision_whose_cited_or_reached_assessments_have_no_later_assessment_holds_evidence_change_null(cites, compared, tmp_path):
    study, ids = copy(compared, "bike", tmp_path)
    attempt = next(p.parent.name for p in study.glob("attempts/*/observation_set.json") if read(p)["observation_set_id"] == ids["control"]["observation_set_id"])
    cited = {"an Assessment": ids["control"]["assessment_id"], "a Comparison alone": ids["comparison"]["comparison_id"], "an Attempt alone": attempt}[cites]
    decision = decide(study, [cited], request_id="d-1")
    row = decision_row(study, decision["decision_id"])
    assert "evidence_change" in row and row["evidence_change"] is None


# --- the matrix: three states and the guard, on a Comparison alone per Track and on an Assessment ------------------------------------------


MATRIX_CONTEXTS = [("bike", "comparison"), ("chinook", "comparison"), ("bike", "assessment")]
MATRIX_ROWS = ["result changed", "evidence rescored", "repeated", "the guard"]


@pytest.mark.parametrize("row_name", MATRIX_ROWS)
@pytest.mark.parametrize(("name", "cites"), MATRIX_CONTEXTS, ids=["bike-comparison", "chinook-comparison", "bike-assessment"])
def test_the_line_state_of_each_row_of_the_matrix_follows_the_later_assessment_and_the_guard(name, cites, row_name, compared, tmp_path):
    track = TRACKS[name]
    study, ids = copy(compared, name, tmp_path)
    control, candidate = ids["control"], ids["candidate"]
    comparison = ids["comparison"]
    if row_name == "the guard":  # the anchor is an Assessment on References R2; a later one on R2 compares itself with the one on R1
        track.revise_an_assessed_item(study, tmp_path)
        control = track.assess_again(study, control)
        if cites == "comparison":
            candidate = track.assess_again(study, candidate)
            comparison = compare(study, control["assessment_id"], candidate["assessment_id"])
    cited = [comparison["comparison_id"]] if cites == "comparison" else [control["assessment_id"]]
    decision = decide(study, cited, request_id="d-matrix")
    [decision_file] = [p for p in study.glob("decisions/*.json") if read(p)["decision_id"] == decision["decision_id"]]
    recorded = decision_file.read_bytes()
    comparison_bytes = comparison_file(study, comparison["comparison_id"]).read_bytes()

    if row_name == "result changed":
        repeat = None
        if (name, cites) == ("bike", "comparison"):
            repeat = track.assess_again(study, control)
        track.revise_an_assessed_item(study, tmp_path)
        later = track.assess_again(study, control)
        assert later["rescoring"] is not None and later["rescoring"]["changed_items"]
        assert later["rescoring"]["earlier_assessment_id"] == (repeat or control)["assessment_id"]  # the anchor, or one later than it
        expected = {control["assessment_id"]: "result_changed"}
        if repeat is not None:
            candidate_later = track.assess_again(study, candidate)
            assert candidate_later["rescoring"]["changed_items"] and candidate_later["rescoring"]["earlier_assessment_id"] == candidate["assessment_id"]  # the anchor
            expected[candidate["assessment_id"]] = "result_changed"
    elif row_name == "evidence rescored":
        track.revise_no_assessed_item(study, tmp_path)
        later = track.assess_again(study, control)
        assert later["rescoring"] is not None and later["rescoring"]["changed_items"] == []
        assert later["rescoring"]["earlier_assessment_id"] == control["assessment_id"]
        expected = {control["assessment_id"]: "evidence_rescored"}
    elif row_name == "repeated":
        later = track.assess_again(study, control)
        assert later["rescoring"] is None
        expected = {control["assessment_id"]: "repeated"}
    else:
        later = track.assess_again(study, control)
        assert later["rescoring"] is not None and later["rescoring"]["changed_items"]
        earlier = later["rescoring"]["earlier_assessment_id"]
        assert earlier != control["assessment_id"] and earlier == ids["control"]["assessment_id"]  # the Assessment on R1, earlier than the anchor
        expected = {control["assessment_id"]: "repeated"}

    row = read_twice(study, decision["decision_id"])
    change = row["evidence_change"]
    assert set(change) == EVIDENCE_KEYS
    assert {line["assessment_id"]: line["state"] for line in change["lines"]} == expected
    assert change["state"] == expected[control["assessment_id"]]
    for line in change["lines"]:
        assert_line_shape(study, line)
    if row_name == "the guard":
        assert line_of(row, control["assessment_id"])["changed_item_count"] == 0
    if row_name == "repeated" and cites == "assessment":  # a repeat still outdates the Decision; `repeated` is what says nothing changed
        assert (row["applies"], row["reasons"]) == (False, [{"reason": "assessment_superseded", "id": later["assessment_id"]}])
    if row_name == "result changed":  # recorded before `init --new-revision`: `revision_changed` stands beside the state
        assert {"reason": "revision_changed", "id": read(study / "study.json")["revision"]} in row["reasons"]
        assert comparison_file(study, comparison["comparison_id"]).read_bytes() == comparison_bytes
        entry = next(e for e in status(study)["comparisons"] if e["comparison_id"] == comparison["comparison_id"])
        assert entry["delta"] == read(comparison_file(study, comparison["comparison_id"]))["delta"]
    assert decision_file.read_bytes() == recorded


# --- the lines, their order and the state of the Decision ----------------------------------------------------------------------------------


@pytest.mark.parametrize("both", [True, False], ids=["both sides", "one side"])
@pytest.mark.parametrize("name", list(TRACKS))
def test_a_decision_on_a_comparison_alone_has_one_line_per_side_with_a_later_assessment_the_control_first(name, both, compared, tmp_path):
    track = TRACKS[name]
    study, ids = copy(compared, name, tmp_path)
    decision = decide(study, [ids["comparison"]["comparison_id"]], request_id="d-1")
    if both:
        repeat = track.assess_again(study, ids["candidate"])  # the Candidate repeats
    track.revise_an_assessed_item(study, tmp_path)
    changed = track.assess_again(study, ids["control"])  # the Control's result changed
    row = decision_row(study, decision["decision_id"])
    lines = [(line["assessment_id"], line["comparison_id"], line["role"], line["latest_assessment_id"], line["state"]) for line in row["evidence_change"]["lines"]]
    expected = [(ids["control"]["assessment_id"], ids["comparison"]["comparison_id"], "control", changed["assessment_id"], "result_changed")]
    if both:
        expected.append((ids["candidate"]["assessment_id"], ids["comparison"]["comparison_id"], "candidate", repeat["assessment_id"], "repeated"))
    assert lines == expected
    assert row["evidence_change"]["state"] == "result_changed"


def cited_order(row, *ids) -> list:
    return sorted(ids, key=row["cited_ids"].index)


@pytest.mark.parametrize("case", ["a Comparison and its two Assessments", "two Assessments and no Comparison", "two Comparisons naming one Assessment", "a Comparison and another Assessment"])
def test_the_lines_are_in_the_order_of_first_appearance_through_the_cited_ids(case, compared, tmp_path):
    track = TRACKS["bike"]
    study, ids = copy(compared, "bike", tmp_path)
    control, candidate, comparison = ids["control"]["assessment_id"], ids["candidate"]["assessment_id"], ids["comparison"]["comparison_id"]
    if case == "a Comparison and its two Assessments":
        cited = [comparison, control, candidate]
    elif case == "two Assessments and no Comparison":
        cited = [control, candidate]
    elif case == "two Comparisons naming one Assessment":
        other = compare(study, control, candidate)["comparison_id"]
        cited = [comparison, other]
    else:
        from _assess_helpers import observation_set_id
        from _study_helpers import run_ml

        code, payload, err = run_ml(study, "seasonal_7", "dev", "a-third-attempt")
        assert code == 0, (payload, err)
        third = track.assess_again(study, {"observation_set_id": observation_set_id(study, payload["attempt"])})
        cited = [comparison, third["assessment_id"]]
    decision = decide(study, cited, request_id="d-1")
    for assessment_id in {control, candidate} | ({third["assessment_id"]} if case == "a Comparison and another Assessment" else set()):
        track.assess_again(study, read(assessment_file(study, assessment_id)))
    row = decision_row(study, decision["decision_id"])
    lines = [(line["assessment_id"], line["comparison_id"], line["role"]) for line in row["evidence_change"]["lines"]]
    if case == "a Comparison and its two Assessments":
        walk = []
        for cited_id in row["cited_ids"]:
            for reached in ([control, candidate] if cited_id == comparison else [cited_id]):
                if reached not in walk:
                    walk.append(reached)
        assert lines == [(a, comparison, "control" if a == control else "candidate") for a in walk]
    elif case == "two Assessments and no Comparison":
        assert lines == [(a, None, None) for a in cited_order(row, control, candidate)]
    elif case == "two Comparisons naming one Assessment":
        first = cited_order(row, comparison, other)[0]
        assert lines == [(control, first, "control"), (candidate, first, "candidate")]
    else:
        expected = {comparison: [(control, comparison, "control"), (candidate, comparison, "candidate")], third["assessment_id"]: [(third["assessment_id"], None, None)]}
        assert lines == [line for cited_id in row["cited_ids"] for line in expected[cited_id]]


@pytest.mark.parametrize(
    ("control_state", "candidate_state"), [("result_changed", "evidence_rescored"), ("result_changed", "repeated"), ("evidence_rescored", "repeated")]
)
def test_the_state_of_the_decision_is_the_strongest_state_of_its_lines(control_state, candidate_state, compared, tmp_path):
    track = TRACKS["bike"]
    study, ids = copy(compared, "bike", tmp_path)
    decision = decide(study, [ids["comparison"]["comparison_id"]], request_id="d-1")
    if candidate_state == "evidence_rescored":
        track.revise_no_assessed_item(study, tmp_path, name="first")
        track.assess_again(study, ids["candidate"])
    else:
        track.assess_again(study, ids["candidate"])
    if control_state == "result_changed":
        track.revise_an_assessed_item(study, tmp_path)
    else:
        track.revise_no_assessed_item(study, tmp_path, name="second")
    track.assess_again(study, ids["control"])
    change = decision_row(study, decision["decision_id"])["evidence_change"]
    assert [line["state"] for line in change["lines"]] == [control_state, candidate_state]
    assert change["state"] == control_state


# --- what a line holds ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(TRACKS))
def test_the_changed_item_count_is_the_number_of_distinct_item_ids_the_counted_later_assessments_changed(name, compared, tmp_path):
    track = TRACKS[name]
    study, ids = copy(compared, name, tmp_path)
    decision = decide(study, [ids["comparison"]["comparison_id"]], request_id="d-1")
    track.revise_an_assessed_item(study, tmp_path)
    later = track.assess_again(study, ids["control"])
    changed = later["rescoring"]["changed_items"]
    if name == "chinook":  # one Episode changed on two Criteria
        assert len(changed) == 2 and len({c["item_id"] for c in changed}) == 1
    line = line_of(decision_row(study, decision["decision_id"]), ids["control"]["assessment_id"])
    assert line["changed_item_count"] == len({c["item_id"] for c in changed})
    assert_line_shape(study, line)
    assert len(line["metrics"]) == {"bike": 1, "chinook": 2}[name]


@pytest.mark.parametrize("edit", ["the Metric's id renamed", "the Metric's value null"])
def test_latest_is_null_when_the_latest_record_holds_no_metric_of_that_id_or_its_value_is_null(edit, compared, tmp_path):
    track = TRACKS["bike"]
    study, ids = copy(compared, "bike", tmp_path)
    decision = decide(study, [ids["control"]["assessment_id"]], request_id="d-1")
    later = track.assess_again(study, ids["control"])

    def change(record):
        if edit == "the Metric's id renamed":
            record["metrics"][0]["id"] = "renamed"
        else:
            record["metrics"][0].update(value=None, status="unscored", reason="no_scored_item")

    rewrite(assessment_file(study, later["assessment_id"]), change)
    [entry] = line_of(decision_row(study, decision["decision_id"]), ids["control"]["assessment_id"])["metrics"]
    assert entry == {"id": ids["control"]["metrics"][0]["id"], "cited": ids["control"]["metrics"][0]["value"], "latest": None}


# --- records the label cannot read whole -------------------------------------------------------------------------------------------------


def test_a_later_assessment_whose_record_holds_no_rescoring_key_counts_as_a_repeat(compared, tmp_path):
    track = TRACKS["bike"]
    study, ids = copy(compared, "bike", tmp_path)
    decision = decide(study, [ids["control"]["assessment_id"]], request_id="d-1")
    track.revise_no_assessed_item(study, tmp_path)
    later = track.assess_again(study, ids["control"])
    assert later["rescoring"] is not None
    rewrite(assessment_file(study, later["assessment_id"]), lambda record: record.pop("rescoring"))  # the key is not required
    assert line_of(decision_row(study, decision["decision_id"]), ids["control"]["assessment_id"])["state"] == "repeated"


def test_a_side_of_a_cited_comparison_that_the_study_does_not_hold_adds_no_line(compared, tmp_path):
    import shutil

    track = TRACKS["bike"]
    study, ids = copy(compared, "bike", tmp_path)
    decision = decide(study, [ids["comparison"]["comparison_id"]], request_id="d-1")
    track.assess_again(study, ids["control"])
    shutil.rmtree(study / "assessments" / ids["candidate"]["assessment_id"])
    lines = decision_row(study, decision["decision_id"])["evidence_change"]["lines"]
    assert [line["assessment_id"] for line in lines] == [ids["control"]["assessment_id"]]


def test_with_no_roles_in_the_comparison_record_the_left_line_is_the_control_and_the_right_one_the_candidate(compared, tmp_path):
    track = TRACKS["bike"]
    study, ids = copy(compared, "bike", tmp_path)
    rewrite(comparison_file(study, ids["comparison"]["comparison_id"]), lambda record: record.pop("roles"))
    decision = decide(study, [ids["comparison"]["comparison_id"]], request_id="d-1")
    track.assess_again(study, ids["control"])
    track.assess_again(study, ids["candidate"])
    lines = decision_row(study, decision["decision_id"])["evidence_change"]["lines"]
    assert [(line["assessment_id"], line["role"]) for line in lines] == [(ids["comparison"]["left_assessment_id"], "control"), (ids["comparison"]["right_assessment_id"], "candidate")]


# --- `public_check` ---------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("track", ["bike", "chinook"])
def test_on_public_check_a_line_holds_only_metric_values_of_the_records_and_reading_it_records_no_exposure(track, tmp_path):
    study, _, assessment_ids, comparison = REPORT_TRACKS[track].public_world(tmp_path)
    decision = decide(study, [comparison["comparison_id"]], request_id="d-1")
    control = read(assessment_file(study, comparison["roles"]["control_assessment_id"]))
    TRACKS[track].assess_again(study, control)
    count = exposure_count(study)
    row = decision_row(study, decision["decision_id"])
    assert exposure_count(study) == count
    assert set(row["evidence_change"]) == EVIDENCE_KEYS
    [line] = row["evidence_change"]["lines"]
    assert_line_shape(study, line)
