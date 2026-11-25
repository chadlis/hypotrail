"""D-055 on chadlis/hypotrail#75, item 2: the premise sheet of a fix prompt, `.claude/skills/drive/premises.py`.

The sheet is run on a small worktree built in `tmp_path`, with the repository's own resolver (`tests/_architecture.py`) copied in.
The `checked_by(...)` claims of D-065 on chadlis/hypotrail#75, item 2, are run on a small git worktree whose `.venv/bin/python`
starts the interpreter of this suite.
"""

import shutil
import subprocess
import sys
import textwrap

import pytest

from _drive_scripts import FIXTURES, ROOT, load, run

FUNCTION = "pkg.core.guard.fault"
BY_IMPORT = "pkg.cli:entry"
BY_ALIAS = "pkg.ml.run:execute"


@pytest.fixture
def worktree(tmp_path):
    files = {
        "src/pkg/__init__.py": "",
        "src/pkg/core/__init__.py": "",
        "src/pkg/core/guard.py": "def fault(value):\n    return None\n\n\ndef unrelated():\n    return 1\n",
        "src/pkg/cli.py": "from pkg.core import guard\n\n\ndef entry():\n    return guard.fault(1)\n",
        "src/pkg/ml/__init__.py": "",
        "src/pkg/ml/run.py": "from pkg.core.guard import fault as check\n\n\ndef execute():\n    return check(2)\n",
        "src/pkg/ml/other.py": "from pkg.core import guard\n\n\ndef spare():\n    return guard.unrelated()\n",
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    (tmp_path / "tests").mkdir()
    shutil.copy(ROOT / "tests" / "_architecture.py", tmp_path / "tests" / "_architecture.py")
    return tmp_path


def sheet(worktree, prompt: str):
    return run("premises", "-", worktree, stdin=prompt)


def test_a_callers_line_equal_to_what_the_resolver_finds_passes_and_is_shown_as_claimed(worktree):
    result = sheet(worktree, f"callers({FUNCTION}) = {{{BY_IMPORT}, {BY_ALIAS}}}\n")
    assert (result.returncode, result.stderr) == (0, "")
    assert f"callers({FUNCTION}) = {{{BY_IMPORT}, {BY_ALIAS}}}: as claimed" in result.stdout


def test_a_callers_line_that_leaves_out_a_caller_reached_through_an_import_alias_is_refused(worktree):
    result = sheet(worktree, f"callers({FUNCTION}) = {{{BY_IMPORT}}}\n")
    assert result.returncode == 2
    assert f"found but not claimed: ['{BY_ALIAS}']" in result.stdout


def test_a_callers_line_that_names_a_caller_that_does_not_call_it_is_refused(worktree):
    result = sheet(worktree, f"callers({FUNCTION}) = {{{BY_IMPORT}, {BY_ALIAS}, pkg.ml.other:spare}}\n")
    assert result.returncode == 2
    assert "claimed but not found: ['pkg.ml.other:spare']" in result.stdout


def test_a_callers_line_for_a_function_that_src_neither_defines_nor_calls_is_refused(worktree):
    result = sheet(worktree, "callers(pkg.core.guard.fualt) = {}\n")
    assert result.returncode == 2
    assert "NOT DEFINED AND NEVER CALLED" in result.stdout


def test_the_sheet_lists_only_the_functions_the_prompt_makes_a_claim_about(worktree):
    result = sheet(worktree, f"`unrelated` is read here. callers({FUNCTION}) = {{{BY_IMPORT}, {BY_ALIAS}}}\n")
    assert result.returncode == 0
    assert result.stdout.count("callers(") == 1 and "unrelated" not in result.stdout


def test_a_called_from_only_sentence_with_no_callers_line_is_reported(worktree):
    result = sheet(worktree, "So `fault` may be called from `core/guard.py` and, for the entry, from `cli.py` only.\n")
    assert result.returncode == 2
    assert "NO callers(...) LINE for the claim" in result.stdout and "called from" in result.stdout


def test_a_called_from_only_sentence_with_a_callers_line_for_its_function_passes(worktree):
    prompt = f"So `fault` is called from `cli.py` and `ml/run.py` only.\ncallers({FUNCTION}) = {{{BY_IMPORT}, {BY_ALIAS}}}\n"
    assert sheet(worktree, prompt).returncode == 0


def test_a_called_from_only_sentence_is_reported_when_only_another_function_has_a_callers_line(worktree):
    prompt = f"`unrelated` is called from `core/guard.py` only.\ncallers({FUNCTION}) = {{{BY_IMPORT}, {BY_ALIAS}}}\n"
    result = sheet(worktree, prompt)
    assert result.returncode == 2 and "NO callers(...) LINE" in result.stdout


def test_a_prompt_that_makes_no_claim_about_callers_gives_an_empty_sheet(worktree):
    result = sheet(worktree, "Rename `fault` in `tests/test_guard.py`. It is used in several places.\n")
    assert (result.returncode, result.stdout) == (0, "")


def test_a_missing_prompt_file_blocks_with_exit_2(worktree):
    result = run("premises", worktree / "no-such-prompt.md", worktree)
    assert result.returncode == 2 and "premises.py failed" in result.stderr


def test_a_worktree_without_the_resolver_blocks_with_exit_2(tmp_path):
    result = sheet(tmp_path, f"callers({FUNCTION}) = {{}}\n")
    assert result.returncode == 2 and "premises.py failed" in result.stderr


def test_the_round_1_prompt_of_the_second_slice_that_says_who_calls_the_guard_is_reported_without_a_callers_line():
    prompt = (FIXTURES / "fix-prompts" / "r1b-round-1.md").read_text()
    result = sheet(ROOT, prompt)
    assert result.returncode == 2
    assert "So `read_sequence_fault` may be called from `core/study_write.py`" in result.stdout


def test_the_drive_skill_runs_the_premise_sheet_before_it_posts_a_fix_prompt_and_names_its_two_lines_whose_forms_the_script_docstring_gives():
    lines = (ROOT / ".claude/skills/drive/SKILL.md").read_text().splitlines()
    row = next(line for line in lines if line.startswith("| 6 |"))
    paragraph = next(line for line in lines if line.startswith("**Check the premise before you route.**"))
    assert "posted by `.claude/skills/drive/post_fix_prompt.sh`, before the builder starts; it posts nothing while `premises.py` or `fix_prompt_check.py --strict` refuses the prompt" in row
    assert "`callers(\u2026)`" in paragraph and "`checked_by(\u2026)`" in paragraph and "premises.py <prompt file> <worktree>" in paragraph
    docstring = load("premises").__doc__
    assert "callers(<package.module.function>) = {<package.module:function>, ...}" in docstring
    assert "checked_by(<package.module.function>) = {<tests/file.py::test_name>, ...}" in docstring


REACHED = "pkg.core.reached"
UNREACHED = "pkg.core.unreached"
MODULE_RUN = "tests/test_core.py::test_the_module_run_prints_four"
CORE = "def reached(value):\n    \"\"\"Twice the value.\"\"\"\n    return value * 2\n\n\ndef unreached():\n    return 1\n"


@pytest.fixture
def git_worktree(tmp_path):
    """A committed package whose one test reaches `pkg.core.reached` only through a `python -m pkg` subprocess, so only `PYTHONPATH` lets that subprocess load the copy."""
    files = {
        "src/pkg/__init__.py": "",
        "src/pkg/core.py": CORE,
        "src/pkg/__main__.py": "from pkg.core import reached\n\nprint(reached(2))\n",
        "tests/test_core.py": (
            "import subprocess\nimport sys\n\nimport pytest\n\nfrom pkg.core import reached\n\n\ndef test_the_module_run_prints_four():\n"
            "    done = subprocess.run([sys.executable, '-m', 'pkg'], capture_output=True, text=True)\n"
            "    assert done.stdout.strip() == '4'\n\n\n"
            "@pytest.mark.parametrize('value', [1, 3])\ndef test_twice(value):\n    assert reached(value) == 2 * value\n\n\n"
            "@pytest.mark.skip(reason='not here')\ndef test_skipped():\n    assert reached(1) == 2\n\n\n"
            "def test_a_long_wait():\n    import time\n    time.sleep(60)\n"
        ),
        "src/hypotrail/__init__.py": "",
        "src/hypotrail/cli.py": "INVALID_ARGUMENTS = 'INVALID_ARGUMENTS'\n\n\ndef decide():\n    return INVALID_ARGUMENTS\n",
        "tests/test_cli.py": "from hypotrail.cli import decide\n\n\ndef test_refuses():\n    assert decide() == 'INVALID_ARGUMENTS'\n",
        "tests/_architecture.py": (ROOT / "tests" / "_architecture.py").read_text(),
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "a package"], check=True)
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(f"#!/bin/sh\nexec {sys.executable} \"$@\"\n")
    python.chmod(0o755)
    return tmp_path


