"""Ticket #74: what a native `llm_live` Attempt records, from the Inspect log of the run (the model is Inspect's mock model)."""

import json
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from _agent_helpers import CHINOOK, WORKLOAD, read_jsonl
from _chinook_helpers import chinook_examples, database_of, init_chinook
from _exposure_helpers import PUBLIC_CASES, assess_agent, import_public
from _run_agent_helpers import (
    ALL_CASES,
    DEV,
    FAKE_KEY,
    MODEL,
    TWO,
    answering_with,
    error_of,
    fixture,
    folder_of,
    live,
    observation_set_id_of,
    observations_of,
    ok,
    patch_model,
    read,
    scripted,
    study_of,
    tree,
    tree_without_lock,
)
from _study_helpers import run_cli, run_json

from hypotrail.agentic import limits as limits_module
from hypotrail.agentic import live as agentic_live
from hypotrail.agentic import runner
from hypotrail.agentic.sql_tool import QueryCaps
from hypotrail.core import canonical, contracts, environment, exposure
from hypotrail.core.errors import EXIT_INFRASTRUCTURE, EXIT_INTEGRITY_REFUSED

from inspect_ai.log import read_eval_log


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    """One Study with `plain` run on D03 and D05, two Repeats each, through the mock model: read-only for the tests that use it."""
    with pytest.MonkeyPatch.context() as patch:
        study = study_of(tmp_path_factory.mktemp("recorded"))
        script = patch_model(patch)
        attempt = ok(live(study, "plain", "rec", repeats=2))
        yield study, attempt, script


def log_of(study, attempt):
    (path,) = (folder_of(study, attempt) / "inspect").glob("*.eval")
    return path


# --- The manifest ----------------------------------------------------------------------------------------------------------------


def test_the_manifest_is_an_attempt_record_with_the_keys_compare_reads_the_protocol_the_digests_and_the_code_environment(recorded):
    study, attempt, _ = recorded
    contracts.validate(attempt)
    stored = (folder_of(study, attempt) / "attempt.json").read_bytes()
    assert stored == canonical.dumps(attempt)
    assert attempt["schema_version"] == "attempt/1" and attempt["operation"] == "execute" and attempt["mode"] == "llm_live"
    assert str(uuid.UUID(attempt["attempt_id"])) == attempt["attempt_id"]
    assert attempt["technical_status"] == "completed" and attempt["outcome_unknown"] is False and attempt["retry_of"] is None
    config = attempt["effective_config"]
    log = read_eval_log(str(log_of(study, attempt)), header_only=True)
    assert {"configuration", "model", "served_model", "tools", "limits", "repeats", "limit_notes", "effective_parameters"} <= set(config)
    assert (config["command"], config["workload"], config["mode"], config["partition"]) == ("run agent", "chinook", "llm_live", "dev")
    assert config["cases"] == TWO and config["repeats"] == 2
    assert config["tools"] == ["describe_schema", "query_readonly"]
    assert config["limits"] == limits_module.effective_limits(log)  # the effective limits, read back from the log
    spec = json.loads((study / "study.json").read_text())
    assert config["protocol"] == {"protocol_id": spec["protocol_id"], "protocol_digest": spec["protocol_digest"]}
    assert set(config["input_digests"]) == {"dataset", "population", "references", "cases"}
    assert config["input_digests"]["cases"] == canonical.sha256_hex((CHINOOK / "cases" / "chinook-dev.jsonl").read_bytes())
    assert attempt["effective_config_digest"] == canonical.digest(config)
    assert set(attempt["code_environment"]) == {"python", "dependency_lock", "code_revision"} == set(environment.code_environment())
    # the requested model is the one of the identity; the model the log reports stands beside it, never hidden (D-012 item 11)
    assert config["model"] == MODEL and config["served_model"] == "mockllm/model" != config["model"]
    assert config["served_model"] == log.eval.model


