"""D-055 on chadlis/hypotrail#75, item 2: the premise sheet of a fix prompt, `.claude/skills/drive/premises.py`.

The sheet is run on a small worktree built in `tmp_path`, with the repository's own resolver (`tests/_architecture.py`) copied in.
"""

import shutil
import textwrap

import pytest

from _drive_scripts import FIXTURES, ROOT, run

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


def test_the_drive_skill_runs_the_premise_sheet_before_it_posts_a_fix_prompt_and_says_how_a_callers_line_is_written():
    lines = (ROOT / ".claude/skills/drive/SKILL.md").read_text().splitlines()
    row = next(line for line in lines if line.startswith("| 6 |"))
    paragraph = next(line for line in lines if line.startswith("**Check the premise before you route.**"))
    assert "after `premises.py` accepts it" in row
    assert "`callers(<package.module.function>) = {<package.module:function>, \u2026}`" in paragraph and "premises.py <prompt file> <worktree>" in paragraph
