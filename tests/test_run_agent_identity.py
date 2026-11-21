"""Ticket #74: the request identity of `run agent`, its replay, its writer lock, an interruption and `--retry-of`."""

import json

import pytest
from _chinook_helpers import chinook_examples, database_of, init_chinook
from _exposure_helpers import edit_chinook_references
from _run_agent_helpers import (
    TWO,
    PUBLIC,
    error_of,
    fixture,
    live,
    ok,
    patch_model,
    refuse_provider,
    tree,
    tree_without_lock,
)
from _study_helpers import run_cli, run_json
from test_study_lock import held_by_another_process

from hypotrail.core import artifacts, environment, requests
from hypotrail.core.errors import EXIT_INVALID_INPUT, EXIT_LOCK_OR_CONFLICT

CONFLICT = EXIT_LOCK_OR_CONFLICT


def edited(path, edit):
    document = json.loads(path.read_text(encoding="utf-8"))
    edit(document)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


class Rig:
    """A Chinook Study over a private copy of `examples/`, and the mock model patched in."""

    def __init__(self, tmp_path, monkeypatch):
        self.tmp_path = tmp_path
        self.examples = chinook_examples(tmp_path)
        self.study, _ = init_chinook(tmp_path, examples=self.examples)
        self.more = ["--examples-dir", self.examples]
        patch_model(monkeypatch)
        self.monkeypatch = monkeypatch

    def live(self, config, request_id, **options):
        return live(self.study, config, request_id, *self.more, **options)

    def fixture(self, config, request_id):
        return fixture(self.study, config, request_id, *self.more)

    def declaration(self, edit):
        edited(self.examples / "chinook" / "workload.json", edit)

    def conflict(self, result, *differs):
        before = tree_without_lock(self.study)
        code, error = error_of(result)
        assert (code, error["code"], error["stage"]) == (CONFLICT, "REQUEST_CONFLICT", "request")
        assert error["details"]["differs"] == list(differs), error["details"]
        assert error["details"]["decision_id"] is None and error["details"]["attempt_id"]  # #109 Tightened K: it names an Attempt, no decision
        assert tree_without_lock(self.study) == before  # nothing written


# --- Replay -------------------------------------------------------------------------------------------------------------------------


def test_the_same_request_returns_the_recorded_attempt_and_runs_nothing_in_either_mode(tmp_path, monkeypatch):
    """T18 (SPEC §10)."""
    rig = Rig(tmp_path, monkeypatch)
    first = ok(rig.live("plain", "same"))
    scenario = ok(rig.fixture("plain", "same-fixture"))
    refuse_provider(monkeypatch)  # no Inspect eval, no provider call
    before = tree(rig.study)
    code, payload, _ = rig.live("plain", "same")
    assert code == 0 and payload["replayed"] is True and payload["attempt"] == first
    code, payload, _ = rig.fixture("plain", "same-fixture")
    assert code == 0 and payload["replayed"] is True and payload["attempt"] == scenario
    assert tree(rig.study) == before


# --- One conflict test per element a CLI request can change alone -------------------------------------------------------------------


def test_another_configuration_under_the_same_request_id_is_a_conflict_on_configuration(tmp_path, monkeypatch):
    """T18 (SPEC §10)."""
    rig = Rig(tmp_path, monkeypatch)
    ok(rig.live("plain", "r"))
    rig.conflict(rig.live("verify", "r"), "configuration")
    # a Configuration that declares the very same content under another name is another Configuration: the id is an element
    rig.declaration(lambda d: d["configurations"].update(plain_again=json.loads(json.dumps(d["configurations"]["plain"]))))
    rig.conflict(rig.live("plain_again", "r"), "configuration")


