"""Shared by the client checks: the CLI output that `clients/vscode/test/cli/` keeps, made again offline on a scratch Study.

Each output is kept as three files, `NAME.exit`, `NAME.out` and `NAME.err`, with each UUID replaced by `UUID` and the scratch Study's
folder by `SCRATCH`, so that a second making compares equal. `status-not-found` names no scratch folder and is kept as printed.
"""

import re
from pathlib import Path

from _compare_helpers import assessed, compare
from _study_helpers import run_cli

ROOT = Path(__file__).resolve().parent.parent
KEPT = ROOT / "clients" / "vscode" / "test" / "cli"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def normalized(text: str, study) -> str:
    return UUID.sub("UUID", text.replace(str(study), "SCRATCH"))


def compared_study(tmp_path):
    """A Study of the Bike Workload at write sequence 12: two Attempts on dev, their two Assessments and one Comparison."""
    study, _, assessments = assessed(tmp_path, "seasonal_7", "ridge_v1")
    code, payload, err = compare(study, assessments["seasonal_7"]["assessment_id"], assessments["ridge_v1"]["assessment_id"])
    assert code == 0, (payload, err)
    return study


def status_outputs(tmp_path) -> dict:
    """{name: (exit code, stdout, stderr)} of the two reads the client tests keep."""
    study = compared_study(tmp_path)
    code, out, err = run_cli("status", "--study", study, "--json")
    return {
        "status-success": (code, normalized(out, study), normalized(err, study)),
        "status-not-found": run_cli("status", "--study=/nonexistent-x", "--json"),
    }


QUESTION = "Which Configuration do we keep after this Comparison?"


def decide(study, option, request_id, read_sequence, *cited):
    """`decide` as the bridge starts it: each option joined to its value by `=`."""
    args = ["decide", f"--study={study}", f"--question={QUESTION}", f"--option={option}", "--author=human"]
    args += [f"--artifact={i}" for i in cited] + [f"--request-id={request_id}", f"--read-sequence={read_sequence}", "--json"]
    return run_cli(*args)


def decide_outputs(tmp_path) -> dict:
    """{name: (exit code, stdout, stderr)} of the writes the client tests keep: a success, its replay, a changed Study and four other refusals."""
    study = compared_study(tmp_path)
    [comparison] = [p.name for p in (Path(study) / "comparisons").iterdir()]
    made = {
        "decide-success": decide(study, "Keep the Control", "panel-1", 12, comparison),
        "decide-replay": decide(study, "Keep the Control", "panel-1", 12, comparison),
        "decide-study-changed": decide(study, "Keep the Candidate", "panel-2", 12, comparison),
        "decide-write-sequence-ahead": decide(study, "Keep the Candidate", "panel-3", 99, comparison),
        "decide-request-conflict": decide(study, "Keep the Candidate", "panel-1", 14, comparison),
        "decide-invalid-arguments": run_cli("decide", f"--study={study}", "--json"),
    }
    made["decide-study-not-found"] = decide("/nonexistent-x", "Keep the Control", "panel-1", 12, comparison)
    return {name: (code, normalized(out, study), normalized(err, study)) for name, (code, out, err) in made.items()}


def kept(name: str) -> tuple:
    return (int((KEPT / f"{name}.exit").read_text(encoding="utf-8")), (KEPT / f"{name}.out").read_text(encoding="utf-8"), (KEPT / f"{name}.err").read_text(encoding="utf-8"))


def write_kept(outputs: dict) -> None:
    """Writes the files of `outputs` under `KEPT`; used once, by hand, when an output is added."""
    KEPT.mkdir(parents=True, exist_ok=True)
    for name, (code, out, err) in outputs.items():
        (KEPT / f"{name}.exit").write_text(f"{code}\n", encoding="utf-8")
        (KEPT / f"{name}.out").write_text(out, encoding="utf-8")
        (KEPT / f"{name}.err").write_text(err, encoding="utf-8")
