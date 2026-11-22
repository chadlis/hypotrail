"""`status --json` lists every Assessment and every Comparison record of a Study, each entry equal to the stored record.

"A client reads through `status --json`, which takes no lock and writes nothing, and writes only through the documented CLI commands."
(ADR 0004). The listings follow the order of the write journal. No model is called: the Chinook sides are Imports of the kit's answers.
"""

import json
from pathlib import Path

import pytest
from _report_tracks import TRACKS as REPORT_TRACKS
from _review_helpers import TRACKS, assessment_files, comparison_file, comparison_files, copy_of, decide, exposure_count, files, positions, status
from test_study_lock import held_by_another_process

from hypotrail.core import canonical, contracts


@pytest.fixture(scope="module")
def bike(tmp_path_factory):
    """A Bike Study: `seasonal_7` (Control) against `ridge_v1` (Candidate) on `dev`, a repeated `assess` of the Control and a second `compare`."""
    track = TRACKS["bike"]
    base = tmp_path_factory.mktemp("listings-bike")
    study, control, candidate, first = track.compared(base)
    again = track.assess_again(study, control)
    from _review_helpers import compare

    second = compare(study, again["assessment_id"], candidate["assessment_id"])
    return study, {"control": control, "candidate": candidate, "again": again, "first": first, "second": second}


@pytest.fixture(scope="module")
def chinook(tmp_path_factory):
    """A Chinook Study: two Imports compared, an Episode of the Control failed, so the main delta is withheld (`value` null)."""
    study, control, candidate, comparison = TRACKS["chinook"].compared(tmp_path_factory.mktemp("listings-chinook"), failed={("D03", 2)}, repeats=3)
    return study, {"control": control, "candidate": candidate, "first": comparison}


@pytest.fixture
def built(request, tmp_path):
    """A private copy of the Study of the Track named by the parameter, with its ids."""
    study, ids = request.getfixturevalue(request.param)
    return copy_of(study, tmp_path / "copy" / "study"), ids


def assert_each_listing_is_the_records_on_disk(study, listing):
    on_disk = assessment_files(study)
    assert [entry["assessment_id"] for entry in listing["assessments"]] and {entry["assessment_id"] for entry in listing["assessments"]} == set(on_disk)
    assert len(listing["assessments"]) == len(on_disk)
    for entry in listing["assessments"]:
        assert entry == on_disk[entry["assessment_id"]]
    on_disk = comparison_files(study)
    assert {entry["comparison_id"] for entry in listing["comparisons"]} == set(on_disk) and len(listing["comparisons"]) == len(on_disk)
    for entry in listing["comparisons"]:
        assert entry == on_disk[entry["comparison_id"]]


# --- the two listings: every record, each equal to the stored record -------------------------------------------------------


@pytest.mark.parametrize("built", ["bike", "chinook"], indirect=True)
def test_status_lists_every_assessment_and_comparison_record_of_the_study_each_equal_to_its_file(built):
    study, ids = built
    listing = status(study)
    assert_each_listing_is_the_records_on_disk(study, listing)
    entry = next(e for e in listing["comparisons"] if e["comparison_id"] == ids["first"]["comparison_id"])
    assert (entry["left_assessment_id"], entry["right_assessment_id"]) == (ids["control"]["assessment_id"], ids["candidate"]["assessment_id"])
    assert entry["roles"] == {"control_assessment_id": ids["control"]["assessment_id"], "candidate_assessment_id": ids["candidate"]["assessment_id"]}


@pytest.mark.parametrize("built", ["bike"], indirect=True)
def test_the_bike_comparison_entry_carries_the_single_feature_warning_and_its_limitations(built):
    study, ids = built
    entry = next(e for e in status(study)["comparisons"] if e["comparison_id"] == ids["first"]["comparison_id"])
    assert "COMPARISON_SINGLE_FEATURE_BEATS" in [warning["code"] for warning in entry["warnings"]]
    assert entry["limitations"] == ids["first"]["limitations"] and entry["delta"] == ids["first"]["delta"]


