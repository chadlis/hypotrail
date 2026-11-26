"""Run the frozen demonstration of Hypotrail in a work folder outside the checkout, and check each step.

Standard library only; it imports nothing of Hypotrail and is not a command of the CLI. Run it with the Python of the
checkout:

    uv run python docs/demo/demonstration.py --work DIR

DIR is a new or empty folder outside the checkout: it receives the Studies, the Workload copy, the report pages, the population
file and the reads kept for the client's tests (`kept/`). The steps are those of section 18 of the teaching page,
`pages/de-zero-a-la-demo.html` in chadlis/hypotrail-learning (in French; read at commit `164aa3a`), that need no person: a first
Bike Study, a second Bike Study on a copy of the Workloads, then Chinook. For each step the script prints what
it shows and why, starts each command as a process of its own, as a person would, prints what the command gave, and checks what
the step expects of it. It stops at the first expectation that does not hold. Exit 0 when every step gave what it expects, 1
when one did not, 2 when DIR is refused.

No command calls a live model or the network: `run agent` is given the Mode `scripted_fixture` only, and each process is
started without the live key `HYPOTRAIL_ANTHROPIC_API_KEY` in its environment. A command of the CLI is started as
`python -B -m hypotrail`, with the Python that runs this script, and the task-6 script as `python -B`; `-B` keeps Python from
writing its bytecode cache into the checkout, so that the script writes only inside DIR. The Claude Code hook is started as
its settings fragment starts it, `python3 -I`, and starts the CLI through `uv` itself: it gets `PYTHONDONTWRITEBYTECODE=1`.

The transcript writes each process on a `$` line as a person types it at the root of the checkout: a command of the CLI as
`uv run python -m hypotrail`, the task-6 script as `uv run python`, the hook with its fragment's `python3 -I`, and the work folder
and the checkout as `$WORK` and `$CHECKOUT`, whose values its first line states. An action that starts no process is a `script:`
line.
"""

import argparse
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parents[2]
CLI = [sys.executable, "-B", "-m", "hypotrail"]
LIVE_KEY = "HYPOTRAIL_ANTHROPIC_API_KEY"
# The Inspect log of the paid `run agent` Attempt of 2026-11-20, kept in the repository: L1.8 imports it, read in place.
KEPT_LOG = "docs/handbook/traces/run-agent-live-plain/inspect/2026-11-20T21-46-56-00-00_chinook-plain_e5SoHDfMBV3vBUjsjaQWVu.eval"
POPULATION = '{"episodes": [{"case_id": "D03", "repeat": 0}, {"case_id": "D05", "repeat": 0}]}'
SIGNIFICANT_DIGITS = 12
# A `$` line of the transcript: how a person starts a command of the CLI and the task-6 script, and the name of each folder.
TYPED_CLI = ["uv", "run", "python", "-m", "hypotrail"]
TYPED_PYTHON = ["uv", "run", "python"]
FOLDER_NAMES = {"work": "$WORK", "checkout": "$CHECKOUT"}
# A template names a folder as `{work}` or `{checkout}`, and a value captured from an earlier command by the capture's name.
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
FOLDERS = ("work", "checkout")
# A key path names keys and list indexes; `[*]` takes the rest of the path in each entry of a list.
PATH_PART = re.compile(r"\.?([A-Za-z_][A-Za-z0-9_]*)|\[(-?\d+|\*)\]")

BIKE = "{work}/l1-bike"
CHINOOK = "{work}/l1-chinook"
COUNTS_182 = {"produced": 182, "failed": 0, "missing": 0}

# The second Bike Study, made from the Workload copy: the copy is given as --examples-dir to the commands that read the Workload.
L2_BIKE = "{work}/bike"
COPY = "{work}/demo-examples"
# Where the reads of each kept state, and the two kept decide calls, are written: NAME.exit, NAME.out and NAME.err, and for a
# decide NAME.args, its argument list.
KEPT = "kept"
QUESTION = "Which Configuration do we keep after this Comparison?"
PROXY_SOURCE = "rule: keep the Configuration with the lowest MAE"
# The person's words of the step WORDS, as a file of the work folder: an apostrophe, an accented name, a narrow no-break space, a
# double quote and the two French quotation marks around a French phrase, which a shell or a re-encoding damages. The marks are
# written as escapes, as every file under `tests/` writes them.
WORDS_TEXT = 'Zo\u00eb\'s call\u202f: keep the Control, she wrote \u00ab on garde le t\u00e9moin \u00bb and "the lag feature can wait".'
WORDS_BY = "the owner, in chat"
DEVIATION_TEXT = (
    "The References of revisions 2 and 3 were edited by the demonstration's script, docs/demo/edit_copy.py, in a copy of the "
    "Workload, to show a Decision outdated by its evidence; they correct no error of the data."
)
# The task-6 script, started with the Python that runs this script; the hook, started with the interpreter and flags of
# clients/claude-code/settings-fragment.json.
EDIT_COPY = "docs/demo/edit_copy.py"
HOOK = "clients/claude-code/hypotrail_study_hook.py"
HOOK_INTERPRETER = ["python3", "-I"]
# What Claude Code writes on the hook's stdin at a prompt; the hook reads it whole and uses none of it.
HOOK_INPUT = json.dumps(
    {"session_id": "demonstration", "hook_event_name": "UserPromptSubmit", "prompt": "Which Decision did the Study record last?", "cwd": "{checkout}"}
)
LIMITATIONS = [
    "Daily observations are dependent: the delta carries no confidence interval and no significance claim.",
    "The two Attempts record the same code environment; this does not establish that the two executions were identical.",
]


def keep(state: str, sequence: int) -> dict:
    """The action that writes the two reads of a kept state of the second Bike Study: `status --json` and `figures --json`."""
    return {"keep": state, "study": L2_BIKE, "sequence": sequence}


def decide(option: str, artifact: str, request_id: str, read_sequence, author: str = "human", source: str | None = None) -> list:
    """A decide as the panel's bridge starts it: each option joined to its value by `=`, in the order of `decide_options`."""
    return [
        "decide", f"--study={L2_BIKE}", f"--question={QUESTION}", f"--option={option}", f"--author={author}",
        *([] if source is None else [f"--source={source}"]),
        f"--artifact={artifact}", f"--request-id={request_id}", f"--read-sequence={read_sequence}", "--json",
    ]


def status_l2() -> list:
    return ["status", "--study", L2_BIKE, "--json"]

