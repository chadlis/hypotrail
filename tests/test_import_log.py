"""Ticket #69: `import agent` adopts an Inspect log (read through Inspect's public API) and `assess` scores its kept trace."""

import json
from pathlib import Path

import pytest
from _chinook_helpers import episodes_file, import_agent, init_chinook, references_id
from _log_helpers import KEPT_LOGS, kept_log, scripted_log
from _study_helpers import run_json, sha256

from hypotrail.core import contracts


@pytest.fixture
def study(tmp_path):
    return init_chinook(tmp_path)[0]


def keys(*case_ids, repeats=1):
    return [(case, repeat) for case in case_ids for repeat in range(repeats)]


def attempt_dir(study, attempt):
    return Path(study) / "attempts" / attempt["attempt_id"]


def observation_set_of(study, attempt):
    return json.loads((attempt_dir(study, attempt) / "observation_set.json").read_text())


def normalized_of(study, attempt):
    return [json.loads(line) for line in (attempt_dir(study, attempt) / "observations.jsonl").read_text().splitlines()]


def error_of(payload):
    error = payload["error"]
    assert set(error) == {"code", "message", "stage", "details"}
    return error


def imported(tmp_path, study, log, population_keys, request_id="log"):
    code, payload, err = import_agent(study, log, episodes_file(tmp_path, population_keys), request_id)
    assert code == 0, (payload, err)
    return payload["attempt"]


# --- AC1: read through the public API, every expected Case x Repeat recovered -------------------------------------------


def test_a_log_is_accepted_as_an_import_attempt_with_every_expected_episode(tmp_path, study):
    """T23 (SPEC §10)."""
    log = scripted_log(tmp_path, ("D01", "D03"), repeats=2)
    attempt = imported(tmp_path, study, log, keys("D01", "D03", repeats=2))
    contracts.validate(attempt)
    assert (attempt["operation"], attempt["mode"], attempt["technical_status"]) == ("import", "external_unknown", "completed")
    assert attempt["item_counts"] == {"produced": 4, "failed": 0, "missing": 0}
    assert [(e["case_id"], e["repeat"], e["status"]) for e in normalized_of(study, attempt)] == [
        ("D01", 0, "produced"), ("D01", 1, "produced"), ("D03", 0, "produced"), ("D03", 1, "produced"),
    ]


# --- AC3: the verdicts are those of `rescore_log`, Episode by Episode and Criterion by Criterion ---------------------------

from _agent_helpers import CHINOOK, REFERENCES, WORKLOAD, ScriptedModel, read_jsonl
from _assess_helpers import rows_of

from hypotrail.agentic import rescore

SCHEMA = json.loads((CHINOOK / "schemas" / "table-answer.schema.json").read_text())
REFS = {r["case_id"]: r for r in read_jsonl(REFERENCES)}
SCORER = "chinook_contract_v1"


def assessed(study, attempt):
    observation_set = observation_set_of(study, attempt)["observation_set_id"]
    code, payload, err = run_json("assess", "--study", study, "--observations", observation_set, "--scorer", SCORER, "--references", references_id(study))
    assert code == 0, (payload, err)
    return payload["assessment"]


def per_item_of(study, assessment):
    return {(r["case_id"], int(r["repeat"]), r["criterion"]): r for r in rows_of(Path(study) / assessment["per_item_ref"]["path"])}


def assert_same_verdicts_as_rescore(study, assessment, log, expected):
    rows = per_item_of(study, assessment)
    verdicts = rescore.rescore_log(str(log), REFS, schema=SCHEMA, expected=expected, workload=WORKLOAD)
    assert len(verdicts) == len(expected)
    for verdict in verdicts:
        for criterion in verdict["criteria"]:
            row = rows[verdict["case_id"], verdict["repeat"], criterion["name"]]
            score = "" if criterion["score"] is None else ("true" if criterion["score"] else "false")
            assert (row["execution_status"], row["state"], row["score"], row["reason"]) == (
                verdict["status"], criterion["state"], score, criterion["reason"] or ""
            ), (verdict["case_id"], verdict["repeat"], criterion["name"])
    assert len(rows) == 4 * len(expected)


