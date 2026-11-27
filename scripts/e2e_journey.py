"""Manual journey checks. The launcher runs these inside the cloned product's test suite."""

import hashlib
import io
import json
import os
import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from _assess_helpers import construct, fresh_study
from _demonstration_helpers import Recorder, demonstration, study_of
from _study_helpers import ROOT, run_cli, run_json
from test_run_tool_end_to_end import the_tool

PACK_VARIABLE = "HYPOTRAIL_LESSON_PACKS"
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


def capture(study, track, with_pack, without_pack):
    """Pass only these development Study reads to the local panel harness."""
    status = state(study)
    assert status["pending_decisions"], "capture before the synthetic Decision"
    assert status["attempts"] and all(attempt["partition"] == "dev" for attempt in status["attempts"])
    if track == "bike":
        kept = ROOT / "clients/vscode/test/cli/demonstration/after-compare.status.out"
        attempts = json.loads(kept.read_bytes())["attempts"]
        assert {attempt["request_id"] for attempt in status["attempts"]} == {attempt["request_id"] for attempt in attempts}, (
            "the Bike proof must replay the kept development attempts"
        )
    observations = {attempt["observation_set_id"] for attempt in status["attempts"]}
    observations.discard(None)
    assert all(assessment["observation_set_id"] in observations for assessment in status["assessments"])
    assessment_ids = {assessment["assessment_id"] for assessment in status["assessments"]}
    for comparison in status["comparisons"]:
        roles = comparison["roles"]
        assert {roles["control_assessment_id"], roles["candidate_assessment_id"]} <= assessment_ids
    assert with_pack["write_sequence"] == without_pack["write_sequence"] == status["write_sequence"]
    figures = payload(run_json("figures", "--study", study))
    comparisons = {value["comparison_id"] for value in status["comparisons"]}
    assert all(value["comparison_id"] in comparisons for value in figures["comparisons"])
    data = {"status": status, "figures": figures, "with_pack": with_pack, "without_pack": without_pack}
    (read_files() / f"{track}-panel.json").write_text(json.dumps(data), encoding="utf-8")


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
    rejected = 0

    def scan(raw):
        nonlocal rejected
        rejected += WALL_WORDS.search(raw) is not None

    def read(current, marks):
        before, seq = snapshot(current), state(current)["write_sequence"]
        raw = raw_lesson("--study", current)
        obj = json.loads(raw)
        assert obj["write_sequence"] == state(current)["write_sequence"] == seq
        assert snapshot(current) == before
        assert_station_sequence(obj, marks)
        scan(raw)
        return raw, obj

    with monkeypatch.context() as isolated:
        isolated.chdir(tmp_path)
        before = sorted(tmp_path.iterdir())
        no_study = raw_lesson("--track", "temporal_regression")
        obj = json.loads(no_study)
        assert obj["track"] == "temporal_regression" and not obj["cards"]
        assert_station_sequence(obj, {})
        assert sorted(tmp_path.iterdir()) == before
        scan(no_study)

    # Prepare a synthetic public-check Attempt from a development-only donor.
    # It exists even when the replay has only initialized the Study.
    donor, attempts = fresh_study(tmp_path / "probe-donor", "seasonal_7")
    observation = construct(donor, attempts["seasonal_7"], lambda rows: rows, provenance={"partition": "public_check"})
    [public_attempt] = [
        row["attempt_id"] for row in state(donor)["attempts"]
        if row["observation_set_id"] == observation and row["partition"] == "public_check"
    ]
    fixture = donor / "attempts" / public_attempt

    work = tmp_path / "replay"
    study = work / "bike"
    # A5 uses a copy of the examples. Copy only the public Bike Workload.
    shutil.copytree(ROOT / "examples/bike_day", work / "demo-examples/bike_day")
    module = demonstration()
    [step] = [step for step in module.STEPS if step["id"] == "A5"]
    recorder = Recorder(module)
    marks = dict.fromkeys(("baseline", "iterate", "compare_decide"), False)
    replayed = []

    def paired_read():
        dev, lesson = read(study, marks)
        with TemporaryDirectory(dir=tmp_path) as scratch:
            copy = Path(scratch) / "study"
            # Use hard links for the study files. The read opens no protected payload.
            shutil.copytree(study, copy, copy_function=os.link)
            shutil.copytree(fixture, copy / "attempts" / public_attempt, copy_function=os.link)
            assert any(
                row["observation_set_id"] == observation and row["partition"] == "public_check"
                for row in state(copy)["attempts"]
            )
            with_public, _ = read(copy, marks)
            assert with_public.encode("utf-8") == dev.encode("utf-8"), (
                "the public-check fixture changed the lesson read"
            )
        return lesson

    def start(argv, env, cwd, text=None):
        prefix = recorder.prefix
        assert list(argv[:len(prefix)]) == prefix, "A5 must use only the CLI"
        args = argv[len(prefix):]
        assert study_of(args) == study
        command = args[0]
        assert command in {"init", "run", "assess", "compare", "status", "figures"}
        if command == "run":
            assert args[1] == "ml" and args[args.index("--partition") + 1] == "dev"
        code, stdout, stderr = recorder(argv, env, cwd, text)
        if code == 0 and command in {"init", "run", "assess", "compare"}:
            replayed.append(command)
            if command == "assess":
                marks["iterate" if marks["baseline"] else "baseline"] = True
            elif command == "compare":
                marks["compare_decide"] = True
            paired_read()
        return code, stdout, stderr

    outcome = module.run(work, start=start, out=io.StringIO(), steps=[step])
    assert outcome.code == 0, "the kept Bike development replay failed"
    assert replayed == ["init", "run", "run", "assess", "assess", "compare"]
    comparison = outcome.captures["L2_COMPARISON"]
    _, pending = read(study, marks)
    monkeypatch.delenv(PACK_VARIABLE)
    before, seq = snapshot(study), state(study)["write_sequence"]
    legacy = raw_lesson("--study", study)
    kept = ROOT / "clients/vscode/test/cli/lesson/after-compare.out"
    assert legacy.encode("utf-8") == kept.read_bytes(), "the legacy read changed from its pre-pack capture"
    assert snapshot(study) == before and state(study)["write_sequence"] == seq
    scan(legacy)
    if rejected == 0:
        capture(study, "bike", pending, json.loads(legacy))
    monkeypatch.setenv(PACK_VARIABLE, pack_path)

    # The old Task 3 command claims a human author. Use the fixture panel channel.
    answer = the_tool(work, {"words": "Synthetic words from the manual panel proof."}, panel_record=True)
    [record] = [call for call in answer["calls"] if call[0] == "decide"]
    assert "--channel=panel" in record and f"--artifact={comparison}" in record
    assert len(state(study)["decisions"]) == 1
    paired_read()
    (read_files() / "bike-wall-count.txt").write_text(f"{rejected}\n", encoding="utf-8")


