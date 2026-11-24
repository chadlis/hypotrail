"""A Claude Code `UserPromptSubmit` hook: at every prompt, the state of one Hypotrail Study, as plain text that Claude Code adds as context.

Copy `settings-fragment.json` of this folder into the project's `.claude/settings.local.json` or `.claude/settings.json`, on a checkout of
Hypotrail installed with `uv sync`, one entry per Study. Claude Code starts this script with `python3 -I`, which need not be the project's
Python: it imports the standard library only. The script starts the CLI's read once, prints what the answer holds, and keeps nothing.
"""

import json
import os
import signal
import subprocess
import sys

COMMAND = ("uv", "run", "--no-sync", "python", "-m", "hypotrail", "status", "--study", "{study}", "--since", "{since}", "--json")
SINCE = 0
READ_TIMEOUT_SECONDS = 20
# Claude Code caps a hook's plain stdout at OUTPUT_CAP characters; the text is kept within TEXT_LIMIT, below it.
TEXT_LIMIT = 9000
OUTPUT_CAP = 10000
LEFT_OUT_LINE = "Decisions left out of this text, the oldest first, to keep it within the hook's limit: {count}; `status --json` lists them."
# One line, printed whole after the Study's values and in the failure line, so each sentence holds in both.
RULE = (
    "Rule for an agent on this Study: read the Study's state at the start of each turn; when this hook printed the Study's values above,"
    " they are that read, from `status --since 0 --json`, and `status --json` gives the rest. Pass the `write_sequence` you read as"
    " `--read-sequence` on every write to the Study, and read again when a write is refused with `STUDY_CHANGED`. Record a Decision only"
    " through `decide`. Record an answer chosen by a stated rule as a proxy Decision: `decide --author proxy` with a `--source` that names"
    " the rule."
)
FAILURE_LINE = "Hypotrail: this hook could not read the Study at this prompt, so it printed none of its values. " + RULE


def read(study, project):
    """The object the CLI answered, which is one JSON object with `ok` true; anything else raises."""
    arguments = [word.format(study=study, since=SINCE) for word in COMMAND]
    # A session of its own, so that the bound stops `uv` and the CLI's Python it started, not `uv` alone.
    process = subprocess.Popen(
        arguments, cwd=project, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        encoding="utf-8", start_new_session=True,
    )
    try:
        out, _ = process.communicate(timeout=READ_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise
    payload = json.loads(out)
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ValueError("the CLI's answer is not one JSON object with `ok` true")
    return payload


def quoted(value):
    """A text of the Study as a JSON string: a quote or a line break in it stays on its line."""
    return json.dumps(value, ensure_ascii=False)


def pending_line(entry):
    options = ", ".join(f"{option['id']} {quoted(option['text'])}" for option in entry["options"])
    return f"- Comparison {entry['comparison_id']}: question {quoted(entry['question']['text'])}; options {options}."


def decision_line(decision):
    source = "none" if decision["source"] is None else quoted(decision["source"])
    change = "none" if decision["evidence_change"] is None else decision["evidence_change"]["state"]
    return (
        f"- Decision {decision['decision_id']}: question {quoted(decision['question'])}; option {quoted(decision['option'])};"
        f" author {decision['author']}; source {source}; cited {', '.join(decision['cited_ids']) or 'none'};"
        f" applies {'true' if decision['applies'] else 'false'}; evidence_change {change}."
    )


def text(study, payload):
    """The lines of the text, without its final line break. Past TEXT_LIMIT, the oldest Decisions are left out until it fits, with a count
    line; the Study, its Write sequence, its pending decisions and the rule are never left out, so that many pending decisions alone can
    still pass the limit."""
    pending = payload["pending_decisions"]
    decisions = [decision_line(decision) for decision in payload["decisions"]]
    head = [
        f"Hypotrail Study {quoted(study)}, study_id {payload['study']['study_id']}.",
        f"Write sequence: {payload['write_sequence']}",
        f"Pending decisions: {len(pending)}",
        *(pending_line(entry) for entry in pending),
        f"Decisions, oldest first: {len(decisions)}",
    ]
    left_out = 0
    while True:
        count = [LEFT_OUT_LINE.format(count=left_out)] if left_out else []
        lines = "\n".join([*head, *decisions[left_out:], *count, RULE])
        if len(lines) + 1 <= TEXT_LIMIT or left_out == len(decisions):
            return lines
        left_out += 1


def study_of(arguments):
    """DIR of `--study DIR`, the one argument the script takes."""
    if len(arguments) == 2 and arguments[0] == "--study" and arguments[1]:
        return arguments[1]
    raise ValueError("the script takes `--study DIR`")


def main(arguments):
    """Prints the text, or the failure line when anything goes wrong, and always exits 0, so that the prompt is never blocked."""
    try:
        if sys.stdin is not None and not sys.stdin.isatty():
            sys.stdin.read()  # the prompt's JSON, read whole so that Claude Code's write never meets a closed pipe; nothing in it is used
        study = study_of(arguments)
        project = os.environ.get("CLAUDE_PROJECT_DIR")
        if not project:
            raise ValueError("CLAUDE_PROJECT_DIR is not set")
        output = text(study, read(study, project))
    except Exception:
        output = FAILURE_LINE
    sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