def test_the_served_model_is_the_one_the_episodes_outputs_report_not_the_name_the_eval_was_given(tmp_path, monkeypatch):
    """R1-04, D-012 item 11: `served_model` is what the provider reports (`output.model`, as `run.json`'s `served_models`), so a difference shows."""
    study = study_of(tmp_path)
    script = scripted()

    def serving_another_model(*args, **kwargs):
        output = script(*args, **kwargs)
        output.model = "claude-served-0001"
        return output

    patch_model(monkeypatch, serving_another_model)
    attempt = ok(live(study, "plain", "served", cases=["D03"]))
    config = attempt["effective_config"]
    log = read_eval_log(str(log_of(study, attempt)))
    assert log.eval.model == "mockllm/model"  # what Inspect filled in from the requested model
    assert config["model"] == MODEL and config["served_model"] == "claude-served-0001"
    assert read(study, attempt, "run.json")["served_models"] == ["claude-served-0001"]
    observation_set = json.loads((folder_of(study, attempt) / "observation_set.json").read_text())
    assert observation_set["provenance"]["served_model"] == "claude-served-0001"


def test_the_configuration_is_its_id_its_declared_content_and_its_resolved_system_text_and_its_digest_is_the_freeze_digest(recorded):
    study, attempt, _ = recorded
    configuration = attempt["effective_config"]["configuration"]
    assert set(configuration) == {"id", "declared", "system_text"}
    assert configuration["declared"] == WORKLOAD.declaration["configurations"]["plain"]
    assert configuration["system_text"] == WORKLOAD.system_text("plain")
    from hypotrail.agentic import study as agentic_study

    spec = json.loads((study / "study.json").read_text())
    held = agentic_study.freeze_basis(spec, CHINOOK)["configuration_digests"]["plain"]
    assert exposure.configuration_digest_of(attempt) == held


def test_the_freeze_record_and_check_informed_take_a_configuration_digest_from_the_one_core_function(recorded, monkeypatch):
    """R1-07: the Track's `freeze_basis` and `core/exposure.py` call one function, so they cannot drift."""
    from hypotrail.agentic import study as agentic_study

    study, attempt, _ = recorded
    spec = json.loads((study / "study.json").read_text())
    declared = WORKLOAD.declaration["configurations"]["plain"]
    held = agentic_study.freeze_basis(spec, CHINOOK)["configuration_digests"]["plain"]
    assert held == exposure.configuration_digest(declared, WORKLOAD.system_text("plain")) == exposure.configuration_digest_of(attempt)
    # the shape of the digest is that function's alone: changing it moves both sides together
    monkeypatch.setattr(exposure, "configuration_digest", lambda declared, system_text=None: "one-function")
    assert set(agentic_study.freeze_basis(spec, CHINOOK)["configuration_digests"].values()) == {"one-function"}
    assert exposure.configuration_digest_of(attempt) == "one-function"


def test_no_provider_secret_is_written_anywhere_in_the_study_after_an_llm_live_run_whether_or_not_it_failed(tmp_path, monkeypatch, capsys):
    study = study_of(tmp_path)
    patch_model(monkeypatch)
    code, out, err = run_cli("run", "agent", "--study", study, "--mode", "llm_live", "--config", "plain", "--request-id", "ok", "--partition", "dev",
                             "--repeats", "1", "--model", MODEL, "--cases", "D03", "--json")
    assert code == 0
    # a run that fails (the Chinook file changes during it) still leaves no key in the Study
    real = runner.run_episodes

    def changes_the_database(*args, **kwargs):
        location = real(*args, **kwargs)
        database = kwargs["workload"].database_path
        database.write_bytes(database.read_bytes() + b"\0")
        return location

    examples = chinook_examples(tmp_path)
    failing, _ = init_chinook(tmp_path, name="failing", examples=examples)
    monkeypatch.setattr(runner, "run_episodes", changes_the_database)
    code, out2, err2 = run_cli("run", "agent", "--study", failing, "--mode", "llm_live", "--config", "plain", "--request-id", "bad", "--partition",
                               "dev", "--repeats", "1", "--model", MODEL, "--cases", "D03", "--json", "--examples-dir", examples)
    assert code == EXIT_INTEGRITY_REFUSED
    for folder, shown in ((study, out + err), (failing, out2 + err2)):
        blob = b"".join(p.read_bytes() for p in folder.rglob("*") if p.is_file()) + shown.encode()
        assert FAKE_KEY.encode() not in blob


# --- The Observation set, projected from the Inspect log ---------------------------------------------------------------------------


