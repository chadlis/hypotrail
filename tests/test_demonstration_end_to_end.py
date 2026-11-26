"""The frozen demonstration as end-to-end tests: the script's own step list, run once per session through the CLI in process.

Each test reads what `demonstration_recording` (`conftest.py`) recorded for one step and asserts what a person watching the transcript does not
see: the exit codes and refusals, each expectation, the Write sequence, the records on disk and in the reads, the report's sections.

Stated limit: that every float these tests compare goes through the script's rule (`same`, 12 significant digits) is read from
`assert_the_step` and the tests that call `same`, the only places that compare a computed float; a float compared elsewhere is not
listed mechanically (INFERRED).
"""

import csv
import json
import shlex
import shutil
from itertools import zip_longest
from pathlib import Path

from _demonstration_helpers import ROOT, journal_entries, processes, tracked_examples, value_at

# The values of the walk, from chadlis/hypotrail#218, "Facts checked at `7b8e550`".
F3_MAE = {"seasonal_7": 1090.7912087912089, "ridge_v1": 1264.730691775682}
F3_DELTA = 173.93948298447322
# After edit 6.2, the MAE of each side.
F3_MAE_62 = {"seasonal_7": 1091.3406593406594, "ridge_v1": 1265.2801423251326}

# The ten sections of a report page, in order, from chadlis/hypotrail#218, "Facts checked at `7b8e550`".
F4_SECTIONS = [
    "Question and Mode", "Data and licences", "Protocol and Partitions", "Configurations compared", "Coverage and statuses",
    "Metrics and differences", "Individual errors", "Limits", "Origin of the artifacts", "Exposure",
]

# The Write sequence of the Study each process names, after it: a command that writes moves it by two (its `begin` and `end` entries),
# a read, a refusal, a request sent again and a report that records no Exposure by none. Chinook's is the one the ticket gate measured
# at `7b8e550`, and the second Bike Study's the one chadlis/hypotrail#218 gives, "Facts checked at `7b8e550`"; a process that names
# no Study (the copy's `data verify`, the task-6 script) has none.
WRITE_SEQUENCES = {
    "L1.1": [None],
    "L1.2": [2, 2, 2],
    "L1.3": [4, 6, 6, 6],
    "L1.4": [8, 10],
    "L1.5": [12, 12],
    "L1.6": [12, 12],
    "L1.7": [14, 14, 16, 16, 18, 18],
    "A4": [None],
    "A5": [2, 4, 6, 8, 10, 12, 12, 12],
    "task 1": [12],
    "task 2": [12],
    "task 3": [14, 14, 14, 14],
    "C10": [14],
    "task 4": [14],
    "task 5": [14],
    "task 6.1": [None, None, 16, 18, 20, 20, 20, 20],
    "task 6.2": [None, None, 22, 24, 26, 26, 26, 26],
    "C5-check": [26],
    "COMPARE": [28, 28, 28, 28],
    "S1": [30, 30, 30, 30, 30],
    "C8": [32, 32],
    "DEV": [34, 34, 34, 34],
    "REPORT": [34],
    "L1.8": [2, 4, 6, 8, 8],
}

# Where each kind of record a journal entry lists under `written` lies in the Study, and the key that holds its id.
RECORDS = {
    "revision": (["study.json", "revisions/*/study.json"], "revision"),
    "attempt": (["attempts/*/attempt.json"], "attempt_id"),
    "observation_set": (["attempts/*/observation_set.json"], "observation_set_id"),
    "assessment": (["assessments/*/assessment.json"], "assessment_id"),
    "comparison": (["comparisons/*/comparison.json"], "comparison_id"),
    "freeze": (["revisions/*/freeze.json"], "freeze_id"),
    "exposure": (["exposures/*.json"], "entry_id"),
    "decision": (["decisions/*.json"], "decision_id"),
    "declared_deviation": (["declared_deviations/*.json"], "declared_deviation_id"),
}
# The kinds `status --json` itself lists, each under its key and with the key of its id there.
LISTED = {
    "revision": ("revisions", "revision"),
    "attempt": ("attempts", "attempt_id"),
    "assessment": ("assessments", "assessment_id"),
    "comparison": ("comparisons", "comparison_id"),
    "decision": ("decisions", "decision_id"),
    "declared_deviation": ("declared_deviations", "declared_deviation_id"),
}
WRITERS = {"init", "run", "import", "assess", "compare", "decide", "deviation"}


