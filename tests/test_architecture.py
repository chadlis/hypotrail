"""The architecture rules, read in the code of `src` through `tests/_architecture.py`.

Each rule is a function of the parsed modules of a source tree, so the same rule runs on `src` and on a tree planted with one violation. No model is called.
"""

import ast
import json

from _architecture import SOURCE, calls, imports, parse_all

PACKAGE = "hypotrail"


def plant(root, files: dict):
    for path, source in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(source, encoding="utf-8")
    return root


def test_the_resolver_finds_the_modules_of_the_subpackages_and_resolves_each_relative_import_to_the_absolute_module_it_names(tmp_path):
    plant(tmp_path, {
        "pkg/__init__.py": "from . import top\nfrom .core import y\n",
        "pkg/top.py": "",
        "pkg/core/__init__.py": "from . import y\n",
        "pkg/core/y.py": "",
        "pkg/agentic/__init__.py": "",
        "pkg/agentic/a.py": "from . import sibling\nfrom ..core import y\nfrom ..core.y import z as renamed\nimport pkg.top as aliased\n",
        "pkg/agentic/deep/__init__.py": "",
        "pkg/agentic/deep/b.py": "from .. import a\nfrom ...core import y\n\ndef f():\n    from . import c\n",
    })
    trees = parse_all(tmp_path)
    assert sorted(trees) == ["pkg", "pkg.agentic", "pkg.agentic.a", "pkg.agentic.deep", "pkg.agentic.deep.b", "pkg.core", "pkg.core.y", "pkg.top"]
    found = imports(trees)
    assert found["pkg"] == {"pkg.top", "pkg.core.y"}
    assert found["pkg.core"] == {"pkg.core.y"}
    assert found["pkg.agentic.a"] == {"pkg.agentic.sibling", "pkg.core.y", "pkg.core.y.z", "pkg.top"}
    assert found["pkg.agentic.deep.b"] == {"pkg.agentic.a", "pkg.core.y", "pkg.agentic.deep.c"}


# --- rule 1: layering ----------------------------------------------------------------------------------------------------------

# Every package and top-level module of `src/hypotrail/`, with its layer: cli is above the Tracks and report, which are above core.
LAYERS = {"cli": "top", "__init__": "top", "__main__": "top", "agentic": "track", "ml": "track", "report": "report", "core": "core"}
# What a layer may import, besides the package that holds the importing module.
MAY_IMPORT = {"track": {"core"}, "report": {"core"}, "core": set()}


def entry_of(module: str) -> str:
    """The package or top-level module of `hypotrail` that holds `module` (`__init__` for `hypotrail` itself)."""
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else "__init__"


def layering_problems(trees: dict) -> list:
    problems = [f"{module} is in no layer of the list" for module in sorted(trees) if entry_of(module) not in LAYERS]
    for module, targets in imports(trees).items():
        if entry_of(module) not in LAYERS or LAYERS[entry_of(module)] == "top":
            continue
        for target in sorted(targets):
            if not target.startswith(PACKAGE + ".") and target != PACKAGE:
                continue
            owner = max((name for name in trees if target == name or target.startswith(name + ".")), key=len)
            if entry_of(owner) != entry_of(module) and LAYERS.get(entry_of(owner)) not in MAY_IMPORT[LAYERS[entry_of(module)]]:
                problems.append(f"{module} imports {target}")
    return problems


def test_no_layer_imports_a_layer_above_it_and_every_package_and_top_level_module_of_src_is_in_the_list():
    assert layering_problems(parse_all(SOURCE)) == []


