"""The architecture rules, read in the code of `src` through `tests/_architecture.py`.

Each rule is a function of the parsed modules of a source tree, so the same rule runs on `src` and on a tree planted with one violation. No model is called.
"""

import ast
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import NamedTuple

from _architecture import FUNCTION_NODES, SOURCE, calls, dotted, functions_of, import_targets, imports, names_of, owners_in, parse_all, resolve
from _study_helpers import run_json

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
LAYERS = {"cli": "top", "__init__": "top", "__main__": "top", "agentic": "track", "ml": "track", "report": "report", "lessons": "lessons", "core": "core"}
# What a layer may import, besides the package that holds the importing module.
MAY_IMPORT = {"track": {"core"}, "report": {"core"}, "lessons": {"core"}, "core": set()}


def entry_of(module: str) -> str:
    """The package or top-level module of `hypotrail` that holds `module` (`__init__` for `hypotrail` itself)."""
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else "__init__"


def layering_problems(trees: dict) -> list:
    problems = [f"{module} is in no layer of the list" for module in sorted(trees) if entry_of(module) not in LAYERS]
    for module, targets in imports(trees).items():
        if entry_of(module) not in LAYERS:
            continue
        layer = LAYERS[entry_of(module)]
        for target in sorted(targets):
            if not target.startswith(PACKAGE + ".") and target != PACKAGE:
                continue
            owner = max((name for name in trees if target == name or target.startswith(name + ".")), key=len)
            if entry_of(owner) == entry_of(module):
                continue
            owner_layer = LAYERS.get(entry_of(owner))
            if owner_layer == "lessons" and entry_of(module) != "cli":
                problems.append(f"{module} imports {target}")
            elif layer != "top" and owner_layer not in MAY_IMPORT[layer]:
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



def test_only_the_cli_can_import_lessons_and_the_lessons_layer_imports_only_core(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/__init__.py": "",
        "hypotrail/cli.py": "from hypotrail.lessons import loader\n",
        "hypotrail/core/__init__.py": "",
        "hypotrail/core/c.py": "",
        "hypotrail/lessons/__init__.py": "",
        "hypotrail/lessons/loader.py": "from hypotrail.core import c\n",
        "hypotrail/ml/__init__.py": "",
        "hypotrail/ml/m.py": "",
    })
    assert layering_problems(parse_all(root)) == []
    plant(root, {
        "hypotrail/__init__.py": "from hypotrail.lessons import loader\n",
        "hypotrail/core/c.py": "from hypotrail.lessons import loader\n",
        "hypotrail/lessons/loader.py": "from hypotrail.ml import m\n",
        "hypotrail/ml/m.py": "from hypotrail.lessons import loader\n",
    })
    assert sorted(layering_problems(parse_all(root))) == [
        "hypotrail imports hypotrail.lessons.loader",
        "hypotrail.core.c imports hypotrail.lessons.loader",
        "hypotrail.lessons.loader imports hypotrail.ml.m",
        "hypotrail.ml.m imports hypotrail.lessons.loader",
    ]

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
# These two files hold a copy of the role names: `core/comparison.py` (`DEV`, `PUBLIC_CHECK`) and `report/gather.py` (`PUBLIC_CHECK`). They are the only exemption, and it holds
# while this question stays open, chadlis/hypotrail#117, Q2: "Where do the core's copies of the role names (`core/comparison.py:44-45`, `report/gather.py:14`) belong, given that the core imports no Track?"
# chadlis/hypotrail#130, c4: "A string constant of `src/` that equals a role of either Track is allowed only in that Track's partitions module and in the two files of Q2, `core/comparison.py` and `report/gather.py`, which the test names with the reason."
CORE_COPIES_OF_THE_ROLE_NAMES = {
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
            if module not in home and module not in CORE_COPIES_OF_THE_ROLE_NAMES:
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


def test_no_string_constant_of_src_equals_a_role_outside_the_partitions_module_of_that_track_and_the_core_copies_of_the_role_names():
    trees = parse_all(SOURCE)
    assert role_literal_problems(trees) == []
    assert all(CORE_COPIES_OF_THE_ROLE_NAMES.values()), "each core copy of the role names gives its reason"
    assert set(CORE_COPIES_OF_THE_ROLE_NAMES) <= set(trees)


def test_a_role_literal_in_a_module_of_another_track_or_of_no_track_is_found_and_the_core_copies_of_the_role_names_and_the_partitions_modules_are_not(tmp_path):
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


def test_a_role_removed_from_the_cases_of_a_copy_of_the_agent_schema_and_a_role_planted_in_a_copy_of_the_ml_schema_are_found(tmp_path):
    for track in TRACKS:
        (tmp_path / PACKAGE / track).mkdir(parents=True)
        shutil.copy(SOURCE / PACKAGE / track / "workload.schema.json", tmp_path / PACKAGE / track / "workload.schema.json")
    roles = role_sets(parse_all(SOURCE))
    assert schema_problems(*load_schemas(tmp_path), roles) == []
    agent_copy = tmp_path / PACKAGE / "agentic" / "workload.schema.json"
    agent_schema = json.loads(agent_copy.read_text(encoding="utf-8"))
    del agent_schema["properties"]["cases"]["properties"]["public_check"]
    agent_copy.write_text(json.dumps(agent_schema), encoding="utf-8")
    assert schema_problems(*load_schemas(tmp_path), roles) == [
        "the agent schema closes `cases` to ['dev'], not to the roles ['dev', 'public_check']"
    ]
    shutil.copy(SOURCE / PACKAGE / "agentic" / "workload.schema.json", agent_copy)
    ml_copy = tmp_path / PACKAGE / "ml" / "workload.schema.json"
    ml_schema = json.loads(ml_copy.read_text(encoding="utf-8"))
    ml_schema["properties"]["train"] = {"type": "object"}
    ml_copy.write_text(json.dumps(ml_schema), encoding="utf-8")
    assert schema_problems(*load_schemas(tmp_path), roles) == ["the ml schema holds the role names ['train']"]


# --- rule 5: the third-party imports of each package ----------------------------------------------------------------------------

# The third-party top-level modules each package or top-level module of `src/hypotrail/` may import.
THIRD_PARTY = {
    # `anyio` is declared in the `agent` extra of `pyproject.toml`, beside `inspect_ai`.
    "agentic": {"anyio", "inspect_ai", "jsonschema"},
    "core": {"jsonschema"},
    "ml": {"jsonschema", "numpy", "scipy", "sklearn"},
    "report": set(),
    "lessons": {"jsonschema"},
    "cli": set(),
    "__init__": set(),
    "__main__": set(),
}


def third_party_problems(trees: dict) -> list:
    problems = []
    for module, targets in imports(trees).items():
        allowed = THIRD_PARTY.get(entry_of(module))
        if allowed is None:
            problems.append(f"{module} is in no package of the list")
            continue
        for top in sorted({target.split(".")[0] for target in targets} - set(sys.stdlib_module_names) - {PACKAGE}):
            if top not in allowed:
                problems.append(f"{module} imports {top}")
    return problems


def blocked_import_problems(root, trees: dict) -> list:
    """Import every module outside `agentic` in a fresh interpreter in which `inspect_ai` cannot be imported; each module that fails is a problem.

    `hypotrail.__main__` runs the command line when it is imported, so the probe gives it `--help`, which exits with 0.
    """
    modules = sorted(module for module in trees if entry_of(module) != "agentic")
    probe = (
        "import importlib, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "sys.modules['inspect_ai'] = None\n"
        "names = sys.argv[2:]\n"
        "sys.argv = ['hypotrail', '--help']\n"
        "failed = []\n"
        "for name in names:\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except SystemExit as error:\n"
        "        if error.code not in (0, None):\n"
        "            failed.append(f'{name}: SystemExit: {error.code}')\n"
        "    except BaseException as error:\n"
        "        failed.append(f'{name}: {type(error).__name__}: {error}')\n"
        "print('\\n'.join('FAILED ' + line for line in failed))\n"
    )
    done = subprocess.run([sys.executable, "-I", "-c", probe, str(root), *modules], capture_output=True, text=True)
    if done.returncode:
        return [f"probe exited {done.returncode}: {done.stderr}"]
    return [line.removeprefix("FAILED ") for line in done.stdout.splitlines() if line.startswith("FAILED ")]


def test_each_package_of_src_imports_only_the_third_party_modules_of_its_list():
    assert third_party_problems(parse_all(SOURCE)) == []


def test_every_agent_module_that_imports_anyio_is_covered_by_a_pin_of_anyio_in_the_agent_extra_of_pyproject():
    importing = sorted(
        module for module, targets in imports(parse_all(SOURCE)).items()
        if module.startswith("hypotrail.agentic") and any(target.split(".")[0] == "anyio" for target in targets)
    )
    assert importing, "no module of hypotrail.agentic imports anyio any more"
    declared = tomllib.loads((SOURCE.parent / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]["agent"]
    assert "anyio==4.16.0" in declared


def test_every_module_outside_agentic_imports_with_inspect_ai_made_unimportable():
    trees = parse_all(SOURCE)
    assert any(entry_of(module) == "core" for module in trees)
    assert blocked_import_problems(SOURCE, trees) == []


def test_a_third_party_import_outside_the_list_of_its_package_is_found_through_a_relative_module_a_function_and_the_top_level_modules(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/__init__.py": "",
        "hypotrail/cli.py": "import json\nfrom hypotrail.core import c\n",
        "hypotrail/core/__init__.py": "",
        "hypotrail/core/c.py": "import jsonschema\nfrom . import d\n",
        "hypotrail/core/d.py": "",
        "hypotrail/ml/__init__.py": "",
        "hypotrail/ml/m.py": "import numpy as np\nfrom sklearn.linear_model import Ridge\n",
        "hypotrail/agentic/__init__.py": "",
        "hypotrail/agentic/a.py": "import inspect_ai\n",
    })
    assert third_party_problems(parse_all(root)) == []
    plant(root, {
        "hypotrail/core/d.py": "def f():\n    import numpy\n",
        "hypotrail/ml/m.py": "from inspect_ai import eval\n",
        "hypotrail/cli.py": "import requests\n",
        "hypotrail/new/__init__.py": "",
    })
    assert third_party_problems(parse_all(root)) == [
        "hypotrail.cli imports requests",
        "hypotrail.core.d imports numpy",
        "hypotrail.ml.m imports inspect_ai",
        "hypotrail.new is in no package of the list",
    ]


def test_a_top_level_import_of_inspect_ai_in_a_core_module_fails_the_probe_and_one_in_agentic_does_not(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/__init__.py": "",
        "hypotrail/core/__init__.py": "",
        "hypotrail/core/c.py": "VALUE = 1\n",
        "hypotrail/agentic/__init__.py": "",
        "hypotrail/agentic/a.py": "import inspect_ai\n",
    })
    assert blocked_import_problems(root, parse_all(root)) == []
    plant(root, {"hypotrail/core/c.py": "import inspect_ai\n"})
    [problem] = blocked_import_problems(root, parse_all(root))
    assert problem.startswith("hypotrail.core.c: ModuleNotFoundError: import of inspect_ai halted")


