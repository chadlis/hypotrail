"""Ticket #110 (slice #104, L2.1): the decision history in `status --json`, and whether each decision still applies.

D-031 on chadlis/hypotrail#75, D-033 on chadlis/hypotrail#75, D-034 on chadlis/hypotrail#75, D-035 on chadlis/hypotrail#75, D-036 on chadlis/hypotrail#75 and D-037 on chadlis/hypotrail#75 settle what is tested here. `status --json` lists the Study's decisions in the
order they were recorded, each with the fields `decide` recorded plus `applies` and `reasons`. Whether a decision applies is computed when `status`
reads the Study, from the ids it cites, and is never stored. `status` takes no lock and writes nothing. No model is called.
"""

import copy
import dataclasses
import json
import re
import shutil
from pathlib import Path

import pytest
from _assess_helpers import assess, fresh_study, observation_set_id, references_id
from _chinook_helpers import references_id as chinook_references_id, revision_one_examples
from _revision_helpers import new_revision
from _study_helpers import examples_copy, init_study, run_cli, run_json
from test_write_sequence import entries, seq, tree

from hypotrail.core import canonical, scorers

ROOT = Path(__file__).resolve().parent.parent
KEPT = ROOT / "docs" / "handbook" / "traces" / "campaign-public-check" / "study"
QUESTION = "Which Configuration do we keep?"
SCORER = "regression_mae_v1"
OTHER_SCORER = "regression_rmse_v1"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


# --- helpers ---------------------------------------------------------------------------------------------------------


def listed(study) -> list:
    """The decisions `status --json` lists."""
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    assert "decisions" in payload, "status --json lists no decisions"
    return payload["decisions"]


def row_of(study, decision_id) -> dict:
    return next(row for row in listed(study) if row["decision_id"] == decision_id)


def decide(study, cited, *, request_id, question=QUESTION, option="ridge_v1", author="human", source=None) -> dict:
    flags = ["--study", study, "--question", question, "--option", option, "--author", author, "--request-id", request_id, "--read-sequence", seq(study)]
    flags += [part for cited_id in cited for part in ("--artifact", cited_id)]
    if source is not None:
        flags += ["--source", source]
    code, payload, err = run_json("decide", *flags)
    assert code == 0, (payload, err)
    return payload["decision"]


def records_on_disk(study) -> list:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((Path(study) / "decisions").glob("*.json"))]


def files(study) -> dict:
    return {k: v for k, v in tree(study).items() if k != "writer.lock"}


def generic(path: str) -> str:
    return re.sub(r"write_journal/\d{6}", "write_journal/N", UUID.sub("ID", path))


def delta(before: dict, after: dict) -> tuple:
    """(files added, files changed, files removed) between two trees, the ids and the journal positions masked."""
    added = {generic(p) for p in set(after) - set(before)}
    changed = {generic(p) for p in before if p in after and before[p] != after[p]}
    removed = {generic(p) for p in set(before) - set(after)}
    return added, changed, removed


def assessment_ids(study) -> list:
    return [json.loads(p.read_text())["assessment_id"] for p in sorted((Path(study) / "assessments").glob("*/assessment.json"))]


def assessed_again(study, observation_set, scorer=SCORER) -> str:
    code, payload, err = assess(study, observation_set, scorer, references_id(study))
    assert code == 0, (payload, err)
    return payload["assessment"]["assessment_id"]


def corrected_day(table):
    row = next(r for r in table if r["dteday"] == "2012-03-15")
    row["cnt"], row["registered"] = str(int(row["cnt"]) + 1000), str(int(row["registered"]) + 1000)


def with_new_revision(study, tmp_path):
    code, payload, err = new_revision(study, "--examples-dir", examples_copy(tmp_path, rows=corrected_day, name="revised"))
    assert code == 0, (payload, err)
    return payload["study"]["revision"]


