"""Tickets #70 (A2) and #73 (Tightened B4, D): `init --study DIR --new-revision` adds a StudySpec revision to a Study.

A corrected References set changes the Protocol, so it is added through a new revision. Earlier revisions
and everything they reference stay readable and byte-identical. The freeze record, the Exposure journal and
the `check_informed` mark belong to #73 and are not built here.
"""

import json

import pytest
from _chinook_helpers import init_chinook
from _revision_helpers import corrected_chinook_references, entry_of, error_of, new_revision, snapshot_files, spec_of
from _study_helpers import examples_copy, init_study, run_cli, run_json, run_ml

from hypotrail.core import artifacts, contracts
from hypotrail.core.errors import EXIT_INTEGRITY_REFUSED, EXIT_INVALID_INPUT


def correct_d03(records):
    records["D03"].update(rows=[[1300]], reference_version="chinook-references/2")


def bike_rows_with_a_corrected_day(table):
    row = next(r for r in table if r["dteday"] == "2012-03-15")
    row["cnt"], row["registered"] = str(int(row["cnt"]) + 1000), str(int(row["registered"]) + 1000)  # the data checks keep cnt = casual + registered


# --- a corrected References set is a new revision, beside the old set ----------------------------------------------------------


def test_a_corrected_references_set_is_added_as_a_new_artifact_with_its_own_version_and_digest(tmp_path):
    study, _ = init_chinook(tmp_path)
    first = spec_of(study)
    corrected = corrected_chinook_references(tmp_path, correct_d03)
    code, payload, err = new_revision(study, "--examples-dir", corrected)
    assert code == 0, (payload, err)
    spec = spec_of(study)
    contracts.validate(spec)
    assert payload == {"ok": True, "study": spec}
    old, new = entry_of(first, "references"), entry_of(spec, "references")
    assert (old["version"], new["version"]) == (1, 2)
    assert new["ref"]["sha256"] != old["ref"]["sha256"] and new["artifact_id"] != old["artifact_id"]
    assert new["ref"]["path"] != old["ref"]["path"]
    assert artifacts.read_verified(study, new["ref"]) != artifacts.read_verified(study, old["ref"])
    assert artifacts.read_verified(study, old["ref"])  # the earlier set stays, and still matches its digest


def test_what_the_correction_did_not_touch_is_carried_over_unchanged(tmp_path):
    study, _ = init_chinook(tmp_path)
    first = spec_of(study)
    code, _, err = new_revision(study, "--examples-dir", corrected_chinook_references(tmp_path, correct_d03))
    assert code == 0, err
    spec = spec_of(study)
    for role in ("memberships", "answer_schema"):
        assert entry_of(spec, role) == entry_of(first, role)
    assert spec["dataset_refs"] == first["dataset_refs"]
    assert spec["protocol_digest"] != first["protocol_digest"]
    for field in ("study_id", "workload", "domain", "question", "objective", "protocol_id", "primary_metric", "limitations"):
        assert spec[field] == first[field], field


def test_the_new_revision_numbers_and_chains_itself_to_the_one_before(tmp_path):
    study, _ = init_chinook(tmp_path)
    first = spec_of(study)
    assert first["revision_number"] == 1 and "previous_revision" not in first
    new_revision(study, "--examples-dir", corrected_chinook_references(tmp_path, correct_d03))
    second = spec_of(study)
    assert second["revision_number"] == 2 and second["previous_revision"] == first["revision"]
    assert second["revision"] != first["revision"]

    def correct_d01(records):
        correct_d03(records)
        records["D01"].update(rows=[[3504]])

    new_revision(study, "--examples-dir", corrected_chinook_references(tmp_path, correct_d01, name="again"))
    third = spec_of(study)
    assert third["revision_number"] == 3 and third["previous_revision"] == second["revision"]
    assert entry_of(third, "references")["version"] == 3