@pytest.mark.parametrize("built", ["chinook"], indirect=True)
def test_the_chinook_comparison_entry_carries_a_withheld_main_delta_as_a_null_value(built):
    study, ids = built
    entry = next(e for e in status(study)["comparisons"] if e["comparison_id"] == ids["first"]["comparison_id"])
    assert entry["delta"]["value"] is None and entry["delta"]["reason"] == "coverage_incomplete"
    assert entry["warnings"] == ids["first"]["warnings"] and entry["limitations"] == ids["first"]["limitations"]


def test_a_study_just_created_lists_no_assessment_and_no_comparison(tmp_path):
    from _study_helpers import init_study

    study, _ = init_study(tmp_path)
    listing = status(study)
    assert (listing["assessments"], listing["comparisons"]) == ([], [])


# --- the order: the write journal ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("built", ["bike"], indirect=True)
def test_the_listings_are_in_the_order_of_the_write_journal_entries_that_name_each_record(built):
    study, _ = built
    listing = status(study)
    for kind, key in (("assessment", "assessments"), ("comparison", "comparisons")):
        at = positions(study, kind)
        listed = [entry[f"{kind}_id"] for entry in listing[key]]
        assert set(listed) <= set(at), kind  # every record of this Study is journaled
        assert listed == sorted(listed, key=at.__getitem__), kind
    assert (len(listing["assessments"]), len(listing["comparisons"])) == (3, 2)


@pytest.mark.parametrize("built", ["bike"], indirect=True)
def test_comparisons_no_journal_entry_names_come_first_in_the_order_of_their_ids(built):
    study, ids = built
    journaled = [entry["comparison_id"] for entry in status(study)["comparisons"]]
    source = json.loads(comparison_file(study, ids["first"]["comparison_id"]).read_text(encoding="utf-8"))
    written = ["ffffffff-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"]  # written in this order, out of id order
    for new_id in written:
        folder = Path(study) / "comparisons" / new_id
        folder.mkdir()
        (folder / "comparison.json").write_bytes(canonical.dumps({**source, "comparison_id": new_id}))
    assert [entry["comparison_id"] for entry in status(study)["comparisons"]] == sorted(written) + journaled


# --- a record that holds no `roles` -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("built", ["bike"], indirect=True)
def test_a_comparison_record_without_roles_is_listed_as_the_file_holds_it_without_roles(built):
    study, ids = built
    path = comparison_file(study, ids["first"]["comparison_id"])
    record = json.loads(path.read_text(encoding="utf-8"))
    del record["roles"]
    contracts.validate(record)  # `roles` is not required
    path.write_bytes(canonical.dumps(record))
    entry = next(e for e in status(study)["comparisons"] if e["comparison_id"] == ids["first"]["comparison_id"])
    assert entry == record and "roles" not in entry


# --- `status` only reads -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("built", ["bike", "chinook"], indirect=True)
def test_status_with_the_listings_writes_nothing_keeps_the_write_sequence_and_answers_while_another_writer_holds_the_lock(built):
    study, ids = built
    before = files(study)
    first = status(study)
    second = status(study)
    assert files(study) == before
    assert first["write_sequence"] == second["write_sequence"]
    with held_by_another_process(study):
        locked = status(study)
    assert locked["writer_alive"] is True
    assert [entry["comparison_id"] for entry in locked["comparisons"]] == [entry["comparison_id"] for entry in first["comparisons"]]
    assert ids["first"]["comparison_id"] in {entry["comparison_id"] for entry in locked["comparisons"]}


# --- `public_check` ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("track", ["bike", "chinook"])
def test_on_public_check_the_listings_hold_only_what_the_records_hold_and_reading_them_records_no_exposure(track, tmp_path):
    study, _, assessment_ids, comparison = REPORT_TRACKS[track].public_world(tmp_path)
    count = exposure_count(study)
    assert count > 0  # the Assessments and the Comparison of public_check Items each recorded one
    listing = status(study)
    assert_each_listing_is_the_records_on_disk(study, listing)
    assert {entry["assessment_id"] for entry in listing["assessments"]} == set(assessment_ids)
    assert [entry["comparison_id"] for entry in listing["comparisons"]] == [comparison["comparison_id"]]
    assert exposure_count(study) == count
