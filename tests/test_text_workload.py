"""Text Cases, `text-reference/1` and `text_facts_v1` on the `chinook_prose` Workload (#265).

Every command runs in process through the CLI, offline, with no key and no provider: `chinook_prose` is evaluated only
through `import agent`.
"""

import csv
import io
import json
import shutil
from pathlib import Path

import pytest
from _chinook_helpers import FIXTURE, episodes_file, fixture_population, import_agent, init_chinook, write_lines
from _study_helpers import EXAMPLES, run_json

from hypotrail.core import scorers, text_facts

PROSE = EXAMPLES / "chinook_prose"
DEV_FILE = "cases/chinook-prose-dev.jsonl"


def jsonl(path: Path) -> list:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def prose_copy(tmp_path, edit_cases=None, edit_declaration=None, name="examples") -> Path:
    """A copy of `examples/` whose `chinook_prose` dev Cases (a function of the list) or declaration may be changed."""
    target = Path(tmp_path) / name
    shutil.copytree(EXAMPLES, target)
    if edit_cases is not None:
        path = target / "chinook_prose" / DEV_FILE
        cases = {case["case_id"]: case for case in jsonl(path)}
        edit_cases(cases)
        write_lines(path, list(cases.values()))
    if edit_declaration is not None:
        path = target / "chinook_prose" / "workload.json"
        declaration = json.loads(path.read_text(encoding="utf-8"))
        edit_declaration(declaration)
        path.write_text(json.dumps(declaration, indent=2), encoding="utf-8")
    return target


def init_prose(tmp_path, examples=None, name="prose"):
    study = Path(tmp_path) / name
    args = ["init", "--workload", "chinook_prose", "--study", study]
    if examples is not None:
        args += ["--examples-dir", examples]
    code, payload, err = run_json(*args)
    return study, code, payload, err


def prose_study(tmp_path, examples=None, name="prose"):
    study, code, payload, err = init_prose(tmp_path, examples, name)
    assert code == 0, (payload, err)
    return study, payload["references_id"]


def reference_text(case_id: str) -> str:
    return next(r["reference_text"] for r in jsonl(PROSE / "references" / "chinook-prose-references.jsonl") if r["case_id"] == case_id)


# --- criterion 2: the Case refusals, before any write ---------------------------------------------------------------------------


def _assistant(case, **turn):
    case["history"][1] = {"role": "assistant", **turn}


REFUSALS = {
    "CASE_FIELD_INVALID group": (lambda cases: cases["D01"].update(group=""), "CASE_FIELD_INVALID", {"field": "group"}),
    "CASE_FIELD_INVALID family": (lambda cases: cases["D01"].update(family=5), "CASE_FIELD_INVALID", {"field": "family"}),
    "CASE_FIELD_INVALID history": (lambda cases: cases["D25"].update(history=[{"role": "system", "content": "x"}]), "CASE_FIELD_INVALID", {"field": "history"}),
    "HISTORY_SHOWS_OWN_REFERENCE by from_case": (
        lambda cases: _assistant(cases["D25"], from_case="D25", content=reference_text("D25")),
        "HISTORY_SHOWS_OWN_REFERENCE",
        {"case_id": "D25"},
    ),
    "HISTORY_SHOWS_OWN_REFERENCE by content": (
        lambda cases: _assistant(cases["D25"], content=reference_text("D25")),
        "HISTORY_SHOWS_OWN_REFERENCE",
        {"case_id": "D25"},
    ),
    "HISTORY_SOURCE_MISMATCH by text": (
        lambda cases: _assistant(cases["D25"], from_case="D01", content=reference_text("D01") + " More."),
        "HISTORY_SOURCE_MISMATCH",
        {"case_id": "D25", "from_case": "D01"},
    ),
    "HISTORY_SOURCE_MISMATCH by unknown Case": (
        lambda cases: _assistant(cases["D25"], from_case="D99", content=reference_text("D01")),
        "HISTORY_SOURCE_MISMATCH",
        {"case_id": "D25", "from_case": "D99"},
    ),
}


