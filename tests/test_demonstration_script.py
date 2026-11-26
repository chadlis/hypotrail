"""The frozen demonstration's script (`docs/demo/demonstration.py`): its bounds, its step list, its transcript and its own checks.

The whole step list is run once per session in process (`demonstration_run`, in `conftest.py`); only the tests of the script started as a person
starts it start it as a process, once.
"""

import ast
import copy
import json
import math
import os
import shlex
import subprocess
import sys
from itertools import zip_longest
from pathlib import Path

import pytest
from _demonstration_helpers import LIVE_KEY, ROOT, SCRIPT, commands, demonstration, processes, run_in_process, value_at

MODULE = demonstration()
STEPS = MODULE.STEPS

# The steps of the demonstration, in the order of chadlis/hypotrail#218, "The demonstration, as this slice freezes it": L1.1 to L1.7 on
# the first Bike Study, then the steps of the second Bike Study in the order of chadlis/hypotrail#221, "Words of this ticket", then L1.8
# on the Chinook Study.
DEMO_IDS = [
    "L1.1", "L1.2", "L1.3", "L1.4", "L1.5", "L1.6", "L1.7",
    "A4", "A5", "task 1", "task 2", "task 3", "C10", "task 4", "task 5", "task 6.1", "task 6.2", "C5-check", "COMPARE", "S1", "C8",
    "DEV", "REPORT",
    "L1.8",
]

# Section 18 of `pages/de-zero-a-la-demo.html`, chadlis/hypotrail-learning at commit 164aa3a, steps L1.1 to L1.8: each step's commands
# as the page writes them, run at the root of the checkout, but the ones that only find an id (the `status ... | python -c` lines whose
# value becomes a shell variable). A `status --json | python -c` line that prints what it read is kept as its `status` command. The
# page's `runs/` is the work folder; a shell variable is written `$NAME`, the name of the script's capture that holds that id. The
# References ID that the page writes as the literal `references-7520d791bfe31924` in L1.4 and L1.7 is the one `init` printed, written
# `$L1_BIKE_REFS`.
#
# The steps of the second Bike Study, from A4 to the C5 check of the same section: the page's `../demo-examples` is the Workload copy in the
# work folder, and its `runs/bike` the second Bike Study. The copy is "given as `--examples-dir` to the commands that take it (`init`,
# `run ml`, `run agent`, `import agent`, `data verify`), and to no others" (chadlis/hypotrail#221, "Words of this ticket"), so the page's
# `--examples-dir` of `assess` and `compare`, which read it only for public_check Items, is left out. A `decide` is written as the panel's
# bridge starts it, "each option joined to its value by `=`" (chadlis/hypotrail#221, "Acceptance criteria"); the page's request id at task
# 3 is a new UUID of the walk, the script's a fixed text. Section 18 has neither COMPARE nor DEV, and leaves the hook of C10 to Claude Code
# and the `decide` of S1 and of C8 to the panel and to Claude Code: those commands are written here from chadlis/hypotrail#221,
# "Acceptance criteria", with the `status` read after COMPARE, C8 and DEV that shows what each wrote.
KEPT_LOG = "docs/handbook/traces/run-agent-live-plain/inspect/2026-11-20T21-46-56-00-00_chinook-plain_e5SoHDfMBV3vBUjsjaQWVu.eval"
POPULATION = '{"episodes": [{"case_id": "D03", "repeat": 0}, {"case_id": "D05", "repeat": 0}]}'
QUESTION = "Which Configuration do we keep after this Comparison?"
STATUS_BIKE = ("hypotrail", "status", "--study", "runs/bike", "--json")


def decide_18(option, artifact, request_id, read_sequence, *source, author="human"):
    return (
        "hypotrail", "decide", "--study=runs/bike", f"--question={QUESTION}", f"--option={option}", f"--author={author}", *source,
        f"--artifact={artifact}", f"--request-id={request_id}", f"--read-sequence={read_sequence}", "--json",
    )


def task_6(edit, refs) -> list:
    return [
        ("python", "docs/demo/edit_copy.py", "--copy", "../demo-examples", "--edit", edit),
        ("hypotrail", "data", "verify", "--examples-dir", "../demo-examples"),
        ("hypotrail", "init", "--study", "runs/bike", "--new-revision", "--examples-dir", "../demo-examples"),
        ("hypotrail", "assess", "--study", "runs/bike", "--observations", "$L2_OBS_SEASONAL", "--scorer", "regression_mae_v1", "--references", refs),
        ("hypotrail", "assess", "--study", "runs/bike", "--observations", "$L2_OBS_RIDGE", "--scorer", "regression_mae_v1", "--references", refs),
        STATUS_BIKE,
    ]


