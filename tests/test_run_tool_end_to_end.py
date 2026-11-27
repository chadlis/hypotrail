"""The run tool's corpus on the real CLI (chadlis/hypotrail#285, its end-to-end test under D-170 on chadlis/hypotrail#75).

Each case of the corpus is given to the real tool, `hypotrail_run`, compiled in `clients/vscode/out/` and called as Copilot calls it by
`clients/vscode/test/run-tool-e2e.ts`, with Node, on the `vscode` stub and with the real `execFile`. The tool builds the arguments, refuses or starts the real CLI through
its bridge, from the checkout root, without the live key. The Studies are the demonstration's first Bike Study (`init`, `seasonal_7` and
`ridge_v1` on dev, their two Assessments and their Comparison, as its steps L1.2 to L1.5 make them) and a copy of it to which a person,
through the CLI, added `seasonal_7` on public_check and its Assessment. For an allowed case, the one command started is the argument list
the corpus gives and the CLI answers as the corpus says; for a refused case, the tool gives the corpus's code, starts nothing but the read
of the Study, and the Study's bytes and Write sequence are the same before and after. It needs Node and the compiled client
(`npm ci && npm run compile` in `clients/vscode`), and fails when either is missing.
"""

import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _report_helpers import constructed_attempt, edit_manifest, tree
from _study_helpers import init_study, run_json, run_ml

from hypotrail.core import artifacts, lock

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "clients" / "vscode" / "test" / "run-tool-corpus" / "cases.jsonl"
CLIENT = ROOT / "clients" / "vscode"
HARNESS = CLIENT / "out" / "test" / "run-tool-e2e.js"
LIVE_KEY = "HYPOTRAIL_ANTHROPIC_API_KEY"


