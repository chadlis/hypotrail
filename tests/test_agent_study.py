"""Ticket #68: `init` creates a Study of the tool-using agent Track, with its References set as a Study artifact."""

import json
from pathlib import Path

import pytest
from _chinook_helpers import chinook_examples, init_chinook, spec_of
from _study_helpers import ROOT, run_json

from hypotrail.core import contracts
from hypotrail.core.errors import EXIT_INVALID_INPUT


def test_init_creates_a_chinook_study_with_its_references_as_a_study_artifact(tmp_path):
    study, spec = init_chinook(tmp_path)
    assert spec == spec_of(study)
    contracts.validate(spec)
    assert (spec["domain"], spec["workload"], spec["protocol_id"]) == ("agentic", "chinook", "chinook:protocol")
    by_role = {e["ref"]["role"]: e for e in spec["artifacts"]}
    assert set(by_role) == {"memberships", "references", "answer_schema"}
    kept = Path(study) / by_role["references"]["ref"]["path"]
    assert kept.read_bytes() == (ROOT / "examples/chinook/references/chinook-references.jsonl").read_bytes()
    assert by_role["references"]["artifact_id"].startswith("references-")
    (dataset,) = spec["dataset_refs"]
    assert (Path(study) / dataset["path"]).read_bytes() == (ROOT / "examples/chinook/data/Chinook_Sqlite.sqlite").read_bytes()


def test_the_primary_criterion_is_contract_success_declared_in_the_workload_and_named_by_the_study(tmp_path):
    declaration = json.loads((ROOT / "examples/chinook/workload.json").read_text(encoding="utf-8"))
    assert declaration["primary_criterion"] == "contract_success"
    _, spec = init_chinook(tmp_path)
    assert spec["primary_metric"]["id"] == "contract_success"
    assert spec["primary_metric"]["direction"] == "higher_is_better"


def test_the_primary_criterion_is_read_from_the_declaration_not_from_the_code(tmp_path):
    examples = chinook_examples(tmp_path, edit=lambda d: d.update(primary_criterion="exact_table"))
    _, spec = init_chinook(tmp_path, examples=examples)
    assert spec["primary_metric"]["id"] == "exact_table"


def test_a_primary_criterion_the_scorer_does_not_have_is_refused_and_no_study_is_created(tmp_path):
    examples = chinook_examples(tmp_path, edit=lambda d: d.update(primary_criterion="vibes"))
    study = tmp_path / "study"
    code, payload, _ = run_json("init", "--workload", "chinook", "--study", study, "--examples-dir", examples)
    assert code == EXIT_INVALID_INPUT and payload["error"]["code"] == "DECLARATION_VALUE_NOT_ALLOWED"
    assert not study.exists()


@pytest.mark.parametrize("key", ["primary_criterion", "question", "objective", "limitations"])
def test_a_chinook_workload_that_declares_nothing_for_the_study_spec_is_refused(tmp_path, key):
    examples = chinook_examples(tmp_path, edit=lambda d: d.pop(key))
    study = tmp_path / "study"
    code, payload, _ = run_json("init", "--workload", "chinook", "--study", study, "--examples-dir", examples)
    assert code == EXIT_INVALID_INPUT
    assert payload["error"]["code"] == "DECLARATION_INCOMPLETE" and payload["error"]["details"]["key"] == key
    assert not study.exists()


def test_the_protocol_digest_changes_when_the_references_change(tmp_path):
    _, one = init_chinook(tmp_path, name="one")
    examples = chinook_examples(tmp_path)
    references = examples / "chinook" / "references" / "chinook-references.jsonl"
    references.write_bytes(references.read_bytes().replace(b"[[3503]]", b"[[3504]]", 1))
    _, other = init_chinook(tmp_path, name="two", examples=examples)
    assert one["protocol_digest"] != other["protocol_digest"]


def test_a_workload_of_an_unknown_track_is_still_refused_and_no_study_is_created(tmp_path):
    examples = chinook_examples(tmp_path, edit=lambda d: d.update(track="something_else"))
    code, payload, _ = run_json("init", "--workload", "chinook", "--study", tmp_path / "s", "--examples-dir", examples)
    assert code == EXIT_INVALID_INPUT and payload["error"]["code"] == "WORKLOAD_TRACK_NOT_SUPPORTED"
    assert payload["error"]["details"]["supported"] == ["temporal_regression", "tool_using_agent"]
    assert not (tmp_path / "s").exists()
