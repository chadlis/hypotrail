"""R1-09 (#69 AC4, #68 AC7): neither the import nor `assess` opens or hashes the live Chinook database."""

import json
from pathlib import Path

from _chinook_helpers import chinook_examples, fixture_lines, fixture_population, import_agent, init_chinook, references_id, write_lines
from _exposure_helpers import PUBLIC_CASES, REPEATS, SCORER, journal, public_lines
from _chinook_helpers import episodes_file
from _log_helpers import scripted_log
from _study_helpers import run_json


def database_of(examples) -> Path:
    return Path(examples) / "chinook" / "data" / "Chinook_Sqlite.sqlite"


def observation_set_of(study, attempt) -> str:
    return json.loads((Path(study) / "attempts" / attempt["attempt_id"] / "observation_set.json").read_text())["observation_set_id"]


def assess(study, attempt, examples):
    return run_json(
        "assess", "--study", study, "--observations", observation_set_of(study, attempt), "--scorer", SCORER,
        "--references", references_id(study), "--examples-dir", examples,
    )


def test_a_jsonl_import_and_its_assessment_succeed_when_the_chinook_file_is_gone_before_the_import(tmp_path):
    examples = chinook_examples(tmp_path)
    study = init_chinook(tmp_path, examples=examples)[0]
    source = write_lines(tmp_path / "answers.jsonl", fixture_lines())
    database_of(examples).unlink()  # unreadable before the import, not only before the Assessment
    code, payload, err = import_agent(study, source, fixture_population(tmp_path), "x", "--examples-dir", examples)
    assert code == 0, (payload, err)
    code, payload, err = assess(study, payload["attempt"], examples)
    assert code == 0, (payload, err)


def test_an_inspect_log_import_succeeds_when_the_chinook_file_is_gone_before_the_import(tmp_path):
    log = scripted_log(tmp_path, ("D01", "D03"))
    examples = chinook_examples(tmp_path)
    study = init_chinook(tmp_path, examples=examples)[0]
    database_of(examples).unlink()
    population = episodes_file(tmp_path, [("D01", 0), ("D03", 0)])
    code, payload, err = import_agent(study, log, population, "x", "--examples-dir", examples)
    assert code == 0, (payload, err)
    code, payload, err = assess(study, payload["attempt"], examples)
    assert code == 0, (payload, err)


def test_a_public_check_assessment_freezes_without_reading_the_chinook_file(tmp_path):
    examples = chinook_examples(tmp_path)
    study = init_chinook(tmp_path, examples=examples)[0]
    keys = [(case_id, repeat) for case_id in PUBLIC_CASES for repeat in range(REPEATS)]
    source = write_lines(tmp_path / "public.jsonl", public_lines())
    database_of(examples).unlink()
    code, payload, err = import_agent(study, source, episodes_file(tmp_path, keys), "p", "--examples-dir", examples)
    assert code == 0, (payload, err)
    code, payload, err = assess(study, payload["attempt"], examples)
    assert code == 0, (payload, err)
    assert len(journal(study)) == 1
