"""Run the frozen demonstration of Hypotrail in a work folder outside the checkout, and check each step.

Standard library only; it imports nothing of Hypotrail and is not a command of the CLI. Run it with the Python of the
checkout:

    uv run python docs/demo/demonstration.py --work DIR

DIR is a new or empty folder outside the checkout: it receives the Studies, the report pages and the population file. The
steps are those of section 18 of the teaching page that need no person, Bike then Chinook. For each step the script prints
what it shows and why, starts each command as a process of its own, as a person would, prints what the command gave, and
checks what the step expects of it. It stops at the first expectation that does not hold. Exit 0 when every step gave what
it expects, 1 when one did not, 2 when DIR is refused.

No command calls a live model or the network: `run agent` is given the Mode `scripted_fixture` only, and each process is
started without the live key `HYPOTRAIL_ANTHROPIC_API_KEY` in its environment. A command of the CLI is started as
`python -B -m hypotrail`, with the Python that runs this script; `-B` keeps Python from writing its bytecode cache into the
checkout, so that the script writes only inside DIR.
"""

import argparse
import glob
import json
import os
import re
import shlex
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
# A template names a folder as `{work}` or `{checkout}`, and a value captured from an earlier command by the capture's name.
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
FOLDERS = ("work", "checkout")
PATH_PART = re.compile(r"\.?([A-Za-z_][A-Za-z0-9_]*)|\[(-?\d+)\]")

BIKE = "{work}/l1-bike"
CHINOOK = "{work}/l1-chinook"
COUNTS_182 = {"produced": 182, "failed": 0, "missing": 0}

# The step list. Each step has its id in section 18, its title, what it shows and why, and its actions. An action is a command
# of the CLI (`cli`, its argument list), a file of the work folder written (`write`), or files shown, read only (`show`). A
# command may capture values of its `--json` object for the commands after it (`capture`: name -> key path), print values of
# it (`print`), and expects its exit code, a refusal's code and stage, and the values at named key paths (`expect`).
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
            "recorded; then the first request sent again, which gives the first Attempt's id and Observation set ID with replayed true."
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
            "182 of 182 paired Items; then the Comparison read back from the Study, with its exact delta, the warning and three "
            "limitations; then the first lines of paired_deltas.csv."
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
                        "len(comparisons[-1].limitations)": 3,
                    },
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
                "print": ["attempt.attempt_id", "attempt.mode", "attempt.item_counts"],
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
    """An expectation that does not hold, or a capture that cannot be read: the run stops."""


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


def value_at(payload, path: str):
    """The value at a key path such as `assessment.metrics[0].value`, `len(freeze_records)` for the number of entries, or MISSING."""
    counted = path.startswith("len(") and path.endswith(")")
    value = payload
    for name, index in PATH_PART.findall(path[4:-1] if counted else path):
        try:
            value = value[name] if name else value[int(index)]
        except (KeyError, IndexError, TypeError):
            return MISSING
    if counted:
        return len(value) if isinstance(value, (list, dict)) else MISSING
    return value


def resolved(template, values: dict):
    """A template with each placeholder replaced by its value; any other value as it is."""
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


def expectation_keys(expect: dict) -> list:
    """The key of each expectation, in the order the script checks them: the exit code, a refusal's code and stage, the key paths."""
    keys = ["exit code"]
    if "refusal" in expect:
        keys += ["error.code", "error.stage"]
    return keys + list(expect.get("values", {}))


def expectations(expect: dict, code: int, payload, values: dict) -> list:
    """(key, expected, found) of each expectation of a command."""
    found = [("exit code", expect["exit"], code)]
    if "refusal" in expect:
        found += [("error.code", expect["refusal"]["code"], value_at(payload, "error.code"))]
        found += [("error.stage", expect["refusal"]["stage"], value_at(payload, "error.stage"))]
    for path, expected in expect.get("values", {}).items():
        found.append((path, resolved(expected, values), value_at(payload, path)))
    return found


def start_process(argv, env, cwd):
    """(exit code, stdout, stderr) of one process, started with no input."""
    done = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
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
    if action["show"] == "head":
        return f"show the first {action['lines']} lines of {resolved(action['path'], values)}"
    if action["show"] == "folders":
        return "show the folders " + " ".join(resolved(path, values) for path in action["paths"])
    if action["show"] == "files":
        return f"show the files of {resolved(action['path'], values)}"
    return f"show {resolved(action['path'], values)}"


def quoted(text: str, say) -> None:
    for line in text.splitlines():
        say(f"  | {line}")


def show(action: dict, values: dict, work: Path, say) -> None:
    """Print the files an action shows, read only; a written file must lie in the work folder."""
    if "write" in action:
        target = Path(resolved(action["write"], values))
        if not inside(target, work):
            raise Failed(f"{target} is outside the work folder")
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


def command(action: dict, values: dict, work: Path, start, say) -> None:
    """Start one command of the CLI, print what it gave and what the step expects of it; raise Failed at the first that does not hold."""
    args = [resolved(part, values) for part in action["cli"]]
    say(f"$ python -m hypotrail {shlex.join(args)}")
    code, out, err = start([*CLI, *args], without_live_key(), str(work))
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
    for key, expected, found in expectations(action["expect"], code, payload, values):
        held = same(found, expected) and found is not MISSING
        say(f"  expected {key} {shown(expected)}: found {shown(found)}: {'held' if held else 'did not hold'}")
        if not held:
            raise Failed(f"key {key}: expected {shown(expected)}, found {shown(found)}")
    for name, path in action.get("capture", {}).items():
        value = value_at(payload, path)
        if value is MISSING or not isinstance(value, str):
            raise Failed(f"key {path}: expected an id to capture as {name}, found {shown(value)}")
        values[name] = value


def run(work, *, start=start_process, out=None, steps=None) -> Outcome:
    """Run the step list in `work`, printing the transcript to `out`; each command is started by `start(argv, env, cwd)`."""
    work, steps = Path(work), STEPS if steps is None else steps
    out = sys.stdout if out is None else out

    def say(line: str) -> None:
        print(line, file=out, flush=True)

    work.mkdir(parents=True, exist_ok=True)
    values, passed = folders_of(work), 0
    say(f"The demonstration of Hypotrail in {work}: {len(steps)} steps, Bike then Chinook, with no live model call and no network.")
    for step in steps:
        say("")
        say(f"== {step['id']} · {step['title']}")
        say(f"What it shows: {step['shows']}")
        say(f"Why: {step['why']}")
        try:
            for action in step["actions"]:
                if "cli" in action:
                    command(action, values, work, start, say)
                else:
                    say(f"$ {shown_action(action, values)}")
                    show(action, values, work, say)
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