SECTION_18 = {
    "L1.1": [
        ("hypotrail", "--help"),
        ("ls", "examples", "examples/bike_day", "examples/chinook"),
    ],
    "L1.2": [
        ("hypotrail", "init", "--workload", "bike_day", "--study", "runs/l1-bike"),
        ("hypotrail", "init", "--workload", "bike_day", "--study", "runs/l1-bike"),
        ("hypotrail", "status", "--study", "runs/l1-bike", "--json"),
    ],
    "L1.3": [
        ("hypotrail", "run", "ml", "--study", "runs/l1-bike", "--config", "seasonal_7", "--partition", "dev", "--request-id", "l1-seasonal"),
        ("hypotrail", "run", "ml", "--study", "runs/l1-bike", "--config", "ridge_v1", "--partition", "dev", "--request-id", "l1-ridge"),
        ("hypotrail", "run", "ml", "--study", "runs/l1-bike", "--config", "seasonal_7", "--partition", "dev", "--request-id", "l1-seasonal"),
    ],
    "L1.4": [
        ("hypotrail", "assess", "--study", "runs/l1-bike", "--observations", "$L1_OBS_SEASONAL", "--scorer", "regression_mae_v1", "--references", "$L1_BIKE_REFS"),
        ("hypotrail", "assess", "--study", "runs/l1-bike", "--observations", "$L1_OBS_RIDGE", "--scorer", "regression_mae_v1", "--references", "$L1_BIKE_REFS"),
    ],
    "L1.5": [
        ("hypotrail", "compare", "--study", "runs/l1-bike", "--control", "$L1_A_SEASONAL", "--candidate", "$L1_A_RIDGE"),
        ("hypotrail", "status", "--study", "runs/l1-bike", "--json"),
        ("head", "-3", "runs/l1-bike/comparisons/*/paired_deltas.csv"),
    ],
    "L1.6": [
        ("hypotrail", "status", "--study", "runs/l1-bike"),
        ("hypotrail", "report", "--study", "runs/l1-bike", "--out", "runs/l1-bike-report.html"),
    ],
    "L1.7": [
        ("hypotrail", "run", "ml", "--study", "runs/l1-bike", "--config", "seasonal_7", "--partition", "public_check", "--request-id", "l1-check"),
        ("hypotrail", "status", "--study", "runs/l1-bike"),
        ("hypotrail", "assess", "--study", "runs/l1-bike", "--observations", "$L1_OBS_CHECK", "--scorer", "regression_mae_v1", "--references", "$L1_BIKE_REFS"),
        ("hypotrail", "status", "--study", "runs/l1-bike", "--json"),
        ("hypotrail", "report", "--study", "runs/l1-bike", "--out", "runs/l1-bike-report.html"),
        ("hypotrail", "status", "--study", "runs/l1-bike"),
        ("ls", "runs/l1-bike/exposures"),
    ],
    "L1.8": [
        ("hypotrail", "init", "--workload", "chinook", "--study", "runs/l1-chinook"),
        ("hypotrail", "run", "agent", "--study", "runs/l1-chinook", "--mode", "scripted_fixture", "--config", "plain", "--request-id", "l1-fixture"),
        ("printf", "%s\\n", POPULATION, ">", "runs/l1-population.json"),
        ("hypotrail", "import", "agent", "--study", "runs/l1-chinook", "--source", KEPT_LOG, "--population", "runs/l1-population.json", "--request-id", "l1-import"),
        ("hypotrail", "assess", "--study", "runs/l1-chinook", "--observations", "$L1_OBS_IMPORT", "--scorer", "chinook_contract_v1", "--references", "$L1_CHINOOK_REFS"),
        ("cat", "runs/l1-chinook/assessments/*/per_item.csv"),
        ("hypotrail", "report", "--study", "runs/l1-chinook", "--out", "runs/l1-chinook-report.html"),
    ],
    "A4": [
        ("cp", "-r", "examples", "../demo-examples"),
        ("hypotrail", "data", "verify", "--examples-dir", "../demo-examples"),
    ],
    "A5": [
        ("hypotrail", "init", "--workload", "bike_day", "--study", "runs/bike", "--examples-dir", "../demo-examples"),
        ("hypotrail", "run", "ml", "--study", "runs/bike", "--config", "seasonal_7", "--partition", "dev", "--request-id", "demo-seasonal", "--examples-dir", "../demo-examples"),
        ("hypotrail", "run", "ml", "--study", "runs/bike", "--config", "ridge_v1", "--partition", "dev", "--request-id", "demo-ridge", "--examples-dir", "../demo-examples"),
        ("hypotrail", "assess", "--study", "runs/bike", "--observations", "$L2_OBS_SEASONAL", "--scorer", "regression_mae_v1", "--references", "$L2_REFS"),
        ("hypotrail", "assess", "--study", "runs/bike", "--observations", "$L2_OBS_RIDGE", "--scorer", "regression_mae_v1", "--references", "$L2_REFS"),
        ("hypotrail", "compare", "--study", "runs/bike", "--control", "$L2_A_SEASONAL", "--candidate", "$L2_A_RIDGE"),
    ],
    "task 1": [STATUS_BIKE],
    "task 2": [STATUS_BIKE],
    "task 3": [decide_18("Keep the Control", "$L2_COMPARISON", "demo-task-3", 12), STATUS_BIKE],
    "C10": [("python3", "-I", "clients/claude-code/hypotrail_study_hook.py", "--study", "runs/bike")],
    "task 4": [STATUS_BIKE],
    "task 5": [STATUS_BIKE],
    "task 6.1": task_6("6.1", "$L2_REFS_61"),
    "task 6.2": task_6("6.2", "$L2_REFS_62"),
    "C5-check": [STATUS_BIKE],
    "COMPARE": [("hypotrail", "compare", "--study", "runs/bike", "--control", "$L2_A_SEASONAL_62", "--candidate", "$L2_A_RIDGE_62"), STATUS_BIKE],
    "S1": [
        ("hypotrail", "run", "ml", "--study", "runs/bike", "--config", "seasonal_7", "--partition", "dev", "--request-id", "demo-s1", "--examples-dir", "../demo-examples"),
        STATUS_BIKE,
        decide_18("Keep the Control", "$L2_COMPARISON_62", "demo-s1-decide", 28),
    ],
    "C8": [
        decide_18("Keep the Control", "$L2_COMPARISON_62", "demo-c8", "$L2_READ_AFTER_S1", f"--source={MODULE.PROXY_SOURCE}", author="proxy"),
        STATUS_BIKE,
    ],
    "DEV": [
        (
            "hypotrail", "deviation", "--study", "runs/bike", "--text", MODULE.DEVIATION_TEXT, "--author", "human", "--artifact", "$L2_REFS_62",
            "--request-id", "demo-dev", "--read-sequence", "$L2_READ_AFTER_C8",
        ),
        STATUS_BIKE,
    ],
    "REPORT": [("hypotrail", "report", "--study", "runs/bike", "--out", "runs/bike-report.html")],
}


