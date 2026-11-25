"""Ticket #111 (slice #104, L2.1): the records that #107 to #110 do not write themselves.

The GLOSSARY clarification on "report", the ADR of the panel-CLI contract, and the README. Nothing here runs a command
that writes, and no model is called. The handbook rows are in `tests/test_handbook.py`.
"""

import re
import subprocess
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
    assert match, f"the ADR has no section '{title}'"
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
    assert re.search(r"live view of artifacts already recorded is not a \"report\"", clarification)
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
    bullets = [squash(b) for b in section(adr(), "Considered options").split("\n- ") if "rejected, D-031 on chadlis/hypotrail#75" in b]
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


def test_the_adr_holds_a_dated_line_that_names_status_since_and_writes_since():
    lines = [line for line in section(adr(), "Dated lines").splitlines() if re.match(r"- [0-9]{4}-[0-9]{2}-[0-9]{2}: ", line)]
    assert any("`--since" in line and "`writes_since`" in line for line in lines), lines


def test_the_adr_holds_a_dated_line_that_names_where_the_rule_for_agents_is_written_for_claude_code():
    lines = [line for line in section(adr(), "Dated lines").splitlines() if re.match(r"- [0-9]{4}-[0-9]{2}-[0-9]{2}: ", line)]
    assert any(all(name in line for name in ("`UserPromptSubmit`", "`--read-sequence`", "--author proxy`")) for line in lines), lines


COPILOT_RULE_SENTENCE = "The template states each of the four requirements in its own words"
NARROWED_COPILOT_SENTENCE = "L2.6 still writes it for Copilot."


def test_the_adr_holds_a_dated_line_that_names_where_the_rule_for_agents_is_written_for_copilot_quoting_its_ticket_and_the_line_it_narrows():
    lines = [line for line in section(adr(), "Dated lines").splitlines() if re.match(r"- [0-9]{4}-[0-9]{2}-[0-9]{2}: ", line)]
    found = [line for line in lines if "`.github/copilot-instructions.md`" in line]
    assert len(found) == 1, lines
    [line] = found
    assert "Copilot" in line
    assert f'"{COPILOT_RULE_SENTENCE}" (chadlis/hypotrail#202, B2)' in line
    assert f'the earlier line it narrows: "{NARROWED_COPILOT_SENTENCE}"' in line
    assert "`.github/` holds no such file" in line