def test_the_verdicts_of_a_scripted_log_are_those_of_rescore_log_and_an_absent_episode_is_missing(tmp_path, study):
    log = scripted_log(tmp_path, ("D01", "D03", "D05"))
    expected = keys("D01", "D03", "D05", "D08")  # D08 is absent from the log
    attempt = imported(tmp_path, study, log, expected)
    assert attempt["item_counts"] == {"produced": 3, "failed": 0, "missing": 1}
    assert_same_verdicts_as_rescore(study, assessed(study, attempt), log, expected)


def test_the_verdicts_of_failed_episodes_are_those_of_rescore_log(tmp_path, study):
    cases = WORKLOAD.cases("dev", ["D01", "D03"])
    errored = scripted_log(tmp_path, ("D01", "D03"), script=ScriptedModel(cases, error_on=("D03", 1)), name="errored")
    expected = keys("D01", "D03")
    attempt = imported(tmp_path, study, errored, expected, "errored")
    assert attempt["item_counts"] == {"produced": 1, "failed": 1, "missing": 0}
    assert_same_verdicts_as_rescore(study, assessed(study, attempt), errored, expected)
    # an Episode stopped by the agent's own turn limit is scored false, not unscored
    looping = scripted_log(tmp_path, ("D03",), script=ScriptedModel(WORKLOAD.cases("dev", ["D03"]), always_call_tool=True), name="looping")
    attempt = imported(tmp_path, study, looping, keys("D03"), "looping")
    assessment = assessed(study, attempt)
    assert_same_verdicts_as_rescore(study, assessment, looping, keys("D03"))
    assert per_item_of(study, assessment)["D03", 0, "contract_success"]["reason"] == "turn_limit"


@pytest.mark.parametrize("index", range(len(KEPT_LOGS)))
def test_the_verdicts_of_each_kept_live_log_are_those_of_rescore_log(tmp_path, study, index):
    log = kept_log(tmp_path, index)
    expected = keys("D03", "D05")
    attempt = imported(tmp_path, study, log, expected)
    assessment = assessed(study, attempt)
    assert_same_verdicts_as_rescore(study, assessment, log, expected)
    assert any(r["state"] == "scored" for r in per_item_of(study, assessment).values() if r["criterion"] == "evidence_link_valid")  # a trace was kept


# --- AC1 again: the public API only, and the refusals --------------------------------------------------------------------

from _assess_helpers import snapshot
from inspect_ai.log import read_eval_log, write_eval_log

from hypotrail.agentic import inspect_log


def test_the_log_is_read_once_through_the_public_api_and_never_parsed_by_hand(tmp_path, study, monkeypatch):
    calls = []

    def spy(location, **kwargs):
        calls.append(Path(location).name)
        return read_eval_log(location, **kwargs)

    monkeypatch.setattr(inspect_log, "read_eval_log", spy)
    log = scripted_log(tmp_path, ("D01",))
    imported(tmp_path, study, log, keys("D01"))
    assert Path(log).name in calls
    source = Path(inspect_log.__file__).read_text(encoding="utf-8")
    assert "zipfile" not in source and "ijson" not in source and "json.loads" not in source  # no hand-written parser


def rewritten(location, edit):
    log = read_eval_log(str(location))
    edit(log)
    write_eval_log(log, str(location))
    return location


