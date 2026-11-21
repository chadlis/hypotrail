"""Ticket #111 (slice #104, L2.1): the records that #107 to #110 do not write themselves.

The GLOSSARY clarification on « report », the ADR of the panel-CLI contract, and the README. Nothing here runs a command
that writes, and no model is called. The handbook rows are in `tests/test_handbook.py`.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ADR_DIR = ROOT / "docs" / "adr"


def adr() -> str:
    found = sorted(ADR_DIR.glob("0004-*.md"))
    assert len(found) == 1, f"there is no ADR 0004 in docs/adr/: {[p.name for p in sorted(ADR_DIR.glob('*.md'))]}"
    return found[0].read_text(encoding="utf-8")


def section(text: str, title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"the ADR has no section « {title} »"
    return match[1]


def squash(text: str) -> str:
    return " ".join(text.split())


# --- GLOSSARY ---------------------------------------------------------------------------------------------


def test_the_glossary_says_as_a_dated_clarification_of_exposure_that_a_live_view_is_not_a_report():
    glossary = (ROOT / "GLOSSARY.md").read_text(encoding="utf-8")
    entry = re.search(r"^\*\*Exposure\*\*:\n(.*?)(?=^\*\*|\Z)", glossary, re.S | re.M)[1]
    clarification = next((l for l in entry.splitlines() if l.startswith("Clarification, 2026-11-21")), None)
    assert clarification, "the Exposure entry has no clarification dated 2026-11-21"
    assert "D-031" in clarification and "item 9" in clarification
    assert re.search(r"live view of artifacts already recorded is not a « report »", clarification)
    assert "does not record an Exposure" in clarification and "does not write" in clarification


# --- the ADR ----------------------------------------------------------------------------------------------


def test_the_adr_is_accepted_and_has_the_sections_of_the_others():
    text = adr()
    assert text.startswith("# ") and "\nStatus: accepted\n" in text
    section(text, "Considered options")
    section(text, "Consequences")


def test_the_adr_states_the_study_is_the_only_decision_authority_and_how_a_client_reads_and_writes():
    text = squash(adr())
    assert "The Study is the only decision authority" in text
    assert re.search(r"reads? (the Study )?through `status --json`", text)
    assert re.search(r"writes? only through (the )?documented CLI commands", text)


def test_the_adr_states_every_write_accepts_the_read_sequence_and_decide_requires_it_with_a_request_id():
    text = squash(adr())
    assert re.search(r"[Ee]very command that writes to a Study accepts `--read-sequence", text)
    assert re.search(r"`decide` requires `--read-sequence N` and `--request-id`", text)


def test_the_adr_states_a_write_on_an_older_sequence_is_refused_with_the_code_of_108_and_nothing_is_written():
    text = squash(adr())
    assert re.search(r"`STUDY_CHANGED`.{0,80}exit 6.{0,200}nothing is written", text)
    assert "`WRITE_SEQUENCE_AHEAD`" in text


def test_the_adr_states_whether_a_decision_still_applies_is_computed_when_the_study_is_read_and_never_stored():
    text = squash(adr())
    assert re.search(r"[Ww]hether a decision still applies is computed when the Study is read", text)
    assert "never stored" in text


def test_the_adr_considered_options_include_the_two_that_d_031_rejected_each_with_its_reason():
    bullets = [squash(b) for b in section(adr(), "Considered options").split("\n- ") if "rejected, D-031" in b]
    assert len(bullets) == 2, bullets
    digest = next((b for b in bullets if "A digest of `status --json`" in b), None)
    assert digest and "`writer_alive`" in digest and "without a write" in digest
    revision = next((b for b in bullets if "The Protocol revision" in b), None)
    assert revision and "misses decisions" in revision


def test_the_adr_names_only_codes_and_commands_the_code_defines():
    source = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "src" / "hypotrail").rglob("*.py"))
    text = adr()
    named = set(re.findall(r"`([A-Z][A-Z_]{4,})`", text))
    assert {"STUDY_CHANGED", "WRITE_SEQUENCE_AHEAD", "REQUEST_CONFLICT"} <= named
    for code in named:
        assert f'"{code}"' in source, code
    for flag in set(re.findall(r"`(--[a-z-]+)", text)):
        assert f'"{flag}"' in source, flag


def test_the_adr_records_the_cli_side_only_and_names_no_client_directory_runner_bundler_or_packaging():
    # #111 Tightened A: the client's location and tooling go to L2.4
    text = adr().lower()
    for word in ("clients/", ".vsix", "bundler", "bundle", "esbuild", "webpack", "mocha", "jest", "vitest", "packaging", "test runner", "vscode"):
        assert word not in text, word
    assert "L2.4" in adr()


def test_the_adr_states_the_panel_never_shows_public_check_content_that_no_assessment_or_comparison_journaled():
    # #111 Tightened B
    assert "never shows `public_check` content that no Assessment or Comparison has journaled" in squash(adr())


def test_the_adr_states_the_read_then_pass_rule_and_names_l2_2_and_l2_6_as_the_places_that_write_it_for_agents():
    # #111 Tightened C
    text = squash(adr())
    assert re.search(r"reads the Study \(`status --json`\) and passes the write sequence it read on every write", text)
    assert "L2.2" in text and "L2.6" in text


def test_l2_1_writes_no_agent_instruction():
    # #111 Tightened C: as at `main` 607740c, neither exists
    assert not (ROOT / ".github" / "copilot-instructions.md").exists()
    settings = ROOT / ".claude" / "settings.json"
    assert not settings.exists() or "UserPromptSubmit" not in settings.read_text(encoding="utf-8")


# --- the README -------------------------------------------------------------------------------------------


def test_the_readme_status_paragraph_names_decide_the_decision_history_and_the_write_sequence():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    status = readme.split("## Status\n", 1)[1].split("\n\n", 1)[0]
    assert "`decide`" in status and "decision history" in status and "write sequence" in status


def test_the_readme_does_not_say_every_writing_command_takes_the_option_without_the_two_exceptions_of_the_handbook():
    # chapter 04: `init` that creates a Study refuses `--read-sequence`; `report` compares it only when it records an Exposure
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    line = next(l for l in readme.splitlines() if l.startswith("Every command that writes"))
    assert "`init`" in line and "`report`" in line