def test_layering_finds_a_relative_import_of_another_track_a_package_in_no_layer_and_a_top_level_module_in_no_layer(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/__init__.py": "",
        "hypotrail/cli.py": "from hypotrail.agentic import a\n",
        "hypotrail/core/__init__.py": "",
        "hypotrail/core/c.py": "from . import d\n",
        "hypotrail/core/d.py": "",
        "hypotrail/agentic/__init__.py": "",
        "hypotrail/agentic/a.py": "from ..core import c\nfrom . import sibling\n",
        "hypotrail/ml/__init__.py": "",
        "hypotrail/ml/b.py": "from ..core import d\n",
    })
    assert layering_problems(parse_all(root)) == []
    plant(root, {"hypotrail/agentic/a.py": "from ..ml import b\n"})
    assert layering_problems(parse_all(root)) == ["hypotrail.agentic.a imports hypotrail.ml.b"]
    plant(root, {"hypotrail/agentic/a.py": "", "hypotrail/core/c.py": "from ..agentic import a\n", "hypotrail/ml/b.py": "from .. import cli\n"})
    assert layering_problems(parse_all(root)) == ["hypotrail.core.c imports hypotrail.agentic.a", "hypotrail.ml.b imports hypotrail.cli"]
    plant(root, {"hypotrail/core/c.py": "", "hypotrail/ml/b.py": "", "hypotrail/extra/__init__.py": ""})
    assert layering_problems(parse_all(root)) == ["hypotrail.extra is in no layer of the list"]
    plant(root, {"hypotrail/stray.py": ""})
    assert layering_problems(parse_all(root)) == ["hypotrail.extra is in no layer of the list", "hypotrail.stray is in no layer of the list"]


# --- rule 3: the write protocol is called from the Study-write module only ------------------------------------------------------

STUDY_WRITE = "hypotrail.core.study_write"
WRITE_PROTOCOL = {"hypotrail.core.lock.writer_lock", "hypotrail.core.write_journal.require_current", "hypotrail.core.write_journal.writing"}


def write_protocol_calls_outside_the_study_write_module(trees: dict) -> list:
    return [f"{site.owner} calls {site.callee}" for site in calls(trees) if site.callee in WRITE_PROTOCOL and site.module != STUDY_WRITE]


def test_writer_lock_require_current_and_writing_are_called_from_the_study_write_module_only():
    assert write_protocol_calls_outside_the_study_write_module(parse_all(SOURCE)) == []


def test_a_call_of_the_write_protocol_outside_the_study_write_module_counts_through_an_alias_a_renamed_module_and_an_assignment(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/core/lock.py": "def writer_lock(study):\n    pass\n",
        "hypotrail/core/write_journal.py": "def require_current(study, n):\n    pass\n\ndef writing(study, command):\n    pass\n",
        "hypotrail/core/study_write.py": "from hypotrail.core import lock, write_journal\n\ndef locked(study):\n    with lock.writer_lock(study), write_journal.writing(study, 'x'):\n        write_journal.require_current(study, 1)\n",
        "hypotrail/ml/a.py": "from hypotrail.core.lock import writer_lock as hold\n\ndef f(study):\n    with hold(study):\n        pass\n",
        "hypotrail/ml/b.py": "import hypotrail.core.write_journal as journal\n\ndef g(study):\n    journal.require_current(study, 1)\n",
        "hypotrail/ml/c.py": "from hypotrail.core import write_journal\n\ncheck = write_journal.writing\n\ndef h(study):\n    with check(study, 'x'):\n        pass\n",
        "hypotrail/ml/d.py": "from hypotrail.core import lock\n\ndef i(study):\n    return lock.is_held(study)\n",
    })
    assert write_protocol_calls_outside_the_study_write_module(parse_all(root)) == [
        "hypotrail.ml.a:f calls hypotrail.core.lock.writer_lock",
        "hypotrail.ml.b:g calls hypotrail.core.write_journal.require_current",
        "hypotrail.ml.c:h calls hypotrail.core.write_journal.writing",
    ]


# --- rule 4: the Partition roles ------------------------------------------------------------------------------------------------

TRACKS = ("agentic", "ml")
# `core/comparison.py:44-45` and `report/gather.py:14` hold a copy of the role names; where they belong is the question Q2 of #117 leaves open:
# "Where do the core's copies of the role names (`core/comparison.py:44-45`, `report/gather.py:14`) belong, given that the core imports no Track?"
Q2_FILES = {
    "hypotrail.core.comparison": "the core imports no Track, so it cannot read the roles from a partitions module",
    "hypotrail.report.gather": "the report reads no Track's partitions module, so it keeps its own copy",
}


def roles_of(tree) -> tuple:
    """The values of the names listed by `ROLES = (...)` in a partitions module, read from the module."""
    constants = {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)
    }
    [roles] = [node.value for node in tree.body if isinstance(node, ast.Assign) and [t.id for t in node.targets if isinstance(t, ast.Name)] == ["ROLES"]]
    return tuple(constants[name.id] for name in roles.elts)


