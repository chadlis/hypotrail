"""The frozen demonstration as end-to-end tests: the script's own step list, run once per session through the CLI in process.

Each test reads the run of `demonstration_run` (`conftest.py`) for one step and asserts what a person watching the transcript does not
see: the exit codes and refusals, each expectation, the Write sequence, the records on disk and in the reads, the report's sections.

Stated limit: that every float these tests compare goes through the script's rule (`same`, 12 significant digits) is read from
`assert_the_step` and the tests of L1.4 and L1.5, the only places that compare a computed float; a float compared elsewhere is not
listed mechanically (INFERRED).
"""

import csv
import json
from itertools import zip_longest
from pathlib import Path

from _demonstration_helpers import commands, journal_entries, value_at

# The values of the walk, from chadlis/hypotrail#218, "Facts checked at `7b8e550`".
F3_MAE = {"seasonal_7": 1090.7912087912089, "ridge_v1": 1264.730691775682}
F3_DELTA = 173.93948298447322

# The ten sections of a report page, in order, from chadlis/hypotrail#218, "Facts checked at `7b8e550`".
F4_SECTIONS = [
    "Question and Mode", "Data and licences", "Protocol and Partitions", "Configurations compared", "Coverage and statuses",
    "Metrics and differences", "Individual errors", "Limits", "Origin of the artifacts", "Exposure",
]

# The Write sequence of the Study each command names, after it: a command that writes moves it by two (its `begin` and `end` entries),
# a read, a refusal, a request sent again and a report that records no Exposure by none. Chinook's is the one the ticket gate measured
# at `7b8e550`; a step with no Study has none.
WRITE_SEQUENCES = {
    "L1.1": [None],
    "L1.2": [2, 2, 2],
    "L1.3": [4, 6, 6],
    "L1.4": [8, 10],
    "L1.5": [12, 12],
    "L1.6": [12, 12],
    "L1.7": [14, 14, 16, 16, 18, 18],
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
    """(action, call) of each command of one step: the calls are the step list's commands in order (`test_..._both_ways`)."""
    return [(action, call) for (each, action), call in zip(commands(run.module.STEPS), run.calls) if each == step_id]


def ids_on_disk(study: Path, kind: str) -> set:
    patterns, key = RECORDS[kind]
    return {json.loads(path.read_text(encoding="utf-8"))[key] for pattern in patterns for path in study.glob(pattern)}


def wrote(call) -> bool:
    if call["code"] != 0:
        return False
    if call["args"][0] == "report":
        return call["payload"]["report"]["exposure"]["recorded"]
    return call["args"][0] in WRITERS and not (call["payload"] or {}).get("replayed", False)


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
        # each expectation of the step, compared by the script's rule
        for path, expected in expect.get("values", {}).items():
            found = value_at(payload, path)
            assert run.module.same(found, run.module.resolved(expected, values)), (step_id, path, found, expected)
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
            assert journal[-1]["phase"] == "end" and journal[-1]["command"] == " ".join(call["args"][: 2 if call["args"][0] in ("run", "import") else 1])
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


def test_the_commands_the_end_to_end_tests_ran_are_the_commands_of_the_step_list_in_order_both_ways(demonstration_run):
    run = demonstration_run
    values = run.module.folders_of(run.work) | run.outcome.captures
    listed = [[run.module.resolved(part, values) for part in action["cli"]] for _, action in commands(run.module.STEPS)]
    ran = [call["args"] for call in run.calls]
    for at, (found, expected) in enumerate(zip_longest(ran, listed)):
        assert found == expected, at


def test_the_whole_run_of_the_step_list_exits_0_with_every_step_giving_what_it_expects(demonstration_run):
    steps = demonstration_run.module.STEPS
    assert (demonstration_run.outcome.code, demonstration_run.outcome.passed) == (0, len(steps)), demonstration_run.transcript[-3000:]


def test_l1_1_the_help_and_the_two_workloads(demonstration_run):
    [(action, call)] = assert_the_step(demonstration_run, "L1.1")
    assert call["args"] == ["--help"] and "decide" in call["out"]


def test_l1_2_init_then_the_same_init_refused_with_study_exists(demonstration_run):
    first, again, status = assert_the_step(demonstration_run, "L1.2")
    assert (again[1]["code"], again[1]["payload"]["error"]["code"], again[1]["payload"]["error"]["stage"]) == (2, "STUDY_EXISTS", "study")
    assert first[1]["payload"]["references_id"] == demonstration_run.outcome.captures["L1_BIKE_REFS"]


def test_l1_3_two_attempts_on_dev_and_the_request_sent_again(demonstration_run):
    seasonal, ridge, again = assert_the_step(demonstration_run, "L1.3")
    assert again[1]["payload"]["replayed"] is True
    assert again[1]["payload"]["attempt"]["attempt_id"] == seasonal[1]["payload"]["attempt"]["attempt_id"]
    assert again[1]["payload"]["observation_set_id"] == seasonal[1]["payload"]["observation_set_id"]


def test_l1_4_the_two_assessments_give_the_maes_of_the_walk(demonstration_run):
    run = demonstration_run
    pairs = assert_the_step(run, "L1.4")
    for (action, call), config in zip(pairs, ("seasonal_7", "ridge_v1")):
        assert run.module.same(call["payload"]["assessment"]["metrics"][0]["value"], F3_MAE[config]), config


def test_l1_5_the_comparison_gives_the_delta_of_the_walk_with_its_warning(demonstration_run):
    run = demonstration_run
    (_, compare), (_, status) = assert_the_step(run, "L1.5")
    assert run.module.same(compare["payload"]["comparison"]["delta"]["value"], F3_DELTA)
    assert run.module.same(status["payload"]["comparisons"][-1]["delta"]["value"], F3_DELTA)
    assert "COMPARISON_SINGLE_FEATURE_BEATS" in compare["err"]


def test_l1_6_status_and_the_report_page_with_no_exposure(demonstration_run):
    (_, status), (_, report) = assert_the_step(demonstration_run, "L1.6")
    assert report["payload"]["report"]["exposure"] == {"recorded": False, "entry_id": None, "journal_entries": 0}


def test_l1_7_public_check_the_freeze_record_and_the_two_exposures_on_disk(demonstration_run):
    run = demonstration_run
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


def test_l1_8_chinook_the_scenario_attempt_the_import_its_assessment_and_the_per_criterion_file(demonstration_run):
    pairs = assert_the_step(demonstration_run, "L1.8")
    (_, fixture), (_, imported), (_, assess) = pairs[1], pairs[2], pairs[3]
    assert fixture["payload"]["attempt"]["item_counts"] == {"produced": 5, "failed": 1, "missing": 1}
    assert (imported["payload"]["attempt"]["mode"], imported["payload"]["attempt"]["item_counts"]["produced"]) == ("external_unknown", 2)
    assessment = assess["payload"]["assessment"]
    assert (assessment["primary_criterion"], assessment["counts"]["correct"], assessment["counts"]["expected"]) == ("contract_success", 0, 2)
    with (assess["study"] / assessment["per_item_ref"]["path"]).open(newline="", encoding="utf-8") as handle:
        rows = {(row["case_id"], row["criterion"]): (row["score"], row["reason"]) for row in csv.DictReader(handle)}
    for key in sorted(set(rows) | set(PER_CRITERION)):
        assert rows.get(key) == PER_CRITERION.get(key), key