def written_directly(study, assessment_id, *, new_id, recorded_at) -> str:
    """A new Assessment record, written in the Study's folder with no journal entry (as `tests/test_compare_agent.py` `rewritten` does)."""
    source = Path(study) / "assessments" / assessment_id / "assessment.json"
    record = json.loads(source.read_text(encoding="utf-8"))
    record.update(assessment_id=new_id, recorded_at=recorded_at)
    folder = Path(study) / "assessments" / new_id
    folder.mkdir()
    (folder / "assessment.json").write_bytes(canonical.dumps(record))
    return new_id


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """A Bike Study with an Attempt and one Assessment (Scorer `regression_mae_v1`) of its Observation set: (Study, its ids)."""
    base = tmp_path_factory.mktemp("history")
    study, attempts = fresh_study(base, "seasonal_7")
    attempt = attempts["seasonal_7"]
    observation_set = observation_set_id(study, attempt)
    code, payload, err = assess(study, observation_set, SCORER, references_id(study))
    assert code == 0, (payload, err)
    ids = {
        "attempt": attempt["attempt_id"],
        "observation_set": observation_set,
        "assessment": payload["assessment"]["assessment_id"],
        "revision": json.loads((study / "study.json").read_text())["revision"],
    }
    return study, ids


@pytest.fixture
def study(made, tmp_path):
    """A private copy of that Study."""
    target = tmp_path / "workspace" / "study"
    (tmp_path / "workspace").mkdir()
    shutil.copytree(made[0], target)
    return target


@pytest.fixture
def ids(made):
    return made[1]


# --- criterion 1: every decision, in the order recorded, with every field `decide` recorded ----------------------------


def test_status_lists_the_decisions_in_the_order_they_were_recorded_with_every_field_decide_recorded(study, ids):
    decide(study, [ids["attempt"]], request_id="d-1", author="proxy", source="a rule")
    decide(study, [ids["assessment"], ids["attempt"]], request_id="d-2", question="Another question?", option="seasonal_7")
    on_disk = records_on_disk(study)
    assert len(on_disk) == 2
    rows = listed(study)
    assert [{key: row[key] for key in record} for row, record in zip(rows, on_disk)] == on_disk
    assert [row["decision_id"] for row in rows] == [record["decision_id"] for record in on_disk]
    assert len(rows) == 2


def test_a_study_with_no_decision_lists_none(study):
    assert listed(study) == []


# --- criterion 2, Tightened A, C, E, F, H, I: whether a decision still applies --------------------------------------------


def test_a_decision_that_applies_has_no_reason_and_the_row_holds_the_record_and_three_keys(study, ids):
    record = decide(study, [ids["assessment"]], request_id="d-1")
    (row,) = listed(study)
    assert set(row) == set(record) | {"applies", "reasons", "evidence_change"}
    assert (row["applies"], row["reasons"]) == (True, [])


def outdate_by_removing_the_cited_assessment(study, ids, tmp_path):
    shutil.rmtree(study / "assessments" / ids["assessment"])
    return [{"reason": "cited_id_not_held", "id": ids["assessment"]}]


def outdate_by_a_new_revision(study, ids, tmp_path):
    return [{"reason": "revision_changed", "id": with_new_revision(study, tmp_path)}]


def outdate_by_a_later_assessment_of_the_same_scorer(study, ids, tmp_path):
    return [{"reason": "assessment_superseded", "id": assessed_again(study, ids["observation_set"])}]


def outdate_by_a_later_assessment_under_another_version_of_the_scorer(study, ids, tmp_path, monkeypatch):
    monkeypatch.setitem(scorers.REGISTRY, SCORER, dataclasses.replace(scorers.REGISTRY[SCORER], version="2"))
    return [{"reason": "assessment_superseded", "id": assessed_again(study, ids["observation_set"])}]


CHANGES = {
    "a cited record removed": outdate_by_removing_the_cited_assessment,
    "init --new-revision": outdate_by_a_new_revision,
    "a later Assessment, same Scorer id": outdate_by_a_later_assessment_of_the_same_scorer,
    "a later Assessment, another version of the Scorer id": outdate_by_a_later_assessment_under_another_version_of_the_scorer,
}


def make_the_change(change, study, ids, tmp_path, monkeypatch):
    return change(study, ids, tmp_path, monkeypatch) if change is outdate_by_a_later_assessment_under_another_version_of_the_scorer else change(study, ids, tmp_path)


@pytest.mark.parametrize("name", list(CHANGES))
def test_each_condition_makes_the_decision_outdated_with_its_reason_and_the_causing_id(name, study, ids, tmp_path, monkeypatch):
    record = decide(study, [ids["assessment"]], request_id="d-1")
    assert (row_of(study, record["decision_id"])["applies"], row_of(study, record["decision_id"])["reasons"]) == (True, [])
    expected = make_the_change(CHANGES[name], study, ids, tmp_path, monkeypatch)
    row = row_of(study, record["decision_id"])
    assert (row["applies"], row["reasons"]) == (False, expected)
    assert {key: row[key] for key in record} == record  # the record the row shows is the record `decide` returned


