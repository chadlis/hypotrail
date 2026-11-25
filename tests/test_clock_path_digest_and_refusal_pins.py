"""Pins of what is written in more than one place before each is written once, kept unchanged by the change that does it.

- The time: each timestamp a record holds is an ISO string in UTC, for the manifest of a `run ml` and of an `import ml` Attempt, an
  Assessment of each Track, a freeze record, an Exposure entry and a recovered Attempt.
- The paths: a revision's StudySpec is at `revisions/<n>/study.json` and its freeze record at `revisions/<n>/freeze.json`.
- The parameters file: `run ml` with `ridge_v1` publishes `sklearn_params.json` with the role `effective_parameters`.
- The file digests: `sha256_before` and `sha256_after` of `DATABASE_CHANGED` from `run agent`, `database_sha256` of the record of an
  execution from `run agent`, and `actual_sha256` of a destination file that differs from its lock in `data fetch`: each is the
  SHA-256 of the file's bytes.
- The refusals: the code, the message, the stage, the keys of `details` and the exit code of `SCENARIOS_NOT_DECLARED` and
  `DATABASE_CHANGED`, at each of the two places that refuse with it, and of `SECRET_IN_OUTPUT` from `run agent`.

The spike's `run_live` is called in `tests/test_live.py` only, so its two pins, `database_sha256` and `SECRET_IN_OUTPUT`, are there.

No provider is called: an agent execution runs Inspect's mock model, and `data fetch` reads a server on the loopback interface.
"""

import datetime
import hashlib
import json
from pathlib import Path

import pytest
from _assess_helpers import assess, fresh_study, observation_set_id, references_id
from _chinook_helpers import FIXTURE, chinook_examples, database_of, fixture_population, import_agent, init_chinook
from _exposure_helpers import assess_agent, freezes, journal
from _fetch_helpers import Stand, fetch, source, write_lock
from _import_helpers import import_ml, ready
from _revision_helpers import new_revision
from _run_agent_helpers import FAKE_KEY, answering_with, error_of, fixture, live, ok, patch_model, read
from _study_helpers import EXAMPLES, examples_copy, init_study, run_json
from test_decision_history import corrected_day
from test_run_ml import killed

from hypotrail.agentic import fixture as agentic_fixture
from hypotrail.agentic import runner
from hypotrail.core.errors import EXIT_INFRASTRUCTURE, EXIT_INTEGRITY_REFUSED, EXIT_INVALID_INPUT, HypotrailError

MAE = "regression_mae_v1"


def is_utc_iso(value) -> bool:
    """Whether `value` is the ISO string of an instant in UTC, written as `datetime.isoformat` writes it."""
    if not isinstance(value, str):
        return False
    instant = datetime.datetime.fromisoformat(value)
    return instant.utcoffset() == datetime.timedelta(0) and instant.isoformat() == value


def digest_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_of(study, attempt_id) -> dict:
    return json.loads((Path(study) / "attempts" / attempt_id / "attempt.json").read_text(encoding="utf-8"))


# --- the time ------------------------------------------------------------------------------------------------------------------


def test_the_manifest_of_a_run_ml_attempt_holds_its_start_and_its_end_as_iso_strings_in_utc(tmp_path):
    _, attempts = fresh_study(tmp_path, "seasonal_7")
    manifest = attempts["seasonal_7"]
    assert is_utc_iso(manifest["started_at"])
    assert is_utc_iso(manifest["finished_at"])


def test_the_manifest_of_an_import_ml_attempt_holds_its_start_and_its_end_as_iso_strings_in_utc(tmp_path):
    study, _ = init_study(tmp_path)
    source_file, mapping, population, _ = ready(tmp_path)
    code, payload, err = import_ml(study, source_file, mapping, population, "r")
    assert code == 0, (payload, err)
    manifest = payload["attempt"]
    assert is_utc_iso(manifest["started_at"])
    assert is_utc_iso(manifest["finished_at"])


