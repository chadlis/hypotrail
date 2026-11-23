#!/usr/bin/env python3
"""PreToolUse hook before a merge (D-055 on chadlis/hypotrail#75, item 3). It fails closed: any error exits 2.

It acts on the tool `mcp__github__merge_pull_request`, and on a Bash command that runs `gh pr merge` or
`gh api -X PUT .../pulls/<n>/merge` (a GET of that path is no merge). The whole command string is searched: quoted text and heredoc
bodies are not commands, and a merge behind `env`, `timeout`, `bash -c` or `eval` is found. A merge whose number cannot be read is refused ("name the pull request number"). Every `gh` call it makes ends after `GH_TIMEOUT` seconds.
A merge is refused (exit 2, the reasons on stderr) while any of these is missing
for the slice issue of the pull request:

1. the state comment's round count (`Review rounds used: N of 5`) equals the number of rounds that have a review of record;
2. each round that has a review of record has a "round <r>: routing" comment;
3. when a routing comment of round 5 or later routes a row as documentation, each axis of that row has a
   "round <r>: <axis> verification" comment (the documentation path of the skill);
4. a "closing register" comment exists and names every finding ID that a routing table assigned;
5. each routing row that promises a line in the PR body ("PR body") and is neither refuted, out of scope, a duplicate nor
   fixed has its ID in the PR body. The status of an ID is the one of the latest routing or closing register comment that lists it: the closing register
   when there is one, the routing row otherwise. A fix prompt or a report settles no row;
6. when a requirement has row-1 findings in two rounds, the routing comment of the second of those rounds, or of a later
   round, has a line "Structural option for <requirement>: ..." or "Gate for <requirement>: D-nnn" (D-061 on
   chadlis/hypotrail#75, as amended by D-063 on chadlis/hypotrail#75, item 2: "`check_record.py` counts, for each
   requirement, the rounds that had row-1 findings. At two such rounds, it refuses the merge unless a structural option
   or a gate decision is recorded."). The requirement of a row is its requirement cell up to its first ": " (a colon
   followed by a space), with the word "Tightened" dropped and whitespace collapsed, so "#142 Tightened B" and "#142 B"
   are one requirement; line numbers and URLs are kept whole. A row counts for the round of the routing comment that
   lists it when its row cell starts with "1" and its status there is not settled. A row carried open into a later
   round's table counts for that round too: a blocker a fix left open is a blocker in the next round. A clearing line
   has text after its ": ", and a gate line names a decision. The rule judges every slice record, one merged before it
   was added included: F1's record (chadlis/hypotrail#121) fails it on "#142 B" and on "`slice-builder.md:11`".
   Rule 6 is a backstop to the drive's own count of rounds per requirement, which stays the rule. Its key is textual,
   with these stated limits: two different rules cited from one file under the same text before ": " ("`AGENTS.md`")
   get one key; two spans of one comment block ("decisions.py:30-31" and ":28-31") get two keys; "#142 B (Tightened)"
   and "#142 B" get two keys; and any text after a clearing line's ": " clears it. When it refuses two requirements
   that are not one, the routing comment says so in the clearing form, with the reason: "Structural option for <key>:
   not one requirement, because ...".
7. is held for D-065 on chadlis/hypotrail#75, item 1: "`check_record.py` rule 7 is not added; revisit it if a later
   record shows a requirement cell worded by the drive."
8. each routing comment has four lines, each starting with its label and giving a value after it (D-065 on
   chadlis/hypotrail#75, item 4: "Each routing comment carries `Models:`, `Telemetry:`, `Refusals:` and `Interruptions:`,
   and each label needs a value."). `unknown` is a value of `Models:` and `Telemetry:`; `Refusals:` and `Interruptions:`
   say `none` or list the entries, after the label or as list items on the lines right under it, and a value whose
   first word is `unknown`, backticks aside, is refused for them. The rule skips the slices merged before it was added,
   which `MERGED_BEFORE_ROUND_LINES` lists, F1's (chadlis/hypotrail#121) the last of them: their routing comments lack
   the lines. Its limits: it reads the lines as text, so any value passes `Models:` and `Telemetry:`, any value but
   `unknown` counts as a list, and four `unknown` lines pass while giving the re-evaluation of the round cap no data;
   and only the first line that carries a label is read.
9. each comment of the slice issue or of one of its sub-issues whose first line names the drive ("the drive", "the drive's")
   has its ID in the slice's chadlis/hypotrail#75 entry: a comment of #75 whose first line holds "drive decision
   (delegated)" and whose ID the state comment holds (D-076 on chadlis/hypotrail#75, item 2: "**add** `check_record.py`
   rule 9: the merge is refused while a comment of the slice issue or of a sub-issue whose first line names the drive is
   absent from that entry; slices merged before it are skipped."). The rule skips the slices merged before it was added,
   which `MERGED_BEFORE_DELEGATED_ENTRY` lists, T1's (chadlis/hypotrail#150) the last of them, and reads neither their
   sub-issues nor #75. Its limits: it relies on the convention that a delegated choice's comment has a first line that
   names the drive, so a drive decision under a heading that does not name the drive is not seen; and it checks only
   that each such comment's ID is in the entry, not that the slice has one entry, that the entry has its own D-number,
   that it was posted before the closing register or never edited, or that each item names its case.
10. each round that a later round follows has a comment of the slice issue whose first line holds "round <r>" and
   "fix prompt": a correction opens the next round, and its prompt is posted word for word, or the round is cleared under
   the heading "## <slice>, round <r>: fix prompt: none, because ..." when no `slice-builder` prompt corrected it (D-082
   on chadlis/hypotrail#75, item 2: "**add** the fixed heading of a fix prompt, and `check_record.py` rule 10, which
   refuses a merge while a corrected round has no such comment;"). The rule skips the slices merged before it was added,
   which `MERGED_BEFORE_FIX_PROMPT_RULE` lists, L2.3's (chadlis/hypotrail#159) the last of them. Its limits: it reads
   headings, so it does not check that the comment is the prompt word for word, that it carries `premises.py`'s sheet,
   that a "none, because" reason is true, or that a correction after the last round has one.

The slice issue is the one the squash subject ends with ("(#<n>)"), or the one the PR body names ("Part of #<n>",
"Slice ... (#<n>)"). A pull request is an apparatus pull request when its title starts with "drive:", it changes no file under
`src/` or `examples/`, and no slice issue can be found for it; the hook lets it through with a note. When a slice issue is found, the
record check applies, whatever the title.

Stated limits: the merge detection reads the text of the command, so it does not see a merge whose pull request number is passed
through `xargs`, or whose command words are built in a variable or in a script it does not open. A gap found only by planting a
command built to evade it is a stated limit. A gap that the drive actually uses is a defect.
The record check of one merge makes five `gh` calls plus one per ticket of the slice (three for a slice that rule 9 skips),
each capped at `GH_TIMEOUT` seconds, so the hook's 180 s timeout in `.claude/settings.json` covers a slice of at most 4 tickets
when every call takes its full cap. Past that, the hook can time out, and a timed-out hook blocks the merge: it fails closed.
"""

