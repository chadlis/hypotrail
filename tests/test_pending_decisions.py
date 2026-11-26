"""`status --json` lists each Comparison that waits for a decision, with a fixed question, options and consequence texts.

"A Comparison of the current revision that no applying Decision cites is pending. It has a fixed question and fixed options, with consequence texts
from the core." (D-077 on chadlis/hypotrail#75, Q7). It is derived when `status` reads the Study and never stored. No model is called.
"""

import json
import re
import shutil
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
    exposure_count,
    files,
    positions,
    read,
    status,
)
from test_study_lock import held_by_another_process

from hypotrail.core import canonical, contracts, decisions

ROOT = Path(__file__).resolve().parent.parent
QUESTION = ("keep_after_comparison", "Which Configuration do we keep after this Comparison?")
OPTIONS = [("keep_control", "Keep the Control"), ("keep_candidate", "Keep the Candidate"), ("keep_neither", "Choose neither yet")]
ENTRY_KEYS = {"comparison_id", "control_assessment_id", "candidate_assessment_id", "question", "options"}


@pytest.fixture(scope="module")
def compared(tmp_path_factory):
    """{track: (Study, {"control", "candidate", "comparison"})}: a Comparison of two Assessments of revision 1, built once per module."""
    built = {}
    for name, track in TRACKS.items():
        study, control, candidate, comparison = track.compared(tmp_path_factory.mktemp(f"pending-{name}"))
        built[name] = (study, {"control": control, "candidate": candidate, "comparison": comparison})
    return built


def copy(compared, name, tmp_path):
    study, ids = compared[name]
    return copy_of(study, tmp_path / name / "study"), dict(ids)


def sides_on_disk(record) -> list:
    roles = record.get("roles")
    return [roles["control_assessment_id"], roles["candidate_assessment_id"]] if roles else [record["left_assessment_id"], record["right_assessment_id"]]


def pending_by_the_three_conditions(study, payload) -> list:
    """The ids of the Comparisons, from the files of the Study folder, for which the three conditions hold, in the order of `comparisons`."""
    revision = read(Path(study) / "study.json")["revision"]
    assessments = {read(p)["assessment_id"]: read(p) for p in Path(study).glob("assessments/*/assessment.json")}
    at = positions(study, "assessment")

    def key(record):
        return at.get(record["assessment_id"], 0), record.get("recorded_at", ""), record["assessment_id"]

    def has_later(record):
        return any(o["observation_set_id"] == record["observation_set_id"] and o["scorer"]["id"] == record["scorer"]["id"] and key(o) > key(record) for o in assessments.values())

    cited = {cited_id for row in payload["decisions"] if row["applies"] for cited_id in row["cited_ids"]}
    found = []
    for path in sorted(Path(study).glob("comparisons/*/comparison.json")):
        record = read(path)
        sides = sides_on_disk(record)
        of_the_revision = all(side in assessments and (assessments[side].get("study_revision") or {}).get("revision") == revision for side in sides)
        if of_the_revision and not any(has_later(assessments[side]) for side in sides) and record["comparison_id"] not in cited:
            found.append(record["comparison_id"])
    order = [entry["comparison_id"] for entry in payload["comparisons"]]
    return sorted(found, key=order.index)


def read_pending(study) -> list:
    """The ids of `pending_decisions` of one read, checked against the three conditions computed from the files; the read writes nothing."""
    before = files(study)
    payload = status(study)
    again = status(study)
    assert files(study) == before
    assert payload["write_sequence"] == again["write_sequence"]
    listed = [entry["comparison_id"] for entry in payload["pending_decisions"]]
    assert listed == pending_by_the_three_conditions(study, payload)
    return listed


def assert_entry(study, entry):
    """The keys of an entry, its ids against the Comparison's file, its question and options against the strings of the ticket and the constants."""
    assert set(entry) == ENTRY_KEYS
    record = read(comparison_file(study, entry["comparison_id"]))
    assert [entry["control_assessment_id"], entry["candidate_assessment_id"]] == sides_on_disk(record)
    assert set(entry["question"]) == {"id", "text"} and (entry["question"]["id"], entry["question"]["text"]) == QUESTION
    assert [set(option) for option in entry["options"]] == [{"id", "text", "consequence"}] * 3
    assert [(option["id"], option["text"]) for option in entry["options"]] == OPTIONS
    assert entry["question"] == decisions.PENDING_QUESTION
    assert entry["options"] == [dict(option) for option in decisions.PENDING_OPTIONS]
    assert all(option["consequence"] for option in entry["options"])
    assert "that is pending under the same rule" in entry["options"][2]["consequence"]


# --- which Comparisons are pending: the walk of each Track -----------------------------------------------------------------------


