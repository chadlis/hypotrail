"""The end-to-end test of S2 through the real command line, without network and with no key set: `init` on `chinook_prose`, `import agent`
of the fixture files, `assess --scorer text_facts_v1` of each, `compare` and `status --json`. Each part is one test."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROSE = ROOT / "examples" / "chinook_prose"
FIXTURES = {name: PROSE / "fixtures" / f"answers-{name}.jsonl" for name in ("concise", "verbose")}


def hypotrail(*args, json_out=True):
    """(exit code, stdout as JSON when `json_out`, else as text): the installed command line in a child process, with no key set."""
    environment = {key: value for key, value in os.environ.items() if key != "HYPOTRAIL_ANTHROPIC_API_KEY"}
    command = [sys.executable, "-m", "hypotrail", *map(str, args), *(["--json"] if json_out else [])]
    done = subprocess.run(command, capture_output=True, text=True, env=environment, cwd=ROOT)
    return done.returncode, json.loads(done.stdout) if json_out else done.stdout, done.stderr


def ok(*args):
    code, payload, err = hypotrail(*args)
    assert code == 0, (payload, err)
    return payload


def test_chinook_prose_compare_holds_an_interval_over_ten_groups(tmp_path):
    study = tmp_path / "s2g-study"
    references = ok("init", "--workload", "chinook_prose", "--study", study)["references_id"]
    cases = [json.loads(line)["case_id"] for line in (PROSE / "cases" / "chinook-prose-dev.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    population = tmp_path / "s2g-population.json"
    population.write_text(json.dumps({"episodes": [{"case_id": case_id, "repeat": 0} for case_id in cases]}), encoding="utf-8")
    assessments = {}
    for name, source in FIXTURES.items():
        imported = ok("import", "agent", "--study", study, "--source", source, "--population", population, "--request-id", f"s2g-{name}")
        assessed = ok("assess", "--study", study, "--observations", imported["observation_set_id"], "--scorer", "text_facts_v1", "--references", references)
        assessments[name] = assessed["assessment"]["assessment_id"]
    code, line, err = hypotrail("compare", "--study", study, "--control", assessments["concise"], "--candidate", assessments["verbose"], json_out=False)
    assert code == 0, (line, err)
    assert " over 10 groups (Candidate minus Control" in line
    [stored_path] = (study / "comparisons").glob("*/comparison.json")
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    seed = json.loads((PROSE / "workload.json").read_text(encoding="utf-8"))["resampling"]["seed"]
    interval = stored["interval"]
    assert (interval["unit"], interval["units"], interval["cases"], interval["seed"]) == ("group", 10, 30, seed)
    assert interval["lower"] is not None and interval["upper"] is not None
    [listed] = ok("status", "--study", study)["comparisons"]
    assert listed == stored
