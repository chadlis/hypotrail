"""What the Study-write module owns, read in the code of `src` with the standard library `ast` (see `tests/_architecture.py` for how a call is resolved).

Each check takes the root of a source tree, so the same check runs on `src` and on a tree planted with one violation. No model is called.
"""

import ast
from pathlib import Path

import pytest
from _architecture import SOURCE, calls, defined_functions, dotted, innermost_owners_in, names_of, owners_in, parse_all, receiver_violations, reached_from, resolve, write_bindings
from _order_inventory import LOCKED_PATHS

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


READ_SEQUENCE_FAULT = f"{WRITE_JOURNAL}.read_sequence_fault"
# `check_read_sequence` judges `--read-sequence` for the library callers of a writer; `_read_sequence_value` is the `type=` of `--read-sequence` on every command, so the command line judges it at parse time.
READ_SEQUENCE_FAULT_CALLERS = {f"{STUDY_WRITE}:check_read_sequence", "hypotrail.cli:_read_sequence_value"}


READ_SEQUENCE_VALUE = "hypotrail.cli._read_sequence_value"


def read_sequence_value_uses(root) -> list:
    """The functions that use `_read_sequence_value` as the value of a `type=` keyword argument."""
    return sorted(site for site, ok in read_sequence_value_references(root) if ok)


def read_sequence_value_violations(root) -> list:
    """The uses of `_read_sequence_value` (by any spelling that resolves to it) that are not the value of a `type=` keyword argument."""
    return sorted(
        f"{owner} uses `{spelling}` other than as the value of `type=`" for owner, ok, spelling in read_sequence_value_references(root, spelled=True) if not ok
    )


def read_sequence_value_references(root, spelled: bool = False) -> list:
    found = []
    for module, tree in parse_all(root).items():
        names, owners = names_of(module, tree), innermost_owners_in(module, tree)
        parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            parent = parents.get(id(node))
            if not isinstance(node, (ast.Name, ast.Attribute)) or not isinstance(node.ctx, ast.Load) or isinstance(parent, ast.Attribute) or resolve(names, dotted(node)) != READ_SEQUENCE_VALUE:
                continue
            ok = isinstance(parent, ast.keyword) and parent.arg == "type"
            found.append((owners[id(node)], ok, ast.unparse(node)) if spelled else (owners[id(node)], ok))
    return found


def guard_violations(root) -> list:
    """The calls of `read_sequence_fault` from a function other than the two of `READ_SEQUENCE_FAULT_CALLERS`, and the places that raise `REQUEST_ID_EMPTY` besides `check_arguments`."""
    trees = parse_all(root)
    found = [
        f"{site.owner} calls {site.callee}"
        for site in calls(trees)
        if site.callee == READ_SEQUENCE_FAULT and site.owner not in READ_SEQUENCE_FAULT_CALLERS
    ]
    for module, tree in trees.items():
        for node, owner in owners_in(module, tree):
            if isinstance(node, ast.Constant) and node.value == "REQUEST_ID_EMPTY" and owner != f"{STUDY_WRITE}:check_arguments":
                found.append(f"{owner} names REQUEST_ID_EMPTY")
    return found


def test_read_sequence_fault_is_called_by_check_read_sequence_and_the_parse_time_check_only_and_REQUEST_ID_EMPTY_is_raised_from_check_arguments_only():
    assert guard_violations(SOURCE) == []
    callers = {site.owner for site in calls(parse_all(SOURCE)) if site.callee == READ_SEQUENCE_FAULT}
    assert callers == READ_SEQUENCE_FAULT_CALLERS  # a check that finds no call anywhere would pass as well
    constants = [
        owner
        for module, tree in parse_all(SOURCE).items()
        for node, owner in owners_in(module, tree)
        if isinstance(node, ast.Constant) and node.value == "REQUEST_ID_EMPTY"
    ]
    assert constants == [f"{STUDY_WRITE}:check_arguments"]