# --- rule 6: no dynamically loaded code -----------------------------------------------------------------------------------------

DYNAMIC_BUILTINS = {"__import__", "exec", "eval"}
DYNAMIC_LOADERS = {"import_module", "entry_points"}


def dynamic_code_problems(trees: dict) -> list:
    """A call of `import_module` or `entry_points` however it is imported or aliased, or of `__import__`, `exec` or `eval` that no name of its module explains: a builtin."""
    problems = []
    for site in calls(trees):
        builtin = site.callee is None and site.raw in DYNAMIC_BUILTINS
        loader = (site.callee or "").rpartition(".")[2] in DYNAMIC_LOADERS
        if builtin or loader:
            problems.append(f"{site.owner} calls {site.callee or site.raw}")
    return problems


def test_no_module_of_src_loads_code_dynamically_and_inspects_eval_imported_by_the_runner_is_not_the_builtin():
    trees = parse_all(SOURCE)
    assert dynamic_code_problems(trees) == []
    runner = [site for site in calls(trees) if site.module == f"{PACKAGE}.agentic.runner" and site.raw == "eval"]
    assert runner and all(site.callee == "inspect_ai.eval" for site in runner)


def test_a_builtin_eval_exec_or_dunder_import_and_an_import_module_or_entry_points_call_are_found_and_an_imported_eval_is_not(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/core/a.py": "from inspect_ai import eval\n\ndef f():\n    return eval(1)\n",
        "hypotrail/core/b.py": "def eval(x):\n    return x\n\ndef g():\n    return eval(1)\n",
    })
    assert dynamic_code_problems(parse_all(root)) == []
    plant(root, {
        "hypotrail/core/a.py": "def f(s):\n    return eval(s)\n",
        "hypotrail/core/b.py": "def g(s):\n    exec(s)\n    return __import__(s)\n",
        "hypotrail/core/c.py": "import importlib\n\ndef h(n):\n    return importlib.import_module(n)\n",
        "hypotrail/core/d.py": "from importlib.metadata import entry_points as eps\n\ndef i():\n    return eps(group='x')\n",
        "hypotrail/core/e.py": "from importlib import import_module as load\n\ndef j(n):\n    return load(n)\n",
    })
    assert dynamic_code_problems(parse_all(root)) == [
        "hypotrail.core.a:f calls eval",
        "hypotrail.core.b:g calls exec",
        "hypotrail.core.b:g calls __import__",
        "hypotrail.core.c:h calls importlib.import_module",
        "hypotrail.core.d:i calls importlib.metadata.entry_points",
        "hypotrail.core.e:j calls importlib.import_module",
    ]


# --- rule 7: examples ---------------------------------------------------------------------------------------------------------

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def examples_problems(root) -> list:
    problems = [f"{path.relative_to(root)} is Python outside external/" for path in sorted(root.rglob("*.py")) if path.relative_to(root).parts[0] != "external"]
    for module, targets in imports(parse_all(root)).items():
        if module.split(".")[0] == "external":
            problems += [f"{module} imports {target}" for target in sorted(targets) if target.split(".")[0] == PACKAGE]
    return problems


def test_no_python_is_under_examples_outside_external_and_no_file_of_external_imports_hypotrail():
    assert (EXAMPLES / "external").is_dir() and list((EXAMPLES / "external").rglob("*.py"))
    assert examples_problems(EXAMPLES) == []


def test_a_py_file_in_a_workload_folder_and_an_absolute_or_relative_import_of_hypotrail_in_external_are_found(tmp_path):
    shutil.copytree(EXAMPLES, tmp_path / "examples", ignore=shutil.ignore_patterns("__pycache__", "data"))
    root = tmp_path / "examples"
    assert examples_problems(root) == []
    plant(root, {"chinook/helper.py": "x = 1\n"})
    assert examples_problems(root) == ["chinook/helper.py is Python outside external/"]
    (root / "chinook/helper.py").unlink()
    plant(root, {
        "external/a.py": "import hypotrail\n",
        "external/b.py": "from hypotrail.core import x\n",
        "external/sub/__init__.py": "",
        "external/sub/c.py": "from ... import hypotrail\n",
        "external/d.py": "from . import sibling\nimport json\n",
    })
    assert examples_problems(root) == ["external.a imports hypotrail", "external.b imports hypotrail.core.x", "external.sub.c imports hypotrail"]


# --- the import modules read every JSON input with the strict reader ----------------------------------------------------------

TRACK_IMPORT_MODULES = ("hypotrail.ml.imports", "hypotrail.agentic.imports")
# The core module of what the two import commands share, the strict JSON read among it.
IMPORT_HELPERS = "hypotrail.core.imports"
IMPORT_MODULES = (*TRACK_IMPORT_MODULES, IMPORT_HELPERS)
LOOSE_READS = {"json.load", "json.loads"}


def loose_json_reads(trees: dict) -> list:
    """The calls of `json.load` and `json.loads` in the import modules, as `module:function`, found through the resolver.

    The resolver follows a name the module imports or assigns (`import json as j`, `from json import loads`, `g = json.loads`). A read through an object that is
    passed in, or built with `getattr`, is outside it; no code under `src/` does that, and a planted one is a stated limit of this test.
    """
    return sorted(
        f"{site.module}:{site.owner.split(':')[1]}"
        for site in calls(trees)
        if site.module in IMPORT_MODULES and site.callee in LOOSE_READS
    )


def test_no_import_module_calls_json_load_or_json_loads():
    trees = parse_all(SOURCE)
    assert set(IMPORT_MODULES) <= set(trees)
    assert loose_json_reads(trees) == []