# The step list. Each step has its id in section 18, its title, what it shows and why, and its actions. An action is a command
# of the CLI (`cli`, its argument list), a file of the work folder written (`write`), or files shown, read only (`show`). A
# command may capture values of its `--json` object for the commands after it (`capture`: name -> key path), print values of
# it (`print`), and expects its exit code, a refusal's code and stage, the values at named key paths, the entries a list at a
# key path holds among others (`present`), and the lines or the ends of lines its output holds (`expect`).
STEPS = [
    {
        "id": "L1.1",
        "title": "See the CLI's commands and the two Workloads",
        "shows": "The commands of the CLI, then the folders of the two Workloads, bike_day and chinook, and what each holds.",
        "why": (
            "A Workload is a question asked on data, with no line of code: bike_day asks for the number of bikes rented each day, "
            "forecast at the start of that day, on the data of 2011 and 2012; chinook asks an agent to answer an analyst's questions "
            "in SQL on the sample database of a music shop. Each is one folder: workload.json asks the question, data/ holds the data, "
            "and data-sources.lock.json fixes the digest of each file."
        ),
        "actions": [
            {"cli": ["--help"], "expect": {"exit": 0}},
            {"show": "folders", "paths": ["{checkout}/examples", "{checkout}/examples/bike_day", "{checkout}/examples/chinook"]},
        ],
    },
    {
        "id": "L1.2",
        "title": "Create a Study and see its frozen Protocol",
        "shows": (
            "The Study created, with the digest of its Protocol and the References ID; the same init a second time, refused with "
            "STUDY_EXISTS and exit 2; then revision 1 read back, with its whole Protocol digest and the two artifacts copied into "
            "the Study, the memberships and the References, each with its digest."
        ),
        "why": (
            "A Study is the folder where Hypotrail keeps everything a study uses. init freezes its Protocol: the days, their roles, "
            "the expected values and the rules of scoring, summed up by one SHA-256 digest, protocol_digest. The References, the "
            "expected values (the true number of rentals of each day), are copied in and cited by their digest. The second init is "
            "refused and writes nothing: a Study is never created again over itself, and a change goes through a new revision."
        ),
        "actions": [
            {
                "cli": ["init", "--workload", "bike_day", "--study", BIKE, "--json"],
                "capture": {"L1_BIKE_REFS": "references_id"},
                "print": ["study.study_id", "study.protocol_digest", "references_id"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "study.revision_number": 1,
                        "study.protocol_digest": "d4a1c2cbeb43025f6d3de1be6cc4375b83b0307d928cbb7fadf26f58fd78a6f0",
                        "references_id": "references-7520d791bfe31924",
                    },
                },
            },
            {
                "cli": ["init", "--workload", "bike_day", "--study", BIKE, "--json"],
                "print": ["error.code", "error.message"],
                "expect": {"exit": 2, "refusal": {"code": "STUDY_EXISTS", "stage": "study"}},
            },
            {
                "cli": ["status", "--study", BIKE, "--json"],
                "print": [
                    "revisions[-1].revision_number",
                    "revisions[-1].protocol_digest",
                    "revisions[-1].artifacts[0].artifact_id",
                    "revisions[-1].artifacts[0].sha256",
                    "revisions[-1].artifacts[1].artifact_id",
                    "revisions[-1].artifacts[1].sha256",
                ],
                "expect": {
                    "exit": 0,
                    "values": {
                        "len(revisions)": 1,
                        "revisions[-1].artifacts[0].role": "memberships",
                        "revisions[-1].artifacts[1].role": "references",
                        "revisions[-1].artifacts[1].artifact_id": "{L1_BIKE_REFS}",
                        "write_sequence": 2,
                    },
                },
            },
        ],
    },
    {
        "id": "L1.3",
        "title": "Run two Configurations on dev, then send the first request again",
        "shows": (
            "Two Attempts on the 182 Items of dev, each with 182 produced, 0 failed and 0 missing, and the Observation set ID each "
            "recorded; then the first request sent again, which gives the first Attempt's id and Observation set ID with replayed true; "
            "then the same request a third time without --json, whose line ends with that Observation set ID and which writes nothing."
        ),
        "why": (
            "A Configuration is the whole forecasting recipe: seasonal_7 takes the value of seven days before; ridge_v1 is a ridge "
            "regression on past values and the calendar. run ml records it as an Attempt on one Partition, here dev: the 182 days "
            "from 2012-01-01 to 2012-06-30, kept to measure and compare. Each day is an Item, and the Attempt's Observation set "
            "keeps one forecast per Item. A request sent again with the same --request-id returns the Attempt already recorded and "
            "computes nothing again, so a command that may not have finished can be started again safely."
        ),
        "actions": [
            {
                "cli": ["run", "ml", "--study", BIKE, "--config", "seasonal_7", "--partition", "dev", "--request-id", "l1-seasonal", "--json"],
                "capture": {"L1_ATTEMPT_SEASONAL": "attempt.attempt_id", "L1_OBS_SEASONAL": "observation_set_id"},
                "print": ["attempt.attempt_id", "attempt.technical_status", "attempt.item_counts", "observation_set_id", "replayed"],
                "expect": {"exit": 0, "values": {"replayed": False, "attempt.technical_status": "completed", "attempt.item_counts": COUNTS_182}},
            },
            {
                "cli": ["run", "ml", "--study", BIKE, "--config", "ridge_v1", "--partition", "dev", "--request-id", "l1-ridge", "--json"],
                "capture": {"L1_OBS_RIDGE": "observation_set_id"},
                "print": ["attempt.attempt_id", "attempt.technical_status", "attempt.item_counts", "observation_set_id", "replayed"],
                "expect": {"exit": 0, "values": {"replayed": False, "attempt.technical_status": "completed", "attempt.item_counts": COUNTS_182}},
            },
            {
                "cli": ["run", "ml", "--study", BIKE, "--config", "seasonal_7", "--partition", "dev", "--request-id", "l1-seasonal", "--json"],
                "print": ["attempt.attempt_id", "observation_set_id", "replayed"],
                "expect": {
                    "exit": 0,
                    "values": {"replayed": True, "attempt.attempt_id": "{L1_ATTEMPT_SEASONAL}", "observation_set_id": "{L1_OBS_SEASONAL}"},
                },
            },
            {
                "cli": ["run", "ml", "--study", BIKE, "--config", "seasonal_7", "--partition", "dev", "--request-id", "l1-seasonal"],
                "expect": {"exit": 0, "endings": ["; Observation set {L1_OBS_SEASONAL}"]},
            },
        ],
    },
    {
        "id": "L1.4",
        "title": "Score the two Attempts",
        "shows": "The MAE of each Attempt over 182 of 182 expected Items: 1090.79 rentals per day for seasonal_7, 1264.73 for ridge_v1.",
        "why": (
            "An Assessment applies a Scorer, a versioned rule of scoring (here regression_mae_v1), to an Observation set against the "
            "References: for each day the absolute error, the gap between forecast and true value without its sign, then their mean, "
            "the MAE (mean absolute error), in rentals per day, lower being better. assess reads the kept forecasts and runs no model "
            "again. It takes the Observation set ID that run ml printed and the References ID that init printed."
        ),
        "actions": [
            {
                "cli": ["assess", "--study", BIKE, "--observations", "{L1_OBS_SEASONAL}", "--scorer", "regression_mae_v1", "--references", "{L1_BIKE_REFS}", "--json"],
                "capture": {"L1_A_SEASONAL": "assessment.assessment_id"},
                "print": ["assessment.assessment_id", "assessment.metrics[0].id", "assessment.metrics[0].value", "assessment.metrics[0].unit", "assessment.counts.scored", "assessment.counts.expected"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "assessment.observation_set_id": "{L1_OBS_SEASONAL}",
                        "assessment.metrics[0].value": 1090.7912087912089,
                        "assessment.counts.scored": 182,
                        "assessment.counts.expected": 182,
                    },
                },
            },
            {
                "cli": ["assess", "--study", BIKE, "--observations", "{L1_OBS_RIDGE}", "--scorer", "regression_mae_v1", "--references", "{L1_BIKE_REFS}", "--json"],
                "capture": {"L1_A_RIDGE": "assessment.assessment_id"},
                "print": ["assessment.assessment_id", "assessment.metrics[0].id", "assessment.metrics[0].value", "assessment.metrics[0].unit", "assessment.counts.scored", "assessment.counts.expected"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "assessment.observation_set_id": "{L1_OBS_RIDGE}",
                        "assessment.metrics[0].value": 1264.730691775682,
                        "assessment.counts.scored": 182,
                        "assessment.counts.expected": 182,
                    },
                },
            },
        ],
    },
    {
        "id": "L1.5",
        "title": "Compare the two Assessments, with the warning and the limitations",
        "shows": (
            "The Comparison, compatible, with the warning COMPARISON_SINGLE_FEATURE_BEATS: a delta of +173.939 rentals per day over "
            "182 of 182 paired Items; then the Comparison read back from the Study, with its exact delta, the warning and its "
            "limitations, among them the dependence of daily observations and the one code environment of the two Attempts; then the "
            "first lines of paired_deltas.csv."
        ),
        "why": (
            "A Comparison sets two Assessments side by side: the Control (seasonal_7), against which one measures, and the Candidate "
            "(ridge_v1), which one measures. It first checks that they can be compared (the same days, the same References, the same "
            "Scorer), then pairs the days one by one: paired_deltas.csv keeps, for each day, the error of each side and their "
            "difference. The delta is the Candidate's MAE minus the Control's: positive, so ridge_v1 errs more. The first limitation "
            "says no interval is given: the days are dependent, which rules out the naive interval that treats them as independent, "
            "not every interval. The warning says that ridge_v1 is beaten by each of its own lag features used alone as the forecast."
        ),
        "actions": [
            {
                "cli": ["compare", "--study", BIKE, "--control", "{L1_A_SEASONAL}", "--candidate", "{L1_A_RIDGE}", "--json"],
                "capture": {"L1_COMPARISON": "comparison.comparison_id"},
                "print": ["comparison.comparison_id", "comparison.comparability.status", "comparison.delta.value", "comparison.delta.unit", "comparison.delta.definition", "comparison.coverage.paired", "comparison.warnings[0].code"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "comparison.roles.control_assessment_id": "{L1_A_SEASONAL}",
                        "comparison.roles.candidate_assessment_id": "{L1_A_RIDGE}",
                        "comparison.comparability.status": "compatible",
                        "comparison.delta.value": 173.93948298447322,
                        "comparison.coverage.paired": 182,
                        "comparison.warnings[0].code": "COMPARISON_SINGLE_FEATURE_BEATS",
                    },
                },
            },
            {
                "cli": ["status", "--study", BIKE, "--json"],
                "print": ["comparisons[-1].delta.value", "comparisons[-1].warnings[0].message", "comparisons[-1].limitations"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "comparisons[-1].comparison_id": "{L1_COMPARISON}",
                        "comparisons[-1].delta.value": 173.93948298447322,
                    },
                    "present": {"comparisons[-1].limitations": LIMITATIONS},
                },
            },
            {"show": "head", "lines": 3, "path": BIKE + "/comparisons/*/paired_deltas.csv"},
        ],
    },
    {
        "id": "L1.6",
        "title": "Read the Study and render its report page",
        "shows": (
            "status: 0 Exposures recorded in this Study, and the two Attempts; then the report page, written outside the Study, "
            "which records no Exposure: it shows no public_check Item."
        ),
        "why": (
            "status reads the Study and writes nothing: its Attempts and the count of its Exposures, the recorded looks at the days "
            "of the final check (L1.7). report writes one self-contained HTML page from the Study's records alone, with no network; "
            "open it in a browser to see it. While nothing has touched public_check, the page says so and no Exposure is counted."
        ),
        "actions": [
            {"cli": ["status", "--study", BIKE], "expect": {"exit": 0}},
            {
                "cli": ["report", "--study", BIKE, "--out", "{work}/l1-bike-report.html", "--json"],
                "print": ["report.out", "report.sections", "report.exposure.recorded"],
                "expect": {"exit": 0, "values": {"report.exposure.recorded": False, "report.exposure.journal_entries": 0, "len(report.sections)": 10}},
            },
        ],
    },
    {
        "id": "L1.7",
        "title": "Touch the days of the final check, and see each Exposure recorded",
        "shows": (
            "An Attempt on the 184 Items of public_check, after which the Study still counts 0 Exposures; its Assessment, after which "
            "it counts one freeze record and one Exposure; the report page, which shows those days and records a second Exposure; "
            "then the two files of the Exposure journal."
        ),
        "why": (
            "public_check is the Partition of the final check: 184 days not to look at while choosing, or one ends up choosing what "
            "works on them. Hypotrail does not forbid a look, it records it: each Assessment or page that shows those days is an "
            "Exposure, written in the Study's exposures/ journal. An Attempt on those days records none; its Assessment records one "
            "and, the first time, freezes the state of the Study in a freeze record; a report page that shows them records another. "
            "The statement status prints gives the limit: the Study cannot prove that nobody looked at those days elsewhere."
        ),
        "actions": [
            {
                "cli": ["run", "ml", "--study", BIKE, "--config", "seasonal_7", "--partition", "public_check", "--request-id", "l1-check", "--json"],
                "capture": {"L1_OBS_CHECK": "observation_set_id"},
                "print": ["attempt.attempt_id", "attempt.item_counts", "observation_set_id"],
                "expect": {"exit": 0, "values": {"replayed": False, "attempt.item_counts": {"produced": 184, "failed": 0, "missing": 0}}},
            },
            {
                "cli": ["status", "--study", BIKE, "--json"],
                "print": ["exposures.recorded_in_this_study", "len(freeze_records)"],
                "expect": {"exit": 0, "values": {"exposures.recorded_in_this_study": 0, "len(freeze_records)": 0}},
            },
            {
                "cli": ["assess", "--study", BIKE, "--observations", "{L1_OBS_CHECK}", "--scorer", "regression_mae_v1", "--references", "{L1_BIKE_REFS}", "--json"],
                "print": ["assessment.assessment_id", "assessment.metrics[0].value", "assessment.counts.scored", "assessment.counts.expected"],
                "expect": {
                    "exit": 0,
                    "values": {"assessment.metrics[0].value": 1129.7880434782608, "assessment.counts.scored": 184, "assessment.counts.expected": 184},
                },
            },
            {
                "cli": ["status", "--study", BIKE, "--json"],
                "print": ["len(freeze_records)", "exposures.recorded_in_this_study", "exposures.statement"],
                "expect": {"exit": 0, "values": {"len(freeze_records)": 1, "exposures.recorded_in_this_study": 1}},
            },
            {
                "cli": ["report", "--study", BIKE, "--out", "{work}/l1-bike-report.html", "--json"],
                "print": ["report.out", "report.exposure.recorded", "report.exposure.entry_id"],
                "expect": {"exit": 0, "values": {"report.exposure.recorded": True, "report.exposure.journal_entries": 2, "len(report.sections)": 10}},
            },
            {
                "cli": ["status", "--study", BIKE, "--json"],
                "print": ["exposures.recorded_in_this_study", "len(freeze_records)"],
                "expect": {"exit": 0, "values": {"exposures.recorded_in_this_study": 2, "len(freeze_records)": 1}},
            },
            {"show": "files", "path": BIKE + "/exposures"},
        ],
    },
    {
        "id": "A4",
        "title": "Copy the Workloads outside the checkout, and verify the copy",
        "shows": (
            "The checkout's examples/ copied into the work folder as demo-examples, then data verify on that copy: bike_day and "
            "chinook each verified, with the SHA-256 of its data file, the same as in the checkout."
        ),
        "why": (
            "Task 6 changes two References, and a rule of this repository forbids changing an expected value to improve a score. "
            "So the second Bike Study is made from a copy of the Workloads in the work folder, given with --examples-dir to each "
            "command that reads the Workload, and the two edits of task 6 are made in that copy. No tracked file of the checkout "
            "changes."
        ),
        "actions": [
            {"copy": "{checkout}/examples", "to": COPY},
            {
                "cli": ["data", "verify", "--examples-dir", COPY, "--json"],
                "print": ["datasets[*].workload", "datasets[*].status", "datasets[*].sha256"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "datasets[*].workload": ["bike_day", "chinook"],
                        "datasets[*].status": ["verified", "verified"],
                        "datasets[0].sha256": "a6bcf826782d3c0fbfdcbeead17cd0884185a0dafe8ff10cd48a874ee7ba18be",
                    },
                },
            },
        ],
    },
    {
        "id": "A5",
        "title": "Make the second Bike Study on the copy: two Attempts, two Assessments and one Comparison",
        "shows": (
            "The Study made from the copy, with the Protocol digest and the References ID of the first Bike Study; seasonal_7 and "
            "ridge_v1 run on the 182 Items of dev; their MAEs, 1090.79 and 1264.73 rentals per day; the Comparison of the two, "
            "seasonal_7 as the Control, with its delta of +173.939 and its warning; then the two reads of this state kept for the "
            "client's tests, after-compare."
        ),
        "why": (
            "These are the steps of L1 again, this time in the Study of L2. At the end, no Decision cites the Comparison: that is "
            "what makes it a Pending decision. The reads written to kept/ are status --json and figures --json as the CLI printed "
            "them: the client's tests build the panel's document from them, at this state and at six later ones."
        ),
        "actions": [
            {
                "cli": ["init", "--workload", "bike_day", "--study", L2_BIKE, "--examples-dir", COPY, "--json"],
                "capture": {"L2_STUDY": "study.study_id", "L2_REFS": "references_id"},
                "print": ["study.study_id", "study.protocol_digest", "references_id"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "study.revision_number": 1,
                        "study.protocol_digest": "d4a1c2cbeb43025f6d3de1be6cc4375b83b0307d928cbb7fadf26f58fd78a6f0",
                        "references_id": "references-7520d791bfe31924",
                    },
                },
            },
            {
                "cli": ["run", "ml", "--study", L2_BIKE, "--config", "seasonal_7", "--partition", "dev", "--request-id", "demo-seasonal", "--examples-dir", COPY, "--json"],
                "capture": {"L2_OBS_SEASONAL": "observation_set_id"},
                "print": ["attempt.attempt_id", "attempt.item_counts", "observation_set_id"],
                "expect": {"exit": 0, "values": {"replayed": False, "attempt.technical_status": "completed", "attempt.item_counts": COUNTS_182}},
            },
            {
                "cli": ["run", "ml", "--study", L2_BIKE, "--config", "ridge_v1", "--partition", "dev", "--request-id", "demo-ridge", "--examples-dir", COPY, "--json"],
                "capture": {"L2_OBS_RIDGE": "observation_set_id"},
                "print": ["attempt.attempt_id", "attempt.item_counts", "observation_set_id"],
                "expect": {"exit": 0, "values": {"replayed": False, "attempt.technical_status": "completed", "attempt.item_counts": COUNTS_182}},
            },
            {
                "cli": ["assess", "--study", L2_BIKE, "--observations", "{L2_OBS_SEASONAL}", "--scorer", "regression_mae_v1", "--references", "{L2_REFS}", "--json"],
                "capture": {"L2_A_SEASONAL": "assessment.assessment_id"},
                "print": ["assessment.assessment_id", "assessment.metrics[0].value", "assessment.rescoring"],
                "expect": {"exit": 0, "values": {"assessment.metrics[0].value": 1090.7912087912089, "assessment.rescoring": None}},
            },
            {
                "cli": ["assess", "--study", L2_BIKE, "--observations", "{L2_OBS_RIDGE}", "--scorer", "regression_mae_v1", "--references", "{L2_REFS}", "--json"],
                "capture": {"L2_A_RIDGE": "assessment.assessment_id"},
                "print": ["assessment.assessment_id", "assessment.metrics[0].value", "assessment.rescoring"],
                "expect": {"exit": 0, "values": {"assessment.metrics[0].value": 1264.730691775682, "assessment.rescoring": None}},
            },
            {
                "cli": ["compare", "--study", L2_BIKE, "--control", "{L2_A_SEASONAL}", "--candidate", "{L2_A_RIDGE}", "--json"],
                "capture": {"L2_COMPARISON": "comparison.comparison_id"},
                "print": ["comparison.comparison_id", "comparison.delta.metric", "comparison.delta.value", "comparison.delta.unit", "comparison.warnings[0].code"],
                "expect": {
                    "exit": 0,
                    "values": {"comparison.delta.value": 173.93948298447322, "comparison.warnings[0].code": "COMPARISON_SINGLE_FEATURE_BEATS"},
                },
            },
            keep("after-compare", 12),
        ],
    },
    {
        "id": "task 1",
        "title": "Find the pending decision",
        "shows": (
            "status --json: the Write sequence 12, and one Pending decision, on the Comparison of A5, with its fixed question and "
            "its three options, each with its consequence."
        ),
        "why": (
            "A Pending decision is written nowhere: the Study derives it at each read, for each Comparison of the current revision "
            "that no applying Decision cites. The panel shows this same read. It is the first half of the promise of L2: what needs "
            "a person's attention is found without looking for it."
        ),
        "actions": [
            {
                "cli": status_l2(),
                "print": [
                    "write_sequence", "len(pending_decisions)", "pending_decisions[*].comparison_id", "pending_decisions[0].question.text",
                    "pending_decisions[0].options[*].text", "pending_decisions[0].options[*].consequence",
                ],
                "expect": {
                    "exit": 0,
                    "values": {
                        "write_sequence": 12,
                        "pending_decisions[*].comparison_id": ["{L2_COMPARISON}"],
                        "pending_decisions[0].question.text": QUESTION,
                        "pending_decisions[0].options[*].text": ["Keep the Control", "Keep the Candidate", "Choose neither yet"],
                    },
                },
            },
        ],
    },
    {
        "id": "task 2",
        "title": "Open its evidence",
        "shows": (
            "The Comparison's delta, the Candidate's MAE minus the Control's, +173.939 rentals per day, and the two Assessments it "
            "compares, each with its MAE."
        ),
        "why": (
            "Deciding needs the evidence: the Comparison and the two Assessments it depends on, each number with the record that "
            "holds it. A positive delta means the Candidate errs more. The panel draws the same numbers from this read, and the "
            "spread of the paired deltas from the figures --json read kept at A5."
        ),
        "actions": [
            {
                "cli": status_l2(),
                "print": [
                    "comparisons[0].comparison_id", "comparisons[0].delta.value", "comparisons[0].roles", "assessments[*].assessment_id",
                    "assessments[*].metrics[0].value",
                ],
                "expect": {
                    "exit": 0,
                    "values": {
                        "comparisons[0].comparison_id": "{L2_COMPARISON}",
                        "comparisons[0].delta.value": 173.93948298447322,
                        "comparisons[0].roles.control_assessment_id": "{L2_A_SEASONAL}",
                        "comparisons[0].roles.candidate_assessment_id": "{L2_A_RIDGE}",
                        "assessments[*].assessment_id": ["{L2_A_SEASONAL}", "{L2_A_RIDGE}"],
                        "assessments[*].metrics[0].value": [1090.7912087912089, 1264.730691775682],
                    },
                },
            },
        ],
    },
    {
        "id": "task 3",
        "title": "Record an answer, as the panel records it",
        "shows": (
            "The decide the panel's bridge starts, each option joined to its value by =: the question, the option Keep the Control, "
            "the author human, the Comparison as its one cited id, a request id and the Write sequence 12 it read; then status "
            "--json: the Write sequence 14, no Pending decision, the Decision, which applies and has no reason, and the warning of "
            "the Comparison, word for word; then the two reads of the state after-decide."
        ),
        "why": (
            "A Decision is a file of the Study, written by decide alone and never rewritten. It holds the question, the option, its "
            "author, what it cites and the Write sequence its author read: had the Study been written to since, decide would have "
            "refused it (STUDY_CHANGED). The Write sequence goes from 12 to 14 because a write adds two entries to the Study's write "
            "journal, its begin and its end. The option is the one the owner chose when he walked the demonstration on 2026-11-25. It is "
            "recorded to show how a Decision is written, not as the answer the evidence supports: the warning below shows one lag "
            "feature alone, mean_previous_7 (823.878 rentals per day), below both Configurations (1090.79 and 1264.73)."
        ),
        "actions": [
            {
                "cli": decide("Keep the Control", "{L2_COMPARISON}", "demo-task-3", 12),
                "kept": "decide-task-3",
                "capture": {"L2_DECISION": "decision.decision_id"},
                "print": ["decision.decision_id", "decision.option", "decision.author", "decision.cited_ids", "decision.read_sequence"],
                "expect": {
                    "exit": 0,
                    "values": {"replayed": False, "decision.author": "human", "decision.cited_ids": ["{L2_COMPARISON}"], "decision.read_sequence": 12},
                },
            },
            {
                "cli": status_l2(),
                "print": [
                    "write_sequence", "len(pending_decisions)", "decisions[*].decision_id", "decisions[0].option", "decisions[0].author",
                    "decisions[0].cited_ids", "decisions[0].applies", "decisions[0].reasons", "comparisons[0].warnings[0].message",
                ],
                "expect": {
                    "exit": 0,
                    "values": {
                        "write_sequence": 14,
                        "len(pending_decisions)": 0,
                        "decisions[*].decision_id": ["{L2_DECISION}"],
                        "decisions[0].author": "human",
                        "decisions[0].cited_ids": ["{L2_COMPARISON}"],
                        "decisions[0].applies": True,
                        "decisions[0].reasons": [],
                    },
                },
            },
            keep("after-decide", 14),
        ],
    },
    {
        "id": "C10",
        "title": "Give the Decision to the next prompt of Claude Code, through its hook",
        "shows": (
            "The hook's program, started with the interpreter and flags of its settings fragment, --study set to this Study, and the "
            "hook's input written on its stdin, then closed: its text gives the Write sequence 14, no Pending decision, and the "
            "Decision of task 3 with its option and its id, then the rule for an agent."
        ),
        "why": (
            "Claude Code starts this hook before each prompt, so that the Study's state is in the context before the model answers. "
            "The hook starts one read, status --since 0 --json, through uv in the checkout, and prints what it holds; it writes "
            "nothing. No model is asked here: whether a model's answer then names the Decision is the owner's check."
        ),
        "actions": [
            {
                "program": HOOK,
                "interpreter": HOOK_INTERPRETER,
                "args": ["--study", L2_BIKE],
                "input": HOOK_INPUT,
                "environment": {"CLAUDE_PROJECT_DIR": "{checkout}"},
                "expect": {
                    "exit": 0,
                    "lines": [
                        "Write sequence: 14",
                        "Pending decisions: 0",
                        "Decisions, oldest first: 1",
                        f'- Decision {{L2_DECISION}}: question "{QUESTION}"; option "Keep the Control"; author human; source none; '
                        "channel none; cited {L2_COMPARISON}; applies true; evidence_change none.",
                    ],
                },
            },
        ],
    },
    {
        "id": "task 4",
        "title": "Find the answer again, read by a new process",
        "shows": "status --json from a new process: the Write sequence still 14, no Pending decision, and the same Decision.",
        "why": (
            "No process of the demonstration keeps anything in memory: a new process finds the Decision because it reads it from the "
            "Study's files. A read writes nothing, so the Write sequence stays 14. Closing and opening VS Code is the owner's part of "
            "this task."
        ),
        "actions": [
            {
                "cli": status_l2(),
                "print": ["write_sequence", "len(pending_decisions)", "decisions[*].decision_id", "decisions[0].option", "decisions[0].applies"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "write_sequence": 14,
                        "len(pending_decisions)": 0,
                        "decisions[*].decision_id": ["{L2_DECISION}"],
                        "decisions[0].option": "Keep the Control",
                        "decisions[0].applies": True,
                    },
                },
            },
        ],
    },
    {
        "id": "task 5",
        "title": "See a real limitation",
        "shows": (
            "The warning COMPARISON_SINGLE_FEATURE_BEATS of the Comparison, word for word, and its limitations, among them the "
            "dependence of daily observations and the one code environment of the two Attempts."
        ),
        "why": (
            "This limitation comes from the data, not from a made-up example: ridge_v1 is beaten by each of its own lag features used "
            "alone as the forecast. The limitations say what the delta does not show: the days are dependent, which rules out the "
            "naive interval that treats them as independent, not every interval; none is computed here. The panel shows them beside "
            "the delta they limit."
        ),
        "actions": [
            {
                "cli": status_l2(),
                "print": ["comparisons[0].warnings[*].code", "comparisons[0].warnings[0].message", "comparisons[0].limitations"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "comparisons[0].warnings[0].code": "COMPARISON_SINGLE_FEATURE_BEATS",
                    },
                    "present": {"comparisons[0].limitations": LIMITATIONS},
                },
            },
        ],
    },
    {
        "id": "task 6.1",
        "title": "Edit a Reference outside the assessed Partition: evidence rescored",
        "shows": (
            "edit_copy.py raises registered and cnt of 2012-12-31, a day of public_check, by 100 in the copy and rewrites its lock; "
            "data verify gives the new SHA-256; init --new-revision makes revision 2 and prints its References ID; each Observation "
            "set is assessed again against it, with rescoring.cause references_version, no changed Item and the same MAE; then "
            "status --json: the Decision of task 3 no longer applies, with revision_changed among its reasons, and its evidence is "
            "\"evidence rescored\"; then the two reads of the state after-6.1."
        ),
        "why": (
            "Task 6 shows what becomes of a Decision when its evidence changes. A change of a Reference is a new revision of the "
            "Protocol, then a new Assessment of each kept Observation set, with no model run again. The Decision no longer applies, "
            "because the revision changed, but the Study says \"evidence rescored\": no assessed Item changed, and each cited Metric "
            "equals the latest. The Decision's file is not touched. After this step nothing is pending: the Comparison of task 3 compares "
            "Assessments of revision 1. What a person does next is compare the two latest Assessments, as COMPARE does below."
        ),
        "actions": [
            {
                "program": EDIT_COPY,
                "args": ["--copy", COPY, "--edit", "6.1"],
                "expect": {"exit": 0, "lines": ["day: 2012-12-31", "registered: 2290 -> 2390", "cnt: 2729 -> 2829"]},
            },
            {
                "cli": ["data", "verify", "--examples-dir", COPY, "--json"],
                "print": ["datasets[*].status", "datasets[0].sha256"],
                "expect": {
                    "exit": 0,
                    "values": {"datasets[*].status": ["verified", "verified"], "datasets[0].sha256": "0c4a409f8fb301748ae2593a0480a10bcf2253276dc4a6eab41abb419b210d72"},
                },
            },
            {
                "cli": ["init", "--study", L2_BIKE, "--new-revision", "--examples-dir", COPY, "--json"],
                "capture": {"L2_REFS_61": "references_id"},
                "print": ["study.revision_number", "study.protocol_digest", "references_id"],
                "expect": {"exit": 0, "values": {"study.revision_number": 2}},
            },
            {
                "cli": ["assess", "--study", L2_BIKE, "--observations", "{L2_OBS_SEASONAL}", "--scorer", "regression_mae_v1", "--references", "{L2_REFS_61}", "--json"],
                "capture": {"L2_A_SEASONAL_61": "assessment.assessment_id"},
                "print": ["assessment.assessment_id", "assessment.metrics[0].value", "assessment.rescoring.cause", "len(assessment.rescoring.changed_items)"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "assessment.metrics[0].value": 1090.7912087912089,
                        "assessment.rescoring.cause": "references_version",
                        "len(assessment.rescoring.changed_items)": 0,
                    },
                },
            },
            {
                "cli": ["assess", "--study", L2_BIKE, "--observations", "{L2_OBS_RIDGE}", "--scorer", "regression_mae_v1", "--references", "{L2_REFS_61}", "--json"],
                "capture": {"L2_A_RIDGE_61": "assessment.assessment_id"},
                "print": ["assessment.assessment_id", "assessment.metrics[0].value", "assessment.rescoring.cause", "len(assessment.rescoring.changed_items)"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "assessment.metrics[0].value": 1264.730691775682,
                        "assessment.rescoring.cause": "references_version",
                        "len(assessment.rescoring.changed_items)": 0,
                    },
                },
            },
            {
                "cli": status_l2(),
                "print": [
                    "write_sequence", "len(pending_decisions)", "decisions[0].applies", "decisions[0].reasons[*].reason",
                    "decisions[0].evidence_change.state", "decisions[0].evidence_change.lines[*].changed_item_count",
                    "decisions[0].evidence_change.lines[*].metrics[0]",
                ],
                "expect": {
                    "exit": 0,
                    "values": {
                        "write_sequence": 20,
                        "len(pending_decisions)": 0,
                        "decisions[0].applies": False,
                        "decisions[0].reasons[*].reason": ["revision_changed", "compared_assessment_superseded", "compared_assessment_superseded"],
                        "decisions[0].evidence_change.state": "evidence_rescored",
                        "decisions[0].evidence_change.lines[*].latest_assessment_id": ["{L2_A_SEASONAL_61}", "{L2_A_RIDGE_61}"],
                        "decisions[0].evidence_change.lines[*].changed_item_count": [0, 0],
                        "decisions[0].evidence_change.lines[*].metrics[0].latest": [1090.7912087912089, 1264.730691775682],
                    },
                },
            },
            keep("after-6.1", 20),
        ],
    },
    {
        "id": "task 6.2",
        "title": "Edit a Reference inside the assessed Partition: result changed",
        "shows": (
            "edit_copy.py raises registered and cnt of 2012-03-15, a day of dev, by 100; data verify; revision 3 and its References "
            "ID; the two new Assessments, each with one changed Item, and the MAEs 1091.34 and 1265.28; then status --json: the "
            "Decision does not apply, and its evidence is \"result changed\", with for each side the cited and the latest Metric; "
            "then the two reads of the state after-6.2."
        ),
        "why": (
            "This time the edited day is one the Comparison scores: one Item changes on each side, and each MAE rises by 100/182. "
            "Both rise by the same amount, so their difference does not move: \"result changed\" names a changed Item, not a changed "
            "delta, and not a changed conclusion. The Study says \"result changed\" and shows the value the Decision cited beside the "
            "latest. No delta is computed again behind a person's back: deciding again, on a new Comparison, is a person's choice."
        ),
        "actions": [
            {
                "program": EDIT_COPY,
                "args": ["--copy", COPY, "--edit", "6.2"],
                "expect": {"exit": 0, "lines": ["day: 2012-03-15", "registered: 5187 -> 5287", "cnt: 6192 -> 6292"]},
            },
            {
                "cli": ["data", "verify", "--examples-dir", COPY, "--json"],
                "print": ["datasets[*].status", "datasets[0].sha256"],
                "expect": {
                    "exit": 0,
                    "values": {"datasets[*].status": ["verified", "verified"], "datasets[0].sha256": "dafe91afce9e159bad51950ccc24d78d1f7ef0045e8341f46acdea505613f71b"},
                },
            },
            {
                "cli": ["init", "--study", L2_BIKE, "--new-revision", "--examples-dir", COPY, "--json"],
                "capture": {"L2_REFS_62": "references_id"},
                "print": ["study.revision_number", "study.protocol_digest", "references_id"],
                "expect": {"exit": 0, "values": {"study.revision_number": 3, "references_id": "references-ff964e6939ad94ee"}},
            },
            {
                "cli": ["assess", "--study", L2_BIKE, "--observations", "{L2_OBS_SEASONAL}", "--scorer", "regression_mae_v1", "--references", "{L2_REFS_62}", "--json"],
                "capture": {"L2_A_SEASONAL_62": "assessment.assessment_id"},
                "print": ["assessment.assessment_id", "assessment.metrics[0].value", "assessment.rescoring.cause", "len(assessment.rescoring.changed_items)"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "assessment.metrics[0].value": 1091.3406593406594,
                        "assessment.rescoring.cause": "references_version",
                        "len(assessment.rescoring.changed_items)": 1,
                    },
                },
            },
            {
                "cli": ["assess", "--study", L2_BIKE, "--observations", "{L2_OBS_RIDGE}", "--scorer", "regression_mae_v1", "--references", "{L2_REFS_62}", "--json"],
                "capture": {"L2_A_RIDGE_62": "assessment.assessment_id"},
                "print": ["assessment.assessment_id", "assessment.metrics[0].value", "assessment.rescoring.cause", "len(assessment.rescoring.changed_items)"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "assessment.metrics[0].value": 1265.2801423251326,
                        "assessment.rescoring.cause": "references_version",
                        "len(assessment.rescoring.changed_items)": 1,
                    },
                },
            },
            {
                "cli": status_l2(),
                "print": [
                    "write_sequence", "len(pending_decisions)", "decisions[0].applies", "decisions[0].reasons[*].reason",
                    "decisions[0].evidence_change.state", "decisions[0].evidence_change.lines[*].changed_item_count",
                    "decisions[0].evidence_change.lines[*].metrics[0]",
                ],
                "expect": {
                    "exit": 0,
                    "values": {
                        "write_sequence": 26,
                        "len(pending_decisions)": 0,
                        "decisions[0].applies": False,
                        "decisions[0].evidence_change.state": "result_changed",
                        "decisions[0].evidence_change.lines[*].latest_assessment_id": ["{L2_A_SEASONAL_62}", "{L2_A_RIDGE_62}"],
                        "decisions[0].evidence_change.lines[*].changed_item_count": [1, 1],
                        "decisions[0].evidence_change.lines[*].metrics[0].cited": [1090.7912087912089, 1264.730691775682],
                        "decisions[0].evidence_change.lines[*].metrics[0].latest": [1091.3406593406594, 1265.2801423251326],
                    },
                },
            },
            keep("after-6.2", 26),
        ],
    },
    {
        "id": "C5-check",
        "title": "Check from the terminal what the panel shows",
        "shows": (
            "status --json at the state after-6.2: the study id, the Write sequence 26, the ids of the Pending decisions, none, and "
            "each Decision with whether it applies: the Decision of task 3, which does not."
        ),
        "why": (
            "\"Direct evaluation remains usable without the workflow\": what the panel shows can be read through the CLI alone. A "
            "person notes what the panel shows and finds the same values here; the client's tests compare the panel's document of "
            "the state after-6.2 with them."
        ),
        "actions": [
            {
                "cli": status_l2(),
                "print": ["study.study_id", "write_sequence", "pending_decisions[*].comparison_id", "decisions[*].decision_id", "decisions[*].applies"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "study.study_id": "{L2_STUDY}",
                        "write_sequence": 26,
                        "pending_decisions[*].comparison_id": [],
                        "decisions[*].decision_id": ["{L2_DECISION}"],
                        "decisions[*].applies": [False],
                    },
                },
            },
        ],
    },
    {
        "id": "COMPARE",
        "title": "Compare the two latest Assessments",
        "shows": (
            "A new Comparison of the two Assessments of revision 3, seasonal_7 as the Control: its delta, +173.939 rentals per day, "
            "equal to the delta of A5 to 12 significant digits, with the same warning on other numbers; then status --json: one "
            "Pending decision, on this Comparison; then the two reads of the state before-the-refused-write."
        ),
        "why": (
            "After task 6 nothing is pending: the Comparison of task 3 compares Assessments of revision 1. A Comparison of the latest "
            "Assessments is pending again. Its delta is the delta of A5, because both MAEs rose by the same 100/182: so \"result "
            "changed\" at 6.2 names a changed Item, not a changed delta, and not a changed conclusion."
        ),
        "actions": [
            {
                "cli": ["compare", "--study", L2_BIKE, "--control", "{L2_A_SEASONAL_62}", "--candidate", "{L2_A_RIDGE_62}", "--json"],
                "capture": {"L2_COMPARISON_62": "comparison.comparison_id"},
                "print": ["comparison.comparison_id", "comparison.delta.metric", "comparison.delta.value", "comparison.delta.unit", "comparison.warnings[0].code"],
                "expect": {
                    "exit": 0,
                    "values": {"comparison.delta.value": 173.93948298447322, "comparison.warnings[0].code": "COMPARISON_SINGLE_FEATURE_BEATS"},
                },
            },
            {
                "cli": status_l2(),
                "print": ["write_sequence", "pending_decisions[*].comparison_id"],
                "expect": {"exit": 0, "values": {"write_sequence": 28, "pending_decisions[*].comparison_id": ["{L2_COMPARISON_62}"]}},
            },
            keep("before-the-refused-write", 28),
        ],
    },
    {
        "id": "S1",
        "title": "A write from the terminal, then a Decision sent on the older Write sequence",
        "shows": (
            "run ml of seasonal_7 on dev from the terminal: a new Attempt, which writes an Observation set and no Assessment; status "
            "--json: the Write sequence 30, and the Comparison still pending; then the decide the panel sends when it has not read "
            "again, with the Write sequence 28 it read: refused with STUDY_CHANGED, exit 6, stage sequence, naming the two journal "
            "entries of that write; then the two reads of the state after-the-terminal-wrote, still at 30."
        ),
        "why": (
            "The safety net: when the Study changes between the panel's read and its write, the write is refused and nothing is "
            "written. The run ml from the terminal moves the Write sequence; the panel, which did not read again, sends the older "
            "one, and the refusal is the outcome expected. The Comparison stays pending, since the new Observation set has no "
            "Assessment."
        ),
        "actions": [
            {
                "cli": ["run", "ml", "--study", L2_BIKE, "--config", "seasonal_7", "--partition", "dev", "--request-id", "demo-s1", "--examples-dir", COPY, "--json"],
                "print": ["attempt.attempt_id", "attempt.item_counts", "observation_set_id"],
                "expect": {"exit": 0, "values": {"replayed": False, "attempt.technical_status": "completed", "attempt.item_counts": COUNTS_182}},
            },
            {
                "cli": status_l2(),
                "capture": {"L2_READ_AFTER_S1": "write_sequence"},
                "print": ["write_sequence", "pending_decisions[*].comparison_id"],
                "expect": {"exit": 0, "values": {"write_sequence": 30, "pending_decisions[*].comparison_id": ["{L2_COMPARISON_62}"]}},
            },
            {
                "cli": decide("Keep the Control", "{L2_COMPARISON_62}", "demo-s1-decide", 28),
                "kept": "decide-s1",
                "print": ["error.code", "error.stage", "error.message", "error.details.read_sequence", "error.details.write_sequence", "error.details.writes_since"],
                "expect": {
                    "exit": 6,
                    "refusal": {"code": "STUDY_CHANGED", "stage": "sequence"},
                    "values": {
                        "error.details.read_sequence": 28,
                        "error.details.write_sequence": 30,
                        "error.details.writes_since[*].command": ["run ml", "run ml"],
                        "error.details.writes_since[*].phase": ["begin", "end"],
                        "error.details.writes_since[*].request_id": ["demo-s1", "demo-s1"],
                    },
                },
            },
            keep("after-the-terminal-wrote", 30),
        ],
    },
    {
        "id": "C8",
        "title": "A proxy Decision, by a stated rule",
        "shows": (
            "The decide an agent sends when it answers by a rule: the author proxy, a source that names the rule \"keep the "
            "Configuration with the lowest MAE\", the option that rule gives on the two Metrics of the Comparison, Keep the Control "
            "(1091.34 against 1265.28 rentals per day), and the Write sequence 30 read after S1; then status --json: two Decisions, "
            "the second by proxy with its source, which applies, and no Pending decision."
        ),
        "why": (
            "A Decision made by an agent that applies a rule is not a human Decision. It is written by decide too, with the author "
            "proxy and a source that names the rule, so that who or what decided is always known. The rule is the one the owner gave "
            "Claude Code on 2026-11-25; no model is asked here. The rule compares the two Configurations only: it does not read the "
            "warning, by which mean_previous_7 alone beats both. A proxy Decision records what the rule gave, not that the rule is right."
        ),
        "actions": [
            {
                "cli": decide("Keep the Control", "{L2_COMPARISON_62}", "demo-c8", "{L2_READ_AFTER_S1}", author="proxy", source=PROXY_SOURCE),
                "print": ["decision.decision_id", "decision.option", "decision.author", "decision.source", "decision.cited_ids", "decision.read_sequence"],
                "expect": {
                    "exit": 0,
                    "values": {"replayed": False, "decision.author": "proxy", "decision.source": PROXY_SOURCE, "decision.cited_ids": ["{L2_COMPARISON_62}"]},
                },
            },
            {
                "cli": status_l2(),
                "capture": {"L2_READ_AFTER_C8": "write_sequence"},
                "print": ["write_sequence", "len(pending_decisions)", "decisions[*].author", "decisions[*].source", "decisions[*].applies"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "write_sequence": 32,
                        "len(pending_decisions)": 0,
                        "decisions[*].author": ["human", "proxy"],
                        "decisions[1].source": PROXY_SOURCE,
                        "decisions[1].applies": True,
                    },
                },
            },
        ],
    },
    {
        "id": "DEV",
        "title": "Declare a deviation",
        "shows": (
            "A Declared deviation by human, citing the References ID of revision 3: the References of revisions 2 and 3 were edited "
            "by the demonstration's script and correct no error of the data; then status --json: one Declared deviation, not "
            "withdrawn, and the Write sequence 34; then the two reads of the final state."
        ),
        "why": (
            "A Declared deviation records a known limit on what the Study's results show, one its records cannot establish: here, "
            "that the two changes of task 6 were made to show how a Decision is outdated, not because the data was wrong. It is a "
            "record of the Study, never rewritten; a later record can withdraw it."
        ),
        "actions": [
            {
                "cli": [
                    "deviation", "--study", L2_BIKE, "--text", DEVIATION_TEXT, "--author", "human", "--artifact", "{L2_REFS_62}",
                    "--request-id", "demo-dev", "--read-sequence", "{L2_READ_AFTER_C8}", "--json",
                ],
                "print": ["declared_deviation.declared_deviation_id", "declared_deviation.text", "declared_deviation.author", "declared_deviation.cited_ids"],
                "expect": {"exit": 0, "values": {"replayed": False, "declared_deviation.author": "human", "declared_deviation.cited_ids": ["{L2_REFS_62}"]}},
            },
            {
                "cli": status_l2(),
                "print": ["write_sequence", "declared_deviations[*].declared_deviation_id", "declared_deviations[*].withdrawn"],
                "expect": {"exit": 0, "values": {"write_sequence": 34, "declared_deviations[*].withdrawn": [False]}},
            },
            keep("final", 34),
        ],
    },
    {
        "id": "REPORT",
        "title": "Render the report page of the second Bike Study",
        "shows": "The report page, written outside the Study, with its ten sections and no Exposure recorded: nothing touched public_check here.",
        "why": (
            "The page is made from the Study's records alone, with no network. It shows neither the Decisions nor the Declared "
            "deviation today; the panel and status --json do."
        ),
        "actions": [
            {
                "cli": ["report", "--study", L2_BIKE, "--out", "{work}/bike-report.html", "--json"],
                "print": ["report.out", "report.sections", "report.exposure.recorded"],
                "expect": {"exit": 0, "values": {"report.exposure.recorded": False, "report.exposure.journal_entries": 0, "len(report.sections)": 10}},
            },
        ],
    },
    {
        "id": "WORDS",
        "title": "A human Decision with the person's own words, read back",
        "shows": (
            "The person's words written to a file of the work folder, as typed; the decide that records them with the ids of the "
            "pending decision's question and option, one --words-file and --by; then status --json, whose last Decision gives the "
            "text back whole, its channel chat_relayed, its by and authenticated false."
        ),
        "why": (
            "In accompanied mode the person thinks the choice through in the chat and the agent records it. The words are kept "
            "whole on the Decision, from a file, since a shell reading them could change a quote or an accent. The channel says "
            "how they reached the caller, as the caller declares it: nothing checks them against the chat, and the record says so "
            "with authenticated false."
        ),
        "actions": [
            {
                "cli": status_l2(),
                "capture": {"L2_READ_BEFORE_WORDS": "write_sequence"},
                "expect": {"exit": 0, "values": {"write_sequence": 34}},
            },
            {"write": "{work}/words.txt", "text": WORDS_TEXT},
            {
                "cli": [
                    "decide", "--study", L2_BIKE, "--question", QUESTION, "--option", "Keep the Control", "--author", "human",
                    "--artifact", "{L2_COMPARISON_62}", "--question-id", "keep_after_comparison", "--option-id", "keep_control",
                    "--words-file", "{work}/words.txt", "--by", WORDS_BY, "--request-id", "demo-words",
                    "--read-sequence", "{L2_READ_BEFORE_WORDS}", "--json",
                ],
                "print": ["decision.decision_id", "decision.question_id", "decision.option_id", "decision.words.channel"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "replayed": False,
                        "decision.schema_version": "decision/2",
                        "decision.question_id": "keep_after_comparison",
                        "decision.option_id": "keep_control",
                        "decision.words": {"texts": [WORDS_TEXT + "\n"], "channel": "chat_relayed", "by": WORDS_BY, "authenticated": False},
                    },
                },
            },
            {
                "cli": status_l2(),
                "print": ["write_sequence", "decisions[-1].words.texts", "decisions[-1].words.channel", "decisions[-1].words.by", "decisions[-1].words.authenticated"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "write_sequence": 36,
                        "decisions[-1].words.texts": [WORDS_TEXT + "\n"],
                        "decisions[-1].words.channel": "chat_relayed",
                        "decisions[-1].words.by": WORDS_BY,
                        "decisions[-1].words.authenticated": False,
                    },
                },
            },
        ],
    },
    {
        "id": "L1.8",
        "title": "Evaluate an agent on Chinook, without calling a model",
        "shows": (
            "The Chinook Study; the scenario Attempt, Mode scripted_fixture, with 5 Episodes produced, 1 failed and 1 missing; the "
            "Import of the kept Inspect log, 2 Episodes in Mode external_unknown; its Assessment, 0 correct of 2 expected Episodes; "
            "per_item.csv, where exact_table and evidence_link_valid are true and format_valid and contract_success false; then the "
            "report page."
        ),
        "why": (
            "L1's second Track evaluates an agent that answers questions on Chinook with a SQL tool; an Episode is one pass of the "
            "agent on one question. With no key and no cost there are two ways. scripted_fixture runs the real agent loop with a mock "
            "model (mockllm/model) on the Workload's seven Scenarios: 5 produced, 1 failed and 1 missing are the counts the Scenarios "
            "are written to give, since budget_exhausted repeats one tool call until the turn limit, so its Episode fails, and "
            "absent_from_log has no script, so its Episode is missing from the log; together they show that each of the three states "
            "is recorded. import agent adopts the Inspect log of a paid Attempt of 2026-11-20 on the Cases D03 and D05, kept in the "
            "repository and read in place, and records it in Mode external_unknown, because an Import cannot prove which model "
            "answered nor when. The Scorer chinook_contract_v1 finds the right table and valid evidence in each answer, but refuses "
            "its format (invalid_response_format): 0 correct of 2."
        ),
        "actions": [
            {
                "cli": ["init", "--workload", "chinook", "--study", CHINOOK, "--json"],
                "capture": {"L1_CHINOOK_REFS": "references_id"},
                "print": ["study.study_id", "study.protocol_digest", "references_id"],
                "expect": {"exit": 0, "values": {"study.revision_number": 1}},
            },
            {
                "cli": ["run", "agent", "--study", CHINOOK, "--mode", "scripted_fixture", "--config", "plain", "--request-id", "l1-fixture", "--json"],
                "print": ["attempt.attempt_id", "attempt.mode", "attempt.item_counts", "observation_set_id"],
                "expect": {"exit": 0, "values": {"attempt.mode": "scripted_fixture", "attempt.item_counts": {"produced": 5, "failed": 1, "missing": 1}}},
            },
            {"write": "{work}/l1-population.json", "text": POPULATION},
            {
                "cli": ["import", "agent", "--study", CHINOOK, "--source", "{checkout}/" + KEPT_LOG, "--population", "{work}/l1-population.json", "--request-id", "l1-import", "--json"],
                "capture": {"L1_OBS_IMPORT": "observation_set_id"},
                "print": ["attempt.attempt_id", "attempt.mode", "attempt.item_counts", "observation_set_id"],
                "expect": {
                    "exit": 0,
                    "values": {"attempt.operation": "import", "attempt.mode": "external_unknown", "attempt.item_counts": {"produced": 2, "failed": 0, "missing": 0}},
                },
            },
            {
                "cli": ["assess", "--study", CHINOOK, "--observations", "{L1_OBS_IMPORT}", "--scorer", "chinook_contract_v1", "--references", "{L1_CHINOOK_REFS}", "--json"],
                "print": ["assessment.assessment_id", "assessment.primary_criterion", "assessment.counts.correct", "assessment.counts.expected", "assessment.counts.scored"],
                "expect": {
                    "exit": 0,
                    "values": {
                        "assessment.observation_set_id": "{L1_OBS_IMPORT}",
                        "assessment.primary_criterion": "contract_success",
                        "assessment.counts.correct": 0,
                        "assessment.counts.expected": 2,
                        "assessment.counts.scored": 2,
                    },
                },
            },
            {"show": "file", "path": CHINOOK + "/assessments/*/per_item.csv"},
            {
                "cli": ["report", "--study", CHINOOK, "--out", "{work}/l1-chinook-report.html", "--json"],
                "print": ["report.out", "report.exposure.recorded"],
                "expect": {"exit": 0, "values": {"report.exposure.recorded": False, "len(report.sections)": 10}},
            },
        ],
    },
]