import json
import re
import subprocess
import sys

REPOSITORY = "chadlis/hypotrail"
PRODUCT = ("src/", "examples/")
FINDING_ID = re.compile(r"\b[A-Z]\d+[a-z]?-[A-Z]-\d{2}\b")
ROUND_LIMIT = 5
GH_TIMEOUT = 20


class Refusal(Exception):
    pass


def is_apparatus(title: str, files: list, body: str, subject: str | None) -> bool:
    return title.startswith("drive:") and not any(name.startswith(PRODUCT) for name in files) and not slice_numbers(body, subject)


def slice_numbers(body: str, subject: str | None) -> set:
    found = set()
    if subject:
        found.update(int(n) for n in re.findall(r"\(#(\d+)\)\s*$", subject.strip()))
    found.update(int(n) for n in re.findall(r"\bPart of #(\d+)", body))
    found.update(int(n) for n in re.findall(r"\bSlice\b[^\n(]*\(#(\d+)\)", body))
    return found


def first_line(comment: dict) -> str:
    return (comment["body"] or "").lstrip().splitlines()[0] if (comment["body"] or "").strip() else ""


def rows_of(comment: dict) -> list:
    """The rows of the routing table of a comment, as (ID cell, round, axis, requirement, row, status, evidence)."""
    rows = []
    for line in (comment["body"] or "").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 7 and FINDING_ID.search(cells[0]):
            rows.append(tuple(cells[:7]))
    return rows


