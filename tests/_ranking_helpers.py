"""Synthetic builds of the accepted ranking contract and their CLI setup."""

import hashlib
import json
from pathlib import Path

import pytest

from _study_helpers import run_cli

CONTRACT = Path(__file__).resolve().parents[1] / "src/hypotrail/ml/contracts/ml-scores-1/examples"
WORKLOAD = "ranking-fixture"


def metadata(raw):
    return {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def write_build(tmp_path, *, items=None, references=None, held_out_references=None, cutoff="2011-12-10"):
    """Stage a small declared Workload and a private build in different folders."""
    build_dir = tmp_path / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    sources = {
        "items.csv": (CONTRACT / "items.csv").read_bytes() if items is None else items,
        "references-dev.csv": (CONTRACT / "references-dev.csv").read_bytes() if references is None else references,
    }
    if held_out_references is not None:
        sources["references-held_out.csv"] = held_out_references
    build = json.loads((CONTRACT / "build.json").read_bytes())
    build["label_cutoff"] = cutoff
    build["files"] = {name: metadata(raw) for name, raw in sources.items()}
    sources["build.json"] = json.dumps(build).encode()
    for name, raw in sources.items():
        (build_dir / name).write_bytes(raw)

    workload = tmp_path / "workloads" / WORKLOAD
    workload.mkdir(parents=True, exist_ok=True)
    notice = b"Synthetic ranking test fixture.\n"
    (workload / "NOTICE").write_bytes(notice)
    manifest = {
        "schema_version": "data-manifest/1",
        "sources": [
            {
                "dataset_id": name,
                **metadata(raw),
                "as_of": cutoff,
                "license": "Synthetic fixture",
                "notice": "NOTICE",
                "notice_sha256": metadata(notice)["sha256"],
            }
            for name, raw in sources.items()
        ],
    }
    (workload / "data-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    declaration = {
        "track": "ranking",
        "horizon_days": 90,
        "question": "Can a score rank future events?",
        "objective": "Rank the Items of a single Partition.",
        "limitations": [],
    }
    (workload / "workload.json").write_text(json.dumps(declaration), encoding="utf-8")
    return workload.parent, build_dir


@pytest.fixture
def ranking_paths(tmp_path):
    examples, build_dir = write_build(tmp_path)
    return examples, build_dir, tmp_path / "study"


def command(*args):
    code, out, err = run_cli(*map(str, args), "--json")
    return code, json.loads(out), err


def initialize(paths, *, new_revision=False):
    examples, build_dir, study = paths
    operation = ["--new-revision"] if new_revision else ["--workload", WORKLOAD]
    return command("init", *operation, "--examples-dir", examples, "--build-dir", build_dir, "--study", study)