def test_a_regression_assessment_holds_the_time_it_was_recorded_as_an_iso_string_in_utc(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    code, payload, err = assess(study, observation_set_id(study, attempts["seasonal_7"]), MAE, references_id(study))
    assert code == 0, (payload, err)
    assert is_utc_iso(payload["assessment"]["recorded_at"])


def test_an_agent_assessment_holds_the_time_it_was_recorded_as_an_iso_string_in_utc(tmp_path):
    study, _ = init_chinook(tmp_path)
    code, payload, err = import_agent(study, FIXTURE, fixture_population(tmp_path), "r")
    assert code == 0, (payload, err)
    code, payload, err = assess_agent(study, payload["attempt"])
    assert code == 0, (payload, err)
    assert is_utc_iso(payload["assessment"]["recorded_at"])


def test_a_freeze_record_and_an_exposure_entry_hold_the_time_each_was_recorded_as_an_iso_string_in_utc(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7", partition="public_check")
    code, payload, err = assess(study, observation_set_id(study, attempts["seasonal_7"]), MAE, references_id(study))
    assert code == 0, (payload, err)
    (freeze,) = freezes(study)
    (entry,) = journal(study)
    assert is_utc_iso(freeze["recorded_at"])
    assert is_utc_iso(entry["recorded_at"])


def test_a_recovered_attempt_holds_its_start_and_its_end_as_iso_strings_in_utc(tmp_path):
    study, folder = killed(tmp_path, kill_at=4)
    code, payload, err = run_json("recover", "--study", study, "--attempt", folder.name)
    assert code == 0, (payload, err)
    recovered = manifest_of(study, folder.name)
    assert is_utc_iso(recovered["started_at"])
    assert is_utc_iso(recovered["finished_at"])


# --- the paths -----------------------------------------------------------------------------------------------------------------


def test_a_revisions_study_spec_and_its_freeze_record_are_in_the_folder_of_its_number_under_revisions(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7", partition="public_check")
    first = json.loads((study / "study.json").read_text(encoding="utf-8"))
    code, payload, err = assess(study, observation_set_id(study, attempts["seasonal_7"]), MAE, references_id(study))
    assert code == 0, (payload, err)
    code, payload, err = new_revision(study, "--examples-dir", examples_copy(tmp_path, rows=corrected_day, name="revised"))
    assert code == 0, (payload, err)
    assert json.loads((study / "revisions" / "1" / "study.json").read_text(encoding="utf-8"))["revision"] == first["revision"]
    assert json.loads((study / "revisions" / "1" / "freeze.json").read_text(encoding="utf-8"))["protocol_digest"] == first["protocol_digest"]


# --- the parameters file -------------------------------------------------------------------------------------------------------


def test_run_ml_with_ridge_publishes_its_parameters_file_by_name_with_the_role_effective_parameters(tmp_path):
    _, attempts = fresh_study(tmp_path, "ridge_v1")
    manifest = attempts["ridge_v1"]
    published = {ref["path"].rpartition("/")[2]: ref["role"] for ref in manifest["output_refs"]}
    assert published["sklearn_params.json"] == "effective_parameters"


# --- the file digests ----------------------------------------------------------------------------------------------------------


def changes_the_database(path: Path, real):
    """`runner.run_episodes` that appends a byte to `path` once the Episodes are made."""

    def run(*args, **kwargs):
        location = real(*args, **kwargs)
        path.write_bytes(path.read_bytes() + b"\0")
        return location

    return run


def test_run_agent_records_the_digest_of_the_database_before_and_after_its_execution(tmp_path, monkeypatch):
    study, _ = init_chinook(tmp_path)
    patch_model(monkeypatch)
    attempt = ok(live(study, "plain", "r", cases=["D03"]))
    expected = digest_of(database_of(EXAMPLES).read_bytes())
    record = read(study, attempt, "run.json")
    assert record["database_sha256"]["before"] == expected
    assert record["database_sha256"]["after"] == expected


def test_data_fetch_gives_the_digest_of_a_destination_file_that_differs_from_its_lock(tmp_path):
    body = b"alpha,beta\n1,2\n"
    differing = body + b"extra\n"
    stand = Stand()
    try:
        stand.routes["/a"] = body
        lock = write_lock(tmp_path / "lock", source(stand, "/a", body, "data/a.csv"))
        dest = tmp_path / "dest"
        (dest / "data").mkdir(parents=True)
        (dest / "data" / "a.csv").write_bytes(differing)
        _, payload, _ = fetch(lock, dest)
    finally:
        stand.close()
    assert payload["error"]["code"] == "DEST_FILE_DIFFERS"
    assert payload["error"]["details"]["actual_sha256"] == digest_of(differing)


# --- the refusals: SCENARIOS_NOT_DECLARED ---------------------------------------------------------------------------------------


def without_scenarios(tmp_path) -> Path:
    return chinook_examples(tmp_path, edit=lambda declaration: declaration.pop("scenarios"), name="no-scenarios")


def test_run_agent_scripted_fixture_refuses_a_workload_with_no_scenarios_with_its_code_message_stage_details_and_exit(tmp_path):
    study, _ = init_chinook(tmp_path)
    code, error = error_of(fixture(study, "plain", "r", "--examples-dir", without_scenarios(tmp_path)))
    assert error["code"] == "SCENARIOS_NOT_DECLARED"
    assert error["message"] == "the Workload 'chinook' declares no scenarios"
    assert error["stage"] == "fixture"
    assert set(error["details"]) == {"path"}
    assert code == EXIT_INVALID_INPUT


def test_run_fixture_refuses_a_workload_with_no_scenarios_with_its_code_message_stage_details_and_exit(tmp_path):
    with pytest.raises(HypotrailError) as caught:
        agentic_fixture.run_fixture(workload_dir=without_scenarios(tmp_path) / "chinook", out_dir=tmp_path / "out", configuration="plain")
    error = caught.value
    assert error.code == "SCENARIOS_NOT_DECLARED"
    assert error.message == "the Workload 'chinook' declares no scenarios"
    assert error.stage == "fixture"
    assert set(error.details) == {"path"}
    assert error.exit_code == EXIT_INVALID_INPUT


# --- the refusals: DATABASE_CHANGED ---------------------------------------------------------------------------------------------


def test_run_agent_refuses_a_database_changed_during_its_attempt_with_its_code_message_stage_details_digests_and_exit(tmp_path, monkeypatch):
    examples = chinook_examples(tmp_path)
    study, _ = init_chinook(tmp_path, examples=examples)
    patch_model(monkeypatch)
    database = database_of(examples)
    before = database.read_bytes()
    monkeypatch.setattr(runner, "run_episodes", changes_the_database(database, runner.run_episodes))
    code, error = error_of(live(study, "plain", "r", "--examples-dir", examples, cases=["D03"]))
    assert error["code"] == "DATABASE_CHANGED"
    assert error["message"] == "the Workload's database changed during the Attempt"
    assert error["stage"] == "run"
    assert set(error["details"]) == {"sha256_before", "sha256_after", "warnings"}
    assert code == EXIT_INTEGRITY_REFUSED
    assert error["details"]["sha256_before"] == digest_of(before)
    assert error["details"]["sha256_after"] == digest_of(database.read_bytes())


def test_run_fixture_refuses_a_database_changed_during_its_execution_with_its_code_message_stage_details_and_exit(tmp_path, monkeypatch):
    examples = chinook_examples(tmp_path)
    monkeypatch.setattr(runner, "run_episodes", changes_the_database(database_of(examples), runner.run_episodes))
    with pytest.raises(HypotrailError) as caught:
        agentic_fixture.run_fixture(workload_dir=examples / "chinook", out_dir=tmp_path / "out", configuration="plain")
    error = caught.value
    assert error.code == "DATABASE_CHANGED"
    assert error.message == "the Chinook file changed during the execution"
    assert error.stage == "fixture"
    assert set(error.details) == {"sha256_before", "sha256_after"}
    assert error.exit_code == EXIT_INTEGRITY_REFUSED


# --- the refusals: SECRET_IN_OUTPUT ---------------------------------------------------------------------------------------------


def test_run_agent_refuses_an_execution_whose_log_holds_the_key_with_its_code_message_stage_details_and_exit(tmp_path, monkeypatch):
    study, _ = init_chinook(tmp_path)
    patch_model(monkeypatch, answering_with(FAKE_KEY))
    code, error = error_of(live(study, "plain", "r", cases=["D03"]))
    files = error["details"]["files"]
    assert error["code"] == "SECRET_IN_OUTPUT"
    assert error["message"] == f"the API key was found in what this Attempt would write: {', '.join(files)}; nothing holding it was kept"
    assert error["stage"] == "live"
    assert set(error["details"]) == {"files", "warnings"}
    assert code == EXIT_INFRASTRUCTURE