SETTLED = r"(refuted|out of scope|duplicate|fixed|withdrawn)"


def latest_statuses(comments: list) -> dict:
    """The status text of each finding ID in the latest routing or closing register comment that lists it: the routing cell, or the words after the ID up to the next ID or line end."""
    statuses = {}
    for comment in comments:
        head = first_line(comment)
        if not (re.search(r"\bround \d+\b[:,]? routing", head) or re.search(r"closing register", head, re.IGNORECASE)):
            continue
        body = comment["body"] or ""
        for cells in rows_of(comment):
            for finding in FINDING_ID.findall(cells[0]):
                statuses[finding] = cells[5]
        if rows_of(comment):
            continue
        for line in body.splitlines():
            marks = list(FINDING_ID.finditer(line))
            for here, after in zip(marks, marks[1:] + [None]):
                statuses[here.group()] = line[here.end() : after.start() if after else len(line)]
    return statuses


def requirement_key(text: str) -> str:
    """A requirement cell, or the requirement a clearing line names, reduced to the requirement: up to its first ": ", without "Tightened"."""
    text = re.sub(r"\bTightened\b", "", text.split(": ", 1)[0])
    return re.sub(r"\s+", " ", text).strip()


CLEARING = re.compile(r"^[\s#>*-]*(?:Structural option for (?P<option>.+?): \S|Gate for (?P<gate>.+?): D-\d+)")


def unconverged(routed: dict) -> list:
    """The requirements with row-1 findings in two rounds whose routing comment of the second round, or of a later one, has no line that names a structural option or a gate decision for them."""
    rounds = {}
    for number, comment in routed.items():
        for cells in rows_of(comment):
            if cells[4].strip().startswith("1") and not re.match(rf"[\W_]*{SETTLED}", cells[5], re.IGNORECASE):
                rounds.setdefault(requirement_key(cells[3]), set()).add(number)
    cleared = {}
    for number, comment in routed.items():
        for line in (comment["body"] or "").replace("**", "").splitlines():
            match = CLEARING.match(line)
            if match:
                key = requirement_key(match.group("option") or match.group("gate"))
                cleared.setdefault(key, set()).add(number)
    found = []
    for key, numbers in sorted(rounds.items()):
        if len(numbers) >= 2:
            second = sorted(numbers)[1]
            if not any(number >= second for number in cleared.get(key, ())):
                found.append(
                    f"requirement {key!r} has row-1 findings in rounds {', '.join(map(str, sorted(numbers)))}, and no routing comment of round {second} "
                    f"or later has a line 'Structural option for {key}: ...' or 'Gate for {key}: D-nnn'"
                )
    return found


