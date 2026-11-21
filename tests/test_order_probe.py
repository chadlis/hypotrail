"""The order in which every Study writer refuses, and the classification of every leaf command.

The probe calls each writer with an older `--read-sequence`: with the writer lock held by another process, and with the lock free. The
table of the codes it gives is `tests/_order_table.py`; the calls are `tests/_order_probe.py`. The parser walk classifies every leaf command
as a Study writer or a non-writer, and holds the writers equal to the writers the probe calls. No model is called.
"""

import argparse
import re
from pathlib import Path

import pytest
from _order_probe import CHECKS_BEFORE_THE_LOCK as CHECK_CALLS
from _order_probe import LOCK_HELD as LOCK_HELD_CALLS
from _order_probe import UNDER_THE_LOCK as UNDER_THE_LOCK_CALLS
from _order_table import AFTER, BEFORE, CHECKS_BEFORE_THE_LOCK, LOCK_HELD, REPLAYED, THE_CHECK, UNDER_THE_LOCK
from test_study_lock import held_by_another_process
from test_write_sequence import seq, tree

from hypotrail.cli import build_parser

CHAPTER_04 = Path(__file__).resolve().parent.parent / "docs" / "handbook" / "chapters" / "04-study-and-attempts.html"


def result_of(payload):
    """The error code of a refusal, or `REPLAYED` for the recorded record a replay returns."""
    if payload["ok"]:
        assert payload["replayed"] is True, payload
        return REPLAYED
    return payload["error"]["code"]


def below(study):
    """A `--read-sequence` below the Study's Write sequence (0 for a folder that holds no Study yet)."""
    return max(seq(study) - 2, 0)


def test_every_row_of_the_table_has_a_call_and_every_call_a_row():
    assert set(LOCK_HELD_CALLS) == set(LOCK_HELD)
    assert set(CHECK_CALLS) == set(CHECKS_BEFORE_THE_LOCK)
    assert set(UNDER_THE_LOCK_CALLS) == set(UNDER_THE_LOCK)


def test_every_writer_that_takes_the_option_has_a_row_with_the_lock_free():
    assert {writer for writer, _, _ in LOCK_HELD.values()} - {"init"} == {writer for writer, _, _, _ in UNDER_THE_LOCK.values()}


@pytest.mark.parametrize("case", sorted(LOCK_HELD))
def test_with_the_lock_held_and_an_older_value_each_writer_whose_arguments_pass_gives_study_locked_and_writes_nothing(case, tmp_path):
    _, exit_code, code = LOCK_HELD[case]
    study, call = LOCK_HELD_CALLS[case](tmp_path)
    files = tree(study)
    with held_by_another_process(study):
        got, payload, err = call(below(study))
    assert (got, result_of(payload)) == (exit_code, code), (payload, err)
    assert tree(study) == files


@pytest.mark.parametrize("case", sorted(CHECKS_BEFORE_THE_LOCK))
def test_with_the_lock_held_and_an_older_value_each_check_before_the_lock_gives_its_code_and_writes_nothing(case, tmp_path):
    _, exit_code, code = CHECKS_BEFORE_THE_LOCK[case]
    study, call = CHECK_CALLS[case](tmp_path)
    files = tree(study)
    with held_by_another_process(study):
        got, payload, err = call(below(study))
    assert (got, result_of(payload)) == (exit_code, code), (payload, err)
    assert tree(study) == files


@pytest.mark.parametrize("case", sorted(UNDER_THE_LOCK))
def test_with_the_lock_free_and_an_older_value_each_check_gives_its_place_relative_to_the_stale_check_and_writes_nothing(case, tmp_path):
    writer, place, (exit_code, code), current = UNDER_THE_LOCK[case]
    assert place in (BEFORE, THE_CHECK, AFTER)
    study, call = UNDER_THE_LOCK_CALLS[case](tmp_path)
    files = tree(study)
    got, payload, err = call(below(study))
    assert (got, result_of(payload)) == (exit_code, code), (payload, err)
    assert tree(study) == files
    if current is not None:
        got, payload, err = call(seq(study))
        assert (got, result_of(payload)) == current, (payload, err)
        assert tree(study) == files


# --- the table `checks-before-the-lock` of chapter 04 -------------------------------------------------------------------------


def rows_of_the_chapter_table():
    """{check: (exit code, error code)} of the table `checks-before-the-lock`."""
    table = re.search(r'<table[^>]*id="checks-before-the-lock".*?</table>', CHAPTER_04.read_text(encoding="utf-8"), re.S)
    assert table, "chapter 04 has no table `checks-before-the-lock`"
    return {check: (int(exit_code), code) for check, exit_code, code in re.findall(r'<tr data-command="([^"]+)" data-exit="(\d+)" data-code="([^"]+)"', table[0])}


def test_the_table_of_the_checks_before_the_lock_lists_the_checks_the_probe_provokes_and_no_other():
    provoked = {case: (exit_code, code) for case, (_, exit_code, code) in CHECKS_BEFORE_THE_LOCK.items()}
    assert rows_of_the_chapter_table() == provoked


# --- every leaf command is a Study writer or is not ---------------------------------------------------------------------------

WRITER, NON_WRITER = "Study writer", "non-writer"

# A leaf command of `build_parser()` writes to a Study or does not. `init` is one leaf: it creates a Study, or adds a revision to one
# (`--new-revision`). `data fetch` writes to a folder that is no Study, `spike live` to its `--out`.
LEAF_COMMANDS = {
    "data verify": NON_WRITER,
    "data fetch": NON_WRITER,
    "init": WRITER,
    "run ml": WRITER,
    "run agent": WRITER,
    "import ml": WRITER,
    "import agent": WRITER,
    "assess": WRITER,
    "compare": WRITER,
    "status": NON_WRITER,
    "decide": WRITER,
    "recover": WRITER,
    "report": WRITER,
    "spike live": NON_WRITER,
}


def leaf_commands(parser, path=()):
    """The command lines of the parser that take no further command, as `data verify` or `status`."""
    sub = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
    if not sub:
        yield " ".join(path)
        return
    for name, child in sub[0].choices.items():
        yield from leaf_commands(child, (*path, name))


def leaf_of(writer):
    return writer.replace(" --new-revision", "")


def test_every_leaf_command_of_the_parser_is_classified_and_every_classified_command_is_a_leaf():
    assert set(leaf_commands(build_parser())) == set(LEAF_COMMANDS)


def test_the_study_writers_of_the_list_are_the_writers_the_probe_calls():
    probed = {leaf_of(writer) for table in (LOCK_HELD, CHECKS_BEFORE_THE_LOCK) for writer, _, _ in table.values()}
    probed |= {leaf_of(writer) for writer, _, _, _ in UNDER_THE_LOCK.values()}
    assert {command for command, kind in LEAF_COMMANDS.items() if kind == WRITER} == probed
