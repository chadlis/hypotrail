"""A Decision that cites a Comparison no longer applies when one of its two Assessments has a later Assessment (chadlis/hypotrail#161).

"The read-time rule follows a cited Comparison one hop, to its two Assessments, under a new reason code. `assessment_superseded` keeps its
meaning." (D-077 on chadlis/hypotrail#75, Q6). The new codes are `compared_assessment_superseded` and `compared_assessment_not_held`. Nothing is
stored: the answer is computed when `status` reads the Study. No model is called.
"""

import dataclasses
import json
import shutil
from pathlib import Path

import pytest
from _review_helpers import TRACKS, assessment_file, comparison_file, compare, copy_of, decide, decision_row, files, status

from hypotrail.core import canonical, contracts, scorers

SUPERSEDED, NOT_HELD = "compared_assessment_superseded", "compared_assessment_not_held"
SIDES = ("control", "candidate")


@pytest.fixture(scope="module")
def compared(tmp_path_factory):
    """{track: (Study, {"control", "candidate": Assessment, "comparison": Comparison})}, built once per module."""
    built = {}
    for name, track in TRACKS.items():
        study, control, candidate, comparison = track.compared(tmp_path_factory.mktemp(f"hop-{name}"))
        built[name] = (study, {"control": control, "candidate": candidate, "comparison": comparison})
    return built


def copy(compared, name, tmp_path):
    study, ids = compared[name]
    return copy_of(study, tmp_path / name / "study"), ids


def entry(reason, identifier):
    return {"reason": reason, "id": identifier}


def drop_roles(study, comparison_id):
    path = comparison_file(study, comparison_id)
    record = json.loads(path.read_text(encoding="utf-8"))
    del record["roles"]
    contracts.validate(record)  # `roles` is not required
    path.write_bytes(canonical.dumps(record))


# --- the one hop: a Decision on the Comparison alone, per side and per Track -----------------------------------------------


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("name", list(TRACKS))
def test_a_decision_on_a_comparison_alone_applies_until_a_side_has_a_later_assessment_then_names_it_under_the_hop_reason(name, side, compared, tmp_path):
    track = TRACKS[name]
    study, ids = copy(compared, name, tmp_path)
    decision = decide(study, [ids["comparison"]["comparison_id"]], request_id="d-comparison-only")
    [decision_file] = (study / "decisions").glob("*.json")
    recorded = decision_file.read_bytes()
    before = decision_row(study, decision["decision_id"])
    assert (before["applies"], before["reasons"]) == (True, [])
    later = track.assess_again(study, ids[side])
    tree = files(study)
    first, second = status(study), status(study)
    row = next(r for r in second["decisions"] if r["decision_id"] == decision["decision_id"])
    assert (row["applies"], row["reasons"]) == (False, [entry(SUPERSEDED, later["assessment_id"])])
    assert decision_file.read_bytes() == recorded
    assert first["write_sequence"] == second["write_sequence"]
    assert files(study) == tree


@pytest.mark.parametrize("name", list(TRACKS))
def test_a_decision_on_a_comparison_recorded_after_a_side_already_has_a_later_assessment_does_not_apply_from_its_first_read(name, compared, tmp_path):
    study, ids = copy(compared, name, tmp_path)
    later = TRACKS[name].assess_again(study, ids["control"])
    decision = decide(study, [ids["comparison"]["comparison_id"]], request_id="late-comparison")
    row = decision_row(study, decision["decision_id"])
    assert (row["applies"], row["reasons"]) == (False, [entry(SUPERSEDED, later["assessment_id"])])


@pytest.mark.parametrize("name", list(TRACKS))
def test_a_decision_on_a_comparison_and_its_two_assessments_shows_both_reasons_for_the_side_that_has_a_later_assessment(name, compared, tmp_path):
    study, ids = copy(compared, name, tmp_path)
    cited = [ids["comparison"]["comparison_id"], ids["control"]["assessment_id"], ids["candidate"]["assessment_id"]]
    decision = decide(study, cited, request_id="d-comparison-and-assessments")
    later = TRACKS[name].assess_again(study, ids["control"])
    row = decision_row(study, decision["decision_id"])
    assert row["applies"] is False
    assert {(r["reason"], r["id"]) for r in row["reasons"]} == {("assessment_superseded", later["assessment_id"]), (SUPERSEDED, later["assessment_id"])}


