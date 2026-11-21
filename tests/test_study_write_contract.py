"""What the Study-write module owns, read in the code of `src` with the standard library `ast` (see `tests/_resolve.py` for how a call is resolved).

Each check takes the root of a source tree, so the same check runs on `src` and on a tree planted with one violation. No model is called.
"""

import ast
from pathlib import Path

import pytest
from _locked_paths import SOURCE, dotted
from _order_inventory import LOCKED_PATHS
from _resolve import calls, defined_functions, names_of, owners_in, parse_all, reached_from, resolve

STUDY_WRITE = "hypotrail.core.study_write"
WRITE_JOURNAL = "hypotrail.core.write_journal"
REQUESTS = "hypotrail.core.requests"
OBSERVATION_SET_ROLE = "observation_set"
# The name a writer gives the `Write` it was handed: a call of one of its methods is spelled `write.<method>`.
WRITE_RECEIVER = "write"


def plant(root: Path, files: dict) -> Path:
    for path, source in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(source, encoding="utf-8")
    return root


# --- the guard line and the empty request_id -----------------------------------------------------------------------------------


def guard_violations(root) -> list:
    """The places that run the guard line outside the Study-write module, and the places that raise `REQUEST_ID_EMPTY` besides `check_arguments`."""
    trees = parse_all(root)
    found = [
        f"{site.owner} calls {site.callee or site.raw}"
        for site in calls(trees)
        if (site.callee or site.raw or "").rsplit(".", 1)[-1] == "require_valid_read_sequence" and site.module != STUDY_WRITE
    ]
    for module, tree in trees.items():
        for node, owner in owners_in(module, tree):
            if isinstance(node, ast.Constant) and node.value == "REQUEST_ID_EMPTY" and owner != f"{STUDY_WRITE}:check_arguments":
                found.append(f"{owner} names REQUEST_ID_EMPTY")
    return found


def test_the_guard_on_the_read_sequence_is_run_from_the_study_write_module_only_and_REQUEST_ID_EMPTY_is_raised_from_one_place_only():
    assert guard_violations(SOURCE) == []
    constants = [
        owner
        for module, tree in parse_all(SOURCE).items()
        for node, owner in owners_in(module, tree)
        if isinstance(node, ast.Constant) and node.value == "REQUEST_ID_EMPTY"
    ]
    assert constants == [f"{STUDY_WRITE}:check_arguments"]


def test_the_guard_check_finds_a_call_of_the_old_guard_through_an_import_and_a_second_raise_of_REQUEST_ID_EMPTY(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/core/study_write.py": "def check_arguments(c, r, i):\n    raise E('REQUEST_ID_EMPTY')\n",
        "hypotrail/ml/a.py": "from hypotrail.core import write_journal as wj\n\ndef w(r):\n    wj.require_valid_read_sequence(r, 'a')\n",
        "hypotrail/ml/b.py": "def w(i):\n    if not i:\n        raise E('REQUEST_ID_EMPTY')\n",
    })
    assert guard_violations(root) == [
        "hypotrail.ml.a:w calls hypotrail.core.write_journal.require_valid_read_sequence",
        "hypotrail.ml.b:w names REQUEST_ID_EMPTY",
    ]


# --- the builder of an INVALID_ARGUMENTS refusal ---------------------------------------------------------------------------------


def invalid_arguments_builders(root) -> list:
    """The functions that build an `INVALID_ARGUMENTS` refusal in the module that keeps the write journal."""
    found = set()
    for site in calls(parse_all(root)):
        first = site.node.args[0] if site.node.args else None
        if site.module == WRITE_JOURNAL and isinstance(first, ast.Constant) and first.value == "INVALID_ARGUMENTS":
            found.add(site.owner)
    return sorted(found)


def test_the_module_that_keeps_the_write_journal_builds_no_INVALID_ARGUMENTS_refusal():
    assert invalid_arguments_builders(SOURCE) == []
    assert any(  # the Study-write module builds it, so a check that finds no call anywhere would not pass
        site.module == STUDY_WRITE and site.node.args and isinstance(site.node.args[0], ast.Constant) and site.node.args[0].value == "INVALID_ARGUMENTS"
        for site in calls(parse_all(SOURCE))
    )


def test_the_builder_check_finds_an_INVALID_ARGUMENTS_refusal_built_in_the_write_journal_module(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/core/write_journal.py": "def invalid_arguments(m, c):\n    return E('INVALID_ARGUMENTS', m)\n\ndef other():\n    return E('STUDY_CHANGED')\n",
        "hypotrail/core/study_write.py": "def invalid_arguments(m, c):\n    return E('INVALID_ARGUMENTS', m)\n",
    })
    assert invalid_arguments_builders(root) == ["hypotrail.core.write_journal:invalid_arguments"]


