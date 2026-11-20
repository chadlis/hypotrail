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
