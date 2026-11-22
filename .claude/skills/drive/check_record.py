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
   when there is one, the routing row otherwise. A fix prompt or a report settles no row.

The slice issue is the one the squash subject ends with ("(#<n>)"), or the one the PR body names ("Part of #<n>",
"Slice ... (#<n>)"). A pull request whose title starts with "drive:" and that changes no file under `src/` or `examples/` is an
apparatus pull request, whatever other files it touches: it has no slice issue, and the hook lets it through with a note.
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


def is_apparatus(title: str, files: list) -> bool:
    return title.startswith("drive:") and not any(name.startswith(PRODUCT) for name in files)


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


def problems(pr_body: str, comments: list) -> list:
    """The reasons the record of a slice is incomplete: one string each; empty when it is complete."""
    reviewed = {int(m.group(1)) for c in comments for m in [re.search(r"\bround (\d+)\b[:,]? [^\n]*?\baxis \(review of record", first_line(c))] if m}
    routed = {int(m.group(1)): c for c in comments for m in [re.search(r"\bround (\d+)\b[:,]? routing", first_line(c))] if m}
    found = []
    if not reviewed:
        return ["no review of record is posted: no comment of the form 'round <r>: <axis> axis (review of record ...'"]

    states = [c for c in comments if re.match(r"##.*\bstate\b", first_line(c), re.IGNORECASE) and not re.search(r"\bround \d", first_line(c))]
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
    if is_apparatus(pull.get("title") or "", files):
        return f"Record check: pull request #{number} is an apparatus pull request (titled 'drive:', nothing under src/ or examples/), so it has no slice issue and no record to check."
    candidates = slice_numbers(pull.get("body") or "", subject)
    if len(candidates) != 1:
        raise Refusal(
            f"cannot tell the slice issue of pull request #{number}: found {sorted(candidates) or 'none'}. "
            "End the squash subject with '(#<slice>)' or write 'Part of #<slice>' in the PR body."
        )
    slice_number = candidates.pop()
    reasons = problems(pull.get("body") or "", gh_pages(f"repos/{repo}/issues/{slice_number}/comments"))
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
