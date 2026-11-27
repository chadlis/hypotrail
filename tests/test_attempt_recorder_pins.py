"""Pins of what the Attempt recorder writes, written before the four Attempt writers move into it, and kept unchanged by the change that moves them.

For each of the four Attempt writers and each Mode it has, through the command line: the keys of the `running`, terminal and `failed` manifests and of
the Observation set record; the fixed values those records hold; the Reason a `failed` manifest gives for an OS error, a Hypotrail error and any other
error, and that the text of an OS error reaches neither the Study nor stderr; the order of the keys of the Attempt the command prints; and the keys of a normalized Observation. An Attempt's IDs and timestamps differ at
each call, so these compare keys and fixed values, not whole files.

The `running` and the `failed` manifests are reached through a patched `artifacts.replace_bytes`, as `tests/test_handbook.py` does: every manifest it is
given is kept, and the fault is raised in place of the terminal manifest's write, inside the live process. No provider is called: `llm_live` runs on
Inspect's mock model, patched as the `run agent` tests do.
"""

import csv
import io
import json
from pathlib import Path

import pytest
from _chinook_helpers import FIXTURE, fixture_population, import_agent, init_chinook
from _import_helpers import import_ml, ready
from _run_agent_helpers import fixture, live, patch_model
from _study_helpers import init_study, run_ml

from hypotrail.core import artifacts
from hypotrail.core.errors import HypotrailError

RUN_ML, IMPORT_ML, RUN_AGENT_FIXTURE, RUN_AGENT_LIVE, IMPORT_AGENT = (
    "run ml", "import ml", "run agent scripted_fixture", "run agent llm_live", "import agent",
)
ROWS = (RUN_ML, IMPORT_ML, RUN_AGENT_FIXTURE, RUN_AGENT_LIVE, IMPORT_AGENT)

RUNNING_KEYS = {
    "kind", "schema_version", "attempt_id", "request_id", "operation", "mode", "technical_status", "started_at", "finished_at",
    "effective_config", "effective_config_digest", "input_refs", "code_environment", "outcome_unknown", "retry_of",
}
TERMINAL_KEYS = RUNNING_KEYS | {"output_refs", "item_counts"}
FAILED_KEYS = RUNNING_KEYS | {"reason"}
OBSERVATION_SET_KEYS = {
    "kind", "schema_version", "observation_set_id", "attempt_id", "domain", "origin", "mode", "population_ref", "raw_refs", "normalized_ref",
    "provenance", "unknown_fields",
}
EXPECTED_KEYS = {
    RUN_ML: {"running": RUNNING_KEYS, "terminal": TERMINAL_KEYS, "failed": FAILED_KEYS, "observation_set": OBSERVATION_SET_KEYS},
    IMPORT_ML: {"running": RUNNING_KEYS, "terminal": TERMINAL_KEYS, "failed": FAILED_KEYS, "observation_set": OBSERVATION_SET_KEYS},
    RUN_AGENT_FIXTURE: {"running": RUNNING_KEYS, "terminal": TERMINAL_KEYS, "failed": FAILED_KEYS, "observation_set": OBSERVATION_SET_KEYS},
    RUN_AGENT_LIVE: {
        "running": RUNNING_KEYS | {"case_digests"},
        "terminal": TERMINAL_KEYS | {"case_digests"},
        "failed": FAILED_KEYS | {"case_digests"},
        "observation_set": OBSERVATION_SET_KEYS,
    },
    IMPORT_AGENT: {"running": RUNNING_KEYS, "terminal": TERMINAL_KEYS, "failed": FAILED_KEYS, "observation_set": OBSERVATION_SET_KEYS},
}


def manifest_values(operation, mode, technical_status) -> dict:
    return {
        "kind": "attempt", "schema_version": "attempt/1", "operation": operation, "mode": mode, "technical_status": technical_status,
        "outcome_unknown": False,
    }


def values_of(operation, mode, origin, domain) -> dict:
    return {
        "running": manifest_values(operation, mode, "running"),
        "terminal": manifest_values(operation, mode, "completed"),
        "failed": manifest_values(operation, mode, "failed"),
        "observation_set": {"kind": "observations", "schema_version": "observations/1", "mode": mode, "origin": origin, "domain": domain},
    }


EXPECTED_VALUES = {
    RUN_ML: values_of("execute", "native_ml", "generated", "regression"),
    IMPORT_ML: values_of("import", "external_unknown", "imported", "regression"),
    RUN_AGENT_FIXTURE: values_of("execute", "scripted_fixture", "generated", "agentic"),
    RUN_AGENT_LIVE: values_of("execute", "llm_live", "generated", "agentic"),
    IMPORT_AGENT: values_of("import", "external_unknown", "imported", "agentic"),
}