def test_the_guard_check_finds_a_call_of_read_sequence_fault_through_an_import_in_another_function_of_the_command_line_and_a_second_raise_of_REQUEST_ID_EMPTY_and_accepts_the_two_callers(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/core/study_write.py": "from hypotrail.core import write_journal\n\ndef check_arguments(c, r, i):\n    raise E('REQUEST_ID_EMPTY')\n\n"
        "def check_read_sequence(c, r):\n    return write_journal.read_sequence_fault(r)\n",
        "hypotrail/cli.py": "from hypotrail.core import write_journal\n\ndef _read_sequence_value(r):\n    return write_journal.read_sequence_fault(r)\n\n"
        "def v(r):\n    return write_journal.read_sequence_fault(r)\n",
        "hypotrail/ml/a.py": "from hypotrail.core import write_journal as wj\n\ndef w(r):\n    wj.read_sequence_fault(r)\n",
        "hypotrail/ml/b.py": "def w(i):\n    if not i:\n        raise E('REQUEST_ID_EMPTY')\n",
    })
    assert guard_violations(root) == [
        "hypotrail.cli:v calls hypotrail.core.write_journal.read_sequence_fault",
        "hypotrail.ml.a:w calls hypotrail.core.write_journal.read_sequence_fault",
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


# --- the command names and the journal kinds -------------------------------------------------------------------------------------


def study_write_signatures(trees: dict) -> dict:
    """{entry: its parameters, without `self`} for the public functions of the Study-write module and the public methods of its classes (`Write.wrote`)."""
    found = {}
    for node in trees[STUDY_WRITE].body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            found[node.name] = [a.arg for a in node.args.args]
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            for method in node.body:
                if isinstance(method, ast.FunctionDef) and not method.name.startswith("_"):
                    found[f"{node.name}.{method.name}"] = [a.arg for a in method.args.args if a.arg != "self"]
    return found


def study_write_constants(trees: dict) -> set:
    return {
        f"{STUDY_WRITE}.{node.targets[0].id}"
        for node in trees[STUDY_WRITE].body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id.isupper()
        and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }


def entry_called(site, signatures: dict) -> str | None:
    """The entry of the Study-write module that `site` calls, or None."""
    if site.callee is not None and site.callee.startswith(STUDY_WRITE + "."):
        return site.callee[len(STUDY_WRITE) + 1:]
    if site.raw is not None and site.raw.startswith(WRITE_RECEIVER + "."):
        entry = f"Write.{site.raw.split('.', 1)[1]}"
        return entry if entry in signatures else None
    return None


def literal_violations(root) -> list:
    """The calls into the Study-write module outside it that give a `command` or a `kind` as anything but one of its constants."""
    trees = parse_all(root)
    signatures, constants = study_write_signatures(trees), study_write_constants(trees)
    names = {module: names_of(module, tree) for module, tree in trees.items()}
    found = []
    for site in calls(trees):
        entry = entry_called(site, signatures)
        if entry is None or site.module == STUDY_WRITE:
            continue
        bound = {**dict(zip(signatures[entry], site.node.args)), **{kw.arg: kw.value for kw in site.node.keywords}}
        for parameter in ("command", "kind"):
            argument = bound.get(parameter)
            if argument is not None and resolve(names[site.module], dotted(argument)) not in constants:
                found.append(f"{site.owner} gives `{parameter}` of {entry} as {ast.unparse(argument)}")
    return found


def test_no_call_into_the_study_write_module_gives_a_command_or_a_kind_as_anything_but_one_of_its_constants():
    assert literal_violations(SOURCE) == []
    trees = parse_all(SOURCE)
    signatures = study_write_signatures(trees)
    checked = {entry_called(site, signatures) for site in calls(trees) if site.module != STUDY_WRITE}
    assert {"locked", "check_arguments", "check_read_sequence", "Write.wrote"} <= checked  # the check reaches the calls it is about


def test_the_literal_check_finds_a_string_in_place_of_a_command_or_a_kind_and_accepts_a_constant_by_name_alias_or_import(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/core/study_write.py": "RUN = 'run'\nFREEZE = 'freeze'\n\ndef locked(study, command, request_id=None):\n    pass\n\n"
        "class Write:\n    def wrote(self, kind, identifier):\n        pass\n",
        "hypotrail/ml/ok.py": "from hypotrail.core import study_write\nfrom hypotrail.core.study_write import FREEZE as F\n\nCOMMAND = study_write.RUN\n\n"
        "def w(study, write):\n    with study_write.locked(study, COMMAND, 'r'):\n        write.wrote(F, 'x')\n",
        "hypotrail/ml/bad.py": "from hypotrail.core import study_write\n\ndef w(study, write):\n    with study_write.locked(study, command='assess'):\n        write.wrote('assessment', 'x')\n",
    })
    assert literal_violations(root) == [
        "hypotrail.ml.bad:w gives `command` of locked as 'assess'",
        "hypotrail.ml.bad:w gives `kind` of Write.wrote as 'assessment'",
    ]


