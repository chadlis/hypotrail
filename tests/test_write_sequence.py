"""Ticket #107 (slice #104, L2.1): the write sequence of a Study, kept as an append-only write journal.

D-033 on chadlis/hypotrail#75, D-034 on chadlis/hypotrail#75, D-035 on chadlis/hypotrail#75, D-036 on chadlis/hypotrail#75 and D-037 on chadlis/hypotrail#75 settle what is tested here: two entries per writing command (one
just before its first write, one after its last), the sequence is the number of entries, `status --json` shows it, and a
command that writes nothing leaves it alone. No model is called.
"""

import json
import shutil
from pathlib import Path

import pytest
from _assess_helpers import assess, fresh_study, observation_set_id, references_id
from _chinook_helpers import fixture_lines, fixture_population, import_agent, init_chinook, write_lines
from _compare_helpers import compare
from _import_helpers import import_ml, ready
from _report_helpers import report
from _report_tracks import TRACKS
from _revision_helpers import corrected_chinook_references, new_revision
from _run_agent_helpers import fixture
from _study_helpers import examples_copy, init_study, run_json, run_ml, sha256
from test_exposure import MAE
from test_run_ml import Instruments, killed
from test_study_lock import held_by_another_process, recover

ROOT = Path(__file__).resolve().parent.parent
KEPT = ROOT / "docs" / "handbook" / "traces" / "campaign-public-check" / "study"
JOURNAL = "write_journal"


# --- helpers ----------------------------------------------------------------------------------------------------------


def seq(study) -> int:
    """The write sequence `status --json` shows; 0 for a folder that is no Study yet."""
    if not (Path(study) / "study.json").exists():
        return 0
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    assert "write_sequence" in payload, "status --json shows no write_sequence"
    return payload["write_sequence"]


def entries(study) -> list:
    folder = Path(study) / JOURNAL
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))] if folder.is_dir() else []


def last_entry(study) -> dict:
    journal = entries(study)
    assert journal, "the Study keeps no write journal"
    return journal[-1]


def appended(study, kept: int) -> tuple:
    """The two entries a command appended after the `kept` that were there."""
    added = entries(study)[kept:]
    assert len(added) == 2, f"the command appended {len(added)} journal entries, not 2"
    return added[0], added[1]


def digests(study) -> list:
    folder = Path(study) / JOURNAL
    return [sha256(p) for p in sorted(folder.glob("*.json"))] if folder.is_dir() else []