def test_a_checked_by_line_whose_test_fails_once_the_function_raises_in_a_scratch_copy_passes_and_says_the_test_only_reaches_it(git_worktree):
    prompt = f"`reached` is checked by the test `{MODULE_RUN}`.\nchecked_by({REACHED}) = {{{MODULE_RUN}}}\n"
    result = sheet(git_worktree, prompt)
    assert (result.returncode, result.stderr) == (0, "")
    assert f"checked_by({REACHED}): {MODULE_RUN} fails when {REACHED} raises on entry: the test reaches it, which does not show that it asserts the claimed property" in result.stdout
    assert "a test that expects an infrastructure error (`pytest.raises(Exception)`, `EXIT_INFRASTRUCTURE`) cannot be checked by a plant" in result.stdout
    assert "a claim sentence with no backticked name is not checked against a line" in result.stdout
    assert (git_worktree / "src/pkg/core.py").read_text() == CORE


def test_a_checked_by_line_whose_test_still_passes_once_the_function_raises_is_refused(git_worktree):
    result = sheet(git_worktree, f"checked_by({UNREACHED}) = {{{MODULE_RUN}}}\n")
    assert result.returncode == 2
    assert f"checked_by({UNREACHED}): {MODULE_RUN} STILL PASSES WITH {UNREACHED} BROKEN" in result.stdout