# --- the receiver of every Write is spelled `write` ------------------------------------------------------------------------------


LOCKED = f"{STUDY_WRITE}.locked"


def test_under_src_locked_is_only_the_item_of_a_with_that_binds_write_and_write_is_used_only_in_closed_ways_inside_its_block_and_Write_is_built_only_in_its_module():
    """The receiver of a Write is held in the closed ways of `receiver_violations`. Patterns that the check still cannot see, which no code under `src` uses:

    - a function or lambda defined inside the block that calls a method of the Write and is then used after the block (returned, stored, called later);
    - the value that a method of the Write returns is not followed, so a method that returned the Write itself would hide it;
    - a factory or a class reached by `getattr(module, "locked")`, `getattr(module, "Write")` or any other lookup by a string, a subclass of `Write` that is then built, and `Write.__new__`;
    - a factory or a class that the module gets through a star import, which the resolver does not follow;
    - references that are the base of an attribute, such as `study_write.locked.__wrapped__(study, "x")`;
    - references passed on without a call, such as `functools.partial(study_write.Write)`;
    - Python's scope declarations and comprehension bindings, such as a function that declares `nonlocal write` or `global write` and reads it, or a comprehension that binds `write`;
    - closures returned from a helper, such as `g(write)` that returns a closure over `write`, called after the block;
    - `type=` checked by keyword name only, such as `_read_sequence_value` passed as `type=` to a call other than argparse's `add_argument`.

    These are stated limits. A later escape that code under `src` actually uses is a blocker.
    """
    assert receiver_violations(SOURCE, LOCKED, WRITE_RECEIVER) == []
    bound = [binding.target.id for binding in write_bindings(parse_all(SOURCE), LOCKED) if isinstance(binding.target, ast.Name)]
    assert bound and set(bound) == {WRITE_RECEIVER}  # a check that finds no `with` would pass as well


def test_the_receiver_check_finds_a_Write_bound_as_another_name_a_helper_that_takes_it_under_another_name_however_deep_and_every_use_that_is_not_closed(tmp_path):
    head = "from hypotrail.core import study_write\n\n"
    root = plant(tmp_path, {
        "hypotrail/core/study_write.py": "def locked(study, command):\n    pass\n",
        "hypotrail/ml/ok.py": head
        + "def f(study):\n    with study_write.locked(study, 'x') as write:\n        write.wrote('k', 'i')\n        return g(study, write)\n\n"
        "def g(study, write, /):\n    def inner(write):\n        return write.wrote('k', 'i')\n\n    return inner(write)\n\n"
        "class C:\n    def m(self, study):\n        with study_write.locked(study, 'x') as write:\n            self.n(write=write)\n\n"
        "    def n(self, write):\n        return write.wrote('k', 'i')\n",
        "hypotrail/ml/bound.py": head + "def f(study):\n    with study_write.locked(study, 'x') as w:\n        w.wrote('k', 'i')\n",
        "hypotrail/ml/helper.py": head
        + "def f(study):\n    with study_write.locked(study, 'x') as write:\n        return g(study, write)\n\n"
        "def g(study, w):\n    return h(study, w)\n\n"
        "def h(study, session):\n    return session.wrote('k', 'i')\n",
        "hypotrail/ml/nested.py": head
        + "def f(study):\n    with study_write.locked(study, 'x') as write:\n        def helper(w):\n            return w.wrote('k', 'i')\n\n        return helper(write)\n",
        "hypotrail/ml/rebound.py": head + "def f(study):\n    with study_write.locked(study, 'x') as write:\n        w = write\n        w.wrote('assessment', 'i')\n",
        "hypotrail/ml/starred.py": head
        + "def f(study):\n    with study_write.locked(study, 'x') as write:\n        return g(study, *(write,))\n\ndef g(study, write):\n    return write\n",
        "hypotrail/ml/unresolved.py": head + "def f(study, other):\n    with study_write.locked(study, 'x') as write:\n        return other.take(write)\n",
        "hypotrail/ml/stored.py": head + "def f(study, box):\n    with study_write.locked(study, 'x') as write:\n        box.write = write\n        return write.count\n",
    })
    assert receiver_violations(root, LOCKED, WRITE_RECEIVER) == [
        "hypotrail.ml.bound:f binds the Write as `w`",
        "hypotrail.ml.helper.g receives the Write as `w`",
        "hypotrail.ml.helper.h receives the Write as `session`",
        "hypotrail.ml.nested.f.helper receives the Write as `w`",
        "hypotrail.ml.rebound:f uses the Write in `w = write`",
        "hypotrail.ml.starred:f uses the Write in `(write,)`",
        "hypotrail.ml.stored:f uses the Write in `box.write = write`",
        "hypotrail.ml.stored:f uses the Write in `write.count`",
        "hypotrail.ml.unresolved:f passes the Write to a call that does not resolve: `other.take(write)`",
    ]