Outcome = namedtuple("Outcome", "code captures passed")
MISSING = object()


class Failed(Exception):
    """An expectation that does not hold, or a capture that cannot be read: the script stops."""


def same(found, expected) -> bool:
    """Whether a value found is the value expected. Two numbers of which one is a float agree to 12 significant digits; an integer
    and the equal float are the same; any other value is compared exactly, a list or an object member by member."""
    if isinstance(found, bool) or isinstance(expected, bool):
        return type(found) is type(expected) and found == expected
    if isinstance(found, float) or isinstance(expected, float):
        numbers = isinstance(found, (int, float)) and isinstance(expected, (int, float))
        return numbers and f"{found:.{SIGNIFICANT_DIGITS}g}" == f"{expected:.{SIGNIFICANT_DIGITS}g}"
    if type(found) is not type(expected):
        return False
    if isinstance(found, dict):
        return found.keys() == expected.keys() and all(same(found[key], expected[key]) for key in found)
    if isinstance(found, list):
        return len(found) == len(expected) and all(same(a, b) for a, b in zip(found, expected))
    return found == expected


def walked(value, parts):
    for at, (name, index) in enumerate(parts):
        if index == "*":
            if not isinstance(value, list):
                return MISSING
            each = [walked(entry, parts[at + 1:]) for entry in value]
            return MISSING if any(entry is MISSING for entry in each) else each
        try:
            value = value[name] if name else value[int(index)]
        except (KeyError, IndexError, TypeError):
            return MISSING
    return value


