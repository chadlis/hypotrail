"""Ticket #94 (D-025 option B, D-026, D-027): E07's Case text states the format of `year`, and the change is a new Protocol revision.

The Reference and the Scorer are not touched here. The suffix states the format only, never a value.
"""

import json
import re
import shutil

from _agent_helpers import REFERENCES, WORKLOAD, read_jsonl
from _chinook_helpers import init_chinook
from _revision_helpers import new_revision, spec_of
from _run_agent_helpers import live, ok, patch_model, tree
from _study_helpers import EXAMPLES, ROOT

from hypotrail.agentic.cases import user_message
from hypotrail.core.errors import EXIT_INTEGRITY_REFUSED

# E07's `question` as it was before this ticket (commit c4b3284), kept as a literal.
OLD_QUESTION = "Combien de factures en 2009 et en 2013, séparément ? Trier les années par ordre croissant."
CASES = "chinook/cases/chinook-public-check.jsonl"


def e07():
    return next(case for case in WORKLOAD.cases("public_check") if case["case_id"] == "E07")


def suffix():
    question = e07()["question"]
    assert question.startswith(OLD_QUESTION), question  # the earlier text stays verbatim as a prefix
    return question[len(OLD_QUESTION) :]


def test_e07_question_states_the_year_format_in_one_appended_french_sentence_and_the_user_message_holds_it():
    added = suffix().strip()
    assert "year" in added and "quatre caractères" in added and "texte" in added
    assert len(re.findall(r"[.!?](?:\s|$)", added)) == 1  # one sentence
    message = user_message(e07())
    assert message.startswith(f"Question: {OLD_QUESTION}") and added in message


def test_the_added_text_holds_no_digit_and_no_cell_value_of_the_reference():
    added = suffix()
    assert added.strip()
    assert not re.search(r"\d", added)
    reference = next(r for r in read_jsonl(REFERENCES) if r["case_id"] == "E07")
    cells = [str(cell) for row in reference["rows"] for cell in row]
    assert cells and all(cell not in added for cell in cells)


def old_examples(tmp_path):
    """A copy of `examples/` whose public_check Cases file is the one before this ticket: E07 with its old text."""
    target = tmp_path / "examples-before"
    shutil.copytree(EXAMPLES, target)
    path = target / CASES
    text = path.read_text(encoding="utf-8")
    assert json.dumps(e07()["question"], ensure_ascii=False) in text or e07()["question"] in text
    path.write_text(text.replace(e07()["question"], OLD_QUESTION), encoding="utf-8")  # every other byte is the checkout's
    return target


def test_a_study_created_before_the_change_refuses_then_follows_it_with_a_new_revision(tmp_path, monkeypatch):
    study, _ = init_chinook(tmp_path, examples=old_examples(tmp_path))
    first = spec_of(study)
    first_bytes = (study / "study.json").read_bytes()
    # the Workload now holds the new Cases file (the checkout's): the request is refused and writes no Attempt
    patch_model(monkeypatch)  # no model is called: a refusal comes first
    before = tree(study)
    code, payload, _ = live(study, "plain", "before")
    assert (code, payload.get("error", {}).get("code")) == (EXIT_INTEGRITY_REFUSED, "PROTOCOL_CHANGED")
    assert tree(study) == before and not any(path.startswith("attempts/") for path in before)
    # a new revision follows it
    code, payload, err = new_revision(study)
    assert code == 0, (payload, err)
    second = spec_of(study)
    assert second["protocol_digest"] != first["protocol_digest"]
    assert (study / "revisions" / "1" / "study.json").read_bytes() == first_bytes
    attempt = ok(live(study, "plain", "after"))
    assert attempt["effective_config"]["protocol"]["protocol_digest"] == second["protocol_digest"]


def _text(path):
    return re.sub(r"<[^>]+>", "", (ROOT / path).read_text(encoding="utf-8"))


def test_the_handbook_and_the_readme_say_that_a_changed_case_text_is_taken_with_a_new_revision():
    for chapter in ("04-study-and-attempts", "10-revisions-and-rescoring"):
        text = " ".join(_text(f"docs/handbook/chapters/{chapter}.html").split())
        assert re.search(r"changed Case text[^.]*init --study DIR --new-revision", text), chapter
    line = next(line for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines() if "init --study runs/chinook --new-revision" in line)
    assert "References" in line and "Cases" in line