def as_section_18(text: str) -> str:
    """A template of the script written as section 18 writes it: the Workload copy as `../demo-examples`, the work folder as `runs/`, the
    checkout as its root, a capture as `$NAME`."""
    text = text.replace("{work}/demo-examples", "../demo-examples").replace("{work}/", "runs/").replace("{checkout}/", "")
    return MODULE.PLACEHOLDER.sub(lambda match: f"${match[1]}", text)


def section_18_form(action) -> tuple | None:
    """One action of the step list as section 18 writes it; None for the two reads of a kept state, which are the reads kept for the
    client's tests and no command of section 18. `--json` only chooses the form of what a command prints, so it is left out on both sides
    of the comparison."""
    if "keep" in action:
        return None
    if "cli" in action:
        return ("hypotrail", *(as_section_18(part) for part in action["cli"] if part != "--json"))
    if "program" in action:
        return (*action.get("interpreter", ["python"]), action["program"], *(as_section_18(part) for part in action["args"]))
    if "copy" in action:
        return ("cp", "-r", as_section_18(action["copy"]), as_section_18(action["to"]))
    if "write" in action:
        return ("printf", "%s\\n", action["text"], ">", as_section_18(action["write"]))
    shown = action["show"]
    if shown == "folders":
        return ("ls", *(as_section_18(path) for path in action["paths"]))
    if shown == "files":
        return ("ls", as_section_18(action["path"]))
    if shown == "head":
        return ("head", f"-{action['lines']}", as_section_18(action["path"]))
    if shown == "file":
        return ("cat", as_section_18(action["path"]))
    raise AssertionError(f"an action of no known kind: {action}")


