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


# --- the request_id namespace ----------------------------------------------------------------------------------------------------

NAMESPACE_REFUSALS = (f"{REQUESTS}.conflict_with_a_decision", f"{REQUESTS}.conflict_with_an_attempt")


def namespace_violations(root) -> list:
    """The calls of the two refusals of the shared `request_id` namespace that are made outside the Study-write module."""
    return [f"{site.owner} calls {site.callee}" for site in calls(parse_all(root)) if site.callee in NAMESPACE_REFUSALS and site.module != STUDY_WRITE]


def test_the_guard_on_the_request_id_namespace_is_called_in_both_directions_from_the_study_write_module_only():
    assert namespace_violations(SOURCE) == []
    inside = {site.callee for site in calls(parse_all(SOURCE)) if site.module == STUDY_WRITE}
    assert set(NAMESPACE_REFUSALS) <= inside  # a check that finds no call anywhere would pass as well


def test_the_namespace_check_finds_a_refusal_built_in_the_decisions_module_and_one_built_through_an_alias(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/core/decisions.py": "from hypotrail.core import requests\n\ndef refuse(s, r):\n    raise requests.conflict_with_a_decision(r, 'd')\n",
        "hypotrail/ml/a.py": "from hypotrail.core.requests import conflict_with_an_attempt as clash\n\ndef w(r):\n    raise clash(r, 'a')\n",
    })
    assert namespace_violations(root) == [
        f"hypotrail.core.decisions:refuse calls {REQUESTS}.conflict_with_a_decision",
        f"hypotrail.ml.a:w calls {REQUESTS}.conflict_with_an_attempt",
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


# --- the walk from a manifest to its Observation set -----------------------------------------------------------------------------


def role_constants(trees: dict) -> set:
    """The qualified names of the constants whose value is the role of an Observation set."""
    return {
        f"{module}.{node.targets[0].id}"
        for module, tree in trees.items()
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant) and node.value.value == OBSERVATION_SET_ROLE
    }


def reads_a_role(node) -> bool:
    """`x["role"]` or `x.get("role")`."""
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value == "role"
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and bool(node.args) and (
        isinstance(node.args[0], ast.Constant) and node.args[0].value == "role"
    )


def comparers_of_the_observation_set_role(root) -> set:
    """The functions that compare the role of a ref with the role of an Observation set (a string or a constant that holds it), `==`, `!=` or `in`."""
    trees = parse_all(root)
    constants = role_constants(trees)
    found = set()
    for module, tree in trees.items():
        names = names_of(module, tree)

        def is_the_role(node) -> bool:
            if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                return any(is_the_role(each) for each in node.elts)
            return (isinstance(node, ast.Constant) and node.value == OBSERVATION_SET_ROLE) or resolve(names, dotted(node)) in constants

        for node, owner in owners_in(module, tree):
            if isinstance(node, ast.Compare):
                sides = [node.left, *node.comparators]
                if any(reads_a_role(side) for side in sides) and any(is_the_role(side) for side in sides):
                    found.add(owner)
    return found


# The functions that walk a manifest's `output_refs` to its Observation set, each with its own reading of the record that it finds.
THE_FOUR_WALKS = (
    "hypotrail.core.study:find_observation_set",
    "hypotrail.core.write_journal:_Session._written",
    "hypotrail.core.decisions:held_ids",
    "hypotrail.report.gather:observation_set_of",
)


def test_one_function_of_the_core_compares_the_role_of_an_output_ref_with_the_role_of_an_Observation_set():
    walks = comparers_of_the_observation_set_role(SOURCE)
    assert len(walks) == 1, sorted(walks)
    [walk] = walks
    assert walk.startswith("hypotrail.core.")  # the core imports no other package, and three of the four walks are in it