HEAD = "from hypotrail.core import study_write\n\n"


def test_the_receiver_check_finds_a_Write_used_after_its_block_a_function_that_captures_it_a_locked_that_is_not_the_item_of_a_with_and_a_Write_built_outside_its_module(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/core/study_write.py": "def locked(study, command):\n    pass\n\nclass Write:\n    pass\n\ndef built():\n    return Write()\n",
        "hypotrail/ml/ok.py": HEAD
        + "def f(study):\n    with study_write.locked(study, 'x') as write:\n        write.wrote('k', 'i')\n    with study_write.locked(study, 'y') as write:\n        write.wrote('k', 'i')\n"
        "    with study_write.locked(study, 'z'):\n        pass\n\ndef g(write):\n    return write.wrote('k', 'i')\n\ndef h(study):\n    def own(write):\n        return write.wrote('k', 'i')\n\n"
        "    with study_write.locked(study, 'x') as write:\n        return own(write)\n",
        "hypotrail/ml/after.py": HEAD + "def f(study):\n    with study_write.locked(study, 'x') as write:\n        write.wrote('k', 'i')\n    w = write\n    return w\n",
        "hypotrail/ml/captured.py": HEAD
        + "def f(study):\n    def peek():\n        return write.count\n\n    with study_write.locked(study, 'x') as write:\n        peek()\n",
        "hypotrail/ml/stored.py": HEAD + "def f(study):\n    cm = study_write.locked(study, 'x')\n    with cm as w:\n        w.wrote('k', 'i')\n",
        "hypotrail/ml/passed.py": HEAD + "def f(study, stack):\n    return stack.enter_context(study_write.locked(study, 'x'))\n",
        "hypotrail/ml/referred.py": HEAD + "import functools\n\ndef f(study):\n    return functools.partial(study_write.locked, study)\n",
        "hypotrail/ml/built.py": HEAD + "from hypotrail.core.study_write import Write as W\n\ndef f(study):\n    return study_write.Write(), W()\n",
    })
    assert receiver_violations(root, LOCKED, WRITE_RECEIVER) == [
        "hypotrail.ml.after:f uses the Write `write` outside its block",
        "hypotrail.ml.built:f constructs the Write: `W()`",
        "hypotrail.ml.built:f constructs the Write: `study_write.Write()`",
        "hypotrail.ml.captured:peek uses the Write `write` outside its block",
        "hypotrail.ml.passed:f uses `study_write.locked(study, 'x')` other than as the item of a `with`",
        "hypotrail.ml.referred:f uses `study_write.locked` other than as the item of a `with`",
        "hypotrail.ml.stored:f uses `study_write.locked(study, 'x')` other than as the item of a `with`",
    ]


