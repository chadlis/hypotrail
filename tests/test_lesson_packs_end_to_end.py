"""The CLI's pack lesson contract on synthetic inputs and a Bike dev Study."""

import json
import os

import pytest
from _compare_helpers import assessed, compare
from _study_helpers import ROOT, run_cli, run_json

from hypotrail.ml import lesson as bike_cards

PACKS = ROOT / "tests" / "fixtures" / "lesson_packs"
FIXTURE = PACKS / "minimal"
PACK_VARIABLE = "HYPOTRAIL_LESSON_PACKS"
BIKE_TRACK = "temporal_regression"
AGENT_TRACK = "tool_using_agent"
PACK_KEYS = ("id", "version", "title", "language", "licence")


def pack_files(directory):
    return tuple(
        json.loads((directory / name).read_text(encoding="utf-8"))
        for name in ("pack.json", "lessons.json")
    )


def metadata(manifest):
    return {**{key: manifest[key] for key in PACK_KEYS}, "valid": True, "reason": None}


def expected_lessons(manifest, content, track):
    source = f"{manifest['id']}@{manifest['version']}"
    return [{**row, "source": source} for row in content["lessons"] if row["track"] == track]


def copy_pack(tmp_path, name, tracks):
    directory = tmp_path / name
    directory.mkdir()
    manifest, content = pack_files(FIXTURE)
    manifest.update(id=name, tracks=tracks, title=f"Teaching pack {name}")
    content["lessons"] = [
        {**content["lessons"][0], "track": track, "id": f"{name}-{track.replace('_', '-')}"}
        for track in tracks
    ]
    (directory / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    (directory / "lessons.json").write_text(json.dumps(content), encoding="utf-8")
    return directory, manifest, content


def test_bike_with_and_without_the_fixture_pack_and_without_a_study(tmp_path, monkeypatch):
    monkeypatch.delenv(PACK_VARIABLE, raising=False)
    study, _, reports = assessed(tmp_path, "seasonal_7", "ridge_v1")
    code, _, err = compare(
        study, reports["seasonal_7"]["assessment_id"], reports["ridge_v1"]["assessment_id"]
    )
    assert code == 0, err
    arguments = ("lesson", f"--study={study}")
    expected = {"ok": True, **bike_cards.lesson(study)}
    legacy_json = json.dumps(expected, indent=2) + "\n"
    assert run_cli(*arguments, "--json") == (0, legacy_json, "")
    monkeypatch.setenv(PACK_VARIABLE, "")
    assert run_cli(*arguments, "--json") == (0, legacy_json, "")

    monkeypatch.setenv(PACK_VARIABLE, str(FIXTURE))
    manifest, content = pack_files(FIXTURE)
    code, read, err = run_json(*arguments)
    assert code == 0, err
    marks = {"baseline": True, "iterate": True, "compare_decide": True}
    assert read == {
        **expected,
        "packs": [metadata(manifest)],
        "stations": [{**row, "has_records": marks.get(row["id"])} for row in manifest["stations"]],
        "lessons": expected_lessons(manifest, content, BIKE_TRACK),
    }
    assert bike_cards.lesson(study)["write_sequence"] == expected["write_sequence"]

    without_study = tmp_path / "no-study"
    without_study.mkdir()
    monkeypatch.chdir(without_study)
    code, read, err = run_json("lesson", f"--track={BIKE_TRACK}")
    assert code == 0, err
    assert read == {
        "ok": True,
        "track": BIKE_TRACK,
        "cards": [],
        "packs": [metadata(manifest)],
        "stations": [{**row, "has_records": None} for row in manifest["stations"]],
        "lessons": expected_lessons(manifest, content, BIKE_TRACK),
    }
    assert list(without_study.iterdir()) == []


@pytest.mark.parametrize("track", [BIKE_TRACK, AGENT_TRACK])
def test_no_study_and_no_packs_yields_empty_collections(track, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PACK_VARIABLE, raising=False)
    code, read, err = run_json("lesson", "--track", track)
    assert code == 0, err
    assert read == {"ok": True, "track": track, "cards": [], "packs": [], "stations": [], "lessons": []}


def test_first_valid_pack_for_requested_track_supplies_verbatim_content(tmp_path, monkeypatch):
    missing = tmp_path / "unavailable"
    other, other_manifest, _ = copy_pack(tmp_path, "other", [AGENT_TRACK])
    chosen, manifest, content = copy_pack(tmp_path, "chosen", [BIKE_TRACK, AGENT_TRACK])
    later, later_manifest, _ = copy_pack(tmp_path, "later", [BIKE_TRACK])
    monkeypatch.setenv(PACK_VARIABLE, os.pathsep.join(map(str, [missing, other, chosen, later])))
    code, read, err = run_json("lesson", "--track", BIKE_TRACK)
    assert code == 0, err
    first, *valid = read["packs"]
    assert set(first) == {*PACK_KEYS, "valid", "reason"}
    assert (first["id"], first["valid"], first["reason"]) == (None, False, "NOT_A_DIRECTORY")
    assert valid == [metadata(other_manifest), metadata(manifest), metadata(later_manifest)]
    assert read["stations"] == [{**row, "has_records": None} for row in manifest["stations"]]
    assert read["lessons"] == expected_lessons(manifest, content, BIKE_TRACK)


def test_a_study_with_only_invalid_pack_entries_still_receives_all_pack_keys(tmp_path, monkeypatch):
    monkeypatch.setenv(PACK_VARIABLE, str(tmp_path / "absent"))
    study, _, _ = assessed(tmp_path)
    code, read, err = run_json("lesson", "--study", study)
    assert code == 0, err
    entry, = read["packs"]
    assert (entry["valid"], entry["reason"]) == (False, "NOT_A_DIRECTORY")
    assert read["stations"] == read["lessons"] == []