MERGED_BEFORE_ROUND_LINES = frozenset({6, 7, 8, 9, 10, 56, 60, 80, 93, 104, 119, 120, 121, 138})
ROUND_LABELS = ("Models:", "Telemetry:", "Refusals:", "Interruptions:")
KNOWN_TO_THE_DRIVE = ("Refusals:", "Interruptions:")
DECISION_LOG = 75
DRIVE_HEADING = re.compile(r"\bthe drive(?:'s)?\b", re.IGNORECASE)
DELEGATED_ENTRY = re.compile(r"\bdrive decision \(delegated\)", re.IGNORECASE)
MERGED_BEFORE_DELEGATED_ENTRY = frozenset({6, 7, 8, 9, 10, 56, 60, 80, 93, 104, 119, 120, 121, 138, 150})
FIX_PROMPT = re.compile(r"\bround (\d+)\b[:,]? [^\n]*?\bfix prompt\b", re.IGNORECASE)
MERGED_BEFORE_FIX_PROMPT_RULE = MERGED_BEFORE_DELEGATED_ENTRY | {159}


def round_line_problems(number: int, comment: dict) -> list:
    """The reasons the routing comment of round `number` lacks one of the four round lines, or says `unknown` where the drive knows the value."""
    lines = (comment["body"] or "").replace("**", "").splitlines()
    found = []
    for label in ROUND_LABELS:
        value = None
        for at, line in enumerate(lines):
            match = re.match(rf"[\s>*-]*{label}[ \t]*(.*)$", line)
            if match:
                value = match.group(1).strip()
                below = lines[at + 1] if at + 1 < len(lines) else ""
                if not value and re.match(r"\s*[-*]\s+\S", below) and not re.match(rf"[\s>*-]*(?:{'|'.join(ROUND_LABELS)})", below):
                    value = "a list"
                break
        if not value:
            found.append(f"round {number}: the routing comment has no line '{label} <value>'")
        elif label in KNOWN_TO_THE_DRIVE and re.match(r"unknown\b", value.replace("`", ""), re.IGNORECASE):
            found.append(f"round {number}: the routing comment's '{label}' line says unknown; it says none or lists them")
    return found


def state_comments(comments: list) -> list:
    return [c for c in comments if re.match(r"##.*\bstate\b", first_line(c), re.IGNORECASE) and not re.search(r"\bround \d", first_line(c))]


def unlisted_decisions(comments: list, tickets: dict, log: list, slice_number: int | None) -> list:
    """The comments of the slice issue and of its sub-issues whose first line names the drive and whose ID the slice's delegated entry does not hold.

    The entry is each comment of the log whose first line holds "drive decision (delegated)" and whose ID a state comment holds."""
    linked = "\n".join(c["body"] or "" for c in state_comments(comments))
    entries = "\n".join(c["body"] or "" for c in log if DELEGATED_ENTRY.search(first_line(c)) and re.search(rf"\b{c['id']}\b", linked))
    return [
        f"comment {c['id']} on #{number} names the drive in its first line, and the slice's #{DECISION_LOG} entry labelled 'drive decision (delegated)', linked from the state comment, does not list it"
        for number, issue_comments in [(slice_number, comments), *sorted(tickets.items())]
        for c in issue_comments
        if DRIVE_HEADING.search(first_line(c)) and not re.search(rf"\b{c['id']}\b", entries)
    ]


def unposted_fix_prompts(comments: list, reviewed: set) -> list:
    """The rounds followed by another whose correction has no fix-prompt comment on the slice issue."""
    prompted = {int(m.group(1)) for c in comments for m in [FIX_PROMPT.search(first_line(c))] if m}
    return [
        f"round {r} is followed by round {r + 1}, and no comment headed 'round {r}: fix prompt' holds the prompt of its correction"
        for r in sorted(reviewed)
        if r + 1 in reviewed and r not in prompted
    ]