def calls_of(run, step_id) -> list:
    """(process, call) of each process of one step: the calls are the step list's processes in order (`test_..._both_ways`)."""
    return [(action, call) for (each, action), call in zip(processes(run.module.STEPS), run.calls) if each == step_id]


def ids_on_disk(study: Path, kind: str) -> set:
    patterns, key = RECORDS[kind]
    return {json.loads(path.read_text(encoding="utf-8"))[key] for pattern in patterns for path in study.glob(pattern)}


# What the line of a request sent again holds, when the command prints its line rather than its `--json` object.
REPLAYED_LINE = "(recorded earlier: nothing was"


def wrote(call) -> bool:
    if call["code"] != 0:
        return False
    if call["args"][0] == "report":
        return call["payload"]["report"]["exposure"]["recorded"]
    replayed = REPLAYED_LINE in call["out"] if call["payload"] is None else call["payload"].get("replayed", False)
    return call["args"][0] in WRITERS and not replayed


def journal_command(args) -> str:
    """The command a write-journal entry names for an argument list: `run ml`, `import agent` and `init --new-revision` in two words."""
    if args[0] in ("run", "import"):
        return " ".join(args[:2])
    return "init --new-revision" if args[0] == "init" and "--new-revision" in args else args[0]


def assert_the_step(run, step_id) -> list:
    """What every command of one step is asserted to give; the (action, call) pairs, for the assertions of that step alone."""
    pairs = calls_of(run, step_id)
    sequences = WRITE_SEQUENCES[step_id]
    values = run.module.folders_of(run.work) | run.outcome.captures
    for (action, call), sequence in zip(pairs, sequences):
        expect, payload = action["expect"], call["payload"]
        # the exit code, and a refusal's code and stage
        assert call["code"] == expect["exit"], (step_id, call["args"], call["err"])
        if "refusal" in expect:
            assert (payload["error"]["code"], payload["error"]["stage"]) == (expect["refusal"]["code"], expect["refusal"]["stage"]), step_id
        # each expectation of the step, compared by the script's rule, and each line the output is expected to hold
        for path, expected in expect.get("values", {}).items():
            found = value_at(payload, path)
            assert run.module.same(found, run.module.resolved(expected, values)), (step_id, path, found, expected)
        for line in expect.get("lines", []):
            assert run.module.resolved(line, values) in call["out"].splitlines(), (step_id, line)
        for ending in expect.get("endings", []):
            assert any(line.endswith(run.module.resolved(ending, values)) for line in call["out"].splitlines()), (step_id, ending)
        for path, named in expect.get("present", {}).items():
            for entry in named:
                assert run.module.resolved(entry, values) in value_at(payload, path), (step_id, path, entry)
        study = call["study"]
        if sequence is None:
            assert study is None, step_id
            continue
        # the Write sequence: the number of entries of the journal, and moved by two for a command that wrote, by none otherwise
        status, journal = call["status"], call["journal"]
        assert status["write_sequence"] == len(journal) == sequence, (step_id, call["args"], status["write_sequence"], len(journal))
        assert sequence - call["before"] == (2 if wrote(call) else 0), (step_id, call["args"])
        # each record the command's `end` entry lists under `written`: on disk with its id, in `writes_since`, and in the read
        written = journal[-1]["written"] if wrote(call) else []
        if wrote(call):
            assert journal[-1]["phase"] == "end" and journal[-1]["command"] == journal_command(call["args"])
            assert written, (step_id, call["args"])
        listed = [item for entry in call["since"]["writes_since"] for item in entry.get("written", [])]
        for record in written:
            assert record["id"] in ids_on_disk(study, record["kind"]), (step_id, record)
            assert record in listed, (step_id, record)
            if record["kind"] in LISTED:
                key, id_key = LISTED[record["kind"]]
                assert record["id"] in [each[id_key] for each in status[key]], (step_id, record)
        # a report page lies outside the Study and holds the ten sections, in order
        if call["args"][0] == "report":
            page = Path(call["args"][call["args"].index("--out") + 1])
            assert study.resolve() not in page.resolve().parents, page
            for at, (found, heading) in enumerate(zip_longest(call["headings"], F4_SECTIONS)):
                assert found == heading, (step_id, at)
    assert len(pairs) == len(sequences), (step_id, [call["args"] for _, call in pairs])
    return pairs


