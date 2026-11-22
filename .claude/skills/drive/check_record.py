#!/usr/bin/env python3
"""PreToolUse hook before a merge (D-055 on chadlis/hypotrail#75, item 3). It fails closed: any error exits 2.

It acts on the tool `mcp__github__merge_pull_request`, and on a Bash command that runs `gh pr merge` or
`gh api .../pulls/<n>/merge`. The merge is refused (exit 2, the reasons on stderr) while any of these is missing
for the slice issue of the pull request:

1. the state comment's round count (`Review rounds used: N of 5`) equals the number of rounds that have a review of record;
2. each round that has a review of record has a "round <r>: routing" comment;
3. when a routing comment of round 5 or later routes a row as documentation, each axis of that row has a
   "round <r>: <axis> verification" comment (the documentation path of the skill);
4. a "closing register" comment exists and names every finding ID that a routing table assigned;
5. each routing row that promises a line in the PR body ("PR body") and is neither refuted, out of scope, a duplicate nor
   fixed has its ID in the PR body.

The slice issue is the one the squash subject ends with ("(#<n>)"), or the one the PR body names ("Part of #<n>",
"Slice ... (#<n>)"). A pull request that touches only `.claude/`, `AGENTS.md`, `CLAUDE.md`, `docs/agents/` or
`scripts/` is an apparatus pull request: it has no slice issue, and the hook lets it through with a note.
"""

import json
import re
import shlex
import subprocess
import sys

REPOSITORY = "chadlis/hypotrail"
APPARATUS = (".claude/", "AGENTS.md", "CLAUDE.md", "docs/agents/", "scripts/")
FINDING_ID = re.compile(r"\b[A-Z]\d+[a-z]?-[A-Z]-\d{2}\b")
ROUND_LIMIT = 5


class Refusal(Exception):
    pass


def is_apparatus(files: list) -> bool:
    return bool(files) and all(name.startswith(APPARATUS) for name in files)


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
            settled = re.match(r"(refuted|out of scope|duplicate|fixed|withdrawn)", cells[5], re.IGNORECASE)
            if promised and not settled:
                for finding in FINDING_ID.findall(cells[0]):
                    if finding not in pr_body:
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
    done = subprocess.run(["gh", "api", *arguments], capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise Refusal(f"`gh api {' '.join(arguments)}` failed: {done.stderr.strip()}")
    return json.loads(done.stdout)


def gh_pages(path: str) -> list:
    return [item for page in gh([path, "--paginate", "--slurp"]) for item in page]


def merge_target(payload: dict):
    """(repository, pull request number, squash subject) of the merge the tool call makes, or None when the call is no merge."""
    tool, given = payload.get("tool_name"), payload.get("tool_input")
    if not isinstance(tool, str) or not isinstance(given, dict):
        raise Refusal("the hook input has no tool_name and tool_input")
    if tool == "mcp__github__merge_pull_request":
        return f"{given['owner']}/{given['repo']}", int(given["pullNumber"]), given.get("commit_title")
    if tool != "Bash":
        return None
    if not isinstance(given.get("command"), str):
        raise Refusal("the Bash input has no command")
    for segment in re.split(r"&&|\|\||[;|&\n]", given["command"]):
        match = re.search(r"^\s*(?:\w+=\S+\s+)*gh\s+api\b.*?repos/([\w.-]+/[\w.-]+)/pulls/(\d+)/merge\b", segment)
        if match:
            return match.group(1), int(match.group(2)), None
        if re.search(r"^\s*(?:\w+=\S+\s+)*gh\s+pr\s+merge\b", segment):
            words = shlex.split(segment)
            words = words[words.index("merge") + 1:]
            repo, subject, target, skip = REPOSITORY, None, None, False
            for at, word in enumerate(words):
                if skip:
                    skip = False
                elif word in ("-R", "--repo"):
                    repo, skip = words[at + 1], True
                elif word.startswith("--repo="):
                    repo = word.split("=", 1)[1]
                elif word in ("-t", "--subject"):
                    subject, skip = words[at + 1], True
                elif word.startswith("--subject="):
                    subject = word.split("=", 1)[1]
                elif word in ("-b", "--body", "-F", "--body-file", "-A", "--author-email", "--match-head-commit"):
                    skip = True
                elif not word.startswith("-") and target is None:
                    target = word
            number = re.search(r"(?:^|/pull/)(\d+)$", target or "")
            if number:
                return repo, int(number.group(1)), subject
            argument = [target] if target else []
            done = subprocess.run(["gh", "pr", "view", *argument, "-R", repo, "--json", "number", "--jq", ".number"], capture_output=True, text=True, timeout=60)
            if done.returncode:
                raise Refusal(f"cannot tell which pull request `gh pr merge` merges: {done.stderr.strip()}")
            return repo, int(done.stdout), subject
    return None


def run(payload: dict) -> str | None:
    """None when the call is no merge or the record is complete; a note when the pull request is an apparatus one. Raises Refusal."""
    target = merge_target(payload)
    if target is None or target[0] != REPOSITORY:
        return None
    repo, number, subject = target
    pull = gh([f"repos/{repo}/pulls/{number}"])
    files = [item["filename"] for item in gh_pages(f"repos/{repo}/pulls/{number}/files")]
    if is_apparatus(files):
        return f"Record check: pull request #{number} touches only the apparatus, so it has no slice issue and no record to check."
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
