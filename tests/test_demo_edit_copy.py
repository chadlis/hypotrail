"""The script that makes the two edits of task 6 of the L2 demonstration in a Workload copy (`docs/demo/edit_copy.py`).

The script is run as the owner runs it, in a process of its own; the CLI is run in process.
"""

import ast
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _demo_helpers import SCRIPT, script_values
from _study_helpers import EXAMPLES, run_cli, run_json, sha256

ROOT = Path(__file__).resolve().parent.parent


def run_script(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)], capture_output=True, text=True)


def cells_of(path: Path) -> list:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


def changed_cells(before: list, after: list) -> dict:
    """{(day, column): (before, after)} of every cell that differs, the two tables having the same shape."""
    assert len(before) == len(after) and before[0] == after[0]
    header, found = before[0], {}
    for old_row, new_row in zip(before[1:], after[1:]):
        assert len(old_row) == len(new_row) == len(header)
        for column, old, new in zip(header, old_row, new_row):
            if old != new:
                found[(old_row[header.index("dteday")], column)] = (old, new)
    return found


def lock_entry(bike: Path) -> dict:
    lock = json.loads((bike / "data-sources.lock.json").read_text(encoding="utf-8"))
    [entry] = [source for source in lock["sources"] if source["local_path"] == "data/day.csv"]
    return entry


def references_id(study: Path) -> str:
    _, status, _ = run_json("status", "--study", study)
    return next(entry["artifact_id"] for entry in status["revisions"][-1]["artifacts"] if entry["role"] == "references")


def observation_set_ids(study: Path) -> list:
    """The Observation set ID of each `run ml`, read by the route the README gives: `status --since 0 --json`."""
    _, status, _ = run_json("status", "--study", study, "--since", "0")
    return [
        written["id"]
        for entry in status["writes_since"]
        if entry["command"] == "run ml" and entry["phase"] == "end"
        for written in entry["written"]
        if written["kind"] == "observation_set"
    ]


def assess(study: Path, observations: str, references: str) -> dict:
    code, payload, err = run_json("assess", "--study", study, "--observations", observations, "--scorer", "regression_mae_v1", "--references", references)
    assert code == 0, (payload, err)
    return payload["assessment"]


def test_each_edit_changes_registered_and_cnt_of_its_day_by_the_amount_rewrites_the_lock_and_gives_the_rescoring_the_demonstration_records(tmp_path):
    values = script_values()
    copy = tmp_path / "examples"
    shutil.copytree(EXAMPLES, copy)
    bike, study = copy / "bike_day", tmp_path / "study"
    assert run_cli("init", "--workload", "bike_day", "--study", study, "--examples-dir", copy)[0] == 0
    for config in ("seasonal_7", "ridge_v1"):
        code, payload, err = run_json("run", "ml", "--study", study, "--config", config, "--partition", "dev", "--request-id", f"ml-{config}", "--examples-dir", copy)
        assert code == 0, (payload, err)
    observation_sets = observation_set_ids(study)
    assert len(observation_sets) == 2
    for observations in observation_sets:
        assert assess(study, observations, references_id(study))["rescoring"] is None

    # 6.1 is outside the assessed Partition: the References change, no Item does; 6.2 is inside it: one Item changes on each side.
    for edit, changed_items in (("6.1", 0), ("6.2", 1)):
        day = values["EDITS"][edit]
        before, old_digest = cells_of(bike / "data" / "day.csv"), sha256(bike / "data" / "day.csv")
        result = run_script("--copy", copy, "--edit", edit)
        assert result.returncode == 0, result.stderr
        after = cells_of(bike / "data" / "day.csv")
        old = {column: int(before[[row[before[0].index("dteday")] for row in before].index(day)][before[0].index(column)]) for column in values["COLUMNS"]}
        assert changed_cells(before, after) == {(day, column): (str(old[column]), str(old[column] + values["AMOUNT"])) for column in values["COLUMNS"]}, edit
        assert set(values["COLUMNS"]) == {"registered", "cnt"} and values["AMOUNT"] == 100

        entry, data = lock_entry(bike), bike / "data" / "day.csv"
        assert (entry["sha256"], entry["size_bytes"]) == (sha256(data), data.stat().st_size), edit
        assert run_cli("data", "verify", "--examples-dir", copy)[0] == 0, edit

        lines = result.stdout.splitlines()
        assert f"day: {day}" in lines, (edit, lines)
        for column in values["COLUMNS"]:
            assert f"{column}: {old[column]} -> {old[column] + values['AMOUNT']}" in lines, (edit, column, lines)
        assert f"sha256 of data/day.csv: {old_digest} -> {sha256(data)}" in lines, (edit, lines)

        code, payload, err = run_json("init", "--study", study, "--new-revision", "--examples-dir", copy)
        assert code == 0, (payload, err)
        references = references_id(study)
        for observations in observation_sets:
            rescoring = assess(study, observations, references)["rescoring"]
            assert rescoring is not None and rescoring["cause"] == "references_version", (edit, rescoring)
            assert len(rescoring["changed_items"]) == changed_items, (edit, rescoring)