@pytest.mark.parametrize("name", list(CHANGES))
def test_status_leaves_the_decision_record_the_write_sequence_and_every_file_as_they_were_when_a_decision_becomes_outdated(name, study, ids, tmp_path, monkeypatch):
    record = decide(study, [ids["assessment"]], request_id="d-1")
    [file] = (study / "decisions").glob("*.json")
    digest = file.read_bytes()
    make_the_change(CHANGES[name], study, ids, tmp_path, monkeypatch)
    tree_before = files(study)  # before the first `status` call
    sequence = seq(study)
    for _ in range(2):
        rows = listed(study)
        assert [row["applies"] for row in rows] == [False]
    assert file.read_bytes() == digest and json.loads(digest) == record
    assert seq(study) == sequence and files(study) == tree_before
    assert not list(study.rglob("*.tmp")) and (study / "writer.lock").read_bytes() == b""


@pytest.mark.parametrize("name", list(CHANGES))
def test_the_change_that_outdates_a_decision_adds_the_files_it_adds_with_no_decision_and_nothing_else(name, made, tmp_path, monkeypatch):
    base, ids = made
    with_decision, without = tmp_path / "with", tmp_path / "without"
    shutil.copytree(base, with_decision)
    shutil.copytree(base, without)
    decide(with_decision, [ids["assessment"]], request_id="d-1")
    before_with, before_without = files(with_decision), files(without)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    make_the_change(CHANGES[name], with_decision, ids, tmp_path / "a", monkeypatch)
    listed(with_decision)
    make_the_change(CHANGES[name], without, ids, tmp_path / "b", monkeypatch)
    with_delta, without_delta = delta(before_with, files(with_decision)), delta(before_without, files(without))
    assert with_delta == without_delta
    assert not any(path.startswith("decisions/") for part in with_delta for path in part)
    assert any(with_delta), "the change wrote nothing"


def test_another_scorer_or_a_decision_citing_an_attempt_recorded_under_an_earlier_revision_still_applies(study, ids, tmp_path):
    cited_assessment = decide(study, [ids["assessment"]], request_id="d-1")
    assessed_again(study, ids["observation_set"], OTHER_SCORER)  # an Assessment of the same Observation set by another Scorer
    assert row_of(study, cited_assessment["decision_id"])["applies"] is True
    with_new_revision(study, tmp_path)  # the Attempt and its Assessment were recorded under revision 1
    later = decide(study, [ids["assessment"], ids["attempt"]], request_id="d-2")
    row = row_of(study, later["decision_id"])
    assert (row["applies"], row["reasons"]) == (True, [])
    assert row["revision"] != ids["revision"]


def test_a_decision_with_two_causes_lists_both_reasons(study, ids, tmp_path):
    record = decide(study, [ids["assessment"]], request_id="d-1")
    shutil.rmtree(study / "assessments" / ids["assessment"])
    revision = with_new_revision(study, tmp_path)
    row = row_of(study, record["decision_id"])
    assert row["applies"] is False
    assert sorted(row["reasons"], key=lambda r: r["reason"]) == [
        {"reason": "cited_id_not_held", "id": ids["assessment"]},
        {"reason": "revision_changed", "id": revision},
    ]


def test_the_revision_changed_reason_names_the_current_revision_and_the_record_keeps_the_earlier_one(study, ids, tmp_path):
    record = decide(study, [ids["attempt"]], request_id="d-1")
    revision = with_new_revision(study, tmp_path)
    row = row_of(study, record["decision_id"])
    assert row["reasons"] == [{"reason": "revision_changed", "id": json.loads((study / "study.json").read_text())["revision"]}]
    assert row["reasons"][0]["id"] == revision != ids["revision"]
    assert records_on_disk(study)[0]["revision"] == ids["revision"] and row["revision"] == ids["revision"]


def test_every_listed_decision_has_reasons_empty_when_it_applies_and_not_empty_when_it_does_not(study, ids, tmp_path):
    decide(study, [ids["attempt"]], request_id="d-1")
    decide(study, [ids["assessment"]], request_id="d-2")
    assessed_again(study, ids["observation_set"])
    rows = listed(study)
    assert all("reasons" in row and isinstance(row["reasons"], list) for row in rows)
    assert [(row["applies"], bool(row["reasons"])) for row in rows] == [(True, False), (False, True)]