def test_every_earlier_revision_stays_readable_and_every_earlier_file_keeps_its_digest(tmp_path):
    study, _ = init_chinook(tmp_path)
    first_bytes = (study / "study.json").read_bytes()
    before = snapshot_files(study)
    new_revision(study, "--examples-dir", corrected_chinook_references(tmp_path, correct_d03))
    after = snapshot_files(study)
    assert {path: digest for path, digest in after.items() if path in before and path != "study.json"} == {
        path: digest for path, digest in before.items() if path != "study.json"
    }
    assert (study / "revisions" / "1" / "study.json").read_bytes() == first_bytes
    assert (study / "revisions" / "2" / "study.json").read_bytes() == (study / "study.json").read_bytes()
    contracts.validate(json.loads(first_bytes))
    assert set(after) - set(before) == {
        "revisions/1/study.json",
        "revisions/2/study.json",
        entry_of(spec_of(study), "references")["ref"]["path"],
        "write_journal/000003.json",  # the two entries of `init --new-revision` (chadlis/hypotrail#107)
        "write_journal/000004.json",
    }


def test_the_bike_study_takes_a_corrected_day_as_a_new_revision_with_a_new_dataset_and_references(tmp_path):
    study, _ = init_study(tmp_path)
    first = spec_of(study)
    examples = examples_copy(tmp_path, rows=bike_rows_with_a_corrected_day)
    code, payload, err = new_revision(study, "--examples-dir", examples)
    assert code == 0, (payload, err)
    spec = spec_of(study)
    contracts.validate(spec)
    assert spec["revision_number"] == 2 and spec["previous_revision"] == first["revision"]
    assert spec["dataset_refs"][0]["sha256"] != first["dataset_refs"][0]["sha256"]
    assert entry_of(spec, "references")["version"] == 2 and entry_of(spec, "memberships")["version"] == 1
    assert artifacts.read_verified(study, first["dataset_refs"][0]) and artifacts.read_verified(study, entry_of(first, "references")["ref"])
    old = artifacts.read_verified(study, entry_of(first, "references")["ref"]).decode().splitlines()
    new = artifacts.read_verified(study, entry_of(spec, "references")["ref"]).decode().splitlines()
    assert [i for i, (a, b) in enumerate(zip(old, new)) if a != b] and len(old) == len(new)


def test_a_request_refused_for_a_changed_protocol_is_accepted_under_the_new_revision(tmp_path):
    study, _ = init_study(tmp_path)
    examples = examples_copy(tmp_path, rows=bike_rows_with_a_corrected_day)
    code, payload, _ = run_ml(study, "seasonal_7", "dev", "before", "--examples-dir", examples)
    assert (code, error_of(payload)["code"]) == (EXIT_INTEGRITY_REFUSED, "PROTOCOL_CHANGED")
    assert new_revision(study, "--examples-dir", examples)[0] == 0
    code, payload, err = run_ml(study, "seasonal_7", "dev", "after", "--examples-dir", examples)
    assert code == 0, (payload, err)
    assert payload["attempt"]["effective_config"]["protocol"]["protocol_digest"] == spec_of(study)["protocol_digest"]


# --- refusals ---------------------------------------------------------------------------------------------------------------------


def test_a_workload_whose_protocol_did_not_change_is_refused_and_nothing_is_written(tmp_path):
    study, _ = init_chinook(tmp_path)
    before = snapshot_files(study)
    code, payload, _ = new_revision(study)
    error = error_of(payload)
    assert (code, error["code"], error["stage"]) == (EXIT_INVALID_INPUT, "PROTOCOL_UNCHANGED", "study")
    assert set(error["details"]) == {"protocol_digest", "revision_number"}
    assert snapshot_files(study) == before


def test_a_new_revision_names_no_workload_and_a_new_study_names_one(tmp_path):
    study, _ = init_chinook(tmp_path)
    before = snapshot_files(study)
    code, payload, _ = run_json("init", "--study", study, "--new-revision", "--workload", "chinook")
    error = error_of(payload)
    assert (code, error["code"], error["stage"]) == (EXIT_INVALID_INPUT, "INVALID_ARGUMENTS", "config")
    assert error["details"] == {"command": "hypotrail init", "workload": "chinook"}
    code, payload, _ = run_json("init", "--study", tmp_path / "none")
    error = error_of(payload)
    assert (code, error["code"], error["stage"]) == (EXIT_INVALID_INPUT, "INVALID_ARGUMENTS", "config")
    assert error["details"] == {"command": "hypotrail init"} and "--workload" in error["message"]
    assert snapshot_files(study) == before and not (tmp_path / "none").exists()


