"""The order in which every Study writer refuses, and the classification of every leaf command.

The probe calls each writer with an older `--read-sequence`: with the writer lock held by another process, and with the lock free. The
table of the codes it gives is `tests/_order_table.py`; the inventory of locked paths is `tests/_order_inventory.py`; the calls are `tests/_order_probe.py`. The parser walk classifies every leaf command
as a Study writer or a non-writer, and holds the writers equal to the writers the probe calls. No model is called.
"""

import argparse
import contextlib
import importlib
import unittest.mock

import pytest
from _checks_table import rows_of, rows_of_chapter_04
from _architecture import SOURCE
from _locked_paths import calls_after_the_stale_check, first_call_after_the_stale_check, locked_functions, takes_the_read_sequence
from _order_probe import CHECKS_BEFORE_THE_LOCK as CHECK_CALLS
from _order_probe import LOCK_HELD as LOCK_HELD_CALLS
from _order_probe import UNDER_THE_LOCK as UNDER_THE_LOCK_CALLS
from _order_probe import of
from _order_inventory import ENTERS, ENTERS_NONE, LOCK_HELD_ENTERS_NONE, LOCKED_PATHS, SKIPPED_CALLS
from _order_table import AFTER, BEFORE, CHECKS_BEFORE_THE_LOCK, LOCK_HELD, REPLAYED, THE_CHECK, UNDER_THE_LOCK
from test_study_lock import held_by_another_process
from test_write_sequence import seq, tree

from hypotrail.cli import build_parser
from hypotrail.core import scorers


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
        "from hypotrail.core import lock\nfrom hypotrail.core.lock import writer_lock\nfrom hypotrail.core.lock import writer_lock as hold\n\n"
        "def plain(study):\n    with lock.writer_lock(study):\n        pass\n\n"
        "def other_name(study):\n    stack.enter_context(writer_lock(study))\n\n"
        "def renamed(study):\n    with hold(study):\n        pass\n\n"
        "def outer(study):\n    def inner():\n        with lock.writer_lock(study):\n            pass\n\n"
        "def free(study):\n    return lock.is_held(study)\n",
        encoding="utf-8",
    )
    assert locked_functions(tmp_path) == {"pkg.a:plain", "pkg.a:other_name", "pkg.a:renamed", "pkg.a:inner"}


def test_the_search_for_locked_functions_finds_a_lock_taken_through_the_study_write_module_in_its_caller_and_not_the_call_inside_the_module(tmp_path):
    (tmp_path / "hypotrail" / "core").mkdir(parents=True)
    (tmp_path / "hypotrail" / "ml").mkdir()
    (tmp_path / "hypotrail" / "core" / "study_write.py").write_text(
        "from hypotrail.core import lock\n\ndef locked(study):\n    with lock.writer_lock(study):\n        yield\n", encoding="utf-8"
    )
    (tmp_path / "hypotrail" / "ml" / "w.py").write_text(
        "from hypotrail.core import study_write\n\ndef writer(study):\n    with study_write.locked(study, 'x', 'r', read_sequence=None):\n        pass\n", encoding="utf-8"
    )
    assert locked_functions(tmp_path) == {"hypotrail.ml.w:writer"}