def cli(*args) -> tuple:
    """(exit code, the JSON object printed) of one CLI process, started as the bridge starts it but with this test's Python."""
    env = {key: value for key, value in os.environ.items() if key != LIVE_KEY}
    done = subprocess.run([sys.executable, "-B", "-m", "hypotrail", *map(str, args)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    return done.returncode, json.loads(done.stdout)


def ok(*args) -> dict:
    code, payload = cli(*args)
    assert code == 0 and payload["ok"] is True, payload
    return payload


def status(study) -> dict:
    return ok("status", f"--study={study}", "--json")


def study_bytes(study: Path) -> dict:
    return {str(path.relative_to(study)): path.read_bytes() for path in sorted(study.rglob("*")) if path.is_file()}


def demonstration_bike_study(tmp_path: Path) -> tuple:
    """The Study of the demonstration's steps L1.2 to L1.5, and the ids the corpus's placeholders name."""
    study = tmp_path / "l1-bike"
    refs = ok("init", "--workload", "bike_day", "--study", study, "--json")["references_id"]
    obs = {config: ok("run", "ml", "--study", study, "--config", config, "--partition", "dev", "--request-id", f"l1-{config}", "--json")["observation_set_id"] for config in ("seasonal_7", "ridge_v1")}
    assessed = {config: ok("assess", "--study", study, "--observations", obs[config], "--scorer", "regression_mae_v1", "--references", refs, "--json")["assessment"]["assessment_id"] for config in obs}
    ok("compare", "--study", study, "--control", assessed["seasonal_7"], "--candidate", assessed["ridge_v1"], "--json")
    return study, {"REFS": refs, "OBS_SEASONAL": obs["seasonal_7"], "OBS_RIDGE": obs["ridge_v1"], "A_SEASONAL": assessed["seasonal_7"], "A_RIDGE": assessed["ridge_v1"]}


def public_check_copy(study: Path, ids: dict, tmp_path: Path) -> tuple:
    """A copy of the Study to which a person adds `seasonal_7` on public_check and its Assessment, through the CLI."""
    copy = tmp_path / "l1-bike-public"
    shutil.copytree(study, copy)
    observations = ok("run", "ml", "--study", copy, "--config", "seasonal_7", "--partition", "public_check", "--request-id", "person-public", "--json")["observation_set_id"]
    assessment = ok("assess", "--study", copy, "--observations", observations, "--scorer", "regression_mae_v1", "--references", ids["REFS"], "--json")["assessment"]["assessment_id"]
    return copy, {"OBS_PUBLIC": observations, "OBS_PUBLIC_UPPER": observations.upper(), "A_PUBLIC": assessment}


def filled(value, values: dict):
    if isinstance(value, str):
        if value == "{READ_SEQUENCE}":
            return values["READ_SEQUENCE"]
        for name, each in values.items():
            value = value.replace("{" + name + "}", str(each))
        return value
    if isinstance(value, list):
        return [filled(each, values) for each in value]
    if isinstance(value, dict):
        return {key: filled(each, values) for key, each in value.items()}
    return value


def the_tool(folder: Path, given: dict) -> dict:
    """What the run tool gave back for `given` (`text`) and the argument list of each process it started (`calls`), from the harness."""
    node = shutil.which("node")
    if node is None or not HARNESS.is_file():
        pytest.fail(f"the run tool's end-to-end test needs Node and the compiled client: run `npm ci && npm run compile` in {CLIENT} (node: {node})")
    env = {key: value for key, value in os.environ.items() if key != LIVE_KEY}
    done = subprocess.run(
        [node, str(HARNESS)], input=json.dumps({"folder": str(folder), "input": given}), cwd=CLIENT, env=env,
        capture_output=True, text=True, timeout=300,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def after(text: str, marker: str) -> dict:
    return json.loads(text.split(marker, 1)[1])


def written_id(command: str, payload: dict):
    """The id of the record an allowed command wrote, by its command, or None for a command that writes no record of a listing."""
    return {"run": lambda: payload["attempt"]["attempt_id"], "assess": lambda: payload["assessment"]["assessment_id"], "compare": lambda: payload["comparison"]["comparison_id"]}.get(command, lambda: None)()


def test_the_run_tool_corpus_on_the_real_cli(tmp_path):
    cases = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line]
    folder = (tmp_path / "workspace").resolve()
    folder.mkdir()
    dev, ids = demonstration_bike_study(folder)
    public, public_ids = public_check_copy(dev, ids, folder)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    studies = {"dev": dev, "public_check": public}
    values = {**ids, **public_ids, "OUT_DIR": out_dir}
    assert {each["input"]["command"] for each in cases if each["expected"] == "allowed"} == {"run", "assess", "compare", "profile", "report"}
    assert len([each for each in cases if each["expected"] != "allowed"]) >= 80

    for each in cases:
        study = studies[each["state"]]
        before, sequence = study_bytes(study), status(study)["write_sequence"]
        here = {**values, "STUDY": study, "READ_SEQUENCE": sequence}
        answer = the_tool(folder, filled(each["input"], here))
        text = answer["text"]
        read = ["status", f"--study={study}", "--json"]
        commands = [call for call in answer["calls"] if call != read]
        if each["expected"] != "allowed":
            assert status(study)["write_sequence"] == sequence, each["id"]
            assert study_bytes(study) == before, each["id"]
            assert commands == [], (each["id"], commands)
            assert text.startswith(f"Refused ({each['expected']}):"), (each["id"], text)
            continue
        assert commands == [filled(each["argv"], here)], (each["id"], commands)
        command = commands[0][0]
        if each["cli"] != "ok":
            assert text.startswith("The CLI refused"), (each["id"], text)
            assert after(text, "Its error, as printed:\n")["code"] == each["cli"], (each["id"], text)
            continue
        assert text.startswith("The CLI ran"), (each["id"], text)
        payload = after(text, "It printed:\n")
        shown = status(study)
        listed = {"run": [a["attempt_id"] for a in shown["attempts"]], "assess": [a["assessment_id"] for a in shown["assessments"]], "compare": [c["comparison_id"] for c in shown["comparisons"]]}
        record = written_id(command, payload)
        if record is not None:
            assert record in listed[command], each["id"]
        if command == "profile":
            assert shown["write_sequence"] == sequence, each["id"]
        if command == "report":
            assert Path(payload["report"]["out"]).is_file(), each["id"]

    # The read the tool makes before assess, compare and report gives the Partition it refuses on, in each Study.
    public_status, dev_status = status(public), status(dev)
    on_public = [a for a in public_status["attempts"] if a["partition"] == "public_check"]
    assert [a["observation_set_id"] for a in on_public] == [public_ids["OBS_PUBLIC"]]
    assert {a["assessment_id"]: a["observation_set_id"] for a in public_status["assessments"]}[public_ids["A_PUBLIC"]] == public_ids["OBS_PUBLIC"]
    assert [a["partition"] for a in dev_status["attempts"] if a["partition"] != "dev"] == []


@pytest.mark.parametrize("state", ["changed after status", "manifest only", "writer active"])
def test_guarded_report_refuses_before_opening_artifacts(tmp_path, monkeypatch, state):
    study, _ = init_study(tmp_path)
    stale = run_json("status", "--study", study)[1]["write_sequence"]
    if state == "changed after status":
        code, _, err = run_ml(study, "seasonal_7", "public_check", "later-attempt")
        assert code == 0, err
    if state == "manifest only":
        attempt = constructed_attempt(study, "interrupted", outcome_unknown=True)
        edit_manifest(study, attempt, lambda record: record["effective_config"].update(partition="public_check"))
        assert run_json("status", "--study", study)[1]["attempts"][0]["partition"] is None

    out = tmp_path / "report.html"
    args = ("report", "--study", study, "--out", out, "--read-sequence", str(stale))
    monkeypatch.setenv("HYPOTRAIL_RUN_TOOL", "1")
    # The guard may read Study records. It must refuse before gathering payload artifacts.
    monkeypatch.setattr(artifacts, "read_verified", lambda *_: pytest.fail("guarded report opened an artifact"))
    with lock.writer_lock(study) if state == "writer active" else contextlib.nullcontext():
        before = tree(study)
        code, payload, _ = run_json(*args)
        assert tree(study) == before
    expected = {"changed after status": (6, "STUDY_CHANGED"), "manifest only": (2, "PUBLIC_CHECK_REFUSED"), "writer active": (6, "STUDY_LOCKED")}
    assert (code, payload["error"]["code"]) == expected[state]
    assert not out.exists()


def test_the_run_tool_guards_the_real_report_when_status_has_no_partition(tmp_path):
    study, _ = init_study(tmp_path)
    attempt = constructed_attempt(study, "interrupted", outcome_unknown=True)
    edit_manifest(study, attempt, lambda record: record["effective_config"].update(partition="public_check"))
    current = status(study)
    assert current["attempts"][0]["partition"] is None
    before = tree(study)
    out = tmp_path / "report.html"
    answer = the_tool(tmp_path, {
        "study": str(study),
        "command": "report",
        "arguments": [f"--out={out}"],
        "read_sequence": current["write_sequence"],
    })
    assert after(answer["text"], "Its error, as printed:\n")["code"] == "PUBLIC_CHECK_REFUSED"
    assert not out.exists()
    assert tree(study) == before


@pytest.mark.parametrize("command", ["assess", "compare"])
def test_guarded_commands_refuse_protected_inputs_before_reading_payloads(tmp_path, monkeypatch, command):
    study, initial = init_study(tmp_path)
    code, attempt, err = run_ml(study, "seasonal_7", "public_check", "public-attempt")
    assert code == 0, err
    assess_args = ("--observations", attempt["observation_set_id"], "--scorer", "regression_mae_v1", "--references", initial["references_id"])
    code, assessed, err = run_json("assess", "--study", study, *assess_args)
    assert code == 0, err
    assessment_id = assessed["assessment"]["assessment_id"]
    args = assess_args if command == "assess" else ("--control", assessment_id, "--candidate", assessment_id)
    sequence = run_json("status", "--study", study)[1]["write_sequence"]
    before = tree(study)
    read_verified = artifacts.read_verified

    def records_only(folder, ref):
        if ref["role"] != "observation_set":
            pytest.fail("guarded command opened a protected payload")
        return read_verified(folder, ref)

    monkeypatch.setenv("HYPOTRAIL_RUN_TOOL", "1")
    monkeypatch.setattr(artifacts, "read_verified", records_only)
    code, payload, _ = run_json(command, "--study", study, "--read-sequence", sequence, *args)
    assert (code, payload["error"]["code"]) == (2, "PUBLIC_CHECK_REFUSED")
    assert tree(study) == before