def test_the_log_is_kept_raw_and_the_observation_set_is_projected_from_it_one_observation_per_expected_episode(tmp_path, monkeypatch):
    study = study_of(tmp_path)
    script = patch_model(monkeypatch, scripted(error_on=("D03", 1)))
    real = runner.run_episodes
    # an expected Episode the log never holds: D07 is dropped from the run, and stays expected
    monkeypatch.setattr(runner, "run_episodes", lambda cases, **kw: real([c for c in cases if c["case_id"] != "D07"], **kw))
    attempt = ok(live(study, "plain", "p", cases=["D03", "D05", "D07"]))
    folder = folder_of(study, attempt)
    roles = {ref["role"]: ref for ref in attempt["output_refs"]}
    assert {"inspect_log", "observations", "observation_set", "run_record"} <= set(roles)
    assert (study / roles["inspect_log"]["path"]).read_bytes()[:2] == b"PK"  # the raw Inspect log, kept as it is
    record = read(study, attempt, "observation_set.json")
    contracts.validate(record)
    assert (record["origin"], record["mode"], record["domain"]) == ("generated", "llm_live", "agentic")
    assert record["raw_refs"] == [roles["inspect_log"]]
    assert record["provenance"]["partition"] == "dev"
    entries = {(e["case_id"], e["repeat"]): e for e in observations_of(study, attempt)}
    assert sorted(entries) == [("D03", 0), ("D05", 0), ("D07", 0)]
    assert (entries["D03", 0]["status"], entries["D03", 0]["reason"], entries["D03", 0]["raw_answer"]) == ("failed", "execution_failed", None)
    assert (entries["D05", 0]["status"], entries["D05", 0]["reason"]) == ("produced", None)
    assert entries["D05", 0]["raw_answer"] and entries["D05", 0]["trace"]  # the final answer and the trace
    assert (entries["D07", 0]["status"], entries["D07", 0]["reason"]) == ("missing", "missing_from_log")
    assert attempt["item_counts"] == {"produced": 1, "failed": 1, "missing": 1}
    # the run record is the one #62 defines, kept as an artifact beside the log it summarises
    run_record = json.loads((study / roles["run_record"]["path"]).read_text())
    assert run_record["mode"] == "llm_live" and run_record["request_source"] == "this_attempt"
    assert (folder / run_record["inspect_log"]).is_file() and run_record["inspect_log"] == f"inspect/{log_of(study, attempt).name}"
    assert script.calls  # the model was asked
    # the log is read through Inspect's public API: no hand-written parser of its storage format
    source = Path(agentic_live.__file__).with_name("run.py").read_text(encoding="utf-8")
    assert "zipfile" not in source and "ZipFile" not in source


def test_the_population_is_an_artifact_of_the_attempt_the_selected_cases_times_the_repeats_of_one_partition(recorded):
    study, attempt, _ = recorded
    record = read(study, attempt, "observation_set.json")
    ref = record["population_ref"]
    assert ref["path"].startswith(f"attempts/{attempt['attempt_id']}/") and ref["role"] == "run_population"
    population = json.loads((study / ref["path"]).read_text())
    assert population == {"episodes": [{"case_id": c, "repeat": r} for c in TWO for r in (0, 1)]}
    memberships = (study / "artifacts" / "memberships.csv").read_text().splitlines()
    assert {line.split(",")[1] for line in memberships if line.split(",")[0] in TWO} == {"dev"}
    assert [e["status"] for e in observations_of(study, attempt)] == ["produced"] * 4


def test_with_the_provider_failing_on_one_episode_the_attempt_is_completed_and_that_episode_alone_is_failed(tmp_path, monkeypatch):
    study = study_of(tmp_path)
    script = patch_model(monkeypatch, scripted(error_on=("D03", 1), error_message="transport down"))
    code, payload, err = live(study, "plain", "t")
    assert code == 0, (payload, err)
    attempt = payload["attempt"]
    assert attempt["technical_status"] == "completed" and attempt["item_counts"] == {"produced": 1, "failed": 1, "missing": 0}
    by_case = {e["case_id"]: e for e in observations_of(study, attempt)}
    assert (by_case["D03"]["status"], by_case["D03"]["reason"], by_case["D03"]["raw_answer"], by_case["D03"]["final_answer"]) == ("failed", "execution_failed", None, None)
    assert by_case["D05"]["status"] == "produced"
    assert len(script.calls) == 3  # D03: one failed call, no retry; D05: a tool call, then its answer
    assert "transport down" not in json.dumps(attempt)  # the error text is not an answer, and not a reason