def step(step_id) -> dict:
    [found] = [each for each in STEPS if each["id"] == step_id]
    return found


def cli_actions(step_id) -> list:
    return [action for action in step(step_id)["actions"] if "cli" in action]


def args_of(action) -> list:
    return [part for part in action["cli"] if part != "--json"]


# --- the script's bounds: its imports, the folders it refuses, the files it leaves --------------------------------------------------------

# The modules the script may import: each is in the standard library, and none reaches the network or a model.
ALLOWED_IMPORTS = {"argparse", "collections", "glob", "json", "os", "pathlib", "re", "shlex", "shutil", "subprocess", "sys"}
NEVER_ALLOWED = ("socket", "ssl", "http", "urllib", "requests", "anthropic", "inspect_ai", "hypotrail")


def imported_modules(source: str) -> list:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append("." if node.level else node.module.split(".")[0])
    return found


def test_the_script_imports_only_listed_standard_library_modules_and_the_list_holds_none_that_reaches_the_network_or_a_model():
    assert ALLOWED_IMPORTS <= sys.stdlib_module_names
    for name in NEVER_ALLOWED:
        assert name not in ALLOWED_IMPORTS, name
    imported = imported_modules(SCRIPT.read_text(encoding="utf-8"))
    assert imported
    for name in imported:
        assert name in ALLOWED_IMPORTS, name


def run_script(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)], capture_output=True, text=True, **kwargs)


def tracked_files() -> dict:
    """{path: (size, modification time)} of each file `git ls-files` lists in the checkout."""
    listing = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True)
    found = {}
    for name in sorted(name for name in listing.stdout.split("\0") if name):
        path = ROOT / name
        found[name] = (path.stat().st_size, path.stat().st_mtime_ns) if path.is_file() else None
    return found


def _inside_the_checkout(tmp_path: Path) -> Path:
    return ROOT / "runs" / f"demonstration-refused-{tmp_path.name}"


def _not_empty(tmp_path: Path) -> Path:
    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "kept.txt").write_text("a file a person left here\n", encoding="utf-8")
    return folder


REFUSED_FOLDERS = {"a folder inside the checkout": _inside_the_checkout, "a folder that exists and is not empty": _not_empty}


def folder_state(folder: Path):
    if not folder.exists():
        return None
    return sorted((path.relative_to(folder).as_posix(), path.read_bytes()) for path in folder.rglob("*") if path.is_file())


@pytest.mark.parametrize("case", sorted(REFUSED_FOLDERS))
def test_a_work_folder_inside_the_checkout_or_not_empty_is_refused_with_exit_2_and_one_line_on_stderr_and_nothing_is_written(case, tmp_path):
    folder = REFUSED_FOLDERS[case](tmp_path)
    before, folder_before = tracked_files(), folder_state(folder)
    result = run_script("--work", folder)
    assert result.returncode == 2, (result.stdout[-2000:], result.stderr)
    assert len(result.stderr.splitlines()) == 1 and result.stdout == "", (result.stdout[-2000:], result.stderr)
    assert folder_state(folder) == folder_before
    assert tracked_files() == before


def checkout_files() -> dict:
    """{path: (size, modification time)} of every file under the checkout but git's own folder `.git`, which the CLI's `git status`
    may refresh and which the script does not write."""
    found = {}
    for top, folders, files in os.walk(ROOT):
        if Path(top) == ROOT:
            folders[:] = [name for name in folders if name != ".git"]
        for name in files:
            path = Path(top) / name
            if path.is_file() and not path.is_symlink():
                found[path.relative_to(ROOT).as_posix()] = (path.stat().st_size, path.stat().st_mtime_ns)
    return found


@pytest.fixture(scope="module")
def process_run(tmp_path_factory):
    """The script run as a person runs it, as a process, with a new work folder outside the checkout: the result and the checkout's
    files listed before and after."""
    work = tmp_path_factory.mktemp("demonstration-process") / "work"
    assert ROOT not in work.resolve().parents
    environment = {name: value for name, value in os.environ.items() if name != LIVE_KEY}
    before = checkout_files()
    result = run_script("--work", work, env=environment, timeout=600)
    return result, before, checkout_files()


def test_the_script_run_as_a_process_with_a_new_work_folder_outside_the_checkout_exits_0_and_its_last_line_counts_every_step(process_run):
    result, _, _ = process_run
    assert result.returncode == 0, (result.stdout[-4000:], result.stderr[-2000:])
    assert result.stdout.splitlines()[-1] == f"{len(STEPS)} of {len(STEPS)} steps gave what they expect."


