"""Ticket #64, AC1 and AC4: `init` creates a Study whose StudySpec is valid and whose Protocol digest is stable."""

import json

import pytest
from _study_helpers import EXAMPLES, examples_copy, init_study, run_cli, run_json, sha256

from hypotrail.core import artifacts, canonical, contracts
from hypotrail.core.errors import EXIT_INTEGRITY_REFUSED, EXIT_INVALID_INPUT


def spec_of(study):
    return json.loads((study / "study.json").read_text(encoding="utf-8"))


def test_init_writes_a_study_spec_valid_against_the_contract_schema(tmp_path):
    study, payload = init_study(tmp_path)
    spec = spec_of(study)
    contracts.validate(spec)
    assert payload["ok"] is True and payload["study"] == spec
    assert (study / "study.json").read_bytes() == canonical.dumps(spec)  # a record is canonical JSON
    assert spec["kind"] == "study" and spec["schema_version"] == "study/1"
    assert spec["domain"] == "regression"
    assert spec["primary_metric"] == {"id": "mae", "direction": "lower_is_better", "unit": "rentals per day"}
    for field in ("study_id", "question", "objective", "protocol_id"):
        assert spec[field]
    assert len(spec["revision"]) == 64 and len(spec["protocol_digest"]) == 64
    assert spec["limitations"] and all(spec["limitations"])


def test_the_question_the_objective_and_the_limitations_come_from_the_workload_declaration(tmp_path):
    declared = json.loads((EXAMPLES / "bike_day" / "workload.json").read_text(encoding="utf-8"))
    study, _ = init_study(tmp_path)
    spec = spec_of(study)
    assert spec["question"] == declared["question"]
    assert spec["objective"] == declared["objective"]
    assert spec["limitations"] == declared["limitations"]


def test_the_dataset_the_memberships_and_the_references_are_study_artifacts_with_digests_and_an_id_each(tmp_path):
    study, _ = init_study(tmp_path)
    spec = spec_of(study)
    assert len(spec["dataset_refs"]) == 1
    dataset = spec["dataset_refs"][0]
    assert dataset["role"] == "dataset" and dataset["sha256"] == sha256(EXAMPLES / "bike_day" / "data" / "day.csv")
    by_role = {entry["ref"]["role"]: entry for entry in spec["artifacts"]}
    assert set(by_role) == {"memberships", "references"}
    ids = [entry["artifact_id"] for entry in spec["artifacts"]]
    assert len(set(ids)) == 2 and all(ids)
    for entry in spec["artifacts"]:
        data = artifacts.read_verified(study, entry["ref"])
        assert data.startswith(b"row_id,")
    memberships = (study / by_role["memberships"]["ref"]["path"]).read_text().splitlines()
    references = (study / by_role["references"]["ref"]["path"]).read_text().splitlines()
    assert len(memberships) == 731 + 1  # all 731 dates, 7 of them excluded
    assert len(references) == 358 + 182 + 184 + 1  # one row per Item of every Partition


def test_the_workload_is_copied_into_the_study_and_referenced(tmp_path):
    study, _ = init_study(tmp_path)
    spec = spec_of(study)
    declaration = spec["declaration_ref"]
    assert declaration["role"] == "workload_declaration"
    assert artifacts.read_verified(study, declaration) == (EXAMPLES / "bike_day" / "workload.json").read_bytes()
    assert spec["workload"] == "bike_day"
    assert (study / spec["dataset_refs"][0]["path"]).read_bytes() == (EXAMPLES / "bike_day" / "data" / "day.csv").read_bytes()


def test_the_protocol_digest_is_stable_across_two_inits_and_across_the_key_order_of_a_configuration(tmp_path):
    one, _ = init_study(tmp_path, name="one")

    def reorder(declaration):
        ridge = declaration["configurations"]["ridge_v1"]
        declaration["configurations"]["ridge_v1"] = dict(reversed(list(ridge.items())))
        declaration["configurations"] = dict(reversed(list(declaration["configurations"].items())))

    other, _ = init_study(tmp_path, name="two", examples=examples_copy(tmp_path, edit=reorder))
    assert spec_of(one)["protocol_digest"] == spec_of(other)["protocol_digest"]


