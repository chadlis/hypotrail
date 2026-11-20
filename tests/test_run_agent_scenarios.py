"""Ticket #74: `run agent --mode scripted_fixture` records the scenario Attempt, a labelled self-check that is never assessed or compared."""

import json
from pathlib import Path

import pytest
from _agent_helpers import CHINOOK
from _chinook_helpers import init_chinook
from _run_agent_helpers import error_of, fixture, folder_of, observation_set_id_of, observations_of, ok, read, tree
from _study_helpers import EXAMPLES, run_json

from hypotrail.agentic import fixture as library_fixture
from hypotrail.core import contracts
from hypotrail.core.chinook_contract import CRITERIA
from hypotrail.core.errors import EXIT_INVALID_INPUT

from inspect_ai.log import read_eval_log

BANNER = "test simulation, no LLM evaluated"
SCENARIOS = ["SCN-01", "SCN-02", "SCN-03", "SCN-04", "SCN-05", "SCN-06", "SCN-07"]


@pytest.fixture(scope="module")
def scenario_attempt(tmp_path_factory):
    study, _ = init_chinook(tmp_path_factory.mktemp("scenario"))
    attempt = ok(fixture(study, "plain", "scenarios"))
    return study, attempt


def test_the_scenario_attempt_runs_the_seven_scenarios_with_the_mock_model_and_holds_no_episode_of_a_workload_case(scenario_attempt):
    study, attempt = scenario_attempt
    contracts.validate(attempt)
    assert (attempt["mode"], attempt["operation"], attempt["technical_status"]) == ("scripted_fixture", "execute", "completed")
    config = attempt["effective_config"]
    assert (config["command"], config["mode"], config["model"], config["served_model"]) == ("run agent", "scripted_fixture", "mockllm/model", "mockllm/model")
    assert config["configuration"]["id"] == "plain" and config["partition"] is None and config["cases"] is None
    record = read(study, attempt, "observation_set.json")
    assert (record["origin"], record["mode"]) == ("generated", "scripted_fixture")
    entries = {e["case_id"]: e for e in observations_of(study, attempt)}
    assert sorted(entries) == SCENARIOS and all(e["repeat"] == 0 for e in entries.values())  # no Case of the Workload
    assert {c: e["status"] for c, e in entries.items()} == {
        "SCN-01": "produced", "SCN-02": "produced", "SCN-03": "produced", "SCN-04": "produced", "SCN-05": "failed", "SCN-06": "produced", "SCN-07": "missing",
    }
    assert attempt["item_counts"] == {"produced": 5, "failed": 1, "missing": 1}
    # the Mode and the banner, on the self-check and in the Inspect log header; no record names the results as an LLM's
    log_path = next((folder_of(study, attempt) / "inspect").glob("*.eval"))
    header = read_eval_log(str(log_path), header_only=True)
    assert (header.eval.metadata["mode"], header.eval.metadata["banner"]) == ("scripted_fixture", BANNER)
    check = read(study, attempt, "self_check.json")
    assert (check["mode"], check["banner"]) == ("scripted_fixture", BANNER) and library_fixture.BANNER == BANNER
    for name in ("attempt.json", "observation_set.json", "self_check.json", "population.json", "observations.jsonl", "run.json"):
        if (folder_of(study, attempt) / name).exists():
            assert "llm_live" not in (folder_of(study, attempt) / name).read_text(encoding="utf-8"), name


def test_the_self_check_keeps_the_statuses_and_the_counters_of_each_criterion_against_the_scenario_files_own_references_and_is_no_assessment(scenario_attempt):
    study, attempt = scenario_attempt
    check = read(study, attempt, "self_check.json")
    assert {s["scenario_id"]: s["status"] for s in check["scenarios"]} == {
        "good_result": "produced", "wrong_result": "produced", "invalid_format": "produced", "recovered_tool_error": "produced",
        "budget_exhausted": "failed", "missing_reference": "produced", "absent_from_log": "missing",
    }
    for name in CRITERIA:
        counts = check["counts"][name]
        assert (counts["N_expected"], counts["N_attempted"], counts["N_produced"]) == (7, 6, 5), name
    exact = check["counts"]["exact_table"]
    assert (exact["N_correct"], exact["N_incorrect"], exact["N_unscored"], exact["N_errored"]) == (2, 3, 2, 0)
    assert check["tool_errors"] == {"total": 1, "by_code": {"SQL_ERROR": 1}}
    assert check["business_case_outputs"] == 0
    # never a record of kind `assessment`, and no Assessment ID names it
    assert check.get("kind") != "assessment" and "assessment_id" not in json.dumps(check)
    assert not (study / "assessments").exists()
    ref = next(r for r in attempt["output_refs"] if r["role"] == "self_check")
    assert ref["path"] == f"attempts/{attempt['attempt_id']}/self_check.json"
    # the library's own scripted execution gives the same counters
    from _agent_helpers import CHINOOK as source
    import tempfile

    with tempfile.TemporaryDirectory() as out:
        library = library_fixture.run_fixture(workload_dir=source, out_dir=Path(out) / "o", configuration="plain")
    assert library["counts"] == check["counts"] and library["banner"] == check["banner"]


def test_the_population_of_a_scenario_attempt_is_an_artifact_of_the_attempt_not_the_studys_memberships(scenario_attempt):
    study, attempt = scenario_attempt
    ref = read(study, attempt, "observation_set.json")["population_ref"]
    assert ref["path"] == f"attempts/{attempt['attempt_id']}/population.json" and ref["role"] == "run_population"
    assert json.loads((study / ref["path"]).read_text()) == {"episodes": [{"case_id": s, "repeat": 0} for s in SCENARIOS]}
    memberships = (study / "artifacts" / "memberships.csv").read_text()
    assert not any(scenario in memberships for scenario in SCENARIOS)


def test_assess_on_a_scenario_observation_set_is_refused_with_unsupported_capability_before_any_other_check_and_writes_nothing(scenario_attempt, tmp_path):
    study, attempt = scenario_attempt
    observation_set = observation_set_id_of(study, attempt)
    references = next(e["artifact_id"] for e in json.loads((study / "study.json").read_text())["artifacts"] if e["ref"]["role"] == "references")
    before = tree(study)
    for label, references_id in (("a known References set", references), ("an unknown References set", "references-nonesuch")):
        code, payload, _ = run_json("assess", "--study", study, "--observations", observation_set, "--scorer", "chinook_contract_v1", "--references", references_id)
        assert (code, payload["error"]["code"]) == (EXIT_INVALID_INPUT, "UNSUPPORTED_CAPABILITY"), label
        assert payload["error"]["details"]["mode"] == "scripted_fixture"
    assert tree(study) == before and not (study / "assessments").exists()