def digests_of_the_checkout_examples() -> dict:
    return {path.relative_to(EXAMPLES).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(EXAMPLES.rglob("*")) if path.is_file()}


CHECKOUT_PATHS = {
    "examples": lambda tmp_path: EXAMPLES,
    "examples/bike_day": lambda tmp_path: EXAMPLES / "bike_day",
    "through ..": lambda tmp_path: Path(f"{ROOT}/docs/../examples"),
    "a symbolic link": lambda tmp_path: _link(tmp_path),
}


def _link(tmp_path: Path) -> Path:
    link = tmp_path / "looks-like-a-copy"
    link.symlink_to(EXAMPLES, target_is_directory=True)
    return link


@pytest.mark.parametrize("case", sorted(CHECKOUT_PATHS))
def test_a_folder_inside_the_checkout_is_refused_with_its_reason_and_no_file_of_the_checkout_examples_changes(case, tmp_path):
    """Stated limit: "inside the checkout" is judged on the resolved path against the script's own checkout; another clone of the
    repository elsewhere on the machine is not recognised."""
    folder = CHECKOUT_PATHS[case](tmp_path)
    before = digests_of_the_checkout_examples()
    result = run_script("--copy", folder, "--edit", "6.2")
    assert result.returncode != 0, result.stdout
    assert "inside the checkout" in result.stderr, result.stderr
    assert digests_of_the_checkout_examples() == before


# The modules the script may import: each is in the standard library, and none reaches the network or a model.
ALLOWED_IMPORTS = {"argparse", "csv", "hashlib", "io", "json", "pathlib", "sys"}
NEVER_ALLOWED = ("socket", "ssl", "http", "urllib", "requests", "anthropic", "inspect_ai")


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


def _missing_folder(tmp_path: Path) -> tuple:
    return tmp_path / "no-such-copy", "data/day.csv"


def _copy_without_the_data_file(tmp_path: Path) -> tuple:
    copy = tmp_path / "examples"
    shutil.copytree(EXAMPLES, copy)
    (copy / "bike_day" / "data" / "day.csv").unlink()
    return copy, "data/day.csv"


def _copy_without_the_lock(tmp_path: Path) -> tuple:
    copy = tmp_path / "examples"
    shutil.copytree(EXAMPLES, copy)
    (copy / "bike_day" / "data-sources.lock.json").unlink()
    return copy, "data-sources.lock.json"


MISSING_FILE_CASES = {
    "a missing folder": _missing_folder,
    "a folder without data/day.csv": _copy_without_the_data_file,
    "a folder without data-sources.lock.json": _copy_without_the_lock,
}


def digests_under(folder: Path) -> dict:
    if not folder.exists():
        return {}
    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(folder.rglob("*")) if path.is_file()}


@pytest.mark.parametrize("case", sorted(MISSING_FILE_CASES))
def test_a_folder_without_the_data_file_or_the_lock_exits_non_zero_with_one_line_naming_the_file_and_the_folder_and_writes_nothing(case, tmp_path):
    copy, missing = MISSING_FILE_CASES[case](tmp_path)
    existed, before = copy.exists(), digests_under(copy)
    result = run_script("--copy", copy, "--edit", "6.2")
    assert result.returncode != 0, result.stdout
    lines = result.stderr.splitlines()
    assert len(lines) == 1, lines
    [line] = lines
    assert missing in line and str(copy / "bike_day") in line and not line.startswith("refused:"), line
    assert result.stdout == ""
    assert copy.exists() == existed and digests_under(copy) == before