def test_the_receiver_check_accepts_a_method_called_through_its_class_with_the_instance_a_classmethod_and_a_staticmethod(tmp_path):
    methods = (
        "class C:\n    @classmethod\n    def k(cls, write):\n        return write.wrote('k', 'i')\n\n"
        "    @staticmethod\n    def s(write):\n        return write.wrote('k', 'i')\n\n"
        "    def n(self, write):\n        return write.wrote('k', 'i')\n\n"
    )
    root = plant(tmp_path, {
        "hypotrail/core/study_write.py": "def locked(study, command):\n    pass\n",
        "hypotrail/ml/through_class.py": HEAD + methods
        + "    def m(self, study):\n        with study_write.locked(study, 'x') as write:\n            C.n(self, write)\n            C.n(self, write=write)\n",
        "hypotrail/ml/class_and_static.py": HEAD + methods
        + "    def m(self, study):\n        with study_write.locked(study, 'x') as write:\n            self.k(write)\n            C.k(write)\n            self.s(write)\n            C.s(write)\n",
    })
    assert receiver_violations(root, LOCKED, WRITE_RECEIVER) == []


def test_the_read_sequence_value_of_the_command_line_is_used_as_a_type_argument_only_and_never_called():
    assert read_sequence_value_violations(SOURCE) == []
    assert read_sequence_value_uses(SOURCE) == ["hypotrail.cli:_add_read_sequence"]  # a check that finds no use would pass as well


def test_the_read_sequence_value_check_finds_a_direct_call_a_copy_and_a_use_from_another_module_and_accepts_the_type_argument(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/cli.py": "def _read_sequence_value(t):\n    return t\n\ndef add(p):\n    p.add_argument('--read-sequence', type=_read_sequence_value)\n\n"
        "def direct(t):\n    return _read_sequence_value(t)\n\ndef copy():\n    f = _read_sequence_value\n    return f\n",
        "hypotrail/ml/a.py": "from hypotrail import cli\n\ndef w(p, t):\n    p.add_argument('x', type=cli._read_sequence_value)\n    return cli._read_sequence_value(t)\n",
        "hypotrail/ml/b.py": "from hypotrail.cli import _read_sequence_value as v\n\ndef w(t):\n    return v(t)\n",
    })
    assert read_sequence_value_violations(root) == [
        "hypotrail.cli:copy uses `_read_sequence_value` other than as the value of `type=`",
        "hypotrail.cli:copy uses `f` other than as the value of `type=`",
        "hypotrail.cli:direct uses `_read_sequence_value` other than as the value of `type=`",
        "hypotrail.ml.a:w uses `cli._read_sequence_value` other than as the value of `type=`",
        "hypotrail.ml.b:w uses `v` other than as the value of `type=`",
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


# --- no pass-through -------------------------------------------------------------------------------------------------------------

# The public entries of the Study-write module that fewer than two Study writers call, each with its reason.
ONE_WRITER = {
    "Write.replay_decision": "only `decide` records a decision: no other writer replays one",
    "invalid_arguments": "`decide` builds its own INVALID_ARGUMENTS refusals (the author, `--read-sequence` required, `--artifact` required); no other writer has one",
}


def callers_by_entry(root, writers: dict) -> dict:
    """{public entry of the Study-write module: the writers (commands) from which it is called}, by what each writer runs, outside the module.

    `writers` is {`module:function` of a locked function: the command it writes}. A function that a writer's function calls, in any module of `src`, runs from that writer.
    """
    trees = parse_all(root)
    sites, defined = calls(trees), defined_functions(trees)
    signatures = study_write_signatures(trees)
    reach = {command: reached_from(sites, defined, [key for key, c in writers.items() if c == command], stop_in=STUDY_WRITE) for command in set(writers.values())}
    found: dict = {entry: set() for entry in signatures}
    for site in sites:
        entry = entry_called(site, signatures)
        if entry is None or site.module == STUDY_WRITE:
            continue
        found[entry] |= {command for command, runs in reach.items() if site.owner.replace(":", ".") in runs}
    return found


def pass_throughs(root, writers: dict, exceptions: dict) -> list:
    """The entries called from fewer than two writers and not named in `exceptions`, and the exceptions that two writers call after all."""
    callers = callers_by_entry(root, writers)
    return sorted(
        [f"{entry} is called from {sorted(commands)}" for entry, commands in callers.items() if len(commands) < 2 and entry not in exceptions]
        + [f"{entry} is named as an exception but is called from {sorted(callers[entry])}" for entry in exceptions if len(callers.get(entry, ())) >= 2]
    )


def test_every_public_entry_of_the_study_write_module_is_called_from_at_least_two_study_writers_apart_from_the_named_exceptions():
    writers = {key: path["writer"] for key, path in LOCKED_PATHS.items()}
    assert pass_throughs(SOURCE, writers, ONE_WRITER) == []
    callers = callers_by_entry(SOURCE, writers)
    assert {entry for entry, commands in callers.items() if len(commands) < 2} == set(ONE_WRITER)
    assert all(ONE_WRITER.values())
    assert len(ONE_WRITER) <= 2


def test_the_pass_through_check_finds_an_entry_that_one_writer_calls_through_a_helper_and_an_exception_that_two_writers_call(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/core/study_write.py": "def shared(c):\n    pass\n\ndef hook(c):\n    pass\n\ndef named(c):\n    pass\n\n"
        "class Write:\n    def begin(self):\n        pass\n\n    def only_here(self):\n        pass\n",
        "hypotrail/ml/a.py": "from hypotrail.core import study_write\n\ndef first(s, write):\n    study_write.shared(1)\n    study_write.named(1)\n    help_(write)\n\n"
        "def help_(write):\n    write.begin()\n    study_write.hook(1)\n    write.only_here()\n",
        "hypotrail/ml/b.py": "from hypotrail.core import study_write\n\ndef second(s, write):\n    study_write.shared(1)\n    study_write.named(1)\n    write.begin()\n",
    })
    writers = {"hypotrail.ml.a:first": "a", "hypotrail.ml.b:second": "b"}
    assert pass_throughs(root, writers, {"named": "a reason"}) == [
        "Write.only_here is called from ['a']",
        "hook is called from ['a']",
        "named is named as an exception but is called from ['a', 'b']",
    ]