def test_a_json_read_through_an_alias_in_either_import_module_is_found(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/__init__.py": "",
        "hypotrail/ml/__init__.py": "",
        "hypotrail/ml/imports.py": "import json as j\n\ndef f(raw):\n    return j.loads(raw)\n",
        "hypotrail/agentic/__init__.py": "",
        "hypotrail/agentic/imports.py": "from json import load as ld\n\ndef g(handle):\n    return ld(handle)\n",
    })
    assert loose_json_reads(parse_all(root)) == ["hypotrail.agentic.imports:g", "hypotrail.ml.imports:f"]


def test_a_json_read_in_the_core_module_of_the_import_helpers_is_found(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/__init__.py": "",
        "hypotrail/core/__init__.py": "",
        "hypotrail/core/imports.py": "import json\n\ndef h(raw):\n    return json.loads(raw)\n",
    })
    assert loose_json_reads(parse_all(root)) == ["hypotrail.core.imports:h"]


# --- what the two import commands share is written once -------------------------------------------------------------------------

SERIALIZED_CONSTANTS = ("SERIALIZED_SUFFIXES", "SERIALIZED_MAGIC")
# The `problem` of an Episode outside the population, from JSON Lines and from an Inspect log, and the one function that chooses it.
OUTSIDE_PROBLEMS = ("unknown_case", "other_partition", "not_in_population", "repeat_out_of_range")
OUTSIDE_PROBLEM_CLASSIFIER = "hypotrail.agentic.imports:problem_outside_population"
SHARED_IMPORT_FUNCTIONS = tuple(f"{IMPORT_HELPERS}.{name}" for name in ("read_input", "strict_json_or_none", "producer_entry"))


def shared_import_helper_sites(trees: dict) -> dict:
    """What the rule reads, in three parts:

    - `assignments`: {constant: the module of each assignment of it, one entry per assignment}, over `SERIALIZED_CONSTANTS`;
    - `holders`: {value: the `module:function` (`module:<module>` outside any) of each string constant equal to it, one entry per constant}, over `OUTSIDE_PROBLEMS`;
    - `callers`: {function: the modules that call it, found through the resolver}, over `SHARED_IMPORT_FUNCTIONS`.

    Stated limit: an assignment is to a bare name (`X = ...`, `X: T = ...`, or a name in a tuple target); a value is a string constant equal to it.
    A constant set through an attribute or `globals()`, or a value built from parts, is outside the rule.
    """
    assignments: dict = {name: [] for name in SERIALIZED_CONSTANTS}
    holders: dict = {value: [] for value in OUTSIDE_PROBLEMS}
    for module, tree in trees.items():
        for node, owner in owners_in(module, tree):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name) and name.id in assignments:
                        assignments[name.id].append(module)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in holders:
                holders[node.value].append(owner)
    callers = {function: sorted({site.module for site in calls(trees) if site.callee == function}) for function in SHARED_IMPORT_FUNCTIONS}
    return {"assignments": assignments, "holders": holders, "callers": callers}


def test_each_serialized_constant_is_assigned_in_one_module_each_problem_value_is_held_by_one_function_and_both_import_modules_call_each_shared_helper():
    found = shared_import_helper_sites(parse_all(SOURCE))
    for name in SERIALIZED_CONSTANTS:
        assert found["assignments"][name] == [IMPORT_HELPERS], name
    for value in OUTSIDE_PROBLEMS:
        assert found["holders"][value] == [OUTSIDE_PROBLEM_CLASSIFIER], value
    for function in SHARED_IMPORT_FUNCTIONS:
        for module in TRACK_IMPORT_MODULES:
            assert module in found["callers"][function], (function, module)


SHARED_IMPORT_TREE = {
    "hypotrail/__init__.py": "",
    "hypotrail/core/__init__.py": "",
    "hypotrail/core/imports.py": (
        "SERIALIZED_SUFFIXES = ('.pkl',)\nSERIALIZED_MAGIC = b'\\x80'\n\n\n"
        "def read_input(path, code, what):\n    pass\n\n\ndef strict_json_or_none(raw):\n    pass\n\n\ndef producer_entry(value):\n    pass\n"
    ),
    "hypotrail/ml/__init__.py": "",
    "hypotrail/ml/imports.py": (
        "from hypotrail.core import imports as shared\nfrom hypotrail.core.imports import producer_entry\n\n\n"
        "def f(path, raw):\n    return shared.read_input(path, 'C', 'source'), shared.strict_json_or_none(raw), producer_entry(None)\n"
    ),
    "hypotrail/agentic/__init__.py": "",
    "hypotrail/agentic/imports.py": (
        "from hypotrail.core.imports import producer_entry, read_input, strict_json_or_none\n\n\n"
        "def g(path, raw):\n    return read_input(path, 'C', 'source'), strict_json_or_none(raw), producer_entry(None)\n\n\n"
        "def problem_outside_population(case_id, known, listed):\n"
        "    if case_id not in known:\n        return 'unknown_case'\n    if case_id == 'x':\n        return 'other_partition'\n"
        "    if case_id not in listed:\n        return 'not_in_population'\n    return 'repeat_out_of_range'\n"
    ),
    "hypotrail/agentic/inspect_log.py": "from hypotrail.agentic import imports\n\n\ndef checked(case_id):\n    return imports.problem_outside_population(case_id, {}, set())\n",
}


def test_a_second_serialized_constant_a_second_classification_and_a_helper_one_import_module_does_not_call_are_found_in_a_planted_tree(tmp_path):
    root = plant(tmp_path, SHARED_IMPORT_TREE)
    assert shared_import_helper_sites(parse_all(root)) == {
        "assignments": {"SERIALIZED_SUFFIXES": [IMPORT_HELPERS], "SERIALIZED_MAGIC": [IMPORT_HELPERS]},
        "holders": {value: [OUTSIDE_PROBLEM_CLASSIFIER] for value in OUTSIDE_PROBLEMS},
        "callers": {function: sorted(TRACK_IMPORT_MODULES) for function in SHARED_IMPORT_FUNCTIONS},
    }
    plant(root, {
        "hypotrail/ml/imports.py": "SERIALIZED_MAGIC: bytes = b'\\x80'\n\n\ndef f(path):\n    return path\n",
        "hypotrail/agentic/inspect_log.py": (
            "def checked(case_id, known):\n    if case_id not in known:\n        problem = 'unknown_case'\n    else:\n        problem = 'repeat_out_of_range'\n    return problem\n"
        ),
    })
    found = shared_import_helper_sites(parse_all(root))
    assert found["assignments"]["SERIALIZED_MAGIC"] == [IMPORT_HELPERS, "hypotrail.ml.imports"]
    assert found["holders"]["unknown_case"] == ["hypotrail.agentic.imports:problem_outside_population", "hypotrail.agentic.inspect_log:checked"]
    assert found["holders"]["repeat_out_of_range"] == ["hypotrail.agentic.imports:problem_outside_population", "hypotrail.agentic.inspect_log:checked"]
    assert found["callers"]["hypotrail.core.imports.read_input"] == ["hypotrail.agentic.imports"]


# --- the functions under `src/` that raise `INVALID_ARGUMENTS`, with their numbers of calls, are those in `INVALID_ARGUMENTS_BUILDERS`, and six command lines give the `details.command` stated for each ---

INVALID_INPUT_ERROR = "hypotrail.core.errors.InvalidInputError"

# Each function under `src/` that raises `INVALID_ARGUMENTS`, with the number of such calls.
INVALID_ARGUMENTS_BUILDERS = {
    # `details.command` is self.prog: `hypotrail <command>` for the subparser of a command (a missing flag); `hypotrail` for the top-level parser, which gives it
    # when no command was given and when an unknown flag was given to a command (argparse refuses it at the top level after the subparser has parsed the known arguments)
    "hypotrail.cli:_ArgumentParser.error": 1,
    # `details.command` is f"hypotrail {command}"
    "hypotrail.core.study_write:invalid_arguments": 1,
    # `details.command` is "hypotrail init"
    "hypotrail.cli:_init": 2,
    # `details.command` is "hypotrail init"
    "hypotrail.cli:_new_revision": 1,
}


