"""The run tool's corpus on the real CLI (chadlis/hypotrail#285, its end-to-end test under D-170 on chadlis/hypotrail#75).

`clients/vscode/test/tools-run.test.ts` shows, with the process stubbed, that the tool builds each allowed case's argument list as the corpus
gives it and starts no command for a refused case. This test runs those argument lists through the real CLI, as separate processes started
from the checkout root without the live key, on the demonstration's first Bike Study: `init`, `seasonal_7` and `ridge_v1` on dev, their two
Assessments and their Comparison, as its steps L1.2 to L1.5 make them. A second Study is a copy of it to which a person, through the CLI,
added `seasonal_7` on public_check and its Assessment.

Stated limit: the tool itself runs in Node, which this job does not have; for a refused case this test checks the one process the tool may
start, the read of the Study, and that the read gives the Partition the tool refuses on.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from _study_helpers import run_cli

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "clients" / "vscode" / "test" / "run-tool-corpus" / "cases.jsonl"
CONTRACT = json.loads((ROOT / "clients" / "vscode" / "contract.json").read_text(encoding="utf-8"))
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
        for name, each in values.items():
            value = value.replace("{" + name + "}", str(each))
        return value
    return [filled(each, values) for each in value]


def written_id(args: list, payload: dict):
    """The id of the record an allowed command wrote, by its command, or None for a command that writes no record of a listing."""
    return {"run": lambda: payload["attempt"]["attempt_id"], "assess": lambda: payload["assessment"]["assessment_id"], "compare": lambda: payload["comparison"]["comparison_id"]}.get(args[0], lambda: None)()


def test_the_run_tool_corpus_on_the_real_cli(tmp_path):
    cases = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line]
    dev, ids = demonstration_bike_study(tmp_path)
    public, public_ids = public_check_copy(dev, ids, tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    studies = {"dev": dev, "public_check": public}
    values = {**ids, **public_ids, "OUT_DIR": out_dir}

    allowed = [each for each in cases if each["expected"] == "allowed"]
    assert {each["input"]["command"] for each in allowed} == {"run", "assess", "compare", "profile", "report"}
    for each in allowed:
        study = studies[each["state"]]
        before = status(study)
        args = filled(each["argv"], {**values, "STUDY": study, "READ_SEQUENCE": before["write_sequence"]})
        assert args[0] == each["input"]["command"], each["id"]
        code, payload = cli(*args)
        if each["cli"] == "ok":
            assert code == 0 and payload["ok"] is True, (each["id"], payload)
            after = status(study)
            record = written_id(args, payload)
            listed = {"run": [a["attempt_id"] for a in after["attempts"]], "assess": [a["assessment_id"] for a in after["assessments"]], "compare": [c["comparison_id"] for c in after["comparisons"]]}
            if record is not None:
                assert record in listed[args[0]], each["id"]
            if args[0] == "profile":
                assert after["write_sequence"] == before["write_sequence"], each["id"]
            if args[0] == "report":
                assert Path(args[[a.startswith("--out=") for a in args].index(True)][len("--out="):]).is_file(), each["id"]
        else:
            assert code != 0 and payload["error"]["code"] == each["cli"], (each["id"], payload)

    # The read the tool makes before assess, compare and report gives the Partition it refuses on, in each Study.
    public_status, dev_status = status(public), status(dev)
    on_public = [a for a in public_status["attempts"] if a["partition"] == "public_check"]
    assert [a["observation_set_id"] for a in on_public] == [public_ids["OBS_PUBLIC"]]
    assert {a["assessment_id"]: a["observation_set_id"] for a in public_status["assessments"]}[public_ids["A_PUBLIC"]] == public_ids["OBS_PUBLIC"]
    assert [a["partition"] for a in dev_status["attempts"] if a["partition"] != "dev"] == []

    refused = [each for each in cases if each["expected"] != "allowed"]
    assert len(refused) >= 80 and all("argv" not in each for each in refused)
    read = [argument for argument in CONTRACT["read_arguments"] if "{n}" not in argument]
    status_sequences = {state: status(study)["write_sequence"] for state, study in studies.items()}
    for each in refused:  # in process: the CLI's own entry point, which each process above starts
        study = studies[each["state"]]
        before = study_bytes(study)
        code, payload, err = run_cli(*[argument.replace("{path}", str(study)) for argument in read])
        assert code == 0 and json.loads(payload)["write_sequence"] == status_sequences[each["state"]], (each["id"], err)
        assert study_bytes(study) == before, each["id"]