def value_at(payload, path: str):
    """The value at a key path such as `assessment.metrics[0].value`, `len(freeze_records)` for the number of entries,
    `decisions[*].applies` for the list of that value in each entry, or MISSING."""
    counted = path.startswith("len(") and path.endswith(")")
    value = walked(payload, PATH_PART.findall(path[4:-1] if counted else path))
    if counted:
        return len(value) if isinstance(value, (list, dict)) else MISSING
    return value


def resolved(template, values: dict):
    """A template with each placeholder replaced by its value, in each member of a list; any other value as it is."""
    if isinstance(template, list):
        return [resolved(part, values) for part in template]
    if not isinstance(template, str):
        return template

    def value(match):
        if match[1] not in values:
            raise Failed(f"{match[0]} is used before a command captures it")
        return str(values[match[1]])

    return PLACEHOLDER.sub(value, template)


def folders_of(work: Path) -> dict:
    return {"work": str(work), "checkout": str(CHECKOUT)}


def shown(value) -> str:
    return "<missing>" if value is MISSING else json.dumps(value)


def processes(action: dict) -> list:
    """The processes an action starts, each a command of the CLI (`cli`) or another program (`program`): a kept state starts its
    two reads, each kept under the state's name; an action that copies, writes or shows starts none."""
    if "keep" in action:
        expect = {"exit": 0, "values": {"write_sequence": action["sequence"]}}
        return [
            {"cli": [read, "--study", action["study"], "--json"], "kept": f"{action['keep']}.{read}", "print": ["write_sequence"], "expect": expect}
            for read in ("status", "figures")
        ]
    return [action] if "cli" in action or "program" in action else []


