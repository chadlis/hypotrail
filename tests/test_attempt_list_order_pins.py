"""Pins of the order of the lists an Attempt's records hold, written before the Attempt writers move, and kept unchanged by the change that moves them.

For each of the four Attempt writers, through the command line: the roles of `input_refs` and `output_refs` in the terminal manifest, the roles of
`raw_refs` in the Observation set record, and `unknown_fields`, each in the order the writer gives it. No provider is called: `run agent` runs in
`scripted_fixture` mode.
"""

import json
from pathlib import Path

from _chinook_helpers import FIXTURE, fixture_population, import_agent, init_chinook
from _import_helpers import import_ml, ready
from _run_agent_helpers import fixture
from _study_helpers import init_study, run_ml

PRODUCER_FIELDS = ["model", "generation_time", "historical_protocol", "tool_use", "saw_public_check"]


def lists_of(study, result) -> dict:
    """{list: what it holds in order} of the Attempt `result` recorded: the roles of each list of references, and `unknown_fields` as it is."""
    code, payload, err = result
    assert code == 0, (payload, err)
    folder = Path(study) / "attempts" / payload["attempt"]["attempt_id"]
    manifest = json.loads((folder / "attempt.json").read_text(encoding="utf-8"))
    observation_set = json.loads((folder / "observation_set.json").read_text(encoding="utf-8"))
    return {
        "input_refs": [ref["role"] for ref in manifest["input_refs"]],
        "output_refs": [ref["role"] for ref in manifest["output_refs"]],
        "raw_refs": [ref["role"] for ref in observation_set["raw_refs"]],
        "unknown_fields": observation_set["unknown_fields"],
    }


def test_run_ml_records_its_lists_in_the_order_pinned(tmp_path):
    study, _ = init_study(tmp_path)
    lists = lists_of(study, run_ml(study, "seasonal_7", "dev", "r"))
    assert lists["input_refs"] == ["dataset", "memberships", "references", "workload_declaration"]
    assert lists["output_refs"] == ["predictions", "observations", "observation_set"]
    assert lists["raw_refs"] == ["predictions"]
    assert lists["unknown_fields"] == []


def test_import_ml_records_its_lists_in_the_order_pinned(tmp_path):
    study, _ = init_study(tmp_path)
    source, mapping, population, _ = ready(tmp_path)
    lists = lists_of(study, import_ml(study, source, mapping, population, "i"))
    assert lists["input_refs"] == ["dataset", "memberships", "references", "import_source", "import_mapping", "import_population"]
    assert lists["output_refs"] == ["validation_report", "observations", "observation_set"]
    assert lists["raw_refs"] == ["import_source"]
    assert lists["unknown_fields"] == PRODUCER_FIELDS


def test_run_agent_records_its_lists_in_the_order_pinned(tmp_path):
    study, _ = init_chinook(tmp_path)
    lists = lists_of(study, fixture(study, "plain", "f"))
    assert lists["input_refs"] == ["dataset", "memberships", "references", "answer_schema", "workload_declaration"]
    assert lists["output_refs"] == ["run_population", "inspect_log", "run_record", "self_check", "observations", "observation_set"]
    assert lists["raw_refs"] == ["inspect_log"]
    assert lists["unknown_fields"] == []


def test_import_agent_records_its_lists_in_the_order_pinned(tmp_path):
    study, _ = init_chinook(tmp_path)
    lists = lists_of(study, import_agent(study, FIXTURE, fixture_population(tmp_path), "i"))
    assert lists["input_refs"] == ["dataset", "memberships", "references", "answer_schema", "import_source", "import_population"]
    assert lists["output_refs"] == ["validation_report", "observations", "observation_set"]
    assert lists["raw_refs"] == ["import_source"]
    assert lists["unknown_fields"] == PRODUCER_FIELDS
