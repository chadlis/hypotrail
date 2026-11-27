"""Manual journey checks. The launcher runs these inside the cloned product's test suite."""

import hashlib
import io
import json
import os
import re
import shutil
from pathlib import Path

from _assess_helpers import assess, construct
from _compare_helpers import compare
from _demonstration_helpers import Recorder, demonstration
from _import_helpers import FIELDS, import_ml, ready, rows_of, write_rows
from _study_helpers import ROOT, init_study, run_cli, run_json
from hypotrail.ml import lesson as bike_cards
from test_run_tool_end_to_end import the_tool

PACK_VARIABLE = "HYPOTRAIL_LESSON_PACKS"
PACK_KEYS = ("packs", "stations", "lessons")
STATIONS = ("intake", "framing", "data", "baseline", "iterate", "compare_decide", "held_out", "deliver")
WALL_WORDS = re.compile(r"reference|per_item|public_check", re.IGNORECASE)
GUIDE_LINES = (
    "Quote a pack lesson verbatim and name its source.",
    "Name the station the person names; if they name none, ask which station they are at.",
    "Ask at most the lesson's question.",
    "At the held-out station, say only that the held-out pass runs at the evaluator and that you cannot discuss it.",
    "Before the person opens a Comparison's figures, you may ask what they expect; record nothing.",
)


def payload(result):
    code, obj, _ = result
    assert code == 0 and obj["ok"], "expected a successful CLI command"
    return obj


def raw_lesson(*args):
    code, stdout, stderr = run_cli("lesson", *args, "--json")
    assert code == 0 and not stderr, "expected a successful lesson read"
    return stdout


def state(study):
    return payload(run_json("status", "--study", study))


def read_files():
    return Path(os.environ["HYPOTRAIL_E2E_READS"])


def capture(study, prefix, with_pack):
    """Pass only these development Study reads to the local panel harness."""
    data = {name: payload(run_json(name, "--study", study)) for name in ("status", "figures")}
    data["without_pack"] = json.loads(raw_lesson("--study", study))
    data["with_pack"] = with_pack
    (read_files() / f"{prefix}-panel.json").write_text(json.dumps(data), encoding="utf-8")