def problems(pr_body: str, comments: list, slice_number: int | None = None, tickets: dict | None = None, log: list | None = None) -> list:
    """The reasons the record of a slice is incomplete: one string each; empty when it is complete.

    `tickets` maps each sub-issue of the slice issue to its comments, and `log` holds the comments of the decision log."""
    reviewed = {int(m.group(1)) for c in comments for m in [re.search(r"\bround (\d+)\b[:,]? [^\n]*?\baxis \(review of record", first_line(c))] if m}
    routed = {int(m.group(1)): c for c in comments for m in [re.search(r"\bround (\d+)\b[:,]? routing", first_line(c))] if m}
    found = []
    if not reviewed:
        return ["no review of record is posted: no comment of the form 'round <r>: <axis> axis (review of record ...'"]

    states = state_comments(comments)
    counts = [int(m.group(1)) for c in states for m in [re.search(r"Review rounds(?: used)?:\**\s*(\d+) of %d" % ROUND_LIMIT, c["body"])] if m]
    if not counts:
        found.append("the state comment has no line 'Review rounds used: N of 5'")
    elif counts[-1] != len(reviewed):
        found.append(f"the state comment says {counts[-1]} of {ROUND_LIMIT} review rounds, and {len(reviewed)} have a review of record")

    for number in sorted(reviewed - set(routed)):
        found.append(f"round {number} has a review of record and no 'round {number}: routing' comment")

    statuses = latest_statuses(comments)
    ids = []
    for number, comment in sorted(routed.items()):
        for cells in rows_of(comment):
            ids += FINDING_ID.findall(cells[0])
            axes = {w for w in ("Standards", "Spec") if w in cells[2]} or ({"Standards", "Spec"} if "both" in cells[2].lower() else set())
            if number >= ROUND_LIMIT and "documentation" in cells[4].lower():
                for axis in sorted(axes):
                    pattern = rf"\bround {number}\b.*\b{axis}\b.*\bverification|\bround {number}\b.*\bverification.*\b{axis}\b"
                    if not any(re.search(pattern, first_line(c), re.IGNORECASE) for c in comments):
                        found.append(f"round {number}, documentation path ({cells[0]}): no 'round {number}: {axis} verification' comment")
            promised = re.search(r"\bPR body\b", " ".join(cells[3:]))
            if promised:
                for finding in FINDING_ID.findall(cells[0]):
                    if not re.match(rf"[\W_]*{SETTLED}", statuses[finding], re.IGNORECASE) and finding not in pr_body:
                        found.append(f"{finding} promises a line in the PR body, and the PR body does not name it")

    found += unconverged(routed)
    if slice_number not in MERGED_BEFORE_ROUND_LINES:
        for number, comment in sorted(routed.items()):
            found += round_line_problems(number, comment)
    if slice_number not in MERGED_BEFORE_DELEGATED_ENTRY:
        found += unlisted_decisions(comments, tickets or {}, log or [], slice_number)
    if slice_number not in MERGED_BEFORE_FIX_PROMPT_RULE:
        found += unposted_fix_prompts(comments, reviewed)

    registers = [c for c in comments if re.search(r"closing register", first_line(c), re.IGNORECASE)]
    if not registers:
        found.append("no closing register comment")
    else:
        text = "\n".join(c["body"] or "" for c in registers)
        missing = sorted({i for i in ids if i not in text})
        if missing:
            found.append(f"the closing register does not list: {', '.join(missing)}")
    return list(dict.fromkeys(found))


def gh(arguments: list):
    done = subprocess.run(["gh", "api", *arguments], capture_output=True, text=True, timeout=GH_TIMEOUT)
    if done.returncode:
        raise Refusal(f"`gh api {' '.join(arguments)}` failed: {done.stderr.strip()}")
    return json.loads(done.stdout)


def gh_pages(path: str) -> list:
    return [item for page in gh([path, "--paginate", "--slurp"]) for item in page]


SEPARATORS = re.compile(r"&&|\|\||[;|\n()`]|(?<![<>])&(?!>)")
SHELLS = ("bash", "sh", "zsh", "dash", "ksh")
KEYWORDS = ("if", "then", "else", "elif", "do", "while", "until", "!", "{", "time", "command", "exec", "builtin", "nohup", "setsid", "sudo")
GH_VALUE_FLAGS = ("-R", "--repo", "--hostname")
API_VALUE_FLAGS = ("-X", "--method", "-f", "-F", "--field", "--raw-field", "-H", "--header", "--input", "-q", "--jq", "-t", "--template", "--cache", "--preview", "-p")
MERGE_VALUE_FLAGS = ("-t", "--subject", "-b", "--body", "-F", "--body-file", "-A", "--author-email", "--match-head-commit")
NUMBER_UNREADABLE = "name the pull request number"


