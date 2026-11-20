"""Shared by the revision and rescoring tests (#70, #73 Tightened B4): corrected Workloads, `init --new-revision`, snapshots."""

import json
import shutil
from pathlib import Path

from _study_helpers import EXAMPLES, run_json, sha256


def corrected_chinook_references(tmp_path, edit, *, name="corrected"):
    """A private copy of `examples/` whose Chinook References records `edit` changes.

    `edit` receives the records by `case_id` and changes them in place. The data lock does not cover the
    References file, so the copy still verifies and `init --new-revision` can read it.
    """
    target = tmp_path / name
    shutil.copytree(EXAMPLES, target)
    path = target / "chinook" / "references" / "chinook-references.jsonl"
    records = {r["case_id"]: r for r in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())}
    edit(records)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records.values()), encoding="utf-8")
    return target


def new_revision(study, *more):
    return run_json("init", "--study", study, "--new-revision", *more)


def snapshot_files(folder) -> dict:
    """{relative path: sha256} of every file under `folder`."""
    return {p.relative_to(folder).as_posix(): sha256(p) for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def spec_of(study) -> dict:
    return json.loads((Path(study) / "study.json").read_text(encoding="utf-8"))


def entry_of(spec, role) -> dict:
    return next(e for e in spec["artifacts"] if e["ref"]["role"] == role)


def error_of(payload) -> dict:
    error = payload["error"]
    assert set(error) == {"code", "message", "stage", "details"}
    return error
