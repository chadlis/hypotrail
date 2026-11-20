"""Ticket #73: the freeze record, the Exposure journal, `check_informed`, and where `public_check` is now allowed.

No acceptance test of SPEC section 10 names these rules (SPEC section 2 "Gel et exposition", the GLOSSARY and the #1
amendment on Exposure do): each criterion and each Tightened line of the ticket has its own test below.
"""

import json
import os
from pathlib import Path

import pytest
from _assess_helpers import assess, fresh_study, observation_set_id, references_id, snapshot
from _chinook_helpers import init_chinook
from _compare_helpers import compare
from _exposure_helpers import (
    PUBLIC_CASES,
    REPEATS,
    assess_agent,
    compare_ids,
    correct_e01,
    edit_chinook_references,
    freezes,
    import_public,
    journal,
    public_lines,
)
from _revision_helpers import new_revision, snapshot_files, spec_of
from _study_helpers import examples_copy, init_study, run_json, run_ml

from hypotrail.agentic import counts, rescore
from hypotrail.agentic.declaration import load_workload
from hypotrail.core import artifacts, canonical, contracts, lock
from hypotrail.core.errors import HypotrailError
from hypotrail.ml import comparison as ml_comparison
from hypotrail.ml import metrics

MAE = "regression_mae_v1"
CHINOOK = Path(__file__).resolve().parent.parent / "examples" / "chinook"


def assessed(study, attempt, *more):
    code, payload, err = assess(study, observation_set_id(study, attempt), MAE, references_id(study), *more)
    assert code == 0, (payload, err)
    return payload["assessment"]


def bike_exposed(tmp_path, *configs):
    """(Study, {config: Attempt}, {config: Assessment}): each Configuration ran on public_check and was assessed."""
    study, attempts = fresh_study(tmp_path, *configs, partition="public_check")
    return study, attempts, {config: assessed(study, attempt) for config, attempt in attempts.items()}


def error_of(payload):
    error = payload["error"]
    assert set(error) == {"code", "message", "stage", "details"}
    return error


def status_of(study):
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    return payload


def alpha_changed(declaration):
    declaration["configurations"]["ridge_v1"]["ridge"]["alpha"] = 2.5


# --- AC1, Tightened A: the freeze record ---------------------------------------------------------------------------------------


def test_the_bike_freeze_record_holds_the_protocol_both_configurations_the_environment_and_the_code(tmp_path):
    study, attempts, _ = bike_exposed(tmp_path, "seasonal_7")
    (freeze,) = freezes(study)
    contracts.validate(freeze)
    spec = spec_of(study)
    assert freeze["protocol_digest"] == spec["protocol_digest"] and freeze["study_id"] == spec["study_id"] and freeze["revision_number"] == 1
    assert set(freeze["configuration_digests"]) == {"seasonal_7", "ridge_v1"}
    # the digest is of the declared content an Attempt records of the Configuration it ran
    declared = attempts["seasonal_7"]["effective_config"]["configuration"]["declared"]
    assert freeze["configuration_digests"]["seasonal_7"] == canonical.digest(declared)
    assert freeze["configuration_digests"]["ridge_v1"] != freeze["configuration_digests"]["seasonal_7"]
    environment = attempts["seasonal_7"]["code_environment"]
    assert freeze["environment"] == {"python": environment["python"], "dependency_lock_sha256": environment["dependency_lock"]["sha256"]}
    assert freeze["code"]["revision"] == environment["code_revision"]["commit"] and isinstance(freeze["code"]["dirty"], bool)


def test_the_chinook_freeze_record_holds_plain_and_verify(tmp_path):
    study, _ = init_chinook(tmp_path)
    assert assess_agent(study, import_public(tmp_path, study, "a"))[0] == 0
    (freeze,) = freezes(study)
    contracts.validate(freeze)
    assert freeze["protocol_digest"] == spec_of(study)["protocol_digest"]
    assert set(freeze["configuration_digests"]) == {"plain", "verify"}
    assert len(set(freeze["configuration_digests"].values())) == 2
    assert all(len(digest) == 64 for digest in freeze["configuration_digests"].values())


def test_every_journal_entry_points_to_a_freeze_record_written_before_it(tmp_path):
    study, _, _ = bike_exposed(tmp_path, "seasonal_7", "ridge_v1")
    (freeze,) = freezes(study)
    entries = journal(study)
    assert len(entries) == 2
    for entry in entries:
        contracts.validate(entry)
        assert entry["freeze_id"] == freeze["freeze_id"] and freeze["recorded_at"] <= entry["recorded_at"]