# --- the cases of the hop, on Bike, each with the whole list `reasons` in order -------------------------------------------------


def case_both_sides(study, ids, track, monkeypatch):
    control, candidate = track.assess_again(study, ids["control"]), track.assess_again(study, ids["candidate"])
    return [ids["comparison"]["comparison_id"]], [entry(SUPERSEDED, control["assessment_id"]), entry(SUPERSEDED, candidate["assessment_id"])]


def case_two_later_assessments_of_one_side(study, ids, track, monkeypatch):
    first = track.assess_again(study, ids["candidate"])
    second = track.assess_again(study, ids["candidate"])
    assert first["assessment_id"] != second["assessment_id"]
    return [ids["comparison"]["comparison_id"]], [entry(SUPERSEDED, second["assessment_id"])]


def case_another_version_of_the_scorer(study, ids, track, monkeypatch):
    monkeypatch.setitem(scorers.REGISTRY, track.scorer, dataclasses.replace(scorers.REGISTRY[track.scorer], version="2"))
    later = track.assess_again(study, ids["control"])
    assert later["scorer"]["version"] == "2" != ids["control"]["scorer"]["version"]
    return [ids["comparison"]["comparison_id"]], [entry(SUPERSEDED, later["assessment_id"])]


def case_two_comparisons_that_name_the_same_assessment(study, ids, track, monkeypatch):
    other = compare(study, ids["control"]["assessment_id"], ids["candidate"]["assessment_id"])
    later = track.assess_again(study, ids["control"])
    return [ids["comparison"]["comparison_id"], other["comparison_id"]], [entry(SUPERSEDED, later["assessment_id"])]


def case_the_comparison_and_one_of_its_assessments(study, ids, track, monkeypatch):
    later = track.assess_again(study, ids["candidate"])
    return [ids["comparison"]["comparison_id"], ids["candidate"]["assessment_id"]], [entry("assessment_superseded", later["assessment_id"]), entry(SUPERSEDED, later["assessment_id"])]


def case_two_comparisons_with_their_roles_swapped(study, ids, track, monkeypatch):
    swapped = compare(study, ids["candidate"]["assessment_id"], ids["control"]["assessment_id"])
    control, candidate = track.assess_again(study, ids["control"]), track.assess_again(study, ids["candidate"])
    first = ids["comparison"]["comparison_id"]

    def expected(cited_ids):  # the first cited Comparison in the stored order gives the order: its Control, then its Candidate
        if cited_ids.index(first) < cited_ids.index(swapped["comparison_id"]):
            return [entry(SUPERSEDED, control["assessment_id"]), entry(SUPERSEDED, candidate["assessment_id"])]
        return [entry(SUPERSEDED, candidate["assessment_id"]), entry(SUPERSEDED, control["assessment_id"])]

    return [first, swapped["comparison_id"]], expected


CASES = {
    "both sides have a later Assessment": case_both_sides,
    "a side has two later Assessments": case_two_later_assessments_of_one_side,
    "the later Assessment is under another version of the Scorer": case_another_version_of_the_scorer,
    "two cited Comparisons name the same Assessment": case_two_comparisons_that_name_the_same_assessment,
    "the Comparison and one of its Assessments are cited": case_the_comparison_and_one_of_its_assessments,
    "two cited Comparisons with their roles swapped": case_two_comparisons_with_their_roles_swapped,
}


@pytest.mark.parametrize("case", list(CASES))
def test_on_bike_the_hop_gives_one_entry_per_distinct_assessment_reached_in_the_order_of_the_cited_ids_and_the_control_first(case, compared, tmp_path, monkeypatch):
    study, ids = copy(compared, "bike", tmp_path)
    cited, expected = CASES[case](study, ids, TRACKS["bike"], monkeypatch)
    decision = decide(study, cited, request_id="d-case")  # `applies` reads the order of the Assessments only, not when the Decision was recorded
    row = decision_row(study, decision["decision_id"])
    assert row["applies"] is False
    assert row["reasons"] == (expected(row["cited_ids"]) if callable(expected) else expected)


