"""The `chinook_prose` Workload end to end through the real CLI, offline and with no key set.

Every command runs in process through `hypotrail.cli`; `chinook_prose` is evaluated only through `import agent`.
"""

import json
from pathlib import Path

from _chinook_helpers import episodes_file, import_agent, write_lines
from _study_helpers import EXAMPLES, run_cli, run_json

PROSE = EXAMPLES / "chinook_prose"
CONCISE = PROSE / "fixtures" / "answers-concise.jsonl"
VERBOSE = PROSE / "fixtures" / "answers-verbose.jsonl"
SCORER = "text_facts_v1"


def jsonl(path: Path) -> list:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def ok(result) -> dict:
    code, payload, err = result
    assert code == 0, (payload, err)
    return payload


def imported(tmp_path, study, source: Path, name: str) -> dict:
    """The payload of an `import agent` of `source`, over the Episodes its lines hold."""
    keys = [(line["case_id"], line["repeat"]) for line in jsonl(source)]
    return ok(import_agent(study, source, episodes_file(tmp_path, keys, name=f"{name}-population.json"), name))


def assessed(study, imported_payload, references) -> dict:
    return ok(run_json("assess", "--study", study, "--observations", imported_payload["observation_set_id"], "--scorer", SCORER, "--references", references))[
        "assessment"
    ]


def public_check_lines() -> list:
    """One line per `public_check` Case, written by this test: a produced answer that is the Case's Reference text."""
    references = {r["case_id"]: r["reference_text"] for r in jsonl(PROSE / "references" / "chinook-prose-references.jsonl")}
    cases = [case["case_id"] for case in jsonl(PROSE / "cases" / "chinook-prose-public-check.jsonl")]
    return [{"case_id": case_id, "repeat": 0, "observation_status": "produced", "raw_answer": references[case_id]} for case_id in cases]


def test_an_import_written_after_the_first_public_check_assessment_is_listed_check_informed(tmp_path):
    study = tmp_path / "s2e-prose"
    references = ok(run_json("init", "--workload", "chinook_prose", "--study", study))["references_id"]
    first_dev = imported(tmp_path, study, CONCISE, "s2e-dev-before")
    public = imported(tmp_path, study, write_lines(tmp_path / "s2e-public.jsonl", public_check_lines()), "s2e-public")
    assessed(study, public, references)  # the Study's first Exposure
    second_dev = imported(tmp_path, study, VERBOSE, "s2e-dev-after")
    control = assessed(study, first_dev, references)
    candidate = assessed(study, second_dev, references)
    comparison = ok(run_json("compare", "--study", study, "--control", control["assessment_id"], "--candidate", candidate["assessment_id"]))["comparison"]

    status = ok(run_json("status", "--study", study))
    assert status["exposures"]["recorded_in_this_study"] == 1
    listed = {(mark["kind"], mark["id"]) for mark in status["check_informed"]}
    assert listed == {
        ("attempt", second_dev["attempt"]["attempt_id"]),
        ("assessment", candidate["assessment_id"]),
        ("comparison", comparison["comparison_id"]),
    }
    assert ("attempt", first_dev["attempt"]["attempt_id"]) not in listed


def test_chinook_prose_compare_lists_the_two_fixture_imports_settings(tmp_path):
    study = tmp_path / "s2c-prose"
    references = ok(run_json("init", "--workload", "chinook_prose", "--study", study))["references_id"]
    control = assessed(study, imported(tmp_path, study, CONCISE, "s2c-concise"), references)
    candidate = assessed(study, imported(tmp_path, study, VERBOSE, "s2c-verbose"), references)
    code, out, err = run_cli("compare", "--study", study, "--control", control["assessment_id"], "--candidate", candidate["assessment_id"])
    assert code == 0, (out, err)

    [record] = ok(run_json("status", "--study", study))["comparisons"]
    stored = json.loads((study / "comparisons" / record["comparison_id"] / "comparison.json").read_text(encoding="utf-8"))
    assert record == stored
    declared = {"control": jsonl(CONCISE)[0]["settings"], "candidate": jsonl(VERBOSE)[0]["settings"]}
    states = {"configuration": "different", "streaming": "different", "temperature": "different"}
    states.update(dict.fromkeys(("data_snapshot", "history_source", "model", "seed"), "equal"))
    assert record.get("settings") == {
        "control": "declared",
        "candidate": "declared",
        "keys": [{"key": key, "control": declared["control"][key], "candidate": declared["candidate"][key], "state": states[key]} for key in sorted(states)],
    }
    assert declared["control"]["seed"] is None and declared["candidate"]["seed"] is None
    assert "settings: 4 equal, 3 different, 0 unknown" in out
