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


# A kept argument list names the Study it was given as this placeholder.
STUDY_OPTION = "--study="
STUDY_PLACEHOLDER = "--study=<study>"


def fixed(value):
    """`value` with the three keyed rules applied at every depth, and the value of `--study=` in a text replaced by `<study>`; a value of
    another shape under `code_revision` or `python` fails."""
    if isinstance(value, str) and value.startswith(STUDY_OPTION):
        return STUDY_PLACEHOLDER
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


def numbered(text: str, kind: str, pattern, seen: dict) -> str:
    return pattern.sub(lambda match: seen.setdefault(match[0], placeholder(kind, len(seen) + 1)), text)


def replaced(text: str, seen: dict | None = None) -> str:
    """A `status --json` text as kept: the top-level `attempts` sorted by `request_id`, the keyed rules applied, then each distinct UUID,
    timestamp and 64-hex digest replaced, in order of first appearance, by its numbered placeholder. `seen` holds, by kind, the placeholder
    of each value already replaced in another text, so that a second text made from the same Study goes on with the same numbering."""
    payload = json.loads(text)
    if isinstance(payload.get("attempts"), list):
        keys = [attempt.get("request_id") for attempt in payload["attempts"]]
        assert all(isinstance(key, str) for key in keys), f"a request_id that is not a text: {keys}"
        assert len(set(keys)) == len(keys), f"two Attempts share a request_id: {keys}"
        payload["attempts"] = sorted(payload["attempts"], key=lambda attempt: attempt["request_id"])
    text = json.dumps(fixed(payload), indent=2) + "\n"
    seen = {} if seen is None else seen
    for kind, pattern in (("uuid", UUID), ("timestamp", TIMESTAMP), ("digest", DIGEST)):
        text = numbered(text, kind, pattern, seen.setdefault(kind, {}))
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


def compared_sides(study) -> list:
    """The Control's and the Candidate's Assessment records of the Study's first Comparison, as `status --json` lists them."""
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    roles = payload["comparisons"][0]["roles"]
    by_id = {assessment["assessment_id"]: assessment for assessment in payload["assessments"]}
    return [by_id[roles["control_assessment_id"]], by_id[roles["candidate_assessment_id"]]]


def decide_at_sequence(study, option, request_id, *cited):
    """`decide` with the Study's current Write sequence as its read sequence."""
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    code, out, err = decide(study, option, request_id, payload["write_sequence"], *cited)
    assert code == 0, (out, err)


def rescored_study(tmp_path):
    """`decided_study`, then a new revision that corrects one `public_check` day and an `assess` of each side against it: "evidence rescored"."""
    from _review_helpers import TRACKS

    study = decided_study(tmp_path)
    sides = compared_sides(study)
    TRACKS["bike"].revise_no_assessed_item(study, tmp_path)
    for side in sides:
        TRACKS["bike"].assess_again(study, side)
    return study


def result_changed_study(tmp_path):
    """`decided_study` with a second Decision that cites the Candidate's Assessment, then the two steps of `rescored_study` and of a new
    revision that corrects one `dev` day, each followed by an `assess` of each side: "result changed"."""
    from _review_helpers import TRACKS

    study = decided_study(tmp_path)
    sides = compared_sides(study)
    decide_at_sequence(study, "Keep the Candidate", "panel-2", sides[1]["assessment_id"])
    for revise in (TRACKS["bike"].revise_no_assessed_item, TRACKS["bike"].revise_an_assessed_item):
        revise(study, tmp_path)
        for side in sides:
            TRACKS["bike"].assess_again(study, side)
    return study


def repeated_study(tmp_path):
    """`decided_study`, then one more `assess` of the Control's Observation set on the same revision: "repeated", and no new revision."""
    from _review_helpers import TRACKS

    study = decided_study(tmp_path)
    TRACKS["bike"].assess_again(study, compared_sides(study)[0])
    return study


def chinook_decided_study(tmp_path):
    """`chinook_pending_study` after a Decision on its Comparison."""
    study = chinook_pending_study(tmp_path)
    [comparison] = [p.name for p in (Path(study) / "comparisons").iterdir()]
    decide_at_sequence(study, "Keep the Candidate", "panel-1", comparison)
    return study