def test_a_sample_outside_the_population_or_repeated_is_refused_with_a_code_exit_2_and_nothing_is_written(tmp_path, study):
    log = scripted_log(tmp_path, ("D01", "D03"))
    outside = keys("D01")  # D03 is in the log, not in the population
    before = snapshot(study)
    code, payload, _ = import_agent(study, log, episodes_file(tmp_path, outside), "outside")
    error = error_of(payload)
    assert (code, error["code"], error["stage"], error["details"]["problem"]) == (2, "LOG_EPISODE_OUTSIDE_POPULATION", "import", "not_in_population")
    other = scripted_log(tmp_path, ("D01",), repeats=2, name="repeats")
    code, payload, _ = import_agent(study, other, episodes_file(tmp_path, keys("D01")), "repeat")
    assert (code, error_of(payload)["details"]["problem"]) == (2, "repeat_out_of_range")
    assert snapshot(study) == before


def test_a_repeated_sample_is_refused(tmp_path):
    # Inspect's `.eval` writer drops a repeated sample, so the log is read, then given a second sample for D01 in memory
    from hypotrail.core.errors import InvalidInputError

    loaded = read_eval_log(str(scripted_log(tmp_path, ("D01", "D03"))))
    loaded.samples.append(loaded.samples[0].model_copy())
    with pytest.raises(InvalidInputError) as refused:
        inspect_log.checked_episodes(loaded, keys("D01", "D03"), "dev", {"D01": "dev", "D03": "dev"})
    assert (refused.value.code, refused.value.exit_code, refused.value.stage) == ("LOG_EPISODE_DUPLICATE", 2, "import")
    assert refused.value.details == {"case_id": "D01", "repeat": 0}


def test_a_file_that_is_not_a_log_is_refused_with_a_code_and_only_the_error_type(tmp_path, study):
    junk = tmp_path / "junk.eval"
    junk.write_bytes(b"not a zip, not a log")
    before = snapshot(study)
    code, payload, _ = import_agent(study, junk, episodes_file(tmp_path, keys("D01")), "junk")
    error = error_of(payload)
    assert (code, error["code"], error["stage"]) == (2, "LOG_NOT_READABLE", "import")
    assert set(error["details"]) == {"source", "error_type"}
    assert snapshot(study) == before


# --- AC2: the original is kept, the header is declared, import_time is apart --------------------------------------------


def refs_of(attempt):
    return {ref["role"]: ref for ref in [*attempt["input_refs"], *attempt["output_refs"]]}


def test_the_original_log_is_copied_with_its_digest_and_a_validation_report_is_kept(tmp_path, study):
    """T23 (SPEC §10)."""
    log = scripted_log(tmp_path, ("D01", "D03"))
    population = episodes_file(tmp_path, keys("D01", "D03"))
    attempt = imported(tmp_path, study, log, keys("D01", "D03"))
    kept = attempt_dir(study, attempt) / "source" / Path(log).name
    assert kept.read_bytes() == Path(log).read_bytes()
    assert refs_of(attempt)["import_source"]["sha256"] == sha256(log)
    assert refs_of(attempt)["import_population"]["sha256"] == sha256(population)
    report = json.loads((attempt_dir(study, attempt) / "validation_report.json").read_text())
    assert (report["source_format"], report["source_sha256"], report["samples_read"], report["population_episodes"]) == ("inspect_log", sha256(log), 2, 2)
    assert all(check["result"] == "passed" for check in report["checks"])


def test_what_the_header_states_is_declared_never_verified_and_import_time_is_apart_from_generation_time(tmp_path, study):
    log = scripted_log(tmp_path, ("D01",))
    header = read_eval_log(str(log), header_only=True)
    attempt = imported(tmp_path, study, log, keys("D01"))
    config = attempt["effective_config"]
    producer, declared = config["producer"], config["log"]
    assert producer["model"] == {"value": "mockllm/model", "origin": "declared"}
    assert producer["generation_time"] == {"value": header.eval.created, "origin": "declared"}
    assert config["import_time"] == attempt["started_at"] != header.eval.created
    assert producer["file_mode"] == {"value": "scripted_fixture", "origin": "declared"}
    assert (declared["configuration"], declared["inspect_version"]) == ({"value": "plain", "origin": "declared"}, {"value": header.eval.packages["inspect_ai"], "origin": "declared"})
    assert declared["system_text"]["value"] == header.eval.metadata["system_text"]
    assert declared["limits"]["origin"] == "declared" and declared["limits"]["value"]["model_turns"] == 6
    assert {name: producer[name]["origin"] for name in ("historical_protocol", "tool_use", "saw_public_check", "file_origin")} == {
        "historical_protocol": "unknown", "tool_use": "unknown", "saw_public_check": "unknown", "file_origin": "unknown",
    }
    observation_set = observation_set_of(study, attempt)
    assert observation_set["provenance"]["log"] == declared and observation_set["provenance"]["import_time"] == config["import_time"]
    assert set(observation_set["unknown_fields"]) == {"historical_protocol", "tool_use", "saw_public_check", "file_origin"}
    assert "verified" not in json.dumps(attempt)


