"""Ticket #14: a locked uv project on Python 3.13, with optional extras."""

import json
import socket
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_interpreter_is_python_3_13():
    assert sys.version_info[:2] == (3, 13)


def test_help_exits_zero():
    result = subprocess.run(
        [sys.executable, "-m", "hypotrail", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "hypotrail" in result.stdout


# Loaded in a fresh interpreter: what the core imports on top of what Python
# itself started with. Snapshot first, then run the command.
_IMPORT_PROBE = """
import json, runpy, sys
before = set(sys.modules)
code = None
try:
    if sys.argv[1] == "help":
        sys.argv = ["hypotrail", "--help"]
        try:
            runpy.run_module("hypotrail", run_name="__main__")
        except SystemExit as exit_:
            code = exit_.code
    else:
        import hypotrail
        import hypotrail.core
finally:
    new = sorted({m.split(".")[0] for m in set(sys.modules) - before})
    print(json.dumps({"new": new, "code": code}))
"""


@pytest.mark.parametrize("mode", ["help", "import"])
def test_core_loads_only_the_standard_library(mode):
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE, mode],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(result.stdout.strip().splitlines()[-1])
    foreign = [
        name
        for name in report["new"]
        if name not in sys.stdlib_module_names and name != "hypotrail"
    ]
    assert foreign == []
    if mode == "help":
        assert report["code"] == 0
    assert "inspect_ai" not in report["new"]
    assert "sklearn" not in report["new"]


def _pyproject():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def _locked_versions():
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    return {p["name"]: p["version"] for p in lock["package"]}


def test_the_core_depends_on_one_schema_validator_and_inspect_scikit_learn_numpy_scipy_are_extras():
    project = _pyproject()["project"]
    assert project["dependencies"] == ["jsonschema==4.26.0"]
    extras = project["optional-dependencies"]
    assert any(d.startswith("inspect-ai") for d in extras["agent"])
    assert {d.split("==")[0] for d in extras["ml"]} == {"numpy", "scikit-learn", "scipy"}


def test_every_dependency_is_pinned_exactly_and_matches_the_committed_lock():
    locked = _locked_versions()
    project = _pyproject()["project"]
    pinned = list(project["dependencies"]) + [dep for deps in project["optional-dependencies"].values() for dep in deps]
    assert pinned, "no extras declared"
    for dep in pinned:
        name, sep, version = dep.partition("==")
        assert sep == "==", f"{dep} is not pinned to an exact version"
        assert locked[name] == version


def test_default_tests_make_no_live_call_even_with_a_model_key(
    monkeypatch, network_guard
):
    monkeypatch.setenv("HYPOTRAIL_ANTHROPIC_API_KEY", "key-for-the-guard-test")
    with pytest.raises(Exception, match="network access attempted"):
        socket.create_connection(("api.anthropic.com", 443), timeout=1)
    assert network_guard.attempts
    network_guard.acknowledge()


def test_the_core_docstring_names_jsonschema_and_does_not_claim_the_standard_library_only():
    # #40, I: core/chinook_contract.py imports jsonschema (ENV-02, pyproject.toml).
    import hypotrail.core

    assert "jsonschema" in hypotrail.core.__doc__
    assert "standard library only" not in hypotrail.core.__doc__
    assert "from jsonschema import" in (ROOT / "src" / "hypotrail" / "core" / "chinook_contract.py").read_text(encoding="utf-8")