def test_a_test_id_with_a_parametrisation_in_brackets_is_a_test_id(git_worktree):
    result = sheet(git_worktree, f"checked_by({REACHED}) = {{tests/test_core.py::test_twice[3]}}\n")
    assert (result.returncode, result.stderr) == (0, "")
    assert f"checked_by({REACHED}): tests/test_core.py::test_twice[3] fails when {REACHED} raises on entry" in result.stdout


def test_a_named_test_that_is_skipped_in_the_copy_is_reported_as_skipped_not_as_still_passing(git_worktree):
    result = sheet(git_worktree, f"checked_by({REACHED}) = {{tests/test_core.py::test_skipped}}\n")
    assert result.returncode == 2
    assert f"checked_by({REACHED}): tests/test_core.py::test_skipped SKIPPED IN THE COPY" in result.stdout and "STILL PASSES" not in result.stdout


def test_a_claim_sentence_that_names_several_functions_needs_a_checked_by_line_for_each_one(git_worktree):
    sentence = "`reached` and `unreached` are checked by the test `tests/test_core.py::test_twice`."
    result = sheet(git_worktree, f"{sentence}\nchecked_by({REACHED}) = {{tests/test_core.py::test_twice}}\n")
    assert result.returncode == 2 and f"NO checked_by(...) LINE for the claim: {sentence!r}" in result.stdout


def test_a_constant_named_beside_a_function_needs_no_checked_by_line_of_its_own(git_worktree):
    prompt = (
        "`decide` refuses with `INVALID_ARGUMENTS`, which is checked by the test `tests/test_cli.py::test_refuses`.\n"
        "checked_by(hypotrail.cli.decide) = {tests/test_cli.py::test_refuses}\n"
    )
    result = sheet(git_worktree, prompt)
    assert (result.returncode, result.stderr) == (0, "")
    assert "NO checked_by(...) LINE" not in result.stdout


def test_a_planted_run_that_does_not_end_within_the_time_limit_exits_2_with_its_own_message(git_worktree, monkeypatch, capsys):
    premises = load("premises")
    monkeypatch.setattr(premises, "PLANT_TIMEOUT", 3)
    monkeypatch.setattr(premises.sys, "stdin", __import__("io").StringIO(f"checked_by({REACHED}) = {{tests/test_core.py::test_a_long_wait}}\n"))
    assert premises.main(["premises.py", "-", str(git_worktree)]) == 2
    error = capsys.readouterr().err
    assert "did not end within 3 s" in error and "premises.py failed" not in error


def test_a_checked_by_line_in_a_worktree_without_its_interpreter_exits_2_as_a_script_error(git_worktree):
    shutil.rmtree(git_worktree / ".venv")
    result = sheet(git_worktree, f"checked_by({REACHED}) = {{{MODULE_RUN}}}\n")
    assert result.returncode == 2 and "premises.py failed" in result.stderr and "did not end within" not in result.stderr


def test_the_round_2_prompt_of_the_third_slice_that_says_a_test_checks_details_command_is_reported_without_a_checked_by_line():
    prompt = (FIXTURES / "fix-prompts" / "f1-round-2.md").read_text()
    result = sheet(ROOT, prompt)
    assert result.returncode == 2
    assert "NO checked_by(...) LINE for the claim: 'The forms of `details.command` are checked at runtime by the test about line 530.'" in result.stdout


def test_the_module_docstring_states_what_a_plant_shows_and_which_claims_the_detector_sees():
    doc = " ".join(load("premises").__doc__.split())
    assert "shows that the test reaches the function, not that it asserts the claimed property" in doc
    assert "A claim worded another way is not seen" in doc
    assert "A test that expects an infrastructure error (`pytest.raises(Exception)`, `EXIT_INFRASTRUCTURE`) cannot be checked by a plant, because the CLI turns the planted error into that outcome" in doc
    assert "a backticked name that resolves to none, such as a constant or a test name, is not counted on its own" in doc
    assert "A claim sentence with no backticked name is not checked against a line" in doc
    assert "A test ID whose brackets hold a comma is split in two" in doc