def listed_process(action, values, module) -> tuple:
    """(the program's name, or None for a command of the CLI, and its argument list) of one process of the step list."""
    if "cli" in action:
        return (None, [module.resolved(part, values) for part in action["cli"]])
    return (Path(action["program"]).name, module.resolved(action["args"], values))


def test_the_processes_the_end_to_end_tests_ran_are_the_commands_and_programs_of_the_step_list_in_order_both_ways(demonstration_recording):
    run = demonstration_recording
    values = run.module.folders_of(run.work) | run.outcome.captures
    listed = [listed_process(action, values, run.module) for _, action in processes(run.module.STEPS)]
    ran = [(call["program"], call["args"]) for call in run.calls]
    assert {name for name, _ in listed} == {None, "edit_copy.py", "hypotrail_study_hook.py"}
    for at, (found, expected) in enumerate(zip_longest(ran, listed)):
        assert found == expected, at


def test_every_step_of_the_step_list_gives_what_it_expects_and_the_script_returns_0(demonstration_recording):
    steps = demonstration_recording.module.STEPS
    assert (demonstration_recording.outcome.code, demonstration_recording.outcome.passed) == (0, len(steps)), demonstration_recording.transcript[-3000:]


def test_l1_1_the_help_and_the_two_workloads(demonstration_recording):
    [(action, call)] = assert_the_step(demonstration_recording, "L1.1")
    assert call["args"] == ["--help"] and "decide" in call["out"]


def test_l1_2_init_then_the_same_init_refused_with_study_exists(demonstration_recording):
    first, again, status = assert_the_step(demonstration_recording, "L1.2")
    assert (again[1]["code"], again[1]["payload"]["error"]["code"], again[1]["payload"]["error"]["stage"]) == (2, "STUDY_EXISTS", "study")
    assert first[1]["payload"]["references_id"] == demonstration_recording.outcome.captures["L1_BIKE_REFS"]


def test_l1_3_two_attempts_on_dev_and_the_request_sent_again_then_its_line_ending_with_the_observation_set_id_and_no_write(demonstration_recording):
    seasonal, ridge, again, line = assert_the_step(demonstration_recording, "L1.3")
    assert again[1]["payload"]["replayed"] is True
    assert again[1]["payload"]["attempt"]["attempt_id"] == seasonal[1]["payload"]["attempt"]["attempt_id"]
    assert again[1]["payload"]["observation_set_id"] == seasonal[1]["payload"]["observation_set_id"]
    [printed] = line[1]["out"].splitlines()
    assert printed.startswith(f"Attempt {seasonal[1]['payload']['attempt']['attempt_id']} ") and REPLAYED_LINE in printed, printed
    assert printed.endswith(f"; Observation set {seasonal[1]['payload']['observation_set_id']}"), printed
    assert line[1]["journal"] == again[1]["journal"] and line[1]["status"]["write_sequence"] == again[1]["status"]["write_sequence"] == 6


def test_l1_4_the_two_assessments_give_the_maes_of_the_walk(demonstration_recording):
    run = demonstration_recording
    pairs = assert_the_step(run, "L1.4")
    for (action, call), config in zip(pairs, ("seasonal_7", "ridge_v1")):
        assert run.module.same(call["payload"]["assessment"]["metrics"][0]["value"], F3_MAE[config]), config


def test_l1_5_the_comparison_gives_the_delta_of_the_walk_with_its_warning(demonstration_recording):
    run = demonstration_recording
    (_, compare), (_, status) = assert_the_step(run, "L1.5")
    assert run.module.same(compare["payload"]["comparison"]["delta"]["value"], F3_DELTA)
    assert run.module.same(status["payload"]["comparisons"][-1]["delta"]["value"], F3_DELTA)
    assert "COMPARISON_SINGLE_FEATURE_BEATS" in compare["err"]