def role_sets(trees: dict) -> dict:
    return {track: set(roles_of(trees[f"{PACKAGE}.{track}.partitions"])) for track in TRACKS}


def role_literal_problems(trees: dict) -> list:
    roles = role_sets(trees)
    problems = []
    for module, tree in trees.items():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or not any(node.value in held for held in roles.values()):
                continue
            home = {f"{PACKAGE}.{track}.partitions" for track, held in roles.items() if node.value in held}
            if module not in home and module not in Q2_FILES:
                problems.append(f"{module}:{node.lineno} holds the literal {node.value!r}")
    return problems


def strings_of(value):
    """Every string of a JSON value, the keys of its objects included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, each in value.items():
            yield key
            yield from strings_of(each)
    elif isinstance(value, list):
        for each in value:
            yield from strings_of(each)


def schema_problems(agent_schema: dict, ml_schema: dict, roles: dict) -> list:
    problems = []
    named = set(agent_schema["properties"]["cases"]["properties"])
    if named != roles["agentic"]:
        problems.append(f"the agent schema closes `cases` to {sorted(named)}, not to the roles {sorted(roles['agentic'])}")
    held = sorted(set(strings_of(ml_schema)) & set().union(*roles.values()))
    if held:
        problems.append(f"the ml schema holds the role names {held}")
    return problems


def load_schemas(root) -> tuple:
    return tuple(json.loads((root / PACKAGE / track / "workload.schema.json").read_text(encoding="utf-8")) for track in TRACKS)


def test_no_string_constant_of_src_equals_a_role_outside_the_partitions_module_of_that_track_and_the_two_files_of_q2():
    trees = parse_all(SOURCE)
    assert role_sets(trees) == {"agentic": {"dev", "public_check"}, "ml": {"train", "dev", "public_check"}}
    assert role_literal_problems(trees) == []
    assert all(Q2_FILES.values()), "each file of Q2 gives its reason"
    assert set(Q2_FILES) <= set(trees)


def test_a_role_literal_in_a_module_of_another_track_or_of_no_track_is_found_and_the_two_files_of_q2_and_the_partitions_modules_are_not(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/agentic/partitions.py": 'DEV = "dev"\nPUBLIC_CHECK = "public_check"\nROLES = (DEV, PUBLIC_CHECK)\n',
        "hypotrail/ml/partitions.py": 'TRAIN = "train"\nDEV = "dev"\nPUBLIC_CHECK = "public_check"\nROLES = (TRAIN, DEV, PUBLIC_CHECK)\n',
        "hypotrail/core/comparison.py": 'DEV = "dev"\n',
        "hypotrail/report/gather.py": 'PUBLIC_CHECK = "public_check"\n',
        "hypotrail/ml/run.py": 'ok = "dev_set"\n',
    })
    assert role_literal_problems(parse_all(root)) == []
    plant(root, {"hypotrail/ml/run.py": 'p = "public_check"\n', "hypotrail/agentic/run.py": '\nq = "train"\n'})
    assert role_literal_problems(parse_all(root)) == [
        "hypotrail.agentic.run:2 holds the literal 'train'",
        "hypotrail.ml.run:1 holds the literal 'public_check'",
    ]


def test_the_agent_schema_closes_cases_to_the_roles_of_the_agent_track_and_the_ml_schema_holds_no_role_name():
    agent_schema, ml_schema = load_schemas(SOURCE)
    assert schema_problems(agent_schema, ml_schema, role_sets(parse_all(SOURCE))) == []


def test_a_role_removed_from_the_cases_of_the_agent_schema_and_a_role_planted_in_the_ml_schema_are_found():
    roles = {"agentic": {"dev", "public_check"}, "ml": {"train", "dev", "public_check"}}
    agent = {"properties": {"cases": {"properties": {"dev": {}, "public_check": {}}}}}
    ml = {"properties": {"partitions": {"type": "object"}}}
    assert schema_problems(agent, ml, roles) == []
    del agent["properties"]["cases"]["properties"]["public_check"]
    assert len(schema_problems(agent, ml, roles)) == 1
    agent["properties"]["cases"]["properties"]["public_check"] = {}
    ml["properties"]["partitions"]["examples"] = [{"train": []}]
    assert schema_problems(agent, ml, roles) == ["the ml schema holds the role names ['train']"]