@pytest.mark.parametrize("refusal", list(REFUSALS))
def test_init_refuses_a_malformed_text_case_or_a_history_that_shows_a_reference_before_anything_is_written(tmp_path, refusal):
    edit, code_name, details = REFUSALS[refusal]
    study, code, payload, err = init_prose(tmp_path, prose_copy(tmp_path, edit_cases=edit))
    assert (code, payload.get("error", {}).get("code")) == (2, code_name), (payload, err)
    assert details.items() <= payload["error"]["details"].items()
    assert not study.exists()


# --- criterion 3: assessing a chinook_prose Study -----------------------------------------------------------------------------


PRODUCED_ANSWER = (
    "Customer 12 has 7 invoices:\n\n| Invoice | Date | Total |\n|---|---|---|\n"
    "| INV-0034 | 2009-05-23 | $0.99 |\n| invoice 155 | 2010-11-14 | $1.98 |\n| invoice 166 | 2010-12-25 | $13.86 |\n"
    "| invoice 221 | 2011-08-25 | $8.91 |\n| invoice 350 | 2013-03-31 | $1.98 |\n| invoice 373 | 2013-07-03 | $3.96 |\n"
    "| invoice 395 | 2013-10-05 | $5.94 |\n"
)
LINES = [
    {"case_id": "D01", "repeat": 0, "observation_status": "produced", "raw_answer": PRODUCED_ANSWER},
    {"case_id": "D02", "repeat": 0, "observation_status": "failed"},
    {"case_id": "D03", "repeat": 0, "observation_status": "missing"},
]


def imported(tmp_path, study, lines=LINES, name="answers", *more):
    source = write_lines(Path(tmp_path) / f"{name}.jsonl", lines)
    population = episodes_file(tmp_path, [(line["case_id"], line["repeat"]) for line in lines], name=f"{name}-population.json")
    return import_agent(study, source, population, name, *more)


def observation_set(tmp_path, study, lines=LINES, name="answers", *more) -> str:
    code, payload, err = imported(tmp_path, study, lines, name, *more)
    assert code == 0, (payload, err)
    return payload["observation_set_id"]


def assess(study, observations, scorer, references):
    return run_json("assess", "--study", study, "--observations", observations, "--scorer", scorer, "--references", references)


def per_item(study, record) -> dict:
    rows = csv.DictReader(io.StringIO((Path(study) / record["per_item_ref"]["path"]).read_text(encoding="utf-8")))
    found = {}
    for row in rows:
        found.setdefault(row["case_id"], []).append((row["criterion"], row["state"], row["score"], row["reason"]))
    return found


def test_assess_text_facts_v1_writes_an_assessment_with_the_five_criteria_for_a_produced_a_failed_and_a_missing_episode(tmp_path):
    study, references = prose_study(tmp_path)
    code, payload, err = assess(study, observation_set(tmp_path, study), "text_facts_v1", references)
    assert code == 0, (payload, err)
    record = payload["assessment"]
    assert record["primary_criterion"] == "text_facts_success"
    rows = per_item(study, record)
    assert rows["D01"] == [(name, "scored", "true", "") for name in text_facts.CRITERIA]
    assert rows["D02"] == [(name, "unscored", "", "execution_failed") for name in text_facts.CRITERIA]
    assert rows["D03"] == [(name, "unscored", "", "observation_missing") for name in text_facts.CRITERIA]


def test_chinook_contract_v1_on_a_chinook_prose_study_is_refused_primary_criterion_not_of_scorer(tmp_path):
    study, references = prose_study(tmp_path)
    code, payload, err = assess(study, observation_set(tmp_path, study), "chinook_contract_v1", references)
    assert (code, payload.get("error", {}).get("code")) == (2, "PRIMARY_CRITERION_NOT_OF_SCORER"), (payload, err)
    assert not (study / "assessments").exists()