def test_each_of_the_four_places_that_walked_a_manifest_to_its_Observation_set_calls_the_one_walk():
    walks = comparers_of_the_observation_set_role(SOURCE)
    assert len(walks) == 1, sorted(walks)
    [walk] = walks
    callers = {site.owner for site in calls(parse_all(SOURCE)) if site.callee == walk.replace(":", ".")}
    assert set(THE_FOUR_WALKS) <= callers, sorted(set(THE_FOUR_WALKS) - callers)


def test_the_walk_check_finds_a_comparison_of_a_role_with_a_string_a_constant_a_tuple_and_a_get(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/core/a.py": "ROLE = 'observation_set'\n\ndef by_string(m):\n    return [r for r in m if r['role'] == 'observation_set']\n\n"
        "def by_constant(m):\n    return [r for r in m if r['role'] != ROLE]\n\ndef by_tuple(r):\n    return r.get('role') in ('x', 'observation_set')\n\n"
        "def other(r):\n    return r['role'] == 'observations'\n",
        "hypotrail/report/b.py": "from hypotrail.core.a import ROLE as R\n\ndef by_import(r):\n    return r['role'] == R\n",
    })
    assert comparers_of_the_observation_set_role(root) == {
        "hypotrail.core.a:by_string", "hypotrail.core.a:by_constant", "hypotrail.core.a:by_tuple", "hypotrail.report.b:by_import",
    }


# --- the replay lookups ------------------------------------------------------------------------------------------------------------

REPLAY_LOOKUPS = ("hypotrail.core.study.find_by_request", "hypotrail.core.decisions.find_by_request")


def replay_lookup_violations(root) -> list:
    """The calls of `layout.find_by_request` and of `decisions.find_by_request`, resolved from the function each call names, outside the Study-write module."""
    return [f"{site.owner} calls {site.callee}" for site in calls(parse_all(root)) if site.callee in REPLAY_LOOKUPS and site.module != STUDY_WRITE]


def test_no_writer_calls_a_replay_lookup_outside_the_study_write_module():
    assert replay_lookup_violations(SOURCE) == []
    inside = {site.callee for site in calls(parse_all(SOURCE)) if site.module == STUDY_WRITE}
    assert set(REPLAY_LOOKUPS) <= inside  # a check that finds no call anywhere would pass as well


def test_the_replay_lookup_check_resolves_the_function_through_an_import_an_alias_an_assignment_and_a_bare_name(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/core/decisions.py": "def find_by_request(s, r):\n    return None\n\ndef refuse(s, r):\n    return find_by_request(s, r)\n",
        "hypotrail/core/study.py": "def find_by_request(s, r):\n    return None\n",
        "hypotrail/ml/a.py": "from hypotrail.core import study as layout\n\ndef w(s, r):\n    return layout.find_by_request(s, r)\n",
        "hypotrail/ml/b.py": "from hypotrail.core.study import find_by_request as find\n\ndef w(s, r):\n    return find(s, r)\n",
        "hypotrail/ml/c.py": "import hypotrail.core.decisions as d\n\ndef w(s, r):\n    return d.find_by_request(s, r)\n",
        "hypotrail/ml/d.py": "from hypotrail.core import study\n\nlookup = study.find_by_request\n\ndef w(s, r):\n    return lookup(s, r)\n",
        "hypotrail/ml/e.py": "def find_by_request(s, r):\n    return None\n\ndef w(s, r):\n    return find_by_request(s, r)\n",
        "hypotrail/core/study_write.py": "from hypotrail.core import study as layout\n\ndef w(s, r):\n    return layout.find_by_request(s, r)\n",
    })
    assert replay_lookup_violations(root) == [
        "hypotrail.core.decisions:refuse calls hypotrail.core.decisions.find_by_request",
        "hypotrail.ml.a:w calls hypotrail.core.study.find_by_request",
        "hypotrail.ml.b:w calls hypotrail.core.study.find_by_request",
        "hypotrail.ml.c:w calls hypotrail.core.decisions.find_by_request",
        "hypotrail.ml.d:w calls hypotrail.core.study.find_by_request",
    ]  # `hypotrail.ml.e` defines a function of its own with that name, which is not a replay lookup