def invalid_arguments_builders(trees: dict) -> dict:
    """{`module:function`: the number of its calls of `InvalidInputError` whose first argument is the literal "INVALID_ARGUMENTS"}.

    The conventions that bound it: a call whose first argument is the literal code, resolved through the names the module imports or assigns. A code held in a variable
    or an error built through another function is outside it; no code under `src/` does that, and a planted one is a stated limit of this test.
    """
    found: dict = {}
    for site in calls(trees):
        first = site.node.args[0] if site.node.args else None
        if site.callee == INVALID_INPUT_ERROR and isinstance(first, ast.Constant) and first.value == "INVALID_ARGUMENTS":
            found[site.owner] = found.get(site.owner, 0) + 1
    return found


def test_the_functions_under_src_that_raise_invalid_arguments_and_their_number_of_calls_are_the_listed_ones():
    assert invalid_arguments_builders(parse_all(SOURCE)) == INVALID_ARGUMENTS_BUILDERS


def test_a_function_that_raises_invalid_arguments_through_an_alias_is_found_in_a_planted_tree(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/__init__.py": "",
        "hypotrail/cli.py": "from hypotrail.core.errors import InvalidInputError as E\n\ndef f():\n    raise E('INVALID_ARGUMENTS', 'm', details={'command': 'init'})\n",
        "hypotrail/core/__init__.py": "",
        "hypotrail/core/errors.py": "class InvalidInputError(Exception): pass\n",
    })
    assert invalid_arguments_builders(parse_all(root)) == {"hypotrail.cli:f": 1}


def test_the_details_command_of_each_of_six_command_lines_is_hypotrail_command_except_when_no_command_or_an_unknown_flag_was_given(tmp_path):
    none = tmp_path / "none"
    runs = {
        "a missing flag": (["assess"], "hypotrail assess"),
        "no command was given": ([], "hypotrail"),
        "an unknown flag was given to a command": (["status", "--study", "/x", "--bogus"], "hypotrail"),
        "init with a read sequence for a new Study": (["init", "--study", none, "--workload", "chinook", "--read-sequence", "0"], "hypotrail init"),
        "init with neither a Workload nor a new revision": (["init", "--study", none], "hypotrail init"),
        "init with a new revision and a Workload": (["init", "--study", none, "--new-revision", "--workload", "chinook"], "hypotrail init"),
    }
    gave = {}
    for case, (arguments, _) in runs.items():
        code, payload, _ = run_json(*arguments)
        assert (code, payload["error"]["code"]) == (2, "INVALID_ARGUMENTS"), case
        gave[case] = payload["error"]["details"]["command"]
    assert gave == {case: command for case, (_, command) in runs.items()}
    assert not none.exists()


# --- `report` writes no file itself: its page goes through `core/artifacts.replace_atomically` -------------------------------------

REPLACE_ATOMICALLY = "hypotrail.core.artifacts.replace_atomically"
FILE_FUNCTIONS = {"os.replace", "os.rename", "os.fsync", "os.open"}
WRITING_METHODS = {"write_bytes", "write_text"}


def _writes(mode) -> bool:
    """A mode writes when it is a literal that holds `w`, `a`, `x` or `+`, or when it is not a literal."""
    if mode is None:
        return False
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return any(letter in mode.value for letter in "wax+")
    return True


def _mode_of(node: ast.Call, position: int):
    keyword = next((k.value for k in node.keywords if k.arg == "mode"), None)
    return node.args[position] if len(node.args) > position else keyword


def file_writes_of_modules(trees: dict, prefix: str) -> list:
    """The calls, in every module whose name is `prefix` or starts with `prefix.`, that write a file: `module:function spelling`.

    A call is listed when it resolves to `os.replace`, `os.rename`, `os.fsync` or `os.open`; when it is the builtin `open` with a mode that writes (the second argument,
    or `mode=`); or when it is a method named `write_bytes` or `write_text`, or named `open` with a mode that writes (the first argument, or `mode=`), whatever its receiver.
    The conventions that bound it: the resolver's, for the `os` functions and `open`; the attribute's name, whatever the receiver, for the methods. A write through a
    function that is passed in, or an object built with `getattr`, is outside it; no code under `src/` does that, and a planted one is a stated limit of this test.
    """
    found = []
    for site in calls(trees):
        if not (site.module == prefix or site.module.startswith(prefix + ".")):
            continue
        func = site.node.func
        method = func.attr if isinstance(func, ast.Attribute) else None
        if site.callee in FILE_FUNCTIONS:
            listed = True
        elif site.raw == "open" and site.callee is None:
            listed = _writes(_mode_of(site.node, 1))
        elif method in WRITING_METHODS:
            listed = True
        elif method == "open":
            listed = _writes(_mode_of(site.node, 0))
        else:
            listed = False
        if listed:
            found.append(f"{site.owner} {site.callee or site.raw or method}")
    return sorted(found)


def test_no_module_of_report_writes_a_file_itself():
    assert file_writes_of_modules(parse_all(SOURCE), "hypotrail.report") == []


def test_a_planted_write_in_a_module_of_report_is_found_whatever_the_way_it_is_spelled(tmp_path):
    planted = {
        "os.replace": "import os\ndef f(a, b):\n    os.replace(a, b)\n",
        "os_alias": "from os import rename as r\ndef f(a, b):\n    r(a, b)\n",
        "builtin_open": "def f(p):\n    open(p, 'wb')\n",
        "builtin_open_keyword": "def f(p, m):\n    open(p, mode=m)\n",
        "write_bytes": "from pathlib import Path\ndef f(p):\n    Path(p).write_bytes(b'')\n",
        "write_text": "def f(p):\n    p.write_text('')\n",
        "path_open": "def f(p):\n    p.open('w')\n",
    }
    for name, source in planted.items():
        root = plant(tmp_path / name, {"hypotrail/__init__.py": "", "hypotrail/report/__init__.py": "", "hypotrail/report/x.py": source})
        assert len(file_writes_of_modules(parse_all(root), "hypotrail.report")) == 1, name
    reads = "def f(p):\n    open(p)\n    open(p, 'rb')\n    p.open('r')\n    p.read_bytes()\n"
    root = plant(tmp_path / "reads", {"hypotrail/__init__.py": "", "hypotrail/report/__init__.py": "", "hypotrail/report/x.py": reads})
    assert file_writes_of_modules(parse_all(root), "hypotrail.report") == []


def test_report_command_calls_replace_atomically_and_the_private_write_of_artifacts_calls_it_too():
    sites = calls(parse_all(SOURCE))
    modules = sorted({site.module for site in sites if site.callee == REPLACE_ATOMICALLY and site.module.startswith("hypotrail.report")})
    assert modules == ["hypotrail.report.command"]
    assert "hypotrail.core.artifacts:_write_atomically" in {site.owner for site in sites if site.callee == REPLACE_ATOMICALLY}


# --- #154: `compare` reads the single-feature check, it computes no feature ------------------------------------------------------------

COMPARISON_MODULES = ("hypotrail.core.comparison", "hypotrail.core.agent_comparison")
FEATURE_MODULES = ("hypotrail.ml.lags", "hypotrail.ml.series")


def feature_imports(trees: dict) -> dict:
    """{comparison module: what it imports from the modules that compute a lag feature or read a target series}."""
    found = imports(trees)
    return {module: sorted(t for t in found[module] if any(t == m or t.startswith(m + ".") for m in FEATURE_MODULES)) for module in COMPARISON_MODULES}


def test_the_comparison_modules_import_nothing_from_the_modules_that_compute_lag_features_or_read_the_series():
    assert feature_imports(parse_all(SOURCE)) == {module: [] for module in COMPARISON_MODULES}


# --- the sites a rule finds today that its end state does not allow --------------------------------------------------------------------


class Listed(NamedTuple):
    """A site a rule finds today that its end state does not allow: the number of places the rule finds in it, and the ticket and slice that remove it."""

    count: int
    ticket: str
    slice: str


def both_ways(found: dict, allowed: dict, listed: dict) -> tuple:
    """(found, expected) over the union of their sites, each site with its count and 0 where it is absent, so that one assertion compares every site both ways."""
    expected = {**allowed, **{site: entry.count for site, entry in listed.items()}}
    union = sorted(found.keys() | expected.keys())
    return {site: found.get(site, 0) for site in union}, {site: expected.get(site, 0) for site in union}


def tally(sites) -> dict:
    """{site: the number of times it is given}."""
    found: dict = {}
    for site in sites:
        found[site] = found.get(site, 0) + 1
    return found