# --- Limits, the database, tokens and Repeats ------------------------------------------------------------------------------------


def test_the_run_applies_the_limits_of_the_track_with_the_cache_off_and_no_retry_and_reads_them_back_in_both_modes(tmp_path, monkeypatch):
    study = study_of(tmp_path)
    patch_model(monkeypatch)
    expected = {
        "model_turns": 6, "time_seconds": 60, "output_token_budget": 4000, "token_budget_metering": "output", "max_output_tokens": 1024,
        "concurrency": 1, "response_cache": False, "sample_retries": 0, "transport_retries": 0, "tool_calls": None,
    }
    for attempt in (ok(live(study, "plain", "l", cases=["D03"])), ok(fixture(study, "plain", "f"))):
        config = attempt["effective_config"]
        log = read_eval_log(str(log_of(study, attempt)), header_only=True)
        assert config["limits"] == limits_module.effective_limits(log)
        assert {key: config["limits"][key] for key in expected} == expected, attempt["mode"]
        assert config["limits"]["query_caps"] == QueryCaps().as_dict(), attempt["mode"]  # the per-query caps of the SQL tool
        # what Inspect cannot enforce is stated beside the limits, never inside them (the `budgets` check reads `limits`)
        assert config["limit_notes"]["tool_calls"] == limits_module.NOT_ENFORCEABLE["tool_calls"]
        assert "limit_notes" not in config["limits"]


@pytest.mark.parametrize("mode", ["llm_live", "scripted_fixture"])
def test_a_change_of_the_chinook_file_during_the_run_is_database_changed_and_the_attempt_ends_failed_with_a_reason(tmp_path, monkeypatch, mode):
    examples = chinook_examples(tmp_path)
    study, _ = init_chinook(tmp_path, examples=examples)
    patch_model(monkeypatch)
    real = runner.run_episodes

    def changes_the_database(*args, **kwargs):
        location = real(*args, **kwargs)
        database = database_of(examples)
        database.write_bytes(database.read_bytes() + b"\0")
        return location

    monkeypatch.setattr(runner, "run_episodes", changes_the_database)
    more = ["--examples-dir", examples]
    code, payload, _ = live(study, "plain", "r", *more) if mode == "llm_live" else fixture(study, "plain", "r", *more)
    assert (code, payload["error"]["code"]) == (EXIT_INTEGRITY_REFUSED, "DATABASE_CHANGED")
    (folder,) = (study / "attempts").iterdir()
    manifest = json.loads((folder / "attempt.json").read_text())
    assert manifest["technical_status"] == "failed" and manifest["reason"].startswith("DATABASE_CHANGED")
    contracts.validate(manifest)


def test_tokens_and_cost_are_null_where_the_log_gives_none_and_each_repeat_is_its_own_inspect_epoch(tmp_path, monkeypatch):
    study = study_of(tmp_path)
    patch_model(monkeypatch, scripted(error_on=("D03", 1)))
    attempt = ok(live(study, "plain", "h", repeats=3, cases=["D03", "D05"]))
    entries = {(e["case_id"], e["repeat"]): e for e in observations_of(study, attempt)}
    failed = entries["D03", 0]
    assert failed["status"] == "failed" and failed["usage"]["tokens"] is None and failed["usage"]["cost"] is None  # null, never 0
    assert all(entry["usage"]["cost"] is None for entry in entries.values())  # the mock logs no cost
    assert all(entry["usage"]["tokens"] != 0 for entry in entries.values())
    log = read_eval_log(str(log_of(study, attempt)))
    assert log.eval.config.epochs == 3
    assert sorted((str(s.id), s.epoch) for s in log.samples) == [(c, e) for c in ("D03", "D05") for e in (1, 2, 3)]
    # a Repeat is not a copy of another: each ran its own tool call, with its own identifier
    ids = {r: [s["app_tool_call_id"] for s in entries["D05", r]["trace"] if s["kind"] == "tool_result"] for r in range(3)}
    assert all(len(v) == 1 for v in ids.values()) and len({v[0] for v in ids.values()}) == 3