def test_the_script_that_gives_every_step_leaves_every_file_of_the_checkout_as_it_was(process_run):
    result, before, after = process_run
    assert result.returncode == 0, result.stderr[-2000:]
    for path in sorted(set(before) | set(after)):
        assert before.get(path) == after.get(path), path


# --- no live model call, no network -------------------------------------------------------------------------------------------------------


def live_or_network(args) -> str | None:
    """What makes a command of the step list a live model call or a network fetch, or None."""
    for part in args:
        if "llm_live" in part:
            return part
    if args[:1] == ["spike"] or "fetch" in args:
        return " ".join(args[:2])
    if args[:2] == ["run", "agent"] and args[args.index("--mode") + 1] != "scripted_fixture":
        return args[args.index("--mode") + 1]
    return None


def test_no_command_of_the_step_list_calls_a_live_model_or_fetches_and_run_agent_is_given_only_scripted_fixture():
    listed = commands(STEPS)
    assert listed
    for step_id, action in listed:
        assert live_or_network(action["cli"]) is None, (step_id, action["cli"])


def test_each_process_the_script_starts_gets_an_environment_without_the_live_key(demonstration_run):
    assert demonstration_run.key_in_environment and demonstration_run.calls
    for call in demonstration_run.calls:
        assert (LIVE_KEY in call["env"]) is False, call["args"]


# --- the steps, their commands and what each expects --------------------------------------------------------------------------------------


def test_the_ids_of_the_step_list_are_the_ids_of_the_demonstration_in_order():
    ids = [each["id"] for each in STEPS]
    for at, (found, expected) in enumerate(zip_longest(ids, DEMO_IDS)):
        assert found == expected, (at, ids)


def test_the_commands_of_each_step_are_those_of_its_step_in_section_18_but_the_ones_that_only_find_an_id():
    for step_id in sorted(set(SECTION_18) | {each["id"] for each in STEPS}):
        script = [section_18_form(action) for action in step(step_id)["actions"]] if step_id in [each["id"] for each in STEPS] else []
        script = [each for each in script if each is not None]
        written = [tuple(part for part in each if part != "--json") for each in SECTION_18.get(step_id, [])]
        for at, (found, wrote) in enumerate(zip_longest(script, written)):
            assert found == wrote, (step_id, at)


def test_l1_2_holds_the_second_init_and_expects_its_refusal_study_exists_with_exit_2():
    inits = [action for action in cli_actions("L1.2") if action["cli"][0] == "init"]
    assert len(inits) == 2 and args_of(inits[0]) == args_of(inits[1])
    assert inits[1]["expect"]["exit"] == 2
    assert inits[1]["expect"]["refusal"]["code"] == "STUDY_EXISTS"


def test_l1_3_holds_the_request_sent_again_and_expects_the_first_attempts_id_and_replayed_true():
    first, _, again = cli_actions("L1.3")
    assert args_of(first) == args_of(again)
    [(name, path)] = [(name, path) for name, path in first["capture"].items() if path == "attempt.attempt_id"]
    assert again["expect"]["values"]["attempt.attempt_id"] == "{" + name + "}"
    assert again["expect"]["values"]["replayed"] is True


def test_l1_7_expects_no_exposure_after_the_attempt_one_freeze_record_and_one_exposure_after_its_assessment_and_a_second_after_the_report():
    actions = cli_actions("L1.7")
    kinds = [action["cli"][0] for action in actions]
    assert kinds == ["run", "status", "assess", "status", "report", "status"]
    after_attempt, after_assessment, after_report = actions[1], actions[3], actions[5]
    assert after_attempt["expect"]["values"]["exposures.recorded_in_this_study"] == 0
    assert after_assessment["expect"]["values"]["len(freeze_records)"] == 1
    assert after_assessment["expect"]["values"]["exposures.recorded_in_this_study"] == 1
    assert after_report["expect"]["values"]["exposures.recorded_in_this_study"] == 2


def test_l1_8_expects_5_produced_1_failed_1_missing_of_the_scripted_fixture_attempt_and_says_the_scenarios_are_written_to_give_them():
    [fixture] = [action for action in cli_actions("L1.8") if action["cli"][:2] == ["run", "agent"]]
    assert fixture["expect"]["values"]["attempt.item_counts"] == {"produced": 5, "failed": 1, "missing": 1}
    assert "the counts the Scenarios are written to give" in step("L1.8")["why"]


