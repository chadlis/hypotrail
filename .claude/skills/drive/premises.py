#!/usr/bin/env python3
"""The premise sheet of a fix prompt (D-055 on chadlis/hypotrail#75, item 2).

Usage: python3 -I premises.py <prompt file, or - for stdin> [worktree]

A fix prompt that says who calls a function carries a line

    callers(<package.module.function>) = {<package.module:function>, ...}

This script compares each such line with the callers that `tests/_architecture.py` (the repository's one resolver)
finds in `src/` of the worktree, and prints one sheet line per function. The sheet lists only the functions the prompt
makes a claim about: those of a `callers(...)` line, and those named in a sentence of the form "called from ... only".

A fix prompt that says a test checks some code carries a line (D-065 on chadlis/hypotrail#75, item 2)

    checked_by(<package.module.function>) = {<tests/file.py::test_name>, ...}

For each such line, the script extracts `HEAD` of the worktree into a scratch folder, never touching the worktree, and
runs each named test there with the worktree's interpreter (`.venv/bin/python`) and `PYTHONPATH=<copy>/src`, so that a
`python -m ...` subprocess of the test that inherits its environment loads the copy too: once as it is, then with the function made to raise on
entry. A test that fails only with the plant passes the line. The plant shows that the test reaches the function, not
that it asserts the claimed property. The sentences seen as such claims are those that say "checked" or "covered",
then "by", then "test", within one sentence. A claim worded another way is not seen. Such a sentence needs a
`checked_by(...)` line for each backticked name that resolves to a function defined under `src/` (by
`tests/_architecture.py`); a backticked name that resolves to none, such as a constant or a test name, is not counted
on its own. A sentence whose backticked names include no such function needs a line for each of them, so it is reported
until it names the function. A claim sentence with no backticked name is not checked against a line. A test ID whose brackets hold a comma is split in two, since a comma separates the tests of a
line. A test that expects an infrastructure error (`pytest.raises(Exception)`, `EXIT_INFRASTRUCTURE`)
cannot be checked by a plant, because the CLI turns the planted error into that outcome. A named test that is skipped
in the copy shows nothing either way.

Exit 2 when a `callers(...)` line differs from the resolver, when it names a function that `src/` neither defines nor
calls, when a "called from ... only" sentence has no `callers(...)` line for any function it names, when a named test
still passes with the plant, is skipped in the copy, fails or cannot be run without it, or cannot be run with it, when a `checked_by(...)`
function is not defined in `src/` at `HEAD`, when a "checked by ... test" sentence has no `checked_by(...)` line for any
function it names, when the test runs do not end within `PLANT_TIMEOUT` seconds (with a message of its own), and on any
error of the script itself.
"""

import ast
import io
import os
import re
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from xml.etree import ElementTree

CALLERS_LINE = re.compile(r"callers\(\s*([\w.]+)\s*\)\s*=\s*\{([^}]*)\}")
CLAIM_SENTENCE = re.compile(r"\bcalled\s+from\b.*\bonly\b", re.IGNORECASE | re.DOTALL)
CHECKED_BY_LINE = re.compile(r"checked_by\(\s*([\w.]+)\s*\)\s*=\s*\{([^}]*)\}")
TEST_CLAIM_SENTENCE = re.compile(r"\b(?:checked|covered)\b[^.]*\bby\b[^.]*\btest", re.IGNORECASE)
TEST_ID = re.compile(r"[\w./-]+\.py::[\w:]+(?:\[[^\]]+\])?")
PLANT = 'raise AssertionError("planted by premises.py")'
# The hook that runs this script gives it 120 s in all (`fix_prompt_check.py`).
PLANT_TIMEOUT = 90


class PlantTimeout(Exception):
    pass


def load_resolver(worktree: Path):
    sys.path.insert(0, str(worktree / "tests"))
    import _architecture

    return _architecture, _architecture.parse_all(worktree / "src")


def callers_of(architecture, trees: dict, function: str) -> set:
    """The `module:function` of every function of `src/` that calls `function` (a dotted name), by the resolver."""
    return {site.innermost for site in architecture.calls(trees) if site.callee == function}


def claimed_sets(prompt: str) -> dict:
    claims = {}
    for function, members in CALLERS_LINE.findall(prompt):
        claims[function] = {member.strip() for member in members.split(",") if member.strip()}
    return claims


def sentences(prompt: str) -> list:
    return [part for part in re.split(r"(?<=[.;:])\s+|\n\s*\n", prompt) if part.strip()]


