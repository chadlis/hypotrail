"""The declared settings of two Imports on a Comparison: each key `equal`, `different` or `unknown` (#293).

Offline: no key is set and no provider is called. The answers are the `chinook_prose` concise fixture's, under settings written here.
"""

import json
from pathlib import Path

import pytest
from _chinook_helpers import episodes_file, import_agent, write_lines
from _log_helpers import scripted_log
from _report_helpers import doc_of, report
from _study_helpers import EXAMPLES, ROOT, run_cli, run_json

from hypotrail.core import contracts

PROSE = EXAMPLES / "chinook_prose"
CONCISE = PROSE / "fixtures" / "answers-concise.jsonl"
SCORER = "text_facts_v1"
CASES = ("D01", "D03")  # the two Cases `scripted_log` writes by default
SETTINGS = {"model": "assistant-1", "seed": 1, "temperature": 0}


def ok(result) -> dict:
    code, payload, err = result
    assert code == 0, (payload, err)
    return payload


def prose_study(tmp_path, name="settings"):
    study = Path(tmp_path) / name
    return study, ok(run_json("init", "--workload", "chinook_prose", "--study", study))["references_id"]


def lines_with(*settings) -> list:
    """The concise fixture's lines of `CASES`, the i-th holding `settings[i]` (None: no `settings`; one map: the same on every line)."""
    by_case = {line["case_id"]: line for line in (json.loads(text) for text in CONCISE.read_text(encoding="utf-8").splitlines() if text.strip())}
    if len(settings) == 1:
        settings = settings * len(CASES)
    lines = []
    for case_id, declared in zip(CASES, settings):
        line = {key: value for key, value in by_case[case_id].items() if key != "settings"}
        if declared is not None:
            line["settings"] = declared
        lines.append(line)
    return lines


def assessed(tmp_path, study, references, name, source) -> str:
    """The Assessment ID of an `import agent` of `source` (a list of lines, or the path of an Inspect log) over `CASES`."""
    if isinstance(source, list):
        source = write_lines(Path(tmp_path) / f"{name}.jsonl", source)
    population = episodes_file(tmp_path, [(case_id, 0) for case_id in CASES], name=f"{name}-population.json")
    observations = ok(import_agent(study, source, population, name))["attempt"]
    folder = Path(study) / "attempts" / observations["attempt_id"]
    observation_set = json.loads((folder / "observation_set.json").read_text(encoding="utf-8"))["observation_set_id"]
    return ok(run_json("assess", "--study", study, "--observations", observation_set, "--scorer", SCORER, "--references", references))["assessment"]["assessment_id"]


def compared(tmp_path, control, candidate, *, name="pair") -> dict:
    """The Comparison record of an Import of `control` against one of `candidate`, each a list of lines or an Inspect log's path."""
    study, references = prose_study(tmp_path, name)
    ids = [assessed(tmp_path, study, references, f"{name}-{role}", source) for role, source in (("control", control), ("candidate", candidate))]
    return ok(run_json("compare", "--study", study, "--control", ids[0], "--candidate", ids[1]))["comparison"]


def key(name, control, candidate, state) -> dict:
    return {"key": name, "control": control, "candidate": candidate, "state": state}


# --- S2-3.1: the states ----------------------------------------------------------------------------------------------------------

DECLARED = {
    "the same map on both sides": (
        lambda tmp: lines_with(SETTINGS),
        lambda tmp: lines_with(dict(SETTINGS)),
        {"control": "declared", "candidate": "declared", "keys": [key("model", "assistant-1", "assistant-1", "equal"), key("seed", 1, 1, "equal"), key("temperature", 0, 0, "equal")]},
    ),
    "one key different, 1 against true": (
        lambda tmp: lines_with(SETTINGS),
        lambda tmp: lines_with({**SETTINGS, "seed": True}),
        {"control": "declared", "candidate": "declared", "keys": [key("model", "assistant-1", "assistant-1", "equal"), key("seed", 1, True, "different"), key("temperature", 0, 0, "equal")]},
    ),
    "a key on one side only": (
        lambda tmp: lines_with(SETTINGS),
        lambda tmp: lines_with({"model": "assistant-1", "temperature": 0}),
        {"control": "declared", "candidate": "declared", "keys": [key("model", "assistant-1", "assistant-1", "equal"), key("seed", 1, None, "unknown"), key("temperature", 0, 0, "equal")]},
    ),
    "the candidate's lines disagreeing": (
        lambda tmp: lines_with(SETTINGS),
        lambda tmp: lines_with(SETTINGS, {**SETTINGS, "temperature": 0.7}),
        {"control": "declared", "candidate": "unknown", "keys": [key("model", "assistant-1", None, "unknown"), key("seed", 1, None, "unknown"), key("temperature", 0, None, "unknown")]},
    ),
    "the candidate an Inspect log import": (
        lambda tmp: lines_with(SETTINGS),
        lambda tmp: scripted_log(tmp, CASES),
        {"control": "declared", "candidate": "unknown", "keys": [key("model", "assistant-1", None, "unknown"), key("seed", 1, None, "unknown"), key("temperature", 0, None, "unknown")]},
    ),
}


@pytest.mark.parametrize("case", list(DECLARED))
def test_compare_lists_each_declared_setting_with_both_values_and_its_state(tmp_path, case):
    control, candidate, expected = DECLARED[case]
    record = compared(tmp_path, control(tmp_path), candidate(tmp_path))
    assert record.get("settings") == expected