def test_l2_1_tracks_no_agent_instruction():
    # `.claude/settings.json` is read on disk; the Copilot instructions file is read in the tracked tree.
    # What #111 Tightened C states, as at `main` 607740c, is "neither exists". The tracked-tree read is #205's, so that the
    # uncommitted install of the L2 demonstration, which .gitignore keeps out, does not fail this test.
    # The settings half therefore fails on a `UserPromptSubmit` hook installed in `.claude/settings.json`. The L2 demonstration
    # installs the hook in `.claude/settings.local.json` (chapter 19), which this test does not read.
    tracked = subprocess.run(["git", "ls-files", "--", ".github/copilot-instructions.md"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert tracked == ""
    settings = ROOT / ".claude" / "settings.json"
    assert not settings.exists() or "UserPromptSubmit" not in settings.read_text(encoding="utf-8")


# --- round 1 of the review of #104: R1-S-03, R1-S-04 and R1-P-05 -------------------------------------------------------


def test_the_adr_and_the_glossary_entries_of_this_slice_quote_english_with_plain_double_quotes():
    # R1-S-03: the guillemets are for quoted French
    glossary = (ROOT / "GLOSSARY.md").read_text(encoding="utf-8")
    added = [re.search(rf"^\*\*{name}\*\*:\n(.*?)(?=^\*\*|\Z)", glossary, re.S | re.M)[1] for name in ("Write sequence", "Decision", "Exposure")]
    found = [text for text in (adr(), *added) if "\u00ab" in text or "\u00bb" in text]
    assert found == []


def test_the_adr_names_every_decision_with_its_issue():
    # R1-S-04: a bare D-0xx means nothing
    bare = [m.group(0) for m in re.finditer(r"D-0\d\d(?! on chadlis/hypotrail#75)", adr())]
    assert bare == []


def test_the_adr_gives_each_slice_label_its_issue_at_its_first_appearance():
    # R1-S-04: L2.1 is #104; the parent #103 lists the others
    text = adr()
    for label, issue in (("L2.1", "chadlis/hypotrail#104"), ("L2.2", "chadlis/hypotrail#103"), ("L2.4", "chadlis/hypotrail#103"), ("L2.6", "chadlis/hypotrail#103")):
        first = text.index(label)
        assert issue in text[first : first + 120], (label, text[first : first + 120])


def test_the_glossary_write_sequence_entry_is_true_of_a_writer_killed_between_its_first_and_last_write():
    # R1-P-05, #107 Tightened B: such a writer leaves one entry
    glossary = (ROOT / "GLOSSARY.md").read_text(encoding="utf-8")
    entry = squash(re.search(r"^\*\*Write sequence\*\*:\n(.*?)(?=^\*\*|\Z)", glossary, re.S | re.M)[1])
    assert "two for each command that writes" in entry
    assert re.search(r"one when the writer was killed between its first write and its last", entry)


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


# --- the dated line of the review decision in `status --json` ------------------------------------------------------------


PENDING_SENTENCE = "`status --json` lists each pending decision with a question and options whose texts the core supplies."


def test_the_dated_lines_hold_one_line_for_the_four_additions_to_status_json_quoting_its_ticket_and_overriding_none():
    lines = [line for line in section(adr(), "Dated lines").splitlines() if line.startswith("- ")]
    found = [line for line in lines if "chadlis/hypotrail#163" in line]
    assert len(found) == 1, found
    [line] = found
    assert re.match(r"- \d{4}-\d{2}-\d{2}: ", line), line
    assert PENDING_SENTENCE in line and "the earlier line it overrides: none" in line
    for name in ("`assessments`", "`comparisons`", "`compared_assessment_superseded`", "`compared_assessment_not_held`", "`evidence_change`", "`pending_decisions`"):
        assert name in line, name


# --- the dated line of what "request id on every write" asks of the Study writers without the flag -------------------------------

CLIENT_WRITES_SENTENCE = (
    "The client writes to a Study only through `decide`, with `--request-id` and `--read-sequence`; `assess`, `compare`, `recover`, `init` and"
    " `report` take no `--request-id`, and the client never starts `report`."
)


def test_the_dated_lines_hold_one_line_that_quotes_the_client_writes_sentence_of_168_and_overrides_none_and_the_parser_agrees():
    lines = [line for line in section(adr(), "Dated lines").splitlines() if line.startswith("- ")]
    found = [line for line in lines if "chadlis/hypotrail#168" in line]
    assert len(found) == 1, found
    [line] = found
    assert re.match(r"- \d{4}-\d{2}-\d{2}: ", line), line
    assert CLIENT_WRITES_SENTENCE in line and line.endswith("the earlier line it overrides: none.")
    from hypotrail.cli import build_parser

    leaves = {}

    def walk(parser, path):
        subs = [a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"]
        if not subs:
            leaves[" ".join(path)] = {flag: a.required for a in parser._actions for flag in a.option_strings}
        for sub in subs:
            for name, child in sub.choices.items():
                walk(child, (*path, name))

    walk(build_parser(), ())
    for command in ("assess", "compare", "recover", "init", "report"):
        assert command in leaves and "--request-id" not in leaves[command], command
    assert leaves["decide"].get("--request-id") is True and leaves["decide"].get("--read-sequence") is True


# --- the dated line of the `figures` read ----------------------------------------------------------------------------------------

FIGURES_COMMAND_SENTENCE = "The CLI gains one leaf command, `figures`, taking `--study=DIR` and `--json`, for the whole Study."
FIGURES_READ_SENTENCE = (
    "The read takes no lock, writes nothing, records no Exposure and does not advance the Write sequence, and it answers while another"
    " writer holds the Study's lock."
)
READ_THROUGH_STATUS_SENTENCE = (
    "A client reads through `status --json`, which takes no lock and writes nothing, and writes only through the documented CLI commands."
)


def test_the_dated_lines_hold_one_line_for_the_figures_read_that_quotes_its_ticket_overrides_the_read_line_says_why_and_names_lines_1_and_15():
    lines = [line for line in section(adr(), "Dated lines").splitlines() if line.startswith("- ")]
    found = [line for line in lines if "chadlis/hypotrail#187" in line]
    assert len(found) == 1, found
    [line] = found
    assert re.match(r"- \d{4}-\d{2}-\d{2}: ", line), line
    assert FIGURES_COMMAND_SENTENCE in line and FIGURES_READ_SENTENCE in line
    assert f"the earlier line it overrides: \"{READ_THROUGH_STATUS_SENTENCE}\"" in line
    outside = line.replace(READ_THROUGH_STATUS_SENTENCE, "").replace(FIGURES_READ_SENTENCE, "")
    assert [s for s in re.split(r"(?<=[.:;])\s+", outside) if "takes no lock and writes nothing" in s], outside  # the reason, in a sentence of its own
    assert "line 1" in line and "line 15" in line