@pytest.mark.parametrize("name", list(TRACKS))
def test_a_comparison_is_pending_until_an_applying_decision_cites_it_and_stays_closed_once_a_side_has_a_later_assessment(name, compared, tmp_path):
    study, ids = copy(compared, name, tmp_path)
    comparison = ids["comparison"]["comparison_id"]
    assert read_pending(study) == [comparison]  # (a)
    [entry] = status(study)["pending_decisions"]
    assert_entry(study, entry)
    if name == "bike":  # `status` takes no lock
        with held_by_another_process(study):
            locked = status(study)
        assert [e["comparison_id"] for e in locked["pending_decisions"]] == [comparison]
    question, option = entry["question"]["text"], entry["options"][1]["text"]
    decision = decide(study, [comparison], request_id="d-answer", question=question, option=option)
    [path] = [p for p in study.glob("decisions/*.json") if read(p)["decision_id"] == decision["decision_id"]]
    assert (read(path)["question"], read(path)["option"]) == (question, option)  # recorded as given
    assert read_pending(study) == []  # (b)
    TRACKS[name].assess_again(study, ids["control"])
    assert read_pending(study) == []  # (c)
    decide(study, [comparison], request_id="d-again")
    assert read_pending(study) == []


@pytest.mark.parametrize("name", list(TRACKS))
def test_a_decision_with_the_ids_and_words_closes_its_comparison_exactly_as_one_recorded_without(name, compared, tmp_path):
    from _review_helpers import sequence
    from _study_helpers import run_json

    without, ids = copy(compared, name, tmp_path / "without")
    with_words, _ = copy(compared, name, tmp_path / "with")
    comparison = ids["comparison"]["comparison_id"]
    question, option = decisions.PENDING_QUESTION["text"], decisions.PENDING_OPTIONS[1]["text"]
    decide(without, [comparison], request_id="d-answer", question=question, option=option)
    code, payload, err = run_json(
        "decide", "--study", with_words, "--question", question, "--option", option, "--author", "human", "--artifact", comparison,
        "--request-id", "d-answer", "--read-sequence", sequence(with_words), "--question-id", "keep_after_comparison", "--option-id", "keep_candidate",
        "--words", "Keep the candidate.", "--by", "the owner",
    )
    assert code == 0, (payload, err)
    assert read_pending(without) == read_pending(with_words) == []
    TRACKS[name].assess_again(without, ids["control"])
    TRACKS[name].assess_again(with_words, ids["control"])
    assert read_pending(without) == read_pending(with_words) == []


# --- the other cases, on Bike ------------------------------------------------------------------------------------------------------


def case_a_new_compare_of_the_latest_assessments(study, ids, tmp_path):
    later = TRACKS["bike"].assess_again(study, ids["control"])
    second = compare(study, later["assessment_id"], ids["candidate"]["assessment_id"])
    return [second["comparison_id"]]


def case_decisions_that_cite_other_records_or_do_not_apply(study, ids, tmp_path):
    attempt = next(p.parent.name for p in study.glob("attempts/*/attempt.json"))
    decide(study, [attempt], request_id="d-on-an-attempt")
    held_for_a_while = decide(study, [attempt], request_id="d-to-remove")
    decide(study, [ids["comparison"]["comparison_id"], held_for_a_while["decision_id"]], request_id="d-not-applying")
    next(study.glob(f"decisions/*-{held_for_a_while['decision_id']}.json")).unlink()
    return [ids["comparison"]["comparison_id"]]


def case_two_comparisons_both_pending(study, ids, tmp_path):
    second = compare(study, ids["control"]["assessment_id"], ids["candidate"]["assessment_id"])
    return [ids["comparison"]["comparison_id"], second["comparison_id"]]


def case_a_study_whose_only_comparison_is_not_pending(study, ids, tmp_path):
    decide(study, [ids["comparison"]["comparison_id"]], request_id="d-1")
    return []


def case_a_decision_that_cites_it_with_another_id(study, ids, tmp_path):
    decide(study, [ids["comparison"]["comparison_id"], ids["control"]["assessment_id"]], request_id="d-1", question="Q?", option="any option")
    return []


def case_a_new_revision(study, ids, tmp_path):
    track = TRACKS["bike"]
    track.revise_an_assessed_item(study, tmp_path)
    of_revision_1 = compare(study, ids["control"]["assessment_id"], ids["candidate"]["assessment_id"])
    assert of_revision_1["comparison_id"] not in read_pending(study)
    control, candidate = track.assess_again(study, ids["control"]), track.assess_again(study, ids["candidate"])
    of_revision_2 = compare(study, control["assessment_id"], candidate["assessment_id"])
    return [of_revision_2["comparison_id"]]


CASES = {
    "a new compare of the latest Assessment of each side": case_a_new_compare_of_the_latest_assessments,
    "Decisions that cite other records, or cite it and do not apply": case_decisions_that_cite_other_records_or_do_not_apply,
    "two Comparisons that meet the three conditions": case_two_comparisons_both_pending,
    "a Study whose only Comparison is not pending": case_a_study_whose_only_comparison_is_not_pending,
    "a Decision that cites it with another id": case_a_decision_that_cites_it_with_another_id,
    "init --new-revision, then compare under it": case_a_new_revision,
}