def test_text_facts_v1_on_a_chinook_study_is_refused_primary_criterion_not_of_scorer(tmp_path):
    study, init_payload = init_chinook(tmp_path)
    code, payload, err = import_agent(study, FIXTURE, fixture_population(tmp_path), "i")
    assert code == 0, (payload, err)
    references = next(e["artifact_id"] for e in init_payload["artifacts"] if e["ref"]["role"] == "references")
    code, payload, err = assess(study, payload["observation_set_id"], "text_facts_v1", references)
    assert (code, payload.get("error", {}).get("code")) == (2, "PRIMARY_CRITERION_NOT_OF_SCORER"), (payload, err)


def test_text_facts_v1_on_a_study_that_keeps_no_scoring_config_is_refused_scoring_config_not_kept(tmp_path):
    examples = prose_copy(tmp_path, edit_declaration=lambda d: d.pop("scoring_config"))
    study, references = prose_study(tmp_path, examples)
    code, payload, err = assess(study, observation_set(tmp_path, study, LINES, "answers", "--examples-dir", examples), "text_facts_v1", references)
    assert (code, payload.get("error", {}).get("code")) == (2, "SCORING_CONFIG_NOT_KEPT"), (payload, err)


SCORING_CONFIG_FAULTS = {
    "no identifier kinds": (lambda config: config.pop("identifier_kinds"), ""),
    "a kind without its pattern": (lambda config: config["identifier_kinds"]["invoice"].pop("pattern"), "identifier_kinds.invoice"),
    "a phrase list that is not a list": (lambda config: config["outcome_phrases"].update(not_answerable="no data"), "outcome_phrases.not_answerable"),
}


def scoring_config_copy(tmp_path, edit, name="examples") -> Path:
    """A copy of `examples/` whose `chinook_prose` scoring config is changed by `edit`."""
    target = prose_copy(tmp_path, name=name)
    path = target / "chinook_prose" / "scoring" / "text-facts.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    edit(config)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return target


@pytest.mark.parametrize("fault", list(SCORING_CONFIG_FAULTS))
def test_init_refuses_a_scoring_config_that_does_not_match_the_text_facts_schema_before_anything_is_written(tmp_path, fault):
    edit, path = SCORING_CONFIG_FAULTS[fault]
    study, code, payload, err = init_prose(tmp_path, scoring_config_copy(tmp_path, edit))
    assert (code, payload.get("error", {}).get("code")) == (2, "SCORING_CONFIG_INVALID"), (payload, err)
    assert (payload["error"]["details"]["file"], payload["error"]["details"]["path"]) == ("scoring/text-facts.json", path)
    assert not study.exists()


def test_the_config_digest_of_a_text_facts_assessment_covers_the_studys_scoring_config(tmp_path):
    study, references = prose_study(tmp_path)
    code, payload, err = assess(study, observation_set(tmp_path, study), "text_facts_v1", references)
    assert code == 0, (payload, err)
    kept = next(e["ref"]["sha256"] for e in json.loads((study / "study.json").read_text(encoding="utf-8"))["artifacts"] if e["ref"]["role"] == "scoring_config")
    scorer = scorers.get("text_facts_v1")
    assert payload["assessment"]["scorer"]["config_digest"] == scorer.config_digest_for(kept) != scorer.config_digest_for("0" * 64)


# --- criterion 4: the line's outcome ---------------------------------------------------------------------------------------------


def normalized_entries(study) -> list:
    [path] = sorted(Path(study).glob("attempts/*/observations.jsonl"))
    return jsonl(path)


@pytest.mark.parametrize("outcome", ["answered", "needs_clarification", "not_answerable", None])
def test_a_lines_outcome_reaches_the_normalized_entry_and_is_absent_when_the_line_has_none(tmp_path, outcome):
    study, _ = prose_study(tmp_path)
    line = {"case_id": "D16", "repeat": 0, "observation_status": "produced", "raw_answer": "Do you mean by spend?"}
    if outcome is not None:
        line["outcome"] = outcome
    observation_set(tmp_path, study, [line])
    [entry] = normalized_entries(study)
    if outcome is None:
        assert "outcome" not in entry
    else:
        assert entry["outcome"] == outcome


