# Hypotrail Studies in this workspace

These instructions are for Copilot chat in VS Code, in a workspace that holds a Hypotrail Study and where the Hypotrail extension is installed. To use them, copy this file to `.github/copilot-instructions.md` in that workspace.

A Study is the only authority on its decisions: a Decision exists once the Study records it, and not before. The Hypotrail extension gives you two tools for it. `hypotrail_read_study` reads the Study and writes nothing. `hypotrail_decide` records one Decision through the Hypotrail command `decide`.

## The rule

1. At the start of each turn, read the Study's state with `hypotrail_read_study`, before you answer about the Study or write to it. A Decision may have been recorded since your last turn, in the Study panel, in a terminal or by another agent, so an earlier read may be out of date.
2. Keep the `write_sequence` of that read, and pass it as `read_sequence` on every write to the Study. If the Study was written to after your read, the write is refused with `STUDY_CHANGED` and nothing is recorded.
3. Record a Decision only through `hypotrail_decide`, which starts `decide`.
4. Set `author` by who made the choice:
   - `human` only when the user states the choice in this chat. A `source` may then be given, and it is optional.
   - `proxy` when you answer by a stated rule, one that the user gave you or that this workspace's instructions give. Then pass `source`, a text that names that rule. A `proxy` Decision without a `source` is refused, and nothing is recorded.
5. When the user states the choice in this chat, record the user's own words with the Decision: pass `words`, the user's messages that state the choice, each whole and unchanged, one string per message, and `question_id` and `option_id`, the ids of the pending decision's question and of the option chosen. Your own wording, or a summary of what the user said, goes in `source`, never in `words`. The tool records the words as relayed by Copilot; never declare the channel `panel`, which is the Study panel's own.

## Calling the tools

- On every write with `hypotrail_decide`, pass `study`, the absolute path of the Study's folder, as a tool's answer lists it, even when the workspace holds one Study. On a read, with one Study in the workspace, leave `study` out; with several, pass it. A path that is not absolute matches no Study, and the call is refused.
- Pass `question` and `option` exactly as the pending decision words them in your read, and in `cited_ids` the ids of the records the Decision cites, such as the Comparison's.
- VS Code asks the user to confirm each Decision before it is recorded, unless the user chose "Always Allow" for `hypotrail_decide`. When the user cancels, nothing is recorded.
- A write that is refused, or that gets no answer, is not sent again by the tool. Read the Study before you write again: a write that got no answer may have been recorded.
