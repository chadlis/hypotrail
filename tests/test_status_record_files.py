"""The key `record_files` of `status --json`: the file of the Study that holds each record of the four listings (chadlis/hypotrail#228).

"For every Study, the object of `status --json` and of `status --since N --json` holds `record_files`: a list with one entry per record
of the listings `decisions`, `declared_deviations`, `assessments` and `comparisons`, in that order, which is the order of
`core/state.py:138-141`, and in each listing's order; each entry holds exactly `kind`, `id` and `path`; `path` is relative to the Study
folder, written with `/`, and is a file of the Study that, read as JSON, is the record of that id." (#228, T2-1)
"""

import json
from pathlib import PurePosixPath

import pytest
from _client_helpers import bike_withheld_study, chinook_decided_study, chinook_withheld_study, result_changed_study
from _deviation_helpers import declare
from _study_helpers import init_study, run_json

# Each listing of `status --json` that `record_files` names, in its order, with the kind of its entries and the key of a record's id.
LISTINGS = (
    ("decisions", "decision", "decision_id"),
    ("declared_deviations", "declared_deviation", "declared_deviation_id"),
    ("assessments", "assessment", "assessment_id"),
    ("comparisons", "comparison", "comparison_id"),
)


def with_a_deviation(study):
    """`study` after a Declared deviation that cites its first Attempt."""
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    declare(study, [payload["attempts"][0]["attempt_id"]])
    return study


@pytest.fixture(scope="module")
def studies(tmp_path_factory):
    """{name: folder}: a Bike Study with two Decisions, a Declared deviation and three revisions; a Chinook Study with a Decision and a
    Declared deviation; a Study just made by `init`; and the two kept Studies whose Comparison withholds its delta."""
    return {
        "bike": with_a_deviation(result_changed_study(tmp_path_factory.mktemp("bike"))),
        "chinook": with_a_deviation(chinook_decided_study(tmp_path_factory.mktemp("chinook"))),
        "init": init_study(tmp_path_factory.mktemp("init"))[0],
        "bike-withheld": bike_withheld_study(tmp_path_factory.mktemp("bike-withheld")),
        "chinook-withheld": chinook_withheld_study(tmp_path_factory.mktemp("chinook-withheld")),
    }


def status(study, since):
    code, payload, err = run_json("status", "--study", study, *([] if since is None else ["--since", since]))
    assert code == 0, (payload, err)
    return payload


@pytest.mark.parametrize("since", [None, 0], ids=["status", "status --since 0"])
@pytest.mark.parametrize("name", ["bike", "chinook"])
def test_record_files_names_each_record_of_the_four_listings_in_their_order_with_the_file_that_holds_it(studies, name, since):
    payload = status(studies[name], since)
    assert "record_files" in payload, sorted(payload)
    expected = [(kind, record[key]) for listing, kind, key in LISTINGS for record in payload[listing]]
    assert {kind for kind, _ in expected} == {kind for _, kind, _ in LISTINGS}, "the Study holds each kind of record"
    assert [(entry["kind"], entry["id"]) for entry in payload["record_files"]] == expected
    keys = {kind: key for _, kind, key in LISTINGS}
    for entry in payload["record_files"]:
        assert set(entry) == {"kind", "id", "path"}, entry
        path = PurePosixPath(entry["path"])
        assert "\\" not in entry["path"] and not path.is_absolute() and ".." not in path.parts, entry
        held = studies[name] / entry["path"]
        assert held.is_file(), entry
        assert json.loads(held.read_text(encoding="utf-8"))[keys[entry["kind"]]] == entry["id"], entry


def test_record_files_of_a_study_just_made_by_init_is_an_empty_list(studies):
    for since in (None, 0):
        assert status(studies["init"], since)["record_files"] == []


def withheld_problems(study, payload) -> list:
    """Each value that the file of an Assessment or a Comparison holds and that its entry in the listing of `payload`, the object of
    `status --json`, does not."""
    listed = {(kind, record[key]): record for listing, kind, key in LISTINGS for record in payload[listing]}
    problems = []
    for entry in payload["record_files"]:
        if entry["kind"] in ("assessment", "comparison"):
            stored = json.loads((study / entry["path"]).read_text(encoding="utf-8"))
            shown = listed[(entry["kind"], entry["id"])]
            problems += [(entry["path"], key) for key in stored if key not in shown or shown[key] != stored[key]]
    return problems


@pytest.mark.parametrize("name", ["bike-withheld", "chinook-withheld"])
def test_the_file_of_each_assessment_and_comparison_holds_no_value_that_its_entry_in_status_does_not_hold_on_a_study_that_withholds_its_delta(studies, name):
    payload = status(studies[name], None)
    assert any(comparison["delta"]["value"] is None for comparison in payload["comparisons"]), "the Comparison withholds its delta"
    assert withheld_problems(studies[name], payload) == []


def test_a_comparison_file_given_one_key_more_than_its_entry_is_found(studies, tmp_path):
    import shutil

    study = tmp_path / "study"
    shutil.copytree(studies["chinook-withheld"], study)
    payload = status(study, None)
    [entry] = [each for each in payload["record_files"] if each["kind"] == "comparison"]
    # The listing is built from the stored record, so the key is planted in the file after the read.
    stored = json.loads((study / entry["path"]).read_text(encoding="utf-8"))
    (study / entry["path"]).write_text(json.dumps({**stored, "zq_planted": 1}), encoding="utf-8")
    assert withheld_problems(study, payload) == [(entry["path"], "zq_planted")]
