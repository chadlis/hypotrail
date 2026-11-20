"""Round 1 review of #9 (R1-01, R1-06): the repository rules that a reader can check mechanically."""

import argparse
from pathlib import Path

from hypotrail.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent


def test_no_french_quotation_in_source_or_handbook():
    # AGENTS.md: everything committed is in English; « » only ever quoted French.
    files = [*(ROOT / "src").rglob("*.py"), *(ROOT / "docs" / "handbook" / "chapters").glob("*.html")]
    found = [str(p.relative_to(ROOT)) for p in files if "«" in p.read_text(encoding="utf-8") or "»" in p.read_text(encoding="utf-8")]
    assert found == []


def _helps(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                yield from _helps(sub)
        elif action.help:
            yield action.option_strings, action.help


def test_no_help_text_uses_a_word_the_glossary_avoids_for_attempt():
    # GLOSSARY, Attempt: _Avoid_: run, job. `--retry-of` once said "the Attempt this run repeats".
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


def test_the_core_imports_no_track():
    # R1-04, ADR 0001, core/comparison.py docstring: the core never imports hypotrail.agentic or hypotrail.ml.
    import ast

    offenders = []
    for path in sorted((ROOT / "src" / "hypotrail" / "core").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            if isinstance(node, ast.ImportFrom) and node.module == "hypotrail":
                names = [f"hypotrail.{a.name}" for a in node.names]
            offenders += [f"{path.name}: {n}" for n in names if n.startswith(("hypotrail.agentic", "hypotrail.ml"))]
    assert offenders == []


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
    paragraph = next(line for line in text.splitlines() if "docs/handbook/traces" in line)
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
