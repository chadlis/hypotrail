"""Shared by the Exposure tests (#73): public_check runs and imports, the journal and freeze records as files, the corrected Workloads."""

import json
import shutil
from pathlib import Path

from _agent_compare_helpers import trace_of
from _chinook_helpers import episodes_file, import_agent, references_id as chinook_references_id, write_lines
from _study_helpers import EXAMPLES, run_json

PUBLIC_CASES = [f"E{n:02d}" for n in range(1, 13)]
REPEATS = 3
SCORER = "chinook_contract_v1"


def journal(study) -> list:
    folder = Path(study) / "exposures"
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))] if folder.is_dir() else []


def freezes(study) -> list:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((Path(study) / "revisions").glob("*/freeze.json"))]


def public_lines(*, wrong=()) -> list:
    """One answer per public_check Case and Repeat: the Reference's own answer, or a wrong one for the (case, repeat) in `wrong`."""
    references = {r["case_id"]: r for r in (json.loads(line) for line in (EXAMPLES / "chinook" / "references" / "chinook-references.jsonl").read_text().splitlines())}
    lines = []
    for case_id in PUBLIC_CASES:
        reference = references[case_id]
        for repeat in range(REPEATS):
            answer = {key: reference[key] for key in ("status", "reason_code", "columns", "rows", "unit")}
            answered = answer["status"] == "answered"
            answer["evidence"] = ["c1"] if answered else []
            if (case_id, repeat) in wrong:
                answer["status"], answer["reason_code"], answer["columns"], answer["rows"], answer["unit"] = "not_answerable", "field_not_available", [], [], None
            trace = trace_of() if answered else [{"kind": "model_turn", "turn": 1, "stop_reason": "stop"}, {"kind": "final_answer", "text": "done"}]
            lines.append({"case_id": case_id, "repeat": repeat, "origin": "agent_output", "observation_status": "produced", "final_answer": answer, "trace": trace})
    return lines


def import_public(tmp_path, study, name, lines=None) -> dict:
    """The Attempt of an Import of the 12 public_check Cases x 3 Repeats."""
    source = write_lines(Path(tmp_path) / f"{name}.jsonl", lines or public_lines())
    keys = [(case_id, repeat) for case_id in PUBLIC_CASES for repeat in range(REPEATS)]
    code, payload, err = import_agent(study, source, episodes_file(tmp_path, keys, name=f"{name}-population.json"), name)
    assert code == 0, (payload, err)
    return payload["attempt"]


def observation_set_of(study, attempt) -> str:
    return json.loads((Path(study) / "attempts" / attempt["attempt_id"] / "observation_set.json").read_text())["observation_set_id"]


def assess_agent(study, attempt, *more):
    return run_json(
        "assess", "--study", study, "--observations", observation_set_of(study, attempt), "--scorer", SCORER, "--references", chinook_references_id(study), *more
    )


def compare_ids(study, control, candidate, *more):
    return run_json("compare", "--study", study, "--control", control, "--candidate", candidate, *more)


def edit_chinook_references(tmp_path, edit, *, name="corrected") -> Path:
    """A copy of `examples/` whose Chinook References `edit` changes (the data lock does not cover that file)."""
    target = tmp_path / name
    shutil.copytree(EXAMPLES, target)
    path = target / "chinook" / "references" / "chinook-references.jsonl"
    records = {r["case_id"]: r for r in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())}
    edit(records)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records.values()), encoding="utf-8")
    return target


def correct_e01(records):
    records["E01"]["rows"] = [[records["E01"]["rows"][0][0] + 1]]