def written_outside_the_source(study, attempt):
    folder = attempt_dir(study, attempt)
    return "".join(p.read_text(encoding="utf-8") for p in folder.rglob("*") if p.is_file() and p.parent.name != "source")


def test_a_mock_model_log_is_never_labelled_llm_live_even_when_its_header_claims_it(tmp_path, study):
    log = scripted_log(tmp_path, ("D01",), metadata={"mode": "llm_live"})
    attempt = imported(tmp_path, study, log, keys("D01"))
    assert attempt["mode"] == "external_unknown"
    assert attempt["effective_config"]["producer"]["file_mode"] == {"value": None, "origin": "unknown"}
    assert "llm_live" not in written_outside_the_source(study, attempt)


def test_a_kept_live_log_is_declared_with_its_model_and_is_not_labelled_llm_live_either(tmp_path, study):
    attempt = imported(tmp_path, study, kept_log(tmp_path, 0), keys("D03", "D05"))
    assert attempt["effective_config"]["producer"]["model"] == {"value": "anthropic/claude-sonnet-5-5", "origin": "declared"}
    assert (attempt["mode"], attempt["operation"]) == ("external_unknown", "import")
    assert "llm_live" not in written_outside_the_source(study, attempt)


def test_nothing_of_the_header_beyond_the_listed_fields_is_written_to_the_study_and_nothing_in_the_log_is_executed(tmp_path, study):
    def plant(loaded):
        loaded.eval.model_args = {"api_key": "sk-PLANTED-SECRET"}
        loaded.eval.model_base_url = "https://planted.example/sk-PLANTED-SECRET"
        loaded.eval.metadata["note"] = "__import__('os').system('true')"

    log = rewritten(scripted_log(tmp_path, ("D01",)), plant)
    attempt = imported(tmp_path, study, log, keys("D01"))
    assert "PLANTED" not in written_outside_the_source(study, attempt) and "planted.example" not in written_outside_the_source(study, attempt)
    assert set(inspect_log.HEADER_FIELDS) == {"model", "generation_time", "configuration", "system_text", "mode", "limits", "inspect_version", "log_format_version", "log_status"}


# --- the kept trace: what an import keeps for scoring -----------------------------------------------------------------------


def test_the_trace_of_each_episode_is_kept_so_evidence_link_valid_is_scored_from_it(tmp_path, study):
    attempt = imported(tmp_path, study, scripted_log(tmp_path, ("D01", "D03")), keys("D01", "D03"))
    for entry in normalized_of(study, attempt):
        assert entry["answer_given_as"] == "raw_answer" and entry["final_answer"] is None
        assert any(step["kind"] == "tool_call" for step in entry["trace"])
    rows = per_item_of(study, assessed(study, attempt))
    assert {rows[case, 0, "evidence_link_valid"]["state"] for case in ("D01", "D03")} == {"scored"}
    assert {rows[case, 0, "evidence_link_valid"]["score"] for case in ("D01", "D03")} == {"true"}


# --- AC4: no model, no tool, no Chinook file, no network -------------------------------------------------------------------

import shutil
import sqlite3
import subprocess
import sys
import textwrap

from _chinook_helpers import chinook_examples