@pytest.mark.parametrize("case", list(CASES))
def test_the_pending_comparisons_of_a_bike_study_are_those_for_which_the_three_conditions_hold(case, compared, tmp_path):
    study, ids = copy(compared, "bike", tmp_path)
    expected = CASES[case](study, ids, tmp_path)
    assert read_pending(study) == expected
    if case == "two Comparisons that meet the three conditions":  # the journal order of `comparisons`
        payload = status(study)
        listed = [entry["comparison_id"] for entry in payload["comparisons"]]
        assert [entry["comparison_id"] for entry in payload["pending_decisions"]] == sorted(expected, key=listed.index) == expected


def test_a_study_that_holds_no_comparison_has_no_pending_decision(tmp_path):
    from _study_helpers import init_study

    study, _ = init_study(tmp_path)
    assert status(study)["pending_decisions"] == []


@pytest.mark.parametrize("edit", ["study_revision removed from an Assessment's record", "an Assessment's folder removed"])
def test_a_comparison_one_of_whose_assessments_has_no_study_revision_or_is_not_held_is_not_pending(edit, compared, tmp_path):
    study, ids = copy(compared, "bike", tmp_path)
    path = assessment_file(study, ids["candidate"]["assessment_id"])
    if edit == "an Assessment's folder removed":
        shutil.rmtree(path.parent)
    else:
        record = read(path)
        del record["study_revision"]
        contracts.validate(record)  # the key is not required
        path.write_bytes(canonical.dumps(record))
    assert read_pending(study) == []


def test_a_decision_with_an_option_of_its_own_wording_closes_the_pending_decision(compared, tmp_path):
    study, ids = copy(compared, "bike", tmp_path)
    assert read_pending(study) == [ids["comparison"]["comparison_id"]]
    decide(study, [ids["comparison"]["comparison_id"]], request_id="d-own", question="Shall we ship?", option="Ship both, side by side")
    assert read_pending(study) == []


# --- the entry -----------------------------------------------------------------------------------------------------------------------------


def test_with_no_roles_in_the_comparison_record_the_entry_names_the_left_and_right_assessments(compared, tmp_path):
    study, ids = copy(compared, "bike", tmp_path)
    path = comparison_file(study, ids["comparison"]["comparison_id"])
    record = read(path)
    del record["roles"]
    contracts.validate(record)
    path.write_bytes(canonical.dumps(record))
    [entry] = status(study)["pending_decisions"]
    assert (entry["control_assessment_id"], entry["candidate_assessment_id"]) == (record["left_assessment_id"], record["right_assessment_id"])


@pytest.mark.parametrize("track", ["bike", "chinook"])
def test_on_public_check_an_entry_holds_its_five_keys_only_and_reading_it_records_no_exposure(track, tmp_path):
    study, _, _, comparison = REPORT_TRACKS[track].public_world(tmp_path)
    count = exposure_count(study)
    [entry] = status(study)["pending_decisions"]
    assert set(entry) == ENTRY_KEYS and entry["comparison_id"] == comparison["comparison_id"]
    assert exposure_count(study) == count


def test_no_workload_file_holds_the_question_or_an_option_identifier():
    needles = [QUESTION[0], QUESTION[1], *[identifier for identifier, _ in OPTIONS]]
    found = [(path, needle) for path in (ROOT / "examples").rglob("*") if path.is_file() for needle in needles if needle.encode() in path.read_bytes()]
    assert found == []


def avoided_words() -> set:
    """The words `GLOSSARY.md` lists under _Avoid_ for **Decision**, **Control** and **Candidate**, without those it qualifies "(as a role)"."""
    glossary = (ROOT / "GLOSSARY.md").read_text(encoding="utf-8")
    words = set()
    for term in ("Decision", "Control", "Candidate"):
        entry = re.search(rf"^\*\*{term}\*\*:\n(.*?)(?=^\*\*|\Z)", glossary, re.S | re.M)[1]
        [avoid] = [line for line in entry.splitlines() if line.startswith("_Avoid_:")]
        words |= {word.strip() for word in avoid.removeprefix("_Avoid_:").split(",") if "(as a role)" not in word}
    return words


def test_the_question_options_and_consequence_texts_use_no_word_the_glossary_avoids_for_decision_control_and_candidate():
    assert avoided_words() == {"note", "verdict", "conclusion", "challenger", "treatment"}
    texts = [decisions.PENDING_QUESTION["text"], *[option["text"] for option in decisions.PENDING_OPTIONS], *[option["consequence"] for option in decisions.PENDING_OPTIONS]]
    assert len(texts) == 7
    assert [(word, text) for word in sorted(avoided_words()) for text in texts if re.search(rf"\b{word}\b", text, re.I)] == []