# --- one hop, and no more ----------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def every_kind(tmp_path_factory):
    """A Bike Study holding a record of every citable kind, as the fixture of `tests/test_decide.py` builds one, with a Decision on its Comparison,
    a Declared deviation citing the Control's Attempt and its withdrawal: (Study, the examples of its current revision)."""
    from _deviation_helpers import declare
    from _report_tracks import Bike

    study, revised = Bike().exposed_study(tmp_path_factory.mktemp("every-kind"))
    [comparison] = [json.loads(p.read_text()) for p in study.glob("comparisons/*/comparison.json")]
    decide(study, [comparison["comparison_id"]], request_id="d-on-the-comparison")
    control = json.loads(assessment_file(study, comparison["roles"]["control_assessment_id"]).read_text())
    attempt = next(p.parent.name for p in study.glob("attempts/*/observation_set.json") if json.loads(p.read_text())["observation_set_id"] == control["observation_set_id"])
    declared = declare(study, [attempt])
    declare(study, [declared["declared_deviation_id"]], text="the review is done")
    return study, revised


def later_assessments_and_the_comparisons_that_name_them(study) -> tuple:
    """From the files of the Study folder: the Assessments that have a later Assessment (same Observation set, same Scorer id, a greater
    write-journal position), and the Comparisons that name one of them."""
    from _review_helpers import assessment_files, comparison_files, positions

    at = positions(study, "assessment")
    records = list(assessment_files(study).values())

    def key(record):
        return at.get(record["assessment_id"], 0), record.get("recorded_at", ""), record["assessment_id"]

    superseded = {
        record["assessment_id"]
        for record in records
        if any(o["observation_set_id"] == record["observation_set_id"] and o["scorer"]["id"] == record["scorer"]["id"] and key(o) > key(record) for o in records)
    }
    reached = {
        comparison_id
        for comparison_id, record in comparison_files(study).items()
        if {record.get("roles", {}).get("control_assessment_id", record["left_assessment_id"]), record.get("roles", {}).get("candidate_assessment_id", record["right_assessment_id"])} & superseded
    }
    return superseded, reached


def test_among_decisions_citing_one_id_of_every_kind_the_hop_reaches_exactly_those_on_a_comparison_whose_assessment_has_a_later_one(every_kind, tmp_path):
    from _review_helpers import BIKE_SCORER
    from _study_helpers import run_json
    from test_decide import held

    from hypotrail.core import decisions

    study, revised = every_kind
    study = copy_of(study, tmp_path / "study")
    citable = sorted(decisions.held_ids(study))
    assert set(held(study).values()) <= set(citable)  # an id of each of the nine kinds `held` names
    by_id = {cited: decide(study, [cited], request_id=f"one-{number}")["decision_id"] for number, cited in enumerate(citable)}
    [comparison] = [json.loads(p.read_text()) for p in study.glob("comparisons/*/comparison.json")]
    control = json.loads(assessment_file(study, comparison["roles"]["control_assessment_id"]).read_text())
    from _assess_helpers import references_id

    code, payload, err = run_json(
        "assess", "--study", study, "--observations", control["observation_set_id"], "--scorer", BIKE_SCORER, "--references", references_id(study), "--examples-dir", revised
    )
    assert code == 0, (payload, err)
    superseded, reached = later_assessments_and_the_comparisons_that_name_them(study)
    assert superseded and reached
    rows = [row for row in status(study)["decisions"] if len(row["cited_ids"]) == 1]
    assert {row["decision_id"] for row in rows} >= set(by_id.values())
    holding = {code: {row["cited_ids"][0] for row in rows if code in {r["reason"] for r in row["reasons"]}} for code in (SUPERSEDED, "assessment_superseded")}
    cited_of_rows = {row["cited_ids"][0] for row in rows}
    assert holding[SUPERSEDED] == reached & cited_of_rows
    assert holding["assessment_superseded"] == superseded & cited_of_rows
    assert reached <= cited_of_rows and superseded <= cited_of_rows
    others = [row for row in rows if row["cited_ids"][0] not in reached | superseded]
    assert others and all(not {SUPERSEDED, "assessment_superseded"} & {r["reason"] for r in row["reasons"]} for row in others)


def case_a_later_assessment_of_a_set_on_neither_side(study, ids, track):
    from _assess_helpers import observation_set_id
    from _study_helpers import run_ml

    code, payload, err = run_ml(study, "seasonal_7", "dev", "a-third-attempt")
    assert code == 0, (payload, err)
    third = {"observation_set_id": observation_set_id(study, payload["attempt"])}
    track.assess_again(study, third)
    track.assess_again(study, third)