@pytest.mark.parametrize("value", ["maybe", 3], ids=["another string", "not a string"])
def test_a_lines_outcome_outside_the_three_is_refused_line_field_invalid_and_nothing_is_published(tmp_path, value):
    study, _ = prose_study(tmp_path)
    line = {"case_id": "D16", "repeat": 0, "observation_status": "produced", "raw_answer": "x", "outcome": value}
    code, payload, err = imported(tmp_path, study, [line])
    assert (code, payload.get("error", {}).get("code"), payload.get("error", {}).get("details", {}).get("field")) == (2, "LINE_FIELD_INVALID", "outcome"), (payload, err)
    assert not list(study.glob("attempts/*"))


# --- criterion 5: the registry's per-Episode function is the one used -------------------------------------------------------------


def test_a_registered_scorer_whose_function_marks_every_criterion_false_makes_per_item_follow_it(tmp_path, monkeypatch):
    def all_false(text, reference, read, entry):
        return {"criteria": [{"name": name, "state": "scored", "score": False, "reason": "planted"} for name in text_facts.CRITERIA]}

    planted = scorers.Scorer(
        "all_false_v1", "1", scorers.AGENTIC, None, None, None, criteria=text_facts.CRITERIA, episode=all_false, reads=scorers.SCORING_CONFIG
    )
    monkeypatch.setitem(scorers.REGISTRY, planted.id, planted)
    study, references = prose_study(tmp_path)
    code, payload, err = assess(study, observation_set(tmp_path, study, LINES[:1]), "all_false_v1", references)
    assert code == 0, (payload, err)
    assert per_item(study, payload["assessment"])["D01"] == [(name, "scored", "false", "planted") for name in text_facts.CRITERIA]


# --- criterion 7: the public References parse, and every history turn is its Case's reference_text ------------------------------


REFERENCE_LINES = jsonl(PROSE / "references" / "chinook-prose-references.jsonl")
CASES = {case["case_id"]: case for name in (DEV_FILE, "cases/chinook-prose-public-check.jsonl") for case in jsonl(PROSE / name)}


@pytest.mark.parametrize("record", REFERENCE_LINES, ids=[r["case_id"] for r in REFERENCE_LINES])
def test_each_public_reference_reads_as_text_reference_1(record):
    assert text_facts.reference_problem(record) is None
    assert record["case_id"] in CASES


def test_every_from_case_history_turn_equals_the_reference_text_of_the_case_it_names():
    turns = [turn for case in CASES.values() for turn in case.get("history", []) if "from_case" in turn]
    assert len(turns) == 6
    texts = {r["case_id"]: r.get("reference_text") for r in REFERENCE_LINES}
    for turn in turns:
        assert turn["content"] == texts[turn["from_case"]]


# --- criterion 8: the rule's rewording and the glossary, by dated lines --------------------------------------------------------

ROOT = EXAMPLES.parent
RULE = "- Reference answers are never shown to an evaluated agent, and a reference is never changed to improve a score."
REWORDED = '"the Reference of the Case being answered is never shown to the evaluated agent"'


def test_agents_md_keeps_its_reference_rule_and_rewords_its_first_clause_in_a_dated_line_under_it():
    lines = (ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()
    at = lines.index(RULE)
    assert lines[at + 1].startswith("  - Clarification, 2026-11-26: ") and REWORDED in lines[at + 1]
    assert "scripted history" in lines[at + 1] and "D-154 on chadlis/hypotrail#75, comment 7190632961, item 1" in lines[at + 1]


def test_the_glossary_keeps_the_reference_and_case_definitions_and_dates_the_text_case_lines_under_them():
    lines = (ROOT / "GLOSSARY.md").read_text(encoding="utf-8").splitlines()
    reference = lines.index("**Reference**:")
    assert lines[reference + 1] == "The frozen expected outcome for an Item, versioned as a whole set and never shown to the system being evaluated."
    assert lines[reference + 2].startswith("Clarification, 2026-11-26: ") and "scripted history" in lines[reference + 2] and "not Claims" in lines[reference + 2]
    case = lines.index("**Case**:")
    assert lines[case + 1] == "One question of an agentic Track, with its requested columns and unit; it carries no expected answer."
    assert lines[case + 2].startswith("Clarification, 2026-11-26: ") and "`history`" in lines[case + 2]
