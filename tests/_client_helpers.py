"""Shared by the client checks: the CLI output that `clients/vscode/test/cli/` keeps, made again offline on a scratch Study.

Each output is kept as three files, `NAME.exit`, `NAME.out` and `NAME.err`, with the scratch Study's folder replaced by `SCRATCH`. A kept
`status` read whose `ok` is true has its values replaced as `replaced` says; a kept `decide` output has each UUID replaced by `UUID`.
`status-not-found` names no scratch folder and is kept as printed.
"""

import json
import re
from pathlib import Path

from _compare_helpers import assessed, compare
from _study_helpers import run_cli, run_json

ROOT = Path(__file__).resolve().parent.parent
KEPT = ROOT / "clients" / "vscode" / "test" / "cli"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00")
DIGEST = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")


def placeholder(kind: str, number: int) -> str:
    return {"uuid": f"00000000-0000-4000-8000-{number:012x}", "timestamp": f"2000-01-01T00:00:00.{number:06d}+00:00", "digest": f"{number:064x}"}[kind]


# The fixed values of the rules that replace a value whole: `code_revision`, `python` and `size_bytes`, at every depth.
FIXED_CODE_REVISION = {"commit": "0" * 40, "dirty": False, "local_code_fingerprint": None}
FIXED_PYTHON = "PYTHON"
FIXED_SIZE_BYTES = 0


def fixed(value):
    """`value` with the three keyed rules applied at every depth; a value of another shape under `code_revision` or `python` fails."""
    if isinstance(value, list):
        return [fixed(each) for each in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, each in value.items():
        if key == "code_revision":
            assert isinstance(each, dict), f"code_revision is not an object: {each!r}"
            out[key] = dict(FIXED_CODE_REVISION)
        elif key == "python":
            assert isinstance(each, str), f"python is not a text: {each!r}"
            out[key] = FIXED_PYTHON
        elif key == "size_bytes":
            out[key] = FIXED_SIZE_BYTES
        else:
            out[key] = fixed(each)
    return out


def numbered(text: str, kind: str, pattern) -> str:
    seen: dict = {}
    return pattern.sub(lambda match: seen.setdefault(match[0], placeholder(kind, len(seen) + 1)), text)


def replaced(text: str) -> str:
    """A `status --json` text as kept: the top-level `attempts` sorted by `request_id`, the keyed rules applied, then each distinct UUID,
    timestamp and 64-hex digest replaced, in order of first appearance, by its numbered placeholder (D-093 and D-096 on chadlis/hypotrail#75)."""
    payload = json.loads(text)
    if isinstance(payload.get("attempts"), list):
        keys = [attempt.get("request_id") for attempt in payload["attempts"]]
        assert all(isinstance(key, str) for key in keys), f"a request_id that is not a text: {keys}"
        assert len(set(keys)) == len(keys), f"two Attempts share a request_id: {keys}"
        payload["attempts"] = sorted(payload["attempts"], key=lambda attempt: attempt["request_id"])
    text = json.dumps(fixed(payload), indent=2) + "\n"
    for kind, pattern in (("uuid", UUID), ("timestamp", TIMESTAMP), ("digest", DIGEST)):
        text = numbered(text, kind, pattern)
    return text


def first_difference(kept, made, path="$"):
    """The first path, in the kept object's order, at which `made` differs from `kept`, with both values; None when none does."""
    if isinstance(kept, float) or isinstance(made, float):
        same = isinstance(kept, (int, float)) and isinstance(made, (int, float)) and f"{kept:.12g}" == f"{made:.12g}"
        return None if same and not isinstance(kept, bool) and not isinstance(made, bool) else (path, kept, made)
    if type(kept) is not type(made):
        return (path, kept, made)
    if isinstance(kept, dict):
        for key in [*kept, *(k for k in made if k not in kept)]:
            if key not in kept or key not in made:
                return (f"{path}.{key}", kept.get(key), made.get(key))
            found = first_difference(kept[key], made[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(kept, list):
        for index, (a, b) in enumerate(zip(kept, made)):
            found = first_difference(a, b, f"{path}[{index}]")
            if found:
                return found
        return None if len(kept) == len(made) else (f"{path} (length)", len(kept), len(made))
    return None if kept == made else (path, kept, made)


def normalized(text: str, study) -> str:
    return UUID.sub("UUID", text.replace(str(study), "SCRATCH"))


def compared_study(tmp_path):
    """A Study of the Bike Workload at write sequence 12: two Attempts on dev, their two Assessments and one Comparison."""
    study, _, assessments = assessed(tmp_path, "seasonal_7", "ridge_v1")
    code, payload, err = compare(study, assessments["seasonal_7"]["assessment_id"], assessments["ridge_v1"]["assessment_id"])
    assert code == 0, (payload, err)
    return study


def chinook_pending_study(tmp_path):
    """A Chinook Study with two imports of the same answers, each assessed, and one Comparison of the two: its delta has a value."""
    from _deviation_helpers import chinook_world, compare_ids

    study, _, assessments = chinook_world(tmp_path, count=2)
    compare_ids(study, assessments[0], assessments[1])
    return study


def several_pending_study(tmp_path):
    """The two Assessments of `compared_study`, compared both ways: two pending decisions."""
    study, _, assessments = assessed(tmp_path, "seasonal_7", "ridge_v1")
    for control, candidate in (("seasonal_7", "ridge_v1"), ("ridge_v1", "seasonal_7")):
        code, payload, err = compare(study, assessments[control]["assessment_id"], assessments[candidate]["assessment_id"])
        assert code == 0, (payload, err)
    return study


def decided_study(tmp_path):
    """`compared_study` after a Decision on its Comparison: no pending decision."""
    study = compared_study(tmp_path)
    [comparison] = [p.name for p in (Path(study) / "comparisons").iterdir()]
    code, out, err = decide(study, "Keep the Control", "panel-1", 12, comparison)
    assert code == 0, (out, err)
    return study


def deviation_study(tmp_path):
    """`compared_study` after a Declared deviation, a second one, and the withdrawal of the second."""
    from _deviation_helpers import declare

    study = compared_study(tmp_path)
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    attempts = {attempt["request_id"]: attempt["attempt_id"] for attempt in payload["attempts"]}
    declare(study, [attempts["ml-dev-seasonal_7"]])
    second = declare(study, [attempts["ml-dev-ridge_v1"]], text="the Candidate's Attempt was rerun by hand")
    declare(study, [second["declared_deviation_id"]], text="the review is done")
    return study


STUDIES = {
    "status-success": compared_study,
    "status-chinook-pending": chinook_pending_study,
    "status-several-pending": several_pending_study,
    "status-decided": decided_study,
    "status-deviation": deviation_study,
}


def status_outputs(tmp_path) -> dict:
    """{name: (exit code, stdout, stderr)} of the reads the client tests keep, each `ok` one with its values replaced (`replaced`)."""
    made = {}
    for name, make in STUDIES.items():
        (tmp_path / name).mkdir()
        study = make(tmp_path / name)
        code, out, err = run_cli("status", "--study", study, "--json")
        assert code == 0, (name, out, err)
        made[name] = (code, replaced(out.replace(str(study), "SCRATCH")), err.replace(str(study), "SCRATCH"))
    made["status-not-found"] = run_cli("status", "--study=/nonexistent-x", "--json")
    return made


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