def expectation_keys(expect: dict) -> list:
    """The key of each expectation, in the order the script checks them: the exit code, a refusal's code and stage, the key paths,
    each entry a list holds, then each line and each end of a line the output holds."""
    keys = ["exit code"]
    if "refusal" in expect:
        keys += ["error.code", "error.stage"]
    keys += list(expect.get("values", {}))
    keys += [f"an entry of {path}" for path, entries in expect.get("present", {}).items() for _ in entries]
    return keys + ["stdout line"] * len(expect.get("lines", [])) + ["stdout line ending"] * len(expect.get("endings", []))


def expectations(expect: dict, code: int, payload, values: dict, out: str = "") -> list:
    """(key, expected, found) of each expectation of a process."""
    found = [("exit code", expect["exit"], code)]
    if "refusal" in expect:
        found += [("error.code", expect["refusal"]["code"], value_at(payload, "error.code"))]
        found += [("error.stage", expect["refusal"]["stage"], value_at(payload, "error.stage"))]
    for path, expected in expect.get("values", {}).items():
        found.append((path, resolved(expected, values), value_at(payload, path)))
    for path, entries in expect.get("present", {}).items():
        listed = value_at(payload, path)
        for entry in resolved(entries, values):
            found.append((f"an entry of {path}", entry, entry if isinstance(listed, list) and entry in listed else MISSING))
    lines = out.splitlines()
    for line in expect.get("lines", []):
        line = resolved(line, values)
        found.append(("stdout line", line, line if line in lines else MISSING))
    for ending in expect.get("endings", []):
        ending = resolved(ending, values)
        found.append(("stdout line ending", ending, ending if any(line.endswith(ending) for line in lines) else MISSING))
    return found