def unbacked_claims(prompt: str, claims: dict, line=CALLERS_LINE, claim=CLAIM_SENTENCE, functions=None) -> list:
    """The sentences that `claim` matches ("called from ... only" by default) and that name no function with a `line` (a `callers(...)` line by default).

    With `functions` (the backticked names of a sentence that resolve to a function under `src/`), a sentence is reported when one of
    those functions has no line, or, when it names none, when any of its backticked names has no line."""
    claimed_names = {name.rsplit(".", 1)[-1] for name in claims}
    unbacked = []
    for sentence in sentences(prompt):
        if line.search(sentence) or not claim.search(sentence):
            continue
        named = {name.rstrip("()").rsplit(".", 1)[-1] for name in re.findall(r"`([\w.]+(?:\(\))?)`", sentence)}
        if functions is not None:
            resolved = functions(named)
            missing = (resolved - claimed_names) if resolved else (named - claimed_names)
        else:
            missing = not named & claimed_names
        if missing:
            unbacked.append(" ".join(sentence.split()))
    return unbacked


def checked_sets(prompt: str) -> dict:
    claims = {}
    for function, members in CHECKED_BY_LINE.findall(prompt):
        claims.setdefault(function, set()).update(member.strip() for member in members.split(",") if member.strip())
    return claims


def interpreter(worktree: Path) -> Path:
    python = worktree / ".venv" / "bin" / "python"
    if not python.exists():
        raise FileNotFoundError(f"no interpreter at {python}, which runs the tests of a checked_by(...) line")
    return python


def extract_head(worktree: Path, into: Path):
    archive = subprocess.run(["git", "-C", str(worktree), "archive", "--format=tar", "HEAD"], capture_output=True, check=True, timeout=60)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(into, filter="data")


def definition(tree: ast.Module, owner: list):
    """The `def` of `owner` (a function name, or a class name and a method name) at the top level of `tree`, or None."""
    body = tree.body
    for name in owner[:-1]:
        body = next((node.body for node in body if isinstance(node, ast.ClassDef) and node.name == name), [])
    return next((node for node in body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == owner[-1]), None)


def plant(copy: Path, function: str) -> bool:
    """Make `function` (`package.module.function` or `package.module.Class.method`) raise on entry in the copy; False when `src/` does not define it."""
    parts = function.split(".")
    for split in (len(parts) - 1, len(parts) - 2):
        if split < 1:
            continue
        base = copy / "src" / Path(*parts[:split])
        for path in (base.with_suffix(".py"), base / "__init__.py"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            node = definition(ast.parse(text), parts[split:])
            if node is None:
                continue
            lines = text.splitlines(keepends=True)
            first = node.body[0]
            docstring = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)
            anchor = node.body[1] if docstring and len(node.body) > 1 else first
            indent = lines[anchor.lineno - 1][: anchor.col_offset]
            if indent.strip():
                raise ValueError(f"cannot plant in {function}: its body does not start on a line of its own")
            at = first.end_lineno if docstring and anchor is first else anchor.lineno - 1
            lines.insert(at, f"{indent}{PLANT}\n")
            path.write_text("".join(lines), encoding="utf-8")
            return True
    return False


