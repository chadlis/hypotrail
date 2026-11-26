# Where a human act happens, and how a record says it

Status: accepted

## Context

A Decision whose author is `human` must mean that a person chose, but no record can show that today. The caller declares the channel of the person's words, and nothing checks it: `CHANNELS = ("panel", "choice", "chat_relayed")` (`src/hypotrail/core/decisions.py:69`). Every `words` object is built with `"authenticated": False` (`src/hypotrail/core/decisions.py:329`), whatever the channel. GLOSSARY, **Decision**, says the same: "`authenticated` is false, and the agent's own wording is never `words`".

The Copilot write tool, `hypotrail_decide` (`clients/vscode/src/tools.ts`), accepts `author: "human"` and declares `chat_relayed` for the words it is given. It asks for confirmation through VS Code's tool confirmation, which offers to always allow the tool. Once a user picks that option, the chat agent alone records a `human` Decision, and no dialog appears (chadlis/hypotrail#269). The panel's Record is meant to be the act that makes a Decision human: the panel sends `channel` "panel" and no `by`, since "it knows no person" (D-151 on chadlis/hypotrail#75, answer 6).

Owner decisions bound where such an act may happen:

- D-136 on chadlis/hypotrail#75: "Nothing that tells the reader what to do is computed by the client". A proxy Decision stays "◇ Decided by a rule, not by a person" until a validation record exists, and that validation "is a new record that cites the Decision. A Decision is never rewritten."
- D-148 on chadlis/hypotrail#75, item 1: "a proxy Decision that differs from the rule is marked, not refused".
- D-165 on chadlis/hypotrail#75: "The validation level is configurable. A pull request is the strongest level, not a required step, and no physical key is used. This applies to pre-registration and to the held-out pass." The PR is optional for framing too (item 2), and "The chat is allowed at every station except the held-out pass" (item 3).
- D-167 on chadlis/hypotrail#75: the outside kits hold "a separate evaluator job that alone reads the held-out labels".
- D-166 on chadlis/hypotrail#75: "#269 waits for J0-a, as ratified."

Hypotrail seals nothing: "Any future holdout mechanism needs its own explicit protocol and threat boundary." (`docs/product/ROADMAP.md:148`). The Plan and the Validation record are not built yet (ADR 0005, Consequences). The open points of the draft were answered by the owner's proxy (D-168 on chadlis/hypotrail#75).

## Decision

1. **One surface per act.**
   - The panel records: its Record is where a person's choice becomes a `human` Decision.
   - The chat prepares and relays. It may explain, draft a rule or the person's wording, and relay words, but its relay is never presented as the person's act.
   - A pull request is the strongest level.
   - The job is the outside evaluator (D-167), not a surface of Hypotrail. It has an identity the agents do not have, it runs the CLI, and it writes the final Decision of a reserved pass, such as the held-out pass, from a file. Hypotrail supplies only its commands.
2. **The channel values.** `words.channel` keeps `panel`, `choice` and `chat_relayed`, and gains `file_relayed`: the caller read the words from a file and relays them. A Decision with the channel `file_relayed` requires `source`. Without it, `decide` refuses with `INVALID_ARGUMENTS` before the lock, as it does for other wrong uses of its word options. That `source` names the outside act the file comes from, as non-empty declared text: a pull request citation (point 5), or the job's run and its account. It is not the path or digest of the words file, since the words are already stored whole. `source` stays a string, and there is no `decision/3`.
3. **`authenticated` stays always false.** Hypotrail checks no citation, so a cited act is still what the caller declares. A cited pull request raises the derived level mark only. `authenticated` may turn true only when Hypotrail itself has run a check and recorded it, and a later ADR decides that.
4. **The validation level is configurable** (D-165 items 1 and 2). The level is held in the Plan, as one key beside `rule`, `budget` and `delegation` (ADR 0005). The levels, strongest first, are:
   1. `pr`: `source` cites a merged pull request;
   2. `panel`: channel `panel` or `choice`;
   3. `relayed`: channel `chat_relayed` or `file_relayed`;
   4. `undeclared`: a `human` Decision with no words.

   A `proxy` Decision is off the scale. It reads "Decided by a rule, not by a person", and it takes the level of the Validation that cites it. A Decision written by a person through the CLI has the level of its declared channel: nothing tells a person from an agent at a terminal. Each Decision is shown with a mark of its level, and each level is labelled as declared. When its level is lower than the one in the Plan in force at its write, it also gets the mark "below the declared level". Both marks are derived when the Study is read and never stored. A Decision below the level is marked and never refused by `decide`, on a reserved pass too.
5. **A pull request citation** is written in `source` as `https://github.com/<owner>/<repo>/pull/<n>@<40-hex merge commit>`. Hypotrail checks only its form, offline, and never asks the forge. The mark reads "pr, cited, not checked by Hypotrail".
6. **The order rule and the wall are not configurable.**
   - The order rule: the rule and the declared level are recorded before the Study's first Exposure. It is read from the write journal, where the Exposure entries already are. It is shown at every level, and nothing is refused at write.
   - The wall: no agent of any kind, whether chat or terminal, reads the held-out labels or the per-Item results of a reserved pass. No surface does either, the panel included, until the final Decision is recorded. Only an aggregate report with no question or answer text leaves it. After the final Decision a person may open that Study in the panel; an agent never does. The wall is held by the evaluator's place and the job's identity, outside Hypotrail. No Hypotrail setting stands for it, and the validation level says nothing about it.
7. **#269.** Whether `hypotrail_decide` may still write `author: "human"` is decided after the J0-a trial (D-164 and D-166 on chadlis/hypotrail#75). The two options:
   - **Option 1.** The tool refuses `author: "human"` before any start. It records `proxy` Decisions only, and a `human` Decision goes through the panel's Record or the CLI.
   - **Option 2.** The tool keeps `human`, and such a Decision carries a channel or mark that says the chat tool recorded it. The panel shows it as awaiting the person's validation, through the Validation record.

   Until that decision the tool does not change.

## Consequences

- **Durable formats.**
  - `file_relayed` becomes a value of `words.channel` in `decision/2`: the one durable addition, which stays once a record holds it. A record written before it stays valid and replays.
  - `authenticated` keeps its meaning, always false.
  - The level key arrives with the Plan slice, as part of the Plan record.
  - The level marks, the "below the declared level" mark and the order rule's display are read keys, computed when the Study is read. They can be removed without a migration.
- Until the Plan exists, the level is stated in the words of the pre-registration Decision and read by people, and the "below the declared level" mark waits for the Plan.
- GLOSSARY, **Decision**, gains a dated clarification for `file_relayed`. ADR 0004 gains a dated line for the `--channel` value and for the marks in `status --json`.
- If the job's account is shared with agents, `file_relayed` is worth no more than `chat_relayed`, and a cited pull request no more than `relayed`. The mark must then say so.
- Under option 1, recording moves out of the chat in the accompanied path. A `human` Decision from a terminal agent stays possible through the CLI, and only the agent's instructions close that path. Under option 2, the chat keeps recording, and the Validation record becomes a precondition for reading such a Decision as the person's.
- The Validation record, the Plan's level key, the check of a citation's form and the order rule's display are not built by this ADR. The wall's storage, the job's identity and the separate accounts are outside Hypotrail.

## Alternatives rejected

- **The channel as proof of identity**: the caller declares every channel (`decisions.py:68`), so reading `panel` as "the person chose" says more than the record holds.
- **`authenticated` true when an act is cited**: an agent with a terminal could pass a pull request URL as `--source` and get `authenticated: true` (D-168).
- **The level held in the Workload**: a change of level would then stop every Decision from applying, and one Workload serves a public twin and a private Study at different levels (D-168).
- **Finer ranks, such as the job above the chat**: Hypotrail cannot tell a job from a chat, so a finer rank would claim what the record does not hold (D-168).
- **The path or sha256 of the words file as `source`**: the words are already stored whole, and a path inside the evaluator's place means nothing to a reader (D-168).
- **An online check of the pull request**: the core imports nothing, and CI makes no network call. Such a check would be a later opt-in read (D-168).
- **A fixed level for every Study, with the pull request required**: D-165 items 1 and 2 make it "not a required step".
- **A physical key as the strongest level**: D-165 item 1, "no physical key is used".
- **A Decision below the level refused at write**: D-148 item 1, "marked, not refused". A reserved pass is protected by the wall, not by a refusal in the core.
- **Leaving #269 as it is**, with a note that "always allow" hands the choice to Copilot (option 3 of chadlis/hypotrail#269): the chat would then write `human` with no act of the person.
- **A configurable order rule or wall**: a low level would then let a Study hold results that the order and the wall exist to prevent.

## Open

- **#269**: option 1 or option 2, decided after the J0-a trial.
- **The owner's read of this ADR** comes before any private Study fixes its record format. Public twins do not wait for it.
