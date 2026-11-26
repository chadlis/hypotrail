"""Shared by the tests of the frozen demonstration (`docs/demo/demonstration.py`): the script's own step list, run in process.

The script starts each command through the function it is given. The tests give it `Recorder`, which runs the CLI in process (so the
suite's network guard applies) and keeps, for each command, what it printed and the state of the Study it names before and after.
"""

import contextlib
import io
import json
import os
import re
import types
from collections import namedtuple
from pathlib import Path

from _study_helpers import run_json

from hypotrail import cli

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "docs" / "demo" / "demonstration.py"
LIVE_KEY = "HYPOTRAIL_ANTHROPIC_API_KEY"

Run = namedtuple("Run", "module work outcome transcript calls key_in_environment")


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
    return Path(args[args.index("--study") + 1]) if "--study" in args else None


def journal_entries(study: Path) -> list:
    """The entries of the Study's write journal, read from its files in their order."""
    folder = study / "write_journal"
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))] if folder.is_dir() else []


def headings(page: Path) -> list:
    return re.findall(r"<h2[^>]*>([^<]*)</h2>", page.read_text(encoding="utf-8"))


class Recorder:
    """The function the tests give the script to start a command: the CLI in process, each call kept with the Study it names."""

    def __init__(self, module):
        self.prefix = list(module.CLI)
        self.calls = []

    def __call__(self, argv, env, cwd):
        argv = list(argv)
        assert argv[: len(self.prefix)] == self.prefix, f"not a command of the CLI: {argv}"
        args = argv[len(self.prefix):]
        study = study_of(args)
        call = {"args": args, "env": sorted(env), "cwd": cwd, "study": study, "before": self.sequence(study)}
        code, out, err = cli_in_process(args)
        call.update(code=code, out=out, err=err, payload=json.loads(out) if "--json" in args and out.strip() else None)
        if study is not None and (study / "study.json").is_file():
            call["status"] = run_json("status", "--study", study)[1]
            call["since"] = run_json("status", "--study", study, "--since", "0")[1]
            call["journal"] = journal_entries(study)
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
    """One run of the step list (the script's own when `steps` is None) in the work folder, each command through `Recorder`."""
    module = demonstration()
    recorder, out = Recorder(module), io.StringIO()
    outcome = module.run(work, start=recorder, out=out, steps=steps)
    return Run(module, work, outcome, out.getvalue(), recorder.calls, LIVE_KEY in os.environ)


def commands(steps) -> list:
    """(step id, action) of each command of the step list, in order: every action that starts a process."""
    return [(step["id"], action) for step in steps for action in step["actions"] if "cli" in action]


PATH_PART = re.compile(r"\.?([A-Za-z_][A-Za-z0-9_]*)|\[(-?\d+)\]")


def value_at(payload, path: str):
    """The value at a key path such as `assessment.metrics[0].value`, or `len(freeze_records)` for the number of entries."""
    counted = path.startswith("len(") and path.endswith(")")
    value = payload
    for name, index in PATH_PART.findall(path[4:-1] if counted else path):
        value = value[name] if name else value[int(index)]
    return len(value) if counted else value