def test_import_and_assess_succeed_with_the_model_the_tools_and_the_chinook_file_made_to_fail_and_the_network_guard_on(
    tmp_path, monkeypatch, network_guard
):
    import inspect_ai
    import inspect_ai.model

    from hypotrail.agentic import runner, sql_tool

    log = scripted_log(tmp_path, ("D01", "D03"))  # written before anything is made to fail
    examples = chinook_examples(tmp_path)
    study = init_chinook(tmp_path, examples=examples)[0]
    used = []

    def never(name):
        def fail(*args, **kwargs):
            used.append(name)
            raise AssertionError(f"{name} was called")

        return fail

    for owner, name in [(sqlite3, "connect"), (inspect_ai, "eval"), (inspect_ai.model, "get_model"), (runner, "run_episodes"), (runner, "mock_model"),
                        (sql_tool, "query_readonly"), (sql_tool, "describe_schema")]:
        monkeypatch.setattr(owner, name, never(f"{owner.__name__}.{name}"))
    code, payload, err = import_agent(study, log, episodes_file(tmp_path, keys("D01", "D03")), "x", "--examples-dir", examples)
    assert code == 0, (payload, err)
    shutil.rmtree(examples / "chinook")  # the Workload's files, the Chinook file included, are gone: the frozen References are enough
    assessment = assessed(study, payload["attempt"])
    assert assessment["counts"]["expected"] == 2
    assert used == [] and network_guard.attempts == []


# --- AC5: without Inspect, a log import is refused before anything is written; a JSONL import still works --------------------

BLOCKED_SCRIPT = textwrap.dedent(
    """
    import json, sys
    for name in ("inspect_ai", "sklearn", "numpy"):
        sys.modules[name] = None  # importing any of them now raises ImportError
    from hypotrail import cli
    a = sys.argv[1:]
    code = cli.main(["import", "agent", "--study", a[0], "--source", a[1], "--population", a[2], "--request-id", a[3], "--json"])
    print("LOADED", sorted(m for m in sys.modules if sys.modules[m] is not None and m.split(".")[0] == "inspect_ai"), "EXIT", code)
    """
)


def test_without_inspect_a_log_import_is_refused_before_anything_is_written_and_a_jsonl_import_still_works(tmp_path, study):
    from _chinook_helpers import FIXTURE, fixture_population

    log = scripted_log(tmp_path, ("D01",))
    before = snapshot(study)
    done = subprocess.run(
        [sys.executable, "-c", BLOCKED_SCRIPT, str(study), str(log), str(episodes_file(tmp_path, keys("D01"))), "log"], capture_output=True, text=True
    )
    assert "EXIT 5" in done.stdout, (done.stdout, done.stderr)
    error = json.loads(done.stdout[: done.stdout.index("LOADED")])["error"]
    assert (error["code"], error["stage"], error["details"]) == ("INSPECT_UNAVAILABLE", "import", {"package": "inspect-ai"})
    assert snapshot(study) == before
    done = subprocess.run(
        [sys.executable, "-c", BLOCKED_SCRIPT, str(study), str(FIXTURE), str(fixture_population(tmp_path)), "jsonl"], capture_output=True, text=True
    )
    assert "EXIT 0" in done.stdout and "LOADED []" in done.stdout, (done.stdout, done.stderr)


# --- AC6: an Assessment of public_check Items is an Exposure of the Study (#73) -----------------------------------------------


def test_an_assessment_of_a_logged_public_check_episode_is_recorded_in_the_exposure_journal(tmp_path, study):
    log = scripted_log(tmp_path, ("E01",), partition="public_check")
    attempt = imported(tmp_path, study, log, keys("E01"))
    assert attempt["effective_config"]["partition"] == "public_check"
    code, payload, _ = run_json(
        "assess", "--study", study, "--observations", observation_set_of(study, attempt)["observation_set_id"], "--scorer", SCORER,
        "--references", references_id(study),
    )
    assert code == 0, payload
    (entry,) = [json.loads(p.read_text()) for p in (Path(study) / "exposures").glob("*.json")]
    assert entry["attempt_ids"] == [attempt["attempt_id"]] and entry["assessment_ids"] == [payload["assessment"]["assessment_id"]]


