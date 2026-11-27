"""The `chinook_prose` Workload end to end through the real CLI, offline and with no key set.

Every command runs in process through `hypotrail.cli`; `chinook_prose` is evaluated only through `import agent`.
"""

import csv
import json
import shutil
from pathlib import Path

from _chinook_helpers import episodes_file, import_agent, write_lines
from _study_helpers import EXAMPLES, run_cli, run_json

PROSE = EXAMPLES / "chinook_prose"
CONCISE = PROSE / "fixtures" / "answers-concise.jsonl"
VERBOSE = PROSE / "fixtures" / "answers-verbose.jsonl"
SCORER = "text_facts_v1"
REPEATS = PROSE / "fixtures" / "repeats"


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


def test_chinook_prose_compare_holds_an_interval_over_ten_groups(tmp_path):
    study = tmp_path / "s2g-study"
    references = ok(run_json("init", "--workload", "chinook_prose", "--study", study))["references_id"]
    control = assessed(study, imported(tmp_path, study, CONCISE, "s2g-concise"), references)
    candidate = assessed(study, imported(tmp_path, study, VERBOSE, "s2g-verbose"), references)
    code, line, err = run_cli("compare", "--study", study, "--control", control["assessment_id"], "--candidate", candidate["assessment_id"])
    assert code == 0, (line, err)
    assert " over 10 groups (Candidate minus Control" in line
    [stored_path] = (study / "comparisons").glob("*/comparison.json")
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    seed = json.loads((PROSE / "workload.json").read_text(encoding="utf-8"))["resampling"]["seed"]
    interval = stored["interval"]
    assert (interval["unit"], interval["units"], interval["cases"], interval["seed"]) == ("group", 10, 30, seed)
    assert interval["lower"] is not None and interval["upper"] is not None
    [listed] = ok(run_json("status", "--study", study))["comparisons"]
    assert listed == stored


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


def test_three_authored_versions_at_three_repeats_compared_over_groups(tmp_path):
    study = tmp_path / "s2-repeats"
    refs = ok(run_json("init", "--workload", "chinook_prose", "--study", study))["references_id"]
    declared = json.loads((REPEATS / "instability.json").read_text(encoding="utf-8"))
    cases = {row["case_id"] for row in jsonl(PROSE / "cases" / "chinook-prose-dev.jsonl")}
    reference_texts = {
        row["case_id"]: row["reference_text"]
        for row in jsonl(PROSE / "references" / "chinook-prose-references.jsonl")
        if row["case_id"] in cases
    }
    files = sorted(REPEATS.glob("*.jsonl"))
    assert len(files) == 3
    assert set(declared) == {file.stem for file in files}
    expected = {(case_id, repeat) for case_id in cases for repeat in range(3)}
    imports = []
    assessments = []
    for file in files:
        lines = jsonl(file)
        keys = [(row["case_id"], row["repeat"]) for row in lines]
        assert len(lines) == len(expected) == 90
        assert set(keys) == expected
        routes = {key: row["metadata"]["route"] for key, row in zip(keys, lines)}
        assert all(isinstance(route, str) and route for route in routes.values())
        assert len(set(routes.values())) >= 2
        assert all(row["origin"] == "authored_fixture" and row["settings"]["configuration"] == file.stem for row in lines)
        assert all(row["raw_answer"] != reference_texts[row["case_id"]] for row in lines)

        attempt = imported(tmp_path, study, file, file.stem)
        imports.append(attempt["attempt"]["attempt_id"])
        normalized = jsonl(study / "attempts" / imports[-1] / "observations.jsonl")
        assert {(row["case_id"], row["repeat"]): row["metadata"]["route"] for row in normalized} == routes
        evaluation = assessed(study, attempt, refs)
        assessments.append(evaluation["assessment_id"])
        with (study / evaluation["per_item_ref"]["path"]).open(encoding="utf-8", newline="") as stream:
            scores = [row for row in csv.DictReader(stream) if row["criterion"] == "text_facts_success"]
        assert len(scores) == 90 and all(row["state"] == "scored" and row["score"] in ("true", "false") for row in scores)
        assert {(row["case_id"], int(row["repeat"])) for row in scores} == expected
        by_case = {}
        for row in scores:
            by_case.setdefault(row["case_id"], set()).add(row["score"])
        assert sorted(case_id for case_id, values in by_case.items() if len(values) == 2) == declared[file.stem]

    comparisons = []
    for candidate in assessments[1:]:
        record = ok(run_json("compare", "--study", study, "--control", assessments[0], "--candidate", candidate))["comparison"]
        comparisons.append(record["comparison_id"])
        interval = record["interval"]
        assert (interval["unit"], interval["units"], interval["cases"]) == ("group", 10, 30)
        assert interval["lower"] is not None and interval["upper"] is not None
        assert {row["key"]: row["state"] for row in record["settings"]["keys"]}["configuration"] == "different"
    status = ok(run_json("status", "--study", study))
    assert {row["attempt_id"] for row in status["attempts"]} == set(imports)
    assert {row["assessment_id"] for row in status["assessments"]} == set(assessments)
    assert {row["comparison_id"] for row in status["comparisons"]} == set(comparisons)


def test_chinook_prose_from_init_to_a_comparison_over_groups_with_its_settings(tmp_path):
    study = tmp_path / "s2-study"
    references = ok(run_json("init", "--workload", "chinook_prose", "--study", study))["references_id"]
    control = assessed(study, imported(tmp_path, study, CONCISE, "slice-concise"), references)
    candidate = assessed(study, imported(tmp_path, study, VERBOSE, "slice-verbose"), references)
    comparison = ok(run_json(
        "compare", "--study", study,
        "--control", control["assessment_id"], "--candidate", candidate["assessment_id"],
    ))["comparison"]
    interval = comparison["interval"]
    assert (interval["unit"], interval["units"], interval["cases"]) == ("group", 10, 30)
    assert {row["key"]: row["state"] for row in comparison["settings"]["keys"]} == {
        "configuration": "different", "data_snapshot": "equal", "history_source": "equal",
        "model": "equal", "seed": "equal", "streaming": "different", "temperature": "different",
    }
    assert ok(run_json("status", "--study", study))["comparisons"] == [comparison]
    out = tmp_path / "s2-report.html"
    report = ok(run_json("report", "--study", study, "--out", out))["report"]
    page = out.read_text(encoding="utf-8")
    assert "over 10 groups" in page
    assert "temperature" in page and "data_snapshot" in page
    assert not report["exposure"]["recorded"]