def test_the_protocol_digest_does_not_change_when_a_configuration_changes(tmp_path):
    one, _ = init_study(tmp_path, name="one")

    def change(declaration):
        declaration["configurations"]["ridge_v1"]["ridge"]["alpha"] = 10.0
        declaration["configurations"]["seasonal_7"]["post_processing"]["clip_min"] = 5
        declaration["configurations"]["new_one"] = declaration["configurations"]["seasonal_7"]

    other, _ = init_study(tmp_path, name="two", examples=examples_copy(tmp_path, edit=change))
    assert spec_of(one)["protocol_digest"] == spec_of(other)["protocol_digest"]


def test_the_protocol_digest_changes_when_a_partition_range_changes(tmp_path):
    one, _ = init_study(tmp_path, name="one")

    def shift(declaration):
        declaration["partitions"]["dev"][1] = "2012-06-29"
        declaration["partitions"]["public_check"][0] = "2012-06-30"

    other, _ = init_study(tmp_path, name="two", examples=examples_copy(tmp_path, edit=shift))
    assert spec_of(one)["protocol_digest"] != spec_of(other)["protocol_digest"]
    assert spec_of(one)["revision"] != spec_of(other)["revision"]


def test_the_protocol_digest_changes_when_the_references_change(tmp_path):
    one, _ = init_study(tmp_path, name="one")

    def correct(table):  # one target changed, the lock of the copy rewritten: cnt = casual + registered still holds
        row = next(r for r in table if r["dteday"] == "2012-03-15")
        row["cnt"], row["registered"] = str(int(row["cnt"]) + 1), str(int(row["registered"]) + 1)

    other, _ = init_study(tmp_path, name="two", examples=examples_copy(tmp_path, rows=correct))
    assert spec_of(one)["protocol_digest"] != spec_of(other)["protocol_digest"]
    refs = lambda study: {e["ref"]["role"]: e for e in spec_of(study)["artifacts"]}
    assert refs(one)["references"]["artifact_id"] != refs(other)["references"]["artifact_id"]
    assert refs(one)["memberships"]["artifact_id"] == refs(other)["memberships"]["artifact_id"]


def test_init_verifies_the_data_against_its_lock_before_writing_anything(tmp_path):
    examples = examples_copy(tmp_path)
    data = examples / "bike_day" / "data" / "day.csv"
    data.write_bytes(data.read_bytes().replace(b"2011-01-01", b"2011-01-02", 1))
    study = tmp_path / "study"
    code, payload, _ = run_json("init", "--workload", "bike_day", "--study", study, "--examples-dir", examples)
    assert code == EXIT_INTEGRITY_REFUSED and payload["error"]["code"] == "DATA_INTEGRITY"
    assert not study.exists()


def test_init_refuses_an_existing_study_and_an_unknown_or_other_track_workload(tmp_path):
    study, _ = init_study(tmp_path)
    before = (study / "study.json").read_bytes()
    code, payload, _ = run_json("init", "--workload", "bike_day", "--study", study)
    assert code == EXIT_INVALID_INPUT and payload["error"]["code"] == "STUDY_EXISTS"
    assert (study / "study.json").read_bytes() == before
    code, payload, _ = run_json("init", "--workload", "nope", "--study", tmp_path / "other")
    assert code == EXIT_INVALID_INPUT and payload["error"]["code"] == "UNKNOWN_WORKLOAD"
    code, payload, _ = run_json("init", "--workload", "chinook", "--study", tmp_path / "chinook")
    assert code == EXIT_INVALID_INPUT and payload["error"]["code"] == "WORKLOAD_TRACK_NOT_SUPPORTED"
    assert not (tmp_path / "chinook").exists()


def test_init_in_human_mode_prints_one_line_and_no_json_flag_is_needed(tmp_path):
    code, out, err = run_cli("init", "--workload", "bike_day", "--study", tmp_path / "study")
    assert code == 0 and "study" in out and err == ""
    assert (tmp_path / "study" / "study.json").is_file()


@pytest.mark.parametrize("key", ["question", "objective", "limitations"])
def test_init_refuses_a_workload_that_does_not_declare_what_the_study_spec_needs(tmp_path, key):
    examples = examples_copy(tmp_path, edit=lambda declaration: declaration.pop(key))
    study = tmp_path / "study"
    code, payload, _ = run_json("init", "--workload", "bike_day", "--study", study, "--examples-dir", examples)
    assert code == EXIT_INVALID_INPUT
    assert payload["error"]["code"] == "DECLARATION_INCOMPLETE" and payload["error"]["details"]["key"] == key
    assert not study.exists()