def test_literal_wall():
    count = int((read_files() / "bike-wall-count.txt").read_text(encoding="utf-8"))
    assert count == 0, f"{count} Bike lesson reads contain a token rejected by C3"


def test_chinook_journey(tmp_path, monkeypatch):
    work = tmp_path / "campaign"
    study = work / "chinook-campaign"
    module = demonstration()
    [step] = [step for step in module.STEPS if step["id"] == "CAMPAIGN"]
    recorder = Recorder(module)
    captured = False

    def start(argv, env, cwd, text=None):
        nonlocal captured
        prefix = recorder.prefix
        if list(argv[:len(prefix)]) == prefix and "--request-id=demo-campaign-decide" in argv:
            assert not captured
            before, sequence = snapshot(study), state(study)["write_sequence"]
            packed = json.loads(raw_lesson("--study", study))
            assert packed["track"] == "tool_using_agent" and packed["cards"]
            assert packed["packs"] and packed["stations"] == packed["lessons"] == []
            with monkeypatch.context() as without_pack:
                without_pack.delenv(PACK_VARIABLE)
                plain = json.loads(raw_lesson("--study", study))
            assert snapshot(study) == before and state(study)["write_sequence"] == sequence
            capture(study, "chinook", packed, plain)
            captured = True
        return recorder(argv, env, cwd, text)

    outcome = module.run(work, start=start, out=io.StringIO(), steps=[step])
    assert outcome.code == 0 and captured, "expected the full kept development Campaign"
    before = snapshot(study)
    track_read = json.loads(raw_lesson("--track", "tool_using_agent"))
    assert track_read["track"] == "tool_using_agent"
    assert track_read["packs"] and track_read["stations"] == track_read["lessons"] == []
    assert snapshot(study) == before


def test_guide_pack_tool(tmp_path):
    instructions = (ROOT / "clients/vscode/hypotrail-guide.agent.md").read_text(encoding="utf-8")
    assert all(line in instructions.splitlines() for line in GUIDE_LINES)
    before = tuple(tmp_path.iterdir())
    cli = json.loads(raw_lesson("--track", "temporal_regression"))
    answer = the_tool(tmp_path, {"track": "temporal_regression"}, tool="hypotrail_read_study")
    assert answer["calls"] == [["lesson", "--track=temporal_regression", "--json"]]
    _, notice, text = answer["text"].partition("\n")
    assert notice
    pack = json.loads(text)
    assert pack == cli
    assert {"framing", "data", "compare_decide"} <= {item["station"] for item in pack["lessons"]}
    [wall] = [station for station in pack["stations"] if station["id"] == "held_out"]
    assert wall["chat"] is False
    assert not any(item["station"] == "held_out" for item in pack["lessons"])
    assert tuple(tmp_path.iterdir()) == before