def test_the_freeze_record_is_written_once_by_the_first_command_and_never_rewritten(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7", "ridge_v1", partition="public_check")
    assert freezes(study) == [] and journal(study) == []  # run ml on public_check is not an Exposure
    assessed(study, attempts["seasonal_7"])
    first = (Path(study) / "revisions" / "1" / "freeze.json").read_bytes()
    assessed(study, attempts["ridge_v1"])
    assert (Path(study) / "revisions" / "1" / "freeze.json").read_bytes() == first
    assert len(freezes(study)) == 1 and len(journal(study)) == 2
    with pytest.raises(HypotrailError) as refusal:  # published bytes are immutable
        artifacts.publish_bytes(study, "revisions/1/freeze.json", b"{}", media_type="application/json", role="freeze")
    assert refusal.value.code == "ARTIFACT_IMMUTABLE"


def test_a_dev_assessment_writes_neither_a_freeze_record_nor_a_journal_entry(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    assessed(study, attempts["seasonal_7"])
    assert freezes(study) == [] and journal(study) == []
    assert not (Path(study) / "exposures").exists()


# --- AC2: the journal ----------------------------------------------------------------------------------------------------------


def test_an_assessment_of_public_check_items_appends_one_entry_naming_the_attempt_and_the_assessment(tmp_path):
    study, attempts, assessments = bike_exposed(tmp_path, "seasonal_7")
    (entry,) = journal(study)
    assert entry["attempt_ids"] == [attempts["seasonal_7"]["attempt_id"]]
    assert entry["assessment_ids"] == [assessments["seasonal_7"]["assessment_id"]] and entry["comparison_ids"] == []


def test_a_comparison_of_public_check_items_appends_one_entry_naming_both_sides_and_the_comparison(tmp_path):
    study, attempts, assessments = bike_exposed(tmp_path, "seasonal_7", "ridge_v1")
    code, payload, err = compare(study, assessments["seasonal_7"]["assessment_id"], assessments["ridge_v1"]["assessment_id"])
    assert code == 0, (payload, err)
    last = journal(study)[-1]
    assert len(journal(study)) == 3
    assert last["comparison_ids"] == [payload["comparison"]["comparison_id"]]
    assert last["assessment_ids"] == sorted(a["assessment_id"] for a in assessments.values())
    assert last["attempt_ids"] == sorted(a["attempt_id"] for a in attempts.values())


def test_an_imported_observation_set_is_an_exposure_too(tmp_path):
    study, _ = init_chinook(tmp_path)
    attempt = import_public(tmp_path, study, "imp")
    code, payload, err = assess_agent(study, attempt)
    assert code == 0, (payload, err)
    (entry,) = journal(study)
    assert entry["attempt_ids"] == [attempt["attempt_id"]] and entry["assessment_ids"] == [payload["assessment"]["assessment_id"]]


def test_an_entry_is_published_atomically_under_the_writer_lock_and_never_rewritten(tmp_path):
    study, attempts, assessments = bike_exposed(tmp_path, "seasonal_7")
    (path,) = sorted((Path(study) / "exposures").glob("*.json"))
    assert path.name.startswith("000001-") and not [p for p in Path(study).rglob("*") if p.name.endswith(artifacts.TEMP_SUFFIX)]
    with pytest.raises(HypotrailError) as refusal:
        artifacts.publish_bytes(study, f"exposures/{path.name}", b"{}", media_type="application/json", role="exposure")
    assert refusal.value.code == "ARTIFACT_IMMUTABLE"
    before = snapshot_files(study)
    with lock.writer_lock(study):  # another writer is at work: the command is refused at once and writes nothing
        code, payload, _ = assess(study, observation_set_id(study, attempts["seasonal_7"]), MAE, references_id(study))
    assert (code, error_of(payload)["code"]) == (6, "STUDY_LOCKED")
    assert snapshot_files(study) == before
    assessed(study, attempts["seasonal_7"])
    assert [p.name[:7] for p in sorted((Path(study) / "exposures").glob("*.json"))] == ["000001-", "000002-"]


# --- AC3: where public_check is allowed ----------------------------------------------------------------------------------------


def test_inside_a_study_both_bike_configurations_are_assessed_and_compared_on_the_184_public_check_items(tmp_path):
    study, _, assessments = bike_exposed(tmp_path, "seasonal_7", "ridge_v1")
    assert [a["counts"]["expected"] for a in assessments.values()] == [184, 184]
    code, payload, err = compare(study, assessments["seasonal_7"]["assessment_id"], assessments["ridge_v1"]["assessment_id"])
    assert code == 0, (payload, err)
    comparison = payload["comparison"]
    assert comparison["coverage"]["expected"] == comparison["coverage"]["paired"] == 184
    assert comparison["comparability"]["status"] == "compatible"
    assert len(journal(study)) == 3


def test_inside_a_study_the_12_chinook_public_check_cases_by_3_repeats_are_assessed_and_compared(tmp_path):
    study, _ = init_chinook(tmp_path)
    right = import_public(tmp_path, study, "right")
    wrong = import_public(tmp_path, study, "wrong", public_lines(wrong={("E01", 0), ("E01", 1)}))
    _, first, err = assess_agent(study, right)
    _, second, _ = assess_agent(study, wrong)
    assert first["assessment"]["counts"]["expected"] == len(PUBLIC_CASES) * REPEATS == 36
    assert first["assessment"]["counts"]["unscored"] == 0 and second["assessment"]["counts"]["incorrect"] > 0
    code, payload, err = compare_ids(study, first["assessment"]["assessment_id"], second["assessment"]["assessment_id"])
    assert code == 0, (payload, err)
    assert payload["comparison"]["coverage"]["expected"] == 36
    assert len(journal(study)) == 3 and journal(study)[-1]["comparison_ids"] == [payload["comparison"]["comparison_id"]]


def test_a_partition_other_than_dev_and_public_check_is_still_refused_and_writes_nothing(tmp_path):
    from _assess_helpers import construct

    study, attempts = fresh_study(tmp_path, "seasonal_7")
    train = construct(study, attempts["seasonal_7"], lambda rows: rows, provenance={"partition": "train"})
    before = snapshot_files(study)
    code, payload, _ = assess(study, train, MAE, references_id(study))
    assert (code, error_of(payload)["code"]) == (2, "ASSESSMENT_PARTITION_NOT_DEV")
    assert snapshot_files(study) == before and journal(study) == [] and freezes(study) == []


def test_the_entry_points_that_have_no_study_keep_their_refusal(tmp_path):
    workload = load_workload(CHINOOK)
    public = "E01"
    assert workload.partition_of(public) == "public_check"
    with pytest.raises(HypotrailError) as refusal:
        rescore.rescore_episodes([{"case_id": public, "repeat": 0}], {}, schema={}, workload=workload)
    assert refusal.value.code == "PUBLIC_CHECK_RESCORING_REFUSED"
    with pytest.raises(HypotrailError) as refusal:
        rescore.rescore_log("no-log.eval", {}, schema={}, expected=[(public, 0)], workload=workload)
    assert refusal.value.code == "PUBLIC_CHECK_RESCORING_REFUSED"
    with pytest.raises(HypotrailError) as refusal:
        counts.tally([{"case_id": public, "tool_error_codes": []}], workload=workload)
    assert refusal.value.code == "PUBLIC_CHECK_COUNTS_REFUSED"
    with pytest.raises(HypotrailError) as refusal:
        metrics.compute_metrics("p.csv", "r.csv", "m.csv", tmp_path, partition="public_check")
    assert refusal.value.code == "PUBLIC_CHECK_METRICS_REFUSED"
    with pytest.raises(HypotrailError) as refusal:
        ml_comparison.compare("a.csv", "b.csv", "r.csv", "m.csv", tmp_path / "out", tmp_path, partition="public_check")
    assert refusal.value.code == "PUBLIC_CHECK_COMPARISON_REFUSED"
    assert not (tmp_path / "out").exists()


# --- AC4, Tightened C and E2: check_informed for a Configuration ---------------------------------------------------------------


def test_a_configuration_changed_after_the_first_exposure_is_marked_on_its_attempt_assessment_and_comparison(tmp_path):
    study, attempts, assessments = bike_exposed(tmp_path, "seasonal_7")
    changed = examples_copy(tmp_path, edit=alpha_changed)
    code, payload, err = run_ml(study, "ridge_v1", "public_check", "ridge-changed", "--examples-dir", changed)
    assert code == 0, (payload, err)  # not refused, and no new Study revision is needed
    attempt = payload["attempt"]
    assert attempt["check_informed"] is True and spec_of(study)["revision_number"] == 1
    contracts.validate(attempt)
    candidate = assessed(study, attempt, "--examples-dir", changed)
    assert candidate["check_informed"] is True
    code, payload, err = compare(study, assessments["seasonal_7"]["assessment_id"], candidate["assessment_id"], "--examples-dir", changed)
    assert code == 0, (payload, err)
    assert payload["comparison"]["check_informed"] is True
    contracts.validate(payload["comparison"])


def test_a_configuration_added_after_the_first_exposure_is_marked(tmp_path):
    study, _, _ = bike_exposed(tmp_path, "seasonal_7")

    def add(declaration):
        declaration["configurations"]["ridge_v2"] = json.loads(json.dumps(declaration["configurations"]["ridge_v1"]))
        declaration["configurations"]["ridge_v2"]["ridge"]["alpha"] = 4.0

    code, payload, err = run_ml(study, "ridge_v2", "dev", "added", "--examples-dir", examples_copy(tmp_path, edit=add))
    assert code == 0, (payload, err)
    assert payload["attempt"]["check_informed"] is True


def test_a_configuration_the_freeze_holds_unchanged_is_not_marked(tmp_path):
    study, attempts, assessments = bike_exposed(tmp_path, "seasonal_7", "ridge_v1")
    code, payload, err = run_ml(study, "ridge_v1", "dev", "again")
    assert code == 0, (payload, err)
    assert "check_informed" not in payload["attempt"]
    assert all("check_informed" not in a for a in assessments.values()) and all("check_informed" not in a for a in attempts.values())
    dev = assessed(study, payload["attempt"])
    assert "check_informed" not in dev
    code, payload, err = compare(study, assessments["seasonal_7"]["assessment_id"], assessments["ridge_v1"]["assessment_id"])
    assert code == 0 and "check_informed" not in payload["comparison"]


def test_nothing_is_marked_before_the_first_exposure(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7", "ridge_v1")
    changed = examples_copy(tmp_path, edit=alpha_changed)
    code, payload, _ = run_ml(study, "ridge_v1", "dev", "early", "--examples-dir", changed)
    assert code == 0 and "check_informed" not in payload["attempt"]
    assert status_of(study)["check_informed"] == []


def test_an_import_has_no_configuration_digest_and_is_never_marked_through_a_configuration(tmp_path):
    study, _ = init_chinook(tmp_path)
    assert assess_agent(study, import_public(tmp_path, study, "first"))[0] == 0
    attempt = import_public(tmp_path, study, "second", public_lines(wrong={("E02", 0)}))
    code, payload, _ = assess_agent(study, attempt)
    assert code == 0 and "check_informed" not in attempt and "check_informed" not in payload["assessment"]
    assert status_of(study)["check_informed"] == []


# --- AC4, Tightened B4: a Protocol change is a new revision -------------------------------------------------------------------


def test_a_command_that_finds_another_protocol_than_the_revisions_is_refused_and_writes_nothing(tmp_path):
    study, _ = init_chinook(tmp_path)
    attempt = import_public(tmp_path, study, "imp")
    corrected = edit_chinook_references(tmp_path, correct_e01)
    before = snapshot_files(study)
    code, payload, err = assess_agent(study, attempt, "--examples-dir", corrected)
    error = error_of(payload)
    assert code == 3 and (error["code"], error["stage"]) == ("PROTOCOL_CHANGED", "exposure")
    assert error["details"]["expected_protocol_digest"] != error["details"]["actual_protocol_digest"]
    assert snapshot_files(study) == before and freezes(study) == [] and journal(study) == []
    assert "PROTOCOL_CHANGED" in err


def test_after_an_exposure_the_same_refusal_holds_and_the_journal_keeps_its_entries(tmp_path):
    study, _ = init_chinook(tmp_path)
    attempt = import_public(tmp_path, study, "imp")
    assert assess_agent(study, attempt)[0] == 0
    corrected = edit_chinook_references(tmp_path, correct_e01)
    before = snapshot_files(study)
    code, payload, _ = assess_agent(study, attempt, "--examples-dir", corrected)
    assert (code, error_of(payload)["code"]) == (3, "PROTOCOL_CHANGED")
    assert snapshot_files(study) == before and len(journal(study)) == 1


def test_a_revision_created_after_the_first_exposure_is_marked_has_its_own_freeze_and_leaves_the_earlier_one_unchanged(tmp_path):
    study, _ = init_chinook(tmp_path)
    attempt = import_public(tmp_path, study, "imp")
    first = assess_agent(study, attempt)[1]["assessment"]
    revision_one = spec_of(study)
    before = snapshot_files(study)
    corrected = edit_chinook_references(tmp_path, correct_e01)
    code, payload, err = new_revision(study, "--examples-dir", corrected)
    assert code == 0, (payload, err)
    two = spec_of(study)
    assert two["revision_number"] == 2 and two["check_informed"] is True
    assert not (Path(study) / "revisions" / "2" / "freeze.json").exists()  # taken at the revision's first public_check use
    assert (Path(study) / "revisions" / "1" / "study.json").read_bytes() == canonical.dumps(revision_one)
    after = snapshot_files(study)
    assert all(after[path] == digest for path, digest in before.items() if not path.endswith("study.json"))  # every earlier file, byte for byte
    # an Assessment of the new revision scores the Observation set recorded under revision 1 and names the earlier Assessment
    code, payload, err = assess_agent(study, attempt, "--examples-dir", corrected)
    assert code == 0, (payload, err)
    second = payload["assessment"]
    assert second["study_revision"]["number"] == 2 and second["observation_set_id"] == first["observation_set_id"]
    assert second["rescoring"]["earlier_assessment_id"] == first["assessment_id"] and second["rescoring"]["cause"] == "references_version"
    one, two_freeze = freezes(study)
    assert (one["revision_number"], two_freeze["revision_number"]) == (1, 2)
    assert two_freeze["protocol_digest"] == spec_of(study)["protocol_digest"] != one["protocol_digest"]
    entries = journal(study)
    assert [e["freeze_id"] for e in entries] == [one["freeze_id"], two_freeze["freeze_id"]]
    assert artifacts.read_verified(study, revision_one["artifacts"][1]["ref"])  # the earlier References set stays readable


def test_a_revision_created_before_any_exposure_is_not_marked(tmp_path):
    study, _ = init_chinook(tmp_path)
    corrected = edit_chinook_references(tmp_path, correct_e01)
    assert new_revision(study, "--examples-dir", corrected)[0] == 0
    assert "check_informed" not in spec_of(study)
    assert status_of(study)["check_informed"] == []


def test_the_first_exposure_of_the_study_counts_in_every_later_revision(tmp_path):
    study, _ = init_study(tmp_path)
    seasonal = fresh_attempt(study, "seasonal_7", "public_check", "one")
    assessed(study, seasonal)  # the Study's first Exposure, under revision 1

    def corrected_day(table):
        row = next(r for r in table if r["dteday"] == "2012-03-15")
        row["cnt"], row["registered"] = str(int(row["cnt"]) + 1000), str(int(row["registered"]) + 1000)

    revised = examples_copy(tmp_path, rows=corrected_day, name="revised")
    revised_and_changed = examples_copy(tmp_path, rows=corrected_day, edit=alpha_changed, name="revised-changed")
    assert new_revision(study, "--examples-dir", revised)[0] == 0 and spec_of(study)["check_informed"] is True
    unchanged = run_ml(study, "ridge_v1", "dev", "two", "--examples-dir", revised)[1]["attempt"]
    code, payload, err = run_ml(study, "ridge_v1", "dev", "three", "--examples-dir", revised_and_changed)
    assert code == 0, (payload, err)
    assert "check_informed" not in unchanged  # the first freeze holds ridge_v1 as it was: unmarked in revision 2 as in revision 1
    assert payload["attempt"]["check_informed"] is True  # a Configuration it does not hold is marked in every later revision too
    assert spec_of(study)["revision_number"] == 2


def fresh_attempt(study, config, partition, request_id):
    code, payload, err = run_ml(study, config, partition, request_id)
    assert code == 0, (payload, err)
    return payload["attempt"]


# --- AC5: what a Study with no journal entry says ----------------------------------------------------------------------------


def test_a_study_with_no_entry_reports_zero_exposures_and_says_any_earlier_exposure_is_unknown(tmp_path):
    study, _ = init_study(tmp_path)
    report = status_of(study)
    assert report["exposures"]["recorded_in_this_study"] == 0 and report["exposures"]["entries"] == []
    assert report["exposures"]["earlier_exposure"] == "unknown"
    assert "unknown" in report["exposures"]["statement"]
    assert report["freeze_records"] == [] and report["check_informed"] == []


def test_the_human_status_line_states_zero_exposures_and_unknown_earlier_exposure(tmp_path, capsys):
    from hypotrail import cli

    study, _ = init_study(tmp_path)
    assert cli.main(["status", "--study", str(study)]) == 0
    assert "0 Exposures recorded in this Study; any earlier exposure to public_check is unknown" in capsys.readouterr().out


def test_an_import_records_its_producers_exposure_to_public_check_as_unknown(tmp_path):
    study, _ = init_chinook(tmp_path)
    attempt = import_public(tmp_path, study, "imp")
    producer = attempt["effective_config"]["producer"]
    assert producer["saw_public_check"] == {"value": None, "origin": "unknown"}
    record = json.loads((Path(study) / "attempts" / attempt["attempt_id"] / "observation_set.json").read_text())
    assert record["provenance"]["saw_public_check"] == {"value": None, "origin": "unknown"} and "saw_public_check" in record["unknown_fields"]
    assert assess_agent(study, attempt)[0] == 0
    assert status_of(study)["exposures"]["earlier_exposure"] == "unknown"  # an Exposure recorded here settles nothing about elsewhere


# --- AC6: status ---------------------------------------------------------------------------------------------------------


def test_status_shows_the_freeze_record_the_journal_entries_and_every_check_informed_mark(tmp_path):
    study, attempts, assessments = bike_exposed(tmp_path, "seasonal_7")
    changed = examples_copy(tmp_path, edit=alpha_changed)
    marked = run_ml(study, "ridge_v1", "public_check", "ridge-changed", "--examples-dir", changed)[1]["attempt"]
    marked_assessment = assessed(study, marked, "--examples-dir", changed)
    comparison = compare(study, assessments["seasonal_7"]["assessment_id"], marked_assessment["assessment_id"], "--examples-dir", changed)[1]["comparison"]
    report = status_of(study)
    assert report["freeze_records"] == freezes(study) and len(report["freeze_records"]) == 1
    assert report["exposures"]["recorded_in_this_study"] == len(journal(study)) == 3 and report["exposures"]["entries"] == journal(study)
    assert sorted((m["kind"], m["id"]) for m in report["check_informed"]) == sorted(
        [("attempt", marked["attempt_id"]), ("assessment", marked_assessment["assessment_id"]), ("comparison", comparison["comparison_id"])]
    )


def test_status_marks_a_revision_created_after_the_first_exposure(tmp_path):
    study, _ = init_chinook(tmp_path)
    assert assess_agent(study, import_public(tmp_path, study, "imp"))[0] == 0
    assert new_revision(study, "--examples-dir", edit_chinook_references(tmp_path, correct_e01))[0] == 0
    report = status_of(study)
    assert report["check_informed"] == [{"kind": "revision", "id": spec_of(study)["revision"], "revision_number": 2}]


# --- Tightened J: --json and errors --------------------------------------------------------------------------------------------


def test_with_json_a_refusal_of_the_new_checks_is_one_object_with_code_message_stage_and_details(tmp_path, capsys):
    from hypotrail import cli

    study, _ = init_chinook(tmp_path)
    attempt = import_public(tmp_path, study, "imp")
    corrected = edit_chinook_references(tmp_path, correct_e01)
    capsys.readouterr()
    code = cli.main(["assess", "--study", str(study), "--observations", observation_set_of_attempt(study, attempt), "--scorer", "chinook_contract_v1",
                     "--references", references_of(study), "--examples-dir", str(corrected), "--json"])
    out, err = capsys.readouterr()
    payload = json.loads(out)  # stdout holds exactly one JSON object
    assert code == 3 and payload["ok"] is False and error_of(payload)["code"] == "PROTOCOL_CHANGED"
    assert "PROTOCOL_CHANGED" in err and os.environ.get("HYPOTRAIL_ANTHROPIC_API_KEY", "x") not in json.dumps(payload["error"]["details"])


def observation_set_of_attempt(study, attempt):
    return json.loads((Path(study) / "attempts" / attempt["attempt_id"] / "observation_set.json").read_text())["observation_set_id"]


def references_of(study):
    return next(e["artifact_id"] for e in spec_of(study)["artifacts"] if e["ref"]["role"] == "references")


def test_a_library_comparison_of_public_check_items_without_a_workload_basis_is_refused_with_a_code_and_writes_nothing(tmp_path):
    from hypotrail.core import comparison

    study, _, assessments = bike_exposed(tmp_path, "seasonal_7", "ridge_v1")
    before = snapshot_files(study)
    with pytest.raises(HypotrailError) as refusal:
        comparison.compare(study, assessments["seasonal_7"]["assessment_id"], assessments["ridge_v1"]["assessment_id"])
    assert (refusal.value.code, refusal.value.stage) == ("WORKLOAD_BASIS_REQUIRED", "exposure")
    assert snapshot_files(study) == before