# --- the commands chadlis/hypotrail#221 names for the second Bike Study -----------------------------------------------------------------

CONTRACT = json.loads((ROOT / "clients" / "vscode" / "contract.json").read_text(encoding="utf-8"))
FRAGMENT = json.loads((ROOT / "clients" / "claude-code" / "settings-fragment.json").read_text(encoding="utf-8"))


def options_of(args) -> list:
    """(name, value) of each option of a `decide` argument list, each joined to its value by `=`; `--json` with no value."""
    assert args[0] == "decide" and args[-1] == "--json", args
    pairs = [tuple(part.split("=", 1)) for part in args[1:-1]]
    assert all(len(pair) == 2 and pair[0].startswith("--") for pair in pairs), args
    return [*pairs, ("--json", None)]


def decide_of(step_id) -> dict:
    [found] = [action for action in cli_actions(step_id) if action["cli"][0] == "decide"]
    return found


def capture_of(name) -> tuple:
    """(step id, process) of the process that captures NAME."""
    [found] = [(step_id, action) for step_id, action in commands(STEPS) if name in action.get("capture", {})]
    return found


def test_task_3_records_the_decision_with_the_argument_list_the_panels_bridge_builds():
    options = options_of(decide_of("task 3")["cli"])
    assert [name for name, _ in options] == [name for name in CONTRACT["decide_options"] if name != "--source"]
    values = dict(options)
    assert (values["--study"], values["--author"], values["--read-sequence"]) == ("{work}/bike", "human", "12")
    assert [value for name, value in options if name == "--artifact"] == ["{L2_COMPARISON}"]
    assert capture_of("L2_COMPARISON")[0] == "A5" and capture_of("L2_COMPARISON")[1]["cli"][0] == "compare" and values["--request-id"]


def test_c10_runs_the_hooks_program_with_the_flags_of_the_settings_fragment_on_the_second_bike_study_its_input_on_stdin():
    [hook] = [action for action in step("C10")["actions"] if "program" in action]
    [entry] = FRAGMENT["hooks"]["UserPromptSubmit"]
    words = shlex.split(entry["hooks"][0]["command"])
    assert [*hook["interpreter"], "$CLAUDE_PROJECT_DIR/" + hook["program"], *hook["args"]] == [*words[:4], "{work}/bike"]
    assert hook["environment"] == {"CLAUDE_PROJECT_DIR": "{checkout}"} and json.loads(hook["input"])["hook_event_name"] == "UserPromptSubmit"


def test_task_4_is_a_status_json_read_by_a_process_of_its_own():
    assert [action["cli"] for action in step("task 4")["actions"]] == [["status", "--study", "{work}/bike", "--json"]]


def test_s1_is_a_run_ml_of_seasonal_7_on_dev_then_a_decide_built_as_task_3s_with_read_sequence_28():
    actions = cli_actions("S1")
    run_ml = actions[0]["cli"]
    assert run_ml[:2] == ["run", "ml"] and (run_ml[run_ml.index("--config") + 1], run_ml[run_ml.index("--partition") + 1]) == ("seasonal_7", "dev")
    s1, task_3 = options_of(decide_of("S1")["cli"]), options_of(decide_of("task 3")["cli"])
    assert [name for name, _ in s1] == [name for name, _ in task_3] and dict(s1)["--read-sequence"] == "28"
    assert actions.index(decide_of("S1")) > 0


def test_c8_is_a_proxy_decide_whose_source_names_the_rule_whose_option_the_rule_gives_and_whose_read_sequence_is_read_after_s1(demonstration_run):
    options = dict(options_of(decide_of("C8")["cli"]))
    assert (options["--author"], "keep the Configuration with the lowest MAE" in options["--source"]) == ("proxy", True)
    run = demonstration_run
    comparison = run.outcome.captures["L2_COMPARISON_62"]
    assert options["--artifact"] == "{L2_COMPARISON_62}"
    [status] = [call["payload"] for (_, action), call in zip(processes(STEPS), run.calls) if "L2_READ_AFTER_S1" in action.get("capture", {})]
    [compared] = [each for each in status["comparisons"] if each["comparison_id"] == comparison]
    mae = {each["assessment_id"]: each["metrics"][0]["value"] for each in status["assessments"]}
    lowest = min(("Keep the Control", "control_assessment_id"), ("Keep the Candidate", "candidate_assessment_id"), key=lambda side: mae[compared["roles"][side[1]]])
    assert options["--option"] == lowest[0]
    step_id, read = capture_of("L2_READ_AFTER_S1")
    assert (options["--read-sequence"], step_id, read["cli"][0], read["capture"]["L2_READ_AFTER_S1"]) == ("{L2_READ_AFTER_S1}", "S1", "status", "write_sequence")