INJECTED = HypotrailError("INJECTED_FAULT", "an injected fault", stage="test")
FAULTS = {"os": OSError("disk full"), "hypotrail": INJECTED, "other": RuntimeError("a text that is never recorded")}
# Every writer records an error as `coded_error` names it.
AS_CODED_ERROR_NAMES_IT = {
    "os": "INFRASTRUCTURE_FAILURE: OSError", "hypotrail": "INJECTED_FAULT: an injected fault", "other": "UNEXPECTED_ERROR: unexpected RuntimeError",
}
EXPECTED_REASONS = {row: AS_CODED_ERROR_NAMES_IT for row in ROWS}

# The keys of the Attempt the command prints with `--json`, in the order it prints them.
PRINTED_ORDER = [
    "kind", "schema_version", "attempt_id", "request_id", "operation", "mode", "technical_status", "started_at", "finished_at",
    "effective_config", "effective_config_digest", "input_refs", "code_environment", "outcome_unknown", "retry_of", "output_refs", "item_counts",
]
EXPECTED_PRINTED_ORDER = {
    RUN_ML: PRINTED_ORDER,
    IMPORT_ML: PRINTED_ORDER,
    RUN_AGENT_FIXTURE: PRINTED_ORDER,
    RUN_AGENT_LIVE: [*PRINTED_ORDER[:12], "case_digests", *PRINTED_ORDER[12:]],
    IMPORT_AGENT: PRINTED_ORDER,
}

ML_COLUMNS = ["row_id", "status", "reason", "y_pred_raw", "y_pred"]
RUN_AGENT_ENTRY_KEYS = {"case_id", "repeat", "status", "reason", "raw_answer", "final_answer", "answer_given_as", "trace", "usage"}
IMPORT_AGENT_ENTRY_KEYS = {"case_id", "repeat", "status", "raw_answer", "final_answer", "answer_given_as", "trace"}
USAGE_KEYS = frozenset({"latency_seconds", "tokens", "cost"})
# (the keys of a normalized Observation, the key sets of their `usage`, None for an entry whose `usage` is null or absent): each writer's own.
EXPECTED_NORMALIZED = {
    RUN_ML: (ML_COLUMNS, None),
    IMPORT_ML: (ML_COLUMNS, None),
    RUN_AGENT_FIXTURE: (RUN_AGENT_ENTRY_KEYS, {USAGE_KEYS, None}),
    RUN_AGENT_LIVE: (RUN_AGENT_ENTRY_KEYS, {USAGE_KEYS}),
    IMPORT_AGENT: (IMPORT_AGENT_ENTRY_KEYS, {None}),
}


def study_of(row, tmp_path, monkeypatch) -> Path:
    if row in (RUN_ML, IMPORT_ML):
        return init_study(tmp_path)[0]
    if row == RUN_AGENT_LIVE:
        patch_model(monkeypatch)
    return init_chinook(tmp_path)[0]


def call(row, study, tmp_path, request_id):
    """One call of the row's command through the command line, with inputs of its own under `tmp_path / request_id`."""
    inputs = tmp_path / request_id
    inputs.mkdir()
    if row == RUN_ML:
        return run_ml(study, "seasonal_7", "dev", request_id)
    if row == IMPORT_ML:
        source, mapping, population, _ = ready(inputs)
        return import_ml(study, source, mapping, population, request_id)
    if row == RUN_AGENT_FIXTURE:
        return fixture(study, "plain", request_id)
    if row == RUN_AGENT_LIVE:
        return live(study, "plain", request_id)
    return import_agent(study, FIXTURE, fixture_population(inputs), request_id)


class Manifests:
    """`artifacts.replace_bytes`, patched: each Attempt manifest it is given is kept, and `fault`, when set, is raised in place of the second write."""

    def __init__(self, monkeypatch):
        self.real, self.written, self.fault = artifacts.replace_bytes, [], None
        monkeypatch.setattr(artifacts, "replace_bytes", self.replace_bytes)

    def replace_bytes(self, study, relative, data):
        if str(relative).endswith("/attempt.json"):
            self.written.append(json.loads(data))
            if self.fault is not None and len(self.written) == 2:
                raise self.fault
        return self.real(study, relative, data)

    def run(self, row, study, tmp_path, request_id, fault=None) -> tuple:
        """(the code, the payload, the manifests written) of one call."""
        self.written, self.fault = [], fault
        code, payload, err = call(row, study, tmp_path, request_id)
        return code, payload, err, list(self.written)


