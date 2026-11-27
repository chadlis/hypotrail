"""The `chinook_prose` Workload end to end through the real CLI, offline and with no key set.

Every command runs in process through `hypotrail.cli`; `chinook_prose` is evaluated only through `import agent`.
"""

import json
import shutil
from pathlib import Path

from _chinook_helpers import episodes_file, import_agent, write_lines
from _study_helpers import EXAMPLES, run_json

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


def test_chinook_prose_declares_disjoint_groups_and_a_moved_group_is_refused_before_init_writes(tmp_path):
    assert json.loads((PROSE / "workload.json").read_text(encoding="utf-8")).get("group_partition_rule") == "disjoint"
    ok(run_json("init", "--workload", "chinook_prose", "--study", tmp_path / "s2-rule-prose"))

    examples = tmp_path / "examples"
    shutil.copytree(EXAMPLES, examples)
    public = examples / "chinook_prose" / "cases" / "chinook-prose-public-check.jsonl"
    cases = jsonl(public)
    cases[0]["group"] = jsonl(PROSE / "cases" / "chinook-prose-dev.jsonl")[0]["group"]
    write_lines(public, cases)
    study = tmp_path / "s2-rule-moved"
    code, payload, err = run_json("init", "--workload", "chinook_prose", "--study", study, "--examples-dir", examples)
    assert (code, payload.get("error", {}).get("code")) == (2, "GROUP_IN_TWO_PARTITIONS"), (payload, err)
    assert not study.exists()