def test_the_effective_parameters_are_the_request_parameters_the_log_records_and_null_for_what_it_does_not_show(recorded):
    study, attempt, _ = recorded
    assert attempt["effective_config"]["effective_parameters"] == {"reasoning": None, "output_cap": None}  # the mock logs no request
    request = {"model": "m", "max_tokens": 1024, "thinking": {"type": "disabled"}, "messages": [], "system": "s", "tools": []}
    log = SimpleNamespace(samples=[SimpleNamespace(events=[SimpleNamespace(event="model", call=SimpleNamespace(request=request))])])
    assert agentic_live.effective_parameters(log) == {"reasoning": {"type": "disabled"}, "output_cap": 1024}
    assert agentic_live.effective_parameters(SimpleNamespace(samples=[])) == {"reasoning": None, "output_cap": None}


def test_the_largest_allowed_request_every_dev_case_for_three_repeats_records_24_episodes(tmp_path, monkeypatch):
    study = study_of(tmp_path)
    patch_model(monkeypatch)
    attempt = ok(live(study, "plain", "big", cases=None, repeats=3))
    assert len(DEV) * 3 == 24 and attempt["item_counts"] == {"produced": 24, "failed": 0, "missing": 0}
    population = json.loads((study / read(study, attempt, "observation_set.json")["population_ref"]["path"]).read_text())
    assert len(population["episodes"]) == 24


# --- No Reference reaches the model ---------------------------------------------------------------------------------------------


def test_no_reference_reaches_the_model_in_either_mode(tmp_path, monkeypatch):
    sentinel = "REFERENCE-SENTINEL-8f2c"
    examples = chinook_examples(tmp_path)
    references = examples / "chinook" / "references" / "chinook-references.jsonl"
    records = [json.loads(line) for line in references.read_text().splitlines() if line.strip()]
    for record in records:
        record["rows"] = [[f"{sentinel}-{record['case_id']}"]]
        record["oracle_sql"] = f"SELECT '{sentinel}'"
    references.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    scenarios = examples / "chinook" / "fixtures" / "scenarios.json"
    document = json.loads(scenarios.read_text())
    for scenario in document["scenarios"]:
        if "reference" in scenario:
            scenario["reference"]["rows"] = [[sentinel]]
    scenarios.write_text(json.dumps(document), encoding="utf-8")
    study, _ = init_chinook(tmp_path, examples=examples)
    patch_model(monkeypatch)
    more = ["--examples-dir", examples]
    attempts = [ok(live(study, "plain", "n1", *more, cases=["D03"])), ok(fixture(study, "plain", "n2", *more))]
    for attempt in attempts:
        log = read_eval_log(str(log_of(study, attempt)))
        assert log.samples
        for sample in log.samples:
            assert sentinel not in json.dumps([m.model_dump(mode="json") for m in sample.messages])
            assert sentinel not in json.dumps([e.model_dump(mode="json") for e in sample.events if e.event == "model"])
        assert sentinel not in log.model_dump_json(exclude={"samples"})
        assert sentinel not in json.dumps(attempt)  # nor in what the Attempt records of the run


# --- public_check is not an Exposure for a run; check_informed -----------------------------------------------------------------------


def test_a_public_check_attempt_scores_nothing_and_journals_nothing_and_after_the_first_exposure_only_a_changed_configuration_is_marked(
    tmp_path, monkeypatch
):
    examples = chinook_examples(tmp_path)
    study, _ = init_chinook(tmp_path, examples=examples)
    patch_model(monkeypatch)
    more = ["--examples-dir", examples]
    run = ok(live(study, "plain", "pc", *more, partition="public_check", cases=PUBLIC_CASES[:2]))
    assert run["effective_config"]["partition"] == "public_check" and "check_informed" not in run
    assert not (study / "exposures").exists() and not list(study.glob("revisions/*/freeze.json")) and not (study / "assessments").exists()
    # the Study's first Exposure: an Assessment of imported public_check Items
    code, payload, err = assess_agent(study, import_public(tmp_path, study, "first"))
    assert code == 0, (payload, err)
    unchanged = ok(live(study, "plain", "after", *more))  # a Configuration the freeze holds unchanged is not marked
    assert "check_informed" not in unchanged
    edited_text = json.loads((examples / "chinook" / "workload.json").read_text())
    edited_text["configurations"]["verify"]["added_instruction"] = "\nCheck twice.\n"
    (examples / "chinook" / "workload.json").write_text(json.dumps(edited_text), encoding="utf-8")
    changed = ok(live(study, "verify", "changed", *more))  # a Configuration changed after the freeze is marked
    assert changed["check_informed"] is True
    contracts.validate(changed)
    unchanged_again = ok(live(study, "plain", "after-2", *more))  # plain is still the one the freeze holds
    assert "check_informed" not in unchanged_again