# --- Tightened A2: the request identity ------------------------------------------------------------------------------------

from hypotrail.core import requests
from hypotrail.core.errors import EXIT_LOCK_OR_CONFLICT


def test_the_identity_holds_the_declared_model_and_configuration_and_the_three_digests(tmp_path, study):
    log = scripted_log(tmp_path, ("D01", "D03"), repeats=2)
    population = episodes_file(tmp_path, keys("D01", "D03", repeats=2))
    _, payload, _ = import_agent(study, log, population, "id")
    attempt = payload["attempt"]
    identity = requests.identity(attempt["effective_config"], attempt["code_environment"])
    assert set(identity) == set(requests.ELEMENTS)
    assert (identity["command"], identity["mode"], identity["partition"], identity["model"], identity["configuration"], identity["repeats"]) == (
        "import agent", "external_unknown", "dev", "mockllm/model", "plain", 2,
    )
    assert (identity["input_digests"]["source"], identity["input_digests"]["population"]) == (sha256(log), sha256(population))


def test_the_same_request_returns_the_recorded_import_and_reads_validates_and_writes_nothing(tmp_path, study, monkeypatch):
    log = scripted_log(tmp_path, ("D01",))
    population = episodes_file(tmp_path, keys("D01"))
    _, first, _ = import_agent(study, log, population, "same")
    before = snapshot(study)

    def never(*args, **kwargs):
        raise AssertionError("the log was read in full again")

    monkeypatch.setattr(inspect_log, "checked_episodes", never)
    code, again, err = import_agent(study, log, population, "same")
    assert code == 0, (again, err)
    assert again["replayed"] is True and again["attempt"] == first["attempt"]
    assert snapshot(study) == before


@pytest.mark.parametrize("what", ["log", "population"])
def test_the_same_request_id_with_another_log_or_population_is_request_conflict_exit_6(tmp_path, study, what):
    log = scripted_log(tmp_path, ("D01", "D03"))
    population = episodes_file(tmp_path, keys("D01", "D03"))
    _, first, _ = import_agent(study, log, population, "same")
    before = snapshot(study)
    args = (scripted_log(tmp_path, ("D01", "D03"), name="other"), population) if what == "log" else (log, episodes_file(tmp_path, keys("D01", "D03", repeats=1)[:1], name="other.json"))
    code, payload, _ = import_agent(study, *args, "same")
    error = error_of(payload)
    assert (code, error["code"], error["details"]["attempt_id"], error["details"]["differs"]) == (
        EXIT_LOCK_OR_CONFLICT, "REQUEST_CONFLICT", first["attempt"]["attempt_id"], ["input_digests"],
    )
    assert snapshot(study) == before


# --- R1-10 (#69, ENV-02): only the supported Inspect version, installed and written in the log -------------------------------


def test_the_supported_inspect_version_is_the_one_pyproject_pins():
    import tomllib

    from hypotrail.agentic.imports import SUPPORTED_INSPECT

    pinned = tomllib.loads((Path(__file__).resolve().parent.parent / "pyproject.toml").read_text())["project"]["optional-dependencies"]["agent"]
    assert f"inspect-ai=={SUPPORTED_INSPECT}" in pinned


def test_an_installed_inspect_other_than_the_supported_one_refuses_a_log_import_with_exit_5_and_writes_nothing(tmp_path, study, monkeypatch):
    from importlib import metadata

    log = scripted_log(tmp_path, ("D01",))
    before = snapshot(study)
    real = metadata.version
    monkeypatch.setattr(metadata, "version", lambda name: "0.0.1" if name == "inspect-ai" else real(name))
    code, payload, _ = import_agent(study, log, episodes_file(tmp_path, keys("D01")), "log")
    assert code == 5 and payload["error"]["code"] == "INSPECT_UNAVAILABLE"
    assert payload["error"]["details"] == {"package": "inspect-ai", "installed": "0.0.1", "supported": "0.3.287"}
    assert snapshot(study) == before