def test_the_calls_after_the_stale_check_follow_the_replay_step_of_the_study_write_module_that_runs_it(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text(
        "def locked(study, write):\n    with study_write.locked(study, 'x', 'r', read_sequence=None):\n        return _held(study, write)\n\n"
        "def _held(study, write):\n    before()\n    recorded = write.replay_attempt(check)\n    first()\n",
        encoding="utf-8",
    )
    assert calls_after_the_stale_check(tmp_path, "pkg.m:locked", stale_check_in="_held") == ["first"]


def test_every_locked_path_has_its_lock_held_row_and_every_path_that_takes_the_read_sequence_has_its_after_row():
    assert not set(LOCK_HELD_ENTERS_NONE) & {path["lock_held"] for path in LOCKED_PATHS.values()}
    assert all(LOCK_HELD_ENTERS_NONE.values()), "each row of `LOCK_HELD` that has no locked path gives its reason"
    assert sorted([*(path["lock_held"] for path in LOCKED_PATHS.values()), *LOCK_HELD_ENTERS_NONE]) == sorted(LOCK_HELD)
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


@contextlib.contextmanager
def entered(*keys):
    """Wraps each function `module:function` of `keys` (it still runs); yields a function that gives the set of those entered so far."""
    with contextlib.ExitStack() as stack:
        mocks = {}
        for key in keys:
            module, function = key.split(":")
            mocks[key] = stack.enter_context(unittest.mock.patch(f"{module}.{function}", wraps=getattr(importlib.import_module(module), function)))
        yield lambda: {key for key, mock in mocks.items() if mock.called}


def path_of(row_field, case):
    [key] = [key for key, path in LOCKED_PATHS.items() if path[row_field] == case]
    return key


@pytest.mark.parametrize("case", sorted(set(LOCK_HELD) - set(LOCK_HELD_ENTERS_NONE)))
def test_with_the_lock_held_each_row_enters_the_locked_function_of_its_path_and_no_other_locked_function(case, tmp_path):
    study, call = LOCK_HELD_CALLS[case](tmp_path)
    with held_by_another_process(study), entered(*LOCKED_PATHS) as called:
        call(below(study))
    assert called() == {path_of("lock_held", case)}


def entered_by(call_of_the_row, study, held):
    """The locked functions of `LOCKED_PATHS` that the call enters, with the lock held by another process or free."""
    with (held_by_another_process(study) if held else contextlib.nullcontext()), entered(*LOCKED_PATHS) as called:
        call_of_the_row(below(study))
    return called()


@pytest.mark.parametrize("case", sorted(ENTERS))
def test_each_row_of_the_other_tables_enters_the_locked_function_it_names_and_no_other_locked_function(case, tmp_path):
    held = case in CHECKS_BEFORE_THE_LOCK
    study, call = (CHECK_CALLS if held else UNDER_THE_LOCK_CALLS)[case](tmp_path)
    assert entered_by(call, study, held) == {ENTERS[case]}


@pytest.mark.parametrize("case", sorted(LOCK_HELD_ENTERS_NONE))
def test_each_row_of_the_lock_held_table_that_has_no_locked_path_enters_no_locked_function(case, tmp_path):
    study, call = LOCK_HELD_CALLS[case](tmp_path)
    assert entered_by(call, study, True) == set()


@pytest.mark.parametrize("case", sorted(ENTERS_NONE))
def test_each_row_that_is_refused_before_any_locked_function_enters_none(case, tmp_path):
    held = case in CHECKS_BEFORE_THE_LOCK
    study, call = (CHECK_CALLS if held else UNDER_THE_LOCK_CALLS)[case](tmp_path)
    assert entered_by(call, study, held) == set()


def test_the_checks_before_the_lock_and_the_checks_under_it_share_no_case():
    assert not set(CHECKS_BEFORE_THE_LOCK) & set(UNDER_THE_LOCK)


def test_every_row_of_the_two_tables_names_a_locked_function_of_its_writer_or_gives_the_reason_none_is_entered():
    rows = {**{case: writer for case, (writer, _, _) in CHECKS_BEFORE_THE_LOCK.items()}, **{case: row[0] for case, row in UNDER_THE_LOCK.items()}}
    assert not set(ENTERS) & set(ENTERS_NONE)
    assert set(ENTERS) | set(ENTERS_NONE) == set(rows)
    assert all(ENTERS_NONE.values()), "each row that enters none gives its reason"
    for case, key in ENTERS.items():
        assert LOCKED_PATHS[key]["writer"] == rows[case], case
    for key, path in LOCKED_PATHS.items():
        if path["after"]:
            assert ENTERS[path["after"]] == key


# `tests/_order_inventory.py` (`SKIPPED_CALLS`) rests on the two routing tests below for the calls it skips because the command line picks the module.
NEW_REVISION = ("hypotrail.ml.study:new_revision", "hypotrail.agentic.study:new_revision")
ASSESS = ("hypotrail.ml.assess:assess", "hypotrail.agentic.assess:assess")


@pytest.mark.parametrize(("world", "module"), [("bike", NEW_REVISION[0]), ("chinook", NEW_REVISION[1])])
def test_init_new_revision_enters_the_new_revision_of_the_track_of_the_study_and_not_the_other(world, module, tmp_path):
    study, call = of("init --new-revision", world=world)(tmp_path)
    with held_by_another_process(study), entered(*NEW_REVISION) as called:
        call(below(study))
    assert called() == {module}


@pytest.mark.parametrize("scorer", [*sorted(scorers.REGISTRY), "not_a_scorer"])
def test_assess_enters_the_agentic_module_for_a_registered_agentic_scorer_and_the_regression_module_for_any_other_scorer(scorer, tmp_path):
    agentic = scorer in scorers.REGISTRY and scorers.REGISTRY[scorer].domain == scorers.AGENTIC
    study, call = of("assess", **{"--scorer": scorer})(tmp_path)
    with held_by_another_process(study), entered(*ASSESS) as called:
        call(below(study))
    assert called() == {ASSESS[1] if agentic else ASSESS[0]}


@pytest.mark.parametrize("case", sorted(LOCK_HELD))
def test_with_the_lock_held_and_an_older_value_each_row_gives_the_exit_code_and_code_that_LOCK_HELD_names_and_writes_nothing(case, tmp_path):
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
    "numbers check": NON_WRITER,
    "figures": NON_WRITER,
    "profile": NON_WRITER,
    "lesson": NON_WRITER,
    "decide": WRITER,
    "deviation": WRITER,
    "review import": WRITER,
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
