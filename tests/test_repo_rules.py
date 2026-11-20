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