def start_process(argv, env, cwd, text=None):
    """(exit code, stdout, stderr) of one process: `text` written on its stdin, which is then closed, or no input at all."""
    stdin = {"stdin": subprocess.DEVNULL} if text is None else {"input": text}
    done = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, **stdin)
    return done.returncode, done.stdout, done.stderr


def without_live_key() -> dict:
    return {name: value for name, value in os.environ.items() if name != LIVE_KEY}


def inside(path: Path, folder: Path) -> bool:
    path, folder = path.resolve(), folder.resolve()
    return path == folder or folder in path.parents


def shown_action(action: dict, values: dict) -> str:
    """The line that names an action that is not a command of the CLI."""
    if "write" in action:
        return f"write {resolved(action['write'], values)}"
    if "copy" in action:
        return f"copy {resolved(action['copy'], values)} to {resolved(action['to'], values)}"
    if "keep" in action:
        return f"keep the two reads of the state {action['keep']} of {resolved(action['study'], values)}, in {resolved('{work}', values)}/{KEPT}"
    if action["show"] == "head":
        return f"show the first {action['lines']} lines of {resolved(action['path'], values)}"
    if action["show"] == "folders":
        return "show the folders " + " ".join(resolved(path, values) for path in action["paths"])
    if action["show"] == "files":
        return f"show the files of {resolved(action['path'], values)}"
    return f"show {resolved(action['path'], values)}"


