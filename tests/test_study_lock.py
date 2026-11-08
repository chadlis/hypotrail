"""Ticket #65: one writer per Study, what an interruption leaves, `status`, `recover` and the explicit retry."""

import contextlib
import json
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest
from _study_helpers import init_study, run_cli, run_json, run_ml
from test_run_ml import Instruments, killed, snapshot

from hypotrail.core import artifacts, canonical, contracts, lock
from hypotrail.core.errors import (
    EXIT_CAPABILITY_UNAVAILABLE,
    EXIT_INFRASTRUCTURE,
    EXIT_INTEGRITY_REFUSED,
    EXIT_INVALID_INPUT,
    EXIT_LOCK_OR_CONFLICT,
    HypotrailError,
)

HOLD = textwrap.dedent(
    """
    import sys
    from hypotrail.core import lock

    with lock.writer_lock(sys.argv[1]):
        print("ready", flush=True)
        sys.stdin.readline()
    """
)


@contextlib.contextmanager
def held_by_another_process(study):
    """A live writer in another process holds the Study's lock for the duration of the block."""
    process = subprocess.Popen(
        [sys.executable, "-c", HOLD, str(study)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        yield process
    finally:
        process.stdin.write("\n")
        process.stdin.close()
        process.wait(timeout=30)


def error_of(payload):
    error = payload["error"]
    assert set(error) == {"code", "message", "stage", "details"}
    return error


def manifest_of(study, attempt_id):
    return json.loads((Path(study) / "attempts" / attempt_id / "attempt.json").read_text())


def recover(study, attempt_id):
    return run_json("recover", "--study", study, "--attempt", attempt_id)


def status(study):
    return run_json("status", "--study", study)


# --- AC1: one writer at a time ---------------------------------------------------------------------------------------


def writers(study):
    """Every command that writes to the Study, as the arguments of one call each."""
    return {
        "run ml": lambda: run_ml(study, "seasonal_7", "dev", "second-writer"),
        "recover": lambda: recover(study, str(uuid.uuid4())),
        "init": lambda: run_json("init", "--workload", "bike_day", "--study", study),
    }


@pytest.mark.parametrize("command", ["run ml", "recover", "init"])
def test_while_a_writer_holds_the_lock_every_other_writer_is_refused_at_once_with_exit_6_and_writes_nothing(tmp_path, command):
    study, _ = init_study(tmp_path)
    before = snapshot(study)
    with held_by_another_process(study):
        code, payload, _ = writers(study)[command]()  # returns while the holder is alive: it did not wait
    assert code == EXIT_LOCK_OR_CONFLICT == 6
    error = error_of(payload)
    assert (error["code"], error["stage"]) == ("STUDY_LOCKED", "lock")
    assert error["details"] == {"study": str(study)}
    assert snapshot(study) == before


def test_the_lock_is_released_when_its_holder_dies_abnormally(tmp_path):
    study, _ = init_study(tmp_path)
    process = subprocess.Popen([sys.executable, "-c", HOLD, str(study)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert process.stdout.readline().strip() == "ready"
    process.kill()
    process.wait(timeout=30)
    code, payload, err = run_ml(study, "seasonal_7", "dev", "after-the-death")
    assert code == 0, (payload, err)


def test_a_platform_without_file_locking_is_refused_with_a_code(tmp_path, monkeypatch):
    study, _ = init_study(tmp_path)

    def unavailable():
        raise ImportError("no fcntl")

    monkeypatch.setattr(lock, "_load_fcntl", unavailable)
    code, payload, _ = run_ml(study, "seasonal_7", "dev", "r")
    assert code == EXIT_CAPABILITY_UNAVAILABLE
    assert (error_of(payload)["code"], payload["error"]["stage"]) == ("LOCKING_UNAVAILABLE", "lock")
    assert not (study / "attempts").exists()


# --- AC2: a killed writer leaves partial artifacts and no terminal manifest ------------------------------------------


def test_a_killed_writer_leaves_its_partial_artifacts_and_a_manifest_that_is_not_terminal(tmp_path):
    study, folder = killed(tmp_path, kill_at=4)  # the Attempt's first output is published, the rest is not
    published = sorted(p.name for p in folder.iterdir())
    assert "attempt.json" in published and "workload.json" in published and "predictions.csv" in published
    assert not (folder / "observation_set.json").exists()
    manifest = json.loads((folder / "attempt.json").read_text())
    assert manifest["technical_status"] == "running"
    assert manifest["finished_at"] is None
    assert manifest["technical_status"] != "completed" and "item_counts" not in manifest and "output_refs" not in manifest
    contracts.validate(manifest)


# --- AC3 and Tightened A: status reads, recover records ---------------------------------------------------------------


def test_status_lists_every_attempt_with_its_technical_status_and_artifacts_the_partial_ones_included_and_writes_nothing(tmp_path):
    study, folder = killed(tmp_path, kill_at=4)
    code, payload, err = run_ml(study, "ridge_v1", "dev", "done")
    assert code == 0, (payload, err)
    done = payload["attempt"]
    before = snapshot(study)

    code, listing, err = status(study)

    assert code == 0 and listing["ok"] is True
    assert snapshot(study) == before  # a read
    by_id = {a["attempt_id"]: a for a in listing["attempts"]}
    assert set(by_id) == {folder.name, done["attempt_id"]}
    partial = by_id[folder.name]
    assert partial["technical_status"] == "running" and partial["finished_at"] is None and partial["request_id"] == "killed"
    assert partial["writer_alive"] is False
    names = {a["path"].rsplit("/", 1)[1]: a for a in partial["artifacts"]}
    assert {"workload.json", "predictions.csv"} <= set(names)
    assert names["predictions.csv"]["sha256"] == artifacts.ref_of_existing(
        study, f"attempts/{folder.name}/predictions.csv", media_type="text/csv", role="x"
    )["sha256"]
    assert by_id[done["attempt_id"]]["technical_status"] == "completed"
    assert {a["path"] for a in by_id[done["attempt_id"]]["artifacts"]} >= {r["path"] for r in done["output_refs"]}
    assert listing["study"]["protocol_digest"] == json.loads((study / "study.json").read_text())["protocol_digest"]
    assert listing["writer_alive"] is False


def test_status_says_a_live_writer_is_alive_and_takes_no_lock_itself(tmp_path):
    study, _ = init_study(tmp_path)
    with held_by_another_process(study):
        code, listing, _ = status(study)
        assert code == 0 and listing["writer_alive"] is True
    code, listing, _ = status(study)
    assert listing["writer_alive"] is False


def test_status_of_a_folder_that_is_no_study_is_a_json_error(tmp_path):
    code, payload, err = status(tmp_path / "none")
    assert code == EXIT_INVALID_INPUT
    assert error_of(payload)["code"] == "STUDY_NOT_FOUND"
    assert err.strip()


def test_recover_records_an_attempt_without_a_live_writer_as_interrupted_keeps_its_artifacts_and_resubmits_nothing(tmp_path, monkeypatch):
    study, folder = killed(tmp_path, kill_at=4)
    files_before = {p.name: p.read_bytes() for p in folder.iterdir() if p.name != "attempt.json"}
    instruments = Instruments(monkeypatch)

    code, payload, err = recover(study, folder.name)

    assert code == 0, (payload, err)
    recorded = payload["attempt"]
    assert recorded == manifest_of(study, folder.name)
    contracts.validate(recorded)
    assert recorded["technical_status"] == "interrupted"
    assert recorded["finished_at"] and recorded["reason"]
    assert recorded["attempt_id"] == folder.name and recorded["request_id"] == "killed"
    assert {p.name: p.read_bytes() for p in folder.iterdir() if p.name != "attempt.json"} == files_before
    assert instruments.calls == []
    assert len(list((study / "attempts").iterdir())) == 1  # nothing was resubmitted
    assert run_cli("status", "--study", study)[0] == 0


def test_recover_refuses_an_attempt_that_is_terminal(tmp_path):
    study, _ = init_study(tmp_path)
    _, done, _ = run_ml(study, "seasonal_7", "dev", "done")
    attempt_id = done["attempt"]["attempt_id"]
    before = snapshot(study)
    code, payload, _ = recover(study, attempt_id)
    assert code == EXIT_INTEGRITY_REFUSED
    error = error_of(payload)
    assert (error["code"], error["stage"]) == ("ATTEMPT_TERMINAL", "attempt")
    assert error["details"]["attempt_id"] == attempt_id and error["details"]["technical_status"] == "completed"
    assert snapshot(study) == before


def test_recover_refuses_an_attempt_whose_writer_is_alive(tmp_path):
    study, folder = killed(tmp_path, kill_at=4)  # the manifest is `running`
    before = snapshot(study)
    with held_by_another_process(study):  # a live writer holds the Study
        code, payload, _ = recover(study, folder.name)
    assert code == EXIT_LOCK_OR_CONFLICT
    assert error_of(payload)["code"] == "STUDY_LOCKED"
    assert snapshot(study) == before and manifest_of(study, folder.name)["technical_status"] == "running"


def test_recover_refuses_an_attempt_the_study_does_not_hold(tmp_path):
    study, _ = init_study(tmp_path)
    for name in (str(uuid.uuid4()), "../study.json", "a/b"):
        code, payload, _ = recover(study, name)
        assert code == EXIT_INVALID_INPUT
        assert error_of(payload)["code"] == "ATTEMPT_NOT_FOUND"


# --- AC4: a lock that disappears is not the cancellation of a remote call ---------------------------------------------


def constructed_live_attempt(study, *, outcome_unknown):
    attempt_id = str(uuid.uuid4())
    config = {"mode": "llm_live", "model": "constructed"}
    manifest = {
        "kind": "attempt", "schema_version": "attempt/1", "attempt_id": attempt_id, "request_id": "live-1",
        "operation": "execute", "mode": "llm_live", "technical_status": "running",
        "started_at": "2026-11-08T10:00:00+00:00", "finished_at": None,
        "effective_config": config, "effective_config_digest": canonical.digest(config),
        "input_refs": [], "code_environment": {}, "outcome_unknown": outcome_unknown, "retry_of": None,
    }
    contracts.validate(manifest)
    artifacts.replace_bytes(study, f"attempts/{attempt_id}/attempt.json", canonical.dumps(manifest))
    return attempt_id


@pytest.mark.parametrize("before", [True, False])
def test_an_interrupted_attempt_whose_mode_calls_a_provider_keeps_outcome_unknown_true(tmp_path, before):
    study, _ = init_study(tmp_path)
    attempt_id = constructed_live_attempt(study, outcome_unknown=before)  # no model is called
    code, payload, err = recover(study, attempt_id)
    assert code == 0, (payload, err)
    recorded = manifest_of(study, attempt_id)
    assert recorded["technical_status"] == "interrupted" and recorded["outcome_unknown"] is True
    _, listing, _ = status(study)
    assert listing["attempts"][0]["outcome_unknown"] is True


def test_an_interrupted_native_attempt_has_no_remote_call_to_be_unknown(tmp_path):
    study, folder = killed(tmp_path, kill_at=4)
    recover(study, folder.name)
    assert manifest_of(study, folder.name)["outcome_unknown"] is False


# --- AC5: replay and explicit retry after an interruption -------------------------------------------------------------


@pytest.mark.parametrize("recorded_as_interrupted", [False, True])
def test_the_same_request_id_after_an_interruption_returns_that_attempt_without_recomputing(tmp_path, monkeypatch, recorded_as_interrupted):
    study, folder = killed(tmp_path, kill_at=4)
    if recorded_as_interrupted:
        assert recover(study, folder.name)[0] == 0
    before = snapshot(study)
    instruments = Instruments(monkeypatch)
    code, payload, err = run_ml(study, "seasonal_7", "dev", "killed")
    assert code == 0, (payload, err)
    assert payload["replayed"] is True and payload["attempt"]["attempt_id"] == folder.name
    assert payload["attempt"]["technical_status"] == ("interrupted" if recorded_as_interrupted else "running")
    assert instruments.calls == [] and snapshot(study) == before


def test_a_retry_with_a_new_request_id_and_retry_of_is_a_new_attempt_and_the_interrupted_one_keeps_its_digests(tmp_path):
    study, folder = killed(tmp_path, kill_at=4)
    assert recover(study, folder.name)[0] == 0
    before = {k: v for k, v in snapshot(study).items()}

    code, payload, err = run_ml(study, "seasonal_7", "dev", "killed-again", "--retry-of", folder.name)

    assert code == 0, (payload, err)
    retry = payload["attempt"]
    assert retry["attempt_id"] != folder.name and retry["retry_of"] == folder.name
    assert retry["technical_status"] == "completed" and retry["request_id"] == "killed-again"
    after = snapshot(study)
    old = {k: v for k, v in before.items() if k.startswith(f"attempts/{folder.name}/")}
    assert old and {k: after[k] for k in old} == old
    assert manifest_of(study, folder.name)["technical_status"] == "interrupted"


# --- AC6: atomic while running, immutable once terminal ---------------------------------------------------------------


def test_once_an_attempt_is_terminal_a_write_that_would_change_it_is_refused_with_a_code(tmp_path):
    study, _ = init_study(tmp_path)
    _, done, _ = run_ml(study, "ridge_v1", "dev", "done")
    attempt = done["attempt"]
    folder = f"attempts/{attempt['attempt_id']}"
    before = snapshot(study)

    def refused(call):
        with pytest.raises(HypotrailError) as caught:
            call()
        assert (caught.value.code, caught.value.exit_code, caught.value.stage) == ("ATTEMPT_TERMINAL", EXIT_INTEGRITY_REFUSED, "attempt")
        assert caught.value.details["attempt_id"] == attempt["attempt_id"]

    changed = {**attempt, "technical_status": "failed"}
    refused(lambda: artifacts.replace_bytes(study, f"{folder}/attempt.json", canonical.dumps(changed)))
    refused(lambda: artifacts.publish_bytes(study, f"{folder}/predictions.csv", b"other", media_type="text/csv", role="x"))
    refused(lambda: artifacts.publish_bytes(study, f"{folder}/extra.csv", b"new", media_type="text/csv", role="x"))
    assert snapshot(study) == before


def test_a_recovered_attempt_is_terminal_too(tmp_path):
    study, folder = killed(tmp_path, kill_at=4)
    recover(study, folder.name)
    with pytest.raises(HypotrailError) as caught:
        artifacts.publish_bytes(study, f"attempts/{folder.name}/observations.csv", b"x", media_type="text/csv", role="x")
    assert caught.value.code == "ATTEMPT_TERMINAL"


def test_while_an_attempt_runs_its_manifest_is_replaced_atomically(tmp_path, monkeypatch):
    """Every replacement of the running manifest is a rename of a complete file: a reader never sees half of one."""
    import os

    study, _ = init_study(tmp_path)
    seen = []
    real = os.replace

    def watching(source, target, *args, **kwargs):
        if str(target).endswith("attempt.json"):
            seen.append(canonical.loads(Path(source).read_bytes())["technical_status"])  # complete and parseable before the rename
        return real(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "replace", watching)
    assert run_ml(study, "seasonal_7", "dev", "r")[0] == 0
    assert seen == ["running", "completed"]


# --- Tightened B: an error inside a live process leaves the Attempt failed ---------------------------------------------


def test_an_infrastructure_failure_inside_a_live_run_leaves_the_attempt_failed_with_a_reason_its_partial_artifacts_and_exit_4(tmp_path, monkeypatch):
    study, _ = init_study(tmp_path)
    real = artifacts.publish_bytes

    def failing(study_dir, relative, data, **kwargs):
        if str(relative).endswith("observations.csv"):
            raise OSError(28, "No space left on device")
        return real(study_dir, relative, data, **kwargs)

    monkeypatch.setattr(artifacts, "publish_bytes", failing)
    code, payload, err = run_ml(study, "seasonal_7", "dev", "will-fail")

    assert code == EXIT_INFRASTRUCTURE == 4
    assert error_of(payload)["code"] == "INFRASTRUCTURE_FAILURE"
    (folder,) = (study / "attempts").iterdir()
    manifest = manifest_of(study, folder.name)
    contracts.validate(manifest)
    assert manifest["technical_status"] == "failed" and manifest["finished_at"]
    assert "No space left" in manifest["reason"]
    assert (folder / "predictions.csv").is_file() and not (folder / "observations.csv").exists()
    monkeypatch.undo()
    _, listing, _ = status(study)
    assert listing["attempts"][0]["technical_status"] == "failed" and listing["attempts"][0]["reason"] == manifest["reason"]


def test_a_failed_attempt_is_returned_for_its_request_id_and_a_retry_is_explicit(tmp_path, monkeypatch):
    study, _ = init_study(tmp_path)
    with monkeypatch.context() as patch:
        real = artifacts.publish_bytes

        def failing(study_dir, relative, data, **kwargs):
            if str(relative).endswith("observation_set.json"):
                raise OSError(5, "I/O error")
            return real(study_dir, relative, data, **kwargs)

        patch.setattr(artifacts, "publish_bytes", failing)
        assert run_ml(study, "seasonal_7", "dev", "once")[0] == EXIT_INFRASTRUCTURE
    (folder,) = (study / "attempts").iterdir()
    instruments = Instruments(monkeypatch)
    code, payload, _ = run_ml(study, "seasonal_7", "dev", "once")
    assert code == 0 and payload["replayed"] is True and payload["attempt"]["technical_status"] == "failed"
    assert instruments.calls == []
    monkeypatch.undo()
    code, payload, _ = run_ml(study, "seasonal_7", "dev", "twice", "--retry-of", folder.name)
    assert code == 0 and payload["attempt"]["retry_of"] == folder.name and payload["attempt"]["technical_status"] == "completed"


# --- J: --json and errors for the new commands --------------------------------------------------------------------------


@pytest.mark.parametrize("arguments", [["status"], ["recover", "--attempt", "x"]])
def test_the_new_commands_print_one_json_object_on_stdout_and_diagnostics_on_stderr(tmp_path, arguments):
    study, _ = init_study(tmp_path)
    code, out, err = run_cli(arguments[0], "--study", study, *arguments[1:], "--json")
    payload = json.loads(out)  # exactly one object
    assert out.strip().startswith("{") and out.strip().endswith("}")
    if code != 0:
        error_of(payload)
        assert err.strip()
    code, out, err = run_cli(arguments[0], "--study", tmp_path / "none", *arguments[1:], "--json")
    assert code == EXIT_INVALID_INPUT and error_of(json.loads(out))["code"] in ("STUDY_NOT_FOUND",)
    assert "STUDY_NOT_FOUND" in err


def test_recover_requires_an_attempt(tmp_path):
    study, _ = init_study(tmp_path)
    code, payload, _ = run_json("recover", "--study", study)
    assert code == EXIT_INVALID_INPUT and error_of(payload)["code"] == "INVALID_ARGUMENTS"
