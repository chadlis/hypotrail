# Where a human act happens, and how a record says it

Status: proposed

## Context

A Decision whose author is `human` must mean that a person chose. Today a record cannot show it. The channel of the person's words is declared by the caller and never checked: `CHANNELS = ("panel", "choice", "chat_relayed")` (`src/hypotrail/core/decisions.py:69`), and every `words` object is built with `"authenticated": False` (`src/hypotrail/core/decisions.py:329`), whatever the channel. GLOSSARY, **Decision**, states the same: "`authenticated` is false, and the agent's own wording is never `words`".

The Copilot write tool, `hypotrail_decide` (`clients/vscode/src/tools.ts`), accepts `author: "human"` and declares `chat_relayed` for the words it is given. Its confirmation is a VS Code tool confirmation, which offers to always allow the tool. Once a user picks that, a `human` Decision is recorded by the chat agent alone, with no dialog (chadlis/hypotrail#269). The panel's Record is meant to be the act that makes a Decision human (D-151 on chadlis/hypotrail#75, answer 6: the panel sends `channel` "panel" and no `by`, "it knows no person").

Three owner decisions bound where such an act may happen:

- D-136 on chadlis/hypotrail#75: "Nothing that tells the reader what to do is computed by the client", and a proxy Decision stays "◇ Decided by a rule, not by a person" until a validation record exists. Human validation of a proxy Decision "is a new record that cites the Decision. A Decision is never rewritten."
- D-165 on chadlis/hypotrail#75: "The validation level is configurable. A pull request is the strongest level, not a required step, and no physical key is used. This applies to pre-registration and to the held-out pass." Item 2: "the PR is optional there" for framing. Item 3: "The chat is allowed at every station except the held-out pass."
- D-166 on chadlis/hypotrail#75: the drive's plan is ratified, and "#269 waits for J0-a, as ratified."

The Validation record (GLOSSARY, **Validation**) is not built (ADR 0005, Consequences).

## Decision

1. **One surface per act.**
   - The panel records: its Record is the place where a person's choice becomes a `human` Decision.
   - The chat prepares and relays: it may explain, draft a rule or the person's wording, and relay words, but its relay is never presented as the person's act.
   - A pull request is the strongest level: a Decision or Validation that cites a merged pull request rests on an act that the forge authenticated.
   - A job records a reserved pass, such as the held-out pass of D-165 item 1: the job runs the commands of that pass, and no chat agent takes part in it (D-165 item 3).
2. **The channel values.** `words.channel` keeps `panel`, `choice` and `chat_relayed`, and gains `file_relayed`: the words were read from a file and relayed by the caller. A Decision whose words have the channel `file_relayed` requires `source`, and `decide` refuses one without it with `INVALID_ARGUMENTS` before the lock, as it refuses other wrong uses of its word options. The CLI's `--channel` choices and `CHANNELS` gain the value together.
3. **`authenticated` stays false** unless the record cites an authenticated act, such as a merged pull request. No channel value, on its own, sets it to true. No text of the panel, the report or a tool presents a channel as a proof of who chose.
4. **The validation level is configurable** (D-165 items 1 and 2). A Study declares the level its Decisions and Validations must reach; the pull request is the strongest level and is optional. Each Decision is shown with a mark of the level it reached, derived when the Study is read and never stored, and with a mark "below the declared level" when that level is lower than the declared one.
5. **What is not configurable.** The rules on the order of records (what a Study must hold before a given write is admitted, as its write journal shows) and the wall around a reserved pass (no chat agent reaches it, D-165 item 3) hold at every validation level. No setting relaxes them.
6. **#269.** Whether `hypotrail_decide` may still write `author: "human"` is decided after the J0-a trial (D-164, D-166 on chadlis/hypotrail#75). The two options carried:
   - **Option 1.** The tool refuses `author: "human"` before any start. It records `proxy` Decisions only, and a `human` Decision goes through the panel's Record or the CLI.
   - **Option 2.** The tool keeps `human`, and such a Decision carries a channel or mark that says it was recorded by the chat tool; the panel shows it as awaiting the person's validation, through the Validation record.

   Until that decision, the tool's behaviour is unchanged, and its confirmation text stays the only guard.

## Consequences

- **Durable formats.** `file_relayed` becomes a value of `words.channel` in `decision/2`; a record written before it stays valid and replays. The meaning of `authenticated` widens from "always false" to "false unless an authenticated act is cited"; every record written so far holds false and stays true to that meaning. The declared validation level is part of the record format of a Study, wherever it is held (Open, below). The two marks are read keys, computed when the Study is read: they are not records and can be removed without a migration.
- GLOSSARY, **Decision**, gains a dated clarification for `file_relayed` and for `authenticated`. ADR 0004 gains a dated line for the `--channel` value and for the marks in `status --json`.
- Under option 1, the accompanied path loses recording in the chat, and a `human` Decision from a terminal agent stays possible through the CLI: only the agent's instructions close it. Under option 2, the chat keeps recording, and the Validation record becomes a precondition for reading such a Decision as the person's.
- A reserved pass is never prepared in the chat, at any validation level.
- The Validation record, a pull request's citation and the job's commands are not built by this ADR.

## Alternatives rejected

- **The channel as proof of identity** (rejected): every channel is what the caller declares (`decisions.py:68`), so a record that read `panel` as "the person chose" would say more than it holds.
- **A fixed level for every Study, the pull request required** (rejected by D-165 items 1 and 2): the pull request is the strongest level, "not a required step".
- **A physical key as the strongest level** (rejected by D-165 item 1: "no physical key is used").
- **Leaving #269 as it is and documenting that "always allow" hands the choice to Copilot** (option 3 of chadlis/hypotrail#269; not carried): it makes the chat a channel that writes `human` with no act of the person.
- **Configurable order rules or wall** (rejected): a level that relaxed them would let a Study hold, at a low level, results that the order and the wall exist to prevent.

## Open

- **Where the declared level is held**: in the Plan (ADR 0005), in the Workload declaration, or in a record of its own. A Plan holds what a person ratified about how a Study goes on; the Workload holds what binds every Study of it.
- **The ordered list of levels**: which of `chat_relayed`, `file_relayed`, `choice`, `panel` and a cited pull request rank above which, whether `chat_relayed` and `file_relayed` share a level, and where a `proxy` Decision sits.
- **What `source` holds for `file_relayed`**: a path relative to the Study, a path with the sha256 of the file's bytes, or free text.
- **How a record cites an authenticated act**: the form of a pull request's citation (repository, number, merge commit), and whether Hypotrail checks it offline, online, or not at all.
- **The order rules and the wall**: the sources name them but do not list them. Which order rules hold (for example a rule recorded before the first Exposure), and the exact extent of the wall (which Study, which surfaces, until which record), are to be written before the held-out passes.
- **The CLI as a surface**: whether a `human` Decision written through the CLI by a person is read at the level of its declared channel, or at a level of its own.
- **A Decision below the declared level**: recorded and marked only, or refused at write for some kinds of question (for example on a reserved pass).
- **#269**: option 1 or option 2, after J0-a.