# --- Tightened B: a later decision on the same question changes nothing -----------------------------------------------


def test_two_decisions_on_the_same_question_citing_the_same_ids_both_apply(study, ids):
    first = decide(study, [ids["assessment"]], request_id="d-1", option="ridge_v1")
    second = decide(study, [ids["assessment"]], request_id="d-2", option="seasonal_7")
    assert first["question"] == second["question"]
    rows = listed(study)
    assert [(row["decision_id"], row["applies"], row["reasons"]) for row in rows] == [(first["decision_id"], True, []), (second["decision_id"], True, [])]


# --- Tightened E: "later" is the position in the write journal --------------------------------------------------------


def test_with_two_assessments_of_the_same_set_and_scorer_the_earlier_in_the_journal_is_outdated_and_the_later_applies(study, ids):
    second = assessed_again(study, ids["observation_set"])
    on_earlier = decide(study, [ids["assessment"]], request_id="d-1")
    on_later = decide(study, [second], request_id="d-2")
    earlier_row, later_row = row_of(study, on_earlier["decision_id"]), row_of(study, on_later["decision_id"])
    assert (earlier_row["applies"], earlier_row["reasons"]) == (False, [{"reason": "assessment_superseded", "id": second}])
    assert (later_row["applies"], later_row["reasons"]) == (True, [])


def test_the_position_in_the_write_journal_orders_two_assessments_whatever_their_recorded_at(study, ids):
    second = assessed_again(study, ids["observation_set"])
    path = study / "assessments" / second / "assessment.json"
    record = json.loads(path.read_text())
    record["recorded_at"] = "2000-01-01T00:00:00+00:00"  # earlier than the first one, journaled after it
    path.write_bytes(canonical.dumps(record))
    on_earlier = decide(study, [ids["assessment"]], request_id="d-1")
    assert row_of(study, on_earlier["decision_id"])["reasons"] == [{"reason": "assessment_superseded", "id": second}]


# --- Tightened J and K: a record with no write-journal position counts as 0 ----------------------------------------------


@pytest.fixture
def kept(tmp_path):
    """A copy of the kept Study of the Campaign, whose Assessments were written before the write journal existed."""
    target = tmp_path / "kept"
    shutil.copytree(KEPT, target)
    return target


def kept_assessments(kept) -> list:
    return assessment_ids(kept)


def test_a_new_assess_on_a_study_written_before_the_journal_comes_after_a_kept_assessment_of_the_same_set_and_scorer(kept):
    [first_kept, other_kept] = kept_assessments(kept)
    observation_set = json.loads((kept / "assessments" / first_kept / "assessment.json").read_text())["observation_set_id"]
    on_kept = decide(kept, [first_kept], request_id="k-1")
    on_other = decide(kept, [other_kept], request_id="k-2")
    assert entries(kept) and row_of(kept, on_kept["decision_id"])["applies"] is True
    code, payload, err = run_json(
        "assess", "--study", kept, "--observations", observation_set, "--scorer", "chinook_contract_v1", "--references", chinook_references_id(kept),
        "--examples-dir", revision_one_examples(kept.parent),  # the Workload the kept Study was made on
    )
    assert code == 0, (payload, err)
    new_id = payload["assessment"]["assessment_id"]
    row, other = row_of(kept, on_kept["decision_id"]), row_of(kept, on_other["decision_id"])
    assert (row["applies"], row["reasons"]) == (False, [{"reason": "assessment_superseded", "id": new_id}])
    assert (other["applies"], other["reasons"]) == (True, [])  # another Observation set


@pytest.mark.parametrize(
    ("earlier_at", "later_at", "earlier_id", "later_id"),
    [
        ("2026-12-01T00:00:00+00:00", "2026-12-02T00:00:00+00:00", "ffffffff-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"),
        ("2026-12-01T00:00:00+00:00", "2026-12-01T00:00:00+00:00", "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"),
    ],
    ids=["recorded_at orders them", "a tie is broken by the id"],
)
def test_two_assessments_written_without_a_journal_entry_are_both_at_position_zero_and_are_ordered_by_recorded_at_then_id(kept, earlier_at, later_at, earlier_id, later_id):
    [source, _] = kept_assessments(kept)
    first = written_directly(kept, source, new_id=earlier_id, recorded_at=earlier_at)
    second = written_directly(kept, source, new_id=later_id, recorded_at=later_at)
    on_first = decide(kept, [first], request_id="k-1")
    on_second = decide(kept, [second], request_id="k-2")
    one, two = row_of(kept, on_first["decision_id"]), row_of(kept, on_second["decision_id"])
    assert (one["applies"], one["reasons"]) == (False, [{"reason": "assessment_superseded", "id": second}])
    assert (two["applies"], two["reasons"]) == (True, [])