def masked(command: str) -> tuple:
    """(the command with the text of quotes and heredoc bodies replaced by `_`, the command with only the heredoc bodies blanked).

    The first is where the shell syntax is read, the second where the words are. The text of a `$(...)` inside double quotes stays live."""
    out, blank, modes, pending, i = [], [], ["n"], [], 0
    heredoc = re.compile(r"<<(-?)[ \t]*(?:'([^']*)'|\"([^\"]*)\"|\\?([\w.-]+))")
    while i < len(command):
        char, mode = command[i], modes[-1]
        if char == "\\":
            out.append("_" * len(command[i : i + 2]))
            i += 2
        elif mode == "dq" and char == '"':
            modes.pop()
            out.append(char)
            i += 1
        elif mode != "dq" and char == "'":
            end = command.find("'", i + 1)
            if end < 0:
                out.append("'" + "_" * (len(command) - i - 1))
                i = len(command)
            else:
                out.append("'" + "_" * (end - i - 1) + "'")
                i = end + 1
        elif mode != "dq" and char == '"':
            modes.append("dq")
            out.append(char)
            i += 1
        elif command.startswith("$(", i):
            modes.append("cs")
            out.append("$(")
            i += 2
        elif mode == "cs" and char == ")":
            modes.pop()
            out.append(char)
            i += 1
        elif mode == "dq":
            out.append("_")
            i += 1
        elif command.startswith("<<", i) and not command.startswith("<<<", i) and heredoc.match(command, i):
            found = heredoc.match(command, i)
            pending.append((found.group(1) == "-", next(g for g in found.groups()[1:] if g is not None)))
            out.append("<<" + "_" * (found.end() - i - 2))
            i = found.end()
        elif char == "\n" and pending:
            out.append(char)
            i += 1
            for strip, delimiter in pending:
                while i < len(command):
                    end = command.find("\n", i)
                    end = len(command) if end < 0 else end
                    last = (command[i:end].lstrip("\t") if strip else command[i:end]).rstrip("\r") == delimiter
                    out.append("_" * (end - i))
                    blank.append((i, end))
                    if end < len(command):
                        out.append("\n" if last else "_")
                    i = end + 1
                    if last:
                        break
            pending = []
        else:
            out.append(char)
            i += 1
    live = list(command)
    for start, end in blank:
        live[start:end] = " " * (end - start)
    return "".join(out), "".join(live)


def words(text: str) -> list:
    """The words of one simple command, quotes removed and redirections dropped. It never fails: an unterminated quote runs to the end."""
    found, current, quote, started, i = [], [], None, False, 0
    while i < len(text):
        char = text[i]
        if quote == "'":
            if char == "'":
                quote = None
            else:
                current.append(char)
        elif quote == '"':
            if char == '"':
                quote = None
            elif char == "\\" and i + 1 < len(text) and text[i + 1] in '"\\$`':
                current.append(text[i + 1])
                i += 1
            else:
                current.append(char)
        elif char in "'\"":
            quote, started = char, True
        elif char == "\\" and i + 1 < len(text):
            current.append(text[i + 1])
            started = True
            i += 1
        elif char.isspace():
            if started or current:
                found.append("".join(current))
            current, started = [], False
        else:
            current.append(char)
        i += 1
    if started or current:
        found.append("".join(current))
    return drop_redirections(found)