def snapshot(study):
    """Fingerprint local records without opening the payload of any Reference or membership."""
    files = {}
    for path in sorted(study.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(study)
        if relative.parts[0] in {"artifacts", "memberships", "references"}:
            info = path.stat()
            files[relative] = info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino
        else:
            files[relative] = hashlib.sha256(path.read_bytes()).digest()
    return files


def assert_station_sequence(lesson, marks):
    assert tuple(station["id"] for station in lesson["stations"]) == STATIONS
    assert [station["has_records"] for station in lesson["stations"]] == [
        marks.get(station) for station in STATIONS
    ]
    assert len(lesson["lessons"]) == 28
    assert not any(item["station"] == "held_out" for item in lesson["lessons"])


def test_bike_journey(tmp_path, monkeypatch):
    pack_path = os.environ[PACK_VARIABLE]
    study, initial = init_study(tmp_path)
    seen = []

    def read(current, marks):
        before, seq = snapshot(current), state(current)["write_sequence"]
        raw = raw_lesson("--study", current)
        obj = json.loads(raw)
        assert obj["write_sequence"] == state(current)["write_sequence"] == seq
        assert snapshot(current) == before
        assert_station_sequence(obj, marks)
        seen.append(raw)
        return obj

    with monkeypatch.context() as isolated:
        isolated.chdir(tmp_path)
        before = sorted(tmp_path.iterdir())
        no_study = raw_lesson("--track", "temporal_regression")
        obj = json.loads(no_study)
        assert obj["track"] == "temporal_regression" and not obj["cards"]
        assert_station_sequence(obj, {})
        assert sorted(tmp_path.iterdir()) == before
        seen.append(no_study)

    marks = dict.fromkeys(("baseline", "iterate", "compare_decide"), False)
    read(study, marks)

    # The Import is the documented development-only exporter; a deterministic
    # shift creates a second Configuration's synthetic forecasts for comparison.
    source, mapping, population, _digest = ready(tmp_path)
    shifted = []
    for row in rows_of(source):
        shifted.append({
            **row,
            "forecast_rentals": str(int(row["forecast_rentals"]) + 100),
            "forecast_unrounded": str(float(row["forecast_unrounded"]) + 100),
        })
    candidate = write_rows(tmp_path / "candidate.csv", shifted, FIELDS)
    observations = []
    for name, file in (("control", source), ("candidate", candidate)):
        observations.append(payload(import_ml(study, file, mapping, population, name)))
        read(study, marks)

    assessments = []
    for attempt, mark in zip(observations, ("baseline", "iterate"), strict=True):
        assessed = payload(assess(study, attempt["observation_set_id"], "regression_mae_v1", initial["references_id"]))
        assessments.append(assessed["assessment"]["assessment_id"])
        marks[mark] = True
        read(study, marks)
        if mark == "baseline":
            # Construct only a synthetic Attempt from a development artifact.
            # No actual public-check prediction or protected labels are read.
            copy = tmp_path / "study-public-fixture"
            shutil.copytree(study, copy)
            dev = read(study, marks)
            synthetic = construct(copy, observations[0]["attempt"], lambda rows: rows, provenance={"partition": "public_check"})
            assert any(
                row["observation_set_id"] == synthetic and row["partition"] == "public_check"
                for row in state(copy)["attempts"]
            )
            with_public = read(copy, marks)
            assert json.dumps({key: with_public[key] for key in PACK_KEYS}) == json.dumps({key: dev[key] for key in PACK_KEYS})

    comparison = payload(compare(study, *assessments))["comparison"]["comparison_id"]
    marks["compare_decide"] = True
    pending = read(study, marks)
    monkeypatch.delenv(PACK_VARIABLE)
    before, seq = snapshot(study), state(study)["write_sequence"]
    # Compare strict bytes with the original serializer over this Study's
    # dynamic identifiers. The kept-read test separately verifies normalization.
    legacy = raw_lesson("--study", study)
    assert legacy == json.dumps({"ok": True, **bike_cards.lesson(study)}, indent=2) + "\n"
    assert snapshot(study) == before and state(study)["write_sequence"] == seq
    seen.append(legacy)
    capture(study, "bike", pending)
    monkeypatch.setenv(PACK_VARIABLE, pack_path)

    answer = the_tool(tmp_path, {"words": "Synthetic words from the manual panel proof."}, panel_record=True)
    [record] = [call for call in answer["calls"] if call[0] == "decide"]
    assert "--channel=panel" in record and f"--artifact={comparison}" in record
    assert len(state(study)["decisions"]) == 1
    read(study, marks)
    (read_files() / "bike-lessons.json").write_text(json.dumps(seen), encoding="utf-8")


def test_literal_wall():
    reads = json.loads((read_files() / "bike-lessons.json").read_text(encoding="utf-8"))
    count = sum(WALL_WORDS.search(raw) is not None for raw in reads)
    assert count == 0, f"{count} Bike lesson reads contain a token rejected by C3"


def test_chinook_journey(tmp_path, monkeypatch):
    pack = os.environ[PACK_VARIABLE]
    work = tmp_path / "campaign"
    module = demonstration()
    [step] = [step for step in module.STEPS if step["id"] == "CAMPAIGN"]
    recorder = Recorder(module)
    outcome = module.run(work, start=recorder, out=io.StringIO(), steps=[step])
    assert outcome.code == 0, "expected the kept development Campaign to run"
    study = work / "chinook-campaign"
    before = snapshot(study)
    without = json.loads(raw_lesson("--track", "tool_using_agent"))
    assert without["track"] == "tool_using_agent"
    assert without["packs"] and without["stations"] == without["lessons"] == []
    content = json.loads(raw_lesson("--study", study))
    assert content["track"] == "tool_using_agent" and content["cards"]
    assert content["packs"] and content["stations"] == content["lessons"] == []
    monkeypatch.delenv(PACK_VARIABLE)
    capture(study, "chinook", content)
    assert snapshot(study) == before
    monkeypatch.setenv(PACK_VARIABLE, pack)


def scripted_turn(station, read_pack):
    """One transparent, model-free caller of the Guide's real read tool."""
    if station == "held_out":
        return "The held-out pass runs at the evaluator, and I cannot discuss it."
    lesson = next(item for item in read_pack()["lessons"] if item["station"] == station)
    return f'{lesson["why_this_step"]}\nSource: {lesson["source"]}'


def test_scripted_guide(tmp_path):
    instructions = (ROOT / "clients/vscode/hypotrail-guide.agent.md").read_text(encoding="utf-8")
    assert all(line in instructions.splitlines() for line in GUIDE_LINES)
    before = tuple(tmp_path.iterdir())
    cli = json.loads(raw_lesson("--track", "temporal_regression"))
    for station in ("framing", "data", "compare_decide", "held_out"):
        calls = []

        def read_pack():
            answer = the_tool(tmp_path, {"track": "temporal_regression"}, tool="hypotrail_read_study")
            calls.extend(answer["calls"])
            _, notice, text = answer["text"].partition("\n")
            assert notice
            return json.loads(text)

        reply = scripted_turn(station, read_pack)
        if station == "held_out":
            assert reply == "The held-out pass runs at the evaluator, and I cannot discuss it."
            assert calls == []
        else:
            assert calls == [["lesson", "--track=temporal_regression", "--json"]]
            expected = next(item for item in cli["lessons"] if item["station"] == station)
            assert reply.splitlines() == [expected["why_this_step"], f'Source: {expected["source"]}']
        assert not any("public_check" in argument for call in calls for argument in call)
    assert tuple(tmp_path.iterdir()) == before
