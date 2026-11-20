"""Shared by the Chinook Study tests (#68): a Chinook Study, the kit's authored answers, population files, `import agent`."""

import json
import shutil
from pathlib import Path

from _study_helpers import EXAMPLES, ROOT, run_json

FIXTURE = ROOT / "examples" / "chinook" / "fixtures" / "agent-answers-authored.jsonl"
FIXTURE_CASES = ["D01", "D03", "D07", "D08"]


def chinook_examples(tmp_path, *, edit=None, name="examples"):
    """A private copy of `examples/` whose Chinook declaration `edit` may change."""
    target = tmp_path / name
    shutil.copytree(EXAMPLES, target)
    if edit is not None:
        path = target / "chinook" / "workload.json"
        declaration = json.loads(path.read_text(encoding="utf-8"))
        edit(declaration)
        path.write_text(json.dumps(declaration, indent=2), encoding="utf-8")
    return target


def init_chinook(tmp_path, *, name="study", examples=None):
    study = tmp_path / name
    args = ["init", "--workload", "chinook", "--study", study]
    if examples is not None:
        args += ["--examples-dir", examples]
    code, payload, err = run_json(*args)
    assert code == 0, (payload, err)
    return study, payload["study"]


def write_lines(path, lines):
    Path(path).write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return Path(path)


def fixture_lines():
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]


def episodes_file(tmp_path, keys, *, name="population.json"):
    path = Path(tmp_path) / name
    path.write_text(json.dumps({"episodes": [{"case_id": c, "repeat": r} for c, r in keys]}), encoding="utf-8")
    return path


def fixture_population(tmp_path, name="population.json"):
    return episodes_file(tmp_path, [(c, 0) for c in FIXTURE_CASES], name=name)


def import_agent(study, source, population, request_id, *more):
    return run_json("import", "agent", "--study", study, "--source", source, "--population", population, "--request-id", request_id, *more)


def spec_of(study):
    return json.loads((Path(study) / "study.json").read_text(encoding="utf-8"))


def references_id(study):
    return next(e["artifact_id"] for e in spec_of(study)["artifacts"] if e["ref"]["role"] == "references")


def database_of(examples) -> Path:
    return Path(examples) / "chinook" / "data" / "Chinook_Sqlite.sqlite"