def drop_redirections(found: list) -> list:
    kept, skip = [], False
    for word in found:
        if skip:
            skip = False
        elif re.fullmatch(r"\d*(>>?|<)", word):
            skip = True
        elif not re.fullmatch(r"\d*(>>?|<|&>)&?\S*", word):
            kept.append(word)
    return kept


def command_of(tokens: list) -> tuple:
    """(the words from the command word on, the environment assignments before it): prefixes such as `env`, `timeout` and `nice` are skipped."""
    assigned, i = {}, 0
    while i < len(tokens):
        token, name = tokens[i], tokens[i].rsplit("/", 1)[-1]
        assignment = re.fullmatch(r"([A-Za-z_]\w*)=(.*)", token)
        if assignment:
            assigned[assignment.group(1)] = assignment.group(2)
        elif name in KEYWORDS:
            pass
        elif name == "env":
            while i + 1 < len(tokens) and (tokens[i + 1].startswith("-") or "=" in tokens[i + 1]):
                i += 1
                if tokens[i] in ("-u", "-C", "-S", "--unset", "--chdir"):
                    i += 1
                elif re.fullmatch(r"([A-Za-z_]\w*)=(.*)", tokens[i]):
                    assigned[tokens[i].split("=", 1)[0]] = tokens[i].split("=", 1)[1]
        elif name in ("timeout", "nice", "ionice", "stdbuf"):
            while i + 1 < len(tokens) and tokens[i + 1].startswith("-"):
                i += 1
                if tokens[i] in ("-s", "-k", "-n", "-c", "-p", "--signal", "--kill-after", "--adjustment"):
                    i += 1
            if name == "timeout":
                i += 1
        else:
            break
        i += 1
    return tokens[i:], assigned


def merges_in(command: str, depth: int = 0) -> list:
    """Every pull request merge that the command string makes, as (repository, number or None, subject or None)."""
    found = []
    mask, command = masked(command)
    spans, last = [], 0
    for separator in SEPARATORS.finditer(mask):
        spans.append((last, separator.start()))
        last = separator.end()
    spans.append((last, len(mask)))
    for start, end in spans:
        tokens, assigned = command_of(words(command[start:end]))
        if not tokens:
            continue
        name = tokens[0].rsplit("/", 1)[-1]
        if depth < 4 and name in SHELLS:
            flags = [i for i, t in enumerate(tokens[1:], 1) if t.startswith("-") and not t.startswith("--") and "c" in t]
            if flags and flags[0] + 1 < len(tokens):
                found += merges_in(tokens[flags[0] + 1], depth + 1)
        elif depth < 4 and name == "eval":
            found += merges_in(" ".join(tokens[1:]), depth + 1)
        elif name == "gh":
            merge = gh_merge(tokens[1:], assigned.get("GH_REPO"))
            if merge:
                found.append(merge)
    return found


def gh_merge(arguments: list, default_repo: str | None):
    """(repository, number or None, subject or None) when the `gh` arguments merge a pull request, else None."""
    repo, subject, positional, flags, i = default_repo, None, [], [], 0
    while i < len(arguments):
        word = arguments[i]
        if word.startswith("--") and "=" in word:
            flags.append(tuple(word.split("=", 1)))
        elif word in GH_VALUE_FLAGS or (positional[:1] == ["api"] and word in API_VALUE_FLAGS) or (positional[:1] == ["pr"] and word in MERGE_VALUE_FLAGS):
            flags.append((word, arguments[i + 1] if i + 1 < len(arguments) else ""))
            i += 1
        elif re.fullmatch(r"-[RX]\S+", word):
            flags.append((word[:2], word[2:]))
        elif word.startswith("-"):
            flags.append((word, None))
        else:
            positional.append(word)
        i += 1
    for flag, value in flags:
        if flag in ("-R", "--repo") and value:
            repo = value
    if positional[:2] == ["pr", "merge"]:
        for flag, value in flags:
            if flag in ("-t", "--subject"):
                subject = value
        target = positional[2] if len(positional) > 2 else ""
        url = re.fullmatch(r"https?://[^/]+/([\w.-]+/[\w.-]+)/pull/(\d+)\S*", target)
        if url:
            return url.group(1), int(url.group(2)), subject
        return repo or REPOSITORY, int(target) if target.isdigit() else None, subject
    if positional[:1] == ["api"] and len(positional) > 1:
        method = next((value for flag, value in flags if flag in ("-X", "--method")), "GET")
        path = re.sub(r"[?#].*", "", positional[1]).lstrip("/")
        match = re.fullmatch(r"repos/([^/]+/[^/]+)/pulls/([^/]+)/merge", path)
        if match and (method or "").upper() == "PUT":
            owner_repo = REPOSITORY if "{" in match.group(1) else match.group(1)
            return owner_repo, int(match.group(2)) if match.group(2).isdigit() else None, None
    return None


