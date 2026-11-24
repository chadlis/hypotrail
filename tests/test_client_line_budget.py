"""C6 of chadlis/hypotrail#103, "client under 3,000 lines", amended to 5,000 by its owner: the line count of the VS Code client, read from
`git ls-files` at each check.

"**replace** in C6 the bound "3,000 lines" by "5,000 lines": the owner's criterion of #1 comment 7043566976 is amended by its owner; the
line-budget test and the handbook follow in L2.5." (D-100 on chadlis/hypotrail#75, comment 7112019719.)
"The 3,000 lines count TypeScript, HTML and CSS. Tests and generated bundles are excluded." (D-031 on chadlis/hypotrail#75, item 11.)
Every tracked file under `clients/vscode/` is in exactly one class: counted, test, refused or other. No list of files is written here.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CLIENT_FOLDER = "clients/vscode/"
BUDGET = 5000
COUNTED_KINDS = (".ts", ".tsx", ".mts", ".cts", ".html", ".css")
TEST_FOLDER = "clients/vscode/test/"
REFUSED_KINDS = (".js", ".mjs", ".cjs", ".jsx")
GENERATED_FOLDER = "clients/vscode/out/"
CONTRACT_STRING_LIMIT = 200


def classes_of(path: str) -> list:
    """The classes a path under the client's folder is in, by the four rules; each path is in exactly one."""
    kind = Path(path).suffix
    found = []
    if kind in COUNTED_KINDS and not path.startswith(TEST_FOLDER):
        found.append("counted")
    if kind in COUNTED_KINDS and path.startswith(TEST_FOLDER):
        found.append("test")
    if kind in REFUSED_KINDS:
        found.append("refused")
    if kind not in COUNTED_KINDS + REFUSED_KINDS:
        found.append("other")
    return found


def budget(root: Path, paths: list) -> dict:
    """The counted lines (`str.splitlines()`, blank lines and comments included), the refused files, and whether the client is within the budget."""
    counted = [p for p in paths if classes_of(p) == ["counted"]]
    refused = [p for p in paths if classes_of(p) == ["refused"]]
    lines = sum(len((root / p).read_text(encoding="utf-8").splitlines()) for p in counted)
    return {"lines": lines, "refused": refused, "within": lines < BUDGET and not refused}


def tracked_client_files() -> list:
    listing = subprocess.run(["git", "ls-files", "-z", "--", CLIENT_FOLDER], cwd=ROOT, capture_output=True, text=True, check=True)
    return sorted(name for name in listing.stdout.split("\0") if name)


def test_the_client_is_within_its_line_budget():
    files = tracked_client_files()
    assert files, "git ls-files lists no file under clients/vscode/"
    result = budget(ROOT, files)
    assert result["refused"] == []
    assert result["lines"] < BUDGET, result["lines"]


def test_every_tracked_client_file_is_in_exactly_one_class_and_the_counted_ones_are_the_six_kinds_outside_the_tests():
    files = tracked_client_files()
    assert [(f, classes_of(f)) for f in files if len(classes_of(f)) != 1] == []
    counted = {f for f in files if classes_of(f) == ["counted"]}
    expected = {f for f in files if f.endswith(COUNTED_KINDS) and not f.startswith(TEST_FOLDER)}
    assert counted == expected
    assert {"clients/vscode/src/bridge.ts", "clients/vscode/test/vscode-stub.ts"} <= set(files)
    assert classes_of("clients/vscode/test/vscode-stub.ts") == ["test"]


def planted(tmp_path: Path, files: dict) -> list:
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    return sorted(files)


def lines_of(count: int) -> str:
    """`count` lines, a third of them blank and a third comments."""
    pattern = ["", "// a comment", "const x = 1;"]
    return "\n".join(pattern[i % 3] for i in range(count)) + "\n"


def test_the_count_passes_at_4999_lines_and_fails_at_5000_blank_lines_and_comments_included(tmp_path):
    under = budget(tmp_path / "a", planted(tmp_path / "a", {"clients/vscode/src/a.ts": lines_of(4000), "clients/vscode/media/b.css": lines_of(999)}))
    at = budget(tmp_path / "b", planted(tmp_path / "b", {"clients/vscode/src/a.ts": lines_of(4000), "clients/vscode/media/b.css": lines_of(1000)}))
    assert (under["lines"], under["within"]) == (4999, True)
    assert (at["lines"], at["within"]) == (5000, False)


BASE = {"clients/vscode/src/a.ts": lines_of(10)}
PLANTED_FILES = [
    ("a .ts file of 3,000 lines under test/ is not counted", "clients/vscode/test/big.ts", lines_of(3000), 10, True),
    ("a .tsx file outside test/ is counted", "clients/vscode/src/a.tsx", lines_of(5), 15, True),
    ("an .mts file outside test/ is counted", "clients/vscode/src/a.mts", lines_of(5), 15, True),
    ("a .cts file outside test/ is counted", "clients/vscode/src/a.cts", lines_of(5), 15, True),
    ("an .html file outside test/ is counted", "clients/vscode/media/a.html", lines_of(5), 15, True),
    ("a .css file outside test/ is counted", "clients/vscode/media/a.css", lines_of(5), 15, True),
    ("a .js file under src/ is refused", "clients/vscode/src/a.js", lines_of(5), 10, False),
    ("a .js file under test/ is refused", "clients/vscode/test/a.js", lines_of(5), 10, False),
    ("a .json file of 3,000 lines is neither counted nor refused", "clients/vscode/data.json", lines_of(3000), 10, True),
]


@pytest.mark.parametrize("case, name, text, lines, within", PLANTED_FILES, ids=[case for case, *_ in PLANTED_FILES])
def test_a_planted_file_is_counted_or_not_and_refused_or_not_by_its_class(tmp_path, case, name, text, lines, within):
    result = budget(tmp_path, planted(tmp_path, {**BASE, name: text}))
    assert (result["lines"], result["within"]) == (lines, within), case


def test_the_generated_folder_is_ignored_and_holds_no_tracked_file():
    assert GENERATED_FOLDER in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert [f for f in tracked_client_files() if f.startswith(GENERATED_FOLDER)] == []


def contract_problems(contract) -> list:
    """What makes `contract.json` other than one flat object of strings, numbers and lists of them, no string over the limit."""
    if not isinstance(contract, dict):
        return ["not one object"]
    problems = []

    def scalar(key, value):
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            problems.append(f"{key}: {value!r} is not a string or a number")
        elif isinstance(value, str) and len(value) > CONTRACT_STRING_LIMIT:
            problems.append(f"{key}: a string of {len(value)} characters")

    for key, value in contract.items():
        for each in value if isinstance(value, list) else [value]:
            scalar(key, each)
    return problems


def test_contract_json_is_one_flat_object_of_strings_numbers_and_lists_of_them():
    assert contract_problems(json.loads((ROOT / CLIENT_FOLDER / "contract.json").read_text(encoding="utf-8"))) == []


@pytest.mark.parametrize(
    "value, fails",
    [({"a": 1}, True), ([["a"]], True), ("x" * 201, True), ("x" * 200, False)],
    ids=["a nested object", "a list that holds a list", "a string of 201 characters", "a string of 200 characters"],
)
def test_a_planted_contract_value_fails_or_passes(value, fails):
    contract = json.loads((ROOT / CLIENT_FOLDER / "contract.json").read_text(encoding="utf-8"))
    contract["planted"] = value
    assert bool(contract_problems(contract)) is fails