def pytest_exit(python: Path, copy: Path, test: str, deadline: float) -> tuple:
    """(the exit code of pytest on one test of the copy, with `PYTHONPATH=<copy>/src`, whether a case of it was skipped). Raises PlantTimeout past the deadline."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise PlantTimeout
    report = copy.parent / f"{copy.name}-report.xml"
    run = subprocess.Popen(
        [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}", test],
        cwd=copy, env={**os.environ, "PYTHONPATH": str(copy / "src")},
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    try:
        code = run.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        # The test's own subprocesses are in the same new session, so the whole group is stopped.
        os.killpg(run.pid, signal.SIGKILL)
        run.wait()
        raise PlantTimeout from None
    skipped = report.exists() and any(int(suite.get("skipped", 0)) for suite in ElementTree.parse(report).iter("testsuite"))
    report.unlink(missing_ok=True)
    return code, skipped


def checked_lines(function: str, tests: set, worktree: Path, python: Path, deadline: float) -> tuple:
    """(the sheet lines of one `checked_by(...)` line, whether it passes)."""
    lines, passes = [], True
    named = sorted(test for test in tests if TEST_ID.fullmatch(test))
    for test in sorted(set(tests) - set(named)):
        lines.append(f"- checked_by({function}): {test!r} IS NOT A TEST ID of the form tests/file.py::test_name")
        passes = False
    with tempfile.TemporaryDirectory(prefix="premises-") as scratch:
        copy = Path(scratch) / "head"
        extract_head(worktree, copy)
        unplanted = {test: pytest_exit(python, copy, test, deadline)[0] for test in named}
        if not plant(copy, function):
            return lines + [f"- checked_by({function}): NOT DEFINED in src/ at HEAD"], False
        for test in named:
            if unplanted[test] in (4, 5):
                lines.append(f"- checked_by({function}): {test} IS NOT FOUND at HEAD")
            elif unplanted[test] == 1:
                lines.append(f"- checked_by({function}): {test} FAILS WITHOUT THE PLANT, so it shows nothing")
            elif unplanted[test] != 0:
                lines.append(f"- checked_by({function}): {test} DOES NOT RUN at HEAD (pytest exit {unplanted[test]})")
            else:
                planted, skipped = pytest_exit(python, copy, test, deadline)
                if planted == 1:
                    lines.append(
                        f"- checked_by({function}): {test} fails when {function} raises on entry: "
                        "the test reaches it, which does not show that it asserts the claimed property; "
                        "a test that expects an infrastructure error (`pytest.raises(Exception)`, `EXIT_INFRASTRUCTURE`) cannot be checked by a plant, "
                        "and a claim sentence with no backticked name is not checked against a line"
                    )
                    continue
                if planted == 0 and skipped:
                    lines.append(f"- checked_by({function}): {test} SKIPPED IN THE COPY")
                elif planted == 0:
                    lines.append(f"- checked_by({function}): {test} STILL PASSES WITH {function} BROKEN")
                else:
                    lines.append(f"- checked_by({function}): {test} DOES NOT RUN WITH THE PLANT (pytest exit {planted})")
            passes = False
    return lines, passes


def src_functions(named: set, worktree: Path) -> set:
    """The names among `named` that the resolver finds as a function or method defined under `src/` of the worktree."""
    if not named:
        return set()
    architecture, trees = load_resolver(worktree)
    defined = architecture.defined_functions(trees)
    return {name for name in named if any(full == name or full.endswith("." + name) for full in defined)}


def sheet(prompt: str, worktree: Path) -> tuple:
    """(the sheet lines, whether the prompt passes)."""
    claims = claimed_sets(prompt)
    checks = checked_sets(prompt)
    lines, passes = [], True
    for sentence in unbacked_claims(prompt, claims):
        lines.append(f"- NO callers(...) LINE for the claim: {sentence[:160]!r}")
        passes = False
    for sentence in unbacked_claims(prompt, checks, CHECKED_BY_LINE, TEST_CLAIM_SENTENCE, functions=lambda named: src_functions(named, worktree)):
        lines.append(f"- NO checked_by(...) LINE for the claim: {sentence[:160]!r}")
        passes = False
    if checks:
        python, deadline = interpreter(worktree), time.monotonic() + PLANT_TIMEOUT
        for function, tests in sorted(checks.items()):
            found, ok = checked_lines(function, tests, worktree, python, deadline)
            lines += found
            passes = passes and ok
    if not claims:
        return lines, passes
    architecture, trees = load_resolver(worktree)
    defined = architecture.defined_functions(trees)
    used = {site.callee for site in architecture.calls(trees)}
    for function, claimed in sorted(claims.items()):
        if function not in defined and function not in used:
            lines.append(f"- callers({function}): NOT DEFINED AND NEVER CALLED in src/")
            passes = False
            continue
        found = callers_of(architecture, trees, function)
        shown = ", ".join(sorted(found)) or "nothing"
        if found == claimed:
            lines.append(f"- callers({function}) = {{{shown}}}: as claimed")
        else:
            lines.append(
                f"- callers({function}) = {{{shown}}}: DIFFERS from the claim; "
                f"claimed but not found: {sorted(claimed - found) or 'none'}; found but not claimed: {sorted(found - claimed) or 'none'}"
            )
            passes = False
    return lines, passes


def main(argv: list) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        prompt = sys.stdin.read() if argv[1] == "-" else Path(argv[1]).read_text(encoding="utf-8")
        worktree = Path(argv[2] if len(argv) == 3 else ".").resolve()
        lines, passes = sheet(prompt, worktree)
    except PlantTimeout:
        print(f"premises.py: the test runs of the checked_by(...) lines did not end within {PLANT_TIMEOUT} s; nothing is checked", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"premises.py failed ({type(error).__name__}: {error}); nothing is checked", file=sys.stderr)
        return 2
    if lines:
        print("## Premise sheet")
        print("\n".join(lines))
    return 0 if passes else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
