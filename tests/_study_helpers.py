"""Shared by the Study tests (#64): run the command line in process, copy the Bike Workload, edit it."""

import contextlib
import copy
import csv
import hashlib
import io
import json
import shutil
from pathlib import Path

from hypotrail import cli

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main([str(a) for a in args])
    return code, out.getvalue(), err.getvalue()


def run_json(*args):
    """The exit code and the one JSON object on stdout (`--json` is appended)."""
    code, out, err = run_cli(*args, "--json")
    return code, json.loads(out), err


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def examples_copy(tmp_path, *, edit=None, rows=None, name="examples") -> Path:
    """A private copy of `examples/` whose Bike declaration (`edit`) or data rows (`rows`) may be changed.

    A changed data file gets its lock entry (size and sha256) rewritten, so that the copy still verifies.
    """
    target = tmp_path / name
    shutil.copytree(EXAMPLES, target)
    bike = target / "bike_day"
    if edit is not None:
        declaration = json.loads((bike / "workload.json").read_text(encoding="utf-8"))
        edit(declaration)
        (bike / "workload.json").write_text(json.dumps(declaration, indent=2), encoding="utf-8")
    if rows is not None:
        data = bike / "data" / "day.csv"
        with data.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fieldnames, table = reader.fieldnames, list(reader)
        rows(table)
        with data.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(table)
        lock_path = bike / "data-sources.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        for source in lock["sources"]:
            if source["local_path"] == "data/day.csv":
                source["sha256"], source["size_bytes"] = sha256(data), data.stat().st_size
        lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
    return target


def init_study(tmp_path, *, examples=None, name="study", **extra):
    study = tmp_path / name
    args = ["init", "--workload", "bike_day", "--study", study]
    if examples is not None:
        args += ["--examples-dir", examples]
    code, payload, err = run_json(*args, *extra.get("more", []))
    assert code == 0, (payload, err)
    return study, payload


def run_ml(study, config, partition, request_id, *more):
    return run_json("run", "ml", "--study", study, "--config", config, "--partition", partition, "--request-id", request_id, *more)


def declaration_of(path: Path) -> dict:
    return copy.deepcopy(json.loads((Path(path) / "workload.json").read_text(encoding="utf-8")))