def test_dev_is_a_deviation_whose_text_says_the_references_of_revisions_2_and_3_were_edited_by_the_script_citing_those_of_revision_3():
    [action] = [action for action in cli_actions("DEV") if action["cli"][0] == "deviation"]
    args = action["cli"]
    text = args[args.index("--text") + 1]
    for words in ("References of revisions 2 and 3", "edited by the demonstration's script", "correct no error of the data"):
        assert words in text, words
    step_id, init = capture_of(args[args.index("--artifact") + 1].strip("{}"))
    assert (step_id, init["cli"][:1], init["expect"]["values"]["study.revision_number"]) == ("task 6.2", ["init"], 3)


SHOWN = {"L1.1": "folders", "L1.5": "head", "L1.7": "files", "L1.8": "file"}


def test_the_files_a_step_shows_are_shown_through_a_named_show_action_and_only_in_the_steps_that_show_them():
    for each in STEPS:
        shows = [action["show"] for action in each["actions"] if "show" in action]
        assert shows == ([SHOWN[each["id"]]] if each["id"] in SHOWN else []), each["id"]


# --- each id comes from the command that made it ------------------------------------------------------------------------------------------

ID_FLAGS = ("--observations", "--references", "--control", "--candidate", "--artifact")


def texts_of(value) -> list:
    """Each text of an expected value: the value itself, or each member of a list."""
    if isinstance(value, list):
        return [part for each in value for part in texts_of(each)]
    return [value] if isinstance(value, str) else []


def flags_and_values(args) -> list:
    """(flag, value) of each option of an argument list, given as `--flag value` or as `--flag=value`."""
    pairs = [tuple(part.split("=", 1)) for part in args if part.startswith("--") and "=" in part]
    return pairs + list(zip(args, args[1:]))


def argument_list(action) -> list:
    return action["cli"] if "cli" in action else action["args"]


def captured_names_used_by_a_later_command_only(steps) -> list:
    """The faults of the step list: a name used before a command captures it, or an id flag given a value a `status` command captured."""
    faults, captured = [], {}
    for step_id, action in processes(steps):
        expect = action.get("expect", {})
        expected = [part for value in expect.get("values", {}).values() for part in texts_of(value)] + expect.get("lines", [])
        for part in [*argument_list(action), *expected, action.get("input") or ""]:
            for name in MODULE.PLACEHOLDER.findall(part):
                if name not in MODULE.FOLDERS and name not in captured:
                    faults.append((step_id, name, "used before it is captured"))
        for flag, value in flags_and_values(argument_list(action)):
            for name in MODULE.PLACEHOLDER.findall(value):
                if flag in ID_FLAGS and captured.get(name) == "status":
                    faults.append((step_id, name, f"{flag} given a value a status command captured"))
        for name in action.get("capture", {}):
            captured[name] = action["cli"][0]
    return faults


def test_each_id_a_command_takes_is_captured_at_a_key_of_an_earlier_command_and_none_given_as_an_id_comes_from_status():
    """Stated limit: the test reads the step list's data; that the script's code opens no file of a Study to find an id or a value it
    passes to a command is not listed mechanically, and is INFERRED from the one function that resolves an argument list."""
    assert captured_names_used_by_a_later_command_only(STEPS) == []
    used = {name for _, action in processes(STEPS) for part in argument_list(action) for name in MODULE.PLACEHOLDER.findall(part)} - set(MODULE.FOLDERS)
    captured = {name: path for _, action in commands(STEPS) for name, path in action.get("capture", {}).items()}
    assert used
    for name in sorted(used):
        assert name in captured and captured[name], name


# --- what the transcript shows ------------------------------------------------------------------------------------------------------------


def blocks(transcript: str) -> dict:
    """{step id: the lines of its block} of a transcript: a block starts at its line `== ID · TITLE` and ends before the next block or
    the last line."""
    found, current = {}, None
    for line in transcript.splitlines()[:-1]:
        if line.startswith("== "):
            current = line[3:].split(" · ", 1)[0]
            found[current] = [line]
        elif current is not None:
            found[current].append(line)
    return found