def typed_word(word: str, values: dict) -> str:
    """A word of a `$` line, quoted for a POSIX shell, with the work folder written `$WORK` and the checkout `$CHECKOUT` where the
    quoting allows it: the folder's path and the rest of the word each need no quotes, so that the shell expands the name alone."""
    for name, typed in FOLDER_NAMES.items():
        folder = values[name]
        parts = word.split(folder)
        if len(parts) > 1 and shlex.quote(folder) == folder and all(part[:1] in ("", "/") for part in parts[1:]):
            if all(shlex.quote(part) == part for part in parts if part):
                return typed.join(parts)
    return shlex.quote(word)


def shown_command(args: list, values: dict) -> str:
    """The `$` line of a command of the CLI, as a person types it at the root of the checkout."""
    return "$ " + " ".join([*TYPED_CLI, *(typed_word(word, values) for word in args)])


def shown_program(action: dict, values: dict) -> str:
    """The `$` line of a program the script starts, by its path in the checkout and with its interpreter: the hook's own, any other
    through `uv run python`."""
    interpreter = action.get("interpreter", TYPED_PYTHON)
    return "$ " + " ".join([*interpreter, action["program"], *(typed_word(word, values) for word in resolved(action["args"], values))])


def program_argv(action: dict, values: dict) -> list:
    """The argument list of a program: the hook with its fragment's interpreter, any other with this script's Python and `-B`."""
    interpreter = action.get("interpreter", [sys.executable, "-B"])
    return [*interpreter, str(CHECKOUT / action["program"]), *resolved(action["args"], values)]