def outermost_functions(trees: dict):
    """Yield (`module:function`, its node) for every function and method of every module that no other function holds, named as `owners_in` names them."""
    for qualified, function in functions_of(trees).items():
        yield f"{function.module}:{qualified[len(function.module) + 1:]}", function


# --- what only the recorder does: an Attempt or Observation set record, a manifest path given to `replace_bytes`, `write.attempt(` ---

RECORDER = "hypotrail.core.attempts"
RECORD_VERSIONS = ("attempt/1", "observations/1")
REPLACE_BYTES = "hypotrail.core.artifacts.replace_bytes"
MANIFEST_PATH = "hypotrail.core.study.attempt_manifest_path"

# `recover` writes the `interrupted` manifest of a crashed Attempt and is not one of the four Attempt writers, so it stays where it is.
MANIFEST_WRITES_THAT_STAY = {"hypotrail.core.state:recover": 1}

LISTED_RECORD_LITERALS: dict = {}
LISTED_MANIFEST_WRITES: dict = {}
LISTED_ATTEMPT_CALLS: dict = {}


def recorder_sites(trees: dict) -> dict:
    """What the rule finds outside `hypotrail.core.attempts`, in three parts:

    - `literals`: {`module:line`: count} for every dict literal that holds `"schema_version": "attempt/1"` or `"schema_version": "observations/1"`;
    - `manifest_writes`: {`module:function`: count} for every place where a function gives an Attempt manifest path to `artifacts.replace_bytes`;
    - `attempt_calls`: {`module:function`: count} for every call `write.attempt(`.

    A manifest path is the value of `attempt_manifest_path(...)`, or a name assigned from it in the same function. It is given to `artifacts.replace_bytes`
    itself, or to a function of `src/` outside `hypotrail.core.attempts` that passes the parameter it lands in to `artifacts.replace_bytes`: a function or
    method the resolver names, or a method called on a name the same function assigns from a class of `src/` (`writes = Adapter(...)`, then
    `writes.replace(...)`). A function of `hypotrail.core.attempts` that writes the path it is given is the recorder's own write.

    Stated limit: part (b) follows a manifest path through a name assigned in the same function and through one function that hands it on; a path built
    another way, or handed on twice, is outside it. D-054 on chadlis/hypotrail#75: "**Stop rule.** A later escape that code under `src/` actually uses is a
    blocker. An escape that is only planted is a stated limit, written down in the test's docstring and in the PR body."
    """
    functions = functions_of(trees)
    callees = {id(site.node): site.callee for site in calls(trees)}
    literals, manifest_writes, attempt_calls = [], [], []
    for module, tree in trees.items():
        if module == RECORDER:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                literals += [
                    f"{module}:{value.lineno}"
                    for key, value in zip(node.keys, node.values)
                    if isinstance(key, ast.Constant) and key.value == "schema_version" and isinstance(value, ast.Constant) and value.value in RECORD_VERSIONS
                ]
    # {`module.function` or `module.Class.method`: (its `Function`, the parameters it passes to `replace_bytes`)} for each function outside the recorder that passes one
    hands_on = {}
    for qualified, function in functions.items():
        if function.module == RECORDER:
            continue
        passed = {
            argument.id
            for node in ast.walk(function.node)
            if isinstance(node, ast.Call) and callees.get(id(node)) == REPLACE_BYTES
            for argument in [*node.args, *(keyword.value for keyword in node.keywords)]
            if isinstance(argument, ast.Name)
        }
        receiving = passed & {*function.parameters, *function.keyword_only}
        if receiving:
            hands_on[qualified] = (function, receiving)
    for owner, function in outermost_functions(trees):
        if function.module == RECORDER:
            continue
        nodes = list(ast.walk(function.node))
        paths = {
            target.id
            for node in nodes
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and callees.get(id(node.value)) == MANIFEST_PATH
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        # {name: the class of `src/` it is assigned an instance of}
        instances = {
            target.id: callees[id(node.value)]
            for node in nodes
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and callees.get(id(node.value))
            and any(name.startswith(callees[id(node.value)] + ".") for name in functions)
            for target in node.targets
            if isinstance(target, ast.Name)
        }

        def is_path(argument):
            return (isinstance(argument, ast.Name) and argument.id in paths) or (isinstance(argument, ast.Call) and callees.get(id(argument)) == MANIFEST_PATH)

        for node in nodes:
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "attempt" and isinstance(func.value, ast.Name) and func.value.id == "write":
                attempt_calls.append(owner)
            callee, skipped = callees.get(id(node)), 0
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in instances:
                callee, skipped = f"{instances[func.value.id]}.{func.attr}", 1
            if callee == REPLACE_BYTES:
                if any(is_path(argument) for argument in [*node.args, *(k.value for k in node.keywords)]):
                    manifest_writes.append(owner)
            elif callee in hands_on:
                target, receiving = hands_on[callee]
                positional = target.parameters[skipped:]
                given = [positional[i] for i, argument in enumerate(node.args) if i < len(positional) and is_path(argument)]
                given += [k.arg for k in node.keywords if is_path(k.value)]
                if set(given) & receiving:
                    manifest_writes.append(owner)
    return {"literals": tally(literals), "manifest_writes": tally(manifest_writes), "attempt_calls": tally(attempt_calls)}


def test_outside_the_recorder_the_record_literals_the_manifest_writes_and_the_write_attempt_calls_are_the_listed_ones_and_recover_stays():
    found = recorder_sites(parse_all(SOURCE))
    assert MANIFEST_WRITES_THAT_STAY == {"hypotrail.core.state:recover": 1}
    found_literals, expected_literals = both_ways(found["literals"], {}, LISTED_RECORD_LITERALS)
    assert found_literals == expected_literals
    found_writes, expected_writes = both_ways(found["manifest_writes"], MANIFEST_WRITES_THAT_STAY, LISTED_MANIFEST_WRITES)
    assert found_writes == expected_writes
    found_calls, expected_calls = both_ways(found["attempt_calls"], {}, LISTED_ATTEMPT_CALLS)
    assert found_calls == expected_calls


RECORDER_SUPPORT = {
    "hypotrail/__init__.py": "",
    "hypotrail/core/__init__.py": "",
    "hypotrail/core/artifacts.py": "def replace_bytes(study, relative, data):\n    pass\n",
    "hypotrail/core/study.py": "def attempt_manifest_path(attempt_id):\n    return f'attempts/{attempt_id}/attempt.json'\n",
    "hypotrail/ml/__init__.py": "",
    "hypotrail/ml/hands_on.py": "from hypotrail.core import artifacts\n\n\ndef put(study, relative, data):\n    artifacts.replace_bytes(study, relative, data)\n",
}
RECORDER_VIOLATIONS = {
    "attempt_literal.py": "def f():\n    return {\n        'schema_version': 'attempt/1',\n    }\n",
    "observations_literal.py": "def f():\n    return {'kind': 'observation_set', 'schema_version': 'observations/1'}\n",
    "direct.py": "from hypotrail.core import artifacts\nfrom hypotrail.core import study as layout\n\n\ndef f(study):\n    artifacts.replace_bytes(study, layout.attempt_manifest_path('a'), b'')\n",
    "handed_on.py": "from hypotrail.core import study as layout\nfrom hypotrail.ml.hands_on import put\n\n\ndef f(study):\n    path = layout.attempt_manifest_path('a')\n    put(study, path, b'')\n",
    "attempt_call.py": "def f(write):\n    write.attempt('a')\n",
}


def test_the_recorder_rule_finds_each_planted_violation_outside_the_recorder_and_none_in_a_planted_core_attempts(tmp_path):
    outside = plant(tmp_path / "outside", {**RECORDER_SUPPORT, **{f"hypotrail/ml/{name}": source for name, source in RECORDER_VIOLATIONS.items()}})
    found = recorder_sites(parse_all(outside))
    assert found["literals"].get("hypotrail.ml.attempt_literal:3") == 1
    assert found["literals"].get("hypotrail.ml.observations_literal:2") == 1
    assert found["manifest_writes"].get("hypotrail.ml.direct:f") == 1
    assert found["manifest_writes"].get("hypotrail.ml.handed_on:f") == 1
    assert found["attempt_calls"].get("hypotrail.ml.attempt_call:f") == 1
    inside = plant(tmp_path / "inside", {**RECORDER_SUPPORT, "hypotrail/core/attempts.py": "\n\n".join(
        source.replace("def f(", f"def f{number}(") for number, source in enumerate(RECORDER_VIOLATIONS.values())
    )})
    assert recorder_sites(parse_all(inside)) == {"literals": {}, "manifest_writes": {}, "attempt_calls": {}}


# --- `PROTOCOL_CHANGED` is built in one module -----------------------------------------------------------------------------------------

CODE_BUILDING_ERRORS = {f"hypotrail.core.errors.{name}" for name in ("InvalidInputError", "IntegrityError", "HypotrailError")}

# The one function that builds the code, which every path that checks the Protocol calls.
PROTOCOL_CHANGED_BUILDER = {"hypotrail.core.protocol_check:require_unchanged": 1}


def protocol_changed_builders(trees: dict) -> dict:
    """{`module:function`: the number of its calls of `InvalidInputError`, `IntegrityError` or `HypotrailError` of `hypotrail.core.errors` whose code is the literal "PROTOCOL_CHANGED"}.

    The code is the first argument, or the keyword `code`; the class is resolved through the names the module imports or assigns.
    Stated limit: a code held in a variable, or an error built through another function or another class than the three named, is outside the rule.
    """
    builders = []
    for site in calls(trees):
        if site.callee not in CODE_BUILDING_ERRORS:
            continue
        code = site.node.args[0] if site.node.args else next((k.value for k in site.node.keywords if k.arg == "code"), None)
        if isinstance(code, ast.Constant) and code.value == "PROTOCOL_CHANGED":
            builders.append(site.owner)
    return tally(builders)


def test_protocol_changed_is_built_by_one_call_in_one_function_of_one_core_module():
    found, expected = both_ways(protocol_changed_builders(parse_all(SOURCE)), PROTOCOL_CHANGED_BUILDER, {})
    assert found == expected


def test_protocol_changed_built_through_an_alias_of_each_error_class_in_a_second_module_and_twice_in_one_function_is_found(tmp_path):
    errors = "class HypotrailError(Exception):\n    pass\n\n\nclass InvalidInputError(HypotrailError):\n    pass\n\n\nclass IntegrityError(HypotrailError):\n    pass\n"
    once = "from hypotrail.core.errors import IntegrityError\n\n\ndef check(spec):\n    raise IntegrityError('PROTOCOL_CHANGED', 'm', stage='request', details={})\n"
    root = plant(tmp_path, {
        "hypotrail/__init__.py": "",
        "hypotrail/core/__init__.py": "",
        "hypotrail/core/errors.py": errors,
        "hypotrail/core/protocol.py": once,
        "hypotrail/ml/__init__.py": "",
        "hypotrail/ml/second.py": (
            "from hypotrail.core.errors import HypotrailError as Coded, IntegrityError as Broken, InvalidInputError as Refused\n\n\n"
            "def a():\n    raise Refused('PROTOCOL_CHANGED', 'm', stage='request')\n\n\n"
            "def b():\n    raise Broken('PROTOCOL_CHANGED', 'm', stage='request')\n\n\n"
            "def c():\n    raise Coded(code='PROTOCOL_CHANGED', message='m', stage='request')\n"
        ),
    })
    assert protocol_changed_builders(parse_all(root)) == {"hypotrail.core.protocol:check": 1, "hypotrail.ml.second:a": 1, "hypotrail.ml.second:b": 1, "hypotrail.ml.second:c": 1}
    plant(root, {"hypotrail/core/protocol.py": once + "    raise IntegrityError('PROTOCOL_CHANGED', 'm', stage='request', details={})\n"})
    found = protocol_changed_builders(parse_all(root))
    assert found["hypotrail.ml.second:a"] == 1
    assert found["hypotrail.ml.second:b"] == 1
    assert found["hypotrail.ml.second:c"] == 1
    assert found["hypotrail.core.protocol:check"] == 2


# --- no module uses a private name of another module ----------------------------------------------------------------------------------

LISTED_PRIVATE_NAME_USES = {
    # `_refuse` of `hypotrail.core.comparison`
    "hypotrail.core.agent_comparison:60": Listed(1, "K", "R2b"),
    # `gather._rows`
    "hypotrail.report.gather_agent:68": Listed(1, "K", "R2b"),
    "hypotrail.report.gather_agent:78": Listed(1, "K", "R2b"),
}


def is_private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def private_name_uses(trees: dict) -> dict:
    """{`module:line`: 1} for every line of a module that uses a name of another module of the tree that starts with `_` and is not a dunder.

    The two forms: `from module import _name`, with or without `as`, relative imports resolved; and `module._name` where `module` stands for a module of the tree,
    resolved through the names the module imports or assigns. A public name imported under a private alias (`now as _now`) is not a use of a private name.
    The quantifier ranges over uses of a name, so no static listing is complete; these two forms are the conventions that bound it, and a use written another
    way (through `getattr`, or an object passed in) is outside the rule. D-054 on chadlis/hypotrail#75: "**Stop rule.** A later escape that code under `src/`
    actually uses is a blocker. An escape that is only planted is a stated limit, written down in the test's docstring and in the PR body."
    """
    uses = []
    for module, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                alone = ast.Module(body=[node], type_ignores=[])
                alone.is_package = getattr(tree, "is_package", False)
                for alias, (_, _, full) in zip(node.names, import_targets(module, alone)):
                    owner = full.rpartition(".")[0]
                    if is_private(alias.name) and owner in trees and owner != module:
                        uses.append(f"{module}:{alias.lineno}")
        names = names_of(module, tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and is_private(node.attr):
                owner = resolve(names, dotted(node.value))
                if owner in trees and owner != module:
                    uses.append(f"{module}:{node.lineno}")
    return dict.fromkeys(sorted(set(uses)), 1)


def test_the_uses_of_a_private_name_of_another_module_under_src_are_the_listed_ones():
    found, expected = both_ways(private_name_uses(parse_all(SOURCE)), {}, LISTED_PRIVATE_NAME_USES)
    assert found == expected


def test_a_private_name_imported_or_read_as_an_attribute_or_imported_under_an_alias_is_found_and_a_private_alias_or_a_dunder_is_not(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/__init__.py": "",
        "hypotrail/core/__init__.py": "",
        "hypotrail/core/owner.py": "__version__ = '1'\n\n\ndef _hidden():\n    pass\n\n\ndef public():\n    pass\n",
        "hypotrail/ml/__init__.py": "",
        "hypotrail/ml/imported.py": "from hypotrail.core.owner import _hidden\n",
        "hypotrail/ml/relative.py": "\nfrom ..core.owner import public, _hidden\n",
        "hypotrail/ml/attribute.py": "from hypotrail.core import owner\n\n\ndef f():\n    return owner._hidden()\n",
        "hypotrail/ml/aliased.py": "from hypotrail.core.owner import _hidden as hidden\n",
        "hypotrail/ml/private_alias.py": "from hypotrail.core.owner import public as _public\n",
        "hypotrail/ml/dunder.py": "from hypotrail.core import owner\nfrom hypotrail.core.owner import __version__\n\nNAME = owner.__name__\n",
    })
    found = private_name_uses(parse_all(root))
    assert found.get("hypotrail.ml.imported:1") == 1
    assert found.get("hypotrail.ml.relative:2") == 1
    assert found.get("hypotrail.ml.attribute:5") == 1
    assert found.get("hypotrail.ml.aliased:1") == 1
    assert [site for site in found if site.startswith("hypotrail.ml.private_alias:")] == []
    assert [site for site in found if site.startswith("hypotrail.ml.dunder:")] == []


# --- the two Inspect correspondences, `epoch - 1` and `.split("/", 1)`, are written in `agentic.projection` only -----------------------

PROJECTION = "hypotrail.agentic.projection"
EPOCH_MINUS_ONE, SPLIT_PROVIDER = "epoch - 1", '.split("/", 1)'

LISTED_INSPECT_CORRESPONDENCES = {
    EPOCH_MINUS_ONE: {
        "hypotrail.agentic.live:_record": Listed(2, "J", "R2b"),
        "hypotrail.agentic.inspect_log:usage_by_key": Listed(1, "J", "R2b"),
        "hypotrail.agentic.inspect_log:checked_episodes": Listed(1, "J", "R2b"),
        "hypotrail.agentic.run:_record": Listed(1, "J", "R2b"),
    },
    SPLIT_PROVIDER: {
        "hypotrail.agentic.fixture:run_fixture": Listed(1, "J", "R2b"),
        "hypotrail.agentic.live:_record": Listed(1, "J", "R2b"),
        "hypotrail.agentic.inspect_log:is_mock": Listed(1, "J", "R2b"),
    },
}


def inspect_correspondences(trees: dict) -> dict:
    """{form: {`module:function`: count}} for every expression `<x>.epoch - 1` and every call `<x>.split("/", 1)` outside `hypotrail.agentic.projection`.

    Stated limit: the rule reads the two spellings; the same arithmetic written another way (`epoch + -1`, `partition("/")`) is outside it.
    D-054 on chadlis/hypotrail#75: "**Stop rule.** A later escape that code under `src/` actually uses is a blocker. An escape that is only planted is a stated
    limit, written down in the test's docstring and in the PR body."
    """
    found: dict = {EPOCH_MINUS_ONE: [], SPLIT_PROVIDER: []}
    for module, tree in trees.items():
        if module == PROJECTION:
            continue
        for node, owner in owners_in(module, tree):
            if (
                isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub)
                and isinstance(node.left, ast.Attribute) and node.left.attr == "epoch"
                and isinstance(node.right, ast.Constant) and node.right.value == 1
            ):
                found[EPOCH_MINUS_ONE].append(owner)
            if (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "split" and not node.keywords
                and [a.value if isinstance(a, ast.Constant) else a for a in node.args] == ["/", 1]
            ):
                found[SPLIT_PROVIDER].append(owner)
    return {form: tally(owners) for form, owners in found.items()}