def merge_targets(payload: dict) -> list:
    """The merges the tool call makes, as (repository, pull request number or None, squash subject): none when the call is no merge."""
    tool, given = payload.get("tool_name"), payload.get("tool_input")
    if not isinstance(tool, str) or not isinstance(given, dict):
        raise Refusal("the hook input has no tool_name and tool_input")
    if tool == "mcp__github__merge_pull_request":
        return [(f"{given['owner']}/{given['repo']}", int(given["pullNumber"]), given.get("commit_title"))]
    if tool != "Bash":
        return []
    if not isinstance(given.get("command"), str):
        raise Refusal("the Bash input has no command")
    return merges_in(given["command"])


def run(payload: dict) -> str | None:
    """None when the call is no merge or the record is complete; a note when the pull request is an apparatus one. Raises Refusal."""
    notes = []
    for repo, number, subject in merge_targets(payload):
        if repo.lower() != REPOSITORY:
            continue
        if number is None:
            raise Refusal(f"{NUMBER_UNREADABLE}: the merge of a pull request of {repo} gives none that can be read")
        notes.append(check(REPOSITORY, number, subject))
    return "\n".join(note for note in notes if note) or None


def check(repo: str, number: int, subject: str | None) -> str | None:
    pull = gh([f"repos/{repo}/pulls/{number}"])
    files = [item["filename"] for item in gh_pages(f"repos/{repo}/pulls/{number}/files")]
    if is_apparatus(pull.get("title") or "", files, pull.get("body") or "", subject):
        return f"Record check: pull request #{number} is an apparatus pull request (titled 'drive:', nothing under src/ or examples/, no slice issue named), so it has no record to check."
    candidates = slice_numbers(pull.get("body") or "", subject)
    if len(candidates) != 1:
        raise Refusal(
            f"cannot tell the slice issue of pull request #{number}: found {sorted(candidates) or 'none'}. "
            "End the squash subject with '(#<slice>)' or write 'Part of #<slice>' in the PR body."
        )
    slice_number = candidates.pop()
    comments, tickets, log = gh_pages(f"repos/{repo}/issues/{slice_number}/comments"), {}, []
    if slice_number not in MERGED_BEFORE_DELEGATED_ENTRY:
        tickets = {item["number"]: gh_pages(f"repos/{repo}/issues/{item['number']}/comments") for item in gh_pages(f"repos/{repo}/issues/{slice_number}/sub_issues")}
        log = gh_pages(f"repos/{repo}/issues/{DECISION_LOG}/comments")
    reasons = problems(pull.get("body") or "", comments, slice_number, tickets, log)
    if reasons:
        raise Refusal(f"the record of slice #{slice_number} is incomplete, so pull request #{number} is not merged:\n" + "\n".join(f"- {r}" for r in reasons))
    return None


def main() -> int:
    try:
        note = run(json.load(sys.stdin))
    except Refusal as refusal:
        print(f"check_record: {refusal}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"check_record failed ({type(error).__name__}: {error}); the merge is blocked", file=sys.stderr)
        return 2
    if note:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": note}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
