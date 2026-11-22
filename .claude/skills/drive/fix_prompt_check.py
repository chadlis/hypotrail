#!/usr/bin/env python3
"""PreToolUse hook on the Agent tool (D-055 on chadlis/hypotrail#75, item 1). It warns and never blocks.

It acts only on a prompt that contains "This is a review fix", or that reads "Read <absolute path> and do exactly what it
says" for a file that contains it. It then runs two checks and the premise sheet (`premises.py`), and lets the call through. Its
findings go to the model as `hookSpecificOutput.additionalContext`: the hooks reference says that a PreToolUse
`additionalContext` is added to Claude's context beside the tool result, while `systemMessage` is a warning
shown to the user and is not given to the model. The drive posts the findings beside the prompt.

1. Quotations. A quotation that the prompt attributes (a `#n`, `D-nnn`, `Tightened`, `c<n>`, `Q<n>`, `ADR n` or `.md`
   file, or "says"/"asks", within 70 characters before it) must be found word for word in a source, and must be a
   whole sentence or list item of it. A quotation that elides words with "…" is partial by declaration.
2. Finding IDs. A review-fix prompt names the IDs of the findings it fixes. The check lists the IDs it finds, or says
   that there is none.

The sources are the tracked `.md` and `.py` files of the worktree that the prompt names ("Work in <path>"), and the
bodies and comments of chadlis/hypotrail#75 and of every issue the prompt names, read with `gh api`. When
`HYPOTRAIL_PROMPT_SOURCES` names a directory, its `*.md` files replace the GitHub reads. An unreadable source is a
warning: a quotation that no readable source holds is then reported as unchecked, not as missing.

An error of the hook itself is a warning too, and the call goes through: this is the one hook of the apparatus that
does not fail closed.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

TRIGGER = "This is a review fix"
REPOSITORY = "chadlis/hypotrail"
DECISION_LOG = 75
LEAD = 70
MIN_WORDS = 3
CONTEXT_LIMIT = 9000
HERE = Path(__file__).resolve().parent
DECISION_CUE = re.compile(r"#\d+|D-\d+|Tightened|\bc\d\b|\bQ\d|\bADR \d+")
TEXT_CUE = re.compile(r"\.md\b|\bsays?\b|\basks?\b")
ELISION = re.compile(r"\u2026|(?<=\s)\.\.\.(?=\s|$)|(?<=\w)\.\.\.$")
FINDING_ID = re.compile(r"\b[A-Z]\d+[a-z]?-[A-Z]-\d{2}\b")
SENTENCE_START = re.compile(r'(^|[.:;!?]\s|[-*>|]\s|\d\.\s|\(|"|«\s?)$')


def normalise(text: str) -> str:
    text = text.replace("**", "").replace("“", '"').replace("”", '"').replace("’", "'")
    return re.sub(r"\s+", " ", text)


def tracked_texts(worktree: Path) -> list:
    """[(`repo:<path>`, text)] for every tracked `.md` and `.py` file of the worktree."""
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.md", "*.py"], cwd=worktree, capture_output=True, text=True, check=True
    )
    texts = []
    for name in filter(None, listing.stdout.split("\0")):
        path = worktree / name
        if path.is_file():
            texts.append((f"repo:{name}", path.read_text(encoding="utf-8", errors="ignore")))
    return texts


def gh_json(arguments: list) -> list:
    done = subprocess.run(["gh", "api", *arguments], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(done.stdout)


def github_comments(number: int) -> list:
    done = subprocess.run(
        ["gh", "api", f"repos/{REPOSITORY}/issues/{number}/comments", "--paginate", "--slurp"],
        capture_output=True, text=True, timeout=120, check=True,
    )
    return [(f"issue-{number}-comment-{comment['id']}", comment["body"] or "") for page in json.loads(done.stdout) for comment in page]


def github_texts(numbers: list) -> list:
    """[(`issue-<n>-body` or `issue-<n>-comment-<id>`, text)]: the body of every issue but the decision log, and every comment."""
    texts = []
    for number in numbers:
        if number != DECISION_LOG:
            texts.append((f"issue-{number}-body", gh_json([f"repos/{REPOSITORY}/issues/{number}"])["body"] or ""))
        texts += github_comments(number)
    return texts


def is_firsthand(name: str) -> bool:
    """A body, a file, or a comment of the decision log is a source. A comment of another issue is a record (a report, a routing table, a prompt) that may itself quote a source in part."""
    match = re.fullmatch(r"issue-(\d+)-comment-\d+", name)
    return not match or int(match.group(1)) == DECISION_LOG


def named_issues(prompt: str) -> list:
    numbers = {DECISION_LOG}
    numbers.update(int(n) for n in re.findall(r"(?:chadlis/hypotrail)?#(\d+)\b", prompt))
    return sorted(numbers)


def quotations(prompt: str) -> list:
    """The attributed quotations of the prompt, as (kind, text): each `>` list item, and each inline double-quoted string of at least three words with an attribution within 70 characters before it.

    The kind says what is quoted: `decision` (a decision-log entry, a Tightened line, a ticket or ADR sentence), `text` (the sentence of a file or a rule, introduced by its `.md` file, "says" or "asks") or `block`.
    A quotation of a decision is a whole item; any other quotation only has to be word for word."""
    found = []
    block = []
    for line in prompt.splitlines() + [""]:
        stripped = line.strip()
        if stripped.startswith(">"):
            block.append(stripped.lstrip(">").strip())
            continue
        if block:
            for item in re.split(r"\s(?=\d+\. |- )", " ".join(part for part in block if part)):
                item = re.sub(r"^(\d+\. |- )", "", item).strip()
                if item:
                    found.append(("block", item))
            block = []
        for match in re.finditer(r'"([^"\n]+)"', line):
            lead = line[max(0, match.start() - LEAD):match.start()]
            if len(match.group(1).split()) >= MIN_WORDS and DECISION_CUE.search(lead):
                found.append(("decision", match.group(1)))
            elif len(match.group(1).split()) >= MIN_WORDS and TEXT_CUE.search(lead):
                found.append(("text", match.group(1)))
    return found


def is_whole(corpus: list, piece: str, first: bool, last: bool) -> bool:
    for text in corpus:
        at = text.find(piece)
        while at != -1:
            before = text[max(0, at - 3):at]
            after = text[at + len(piece):at + len(piece) + 2]
            starts = not first or at == 0 or bool(SENTENCE_START.search(before))
            ends = not last or piece.endswith((".", ";", ":", "?", "!")) or after[:1] in ("", ".", "|") or after.startswith((" -", " |"))
            if starts and ends:
                return True
            at = text.find(piece, at + 1)
    return False


def check_quotation(corpus: list, kind: str, quotation: str, complete: bool) -> str | None:
    """None when the quotation is word for word in a source, and for a decision or a block a whole sentence or item of it; otherwise why it is not.

    The corpus is [(name, normalised text)]. Wholeness is judged against the sources themselves. A quotation that only a record holds (a comment of another issue) is not judged.
    """
    pieces = [piece.strip() for piece in ELISION.split(normalise(quotation))]
    elided = len(pieces) > 1
    pieces = [piece for piece in pieces if piece]
    for piece in pieces:
        if not any(piece in text for _, text in corpus):
            return "not found word for word in a source" if complete else "unchecked: a source could not be read"
    if kind == "text":
        return None
    if elided:
        return 'elided with "…": a quotation is a whole sentence or item'
    firsthand = [text for name, text in corpus if is_firsthand(name)]
    if any(pieces[0] in text for text in firsthand) and not is_whole(firsthand, pieces[0], True, True):
        return "word for word, but not a whole sentence or item of its source"
    return None


def check_quotations(prompt: str, corpus: list, complete: bool = True) -> list:
    corpus = [(name, normalise(text)) for name, text in corpus]
    warnings = []
    for kind, quotation in quotations(prompt):
        why = check_quotation(corpus, kind, quotation, complete)
        if why:
            warnings.append(f"quotation ({kind}) {why}: {quotation[:110]!r}")
    return warnings


def check_finding_ids(prompt: str) -> tuple:
    """(the finding IDs the prompt names, the warnings): a review-fix prompt names the IDs of the findings it fixes."""
    ids = sorted(set(FINDING_ID.findall(prompt)))
    return ids, ([] if ids else ["finding IDs: the prompt names none"])


def pointed_file_text(prompt: str) -> str | None:
    for token in re.findall(r"\bRead\s+(/[\w./~@+-]+?)[.,;:)]?\s+and do exactly what it says", prompt):
        path = Path(token.rstrip(".,;:)"))
        try:
            if path.is_file() and path.stat().st_size <= 1_000_000:
                text = path.read_text(encoding="utf-8")
                if TRIGGER in text:
                    return text
        except (OSError, UnicodeDecodeError):
            continue
    return None


def review_fix_text(prompt: str) -> str | None:
    """The text to check: the prompt when it contains the trigger, else the text of the file that a prompt of the form "Read <path> and do exactly what it says" points to when that file contains it, else None."""
    if TRIGGER in prompt:
        return prompt
    return pointed_file_text(prompt)


def worktree_of(text: str) -> Path:
    match = re.search(r"Work in (/[^\s(),;]+)", text)
    if match and Path(match.group(1)).is_dir():
        return Path(match.group(1))
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def sources(text: str, worktree: Path) -> tuple:
    """([(name, text)], whether every source could be read, the reasons it could not)."""
    texts, missing = [], []
    try:
        texts += tracked_texts(worktree)
    except (OSError, subprocess.SubprocessError) as error:
        missing.append(f"repository files of {worktree}: {error}")
    override = os.environ.get("HYPOTRAIL_PROMPT_SOURCES")
    if override:
        texts += [(path.stem, path.read_text(encoding="utf-8")) for path in sorted(Path(override).glob("*.md"))]
    else:
        try:
            texts += github_texts(named_issues(text))
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            missing.append(f"GitHub issues: {error}")
    return texts, not missing, missing


def premise_sheet(text: str, worktree: Path) -> list:
    done = subprocess.run(
        [sys.executable, "-I", str(HERE / "premises.py"), "-", str(worktree)],
        input=text, capture_output=True, text=True, timeout=120,
    )
    lines = (done.stdout + done.stderr).strip().splitlines()
    return ([f"premise sheet exited {done.returncode}:"] if done.returncode else []) + lines


def report(text: str) -> str:
    worktree = worktree_of(text)
    texts, complete, missing = sources(text, worktree)
    warnings = [f"source not read: {reason}" for reason in missing]
    warnings += check_quotations(text, texts, complete)
    ids, id_warnings = check_finding_ids(text)
    warnings += id_warnings
    sheet = premise_sheet(text, worktree)
    head = f"Fix-prompt check (warns only, the call goes through): {len(warnings)} warning(s). Finding IDs named: {', '.join(ids) or 'none'}."
    body = [f"- {warning}" for warning in warnings] + (["", "Premise sheet:", *sheet] if sheet else [])
    return "\n".join([head, *body])


def emit(context: str):
    if len(context) > CONTEXT_LIMIT:
        context = context[:CONTEXT_LIMIT] + "\n[cut]"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": context}}))


def main() -> int:
    try:
        prompt = json.load(sys.stdin)["tool_input"]["prompt"]
        text = review_fix_text(prompt) if isinstance(prompt, str) else None
        if text is not None:
            emit(report(text))
    except Exception as error:
        emit(f"Fix-prompt check failed and did not check the prompt ({type(error).__name__}: {error}). The call goes through.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