def test_the_same_configuration_name_with_its_declared_content_changed_is_a_conflict_on_configuration(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    ok(rig.live("plain", "r"))
    rig.declaration(lambda d: d["configurations"]["plain"].update(system_text=d["configurations"]["plain"]["system_text"] + "Be brief.\n"))
    rig.conflict(rig.live("plain", "r"), "configuration")


def test_a_changed_resolved_system_text_is_a_conflict_though_the_declared_content_is_the_same(tmp_path, monkeypatch):
    """`verify` extends `plain`: change `plain`'s text and `verify` declares the same, and resolves to another text."""
    rig = Rig(tmp_path, monkeypatch)
    ok(rig.live("verify", "r"))
    rig.declaration(lambda d: d["configurations"]["plain"].update(system_text=d["configurations"]["plain"]["system_text"] + "Be brief.\n"))
    rig.conflict(rig.live("verify", "r"), "configuration")


def test_editing_another_configuration_leaves_a_replay_a_replay(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    first = ok(rig.live("plain", "r"))
    rig.declaration(lambda d: d["configurations"]["verify"].update(added_instruction="\nCheck twice.\n"))
    code, payload, _ = rig.live("plain", "r")
    assert code == 0 and payload["replayed"] is True and payload["attempt"] == first


def test_other_cases_under_the_same_request_id_are_a_conflict_on_cases(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    ok(rig.live("plain", "r"))
    rig.conflict(rig.live("plain", "r", cases=["D03", "D07"]), "cases")


def test_other_repeats_under_the_same_request_id_are_a_conflict_on_repeats(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    ok(rig.live("plain", "r"))
    rig.conflict(rig.live("plain", "r", repeats=2), "repeats")


def test_another_model_under_the_same_request_id_is_a_conflict_on_model(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    ok(rig.live("plain", "r"))
    rig.conflict(rig.live("plain", "r", model="anthropic/claude-other"), "model")


def test_another_code_revision_under_the_same_request_id_is_a_conflict_on_code_revision(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    revision = lambda commit: {"commit": commit * 40, "dirty": False, "local_code_fingerprint": None}
    monkeypatch.setattr(environment, "code_revision", lambda root=None: revision("a"))
    ok(rig.live("plain", "r"))
    code, payload, _ = rig.live("plain", "r")
    assert code == 0 and payload["replayed"] is True  # the same revision is a replay
    monkeypatch.setattr(environment, "code_revision", lambda root=None: revision("b"))
    rig.conflict(rig.live("plain", "r"), "code_revision")


def test_a_changed_scenarios_file_under_the_same_request_id_is_a_conflict_on_the_input_digests(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    ok(rig.fixture("plain", "r"))
    path = rig.examples / "chinook" / "fixtures" / "scenarios.json"
    edited(path, lambda d: d.update(description=d["description"] + " (edited)"))
    rig.conflict(rig.fixture("plain", "r"), "input_digests")
    rig.conflict(rig.fixture("verify", "r"), "configuration", "input_digests")  # an element at a time is only possible for one that changes alone


def test_a_changed_dataset_whose_lock_is_rewritten_is_a_conflict_on_the_input_digests(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    ok(rig.live("plain", "r"))
    database = database_of(rig.examples)
    database.write_bytes(database.read_bytes() + b"\0")
    import hashlib

    lock = rig.examples / "chinook" / "data-sources.lock.json"

    def rewrite(document):
        for source in document["sources"]:
            source["sha256"] = hashlib.sha256(database.read_bytes()).hexdigest()
            source["size_bytes"] = database.stat().st_size

    edited(lock, rewrite)
    rig.conflict(rig.live("plain", "r"), "input_digests")


def test_a_changed_live_database_whose_lock_is_not_rewritten_is_a_conflict_not_an_integrity_refusal(tmp_path, monkeypatch):
    """The request is identified before the data is verified (D-012 addendum 2, item 19)."""
    rig = Rig(tmp_path, monkeypatch)
    ok(rig.live("plain", "r"))
    database = database_of(rig.examples)
    database.write_bytes(database.read_bytes() + b"\0")
    rig.conflict(rig.live("plain", "r"), "input_digests")


def test_a_references_set_changed_by_a_new_study_revision_is_a_conflict_on_the_input_digests(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    ok(rig.live("plain", "r"))
    corrected = edit_chinook_references(tmp_path, lambda records: records["D01"].update(rows=[[0]]), name="corrected")
    code, payload, err = run_json("init", "--study", rig.study, "--new-revision", "--examples-dir", corrected)
    assert code == 0, (payload, err)
    code, error = error_of(live(rig.study, "plain", "r", "--examples-dir", corrected))
    assert (code, error["code"], error["details"]["differs"]) == (CONFLICT, "REQUEST_CONFLICT", ["input_digests"])


def test_another_partition_changes_the_partition_the_cases_and_the_cases_file_digest(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    ok(rig.live("plain", "r"))
    rig.conflict(rig.live("plain", "r", partition="public_check", cases=PUBLIC[:2]), "partition", "cases", "input_digests")


def test_without_cases_the_request_is_every_case_of_the_partition_and_both_spellings_are_one_request(tmp_path, monkeypatch):
    from _run_agent_helpers import DEV

    rig = Rig(tmp_path, monkeypatch)
    first = ok(rig.live("plain", "r", cases=None))
    assert first["effective_config"]["cases"] == DEV  # the Partition's Cases, in the file's order
    code, payload, _ = rig.live("plain", "r", cases=list(reversed(DEV)))
    assert code == 0 and payload["replayed"] is True and payload["attempt"] == first


# --- The writer lock and an interruption -----------------------------------------------------------------------------------------


def test_a_second_writer_is_refused_and_an_attempt_stopped_before_its_terminal_manifest_is_recorded_interrupted_without_resubmission(
    tmp_path, monkeypatch
):
    rig = Rig(tmp_path, monkeypatch)
    with held_by_another_process(rig.study):
        before = tree(rig.study)
        code, error = error_of(rig.live("plain", "locked"))
        assert (code, error["code"]) == (EXIT_LOCK_OR_CONFLICT, "STUDY_LOCKED")
        assert tree_without_lock(rig.study) == {k: v for k, v in before.items() if k != "writer.lock"}

    class Stopped(BaseException):
        """What a killed process is for the code: nothing catches it."""

    replaced = []
    real = artifacts.replace_bytes

    def replace(study, relative, data):
        replaced.append(relative)
        if len(replaced) == 2:  # the terminal manifest
            raise Stopped
        return real(study, relative, data)

    monkeypatch.setattr(artifacts, "replace_bytes", replace)
    with pytest.raises(Stopped):
        run_cli("run", "agent", "--study", rig.study, "--mode", "llm_live", "--config", "plain", "--request-id", "killed", "--partition", "dev",
                "--repeats", "1", "--model", "anthropic/claude-test-1", "--cases", "D03", "--json", *rig.more)
    monkeypatch.setattr(artifacts, "replace_bytes", real)
    (folder,) = (rig.study / "attempts").iterdir()
    manifest = json.loads((folder / "attempt.json").read_text())
    assert manifest["technical_status"] == "running" and manifest["finished_at"] is None and "item_counts" not in manifest
    assert (folder / "observation_set.json").is_file() and (folder / "observations.jsonl").is_file()  # what it published stays
    code, status, _ = run_json("status", "--study", rig.study)
    assert status["attempts"][0]["technical_status"] == "running" and status["attempts"][0]["recoverable"] is True
    refuse_provider(monkeypatch)  # `recover` resubmits nothing
    code, payload, err = run_json("recover", "--study", rig.study, "--attempt", manifest["attempt_id"])
    assert code == 0, (payload, err)
    assert payload["attempt"]["technical_status"] == "interrupted" and payload["attempt"]["outcome_unknown"] is True
    assert (folder / "observations.jsonl").is_file()


# --- --retry-of --------------------------------------------------------------------------------------------------------------------


def test_a_retry_is_a_new_attempt_that_leaves_the_earlier_one_unchanged_and_an_unknown_retry_of_is_refused(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    first = ok(rig.live("plain", "first"))
    earlier = tree(rig.study / "attempts" / first["attempt_id"])
    second = ok(live(rig.study, "plain", "again", "--retry-of", first["attempt_id"], *rig.more))
    assert second["retry_of"] == first["attempt_id"] and second["attempt_id"] != first["attempt_id"]
    assert tree(rig.study / "attempts" / first["attempt_id"]) == earlier
    before = tree_without_lock(rig.study)
    code, error = error_of(live(rig.study, "plain", "third", "--retry-of", "no-such-attempt", *rig.more))
    assert (code, error["code"]) == (EXIT_INVALID_INPUT, "RETRY_OF_UNKNOWN")
    assert tree_without_lock(rig.study) == before