@pytest.mark.parametrize("other", [True, 1.0], ids=["true", "1.0"])
def test_a_side_whose_lines_differ_only_by_type_is_unknown_and_not_equal_to_a_side_that_declares_1(tmp_path, other):
    record = compared(tmp_path, lines_with({"seed": 1}), lines_with({"seed": 1}, {"seed": other}))
    assert record.get("settings") == {"control": "declared", "candidate": "unknown", "keys": [key("seed", 1, None, "unknown")]}


def test_a_comparison_where_neither_side_declares_settings_holds_no_settings_key(tmp_path):
    record = compared(tmp_path, lines_with(None), scripted_log(tmp_path, CASES))
    assert "settings" not in record


# --- S2-3.2: nothing else reads it -----------------------------------------------------------------------------------------------

READ_BY_NOTHING = {
    "equal settings": (SETTINGS, dict(SETTINGS)),
    "different settings": (SETTINGS, {"model": "assistant-2", "seed": True, "temperature": 0.7}),
}


@pytest.mark.parametrize("case", list(READ_BY_NOTHING))
def test_two_comparisons_of_imports_that_differ_only_by_settings_hold_the_same_comparability_warnings_and_limitations(tmp_path, case):
    control, candidate = READ_BY_NOTHING[case]
    without = compared(tmp_path, lines_with(None), lines_with(None), name="without")
    declared = compared(tmp_path, lines_with(control), lines_with(candidate), name="declared")
    assert "settings" in declared and "settings" not in without
    for field in ("comparability", "warnings", "limitations"):
        assert declared[field] == without[field], field


# --- S2-3.3: the Bike Track and the records written before -----------------------------------------------------------------------


def _bike_comparison(tmp_path) -> dict:
    from _compare_helpers import assessed as bike_assessed
    from _compare_helpers import compare

    study, _, assessments = bike_assessed(tmp_path, "seasonal_7", "ridge_v1")
    return ok(compare(study, assessments["seasonal_7"]["assessment_id"], assessments["ridge_v1"]["assessment_id"]))["comparison"]


def _chinook_comparison(tmp_path) -> dict:
    from _agent_compare_helpers import answer_lines, compare, imported
    from _chinook_helpers import init_chinook

    study, _ = init_chinook(tmp_path, name="chinook")
    _, plain = imported(tmp_path, study, "plain", answer_lines())
    _, verify = imported(tmp_path, study, "verify", answer_lines(wrong={("D01", 0)}))
    return ok(compare(study, plain, verify))["comparison"]


@pytest.mark.parametrize("track", ["bike_day", "chinook"])
def test_a_comparison_of_a_track_whose_sides_declare_no_settings_holds_no_settings_key(tmp_path, track):
    record = {"bike_day": _bike_comparison, "chinook": _chinook_comparison}[track](tmp_path)
    assert "settings" not in record


def test_a_comparison_stored_before_the_settings_key_validates_and_status_lists_it_as_stored(tmp_path):
    import shutil

    kept = ROOT / "docs" / "handbook" / "traces" / "campaign-chinook-dev" / "study"
    copy = Path(tmp_path) / "kept"
    shutil.copytree(kept, copy)
    [path] = (copy / "comparisons").glob("*/comparison.json")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert "settings" not in stored
    contracts.validate(stored)
    assert ok(run_json("status", "--study", copy))["comparisons"] == [stored]


# --- S2-3.4: the compare line ----------------------------------------------------------------------------------------------------


def compare_line(tmp_path, control, candidate) -> tuple:
    """(the stdout line of `compare` without `--json`, the Comparison record it wrote)."""
    study, references = prose_study(tmp_path, "line")
    ids = [assessed(tmp_path, study, references, f"line-{role}", source) for role, source in (("control", control), ("candidate", candidate))]
    code, out, err = run_cli("compare", "--study", study, "--control", ids[0], "--candidate", ids[1])
    assert code == 0, (out, err)
    [record] = ok(run_json("status", "--study", study))["comparisons"]
    return out.strip(), record


def test_the_compare_line_holds_the_settings_summary_with_the_records_counts_when_the_key_is_present(tmp_path):
    line, record = compare_line(tmp_path, lines_with(SETTINGS), lines_with({"model": "assistant-1", "seed": True}))
    states = [entry["state"] for entry in record.get("settings", {}).get("keys", [])]
    assert (states.count("equal"), states.count("different"), states.count("unknown")) == (1, 1, 1)
    assert "settings: 1 equal, 1 different, 1 unknown" in line


def test_the_compare_line_holds_no_settings_text_when_the_key_is_absent(tmp_path):
    line, record = compare_line(tmp_path, lines_with(None), lines_with(None))
    assert "settings" not in record
    assert "settings" not in line


# --- S2-3.5: the report ----------------------------------------------------------------------------------------------------------


def test_the_reports_settings_table_has_one_row_per_key_of_the_record_with_its_values_and_state(tmp_path):
    study, references = prose_study(tmp_path, "report")
    ids = [
        assessed(tmp_path, study, references, f"report-{role}", lines)
        for role, lines in (("control", lines_with(SETTINGS)), ("candidate", lines_with({"model": "assistant-1", "seed": True})))
    ]
    record = ok(run_json("compare", "--study", study, "--control", ids[0], "--candidate", ids[1]))["comparison"]
    out = Path(tmp_path) / "report.html"
    ok(report(study, out))
    expected = [[entry["key"], json.dumps(entry["control"]), json.dumps(entry["candidate"]), entry["state"]] for entry in record["settings"]["keys"]]
    table = [[cell["text"] for cell in row] for row in doc_of(out).tables.get("comparison-settings-0", [])]
    assert [len(expected), *table] == [3, ["Key", "Control", "Candidate", "State"], *expected]