def test_l1_6_status_and_the_report_page_with_no_exposure(demonstration_recording):
    (_, status), (_, report) = assert_the_step(demonstration_recording, "L1.6")
    assert report["payload"]["report"]["exposure"] == {"recorded": False, "entry_id": None, "journal_entries": 0}


def test_l1_7_public_check_the_freeze_record_and_the_two_exposures_on_disk(demonstration_recording):
    run = demonstration_recording
    pairs = assert_the_step(run, "L1.7")
    (_, attempt), (_, assess), (_, report) = pairs[0], pairs[2], pairs[4]
    assert attempt["payload"]["attempt"]["item_counts"]["produced"] == 184
    study = assess["study"]
    exposures = [record["id"] for call in (assess, report) for record in call["journal"][-1]["written"] if record["kind"] == "exposure"]
    [freeze] = [record["id"] for record in assess["journal"][-1]["written"] if record["kind"] == "freeze"]
    entries = sorted((study / "exposures").glob("*.json"))
    assert [json.loads(path.read_text(encoding="utf-8"))["entry_id"] for path in entries] == exposures and len(exposures) == 2
    [record] = list(study.glob("revisions/*/freeze.json"))
    assert json.loads(record.read_text(encoding="utf-8"))["freeze_id"] == freeze
    assert len(journal_entries(study)) == 18


# chadlis/hypotrail#220: "for D03 and D05, `exact_table` and `evidence_link_valid` true, `format_valid` and `contract_success` false with
# Reason `invalid_response_format`."
PER_CRITERION = {
    ("D03", "exact_table"): ("true", ""), ("D03", "format_valid"): ("false", "invalid_response_format"),
    ("D03", "evidence_link_valid"): ("true", ""), ("D03", "contract_success"): ("false", "invalid_response_format"),
    ("D05", "exact_table"): ("true", ""), ("D05", "format_valid"): ("false", "invalid_response_format"),
    ("D05", "evidence_link_valid"): ("true", ""), ("D05", "contract_success"): ("false", "invalid_response_format"),
}


def test_l1_8_chinook_the_scenario_attempt_the_import_its_assessment_and_the_per_criterion_file(demonstration_recording):
    pairs = assert_the_step(demonstration_recording, "L1.8")
    (_, fixture), (_, imported), (_, assess) = pairs[1], pairs[2], pairs[3]
    assert fixture["payload"]["attempt"]["item_counts"] == {"produced": 5, "failed": 1, "missing": 1}
    assert (imported["payload"]["attempt"]["mode"], imported["payload"]["attempt"]["item_counts"]["produced"]) == ("external_unknown", 2)
    assessment = assess["payload"]["assessment"]
    assert (assessment["primary_criterion"], assessment["counts"]["correct"], assessment["counts"]["expected"]) == ("contract_success", 0, 2)
    with (assess["study"] / assessment["per_item_ref"]["path"]).open(newline="", encoding="utf-8") as handle:
        rows = {(row["case_id"], row["criterion"]): (row["score"], row["reason"]) for row in csv.DictReader(handle)}
    for key in sorted(set(rows) | set(PER_CRITERION)):
        assert rows.get(key) == PER_CRITERION.get(key), key


# --- the second Bike Study, on the Workload copy -----------------------------------------------------------------------------------------


def captured(run, name):
    return run.outcome.captures[name]


def kept_call(run, name):
    """The call that wrote the kept file NAME into the work folder."""
    [(_, call)] = [(action, call) for (_, action), call in zip(processes(run.module.STEPS), run.calls) if action.get("kept") == name]
    return call


def test_a4_the_workload_copy_is_in_the_work_folder_and_data_verify_verifies_it(demonstration_recording):
    run = demonstration_recording
    [(_, verify)] = assert_the_step(run, "A4")
    copy = run.work / "demo-examples"
    assert copy.resolve() not in ROOT.resolve().parents and ROOT.resolve() not in copy.resolve().parents
    assert verify["args"] == ["data", "verify", "--examples-dir", str(copy), "--json"]
    assert [entry["status"] for entry in verify["payload"]["datasets"]] == ["verified", "verified"]