def test_outside_the_projection_module_the_functions_that_write_epoch_minus_one_or_split_the_provider_are_the_listed_ones():
    found = inspect_correspondences(parse_all(SOURCE))
    for form in (EPOCH_MINUS_ONE, SPLIT_PROVIDER):
        found_sites, expected_sites = both_ways(found[form], {}, LISTED_INSPECT_CORRESPONDENCES[form])
        assert found_sites == expected_sites, form


def test_epoch_minus_one_and_split_of_the_provider_planted_in_another_module_are_found_and_in_the_projection_module_are_not(tmp_path):
    source = "def key(sample):\n    return sample.epoch - 1\n\n\ndef provider(model):\n    return model.split('/', 1)[0]\n"
    root = plant(tmp_path, {
        "hypotrail/__init__.py": "",
        "hypotrail/agentic/__init__.py": "",
        "hypotrail/agentic/projection.py": source,
        "hypotrail/agentic/other.py": source,
    })
    found = inspect_correspondences(parse_all(root))
    assert found[EPOCH_MINUS_ONE] == {"hypotrail.agentic.other:key": 1}
    assert found[SPLIT_PROVIDER] == {"hypotrail.agentic.other:provider": 1}


# --- the four rules above read source files: they use no name imported from `hypotrail` -------------------------------------------------