def chinook_withheld_study(tmp_path):
    """A Chinook Study with two imports, the full answers as the Control and answers whose D01 and D03 are `failed` as the Candidate, each
    assessed, and one Comparison of the two: an Episode is not scored on both sides, so the record withholds its main delta."""
    from _agent_compare_helpers import answer_lines, imported
    from _chinook_helpers import init_chinook
    from _deviation_helpers import compare_ids

    study, _ = init_chinook(tmp_path)
    claims = {"repeats": 1, "model": None, "tool_use": None, "mode": None}
    _, control = imported(tmp_path, study, "full", answer_lines(**claims), repeats=1)
    _, candidate = imported(tmp_path, study, "broken", answer_lines(**claims, failed={("D01", 0), ("D03", 0)}), repeats=1)
    compare_ids(study, control["assessment_id"], candidate["assessment_id"])
    return study


def bike_withheld_study(tmp_path):
    """A Bike Study with seasonal_7 run on dev and assessed, an import of forecasts of 1e308 for every dev day, assessed with the same
    Scorer, and one Comparison of the two. Every Item is scored on both sides, but the mean of the import's errors overflows, so its
    Metric is `errored` with a null value and the Comparison's delta value is null."""
    from _assess_helpers import assess, observation_set_id, references_id
    from _import_helpers import FIELDS, import_ml, ready, rows_of, write_rows

    study, _, assessments = assessed(tmp_path, "seasonal_7")
    source, mapping, population, _ = ready(tmp_path)
    write_rows(source, [{**row, "forecast_rentals": "1e308", "forecast_unrounded": "1e308"} for row in rows_of(source)], FIELDS)
    code, payload, err = import_ml(study, source, mapping, population, "import-huge")
    assert code == 0, (payload, err)
    code, payload, err = assess(study, observation_set_id(study, payload["attempt"]), "regression_mae_v1", references_id(study))
    assert code == 0, (payload, err)
    code, payload, err = compare(study, assessments["seasonal_7"]["assessment_id"], payload["assessment"]["assessment_id"])
    assert code == 0, (payload, err)
    return study


def public_check_study(tmp_path):
    """`compared_study`, then seasonal_7 run on public_check and never assessed: an Attempt on public_check that no Assessment assessed."""
    from _study_helpers import run_ml

    study = compared_study(tmp_path)
    code, payload, err = run_ml(study, "seasonal_7", "public_check", "ml-public_check-seasonal_7")
    assert code == 0, (payload, err)
    return study


def public_check_compared_study(tmp_path):
    """A Bike Study with seasonal_7 and ridge_v1 run on public_check, each assessed, and one Comparison of the two: each records an
    Exposure."""
    from _report_tracks import TRACKS as REPORT_TRACKS

    study, _, _, _ = REPORT_TRACKS["bike"].public_world(tmp_path)
    return study


def chinook_spread_study(tmp_path):
    """A Chinook Study with two imports, the full answers as the Control and answers wrong on D01 once and on D03 always as the Candidate,
    each assessed, and one Comparison of the two: its paired deltas are not all equal and its delta has a value."""
    from _agent_compare_helpers import answer_lines, imported
    from _chinook_helpers import init_chinook
    from _deviation_helpers import compare_ids

    study, _ = init_chinook(tmp_path)
    _, control = imported(tmp_path, study, "full", answer_lines())
    _, candidate = imported(tmp_path, study, "some-wrong", answer_lines(wrong={("D01", 0), ("D03", 0), ("D03", 1), ("D03", 2)}))
    compare_ids(study, control["assessment_id"], candidate["assessment_id"])
    return study


# The Studies the `figures` read is checked on.
FIGURES_STUDIES = {
    "compared": compared_study,
    "several-pending": several_pending_study,
    "bike-withheld": bike_withheld_study,
    "chinook-pending": chinook_pending_study,
    "chinook-withheld": chinook_withheld_study,
    "public-check": public_check_study,
    "public-check-compared": public_check_compared_study,
    "chinook-spread": chinook_spread_study,
}