def test_a5_the_second_bike_study_its_two_assessments_give_the_maes_and_its_comparison_the_delta_of_the_walk(demonstration_recording):
    run = demonstration_recording
    pairs = assert_the_step(run, "A5")
    for (_, call), config in zip(pairs[3:5], ("seasonal_7", "ridge_v1")):
        assert run.module.same(call["payload"]["assessment"]["metrics"][0]["value"], F3_MAE[config]), config
    assert run.module.same(pairs[5][1]["payload"]["comparison"]["delta"]["value"], F3_DELTA)
    assert pairs[0][1]["payload"]["references_id"] == captured(run, "L1_BIKE_REFS")


def test_task_1_one_pending_decision_on_the_comparison_of_a5_with_its_question_and_three_options_each_with_a_consequence(demonstration_recording):
    run = demonstration_recording
    [(_, status)] = assert_the_step(run, "task 1")
    [pending] = status["payload"]["pending_decisions"]
    assert pending["comparison_id"] == captured(run, "L2_COMPARISON")
    assert pending["question"]["text"] == run.module.QUESTION
    assert [option["text"] for option in pending["options"]] == ["Keep the Control", "Keep the Candidate", "Choose neither yet"]
    for option in pending["options"]:
        assert isinstance(option["consequence"], str) and option["consequence"].strip(), option["text"]


def test_task_2_the_delta_and_the_two_metrics_in_status_and_one_figures_entry_for_that_comparison(demonstration_recording):
    run = demonstration_recording
    [(_, status)] = assert_the_step(run, "task 2")
    [comparison] = [each for each in status["payload"]["comparisons"] if each["comparison_id"] == captured(run, "L2_COMPARISON")]
    assert run.module.same(comparison["delta"]["value"], F3_DELTA)
    metrics = {each["assessment_id"]: each["metrics"][0]["value"] for each in status["payload"]["assessments"]}
    assert run.module.same(metrics[comparison["roles"]["control_assessment_id"]], F3_MAE["seasonal_7"])
    assert run.module.same(metrics[comparison["roles"]["candidate_assessment_id"]], F3_MAE["ridge_v1"])
    figures = kept_call(run, "after-compare.figures")["payload"]
    assert figures["write_sequence"] == status["payload"]["write_sequence"] == 12
    assert [entry["comparison_id"] for entry in figures["comparisons"]].count(comparison["comparison_id"]) == 1


def the_decision_of_task_3(run, status) -> dict:
    assert status["payload"]["pending_decisions"] == []
    [decision] = status["payload"]["decisions"]
    assert (decision["decision_id"], decision["author"], decision["cited_ids"]) == (captured(run, "L2_DECISION"), "human", [captured(run, "L2_COMPARISON")])
    assert (decision["applies"], decision["reasons"]) == (True, [])
    return decision


def test_task_3_and_task_4_no_pending_decision_one_human_decision_citing_the_comparison_that_applies_with_no_reason_read_again_the_same(demonstration_recording):
    run = demonstration_recording
    decide, status, _, _ = assert_the_step(run, "task 3")
    [(_, again)] = assert_the_step(run, "task 4")
    assert decide[1]["payload"]["decision"]["decision_id"] == captured(run, "L2_DECISION")
    assert the_decision_of_task_3(run, status[1]) == the_decision_of_task_3(run, again)


FRAGMENT = ROOT / "clients" / "claude-code" / "settings-fragment.json"