def test_the_transcript_holds_one_block_per_step_with_its_title_commands_shown_values_what_it_shows_why_and_each_expectation_held(demonstration_run):
    run, by_block = demonstration_run, blocks(demonstration_run.transcript)
    calls = iter(run.calls)
    ids = [each["id"] for each in STEPS]
    for step_id in [*ids, *(name for name in by_block if name not in ids)]:
        assert step_id in by_block and step_id in ids, step_id
        lines, each = by_block[step_id], step(step_id)
        assert lines[0] == f"== {each['id']} · {each['title']}"
        assert f"What it shows: {each['shows']}" in lines and f"Why: {each['why']}" in lines, step_id
        at = 0
        for action in each["actions"]:
            if "cli" not in action and "program" not in action:
                at = lines.index(f"$ {run.module.shown_action(action, run.module.folders_of(run.work))}", at)
            for started in run.module.processes(action):
                call = next(calls)
                if "program" in started:
                    at = lines.index(run.module.shown_program(started, run.module.folders_of(run.work) | run.outcome.captures), at)
                else:
                    at = lines.index(f"$ python -m hypotrail {run.module.shlex.join(call['args'])}", at)
                for path in started.get("print", []):
                    value = value_at(call["payload"], path)
                    assert f"  {path} = {json.dumps(value)}" in lines[at:], (step_id, path)
                for key in run.module.expectation_keys(started["expect"]):
                    assert any(line.startswith(f"  expected {key} ") and line.endswith(": held") for line in lines[at:]), (step_id, key)
    assert run.transcript.splitlines()[-1] == f"{len(STEPS)} of {len(STEPS)} steps gave what they expect."


# --- the script checks itself -------------------------------------------------------------------------------------------------------------


def _exit_code(steps):
    action = [action for action in steps[1]["actions"] if "cli" in action][0]
    action["expect"]["exit"] = 3
    return "exit code", "3", "0"


def _refusal(steps):
    action = [action for action in steps[1]["actions"] if "cli" in action][1]
    action["expect"]["refusal"]["code"] = "STUDY_GONE"
    return "error.code", '"STUDY_GONE"', '"STUDY_EXISTS"'


def _value_at_a_key(steps):
    action = [action for action in steps[1]["actions"] if "cli" in action][0]
    action["expect"]["values"]["references_id"] = "references-0000000000000000"
    return "references_id", '"references-0000000000000000"', '"references-7520d791bfe31924"'


CHANGED_EXPECTATIONS = {"an exit code": _exit_code, "a refusal's code": _refusal, "the value at a key": _value_at_a_key}


@pytest.mark.parametrize("kind", sorted(CHANGED_EXPECTATIONS))
def test_when_one_expectation_does_not_hold_the_script_exits_1_after_a_line_naming_the_step_key_expected_and_found_and_runs_no_later_step(kind, tmp_path):
    steps = copy.deepcopy(STEPS)
    key, expected, found = CHANGED_EXPECTATIONS[kind](steps)
    assert steps[1]["id"] == "L1.2"
    run = run_in_process(tmp_path / "work", steps=steps)
    assert run.outcome.code == 1, run.transcript[-3000:]
    assert f"FAILED: step L1.2, key {key}: expected {expected}, found {found}" in run.transcript.splitlines(), run.transcript[-3000:]
    ran = [call["args"] for call in run.calls]
    started = [action["cli"] for _, action in commands(steps)]
    assert ran == [[run.module.resolved(part, run.module.folders_of(run.work) | run.outcome.captures) for part in args] for args in started[: len(ran)]]
    assert all(step_id in ("L1.1", "L1.2") for step_id, _ in commands(steps)[: len(ran)])
    assert run.transcript.splitlines()[-1].startswith(f"1 of {len(steps)} steps gave what they expect; L1.2 did not")


# --- the rule that compares a value found with a value expected ---------------------------------------------------------------------------

RIDGE_MAE = 1264.730691775682
SAME_OR_NOT = {
    "the same float moved in its last bit": (RIDGE_MAE, math.nextafter(RIDGE_MAE, 2000.0), True),
    "the same float moved in its sixth significant digit": (RIDGE_MAE, 1264.740691775682, False),
    "an integer and the equal float": (182, 182.0, True),
}


@pytest.mark.parametrize("pair", sorted(SAME_OR_NOT))
def test_the_rule_that_compares_a_value_found_with_a_value_expected_holds_floats_equal_to_12_significant_digits(pair):
    found, expected, same = SAME_OR_NOT[pair]
    assert MODULE.same(found, expected) is same