def tree(folder) -> dict:
    return {p.relative_to(folder).as_posix(): sha256(p) for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def tree_without_lock(folder) -> dict:
    return {k: v for k, v in tree(folder).items() if k != "writer.lock"}


# --- the commands that write: each is a scenario (the Study it works on, and the one call it makes) ------------------


def init_new(tmp_path):
    study = tmp_path / "fresh"
    return study, lambda: run_json("init", "--workload", "bike_day", "--study", study)


def init_new_revision(tmp_path):
    study, _ = init_chinook(tmp_path)
    corrected = corrected_chinook_references(tmp_path, lambda r: r["D03"].update(rows=[[r["D03"]["rows"][0][0] + 1]]))
    return study, lambda: new_revision(study, "--examples-dir", corrected)


def run_ml_scenario(tmp_path):
    study, _ = init_study(tmp_path)
    return study, lambda: run_ml(study, "seasonal_7", "dev", "w-run")


def run_agent_scenario(tmp_path):
    study, _ = init_chinook(tmp_path)
    return study, lambda: fixture(study, "plain", "w-agent")


def import_ml_scenario(tmp_path):
    study, _ = init_study(tmp_path)
    source, mapping, population, _ = ready(tmp_path)
    return study, lambda: import_ml(study, source, mapping, population, "w-import")


def import_agent_scenario(tmp_path):
    study, _ = init_chinook(tmp_path)
    source = write_lines(tmp_path / "answers.jsonl", fixture_lines())
    return study, lambda: import_agent(study, source, fixture_population(tmp_path), "w-import-agent")


def assess_scenario(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    return study, lambda: assess(study, observation_set_id(study, attempts["seasonal_7"]), "regression_mae_v1", references_id(study))


def compare_scenario(tmp_path):
    from _compare_helpers import assessed

    study, _, ids = assessed(tmp_path, "seasonal_7", "ridge_v1")
    return study, lambda: compare(study, ids["seasonal_7"]["assessment_id"], ids["ridge_v1"]["assessment_id"])


def recover_scenario(tmp_path):
    study, folder = killed(tmp_path, kill_at=4)
    return study, lambda: recover(study, folder.name)


def report_scenario(tmp_path):
    study, _ = TRACKS["bike"].public_outputs(tmp_path)  # a page that shows public_check Items is an Exposure
    return study, lambda: report(study, tmp_path / "page.html")


def run_ml_leaving_a_failed_attempt(tmp_path):
    study, _ = init_study(tmp_path)
    return study, lambda: run_ml(study, "seasonal_7", "dev", "w-failed")


def compare_refused_for_coverage(tmp_path):
    from _compare_helpers import forged

    study, attempts = fresh_study(tmp_path, "seasonal_7", "ridge_v1", partition="public_check")
    made = {}
    for config, attempt in attempts.items():
        code, payload, err = assess(study, observation_set_id(study, attempt), MAE, references_id(study))
        assert code == 0, (payload, err)
        made[config] = payload["assessment"]

    def lose_one(rows):
        rows[0].update(state="unscored", value="", reason="item_failed")
        return rows

    other = forged(study, made["ridge_v1"], per_item=lose_one)
    return study, lambda: compare(study, made["seasonal_7"]["assessment_id"], other["assessment_id"])


def decide_scenario(tmp_path):
    study, _ = init_study(tmp_path)
    code, payload, err = run_ml(study, "seasonal_7", "dev", "w-held")
    assert code == 0, (payload, err)
    attempt = payload["attempt"]["attempt_id"]
    return study, lambda: run_json(
        "decide", "--study", study, "--question", "Which Configuration?", "--option", "seasonal_7", "--author", "human",
        "--artifact", attempt, "--request-id", "w-decide", "--read-sequence", seq(study),
    )


def deviation_scenario(tmp_path):
    study, _ = init_study(tmp_path)
    code, payload, err = run_ml(study, "seasonal_7", "dev", "w-held")
    assert code == 0, (payload, err)
    attempt = payload["attempt"]["attempt_id"]
    return study, lambda: run_json(
        "deviation", "--study", study, "--text", "owner review of References pending", "--author", "human",
        "--artifact", attempt, "--request-id", "w-deviation", "--read-sequence", seq(study),
    )


WRITERS = {
    "init": init_new,
    "init --new-revision": init_new_revision,
    "run ml": run_ml_scenario,
    "run agent": run_agent_scenario,
    "import ml": import_ml_scenario,
    "import agent": import_agent_scenario,
    "assess": assess_scenario,
    "compare": compare_scenario,
    "recover": recover_scenario,
    "report": report_scenario,
    "decide": decide_scenario,
    "deviation": deviation_scenario,
}


@pytest.fixture
def failing_attempt(monkeypatch):
    Instruments(monkeypatch)  # fit and prediction fail when called: the Attempt is left `failed`


# --- criterion 2 and Tightened A, B, E: every writing command appends two entries ------------------------------------


@pytest.mark.parametrize("command", WRITERS)
def test_a_command_that_writes_advances_the_write_sequence_by_two_and_the_value_is_the_number_of_entries(command, tmp_path):
    study, act = WRITERS[command](tmp_path)
    before, kept = seq(study), digests(study)
    code, payload, err = act()
    assert code == 0, (payload, err)
    assert seq(study) == before + 2
    assert len(entries(study)) == seq(study)
    assert digests(study)[: len(kept)] == kept  # an entry is never rewritten


def test_a_run_ml_that_leaves_a_failed_attempt_appends_both_entries(failing_attempt, tmp_path):
    study, act = run_ml_leaving_a_failed_attempt(tmp_path)
    before = seq(study)
    code, payload, err = act()
    assert code == 4 and payload["ok"] is False
    assert seq(study) == before + 2


def test_a_compare_refused_for_its_coverage_after_its_exposure_entry_appends_both_entries(tmp_path):
    study, act = compare_refused_for_coverage(tmp_path)
    before = seq(study)
    code, payload, err = act()
    assert (code, payload["error"]["code"]) == (3, "COMPARISON_COVERAGE_INSUFFICIENT")
    assert seq(study) == before + 2


def test_a_new_study_shows_a_write_sequence_of_two(tmp_path):
    study, act = init_new(tmp_path)
    code, payload, err = act()
    assert code == 0, (payload, err)
    assert seq(study) == 2


def test_a_writer_killed_after_its_running_manifest_leaves_one_entry_and_the_recover_that_follows_adds_two(tmp_path):
    study, folder = killed(tmp_path, kill_at=4)
    assert seq(study) == 2 + 1  # `init`'s two entries, and the `begin` entry of the killed `run ml`
    assert [e["phase"] for e in entries(study)] == ["begin", "end", "begin"]
    code, payload, err = recover(study, folder.name)
    assert code == 0, (payload, err)
    assert seq(study) == 2 + 1 + 2


# --- criterion 3: a command that writes nothing leaves the write sequence alone ---------------------------------------


def status_scenario(tmp_path):
    study, _ = init_study(tmp_path)
    return study, lambda: run_json("status", "--study", study), 0


def replay_scenario(tmp_path):
    study, _ = init_study(tmp_path)
    assert run_ml(study, "seasonal_7", "dev", "w-replay")[0] == 0
    return study, lambda: run_ml(study, "seasonal_7", "dev", "w-replay"), 0


def locked_scenario(tmp_path):
    study, _ = init_study(tmp_path)

    def act():
        with held_by_another_process(study):
            return run_ml(study, "seasonal_7", "dev", "w-locked")

    return study, act, 6


def conflict_scenario(tmp_path):
    study, _ = init_study(tmp_path)
    assert run_ml(study, "seasonal_7", "dev", "w-conflict")[0] == 0
    return study, lambda: run_ml(study, "ridge_v1", "dev", "w-conflict"), 6


def protocol_changed_scenario(tmp_path):
    study, _ = init_study(tmp_path)

    def shift(declaration):
        declaration["partitions"]["dev"][1] = "2012-06-29"
        declaration["partitions"]["public_check"][0] = "2012-06-30"

    changed = examples_copy(tmp_path, edit=shift)
    return study, lambda: run_ml(study, "seasonal_7", "dev", "w-changed", "--examples-dir", changed), 3


def invalid_arguments_scenario(tmp_path):
    study, _ = init_study(tmp_path)
    return study, lambda: run_json("init", "--study", study), 2


def dev_report_scenario(tmp_path):
    study = TRACKS["bike"].dev_study(tmp_path)  # a page that shows `dev` Items only records nothing and takes no lock
    return study, lambda: report(study, tmp_path / "dev.html"), 0


NON_WRITERS = {
    "status": status_scenario,
    "a replay": replay_scenario,
    "STUDY_LOCKED": locked_scenario,
    "REQUEST_CONFLICT": conflict_scenario,
    "PROTOCOL_CHANGED": protocol_changed_scenario,
    "INVALID_ARGUMENTS": invalid_arguments_scenario,
    "a dev-only report": dev_report_scenario,
}


@pytest.mark.parametrize("command", NON_WRITERS)
def test_a_command_that_writes_nothing_leaves_the_write_sequence_and_the_journal_unchanged(command, tmp_path):
    study, act, expected_exit = NON_WRITERS[command](tmp_path)
    before, kept = seq(study), digests(study)
    code, payload, err = act()
    assert code == expected_exit, (payload, err)
    assert seq(study) == before
    assert digests(study) == kept


# --- criterion 4: `status --json` shows the value and writes nothing ------------------------------------------------------


def test_status_shows_the_write_sequence_and_two_calls_with_no_write_between_them_agree_and_leave_every_file_as_it_was(tmp_path):
    study, _ = init_study(tmp_path)
    assert run_ml(study, "seasonal_7", "dev", "w-status")[0] == 0
    before = tree(study)
    first = run_json("status", "--study", study)[1]
    second = run_json("status", "--study", study)[1]
    assert "write_sequence" in first, "status --json shows no write_sequence"
    assert first["write_sequence"] == second["write_sequence"] == 4
    assert tree(study) == before


# --- Tightened C: a Study written before this slice -------------------------------------------------------------------------


def test_a_study_written_before_this_slice_shows_zero_until_its_first_write_and_its_kept_files_are_never_rewritten(tmp_path):
    before = tree(KEPT)
    assert seq(KEPT) == 0
    assert tree(KEPT) == before
    copy = tmp_path / "kept"
    shutil.copytree(KEPT, copy)
    attempt = run_json("status", "--study", copy)[1]["attempts"][0]
    observations = json.loads((copy / "attempts" / attempt["attempt_id"] / "observation_set.json").read_text())["observation_set_id"]
    code, payload, err = run_json(
        "assess", "--study", copy, "--observations", observations, "--scorer", "chinook_contract_v1", "--references", references_id(copy)
    )
    assert code == 0, (payload, err)  # a write on a copy of it
    assert seq(copy) == 2


# --- Tightened D and H: the key, and the shapes that stay ------------------------------------------------------------------

KEYS = {
    "init": {"ok", "study", "references_id"},
    "init --new-revision": {"ok", "study", "references_id"},
    "run ml": {"ok", "replayed", "attempt", "observation_set_id"},
    "run agent": {"ok", "replayed", "attempt", "observation_set_id", "warnings"},
    "import ml": {"ok", "replayed", "attempt", "observation_set_id"},
    "import agent": {"ok", "replayed", "attempt", "observation_set_id"},
    "assess": {"ok", "assessment"},
    "compare": {"ok", "comparison"},
    "recover": {"ok", "attempt"},
    "report": {"ok", "report"},
    "decide": {"ok", "replayed", "decision"},
    "deviation": {"ok", "replayed", "declared_deviation"},
}


@pytest.mark.parametrize("command", WRITERS)
def test_the_json_output_of_a_command_that_existed_before_this_slice_keeps_its_keys(command, tmp_path):
    study, act = WRITERS[command](tmp_path)
    code, payload, err = act()
    assert code == 0, (payload, err)
    assert set(payload) == KEYS[command]


def test_status_json_gains_the_one_top_level_key_write_sequence_and_keeps_the_others(tmp_path):
    study, _ = init_study(tmp_path)
    payload = run_json("status", "--study", study)[1]
    assert "write_sequence" in payload, "status --json shows no write_sequence"
    assert set(payload) == {"ok", "study", "writer_alive", "revisions", "attempts", "freeze_records", "exposures", "check_informed", "write_sequence", "decisions", "declared_deviations", "assessments", "comparisons", "pending_decisions", "record_files", "next_step"}


# --- Tightened F, G, I, J: what an entry holds --------------------------------------------------------------------------


def test_a_completed_run_ml_appends_a_begin_entry_with_its_three_keys_and_an_end_entry_naming_the_attempt_and_its_observation_set(tmp_path):
    study, act = run_ml_scenario(tmp_path)
    kept = len(entries(study))
    code, payload, err = act()
    assert code == 0, (payload, err)
    begin, end = appended(study, kept)
    assert begin == {"phase": "begin", "command": "run ml", "request_id": "w-run"}
    assert set(end) == {"phase", "command", "request_id", "outcome", "written"}
    assert (end["phase"], end["command"], end["request_id"], end["outcome"]) == ("end", "run ml", "w-run", "completed")
    attempt = payload["attempt"]["attempt_id"]
    observation_set = observation_set_id(study, payload["attempt"])
    assert end["written"] == [{"kind": "attempt", "id": attempt}, {"kind": "observation_set", "id": observation_set}]
    assert all(set(item) == {"kind", "id"} for item in end["written"])


def test_a_decide_appends_a_begin_entry_with_its_request_id_and_an_end_entry_naming_the_decision(tmp_path):
    study, act = decide_scenario(tmp_path)
    kept = len(entries(study))
    code, payload, err = act()
    assert code == 0, (payload, err)
    begin, end = appended(study, kept)
    assert begin == {"phase": "begin", "command": "decide", "request_id": "w-decide"}
    assert (end["request_id"], end["outcome"]) == ("w-decide", "completed")
    assert end["written"] == [{"kind": "decision", "id": payload["decision"]["decision_id"]}]


def test_an_assess_appends_entries_whose_request_id_is_null(tmp_path):
    study, act = assess_scenario(tmp_path)
    kept = len(entries(study))
    code, payload, err = act()
    assert code == 0, (payload, err)
    begin, end = appended(study, kept)
    assert begin == {"phase": "begin", "command": "assess", "request_id": None}
    assert (end["request_id"], end["outcome"]) == (None, "completed")
    assert end["written"] == [{"kind": "assessment", "id": payload["assessment"]["assessment_id"]}]


def test_a_run_ml_left_failed_by_an_exception_after_its_running_manifest_ends_with_the_outcome_failed(failing_attempt, tmp_path):
    study, act = run_ml_leaving_a_failed_attempt(tmp_path)
    code, payload, err = act()
    assert code == 4, (payload, err)
    end = last_entry(study)
    assert (end["phase"], end["outcome"]) == ("end", "failed")
    [attempt] = [p.name for p in (study / "attempts").iterdir()]
    assert {"kind": "attempt", "id": attempt} in end["written"]


def test_a_run_agent_stopped_by_a_coded_error_after_its_running_manifest_keeps_its_exit_code_and_ends_with_the_outcome_failed(monkeypatch, tmp_path):
    from hypotrail.agentic import run as agent_run
    from hypotrail.core.errors import InvalidInputError

    def stop(*args, **kwargs):
        raise InvalidInputError("STOPPED_FOR_THE_TEST", "a coded error with exit 2", stage="run", details={})

    monkeypatch.setattr(agent_run, "_record", stop)
    study, act = run_agent_scenario(tmp_path)
    code, payload, err = act()
    assert (code, payload["error"]["code"]) == (2, "STOPPED_FOR_THE_TEST"), (payload, err)
    end = last_entry(study)
    assert (end["phase"], end["outcome"]) == ("end", "failed")  # not `refused`: the Attempt is left failed


def test_an_assess_stopped_by_an_os_error_after_its_first_write_ends_with_the_outcome_failed(monkeypatch, tmp_path):
    from hypotrail.core import artifacts

    real = artifacts.publish_record

    def stop_at_the_record(study, relative, *args, **kwargs):
        if str(relative).endswith("assessment.json"):  # after the per-Item file, the first write, is published
            raise OSError("disk full")
        return real(study, relative, *args, **kwargs)

    study, act = assess_scenario(tmp_path)
    monkeypatch.setattr(artifacts, "publish_record", stop_at_the_record)
    code, payload, err = act()
    assert (code, payload["error"]["code"]) == (4, "INFRASTRUCTURE_FAILURE"), (payload, err)
    assert last_entry(study)["outcome"] == "failed"
    assert (study / "assessments").is_dir() and not list((study / "assessments").glob("*/assessment.json"))


def test_a_compare_refused_for_its_coverage_after_its_exposure_entry_ends_with_the_outcome_refused_and_names_that_entry(tmp_path):
    study, act = compare_refused_for_coverage(tmp_path)
    code, payload, err = act()
    assert (code, payload["error"]["code"]) == (3, "COMPARISON_COVERAGE_INSUFFICIENT")
    end = last_entry(study)
    assert (end["phase"], end["command"], end["outcome"]) == ("end", "compare", "refused")
    exposure_entry = json.loads(sorted((study / "exposures").glob("*.json"))[-1].read_text(encoding="utf-8"))
    assert {"kind": "exposure", "id": exposure_entry["entry_id"]} in end["written"]
    assert all(set(item) == {"kind", "id"} for item in end["written"])


def test_a_writer_killed_after_its_running_manifest_leaves_a_begin_entry_and_no_end_entry(tmp_path):
    study, _ = killed(tmp_path, kill_at=4)
    last = last_entry(study)
    assert last == {"phase": "begin", "command": "run ml", "request_id": "killed"}


@pytest.mark.parametrize("scenario", [locked_scenario, conflict_scenario])
def test_a_command_refused_before_its_first_write_appends_no_entry(scenario, tmp_path):
    study, act, _ = scenario(tmp_path)
    kept = entries(study)
    assert kept, "the Study keeps no write journal"
    act()
    assert entries(study) == kept


# --- criterion 1 and 5: the kept files ---------------------------------------------------------------------------------------


def test_the_glossary_has_a_write_sequence_entry_that_avoids_the_word_revision():
    text = (ROOT / "GLOSSARY.md").read_text(encoding="utf-8")
    assert "**Write sequence**:" in text, "GLOSSARY.md has no entry Write sequence"
    entry = text.split("**Write sequence**:", 1)[1].split("\n\n", 1)[0]
    assert "_Avoid_:" in entry and "revision" in entry.split("_Avoid_:", 1)[1].lower()