# --- The key is never kept: scans before every write --------------------------------------------------------------------------------


def holds_the_key(study) -> list:
    return [str(p.relative_to(study)) for p in sorted(Path(study).rglob("*")) if p.is_file() and FAKE_KEY.encode() in p.read_bytes()]


def test_a_key_planted_in_the_runs_output_ends_the_attempt_failed_with_secret_in_output_and_no_file_holds_it(tmp_path, monkeypatch):
    study = study_of(tmp_path)
    patch_model(monkeypatch, answering_with(FAKE_KEY))
    code, error = error_of(live(study, "plain", "leak", cases=["D03"]))
    assert (code, error["code"]) == (EXIT_INFRASTRUCTURE, "SECRET_IN_OUTPUT")
    assert FAKE_KEY not in json.dumps(error)
    (folder,) = (study / "attempts").iterdir()
    manifest = json.loads((folder / "attempt.json").read_text())
    assert manifest["technical_status"] == "failed" and manifest["reason"].startswith("SECRET_IN_OUTPUT")
    assert holds_the_key(study) == []
    assert not list(study.rglob("*.eval"))  # the leaking log was not published


def test_a_key_in_the_request_writes_nothing_and_exits_4_with_no_attempt(tmp_path, monkeypatch):
    study = study_of(tmp_path)
    patch_model(monkeypatch)
    before = tree_without_lock(study)
    code, error = error_of(live(study, "plain", FAKE_KEY))  # the running manifest would hold it
    assert (code, error["code"]) == (EXIT_INFRASTRUCTURE, "SECRET_IN_OUTPUT")
    assert tree_without_lock(study) == before and not list((study / "attempts").glob("*"))


def test_the_terminal_manifest_is_scanned_before_it_is_written(tmp_path, monkeypatch):
    study = study_of(tmp_path)
    patch_model(monkeypatch)
    monkeypatch.setattr(agentic_live, "effective_parameters", lambda log: {"reasoning": FAKE_KEY, "output_cap": None})
    code, error = error_of(live(study, "plain", "late", cases=["D03"]))
    assert (code, error["code"]) == (EXIT_INFRASTRUCTURE, "SECRET_IN_OUTPUT")
    (folder,) = (study / "attempts").iterdir()
    manifest = json.loads((folder / "attempt.json").read_text())
    assert manifest["technical_status"] == "failed" and holds_the_key(study) == []


def test_a_key_found_elsewhere_in_the_study_is_a_warning_that_changes_no_recorded_attempt_and_the_log_dir_is_outside_the_study(
    tmp_path, monkeypatch, capsys
):
    study = study_of(tmp_path)
    patch_model(monkeypatch)
    (study / "notes.txt").write_text(f"my key is {FAKE_KEY}\n", encoding="utf-8")
    seen = []
    real = runner.run_episodes
    monkeypatch.setattr(runner, "run_episodes", lambda *a, **k: seen.append(k["log_dir"]) or real(*a, **k))
    args = ["run", "agent", "--study", study, "--mode", "llm_live", "--config", "plain", "--request-id", "w", "--partition", "dev", "--repeats", "1",
            "--model", MODEL, "--cases", "D03", "--json"]
    code, out, err = run_cli(*args)
    payload = json.loads(out)
    assert code == 0 and payload["ok"] is True and payload["attempt"]["technical_status"] == "completed"
    assert [w["file"] for w in payload["warnings"]] == ["notes.txt"] and payload["warnings"][0]["code"] and "notes.txt" in err
    assert FAKE_KEY not in out + err
    assert not Path(seen[0]).resolve().is_relative_to(study.resolve())  # Inspect wrote its log outside the Study
    stored = json.loads((study / "attempts" / payload["attempt"]["attempt_id"] / "attempt.json").read_text())
    assert stored == payload["attempt"]
    code, out, err = run_cli(*args)  # a replay runs no scan
    assert code == 0 and json.loads(out)["replayed"] is True and json.loads(out)["warnings"] == [] and "notes.txt" not in err


