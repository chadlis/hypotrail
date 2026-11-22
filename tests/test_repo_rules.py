"""Round 1 review of #9 (R1-01, R1-06): the repository rules that a reader can check mechanically."""

import argparse
import re
import subprocess
from pathlib import Path

import pytest

from hypotrail.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent


# The pathspecs that both scans below use, written once.
HANDBOOK_CHAPTERS_PATHSPEC = ":(glob)docs/handbook/chapters/*.html"
TESTS_PATHSPEC = "tests/"

# Every pathspec: chadlis/hypotrail#122, criterion 1.
BARE_ID_SCAN = ["src/", TESTS_PATHSPEC, HANDBOOK_CHAPTERS_PATHSPEC, "README.md"]

# - the Python source and the handbook chapters: chadlis/hypotrail#122, criterion 6.
# - tests/: chadlis/hypotrail#115 and D-043 on chadlis/hypotrail#75.
# - ADR 0004: chadlis/hypotrail#122, Tightened E, from D-044 on chadlis/hypotrail#75, item 5.
GUILLEMET_SCAN = [":(glob)src/**/*.py", HANDBOOK_CHAPTERS_PATHSPEC, TESTS_PATHSPEC, "docs/adr/0004-panel-cli-contract.md"]


def _git_ls_files(pathspecs):
    """The tracked files under the pathspecs, listed by `git ls-files`: an untracked or ignored file is not in the list."""
    try:
        listing = subprocess.run(["git", "ls-files", "-z", "--", *pathspecs], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        pytest.fail(f"`git ls-files` is unavailable, so the tracked files cannot be listed: {error}")
    return sorted(ROOT / name for name in listing.stdout.split("\0") if name and (ROOT / name).is_file())


# This test enforces a stricter form of AGENTS.md's rule on French quotation marks: no opening French quotation
# mark (U+00AB) and no closing one (U+00BB) appears in any file it scans. The code below spells the two characters
# as escapes, because this test scans its own module.
# docs/adr/ beyond ADR 0004 is not scanned: ADR 0002's French quotation marks hold a recorded quotation, and its
# 2026-11-08 note records the harm of rewriting an ADR in place.
# The French string in tests/test_report.py is written as escapes, so the scan keeps no named exception
# (D-044 on chadlis/hypotrail#75, item 6).
def test_no_guillemet_in_the_python_files_under_src_the_handbook_chapters_tests_or_adr_0004():
    found = [str(p.relative_to(ROOT)) for p in _git_ls_files(GUILLEMET_SCAN) if set("\u00ab\u00bb") & set(p.read_text(encoding="utf-8"))]
    assert found == []


def _helps(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                yield from _helps(sub)
        elif action.help:
            yield action.option_strings, action.help


def test_no_help_text_uses_a_word_the_glossary_avoids_for_attempt():
    # GLOSSARY, Attempt: _Avoid_: run, job. `--retry-of` once named the Attempt it repeats with the avoided noun.
    for options, text in _helps(build_parser()):
        assert " run " not in f" {text.lower()} " or "--retry-of" not in options, text


def test_the_comparison_definition_is_unchanged_and_the_agent_rule_is_a_dated_line_beside_it():
    # R1-03: earlier glossary entries add a separate `Clarification, DATE:` line, never an edit inside a definition.
    lines = (ROOT / "GLOSSARY.md").read_text(encoding="utf-8").splitlines()
    at = lines.index("**Comparison**:")
    assert lines[at + 1] == "Two Assessments of the same population, Scorer, units and Mode, aligned Item by Item, with a Control and a Candidate."
    assert lines[at + 2].startswith("Clarification, 2026-11-20: ")


def test_the_readme_status_stays_short():
    # R1-02, AGENTS.md: keep README.md short; the detail belongs in the handbook.
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    status = text.split("## Status\n", 1)[1].split("\n## ", 1)[0]
    assert len(status.split()) <= 200


def test_both_tracks_read_the_memberships_with_the_one_shared_reader():
    # R1-05: the agentic copy split on the first comma, kept empty Partitions and ignored CSV quoting.
    from hypotrail.agentic import imports as agent_imports
    from hypotrail.core import study as layout
    from hypotrail.ml import imports as ml_imports

    assert not hasattr(agent_imports, "_partition_of") and not hasattr(ml_imports, "_partition_of")
    csv_bytes = b'case_id,partition\n"A,1",dev\nB2,\nC3,public_check\n'
    assert layout.partition_of(csv_bytes, "case_id") == {"A,1": "dev", "C3": "public_check"}
    assert layout.partition_of(b"row_id,partition\nr1,train\nr2,\n", "row_id") == {"r1": "train"}


def test_the_readme_claims_the_kept_live_episodes_come_from_spike_live_which_records_nothing_in_a_study():
    # R2-04, R3-02, R3-03, AGENTS.md "short and true": the claim, not its phrasing (#72 B2: `spike live --out DIR` records nothing in a Study).
    import re

    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "A live Attempt" not in text
    paragraph = next(line for line in text.splitlines() if "docs/handbook/traces" in line and not line.startswith("uv run"))  # not the `import agent` command line (#87 D)
    assert "spike live" in paragraph and "Episodes" in paragraph  # where the kept live Episodes come from
    assert re.search(r"\b(?:no|nothing|not)\b[^.;:]*\bStudy\b", paragraph)  # that command records nothing in a Study
    # the README names the kept outputs Episodes; whether a `spike live` execution is an Attempt is open
    # (chadlis/hypotrail#77), so no Attempt here, and no noun the GLOSSARY does not define
    assert not re.search(r"\bAttempts?\b", paragraph) and "spike output" not in paragraph
    # R4-01: the README and chapter 03 name the kept live traces with the same GLOSSARY term, Episodes
    chapter = (ROOT / "docs" / "handbook" / "chapters" / "03-agentic-track.html").read_text(encoding="utf-8")
    assert "live Episodes" in chapter and "live Episodes" in paragraph
    assert "live Attempt" not in chapter and "The live Attempts" not in chapter
    assert re.search(r"^\*\*Episode\*\*:", (ROOT / "GLOSSARY.md").read_text(encoding="utf-8"), re.M)
    assert len(paragraph.split()) <= 100  # short



def test_the_dataset_reference_is_found_by_its_role_for_both_tracks():
    # R3-05: the agentic Track looked it up by role, the regression Track by position; one helper in the core serves both.
    from hypotrail.core import study as layout

    other = {"role": "memberships", "sha256": "a" * 64}
    dataset = {"role": "dataset", "sha256": "b" * 64}
    assert layout.dataset_ref({"dataset_refs": [other, dataset]}) is dataset


def _glossary_attempt_lines():
    lines = (ROOT / "GLOSSARY.md").read_text(encoding="utf-8").splitlines()
    return lines, lines.index("**Attempt**:")


def test_the_attempt_definition_is_unchanged_and_a_dated_line_says_what_is_not_an_attempt():
    # #77, D-011 on chadlis/hypotrail#75 (Tightened A): the definition is not rewritten; the clarification is a separate dated line beside it.
    lines, at = _glossary_attempt_lines()
    assert lines[at + 1] == "One execution or one import of exactly one Configuration on one population, with an identity that is never derived from its inputs."
    clarification = lines[at + 2]
    assert clarification.startswith("Clarification, 2026-11-20: ")
    assert lines[at + 3] == "_Avoid_: run, job, execution record"
    assert "recorded in a Study" in clarification and "manifest" in clarification and "Observation set" in clarification
    assert "`spike live`" in clarification and "`fixture.run_fixture`" in clarification  # the executions that are not Attempts
    assert "run agent --mode llm_live" in clarification  # the command that records the live path as an Attempt
    assert "format values" in clarification and "`mode`" in clarification and "`this_attempt`" in clarification
    # words the GLOSSARY avoids: Mode's `profile`, Attempt's `run` and `execution record`
    assert "--profile" not in clarification and "profile" not in clarification
    assert "execution record" not in clarification and not re.search(r"\brun\b(?! agent)", clarification.replace("`fixture.run_fixture`", ""))
    # the relationships line it must stay consistent with
    assert "- An **Attempt** runs one **Configuration** in one **Mode** and yields exactly one **Observation set**." in lines


def test_the_live_execution_record_comment_does_not_call_a_spike_live_request_an_attempts():
    # #77, D-012 on chadlis/hypotrail#75 item 17: `record_execution` is called by `spike live` and by the library fixture, neither of which records an Attempt.
    from hypotrail.agentic import live

    doc = live.record_execution.__doc__
    assert "this execution's own request" in doc and "this Attempt" not in doc


def test_the_readme_names_an_attempt_only_for_what_a_study_records():
    # #77 AC4, AGENTS.md "short and true": no README sentence calls a `spike live` execution an Attempt.
    sentences = re.split(r"(?<=[.;:])\s+", (ROOT / "README.md").read_text(encoding="utf-8").replace("\n", " "))
    assert [s for s in sentences if "spike live" in s and re.search(r"\bAttempts?\b", s)] == []
    status = next(s for s in sentences if "`run agent` records a Chinook Attempt" in s)
    assert "`init` creates a Study" in status and "`run ml` records a Bike Attempt" in status


def test_no_decision_is_cited_without_its_issue_in_the_source_the_tests_the_chapters_or_the_readme():
    # GLOSSARY cites a Decision as "D-011 on chadlis/hypotrail#75": a bare ID means nothing to a reader. Whitespace is collapsed, as a citation may wrap over two
    # lines. An ID that is the whole of a double-quoted string ("D-025") is a string an assertion looks for, not a citation, wherever it stands.
    bare = []
    for path in _git_ls_files(BARE_ID_SCAN):
        text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
        bare += [
            f"{path.relative_to(ROOT)}: {text[max(0, m.start() - 30):m.end() + 30]}"
            for m in re.finditer(r"D-0\d\d(?! on chadlis/hypotrail#75)", text)
            if not re.fullmatch(r'"D-0\d\d"', text[max(0, m.start() - 1):m.end() + 1])
        ]
    assert bare == []


# --- the Declared deviation: its GLOSSARY entry, and the names of its record, folder and command -------------------------------


def _declared_deviation_entry(text: str) -> list:
    """The lines of the GLOSSARY entry **Declared deviation**, from its heading to the blank line that ends it; [] when no line starts the entry."""
    lines = text.splitlines()
    starts = [at for at, line in enumerate(lines) if line.startswith("**Declared deviation**")]
    if not starts:
        return []
    entry = []
    for line in lines[starts[0]:]:
        if not line.strip():
            break
        entry.append(line)
    return entry


def test_the_glossary_entry_declared_deviation_says_a_derived_deviation_is_not_one_and_avoids_caveat_waiver_limitation_and_warning():
    # D-067 on chadlis/hypotrail#75, point 1: "The entry says in one clause that a derived deviation is a deviation but not a Declared deviation." |
    # "Its _Avoid_ line keeps "caveat, waiver, limitation, warning"." | "B2's ticket carries the test of the entry."
    entry = _declared_deviation_entry((ROOT / "GLOSSARY.md").read_text(encoding="utf-8"))
    assert entry, "no line of GLOSSARY.md starts the entry **Declared deviation**"
    text = " ".join(entry)
    assert "derived deviation" in text and "not a Declared deviation" in text, text
    [avoid] = [line for line in entry if line.startswith("_Avoid_")]
    for word in ("caveat", "waiver", "limitation", "warning"):
        assert word in avoid, (word, avoid)


def _leaf_parsers(parser, path=()):
    """(command line, parser) of every command of the parser that takes no further command."""
    sub = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
    if not sub:
        yield " ".join(path), parser
        return
    for name, child in sub[0].choices.items():
        yield from _leaf_parsers(child, (*path, name))


def test_the_kind_of_the_declared_deviation_record_is_the_glossary_term_and_its_folder_and_its_command_hold_deviation():
    from hypotrail import cli
    from hypotrail.core import contracts

    [heading] = [line for line in _declared_deviation_entry((ROOT / "GLOSSARY.md").read_text(encoding="utf-8")) if line.startswith("**")]
    term = heading.split("**")[1]
    commands = [name for name, parser in _leaf_parsers(build_parser()) if parser.get_default("handler") is cli._deviation]
    assert len(commands) == 1 and "deviation" in commands[0], commands
    kinds = {d["properties"]["kind"].get("const") for d in contracts.schema()["$defs"].values() if "kind" in d.get("properties", {})}
    assert term.lower().replace(" ", "_") in kinds, sorted(k for k in kinds if k)
    from hypotrail.core import deviations

    assert "deviation" in deviations.DEVIATIONS_DIR


def _glossary_entry(text: str, term: str) -> list:
    """The lines of the GLOSSARY entry `term`, from its heading to the blank line that ends it; [] when no line starts the entry."""
    lines = text.splitlines()
    starts = [at for at, line in enumerate(lines) if line.startswith(f"**{term}**")]
    if not starts:
        return []
    entry = []
    for line in lines[starts[0]:]:
        if not line.strip():
            break
        entry.append(line)
    return entry


def test_the_glossary_entry_pending_decision_says_it_is_derived_never_stored_and_not_a_decision_and_avoids_open_decision_and_pending_choice():
    # "#163 gains a criterion for an entry **Pending decision**: a Comparison of the current revision that no applying Decision cites and whose two
    # Assessments have no later Assessment; derived at read, never stored, not a **Decision**." (D-078 on chadlis/hypotrail#75, item 8)
    entry = _glossary_entry((ROOT / "GLOSSARY.md").read_text(encoding="utf-8"), "Pending decision")
    assert entry, "no line of GLOSSARY.md starts the entry **Pending decision**"
    text = " ".join(entry)
    for part in ("no applying Decision cites", "no later Assessment", "never stored", "not a **Decision**"):
        assert part in text, (part, text)
    [avoid] = [line for line in entry if line.startswith("_Avoid_")]
    assert "open decision" in avoid and "pending choice" in avoid, avoid