# --- the steps the module owns -----------------------------------------------------------------------------------------------------

OWNED_STEPS = tuple(
    f"hypotrail.core.{module}.{function}"
    for module, function in (
        ("lock", "writer_lock"),
        ("write_journal", "writing"),
        ("write_journal", "require_current"),
        ("write_journal", "begin"),
        ("write_journal", "wrote"),
        ("write_journal", "attempt"),
    )
)


def owned_step_violations(root) -> list:
    """The calls, outside the Study-write module, of the steps it owns: the lock, the journal's session, the stale check and the entries."""
    return [f"{site.owner} calls {site.callee}" for site in calls(parse_all(root)) if site.callee in OWNED_STEPS and site.module != STUDY_WRITE]


def test_no_function_outside_the_study_write_module_takes_the_lock_opens_the_journal_runs_the_stale_check_or_appends_an_entry():
    assert owned_step_violations(SOURCE) == []
    inside = {site.callee for site in calls(parse_all(SOURCE)) if site.module == STUDY_WRITE}
    assert set(OWNED_STEPS) - {f"hypotrail.core.write_journal.{name}" for name in ("begin", "wrote", "attempt")} <= inside


def test_the_owned_steps_check_finds_a_call_of_the_old_begin_and_one_of_the_lock_through_an_import(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/core/exposure.py": "from hypotrail.core import write_journal\n\ndef record():\n    write_journal.begin()\n",
        "hypotrail/ml/a.py": "from hypotrail.core.lock import writer_lock as take\n\ndef w(s):\n    with take(s):\n        pass\n",
        "hypotrail/core/study_write.py": "from hypotrail.core import lock\n\ndef locked(s):\n    with lock.writer_lock(s):\n        pass\n",
    })
    assert owned_step_violations(root) == [
        "hypotrail.core.exposure:record calls hypotrail.core.write_journal.begin",
        "hypotrail.ml.a:w calls hypotrail.core.lock.writer_lock",
    ]