def test_the_study_is_scanned_for_the_key_after_a_failed_llm_live_run_too_and_a_hit_elsewhere_is_a_warning_on_the_error(tmp_path, monkeypatch):
    """#74: « the Study folder is scanned for the key after an `llm_live` run, whether or not the run failed »."""
    examples = chinook_examples(tmp_path)
    study, _ = init_chinook(tmp_path, name="failing", examples=examples)
    patch_model(monkeypatch)
    (study / "notes.txt").write_text(f"my key is {FAKE_KEY}\n", encoding="utf-8")
    real = runner.run_episodes

    def changes_the_database(*args, **kwargs):
        location = real(*args, **kwargs)
        database = kwargs["workload"].database_path
        database.write_bytes(database.read_bytes() + b"\0")
        return location

    monkeypatch.setattr(runner, "run_episodes", changes_the_database)
    code, out, err = run_cli("run", "agent", "--study", study, "--mode", "llm_live", "--config", "plain", "--request-id", "bad", "--partition", "dev",
                             "--repeats", "1", "--model", MODEL, "--cases", "D03", "--json", "--examples-dir", examples)
    assert code == EXIT_INTEGRITY_REFUSED
    error = json.loads(out)["error"]
    assert error["code"] == "DATABASE_CHANGED"
    assert [w["file"] for w in error["details"]["warnings"]] == ["notes.txt"] and "SECRET_IN_STUDY" in err and "notes.txt" in err
    assert FAKE_KEY not in out + err


@pytest.mark.parametrize("raised, code", [(RuntimeError("provider down"), "UNEXPECTED_ERROR"), (OSError("disk gone"), "INFRASTRUCTURE_FAILURE")])
def test_the_warnings_of_the_study_scan_reach_the_json_error_whatever_exception_ended_the_attempt(tmp_path, monkeypatch, raised, code):
    """R2-01, #74 U4 « a warning on stderr (and in the `--json` object) naming the file »: not only for a Hypotrail error."""
    examples = chinook_examples(tmp_path)
    study, _ = init_chinook(tmp_path, name="failing", examples=examples)
    patch_model(monkeypatch)
    (study / "notes.txt").write_text(f"my key is {FAKE_KEY}\n", encoding="utf-8")

    def fails(*args, **kwargs):
        raise raised

    monkeypatch.setattr(runner, "run_episodes", fails)
    exit_code, out, err = run_cli("run", "agent", "--study", study, "--mode", "llm_live", "--config", "plain", "--request-id", "boom", "--partition", "dev",
                                  "--repeats", "1", "--model", MODEL, "--cases", "D03", "--json", "--examples-dir", examples)
    error = json.loads(out)["error"]
    assert error["code"] == code and exit_code == EXIT_INFRASTRUCTURE
    assert [w["file"] for w in error["details"]["warnings"]] == ["notes.txt"] and "SECRET_IN_STUDY" in err and "notes.txt" in err
    assert FAKE_KEY not in out + err


def test_a_key_that_reaches_a_published_file_after_the_log_was_scanned_is_not_written(tmp_path, monkeypatch):
    """The run record is written after the log scan: the scan before each write is its own guard."""
    study = study_of(tmp_path)
    patch_model(monkeypatch)
    real = agentic_live.record_execution

    def writes_the_key_into_the_record(**kwargs):
        record = real(**kwargs)
        path = Path(kwargs["out_dir"]) / "run.json"
        path.write_text(path.read_text(encoding="utf-8") + FAKE_KEY, encoding="utf-8")
        return record

    monkeypatch.setattr(agentic_live, "record_execution", writes_the_key_into_the_record)
    code, error = error_of(live(study, "plain", "late-file", cases=["D03"]))
    assert (code, error["code"]) == (EXIT_INFRASTRUCTURE, "SECRET_IN_OUTPUT")
    (folder,) = (study / "attempts").iterdir()
    assert json.loads((folder / "attempt.json").read_text())["technical_status"] == "failed"
    assert holds_the_key(study) == [] and not (folder / "run.json").exists()