def quoted(text: str, say) -> None:
    for line in text.splitlines():
        say(f"  | {line}")


def show(action: dict, values: dict, work: Path, say) -> None:
    """Carry out an action that starts no process: copy a folder or write a file, each inside the work folder, or print the files
    an action shows, read only."""
    if "write" in action or "copy" in action:
        target = Path(resolved(action.get("write") or action["to"], values))
        if not inside(target, work):
            raise Failed(f"{target} is outside the work folder")
        if "copy" in action:
            shutil.copytree(resolved(action["copy"], values), target)
            say(f"  | {len(list(target.rglob('*')))} files and folders copied")
            return
        target.write_text(action["text"] + "\n", encoding="utf-8")
        quoted(action["text"], say)
        return
    if action["show"] == "folders":
        for folder in action["paths"]:
            say(f"  {resolved(folder, values)}:")
            for entry in sorted(os.listdir(resolved(folder, values))):
                say(f"  | {entry}")
        return
    if action["show"] == "files":
        for entry in sorted(os.listdir(resolved(action["path"], values))):
            say(f"  | {entry}")
        return
    for name in sorted(glob.glob(resolved(action["path"], values))):
        lines = Path(name).read_text(encoding="utf-8").splitlines()
        say(f"  {name}:")
        quoted("\n".join(lines[: action["lines"]] if action["show"] == "head" else lines), say)


def kept_files(name: str, args: list, code: int, out: str, err: str, work: Path) -> None:
    """Write what a kept process gave into the work folder's kept/, as it printed it; a decide also keeps its argument list."""
    folder = work / KEPT
    folder.mkdir(exist_ok=True)
    (folder / f"{name}.exit").write_text(f"{code}\n", encoding="utf-8")
    (folder / f"{name}.out").write_text(out, encoding="utf-8")
    (folder / f"{name}.err").write_text(err, encoding="utf-8")
    if args[0] == "decide":
        (folder / f"{name}.args").write_text(json.dumps({"arguments": args}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def process(action: dict, values: dict, work: Path, start, say) -> None:
    """Start one command of the CLI or one other program, print what it gave and what the step expects of it; raise Failed at the
    first that does not hold."""
    if "cli" in action:
        args = [resolved(part, values) for part in action["cli"]]
        say(shown_command(args, values))
        argv, env, text = [*CLI, *args], without_live_key(), None
    else:
        args = resolved(action["args"], values)
        say(shown_program(action, values))
        argv, text = program_argv(action, values), resolved(action.get("input"), values)
        env = {**without_live_key(), **{name: resolved(value, values) for name, value in action.get("environment", {}).items()}}
        if "interpreter" in action:
            env["PYTHONDONTWRITEBYTECODE"] = "1"
        for line in (text or "").splitlines():
            say(f"  stdin | {line}")
    try:
        code, out, err = start(argv, env, str(work), text)
    except OSError as error:
        raise Failed(f"{argv[0]} could not be started: {error}") from error
    if "kept" in action:
        kept_files(action["kept"], args, code, out, err, work)
    payload = None
    if "--json" in args:
        try:
            payload = json.loads(out)
        except ValueError:
            say(f"  (stdout is not one JSON object: {out[:200]!r})")
        for path in action.get("print", []):
            say(f"  {path} = {shown(value_at(payload, path))}")
    else:
        quoted(out, say)
    for line in err.splitlines():
        say(f"  stderr | {line}")
    for key, expected, found in expectations(action["expect"], code, payload, values, out):
        held = same(found, expected) and found is not MISSING
        # `same` holds two values that differ only when a float differs past its 12th significant digit: the line names that rule.
        verdict = (f"held (equal to {SIGNIFICANT_DIGITS} significant digits)" if found != expected else "held") if held else "did not hold"
        say(f"  expected {key} {shown(expected)}: found {shown(found)}: {verdict}")
        if not held:
            raise Failed(f"key {key}: expected {shown(expected)}, found {shown(found)}")
    for name, path in action.get("capture", {}).items():
        value = value_at(payload, path)
        if value is MISSING or isinstance(value, bool) or not isinstance(value, (str, int)):
            raise Failed(f"key {path}: expected an id or a Write sequence to capture as {name}, found {shown(value)}")
        values[name] = value


def run(work, *, start=start_process, out=None, steps=None) -> Outcome:
    """Run the step list in `work`, printing the transcript to `out`; each process is started by `start(argv, env, cwd, text)`."""
    work, steps = Path(work), STEPS if steps is None else steps
    out = sys.stdout if out is None else out

    def say(line: str) -> None:
        print(line, file=out, flush=True)

    work.mkdir(parents=True, exist_ok=True)
    values, passed = folders_of(work), 0
    say(
        f"The demonstration of Hypotrail in {work}: {len(steps)} steps, a first Bike Study, a second on a copy of the Workloads, then "
        f"Chinook, with no live model call and no network. On each $ line, $WORK is {work} and $CHECKOUT is {CHECKOUT}. A float is "
        "compared to 12 significant digits, so a last digit may differ from one machine to another."
    )
    for step in steps:
        say("")
        say(f"== {step['id']} · {step['title']}")
        say(f"What it shows: {step['shows']}")
        say(f"Why: {step['why']}")
        try:
            for action in step["actions"]:
                started = processes(action)
                if "cli" not in action and "program" not in action:
                    say(f"script: {shown_action(action, values)}")
                    if not started:
                        show(action, values, work, say)
                for each in started:
                    process(each, values, work, start, say)
        except Failed as failure:
            say(f"FAILED: step {step['id']}, {failure}")
            later = len(steps) - passed - 1
            say(f"{passed} of {len(steps)} steps gave what they expect; {step['id']} did not, and the {later} steps after it were not run.")
            return Outcome(1, {name: value for name, value in values.items() if name not in FOLDERS}, passed)
        passed += 1
        say(f"{step['id']} gave what it expects.")
    say("")
    say(f"{passed} of {len(steps)} steps gave what they expect.")
    return Outcome(0, {name: value for name, value in values.items() if name not in FOLDERS}, passed)


def refusal(work: Path) -> str | None:
    """Why a work folder is refused, or None."""
    if inside(work, CHECKOUT):
        return f"refused: {work} is inside the checkout {CHECKOUT}. The work folder is made outside it, so that no file of the checkout changes. Nothing was written."
    if work.exists() and (not work.is_dir() or any(work.iterdir())):
        return f"refused: {work} exists and is not an empty folder. The demonstration starts from a Study that does not exist. Nothing was written."
    return None


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    made.add_argument("--work", required=True, metavar="DIR", help="the work folder: new, or empty, and outside the checkout")
    return made


def main(argv=None) -> int:
    work = Path(parser().parse_args(argv).work)
    reason = refusal(work)
    if reason is not None:
        print(reason, file=sys.stderr)
        return 2
    return run(work.resolve()).code


if __name__ == "__main__":
    sys.exit(main())