def test_a_record_named_in_no_end_entry_sorts_before_a_journaled_one_even_with_a_later_recorded_at(study, ids):
    direct = written_directly(study, ids["assessment"], new_id="00000000-0000-4000-8000-0000000000aa", recorded_at="2999-01-01T00:00:00+00:00")
    journaled = assessed_again(study, ids["observation_set"])
    named = [item["id"] for entry in entries(study) if entry["phase"] == "end" for item in entry["written"]]
    assert journaled in named and direct not in named
    on_direct = decide(study, [direct], request_id="d-1")
    on_journaled = decide(study, [journaled], request_id="d-2")
    row_direct, row_journaled = row_of(study, on_direct["decision_id"]), row_of(study, on_journaled["decision_id"])
    assert (row_direct["applies"], row_direct["reasons"]) == (False, [{"reason": "assessment_superseded", "id": journaled}])
    assert (row_journaled["applies"], row_journaled["reasons"]) == (True, [])


# --- Tightened D and G: the human count line ---------------------------------------------------------------------------


def human(study) -> list:
    code, out, err = run_cli("status", "--study", study)
    assert code == 0, err
    return out.splitlines()


def test_the_human_status_of_a_study_with_decisions_holds_one_count_line_with_the_decisions_and_those_that_no_longer_apply(study, ids):
    decide(study, [ids["attempt"]], request_id="d-1")
    decide(study, [ids["assessment"]], request_id="d-2")
    assessed_again(study, ids["observation_set"])
    lines = [line for line in human(study) if "Decisions" in line]
    assert lines == ["Decisions: 2 recorded, 1 no longer applies"]


def test_the_human_status_of_a_study_with_no_decision_has_no_such_line_and_is_what_it_was(tmp_path):
    study, _ = init_study(tmp_path)
    spec = json.loads((study / "study.json").read_text())
    assert human(study) == [
        f"Study {spec['study_id']} ({spec['workload']}); a writer is not active",
        "  0 Exposures recorded in this Study; any earlier exposure to public_check is unknown",
    ]


# --- #155, TB2.11: a withdrawal changes no decision's `applies` ---------------------------------------------------------------


def test_a_decision_that_cites_a_declared_deviation_applies_with_no_reason_before_and_after_that_declared_deviation_is_withdrawn(tmp_path):
    from _deviation_helpers import declare

    study, attempts = fresh_study(tmp_path, "seasonal_7")
    declared = declare(study, [attempts["seasonal_7"]["attempt_id"]])
    decision = decide(study, [declared["declared_deviation_id"]], request_id="d-on-a-deviation")
    before = row_of(study, decision["decision_id"])
    declare(study, [declared["declared_deviation_id"]], text="the review is done")
    after = row_of(study, decision["decision_id"])
    assert (before["applies"], before["reasons"]) == (after["applies"], after["reasons"]) == (True, [])


# --- the whole human output of `status` on a Study whose Decision on a Comparison is reached by a later Assessment ----


def test_the_human_status_of_a_study_with_a_comparison_a_decision_on_it_a_later_assessment_and_a_second_comparison_is_these_lines(tmp_path):
    from _review_helpers import TRACKS, compare
    from _review_helpers import decide as decide_on

    track = TRACKS["bike"]
    study, control, candidate, comparison = track.compared(tmp_path / "base")
    decide_on(study, [comparison["comparison_id"]], request_id="d-on-the-comparison")
    again = track.assess_again(study, control)
    compare(study, again["assessment_id"], candidate["assessment_id"])
    spec = json.loads((study / "study.json").read_text())
    by_request = {json.loads(p.read_text())["request_id"]: p.parent.name for p in (study / "attempts").glob("*/attempt.json")}
    seasonal, ridge = by_request["ml-dev-seasonal_7"], by_request["ml-dev-ridge_v1"]
    attempts = sorted([(seasonal, f"  {seasonal} completed request ml-dev-seasonal_7, 4 artifacts"), (ridge, f"  {ridge} completed request ml-dev-ridge_v1, 5 artifacts")])
    assert human(study) == [
        f"Study {spec['study_id']} ({spec['workload']}); a writer is not active",
        "  0 Exposures recorded in this Study; any earlier exposure to public_check is unknown",
        "Decisions: 1 recorded, 1 no longer applies",
        *[line for _, line in attempts],
    ]