def case_another_scorer_id_on_a_side(study, ids, track):
    from _assess_helpers import assess, references_id

    code, payload, err = assess(study, ids["control"]["observation_set_id"], "regression_rmse_v1", references_id(study))
    assert code == 0, (payload, err)


def case_a_new_compare_of_the_same_two_assessments(study, ids, track):
    compare(study, ids["control"]["assessment_id"], ids["candidate"]["assessment_id"])


@pytest.mark.parametrize(
    "case", [case_a_later_assessment_of_a_set_on_neither_side, case_another_scorer_id_on_a_side, case_a_new_compare_of_the_same_two_assessments], ids=lambda case: case.__name__
)
def test_a_decision_on_a_comparison_alone_still_applies_after_a_write_that_gives_neither_side_a_later_assessment(case, compared, tmp_path):
    study, ids = copy(compared, "bike", tmp_path)
    decision = decide(study, [ids["comparison"]["comparison_id"]], request_id="d-comparison-only")
    case(study, ids, TRACKS["bike"])
    row = decision_row(study, decision["decision_id"])
    assert (row["applies"], row["reasons"]) == (True, [])


# --- a Comparison whose Assessment the Study does not hold, and a Comparison without `roles` -----------------------------------------


def remove(study, assessment):
    shutil.rmtree(Path(study) / "assessments" / assessment["assessment_id"])


def missing_one_side_the_other_later(study, ids, track):
    later = track.assess_again(study, ids["control"])
    remove(study, ids["candidate"])
    return [entry(SUPERSEDED, later["assessment_id"]), entry(NOT_HELD, ids["candidate"]["assessment_id"])]


def missing_both_sides(study, ids, track):
    remove(study, ids["candidate"])
    remove(study, ids["control"])
    return [entry(NOT_HELD, ids["control"]["assessment_id"]), entry(NOT_HELD, ids["candidate"]["assessment_id"])]


def missing_one_named_by_two_cited_comparisons(study, ids, track):
    remove(study, ids["candidate"])
    return [entry(NOT_HELD, ids["candidate"]["assessment_id"])]


def missing_one_cited_and_compared(study, ids, track):
    remove(study, ids["control"])
    return [entry("cited_id_not_held", ids["control"]["assessment_id"]), entry(NOT_HELD, ids["control"]["assessment_id"])]


MISSING = {
    "one side missing, the other with a later Assessment": (missing_one_side_the_other_later, lambda ids, other: [ids["comparison"]["comparison_id"]]),
    "both sides missing": (missing_both_sides, lambda ids, other: [ids["comparison"]["comparison_id"]]),
    "two cited Comparisons name the missing Assessment": (missing_one_named_by_two_cited_comparisons, lambda ids, other: [ids["comparison"]["comparison_id"], other]),
    "a cited and compared Assessment removed": (missing_one_cited_and_compared, lambda ids, other: [ids["comparison"]["comparison_id"], ids["control"]["assessment_id"]]),
}


@pytest.mark.parametrize("case", list(MISSING))
def test_each_assessment_a_cited_comparison_names_and_the_study_does_not_hold_gives_one_not_held_entry_and_status_still_answers(case, compared, tmp_path):
    study, ids = copy(compared, "bike", tmp_path)
    other = compare(study, ids["control"]["assessment_id"], ids["candidate"]["assessment_id"])["comparison_id"]
    change, cited = MISSING[case]
    decision = decide(study, cited(ids, other), request_id="d-missing")
    expected = change(study, ids, TRACKS["bike"])
    row = decision_row(study, decision["decision_id"])  # `status --json` exits 0
    assert (row["applies"], row["reasons"]) == (False, expected)


@pytest.mark.parametrize("side", SIDES)
def test_with_no_roles_in_the_comparison_record_the_hop_reaches_the_left_as_the_control_and_the_right_as_the_candidate(side, compared, tmp_path):
    study, ids = copy(compared, "bike", tmp_path)
    drop_roles(study, ids["comparison"]["comparison_id"])
    assert (ids["comparison"]["left_assessment_id"], ids["comparison"]["right_assessment_id"]) == (ids["control"]["assessment_id"], ids["candidate"]["assessment_id"])
    decision = decide(study, [ids["comparison"]["comparison_id"]], request_id="d-comparison-only")
    later = TRACKS["bike"].assess_again(study, ids[side])
    row = decision_row(study, decision["decision_id"])
    assert (row["applies"], row["reasons"]) == (False, [entry(SUPERSEDED, later["assessment_id"])])