def test_c10_the_hooks_text_names_the_write_sequence_no_pending_decision_and_the_decision_of_task_3_with_its_option_and_its_id(demonstration_recording):
    missing = [name for name in ("uv", "python3") if shutil.which(name) is None]
    assert missing == [], f"C10 starts the hook with python3 and the hook starts the CLI through uv: not on PATH: {missing}"
    run = demonstration_recording
    [(action, hook)] = assert_the_step(run, "C10")
    [entry] = json.loads(FRAGMENT.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"]
    words = shlex.split(entry["hooks"][0]["command"])
    assert [*action["interpreter"], "$CLAUDE_PROJECT_DIR/" + action["program"], action["args"][0]] == words[:4]
    assert (hook["program"], hook["args"]) == (Path(action["program"]).name, ["--study", str(run.work / "bike")])
    assert json.loads(hook["input"])["hook_event_name"] == "UserPromptSubmit"
    lines = hook["out"].splitlines()
    assert "Write sequence: 14" in lines and "Pending decisions: 0" in lines
    [decision] = [line for line in lines if line.startswith("- Decision ")]
    assert decision.startswith(f"- Decision {captured(run, 'L2_DECISION')}: ") and '; option "Keep the Control";' in decision


def test_task_5_the_warning_of_the_comparison_and_its_limitations_in_status(demonstration_recording):
    run = demonstration_recording
    [(_, status)] = assert_the_step(run, "task 5")
    comparison = status["payload"]["comparisons"][0]
    assert comparison["comparison_id"] == captured(run, "L2_COMPARISON")
    assert "COMPARISON_SINGLE_FEATURE_BEATS" in [warning["code"] for warning in comparison["warnings"]]
    for limitation in run.module.LIMITATIONS:
        assert limitation in comparison["limitations"], limitation


def the_rescored_decision(run, step_id, changed, state, latest):
    """The assertions of task 6.1 and task 6.2: each new Assessment rescored for its References with `changed` changed Items, and the
    Decision of task 3 outdated, its evidence in `state`, each side's cited Metric that of A5 and its latest `latest`."""
    pairs = assert_the_step(run, step_id)
    for (_, assess), config in zip(pairs[3:5], ("seasonal_7", "ridge_v1")):
        rescoring = assess["payload"]["assessment"]["rescoring"]
        assert (rescoring["cause"], len(rescoring["changed_items"])) == ("references_version", changed), (step_id, config)
    [decision] = pairs[5][1]["payload"]["decisions"]
    reasons = [reason["reason"] for reason in decision["reasons"]]
    assert decision["applies"] is False and "revision_changed" in reasons and reasons.count("compared_assessment_superseded") == 2, reasons
    assert decision["evidence_change"]["state"] == state
    for line, config in zip(decision["evidence_change"]["lines"], ("seasonal_7", "ridge_v1")):
        [metric] = line["metrics"]
        assert run.module.same(metric["cited"], F3_MAE[config]) and run.module.same(metric["latest"], latest[config]), (step_id, config)
    assert len(decision["evidence_change"]["lines"]) == 2


def test_task_6_1_each_new_assessment_changes_no_item_and_the_decision_is_outdated_with_evidence_rescored(demonstration_recording):
    the_rescored_decision(demonstration_recording, "task 6.1", 0, "evidence_rescored", F3_MAE)


def test_task_6_2_each_new_assessment_changes_one_item_and_the_decision_is_outdated_with_result_changed(demonstration_recording):
    the_rescored_decision(demonstration_recording, "task 6.2", 1, "result_changed", F3_MAE_62)


def transcript_block(run, step_id) -> list:
    lines = run.transcript.splitlines()
    start = lines.index(next(line for line in lines if line.startswith(f"== {step_id} · ")))
    end = next((at for at in range(start + 1, len(lines)) if lines[at].startswith("== ")), len(lines))
    return lines[start:end]


# The four kinds of value C5-check prints, each by the key path the script prints it at.
C5_KINDS = {
    "study id": ["study.study_id"],
    "Write sequence": ["write_sequence"],
    "pending ids": ["pending_decisions[*].comparison_id"],
    "Decisions with applies": ["decisions[*].decision_id", "decisions[*].applies"],
}


def test_c5_check_the_values_the_transcript_prints_are_those_of_the_status_read_kept_at_write_sequence_26(demonstration_recording):
    run = demonstration_recording
    [(action, _)] = assert_the_step(run, "C5-check")
    read = json.loads((run.work / "kept" / "after-6.2.status.out").read_text(encoding="utf-8"))
    assert read["write_sequence"] == 26
    printed = dict(line[2:].split(" = ", 1) for line in transcript_block(run, "C5-check") if line.startswith("  ") and " = " in line)
    assert sorted(path for paths in C5_KINDS.values() for path in paths) == sorted(action["print"])
    for kind, paths in C5_KINDS.items():
        assert [json.loads(printed[path]) for path in paths] == [value_at(read, path) for path in paths], kind


def test_compare_one_pending_decision_on_the_new_comparison_its_delta_that_of_a5_and_the_transcript_says_what_result_changed_names(demonstration_recording):
    run = demonstration_recording
    (_, compare), (_, status), _, _ = assert_the_step(run, "COMPARE")
    [(_, a5)] = [pair for pair in calls_of(run, "A5") if pair[1]["args"][0] == "compare"]
    assert [entry["comparison_id"] for entry in status["payload"]["pending_decisions"]] == [captured(run, "L2_COMPARISON_62")]
    assert run.module.same(compare["payload"]["comparison"]["delta"]["value"], a5["payload"]["comparison"]["delta"]["value"])
    assert "\"result changed\" at 6.2 names a changed Item, not a changed delta" in " ".join(transcript_block(run, "COMPARE"))


def test_s1_the_decide_on_the_older_write_sequence_is_refused_with_study_changed_naming_the_run_ml_and_nothing_is_written(demonstration_recording):
    run = demonstration_recording
    (_, attempt), _, (_, refused), _, _ = assert_the_step(run, "S1")
    error = refused["payload"]["error"]
    assert (refused["code"], error["code"], error["stage"]) == (6, "STUDY_CHANGED", "sequence")
    assert (error["details"]["read_sequence"], error["details"]["write_sequence"]) == (28, 30)
    entries = [(entry["command"], entry["phase"], entry["request_id"]) for entry in error["details"]["writes_since"]]
    assert entries == [("run ml", "begin", "demo-s1"), ("run ml", "end", "demo-s1")]
    assert error["details"]["writes_since"][1]["written"] == attempt["journal"][-1]["written"]
    assert refused["status"]["write_sequence"] == 30 and len(refused["status"]["decisions"]) == 1
    assert [entry["comparison_id"] for entry in refused["status"]["pending_decisions"]] == [captured(run, "L2_COMPARISON_62")]


def test_c8_a_second_decision_by_proxy_with_its_source_that_applies_and_no_pending_decision(demonstration_recording):
    run = demonstration_recording
    _, (_, status) = assert_the_step(run, "C8")
    first, second = status["payload"]["decisions"]
    assert first["decision_id"] == captured(run, "L2_DECISION")
    assert (second["author"], second["source"], second["applies"]) == ("proxy", run.module.PROXY_SOURCE, True)
    assert second["cited_ids"] == [captured(run, "L2_COMPARISON_62")]
    assert status["payload"]["pending_decisions"] == []


def test_dev_one_declared_deviation_not_withdrawn_by_human_citing_the_references_id_of_revision_3(demonstration_recording):
    run = demonstration_recording
    (_, declared), (_, status), _, _ = assert_the_step(run, "DEV")
    [deviation] = status["payload"]["declared_deviations"]
    [references] = [a["artifact_id"] for a in status["payload"]["revisions"][2]["artifacts"] if a["role"] == "references"]
    assert status["payload"]["revisions"][2]["revision_number"] == 3
    assert (deviation["withdrawn"], deviation["cited_ids"]) == (False, [references])
    assert declared["payload"]["declared_deviation"]["author"] == "human"
    assert deviation["declared_deviation_id"] == declared["payload"]["declared_deviation"]["declared_deviation_id"]


def test_report_the_page_of_the_second_bike_study_holds_the_ten_sections_and_records_no_exposure(demonstration_recording):
    [(_, report)] = assert_the_step(demonstration_recording, "REPORT")
    assert report["payload"]["report"]["exposure"] == {"recorded": False, "entry_id": None, "journal_entries": 0}


# --- a Decision is never rewritten, no Reference of the repository changes, and the reads kept for the client ------------------------


def test_the_file_of_the_decision_of_task_3_keeps_its_bytes_after_task_6_1_after_task_6_2_and_after_dev(demonstration_recording):
    run = demonstration_recording
    [file] = calls_of(run, "task 3")[0][1]["decision_files"]
    recorded = calls_of(run, "task 3")[-1][1]["decision_files"][file]
    for step_id in ("task 6.1", "task 6.2", "DEV"):
        assert calls_of(run, step_id)[-1][1]["decision_files"][file] == recorded, step_id


# The two edits of task 6, each with its day and the values of `registered` and `cnt` after it (docs/demo/edit_copy.py).
EDITED_DAYS = {"6.1": ("2012-12-31", "2390", "2829"), "6.2": ("2012-03-15", "5287", "6292")}


def test_no_tracked_file_under_examples_changed_and_both_edits_are_in_the_copys_data(demonstration_recording):
    run = demonstration_recording
    before, after = run.examples_before, run.examples_after
    assert before and after == tracked_examples()
    for path in sorted(set(before) | set(after)):
        assert before.get(path) == after.get(path), path
    with (run.work / "demo-examples" / "bike_day" / "data" / "day.csv").open(newline="", encoding="utf-8") as handle:
        rows = {row["dteday"]: (row["registered"], row["cnt"]) for row in csv.DictReader(handle)}
    for edit, (day, registered, count) in EDITED_DAYS.items():
        assert rows[day] == (registered, count), edit


# The kept states of the second Bike Study, each with its Write sequence, from chadlis/hypotrail#221, "Words of this ticket".
KEPT_STATES = {
    "after-compare": 12,
    "after-decide": 14,
    "after-6.1": 20,
    "after-6.2": 26,
    "before-the-refused-write": 28,
    "after-the-terminal-wrote": 30,
    "final": 34,
}
KEPT_DECIDES = ["decide-task-3", "decide-s1"]


def test_the_work_folder_holds_the_two_reads_of_each_kept_state_at_its_write_sequence_and_the_two_kept_decide_calls(demonstration_recording):
    run = demonstration_recording
    folder = run.work / "kept"
    written = {path.name.rsplit(".", 1)[0] for path in folder.iterdir()}
    expected = {f"{state}.{read}" for state in KEPT_STATES for read in ("status", "figures")} | set(KEPT_DECIDES)
    for name in sorted(written | expected):
        assert name in written and name in expected, name
    for state, sequence in KEPT_STATES.items():
        status, figures = (json.loads((folder / f"{state}.{read}.out").read_text(encoding="utf-8")) for read in ("status", "figures"))
        assert status["write_sequence"] == figures["write_sequence"] == sequence, state
        assert (folder / f"{state}.status.out").read_text(encoding="utf-8") == kept_call(run, f"{state}.status")["out"], state
    for name in KEPT_DECIDES:
        call = kept_call(run, name)
        assert json.loads((folder / f"{name}.args").read_text(encoding="utf-8")) == {"arguments": call["args"]}, name
        printed = tuple((folder / f"{name}.{part}").read_text(encoding="utf-8") for part in ("exit", "out", "err"))
        assert printed == (f"{call['code']}\n", call["out"], call["err"]), name


# --- what the Why of a step says, read against what its commands gave --------------------------------------------------------------

# The lag feature task 3 and C8 name, as the warning of the Comparison prints it.
MEAN_PREVIOUS_7 = "mean_previous_7 (823.878 rentals per day)"


def test_the_figures_the_why_of_task_3_and_of_c8_names_are_the_warnings_and_the_two_maes_and_the_lag_feature_beats_both(demonstration_recording):
    run = demonstration_recording
    _, (_, status), _, _ = assert_the_step(run, "task 3")
    [warning] = status["payload"]["comparisons"][0]["warnings"]
    assert MEAN_PREVIOUS_7 in warning["message"], warning["message"]
    why = run.module.STEPS[[each["id"] for each in run.module.STEPS].index("task 3")]["why"]
    assert MEAN_PREVIOUS_7 in why and f"({F3_MAE['seasonal_7']:.6g} and {F3_MAE['ridge_v1']:.6g})" in why, why
    assert 823.878 < min(F3_MAE.values())


def test_after_task_6_1_nothing_is_pending_because_the_comparison_of_task_3_compares_assessments_of_revision_1(demonstration_recording):
    run = demonstration_recording
    status = assert_the_step(run, "task 6.1")[5][1]["payload"]
    [comparison] = [each for each in status["comparisons"] if each["comparison_id"] == captured(run, "L2_COMPARISON")]
    revisions = {each["assessment_id"]: each["study_revision"]["number"] for each in status["assessments"]}
    assert status["pending_decisions"] == [] and status["revisions"][-1]["revision_number"] == 2
    assert [revisions[comparison["roles"][side]] for side in ("control_assessment_id", "candidate_assessment_id")] == [1, 1]
    assert [each["comparison_id"] for each in status["comparisons"]] == [captured(run, "L2_COMPARISON")]
