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

from _architecture import SOURCE, calls, imports, parse_all
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
    "ml": {"jsonschema", "numpy", "sklearn"},
    "report": set(),
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

IMPORT_MODULES = ("hypotrail.ml.imports", "hypotrail.agentic.imports")
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