def completed(row, tmp_path, monkeypatch) -> dict:
    """{record: the record} of one completed Attempt of the row, with the `failed` manifest of a second one that an OS error stopped."""
    study = study_of(row, tmp_path, monkeypatch)
    manifests = Manifests(monkeypatch)
    code, payload, err, written = manifests.run(row, study, tmp_path, "completed")
    assert code == 0, (payload, err)
    running, terminal = written
    folder = study / "attempts" / terminal["attempt_id"]
    observation_set = json.loads((folder / "observation_set.json").read_text(encoding="utf-8"))
    code, payload, err, written = manifests.run(row, study, tmp_path, "failed", FAULTS["os"])
    assert code != 0, (payload, err)
    return {"running": running, "terminal": terminal, "failed": written[-1], "observation_set": observation_set}


@pytest.mark.parametrize("row", ROWS)
def test_the_running_terminal_and_failed_manifests_and_the_observation_set_record_hold_the_keys_pinned(row, tmp_path, monkeypatch):
    records = completed(row, tmp_path, monkeypatch)
    assert set(records["running"]) == EXPECTED_KEYS[row]["running"]
    assert set(records["terminal"]) == EXPECTED_KEYS[row]["terminal"]
    assert set(records["failed"]) == EXPECTED_KEYS[row]["failed"]
    assert set(records["observation_set"]) == EXPECTED_KEYS[row]["observation_set"]


@pytest.mark.parametrize("row", ROWS)
def test_the_running_terminal_and_failed_manifests_and_the_observation_set_record_hold_the_fixed_values_pinned(row, tmp_path, monkeypatch):
    records = completed(row, tmp_path, monkeypatch)
    for record, values in EXPECTED_VALUES[row].items():
        for key, value in values.items():
            assert records[record][key] == value, (record, key)


@pytest.mark.parametrize("row", ROWS)
def test_the_reason_of_a_failed_manifest_names_an_os_error_a_hypotrail_error_and_any_other_error_as_pinned(row, tmp_path, monkeypatch):
    study = study_of(row, tmp_path, monkeypatch)
    manifests = Manifests(monkeypatch)
    reasons = {}
    for form, fault in FAULTS.items():
        code, payload, err, written = manifests.run(row, study, tmp_path, form, fault)
        assert code != 0 and written[-1]["technical_status"] == "failed", (payload, err)
        reasons[form] = written[-1]["reason"]
    assert reasons["os"] == EXPECTED_REASONS[row]["os"]
    assert reasons["hypotrail"] == EXPECTED_REASONS[row]["hypotrail"]
    assert reasons["other"] == EXPECTED_REASONS[row]["other"]


SECRET_TEXT = "sk-ant-secret"


@pytest.mark.parametrize("row", ROWS)
def test_an_os_error_whose_text_holds_a_key_leaves_a_failed_attempt_with_the_coded_reason_and_its_text_in_no_file_of_the_study_and_not_on_stderr(
    row, tmp_path, monkeypatch
):
    study = study_of(row, tmp_path, monkeypatch)
    manifests = Manifests(monkeypatch)
    code, payload, err, written = manifests.run(row, study, tmp_path, "secret", OSError(SECRET_TEXT))
    assert code == 4 and written[-1]["technical_status"] == "failed", (payload, err)
    assert written[-1]["reason"] == "INFRASTRUCTURE_FAILURE: OSError"
    assert payload["error"]["code"] == "INFRASTRUCTURE_FAILURE"
    holding = [str(path.relative_to(study)) for path in study.rglob("*") if path.is_file() and SECRET_TEXT.encode() in path.read_bytes()]
    assert holding == []
    assert SECRET_TEXT not in err


@pytest.mark.parametrize("row", ROWS)
def test_the_attempt_the_command_prints_holds_its_keys_in_the_order_pinned(row, tmp_path, monkeypatch):
    study = study_of(row, tmp_path, monkeypatch)
    code, payload, err = call(row, study, tmp_path, "printed")
    assert code == 0, (payload, err)
    assert list(payload["attempt"]) == EXPECTED_PRINTED_ORDER[row]


@pytest.mark.parametrize("row", ROWS)
def test_a_normalized_observation_holds_the_keys_and_the_usage_keys_pinned(row, tmp_path, monkeypatch):
    study = study_of(row, tmp_path, monkeypatch)
    code, payload, err = call(row, study, tmp_path, "normalized")
    assert code == 0, (payload, err)
    [ref] = [ref for ref in payload["attempt"]["output_refs"] if ref["role"] == "observations"]
    text = (study / ref["path"]).read_text(encoding="utf-8")
    keys, usage = EXPECTED_NORMALIZED[row]
    if row in (RUN_ML, IMPORT_ML):
        assert next(csv.reader(io.StringIO(text))) == keys
        return
    entries = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert {frozenset(entry) for entry in entries} == {frozenset(keys)}
    assert {None if entry.get("usage") is None else frozenset(entry["usage"]) for entry in entries} == usage