TESTS = Path(__file__).resolve().parent
READ_ONLY_RULES = (
    "recorder_sites",
    "test_outside_the_recorder_the_record_literals_the_manifest_writes_and_the_write_attempt_calls_are_the_listed_ones_and_recover_stays",
    "test_the_recorder_rule_finds_each_planted_violation_outside_the_recorder_and_none_in_a_planted_core_attempts",
    "protocol_changed_builders",
    "test_protocol_changed_is_built_by_one_call_in_one_function_of_one_core_module",
    "test_protocol_changed_built_through_an_alias_of_each_error_class_in_a_second_module_and_twice_in_one_function_is_found",
    "private_name_uses",
    "test_the_uses_of_a_private_name_of_another_module_under_src_are_the_listed_ones",
    "test_a_private_name_imported_or_read_as_an_attribute_or_imported_under_an_alias_is_found_and_a_private_alias_or_a_dunder_is_not",
    "inspect_correspondences",
    "test_outside_the_projection_module_the_functions_that_write_epoch_minus_one_or_split_the_provider_are_the_listed_ones",
    "test_epoch_minus_one_and_split_of_the_provider_planted_in_another_module_are_found_and_in_the_projection_module_are_not",
)


def names_imported_from_outside(test_modules: dict, starts) -> dict:
    """{`module:function`: the names it uses that an import binds to a module other than the standard library and `_architecture`} for each of the `starts`
    of `test_architecture` and each function those call, followed through the functions of `test_architecture` and `_architecture`.

    `test_modules` is {module name: its tree}. A name is followed when it is a function of its own module or a function of `_architecture` imported by
    name; an import written inside a followed function counts as a use of the names it binds.
    """
    defined = {module: {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))} for module, tree in test_modules.items()}
    imported = {module: {bound: target for bound, _, target in import_targets(module, tree)} for module, tree in test_modules.items()}

    def allowed(target: str) -> bool:
        top = target.split(".")[0]
        return top in sys.stdlib_module_names or top == "_architecture"

    found: dict = {}
    pending, seen = [("test_architecture", start) for start in starts], set()
    while pending:
        module, name = pending.pop()
        if (module, name) in seen:
            continue
        seen.add((module, name))
        function = defined[module][name]
        local = {bound: target for bound, _, target in import_targets(module, ast.Module(body=[function], type_ignores=[]))}
        for node in ast.walk(function):
            if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
                continue
            target = local.get(node.id) or (None if node.id in defined[module] else imported[module].get(node.id))
            if node.id in defined[module] and node.id not in local:
                pending.append((module, node.id))
            elif target is not None and not allowed(target):
                found.setdefault(f"{module}:{name}", set()).add(node.id)
            elif target is not None and target.startswith("_architecture.") and target.rpartition(".")[2] in defined["_architecture"]:
                pending.append(("_architecture", target.rpartition(".")[2]))
        for bound, _, target in import_targets(module, ast.Module(body=[function], type_ignores=[])):
            if not allowed(target):
                found.setdefault(f"{module}:{name}", set()).add(bound)
    return found


def test_the_four_rules_their_tests_and_the_functions_they_call_use_no_name_imported_from_hypotrail():
    test_modules = {name: ast.parse((TESTS / f"{name}.py").read_text(encoding="utf-8")) for name in ("test_architecture", "_architecture")}
    assert set(READ_ONLY_RULES) <= {node.name for node in test_modules["test_architecture"].body if isinstance(node, ast.FunctionDef)}
    assert names_imported_from_outside(test_modules, READ_ONLY_RULES) == {}


# --- one clock, one assignment of each of two path names, one builder of each of three error codes -------------------------------------

CLOCK = "datetime.datetime.now"

# The one function that gives the time every record that holds a timestamp is given.
ONE_CLOCK = {"hypotrail.core.attempts:now": 1}

# {name: the one module that assigns it}
NAMES_ASSIGNED_ONCE = {"REVISIONS_DIR": {"hypotrail.core.revisions"}, "PARAMETERS_NAME": {"hypotrail.ml.predictions"}}

# {code: the one function that builds an error with it}: a code with two texts or two stages keeps each, given by its caller.
ONE_BUILDER = {
    "SCENARIOS_NOT_DECLARED": {"hypotrail.agentic.declaration:Workload.scenarios_file": 1},
    "DATABASE_CHANGED": {"hypotrail.agentic.declaration:database_changed": 1},
    "SECRET_IN_OUTPUT": {"hypotrail.core.attempts:leak": 1},
}


def clock_calls(trees: dict) -> dict:
    """{`module:function`: the number of its calls that resolve to `datetime.datetime.now`}, through the names the module imports or assigns."""
    return tally(site.owner for site in calls(trees) if site.callee == CLOCK)


def modules_assigning(trees: dict, name: str) -> set:
    """The modules that assign `name` anywhere: a plain, an annotated or an augmented assignment, unpacking included. An import that binds the name is not an assignment."""
    found = set()
    for module, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            else:
                continue
            if any(isinstance(each, ast.Name) and each.id == name for target in targets for each in ast.walk(target)):
                found.add(module)
    return found


def code_builders(trees: dict, code: str) -> dict:
    """{`module:function`: the number of its calls of `InvalidInputError`, `IntegrityError` or `HypotrailError` of `hypotrail.core.errors` whose code is the literal `code`}.

    The code is the first argument, or the keyword `code`; the class is resolved through the names the module imports or assigns.
    Stated limit: a code held in a variable, or an error built through another class than the three named, is outside the rule.
    """
    builders = []
    for site in calls(trees):
        if site.callee not in CODE_BUILDING_ERRORS:
            continue
        given = site.node.args[0] if site.node.args else next((k.value for k in site.node.keywords if k.arg == "code"), None)
        if isinstance(given, ast.Constant) and given.value == code:
            builders.append(site.owner)
    return tally(builders)