# --- the consequence texts of a pending decision, as read on #163 --------------------------------------------------------------------


CONSEQUENCES_READ = [
    'A Decision that cites this Comparison is recorded with the option "Keep the Control". The Comparison stops being pending while that Decision applies. Beyond that Decision and its two write-journal entries, nothing is written, and the Study enforces nothing on later work.',
    'A Decision that cites this Comparison is recorded with the option "Keep the Candidate". The Comparison stops being pending while that Decision applies. Beyond that Decision and its two write-journal entries, nothing is written, and the Study enforces nothing on later work.',
    'A Decision that cites this Comparison is recorded with the option "Choose neither yet". The Comparison stops being pending while that Decision applies. Beyond that Decision and its two write-journal entries, nothing is written, and the Study enforces nothing on later work: a later compare writes a new Comparison that is pending under the same rule.',
]


def test_the_consequence_texts_status_gives_for_a_pending_decision_are_the_three_texts_read_on_the_ticket(tmp_path):
    """The three texts exactly as chadlis/hypotrail#163, comment 7083264884, gives them for the reading."""
    from _review_helpers import TRACKS, status

    study, _, _, _ = TRACKS["bike"].compared(tmp_path / "base")
    [entry] = status(study)["pending_decisions"]
    assert [option["consequence"] for option in entry["options"]] == CONSEQUENCES_READ


# --- ticket #244: a Study that holds a `decision/1` record and a `decision/2` record with words ---------------------------------------


def test_status_lists_the_ids_and_words_of_a_decision_2_as_stored_beside_a_decision_1_and_computes_whether_each_applies_as_before(tmp_path):
    from test_decision_versions import KEPT_FILE, RECORD, holding_both
    from test_status_since import STATUS_KEYS

    study = holding_both(tmp_path)
    words = tmp_path / "words.txt"
    words.write_text("Keep the candidate,\nas I said.", encoding="utf-8")
    code, payload, err = run_json(
        "decide", "--study", study, "--question", "Which Configuration do we keep after this Comparison?", "--option", "Keep the Candidate",
        "--author", "human", "--artifact", RECORD["cited_ids"][0], "--request-id", "with-words", "--read-sequence", seq(study),
        "--question-id", "keep_after_comparison", "--option-id", "keep_candidate", "--words-file", words, "--by", "the owner",
    )
    assert code == 0, (payload, err)
    stored = json.loads(next((study / "decisions").glob(f"*-{payload['decision']['decision_id']}.json")).read_text(encoding="utf-8"))
    code, listing, err = run_json("status", "--study", study)
    assert code == 0, (listing, err)
    assert set(listing) == STATUS_KEYS
    old, new = listing["decisions"]
    assert {key: new.get(key, "absent") for key in ("question_id", "option_id", "words")} == {key: stored[key] for key in ("question_id", "option_id", "words")}
    assert new["words"] == {"texts": ["Keep the candidate,\nas I said."], "channel": "chat_relayed", "by": "the owner", "authenticated": False}
    assert [(row["applies"], row["reasons"], row["evidence_change"]) for row in (old, new)] == [(True, [], None)] * 2

    code, payload, err = new_revision(study, "--examples-dir", examples_copy(tmp_path, rows=corrected_day, name="revised"), "--read-sequence", seq(study))
    assert code == 0, (payload, err)
    revision = json.loads((study / "study.json").read_text(encoding="utf-8"))["revision"]
    old, new = listed(study)
    assert [(row["applies"], row["reasons"]) for row in (old, new)] == [(False, [{"reason": "revision_changed", "id": revision}])] * 2
    assert "words" not in old and old["schema_version"] == "decision/1"
    assert (study / "decisions" / KEPT_FILE.name).read_text(encoding="utf-8") == KEPT_FILE.read_text(encoding="utf-8")