STUDIES = {
    "status-success": compared_study,
    "status-chinook-pending": chinook_pending_study,
    "status-several-pending": several_pending_study,
    "status-decided": decided_study,
    "status-deviation": deviation_study,
    "status-rescored": rescored_study,
    "status-result-changed": result_changed_study,
    "status-repeated": repeated_study,
    "status-chinook-decided": chinook_decided_study,
    "status-chinook-withheld": chinook_withheld_study,
    "status-bike-withheld": bike_withheld_study,
    "status-public-check": public_check_study,
    "status-chinook-spread": chinook_spread_study,
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


# The demonstration's kept files (docs/demo/demonstration.py): the two reads of each kept state of the second Bike Study and the two kept
# `decide` calls, each as NAME.exit, NAME.out and NAME.err, and a `decide` with NAME.args, its argument list.
DEMONSTRATION_KEPT = KEPT / "demonstration"


def kept_names_of_the_demonstration() -> list:
    """The name of each kept process of the demonstration's step list, in the order the script writes them."""
    from _demonstration_helpers import demonstration, processes

    return [each["kept"] for _, each in processes(demonstration().STEPS) if "kept" in each]


def demonstration_outputs(folder: Path) -> dict:
    """{file name: text} of the files the step list wrote in `folder`, the work folder's `kept/`: each `.args` and `.out` replaced as
    `replaced` replaces them, with one numbering over all of them in the order the script wrote them, each `.exit` and `.err` as printed."""
    made, seen = {}, {}
    for name in kept_names_of_the_demonstration():
        for part in ("args", "exit", "out", "err"):
            path = folder / f"{name}.{part}"
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                made[path.name] = replaced(text, seen) if part in ("args", "out") else text
    return made


def write_kept(outputs: dict) -> None:
    """Writes the files of `outputs` under `KEPT`; used once, by hand, when an output is added."""
    KEPT.mkdir(parents=True, exist_ok=True)
    for name, (code, out, err) in outputs.items():
        (KEPT / f"{name}.exit").write_text(f"{code}\n", encoding="utf-8")
        (KEPT / f"{name}.out").write_text(out, encoding="utf-8")
        (KEPT / f"{name}.err").write_text(err, encoding="utf-8")


def write_demonstration_kept(folder: Path) -> None:
    """Writes the files of `demonstration_outputs(folder)` under `DEMONSTRATION_KEPT`; used once, by hand, when the step list changes."""
    DEMONSTRATION_KEPT.mkdir(parents=True, exist_ok=True)
    for name, text in demonstration_outputs(folder).items():
        (DEMONSTRATION_KEPT / name).write_text(text, encoding="utf-8")


# The kept `figures` reads, each with the kept `status` read made from the same helper call.
FIGURES_KEPT = {
    "figures-success": "status-success",
    "figures-several-pending": "status-several-pending",
    "figures-bike-withheld": "status-bike-withheld",
    "figures-chinook-pending": "status-chinook-pending",
    "figures-chinook-withheld": "status-chinook-withheld",
    "figures-public-check": "status-public-check",
    "figures-chinook-spread": "status-chinook-spread",
}


def pair_outputs(tmp_path) -> dict:
    """{name: (exit code, stdout, stderr)} of each kept `figures` read and of the kept `status` read made beside it from the same Study, both
    replaced with one numbering, so that a value of the two objects has one placeholder; and the `figures` read of a Study that does not
    exist, kept as printed."""
    made = {}
    for name, status in FIGURES_KEPT.items():
        (tmp_path / name).mkdir()
        study = STUDIES[status](tmp_path / name)
        seen: dict = {}
        for kept_name, command in ((status, "status"), (name, "figures")):
            code, out, err = run_cli(command, "--study", study, "--json")
            assert code == 0, (kept_name, out, err)
            made[kept_name] = (code, replaced(out.replace(str(study), "SCRATCH"), seen), err.replace(str(study), "SCRATCH"))
    made["figures-not-found"] = run_cli("figures", "--study=/nonexistent-x", "--json")
    return made
