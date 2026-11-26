"""Shared by the tests of the frozen demonstration (`docs/demo/demonstration.py`): the script's own step list, run in process.

The script starts each process through the function it is given. The tests give it `Recorder`, which runs the CLI in process (so the
suite's network guard applies) and keeps, for each command, what it printed and the state of the Study it names before and after. The
two other programs of the step list, `docs/demo/edit_copy.py` and the Claude Code hook, are started as processes, each recorded by its
name: they are outside the guard.
"""

import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import types
from collections import namedtuple
from pathlib import Path

from _study_helpers import run_json

from hypotrail import cli

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "docs" / "demo" / "demonstration.py"
LIVE_KEY = "HYPOTRAIL_ANTHROPIC_API_KEY"

Run = namedtuple("Run", "module work outcome transcript calls key_in_environment examples_before examples_after")


def demonstration():
    """The script as a module, its source run as a module that is not `__main__`, which runs no step. The source is compiled each
    time, so no bytecode cache is written into the checkout or read back from an earlier version of the file."""
    module = types.ModuleType("demonstration")
    module.__file__ = str(SCRIPT)
    exec(compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec"), module.__dict__)
    return module


def cli_in_process(args):
    """(exit code, stdout, stderr) of the CLI given `args`, in this process; `--help` exits through argparse, as a person sees it."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(args))
        except SystemExit as exit:
            code = exit.code or 0
    return code, out.getvalue(), err.getvalue()


def study_of(args) -> Path | None:
    """The Study an argument list names, as `--study DIR` or as `--study=DIR`."""
    if "--study" in args:
        return Path(args[args.index("--study") + 1])
    joined = [part.removeprefix("--study=") for part in args if part.startswith("--study=")]
    return Path(joined[0]) if joined else None


def digests(folder: Path) -> dict:
    """{name: SHA-256} of each file directly in `folder`; {} when there is none."""
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(folder.glob("*")) if path.is_file()} if folder.is_dir() else {}


def tracked_examples() -> dict:
    """{path: SHA-256} of each file `git ls-files examples` lists in the checkout."""
    listing = subprocess.run(["git", "ls-files", "-z", "examples"], cwd=ROOT, capture_output=True, text=True, check=True)
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(listing.stdout.split("\0")) if name}


def journal_entries(study: Path) -> list:
    """The entries of the Study's write journal, read from its files in their order."""
    folder = study / "write_journal"
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))] if folder.is_dir() else []


def headings(page: Path) -> list:
    return re.findall(r"<h2[^>]*>([^<]*)</h2>", page.read_text(encoding="utf-8"))


def program_of(argv) -> tuple:
    """(the name of the program, its arguments) of a process that is not a command of the CLI: the first `.py` file it starts."""
    [at] = [at for at, part in enumerate(argv) if part.endswith(".py")][:1]
    return Path(argv[at]).name, argv[at + 1:]


class Recorder:
    """The function the tests give the script to start a process: the CLI in process, another program as a process, each call kept with
    the Study it names."""

    def __init__(self, module):
        self.module = module
        self.prefix = list(module.CLI)
        self.calls = []

    def __call__(self, argv, env, cwd, text=None):
        argv = list(argv)
        cli_call = argv[: len(self.prefix)] == self.prefix
        program, args = (None, argv[len(self.prefix):]) if cli_call else program_of(argv)
        study = study_of(args)
        call = {"program": program, "args": args, "env": sorted(env), "input": text, "study": study, "before": self.sequence(study)}
        code, out, err = cli_in_process(args) if cli_call else self.module.start_process(argv, env, cwd, text)
        call.update(code=code, out=out, err=err, payload=json.loads(out) if "--json" in args and out.strip() else None)
        if study is not None and (study / "study.json").is_file():
            call["status"] = run_json("status", "--study", study)[1]
            call["since"] = run_json("status", "--study", study, "--since", "0")[1]
            call["journal"] = journal_entries(study)
            call["decision_files"] = digests(study / "decisions")
        if args[:1] == ["report"] and code == 0:
            page = Path(args[args.index("--out") + 1])
            call["headings"] = headings(page)
        self.calls.append(call)
        return code, out, err

    @staticmethod
    def sequence(study):
        if study is None or not (study / "study.json").is_file():
            return 0
        return run_json("status", "--study", study)[1]["write_sequence"]


def run_in_process(work: Path, steps=None) -> Run:
    """The step list (the script's own when `steps` is None) carried out once in the work folder, each process through `Recorder`, with
    the SHA-256 of each tracked file under `examples/` read before and after."""
    module = demonstration()
    recorder, out = Recorder(module), io.StringIO()
    before = tracked_examples()
    outcome = module.run(work, start=recorder, out=out, steps=steps)
    return Run(module, work, outcome, out.getvalue(), recorder.calls, LIVE_KEY in os.environ, before, tracked_examples())


EXPANDED = demonstration().processes


def processes(steps) -> list:
    """(step id, process) of each process of the step list, in order: each command of the CLI, the two reads of each kept state included,
    and each other program."""
    return [(step["id"], each) for step in steps for action in step["actions"] for each in EXPANDED(action)]


def commands(steps) -> list:
    """(step id, action) of each command of the CLI of the step list, in order."""
    return [(step_id, each) for step_id, each in processes(steps) if "cli" in each]


PATH_PART = re.compile(r"\.?([A-Za-z_][A-Za-z0-9_]*)|\[(-?\d+|\*)\]")


def walked(value, parts):
    for at, (name, index) in enumerate(parts):
        if index == "*":
            return [walked(entry, parts[at + 1:]) for entry in value]
        value = value[name] if name else value[int(index)]
    return value


def value_at(payload, path: str):
    """The value at a key path such as `assessment.metrics[0].value`, `len(freeze_records)` for the number of entries, or
    `decisions[*].applies` for that value in each entry of the list."""
    counted = path.startswith("len(") and path.endswith(")")
    value = walked(payload, PATH_PART.findall(path[4:-1] if counted else path))
    return len(value) if counted else value
