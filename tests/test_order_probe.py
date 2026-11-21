"""The order in which every Study writer refuses, and the classification of every leaf command.

The probe calls each writer with an older `--read-sequence`: with the writer lock held by another process, and with the lock free. The
table of the codes it gives is `tests/_order_table.py`; the calls are `tests/_order_probe.py`. The parser walk classifies every leaf command
as a Study writer or a non-writer, and holds the writers equal to the writers the probe calls. No model is called.
"""

import argparse

import pytest
from _checks_table import rows_of, rows_of_chapter_04
from _locked_paths import SOURCE, calls_after_the_stale_check, first_call_after_the_stale_check, locked_functions, takes_the_read_sequence
from _order_probe import CHECKS_BEFORE_THE_LOCK as CHECK_CALLS
from _order_probe import LOCK_HELD as LOCK_HELD_CALLS
from _order_probe import UNDER_THE_LOCK as UNDER_THE_LOCK_CALLS
from _order_table import AFTER, BEFORE, CHECKS_BEFORE_THE_LOCK, LOCK_HELD, LOCKED_PATHS, REPLAYED, SKIPPED_CALLS, THE_CHECK, UNDER_THE_LOCK
from test_study_lock import held_by_another_process
from test_write_sequence import seq, tree

from hypotrail.cli import build_parser


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


def test_the_inventory_of_locked_paths_is_the_set_of_functions_of_src_that_take_the_writer_lock():
    found = locked_functions(SOURCE)
    assert (found - set(LOCKED_PATHS), set(LOCKED_PATHS) - found) == (set(), set())


def test_the_search_for_locked_functions_finds_a_lock_taken_in_a_with_or_by_another_name_and_attributes_it_to_the_innermost_function(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text(
        "def plain(study):\n    with lock.writer_lock(study):\n        pass\n\n"
        "def other_name(study):\n    stack.enter_context(writer_lock(study))\n\n"
        "def outer(study):\n    def inner():\n        with lock.writer_lock(study):\n            pass\n\n"
        "def free(study):\n    return lock.is_held(study)\n",
        encoding="utf-8",
    )
    assert locked_functions(tmp_path) == {"pkg.a:plain", "pkg.a:other_name", "pkg.a:inner"}


def test_every_locked_path_has_its_lock_held_row_and_every_path_that_takes_the_read_sequence_has_its_after_row():
    assert sorted(path["lock_held"] for path in LOCKED_PATHS.values()) == sorted(LOCK_HELD)
    assert sorted(path["after"] for path in LOCKED_PATHS.values() if path["after"]) == sorted(case for case, row in UNDER_THE_LOCK.items() if row[1] == AFTER)
    for key, path in LOCKED_PATHS.items():
        assert LOCK_HELD[path["lock_held"]][0] == path["writer"], key
        assert takes_the_read_sequence(SOURCE, key) == path["reads_sequence"], key
        assert (path["after"] is not None) == path["reads_sequence"], key
        if path["after"]:
            assert UNDER_THE_LOCK[path["after"]][:2] == (path["writer"], AFTER), key


def after_call(key):
    path = LOCKED_PATHS[key]
    names = calls_after_the_stale_check(SOURCE, key, stale_check_in=path.get("stale_check_in"), then=path.get("then"))
    call, skipped = SKIPPED_CALLS[path["after"]][0], SKIPPED_CALLS[path["after"]][1]
    return names, call, skipped


@pytest.mark.parametrize("key", [key for key, path in LOCKED_PATHS.items() if path["after"]])
def test_the_call_an_after_row_provokes_is_the_first_call_after_the_stale_check_of_its_path_once_the_calls_it_names_as_unable_to_refuse_are_skipped(key):
    names, call, skipped = after_call(key)
    assert all(skipped.values()), "each skipped call gives its reason"
    assert first_call_after_the_stale_check(names, skipped) == (call, []), names


def test_every_after_row_names_its_call():
    assert sorted(SKIPPED_CALLS) == sorted(case for case, row in UNDER_THE_LOCK.items() if row[1] == AFTER)


def test_the_first_call_after_the_stale_check_is_the_first_that_is_not_skipped_and_a_skipped_call_that_stands_later_is_reported():
    assert first_call_after_the_stale_check(["a", "b", "c"], {"a": "x"}) == ("b", [])
    assert first_call_after_the_stale_check(["a", "b", "c"], {"c": "x"}) == ("a", ["c"])


def test_the_calls_after_the_stale_check_follow_the_one_call_that_holds_it_or_the_one_that_comes_after_it(tmp_path):
    folder = tmp_path / "pkg"
    folder.mkdir()
    (folder / "m.py").write_text(
        "def locked(study):\n    with lock.writer_lock(study):\n        return _held(study)\n\n"
        "def _held(study):\n    before()\n    write_journal.require_current(study, 1)\n    first(str(1))\n    second()\n\n"
        "def top(study):\n    with lock.writer_lock(study):\n        write_journal.require_current(study, 1)\n        return _then(study)\n\n"
        "def _then(study):\n    third()\n",
        encoding="utf-8",
    )
    assert calls_after_the_stale_check(tmp_path, "pkg.m:locked", stale_check_in="_held") == ["first", "second"]
    assert calls_after_the_stale_check(tmp_path, "pkg.m:top", then="_then") == ["third"]


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


def test_the_table_of_the_checks_before_the_lock_lists_the_checks_the_probe_provokes_and_no_other():
    provoked = {case: (exit_code, code) for case, (_, exit_code, code) in CHECKS_BEFORE_THE_LOCK.items()}
    assert rows_of_chapter_04() == provoked


def table_of(*rows):
    return f'<table class="tbl" id="checks-before-the-lock"><thead><tr><th>Check</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'


def test_the_table_parser_reads_a_row_whose_attributes_come_in_another_order():
    row = '<tr data-code="A_CODE" data-exit="2" data-command="a check"><td>x</td></tr>'
    assert rows_of(table_of(row)) == {"a check": (2, "A_CODE")}


@pytest.mark.parametrize(
    "row",
    [
        '<tr data-command="a check" data-code="A_CODE"><td>x</td></tr>',
        '<tr data-command="a check" data-exit="two" data-code="A_CODE"><td>x</td></tr>',
        '<tr><td>x</td></tr>',
    ],
    ids=["no exit", "exit not an integer", "no attributes"],
)
def test_the_table_parser_fails_on_a_row_it_cannot_read(row):
    good = '<tr data-command="b" data-exit="2" data-code="B_CODE"><td>x</td></tr>'
    with pytest.raises(AssertionError):
        rows_of(table_of(good, row))


def test_the_table_parser_fails_on_a_check_that_appears_twice():
    row = '<tr data-command="a check" data-exit="2" data-code="A_CODE"><td>x</td></tr>'
    with pytest.raises(AssertionError):
        rows_of(table_of(row, row))


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