def test_a_log_written_by_another_inspect_version_is_refused_and_nothing_is_written(tmp_path, study):
    from inspect_ai.log import read_eval_log, write_eval_log

    log = scripted_log(tmp_path, ("D01",))
    loaded = read_eval_log(str(log))
    loaded.eval.packages = {"inspect_ai": "0.3.1"}
    other = tmp_path / "other-version.eval"
    write_eval_log(loaded, str(other))
    before = snapshot(study)
    code, payload, _ = import_agent(study, other, episodes_file(tmp_path, keys("D01")), "log")
    error = payload["error"]
    assert (code, error["code"], error["stage"]) == (2, "LOG_INSPECT_VERSION_UNSUPPORTED", "import")
    assert error["details"]["log_inspect_version"] == "0.3.1" and error["details"]["supported"] == "0.3.287"
    assert snapshot(study) == before


# --- R1-11 (#72 Tightened D): the log's latency and token usage are kept and reported descriptively -----------------------------


def test_a_log_import_keeps_each_episodes_latency_and_tokens_and_a_comparison_reports_their_sums(tmp_path, study):
    from inspect_ai.log import read_eval_log

    logs = [kept_log(tmp_path, 0), kept_log(tmp_path, 3)]  # l12-plain and l12b-plain: the same Cases, one Repeat each
    attempts = [imported(tmp_path, study, log, keys("D03", "D05"), request_id=f"log-{n}") for n, log in enumerate(logs)]
    expected = []
    for log, attempt in zip(logs, attempts):
        samples = read_eval_log(str(log)).samples
        want = {(str(s.id), s.epoch - 1): (float(s.total_time), sum(u.total_tokens for u in s.model_usage.values())) for s in samples}
        got = {(e["case_id"], e["repeat"]): (e["usage"]["latency_seconds"], e["usage"]["tokens"]) for e in normalized_of(study, attempt)}
        assert got == want and all(latency > 0 and tokens > 0 for latency, tokens in got.values())
        expected.append((sum(l for l, _ in got.values()), sum(t for _, t in got.values())))
    assessments = [assessed(study, attempt) for attempt in attempts]
    code, payload, err = run_json("compare", "--study", study, "--control", assessments[0]["assessment_id"], "--candidate", assessments[1]["assessment_id"], "--factor", "budgets")
    if code != 0:  # the two kept logs may differ in a planned element: name the one the refusal gives
        factor = payload["error"]["details"]["check"]
        code, payload, err = run_json("compare", "--study", study, "--control", assessments[0]["assessment_id"], "--candidate", assessments[1]["assessment_id"], "--factor", factor)
    assert code == 0, (payload, err)
    descriptive = payload["comparison"]["descriptive"]
    for side, (latency, tokens) in zip(("control", "candidate"), expected):
        assert descriptive[side]["latency_seconds"] == pytest.approx(latency) and descriptive[side]["tokens"] == tokens
        assert descriptive[side]["cost"] is None


def test_a_jsonl_import_has_no_usage_so_latency_and_tokens_stay_null_never_zero(tmp_path, study):
    from _chinook_helpers import FIXTURE, fixture_population
    from _chinook_helpers import import_agent as import_jsonl

    code, payload, err = import_jsonl(study, FIXTURE, fixture_population(tmp_path), "jsonl")
    assert code == 0, (payload, err)
    assert all(e.get("usage") is None for e in normalized_of(study, payload["attempt"]))
    from hypotrail.core import agent_comparison

    side = {"observation_set": observation_set_of(study, payload["attempt"])}
    measures = agent_comparison._measures(study, side)
    assert measures["latency_seconds"] is None and measures["tokens"] is None
