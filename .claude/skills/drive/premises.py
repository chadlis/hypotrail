#!/usr/bin/env python3
"""The premise sheet of a fix prompt (D-055 on chadlis/hypotrail#75, item 2).

Usage: python3 -I premises.py <prompt file, or - for stdin> [worktree]

A fix prompt that says who calls a function carries a line

    callers(<package.module.function>) = {<package.module:function>, ...}

This script compares each such line with the callers that `tests/_architecture.py` (the repository's one resolver)
finds in `src/` of the worktree, and prints one sheet line per function. The sheet lists only the functions the prompt
makes a claim about: those of a `callers(...)` line, and those named in a sentence of the form "called from ... only".

Exit 2 when a `callers(...)` line differs from the resolver, when it names a function that `src/` neither defines nor
calls, when a "called from ... only" sentence has no `callers(...)` line for any function it names, and on any error
of the script itself.
"""

import re
import sys
from pathlib import Path

CALLERS_LINE = re.compile(r"callers\(\s*([\w.]+)\s*\)\s*=\s*\{([^}]*)\}")
CLAIM_SENTENCE = re.compile(r"\bcalled\s+from\b.*\bonly\b", re.IGNORECASE | re.DOTALL)


def load_resolver(worktree: Path):
    sys.path.insert(0, str(worktree / "tests"))
    import _architecture

    return _architecture, _architecture.parse_all(worktree / "src")


def callers_of(architecture, trees: dict, function: str) -> set:
    """The `module:function` of every function of `src/` that calls `function` (a dotted name), by the resolver."""
    return {site.innermost for site in architecture.calls(trees) if site.callee == function}


def claimed_sets(prompt: str) -> dict:
    claims = {}
    for function, members in CALLERS_LINE.findall(prompt):
        claims[function] = {member.strip() for member in members.split(",") if member.strip()}
    return claims


def sentences(prompt: str) -> list:
    return [part for part in re.split(r"(?<=[.;:])\s+|\n\s*\n", prompt) if part.strip()]


def unbacked_claims(prompt: str, claims: dict) -> list:
    """The sentences of the form "called from ... only" that name no function with a `callers(...)` line."""
    claimed_names = {name.rsplit(".", 1)[-1] for name in claims}
    unbacked = []
    for sentence in sentences(prompt):
        if CALLERS_LINE.search(sentence) or not CLAIM_SENTENCE.search(sentence):
            continue
        named = {name.rstrip("()").rsplit(".", 1)[-1] for name in re.findall(r"`([\w.]+(?:\(\))?)`", sentence)}
        if not named & claimed_names:
            unbacked.append(" ".join(sentence.split()))
    return unbacked


def sheet(prompt: str, worktree: Path) -> tuple:
    """(the sheet lines, whether the prompt passes)."""
    claims = claimed_sets(prompt)
    lines, passes = [], True
    for sentence in unbacked_claims(prompt, claims):
        lines.append(f"- NO callers(...) LINE for the claim: {sentence[:160]!r}")
        passes = False
    if not claims:
        return lines, passes
    architecture, trees = load_resolver(worktree)
    defined = architecture.defined_functions(trees)
    used = {site.callee for site in architecture.calls(trees)}
    for function, claimed in sorted(claims.items()):
        if function not in defined and function not in used:
            lines.append(f"- callers({function}): NOT DEFINED AND NEVER CALLED in src/")
            passes = False
            continue
        found = callers_of(architecture, trees, function)
        shown = ", ".join(sorted(found)) or "nothing"
        if found == claimed:
            lines.append(f"- callers({function}) = {{{shown}}}: as claimed")
        else:
            lines.append(
                f"- callers({function}) = {{{shown}}}: DIFFERS from the claim; "
                f"claimed but not found: {sorted(claimed - found) or 'none'}; found but not claimed: {sorted(found - claimed) or 'none'}"
            )
            passes = False
    return lines, passes


def main(argv: list) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        prompt = sys.stdin.read() if argv[1] == "-" else Path(argv[1]).read_text(encoding="utf-8")
        worktree = Path(argv[2] if len(argv) == 3 else ".").resolve()
        lines, passes = sheet(prompt, worktree)
    except Exception as error:
        print(f"premises.py failed ({type(error).__name__}: {error}); nothing is checked", file=sys.stderr)
        return 2
    if lines:
        print("## Premise sheet")
        print("\n".join(lines))
    return 0 if passes else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
