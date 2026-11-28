"""How a command finds the Workloads (#23, D-016 on chadlis/hypotrail#75): one resolver, the flag first, the checkout's `examples/` second, else a refusal.

The package is imported from a copy placed where an install puts it (no `examples/` beside it) or where a checkout has it,
and the command runs in a subprocess from that copy. No case reads the key, imports a provider or calls a model.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _assess_helpers import assess, fresh_study, observation_set_id, references_id, snapshot
from _chinook_helpers import FIXTURE, fixture_population, init_chinook
from _exposure_helpers import assess_agent, import_public
from _import_helpers import export, mapping_of, population_of
from _study_helpers import EXAMPLES, ROOT, init_study

from hypotrail import cli
from hypotrail.core import live as core_live

VARIABLE = "HYPOTRAIL_EXAMPLES_DIR"
UNDECLARED = "CONFIGURATION_NOT_DECLARED"


# --- the installs ---------------------------------------------------------------------------------------------------


def _copy_package(target: Path) -> Path:
    shutil.copytree(ROOT / "src" / "hypotrail", target, ignore=shutil.ignore_patterns("__pycache__"))
    return target.parent


@pytest.fixture(scope="module")
def installs(tmp_path_factory):
    """Where the package can sit: {name: (directory to put on the import path, the examples/ a checkout would hold or None)}."""
    base = tmp_path_factory.mktemp("installs")
    outside = _copy_package(base / "wheel" / "lib" / "site-packages" / "hypotrail")  # no examples/ beside it
    bare = _copy_package(base / "bare" / "src" / "hypotrail")
    (base / "bare" / "examples" / "notes").mkdir(parents=True)  # exists, holds no Workload lock
    (base / "bare" / "examples" / "README.txt").write_text("not a Workload", encoding="utf-8")
    checkout = _copy_package(base / "checkout" / "src" / "hypotrail")
    (base / "checkout" / "examples").symlink_to(EXAMPLES, target_is_directory=True)
    copy = base / "copy-of-examples"
    shutil.copytree(EXAMPLES, copy)  # what a user passes to `--examples-dir`
    return {"outside": outside, "bare": bare, "checkout": checkout, "copy": copy, "no_lock": base / "no-lock"}


def _run(install: Path, argv, *, cwd: Path, extra_env=None):
    """The command in a subprocess whose `hypotrail` is the copy at `install`, with no key in the environment."""
    env = {k: v for k, v in os.environ.items() if k not in (core_live.KEY_VARIABLE, "ANTHROPIC_AUTH_TOKEN", "PYTHONPATH")}
    env["PYTHONPATH"] = str(install)
    env.update(extra_env or {})
    probe = "import hypotrail, sys; from hypotrail.cli import main; assert hypotrail.__file__.startswith(sys.argv[1]); sys.exit(main(sys.argv[2:]))"
    done = subprocess.run(
        [sys.executable, "-c", probe, str(install), *map(str, argv), "--json"], capture_output=True, text=True, cwd=cwd, env=env
    )
    try:
        payload = json.loads(done.stdout)
    except ValueError:
        payload = {"unparsed": done.stdout, "stderr": done.stderr}
    return done.returncode, payload


# --- the commands: what each needs, and what it does once the Workloads are found ---------------------------------------


def _data_verify(root):
    return ["data", "verify"], None


def _init(root):
    return ["init", "--workload", "bike_day", "--study", root / "study"], None


def _new_revision(root):
    study, _ = init_study(root)
    return ["init", "--study", study, "--new-revision"], "PROTOCOL_UNCHANGED"


def _run_ml(root):
    study, _ = init_study(root)
    return ["run", "ml", "--study", study, "--config", "seasonal_7", "--partition", "dev", "--request-id", "r"], None


def _run_agent(root):
    study, _ = init_chinook(root)
    return ["run", "agent", "--study", study, "--mode", "llm_live", "--config", "nonesuch", "--request-id", "r", "--partition", "dev", "--repeats", "1", "--model", "anthropic/m"], UNDECLARED


def _import_ml(root):
    study, _ = init_study(root)
    source, digest = export(root)
    return ["import", "ml", "--study", study, "--source", source, "--mapping", mapping_of(root, digest), "--population", population_of(root, source), "--request-id", "i"], None


def _import_agent(root):
    study, _ = init_chinook(root)
    return ["import", "agent", "--study", study, "--source", FIXTURE, "--population", fixture_population(root), "--request-id", "i"], None


def _assess_ml(root):
    study, attempts = fresh_study(root, "seasonal_7", partition="public_check")
    return ["assess", "--study", study, "--observations", observation_set_id(study, attempts["seasonal_7"]), "--scorer", "regression_mae_v1", "--references", references_id(study)], None


def _compare_ml(root):
    study, attempts = fresh_study(root, "seasonal_7", "ridge_v1", partition="public_check")
    ids = []
    for config in ("seasonal_7", "ridge_v1"):
        _, payload, _ = assess(study, observation_set_id(study, attempts[config]), "regression_mae_v1", references_id(study))
        ids.append(payload["assessment"]["assessment_id"])
    return ["compare", "--study", study, "--control", ids[0], "--candidate", ids[1]], None


def _assess_agent(root):
    study, _ = init_chinook(root)
    attempt = import_public(root, study, "pub")
    return ["assess", "--study", study, "--observations", observation_set_id(study, attempt), "--scorer", "chinook_contract_v1", "--references", references_id(study)], None


def _compare_agent(root):
    study, _ = init_chinook(root)
    ids = []
    for name in ("pub-a", "pub-b"):
        attempt = import_public(root, study, name)
        _, payload, _ = assess_agent(study, attempt)
        ids.append(payload["assessment"]["assessment_id"])
    return ["compare", "--study", study, "--control", ids[0], "--candidate", ids[1]], None


def _report(root):
    study, _ = fresh_study(root, "seasonal_7", partition="public_check")  # its outputs are public_check Items: the page is an Exposure, which reads the Workload
    return ["report", "--study", study, "--out", root / "page.html"], None


def _profile(root):
    study, _ = fresh_study(root, "seasonal_7")
    return ["profile", "--study", study], None


def _spike_live(root):
    return ["spike", "live", "--config", "nonesuch", "--model", "anthropic/m", "--out", root / "out"], UNDECLARED


# (parser path of the command, builder). One row per way a command reads a Workload.
ROWS = {
    "data verify": ("data verify", _data_verify),
    "init": ("init", _init),
    "init --new-revision": ("init", _new_revision),
    "run ml": ("run ml", _run_ml),
    "run agent": ("run agent", _run_agent),
    "import ml": ("import ml", _import_ml),
    "import agent": ("import agent", _import_agent),
    "assess (ml)": ("assess", _assess_ml),
    "assess (agent)": ("assess", _assess_agent),
    "compare (ml)": ("compare", _compare_ml),
    "compare (agent)": ("compare", _compare_agent),
    "report": ("report", _report),
    "profile": ("profile", _profile),
    "spike live": ("spike live", _spike_live),
}


def _outcome(result):
    code, payload = result
    return code, (payload.get("error", {}).get("code") if payload.get("ok") is False else None)


def _tree(root: Path):
    return {p.relative_to(root).as_posix() for p in root.rglob("*")} | {"/" + k for k in snapshot(root)}


def _setup(tmp_path, name):
    """(a fresh working folder, the command's arguments, the code of its refusal once the Workloads are found or None for success)."""
    root = tmp_path / "work"
    root.mkdir()
    (root / "cwd").mkdir()
    argv, expected = ROWS[name][1](root)
    return root, argv, expected


@pytest.mark.parametrize("name", ROWS)
def test_without_a_flag_outside_a_checkout_a_command_is_refused_before_any_write_and_names_the_flag(name, installs, tmp_path):
    root, argv, expected = _setup(tmp_path, name)
    before = _tree(root)
    code, payload = _run(installs["outside"], argv, cwd=root / "cwd")
    assert (code, payload["ok"]) == (2, False), payload
    assert "--examples-dir" in payload["error"]["message"], payload["error"]
    assert _tree(root) == before, "a write happened before the refusal"


@pytest.mark.parametrize("name", ROWS)
def test_a_checkout_whose_examples_holds_no_workload_lock_refuses_like_no_checkout(name, installs, tmp_path):
    root, argv, expected = _setup(tmp_path, name)
    before = _tree(root)
    code, payload = _run(installs["bare"], argv, cwd=root / "cwd")
    assert (code, payload["ok"]) == (2, False), payload
    assert "--examples-dir" in payload["error"]["message"], payload["error"]
    assert _tree(root) == before, "a write happened before the refusal"


@pytest.mark.parametrize("name", ROWS)
def test_the_flag_naming_a_copy_gets_past_resolution_and_the_key_is_never_read(name, installs, tmp_path):
    root, argv, expected = _setup(tmp_path, name)
    code, payload = _run(installs["outside"], [*argv, "--examples-dir", installs["copy"]], cwd=root / "cwd")
    if expected is None:
        assert (code, payload.get("ok")) == (0, True), payload
    else:
        # the Workload was found (the Configuration is checked against its declaration) and the key was not read
        assert (code, payload["error"]["code"]) == (2, expected), payload


@pytest.mark.parametrize("name", ROWS)
def test_the_variable_does_not_select_the_workloads(name, installs, tmp_path):
    root, argv, expected = _setup(tmp_path, name)
    before = _tree(root)
    code, payload = _run(installs["outside"], argv, cwd=root / "cwd", extra_env={VARIABLE: str(installs["copy"])})
    assert (code, payload["ok"]) == (2, False), payload
    assert "--examples-dir" in payload["error"]["message"], payload["error"]
    assert _tree(root) == before


@pytest.mark.parametrize("name", ROWS)
def test_an_editable_checkout_finds_its_examples_without_a_flag_and_the_flag_takes_precedence(name, installs, tmp_path):
    root, argv, expected = _setup(tmp_path, name)
    default = _outcome(_run(installs["checkout"], argv, cwd=root / "cwd"))
    assert default == ((0, None) if expected is None else (2, expected))
    # `--examples-dir` wins: a directory with no Workload is not the checkout's examples/
    installs["no_lock"].mkdir(exist_ok=True)
    root2, argv2, _ = _setup(tmp_path / "second", name) if (tmp_path / "second").mkdir() is None else None
    named = _outcome(_run(installs["checkout"], [*argv2, "--examples-dir", installs["no_lock"]], cwd=root2 / "cwd"))
    assert named != default and named[0] != 0


def test_a_report_of_dev_items_needs_no_flag_where_no_workload_is_found_and_its_data_profile_holds_the_refusal_code(installs, tmp_path):
    """D-016 on chadlis/hypotrail#75 and #85 Tightened H: a page of `dev` Items works from any install. Its data profile reads the Workload,
    and "the report never fails because of the profile" (D-153 on chadlis/hypotrail#75): the section holds the resolver's code."""
    root = tmp_path / "work"
    (root / "cwd").mkdir(parents=True)
    study, _ = fresh_study(root, "seasonal_7")
    argv = ["report", "--study", study, "--out", root / "page.html"]
    code, payload = _run(installs["outside"], argv, cwd=root / "cwd")
    assert (code, payload.get("ok")) == (0, True), payload
    assert payload["report"]["exposure"]["recorded"] is False and (root / "page.html").is_file()
    assert "The data profile could not be read: <code>EXAMPLES_DIR_NOT_FOUND</code>." in (root / "page.html").read_text(encoding="utf-8")


# --- the parser and the list --------------------------------------------------------------------------------------------


def _parsers_taking_the_flag():
    found = set()

    def walk(parser, path):
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    walk(child, [*path, name])
        if any("--examples-dir" in a.option_strings for a in parser._actions):
            found.add(" ".join(path))

    walk(cli.build_parser(), [])
    return found


def test_the_commands_of_the_list_are_exactly_the_commands_the_parser_gives_the_flag():
    assert {path for path, _ in ROWS.values()} == _parsers_taking_the_flag()
    assert "spike live" in _parsers_taking_the_flag()


def test_every_command_the_parser_defines_either_takes_the_flag_or_reads_no_workload():
    leaves = set()

    def walk(parser, path):
        children = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        for action in children:
            for name, child in action.choices.items():
                walk(child, [*path, name])
        if not children and path:
            leaves.add(" ".join(path))

    walk(cli.build_parser(), [])
    # A new command must appear in the Workload list or in this inventory of commands that operate without one.
    # `review import` reads the aggregate receipt and the ordinary Study only.
    assert leaves - _parsers_taking_the_flag() == {
        "status", "figures", "lesson", "recover", "data fetch", "decide", "deviation", "review import",
    }