HAND_BUILT_INIT_REFUSALS = {
    "read_sequence_given_to_a_new_study": (["--workload", "chinook", "--read-sequence", "0"], {"command": "hypotrail init"}),
    "neither_workload_nor_new_revision": ([], {"command": "hypotrail init"}),
    "new_revision_with_a_workload": (["--new-revision", "--workload", "chinook"], {"command": "hypotrail init", "workload": "chinook"}),
}


@pytest.mark.parametrize("case", sorted(HAND_BUILT_INIT_REFUSALS))
def test_each_init_refusal_built_by_hand_gives_the_whole_details_with_the_command_as_hypotrail_init_and_writes_nothing(tmp_path, case):
    flags, details = HAND_BUILT_INIT_REFUSALS[case]
    study, _ = init_chinook(tmp_path)
    before = snapshot_files(study)
    target = study if "--new-revision" in flags else tmp_path / "none"
    code, payload, _ = run_json("init", "--study", target, *flags)
    error = error_of(payload)
    assert (code, error["code"], error["stage"], error["details"]) == (EXIT_INVALID_INPUT, "INVALID_ARGUMENTS", "config", details)
    assert snapshot_files(study) == before and not (tmp_path / "none").exists()


def test_a_folder_that_is_no_study_has_no_revision_to_add(tmp_path):
    (tmp_path / "empty").mkdir()
    code, payload, _ = new_revision(tmp_path / "empty")
    assert (code, error_of(payload)["code"]) == (EXIT_INVALID_INPUT, "STUDY_NOT_FOUND")
    assert list((tmp_path / "empty").iterdir()) == []  # not even a lock file


def test_data_that_no_longer_matches_its_lock_is_refused_before_anything_is_written(tmp_path):
    study, _ = init_study(tmp_path)
    examples = examples_copy(tmp_path)
    data_file = examples / "bike_day" / "data" / "day.csv"
    content = bytearray(data_file.read_bytes())
    content[len(content) // 2] ^= 1
    data_file.write_bytes(bytes(content))
    before = snapshot_files(study)
    code, payload, _ = new_revision(study, "--examples-dir", examples)
    assert (code, error_of(payload)["code"]) == (EXIT_INTEGRITY_REFUSED, "DATA_INTEGRITY")
    assert snapshot_files(study) == before


def test_a_revision_interrupted_before_the_current_spec_was_replaced_is_completed_by_running_it_again(tmp_path):
    study, _ = init_chinook(tmp_path)
    first_bytes = (study / "study.json").read_bytes()
    corrected = corrected_chinook_references(tmp_path, correct_d03)
    new_revision(study, "--examples-dir", corrected)
    done = spec_of(study)
    (study / "study.json").write_bytes(first_bytes)  # the state a writer killed before its last step leaves
    code, payload, err = new_revision(study, "--examples-dir", corrected)
    assert code == 0, (payload, err)
    assert spec_of(study) == done


# --- the output ---------------------------------------------------------------------------------------------------------------------


def test_the_human_line_names_the_revision_and_the_protocol_digest(tmp_path):
    study, _ = init_chinook(tmp_path)
    code, out, err = run_cli("init", "--study", study, "--new-revision", "--examples-dir", corrected_chinook_references(tmp_path, correct_d03))
    spec = spec_of(study)
    assert code == 0 and err == ""
    assert out.count("\n") == 1 and f"revision 2" in out and spec["protocol_digest"][:12] in out


def test_status_lists_every_revision_with_its_protocol_and_its_artifacts(tmp_path):
    study, _ = init_chinook(tmp_path)
    first = spec_of(study)
    new_revision(study, "--examples-dir", corrected_chinook_references(tmp_path, correct_d03))
    second = spec_of(study)
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, err
    assert payload["study"]["revision_number"] == 2 and payload["study"]["revision"] == second["revision"]
    assert [r["revision_number"] for r in payload["revisions"]] == [1, 2]
    for listed, spec in zip(payload["revisions"], (first, second)):
        assert listed["revision"] == spec["revision"] and listed["protocol_digest"] == spec["protocol_digest"]
        assert {a["artifact_id"]: (a["version"], a["sha256"]) for a in listed["artifacts"]} == {
            e["artifact_id"]: (e["version"], e["ref"]["sha256"]) for e in spec["artifacts"]
        }
