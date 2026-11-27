"""Check lesson packs using synthetic kept reads and explicit discovery environments."""

import json
import os
import shutil
from pathlib import Path

import pytest
from _study_helpers import ROOT, run_cli, run_json

PACKS = ROOT / "tests" / "fixtures" / "lesson_packs"
ENV_VAR = "HYPOTRAIL_LESSON_PACKS"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def kept(tmp_path):
    directory = tmp_path / "kept"
    write_json(directory / "status-bike.out", {"ok": True, "comparisons": [{"delta": {"value": 0.5}, "reference_notes": []}]})
    write_json(directory / "journey" / "after-compare.figures.out", {"ok": True, "comparisons": [{"quartiles": {"median": 0.5}}]})
    # Neither a read of the other Track nor a refusal can satisfy an unresolved path.
    write_json(directory / "status-chinook.out", {"ok": True, "comparisons": [{"interval": {"lower": 0.1}}]})
    write_json(directory / "status-bike-refused.out", {"ok": False, "comparisons": [{"interval": {"lower": 0.1}}]})
    return directory


def test_lesson_check_accepts_the_minimal_pack_and_writes_nothing(kept, tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    pack = tmp_path / "pack"
    shutil.copytree(PACKS / "minimal", pack)

    def snapshot():
        return {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    before = snapshot()
    code, payload, stderr = run_json("lesson", "check", pack, "--kept", kept)
    assert code == 0, stderr
    assert payload["ok"] is True
    assert snapshot() == before


def test_lesson_check_requires_kept_reads(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    code, payload, _ = run_json("lesson", "check", PACKS / "minimal")
    assert code == 2
    assert payload["error"]["code"] == "INVALID_ARGUMENTS"
    assert "--kept" in payload["error"]["message"]


@pytest.mark.parametrize(
    ("fixture", "rule", "lesson_id"),
    [
        ("schema", "SCHEMA", "read-the-delta"),
        ("digit", "DIGIT", "read-the-delta"),
        ("unresolved-path", "UNRESOLVED_PATH", "read-the-delta"),
        ("forbidden-path", "FORBIDDEN_PATH", "read-the-delta"),
        ("held-out-lesson", "HELD_OUT_LESSON", "read-the-delta"),
        ("chat-flag", "CHAT_FLAG", None),
        ("duplicate-lesson-id", "DUPLICATE_LESSON_ID", "read-the-delta"),
    ],
)
def test_lesson_check_reports_the_validation_rule(fixture, rule, lesson_id, kept, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    code, payload, _ = run_json("lesson", "check", PACKS / fixture, "--kept", kept)
    assert code == 2
    error = payload["error"]
    assert error["code"] == "LESSON_PACK_INVALID"
    diagnostics = error["details"]["errors"]
    assert diagnostics
    assert all(set(entry) == {"rule", "lesson_id", "path"} for entry in diagnostics)
    assert any((entry["rule"], entry["lesson_id"]) == (rule, lesson_id) for entry in diagnostics)


def test_lesson_check_also_accepts_a_pack_without_json_output(kept, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    code, stdout, _ = run_cli("lesson", "check", PACKS / "minimal", "--kept", kept)
    assert code == 0
    assert stdout.strip()


@pytest.mark.parametrize("path", ["comparisons[].paired_deltas", "comparisons[]"])
def test_discovery_and_check_refuse_paths_that_could_return_per_item_content(tmp_path, kept, path):
    pack = tmp_path / "pack"
    shutil.copytree(PACKS / "minimal", pack)
    content_file = pack / "lessons.json"
    content = json.loads(content_file.read_text(encoding="utf-8"))
    content["lessons"][0]["key_paths"] = [{"read": "figures", "path": path}]
    write_json(content_file, content)
    entry, = discover(pack)
    assert entry["reason"] == "CHECK_FAILED"
    assert set(entry) == {"id", "path", "valid", "reason"}
    code, payload, _ = run_json("lesson", "check", pack, "--kept", kept)
    assert code == 2
    assert payload["error"]["details"]["errors"][0]["rule"] == "FORBIDDEN_PATH"


def discover(*paths: Path):
    from hypotrail.lessons import discover

    return list(discover({ENV_VAR: os.pathsep.join(map(str, paths))} if paths else {}))


def test_discovery_uses_only_the_supplied_environment_and_keeps_its_order(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(PACKS / "minimal"))
    assert discover() == []
    other = tmp_path / "other"
    shutil.copytree(PACKS / "minimal", other)
    manifest = json.loads((other / "pack.json").read_text(encoding="utf-8"))
    write_json(other / "pack.json", {**manifest, "id": "other"})
    entries = discover(other, PACKS / "minimal")
    assert [row["id"] for row in entries] == ["other", "minimal"]
    assert all(row["valid"] is True for row in entries)


@pytest.mark.parametrize(
    ("fixture", "identifier", "reason"),
    [
        ("missing", None, "MANIFEST_MISSING"),
        ("schema", "minimal", "SCHEMA"),
        ("digit", "minimal", "CHECK_FAILED"),
        ("absent", None, "NOT_A_DIRECTORY"),
    ],
)
def test_discovery_reports_invalid_entries_without_content(tmp_path, fixture, identifier, reason):
    path = PACKS / fixture
    if fixture in ("missing", "absent"):
        path = tmp_path / fixture
        if fixture == "missing":
            path.mkdir()
    entries = discover(path)
    assert len(entries) == 1
    entry = entries[0]
    assert set(entry) == {"id", "path", "valid", "reason"}
    assert entry["id"] == identifier
    assert Path(entry["path"]) == path
    assert entry["valid"] is False
    assert entry["reason"] == reason


def test_discovery_marks_both_duplicate_pack_ids_invalid(tmp_path):
    first = PACKS / "minimal"
    second = tmp_path / "duplicate"
    shutil.copytree(first, second)
    entries = discover(first, second)
    assert len(entries) == 2
    for entry, path in zip(entries, (first, second), strict=True):
        assert set(entry) == {"id", "path", "valid", "reason"}
        assert entry["id"] == "minimal"
        assert Path(entry["path"]) == path
        assert entry["valid"] is False
        assert entry["reason"] == "DUPLICATE_PACK_ID"


@pytest.mark.parametrize(
    ("filename", "field", "value"),
    [
        ("pack.json", "id", "minimal\n"),
        ("pack.json", "version", "01.0.0"),
        ("pack.json", "licence", "MadeUpLicence"),
        ("lessons.json", "id", "read-the-delta\n"),
        ("lessons.json", "links", [{"title": "Guide", "url": "https://example.com:abc"}]),
    ],
)
def test_discovery_rejects_invalid_identifiers_and_formats(tmp_path, filename, field, value):
    pack = tmp_path / "pack"
    shutil.copytree(PACKS / "minimal", pack)
    source = pack / filename
    data = json.loads(source.read_text(encoding="utf-8"))
    record = data if filename == "pack.json" else data["lessons"][0]
    record[field] = value
    write_json(source, data)
    entry, = discover(pack)
    assert entry["reason"] == "SCHEMA"


def test_discovery_does_not_refuse_the_read_for_an_inaccessible_directory_name(tmp_path):
    entry, = discover(tmp_path / ("a" * 256))
    assert entry["reason"] == "NOT_A_DIRECTORY"


def test_the_loader_and_checker_do_not_follow_pack_or_kept_file_links(kept, tmp_path):
    pack = tmp_path / "pack"
    shutil.copytree(PACKS / "minimal", pack)
    content = pack / "lessons.json"
    content.rename(tmp_path / "external-lessons.json")
    content.symlink_to(tmp_path / "external-lessons.json")
    entry, = discover(pack)
    assert entry["reason"] == "SCHEMA"
    content.unlink()
    shutil.copyfile(tmp_path / "external-lessons.json", content)
    status = kept / "status-bike.out"
    status.rename(tmp_path / "external-status.out")
    status.symlink_to(tmp_path / "external-status.out")
    code, payload, _ = run_json("lesson", "check", pack, "--kept", kept)
    assert code == 2
    assert payload["error"]["details"]["errors"][0]["rule"] == "UNRESOLVED_PATH"


ILLUSTRATION = {
    "layout": "flow",
    "labels": ["Choose a baseline", "Test the alternative", "Review the difference"],
    "caption": "Compare the baseline and the alternative under the same Protocol.",
}


def illustrated_pack(tmp_path, illustration, *, schema_version="lesson-pack/2"):
    pack = tmp_path / "pack"
    shutil.copytree(PACKS / "minimal", pack)
    manifest_file = pack / "pack.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    write_json(manifest_file, {**manifest, "schema_version": schema_version})
    lessons_file = pack / "lessons.json"
    content = json.loads(lessons_file.read_text(encoding="utf-8"))
    if illustration is not None:
        content["lessons"][0]["illustration"] = illustration
    write_json(lessons_file, content)
    return pack


@pytest.mark.parametrize(
    "illustration",
    [
        None,
        ILLUSTRATION,
        {**ILLUSTRATION, "labels": ["Set a goal", "Get a baseline"]},
        {**ILLUSTRATION, "layout": "compare", "labels": ["Control", "Candidate"]},
        {**ILLUSTRATION, "labels": ["Frame", "Measure", "Evaluate", "Decide"]},
        {**ILLUSTRATION, "labels": ["a", "b" * 64], "caption": "c" * 240},
    ],
    ids=["omitted", "flow-three", "flow-two", "compare", "flow-four", "text-bounds"],
)
def test_lesson_pack_v2_accepts_plain_bounded_illustrations_and_serves_them_verbatim(
    tmp_path, kept, monkeypatch, illustration
):
    pack = illustrated_pack(tmp_path, illustration)
    code, _, stderr = run_json("lesson", "check", pack, "--kept", kept)
    assert code == 0, stderr

    monkeypatch.setenv(ENV_VAR, str(pack))
    code, payload, stderr = run_json("lesson", "--track", "temporal_regression")
    assert code == 0, stderr
    served, = payload["lessons"]
    if illustration is None:
        assert "illustration" not in served
    else:
        assert served["illustration"] == illustration
    assert served["source"] == "minimal@1.0.0"


def test_lesson_pack_v1_rejects_an_illustration(tmp_path, kept):
    pack = illustrated_pack(tmp_path, ILLUSTRATION, schema_version="lesson-pack/1")
    code, payload, _ = run_json("lesson", "check", pack, "--kept", kept)
    assert code == 2
    assert payload["error"]["code"] == "LESSON_PACK_INVALID"
    assert any(error["rule"] == "SCHEMA" for error in payload["error"]["details"]["errors"])


@pytest.mark.parametrize(
    "changes",
    [
        {"layout": "network"},
        {"labels": ["Frame"]},
        {"labels": ["Frame", "Measure", "Evaluate", "Decide", "Deliver"]},
        {"layout": "compare", "labels": ["Measure", "Evaluate", "Decide"]},
        {"labels": ["", "Measure"]},
        {"labels": ["a" * 65, "Measure"]},
        {"labels": ["Frame\nMeasure", "Decide"]},
        {"labels": ["Frame <b>carefully</b>", "Decide"]},
        {"labels": ["Step 1", "Measure"]},
        {"caption": ""},
        {"caption": "a" * 241},
        {"caption": "Compare the results.\nExplain the differences."},
        {"caption": "<img src='some-file'>"},
        {"caption": "Compare 2 alternatives."},
        {"url": "https://example.invalid/diagram.svg"},
    ],
    ids=[
        "unsupported-layout", "flow-too-short", "flow-too-long", "compare-arity",
        "empty-label", "long-label", "label-newline", "label-markup", "label-digit",
        "empty-caption", "long-caption", "caption-newline", "caption-markup",
        "caption-digit", "external-url-field",
    ],
)
def test_lesson_pack_v2_rejects_illustrations_outside_the_plain_shape(tmp_path, kept, changes):
    pack = illustrated_pack(tmp_path, {**ILLUSTRATION, **changes})
    code, payload, _ = run_json("lesson", "check", pack, "--kept", kept)
    assert code == 2
    assert payload["error"]["code"] == "LESSON_PACK_INVALID"
    assert any(
        error["lesson_id"] == "read-the-delta" and error["rule"] in {"SCHEMA", "DIGIT"}
        for error in payload["error"]["details"]["errors"]
    )