def test_datetime_now_is_called_in_one_function_each_path_name_is_assigned_in_one_module_and_each_of_three_codes_is_built_in_one_function():
    trees = parse_all(SOURCE)
    assert clock_calls(trees) == ONE_CLOCK
    assert modules_assigning(trees, "REVISIONS_DIR") == NAMES_ASSIGNED_ONCE["REVISIONS_DIR"]
    assert modules_assigning(trees, "PARAMETERS_NAME") == NAMES_ASSIGNED_ONCE["PARAMETERS_NAME"]
    assert code_builders(trees, "SCENARIOS_NOT_DECLARED") == ONE_BUILDER["SCENARIOS_NOT_DECLARED"]
    assert code_builders(trees, "DATABASE_CHANGED") == ONE_BUILDER["DATABASE_CHANGED"]
    assert code_builders(trees, "SECRET_IN_OUTPUT") == ONE_BUILDER["SECRET_IN_OUTPUT"]


ONE_OF_EACH_TREE = {
    "hypotrail/__init__.py": "",
    "hypotrail/core/__init__.py": "",
    "hypotrail/core/errors.py": "class HypotrailError(Exception):\n    pass\n\n\nclass InvalidInputError(HypotrailError):\n    pass\n\n\nclass IntegrityError(HypotrailError):\n    pass\n",
    "hypotrail/core/attempts.py": (
        "import datetime\n\nfrom hypotrail.core.errors import HypotrailError\n\n\n"
        "def now():\n    return datetime.datetime.now(datetime.timezone.utc).isoformat()\n\n\n"
        "def leak(files):\n    return HypotrailError('SECRET_IN_OUTPUT', 'm', stage='live', details={'files': files})\n"
    ),
    "hypotrail/core/revisions.py": "REVISIONS_DIR = 'revisions'\n",
    "hypotrail/agentic/__init__.py": "",
    "hypotrail/agentic/declaration.py": (
        "from hypotrail.core.errors import IntegrityError, InvalidInputError\n\n\n"
        "class Workload:\n    def scenarios_file(self):\n        raise InvalidInputError('SCENARIOS_NOT_DECLARED', 'm', stage='fixture')\n\n\n"
        "def database_changed(before, after, *, stage):\n    return IntegrityError('DATABASE_CHANGED', 'm', stage=stage)\n"
    ),
    "hypotrail/ml/__init__.py": "",
    "hypotrail/ml/predictions.py": "PARAMETERS_NAME = 'sklearn_params.json'\n",
}


def test_a_second_clock_a_second_assignment_of_each_path_name_and_a_second_builder_of_each_code_are_found_in_a_planted_tree(tmp_path):
    root = plant(tmp_path, ONE_OF_EACH_TREE)
    trees = parse_all(root)
    assert clock_calls(trees) == ONE_CLOCK
    assert modules_assigning(trees, "REVISIONS_DIR") == NAMES_ASSIGNED_ONCE["REVISIONS_DIR"]
    assert modules_assigning(trees, "PARAMETERS_NAME") == NAMES_ASSIGNED_ONCE["PARAMETERS_NAME"]
    assert {code: code_builders(trees, code) for code in ONE_BUILDER} == ONE_BUILDER
    plant(root, {
        "hypotrail/ml/stamp.py": "from datetime import datetime as moment\n\n\ndef stamped():\n    return moment.now()\n",
        "hypotrail/core/exposure.py": "REVISIONS_DIR: str = 'revisions'\n",
        "hypotrail/ml/run.py": "def names():\n    PARAMETERS_NAME, other = 'sklearn_params.json', None\n    return PARAMETERS_NAME\n",
        "hypotrail/agentic/fixture.py": (
            "from hypotrail.core.errors import HypotrailError as Coded, IntegrityError as Broken, InvalidInputError as Refused\n\n\n"
            "def load_scenarios(workload):\n    raise Refused('SCENARIOS_NOT_DECLARED', 'm', stage='fixture')\n\n\n"
            "def run_fixture():\n    raise Broken('DATABASE_CHANGED', 'm', stage='fixture')\n\n\n"
            "def scanned():\n    raise Coded(code='SECRET_IN_OUTPUT', message='m', stage='live')\n"
        ),
    })
    trees = parse_all(root)
    assert clock_calls(trees) == {**ONE_CLOCK, "hypotrail.ml.stamp:stamped": 1}
    assert modules_assigning(trees, "REVISIONS_DIR") == {"hypotrail.core.revisions", "hypotrail.core.exposure"}
    assert modules_assigning(trees, "PARAMETERS_NAME") == {"hypotrail.ml.predictions", "hypotrail.ml.run"}
    assert code_builders(trees, "SCENARIOS_NOT_DECLARED") == {**ONE_BUILDER["SCENARIOS_NOT_DECLARED"], "hypotrail.agentic.fixture:load_scenarios": 1}
    assert code_builders(trees, "DATABASE_CHANGED") == {**ONE_BUILDER["DATABASE_CHANGED"], "hypotrail.agentic.fixture:run_fixture": 1}
    assert code_builders(trees, "SECRET_IN_OUTPUT") == {**ONE_BUILDER["SECRET_IN_OUTPUT"], "hypotrail.agentic.fixture:scanned": 1}


# --- a file is hashed through `data.sha256_file`: `hashlib.sha256` is called in the listed modules only ----------------------------------

AGENTIC = "hypotrail.agentic"

# {module: what it hashes with `hashlib.sha256`}
HASHING_MODULES = {
    "hypotrail.core.canonical": "bytes held in memory (`sha256_hex`)",
    "hypotrail.core.data": "a file, read in blocks (`sha256_file`)",
    "hypotrail.core.fetch": "a download and an archive member while their bytes arrive, before any file holds them whole",
}


def sha256_functions(trees: dict, package: str) -> set:
    """`module:line` of every function named `_sha256`, nested ones included, in the modules of `package`."""
    return {
        f"{module}:{node.lineno}"
        for module, tree in trees.items()
        if module == package or module.startswith(package + ".")
        for node in ast.walk(tree)
        if isinstance(node, FUNCTION_NODES) and node.name == "_sha256"
    }


def hashing_modules(trees: dict) -> set:
    """The modules with a call that resolves to `hashlib.sha256`, through the names the module imports or assigns. Stated limit: `hashlib.new("sha256")` is outside it."""
    return {site.module for site in calls(trees) if site.callee == "hashlib.sha256"}


def test_no_agentic_module_defines_a_sha256_function_and_hashlib_sha256_is_called_in_the_listed_modules_only():
    trees = parse_all(SOURCE)
    assert sha256_functions(trees, AGENTIC) == set()
    found = hashing_modules(trees)
    union = sorted(found | set(HASHING_MODULES))
    assert {module: module in found for module in union} == {module: module in HASHING_MODULES for module in union}


def test_a_sha256_function_in_an_agentic_module_and_a_hashlib_sha256_call_outside_the_listed_modules_are_found_in_a_planted_tree(tmp_path):
    root = plant(tmp_path, {
        "hypotrail/__init__.py": "",
        "hypotrail/core/__init__.py": "",
        "hypotrail/core/data.py": "import hashlib\n\n\ndef sha256_file(path):\n    return hashlib.sha256(path.read_bytes()).hexdigest()\n",
        "hypotrail/agentic/__init__.py": "",
        "hypotrail/agentic/live.py": "import hashlib\n\n\ndef _sha256(path):\n    return hashlib.sha256(path.read_bytes()).hexdigest()\n",
        "hypotrail/agentic/run.py": "from hypotrail.core import data\n\n\ndef record(path):\n    def _sha256(p):\n        return data.sha256_file(p)\n\n    return _sha256(path)\n",
        "hypotrail/ml/__init__.py": "",
        "hypotrail/ml/run.py": "from hashlib import sha256 as digest\n\n\ndef f(raw):\n    return digest(raw).hexdigest()\n",
    })
    trees = parse_all(root)
    assert sha256_functions(trees, AGENTIC) == {"hypotrail.agentic.live:4", "hypotrail.agentic.run:5"}
    assert hashing_modules(trees) == {"hypotrail.core.data", "hypotrail.agentic.live", "hypotrail.ml.run"}
