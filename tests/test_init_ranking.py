"""The private development build is verified and its dev References are frozen."""

import json
import os
from pathlib import Path

import pytest

from _ranking_helpers import CONTRACT, WORKLOAD, command, initialize, ranking_paths, write_build

REFUSALS = ("reference-duplicate", "reference-immature-item", "reference-item-unknown", "reference-label-not-binary")


def verify(examples, *args):
    return command("data", "verify", "--workload", WORKLOAD, "--examples-dir", examples, *args)


def test_data_verify_checks_private_build_bytes_and_keeps_manifest_only_mode(ranking_paths):
    examples, build_dir, _ = ranking_paths
    code, declared, err = verify(examples)
    assert code == 0, (declared, err)
    assert {record["status"] for record in declared["datasets"]} == {"declared"}

    code, verified, err = verify(examples, "--build-dir", build_dir)
    assert code == 0, (verified, err)
    assert {record["status"] for record in verified["datasets"]} == {"verified"}
    assert {record["dataset_id"]: record["sha256"] for record in verified["datasets"]} == {
        record["dataset_id"]: record["sha256"] for record in declared["datasets"]
    }

    items = build_dir / "items.csv"
    items.write_bytes(items.read_bytes().replace(b"12347", b"12397"))
    code, refused, _ = verify(examples, "--build-dir", build_dir)
    assert (code, refused["error"]["code"]) == (3, "DATA_INTEGRITY")
    assert refused["error"]["details"]["file"] == "items.csv"
    assert verify(examples)[0] == 0


def test_verified_bytes_stay_outside_git_and_contain_no_symlinks(ranking_paths):
    examples, build_dir, _ = ranking_paths
    repository = build_dir.parent / ".git"
    repository.mkdir()
    head = repository / "HEAD"
    head.write_text("ref: refs/heads/main\n", encoding="utf-8")
    code, refused, _ = verify(examples, "--build-dir", build_dir)
    assert (code, refused["error"]["code"]) == (2, "RANKING_BUILD_IN_REPOSITORY")
    head.unlink()
    repository.rmdir()

    references = build_dir / "references-dev.csv"
    target = build_dir.parent / "synthetic.csv"
    references.rename(target)
    references.symlink_to(target)
    code, refused, _ = verify(examples, "--build-dir", build_dir)
    assert (code, refused["error"]["code"]) == (3, "DATA_MISSING")


def test_init_needs_an_explicit_build_and_never_opens_a_held_out_reference(ranking_paths, monkeypatch):
    examples, build_dir, study = ranking_paths
    code, refused, _ = command("init", "--workload", WORKLOAD, "--examples-dir", examples, "--study", study)
    assert (code, refused["error"]["code"]) == (2, "RANKING_BUILD_REQUIRED")
    assert not study.exists()

    # A synthetic safety sentinel. The open guard checks the operation without reading the file.
    sentinel = build_dir / "references-held_out.csv"
    sentinel.write_bytes(b"synthetic safety sentinel\n")
    original = Path.open

    def checking_open(path, *args, **kwargs):
        if path == sentinel:
            pytest.fail("rank development tried to open a protected References file")
        return original(path, *args, **kwargs)

    open_descriptor = os.open

    def checking_descriptor(path, *args, **kwargs):
        if path in (sentinel, str(sentinel)):
            pytest.fail("rank development tried to open a protected References file")
        return open_descriptor(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checking_open)
    monkeypatch.setattr(os, "open", checking_descriptor)
    code, initialized, err = initialize(ranking_paths)
    assert code == 0, (initialized, err)
    spec = initialized["study"]
    assert spec["domain"] == "ranking"
    assert spec["primary_metric"]["id"] == "recall_at_top_fraction"
    references = next(entry for entry in spec["artifacts"] if entry["artifact_id"] == initialized["references_id"])
    assert (study / references["ref"]["path"]).read_bytes() == (build_dir / "references-dev.csv").read_bytes()
    assert all(b"12346@2011-06-01" not in path.read_bytes() for path in study.rglob("*") if path.is_file())


@pytest.mark.parametrize("case", REFUSALS)
def test_each_refused_references_file_is_refused_by_init_with_its_code(case, tmp_path):
    examples, build_dir = write_build(tmp_path)
    study = tmp_path / "study"
    assert initialize((examples, build_dir, study))[0] == 0
    earlier = (study / "study.json").read_bytes()
    case_dir = CONTRACT / "refused" / case
    expected = json.loads((case_dir / "expected.json").read_bytes())
    write_build(tmp_path, references=(case_dir / "references-dev.csv").read_bytes())

    new_study = tmp_path / "fresh"
    for paths, new_revision in (((examples, build_dir, new_study), False), ((examples, build_dir, study), True)):
        code, refused, _ = initialize(paths, new_revision=new_revision)
        assert (code, refused["error"]["code"]) == (expected["exit"], expected["code"])
    assert not new_study.exists()
    assert (study / "study.json").read_bytes() == earlier


def test_data_verify_refuses_a_hard_link_or_a_symbolic_replacement_before_reading(ranking_paths, monkeypatch):
    examples, build_dir, _ = ranking_paths
    source = build_dir / "references-dev.csv"
    alias_target = build_dir.parent / "synthetic-reference.csv"
    source.rename(alias_target)
    source.hardlink_to(alias_target)
    code, refused, _ = verify(examples, "--build-dir", build_dir)
    assert (code, refused["error"]["code"]) == (3, "DATA_MISSING")
    source.unlink()
    alias_target.rename(source)

    real_open = os.open

    def exchange_before_open(path, flags, *args, **kwargs):
        if path == source:
            source.rename(alias_target)
            source.symlink_to(alias_target)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", exchange_before_open)
    code, refused, _ = verify(examples, "--build-dir", build_dir)
    assert (code, refused["error"]["code"]) == (3, "DATA_MISSING")
