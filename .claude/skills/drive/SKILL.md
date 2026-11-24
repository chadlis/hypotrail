---
name: drive
description: "Deliver one Hypotrail slice through the existing delegated implementation and independent review workflow. Preserve autonomous development and attach concise evidence for selected learning goals. Invoke with /drive, /drive #n, or a request to resume a slice. Optional prepare produces a learning handoff before implementation. Existing merge and chain modifiers remain explicit, except under the autonomous protocol of 2026-11-20, which implies them."
disable-model-invocation: true
---

# Drive: one slice, issue to pull request

You are the session that stays open while a slice is built. Subagents do the work that needs fresh eyes; you keep the thread, the order of the steps, and the reasoning.

Everything you need is in the repository and its issue tracker. Read it; do not assume it.

## What you are, and what you are not

**You are** where the slice's reasoning lives: which option, why, what a finding means, whether something was decided without being written down. You refuse to let a step be skipped.

**You hold no gate.** You followed the design, so you cannot judge whether it belongs. Three checks need a session that followed nothing:

- the **ticket gate** (step 3), delegated to a fresh agent that reads text against text;
- the **pre-run gate** (« Paid live runs »), a fresh `slice-gate` before the first paid invocation;
- the **review of record** (step 5), `/mattpocock-skills:code-review` invoked bare, its two axis readers each a fresh `slice-gate` agent.

**You write no implementation code.** Not one line under `src/`, `tests/` or `examples/`. You write issue comments, amendments, glossary or ADR lines when a finding requires them, and the commits that carry what subagents leave uncommitted. An ADR line you write states only what the code does or a ticket requires. Once a review of record has read it, it changes only by a new dated line in the `## Dated lines` section at the end of the ADR, added after the ADR's existing sections when it has none: the date, the change, the ticket line that asks for it, quoted, the earlier line it overrides, and why that line's reason does not hold for the change (`docs/agents/domain.md:53`, "worth reopening because…"). A line that only adds ends "the earlier line it overrides: none" and gives no why.

**Say what you read and what you deduce.** Each time you state where the slice stands, name the file, issue or command that told you. When you infer, write « je déduis ».

At the end of a slice, say honestly whether you wrote code you should have delegated, and whether a review came back suspiciously agreeable.

## Subagents and models

Each step runs as a subagent **of a named type**, so its model is fixed by the type's frontmatter in `.claude/agents/`, never by a default, except the two model overrides named below (D-063 on chadlis/hypotrail#75):

| step | model |
|---|---|
| tickets (`slice-planner`) | Fable |
| ticket gate (`slice-gate`) | Fable |
| owner decisions (`owner-proxy`) | Fable, Opus when Fable is unavailable |
| implementation and fixes (`slice-builder`) | Opus |
| review of record, verifications and disposition checks (`slice-gate`) | Opus |
| retro (`slice-planner`, with a model override to Opus), and the drive itself | Opus |

The ticket gate's reading (step 3) runs as `slice-gate`, with a model override to Fable; every other `slice-gate` step runs on its frontmatter's Opus (D-063 on chadlis/hypotrail#75).

**A subagent cannot start subagents.** A skill that starts its own (`implement-spec`, `mattpocock-skills:code-review`) runs in your session, and only its leaves are delegated, each as a named type below. You orchestrate, you still write no code. For the review of record, each axis report goes to Salah word for word: you route findings, you never merge or summarise the two reports.

**A reviewer never runs on a weaker model than the author.** The required named types are checked in "Preflight". If one is missing, propose its creation separately. Do not create it during the slice or fall back to an untyped call. `prepare`, which writes only its note and a preparation comment, does not require these types. Never change a step's model mid-slice, except the proxy's fallback under "Autonomous protocol" and, when Fable is unavailable, this named exception (D-063 on chadlis/hypotrail#75): before a ticket gate passes, the chain pauses rather than running the gate on Opus over tickets that Fable wrote; after the gate passes, only the proxy needs Fable, and it falls back to Opus as written there. When an agent file changes during a session, put the changed paragraph in that agent's prompts until a new session loads the file.

**Reaching Matt Pocock's user-invoked skills.** `to-tickets`, `implement`, `implement-spec` and `retro` cannot be invoked through the Skill tool. Tell the subagent to read the file and follow it:

```
Read and follow ~/.claude/plugins/cache/*/mattpocock-skills/*/skills/engineering/<name>/SKILL.md
```

`code-review`, `tdd` and `pr` are invocable directly. Always name Matt Pocock's code review in full, `/mattpocock-skills:code-review`: the bare `/code-review` resolves to Claude Code's built-in reviewer, which checks correctness only and never reads the issue.

**Every delegation prompt is short** and ends with exactly this line, except the review of record:

```
If the repository does not settle a question, stop and hand back with the question. Do not decide in my place.
```

When a subagent asks, answer it yourself from the repository, inside your delegation (see "Who decides"), without forwarding it to Salah (EXÉCUTION). If the question rests on a false premise, correct the premise in the answer.
Each fact about a file that your answer states, to a builder or to a ticket-gate point, gets the check of "Check the premise before you route" before you post it, with the command and its output under the answer. A test your answer names as existing is named by its ID (`tests/file.py::test_name`).

**The review of record goes out bare**: `/mattpocock-skills:code-review main` in round 1, `/mattpocock-skills:code-review <head of the last reviewed round>` after, nothing else, ever. Merge `main` into the slice branch only directly onto a reviewed head. The next round's base is then that merge commit, so `main`'s changes stay out of the diff and nothing is excluded by hand. "Look especially at X" contaminates it while it still looks independent. A disposition check (see "Routing findings") is a separate, later message to an axis reader, after its independent first reading, never part of the invocation.

## Full-auto, and what may leave the branch

Code on the feature branch is reversible. Issue edits, learning notes and paid live runs are external effects and remain bounded by their existing authorization. Learning preparation adds no permission to merge, spend, or change the product scope.

By default the run **stops at the open PR**:

- `main` gains nothing;
- the feature branch is pushed, force-pushed if needed;
- issues are commented and labelled, never closed;
- no live LLM campaign beyond what the slice issue explicitly asks for.

**Modifiers**, only if named in the opening message:

- **`merge`**: authorization to squash-merge a completed, reviewed slice without a second routine approval, then close it without deleting the branch. Resolve every pending product decision, owner reservation and blocking finding before merging. An `INFERRED` ticket is cleared by a cited requirement or an explicit owner decision, never by a teaching result. With no pending decision, deliver the ordinary brief after merging. With a pending decision, deliver a STOP brief before dependent work or merge.
- **`chain`** requires `merge`; asked alone, treat it as both and say so. Apply the `merge` rules to each slice. Continue in the requested order, otherwise by "Picking the slice". Give one ordinary brief at the end of the chain. A pending decision or floor stops the chain at that boundary and triggers a STOP brief. Invented-behaviour counts apply per chain. Review rounds are counted per slice; a slice split from another keeps its count (see "Counting"), and a floor reached in any slice stops the chain. Paid live runs, as defined under "Paid live runs" below, are capped at 100 per slice and 100 in total across the explicitly requested chain (owner decision of 2026-11-21 on chadlis/hypotrail#75, comment 7067385973), unless Salah explicitly sets a different chain budget. Resume does not reset counters.

**Review rounds under `merge` and `chain`.** The round number alone does not revoke an explicit merge or chain authorization: up to five review rounds (see "Review rounds") can run before a slice reaches `main` without Salah reading it. What bounds it: merge still requires a completed review on the accepted head, passing required checks, no unresolved blocker, no unmet owner reservation and no other floor. Default mode still stops at an open PR.

**Learning and `prepare`.** Under the autonomous protocol, learning steps are skipped (D-001 on chadlis/hypotrail#75). Outside it, on `/drive #n prepare`, or when a step names a learning note (steps 7 and 9), read `.claude/skills/drive/learning.md` first: preparation mode, learning occasions, the slice note and its fields, and the learning anti-patterns.

**Changes to the apparatus are deferred, never applied** (except under the autonomous protocol, where the proxy decides them, or the owner instructs them, and they go on their own pull request). The apparatus is `.claude/**`, `AGENTS.md`, `CLAUDE.md`, `docs/agents/**` and scripts. Write the proposed diff into the brief.

**Paid live runs.** A live run is one invocation of a command that calls a real model, whatever its number of Episodes. At most 100 per slice (owner decision of 2026-11-21 on chadlis/hypotrail#75, comment 7067385973), each within the slice issue's bounds and written in the state comment with its reason. Before the first, a test runs the exact live command (same working directory, same arguments) with the provider patched, and exits 0. The test proves the arguments, not the launcher (D-029), so also run the live line's launcher with the command's `--help` from that working directory (for example `uv run python -m hypotrail run agent --help`), which calls no model, and record its exit 0 in the state comment. A run is repeated only after a technical failure, never to get a better result. When post-processing fails, rerun it from the kept log, never the call.

**Captures.** Run every command of a paid run, its offline post-processing included, through `.claude/skills/drive/capture.sh <kept folder>/commands <step> <command…>`, from the working directory the rehearsal used. The exact live command above is the command inside `capture.sh`: its arguments after `<step>`. In the same turn, post the `sha256sum` lines it prints in a new comment on the slice issue, since the state comment's `updated_at` moves with every edit, and link that comment from the state comment. Commit the captures with the outputs. These files are the commands' own output. An index you build from them later says so, and a test checks it against them.

**Only `capture.sh` holds the key.** A PreToolUse hook on Bash, `.claude/hooks/no-live-key.sh` registered in `.claude/settings.json`, unsets `HYPOTRAIL_ANTHROPIC_API_KEY` for every command, subagents' included, except a single simple command whose first word is `capture.sh`. A command anywhere else that tries `--mode llm_live` is refused before any call (D-048 on chadlis/hypotrail#75).

**Pre-run gate.** Before the first paid invocation of a slice, a fresh `slice-gate` reads every ticket criterion that must hold before or during the paid run (a verdict posted, a rehearsal, what is captured and where), each beside the evidence you name for it: a comment link, a test with its command and exit, a path. A criterion that holds during the run is answered against the `capture.sh` command that will run. It answers each criterion `met`, `not met` or `not witnessable`. Spend only when every answer is `met`. A `not met` is fixed and read again. A `not witnessable` goes to the owner-decision gate (under the autonomous protocol, the proxy) before the spend. The reading is a comment on the slice issue, and the state comment links it.

**Native primitives are his to leave.** Inspect owns the agent loop, its logs, retries and limits. scikit-learn owns fitting and preprocessing. SQLite owns read-only enforcement through `mode=ro` and its authorizer. Do not recreate what they provide, never parse an Inspect log by hand, never filter SQL with a regex. A slice that seems to need any of these departures is a floor.

## Autonomous protocol (owner decision, 2026-11-20)

Salah adopted this protocol on chadlis/hypotrail#1 ([end state and protocol](https://github.com/chadlis/hypotrail/issues/1#issuecomment-7043774378), with [1](https://github.com/chadlis/hypotrail/issues/1#issuecomment-7042941886) and [2](https://github.com/chadlis/hypotrail/issues/1#issuecomment-7043566976)). Its scope, in his words: « all work after #9's current state, until the end state is reached ». « The drive skill's owner-decision rules are amended accordingly »: where this section disagrees with another section of this skill, this section wins within that scope. Outside it, the rest of the skill applies unchanged.

- **`merge` and `chain` are implied.** One pull request per slice, with its review of record, squash-merged by you (« 2A »).
- **What still goes to Salah, as a STOP** (written as in "How a STOP is written", with its brief page): (i) live spending beyond the agreed budget, which is USD 80 in total across the remaining work (owner decision of 2026-11-21 on chadlis/hypotrail#75, comment 7067395129), on `anthropic/claude-sonnet-5-5`, on top of the cap of 100 paid runs per slice and the chain-wide cap of 100 under `chain` (owner decision of 2026-11-21 on chadlis/hypotrail#75, comment 7067385973; both caps still apply; going past either is this case); (ii) an irreversible act other than a pull-request merge (force-push on `main`, deleting a branch or an issue); (iii) the licence (AGENTS.md). The fourth owner-only case, (iv) changing a Reference to improve a score, is never asked: it is refused in every case.
- **The fifth owner-reserved case, (v) "end of #173's build, owner's demonstration"** (D-068 on chadlis/hypotrail#75, owner decision, 2026-11-22, as amended by D-088, owner decision, 2026-11-23). It is not a floor. When L2 is delivered, the run continues with chadlis/hypotrail#173: `/domain-modeling` first, then its slices under this protocol (D-088 on chadlis/hypotrail#75). When #173's build is delivered, you stop with a STOP brief that carries the L2 teaching page's link, a teaching page for #173 and the demonstration protocol, which covers both (D-088 on chadlis/hypotrail#75, amending D-068). While the owner demonstrates, the only work allowed is preparing the validation of L3's evaluation contracts and datasets, with nothing built (D-068 on chadlis/hypotrail#75). After the demonstration, each blocker the owner reports becomes an issue, and blockers that prevent a protocol task are fixed in a slice of their own, before L3 (D-068 on chadlis/hypotrail#75).
- **Every other owner decision goes to a proxy** (« Everything else goes to a fresh proxy agent »). That covers what "Owner decisions" sends to Salah, every floor that is not one of the cases above (the floor's record stays; the proxy decides what happens next), a pending `INFERRED` ticket the sources cannot settle, an owner reservation recorded before the protocol, an apparatus change (from `retro` or elsewhere), and the validation of each L3 Track's evaluation contract and dataset before it is implemented (end state, item 3).
- **Proxy procedure.**
  1. Write the decision in the log (below) before asking: the question, the sources, at least two options with their cost, their reversibility and what Inspect does for the same thing ("Inspect first"), and your own choice with its reason. Each fact about a file that a ticket-gate point states, or that an option of the entry states, gets the check of "Check the premise before you route", and an option whose premise the command contradicts is corrected or dropped before the entry is posted (D-065 on chadlis/hypotrail#75, item 3: "The premise check also covers the ticket-gate points and the options of a decision-log entry."). The command and its output go in the options file beside the option, as commands and outputs only, never your choice (D-065 on chadlis/hypotrail#75, item 3). Post that entry before you start the proxy, and never edit it: the readings and the decision go in a later entry that links it.
  2. Start a fresh `owner-proxy` with the question, the sources and the options, **without your choice or recommendation**, and without pointing it at the decision log. The options reach the proxy as a file that leaves out the drive's choice, and the proxy never fetches a decision-log comment that holds it. The state comment records the sealed entry's URL, which is never put in the brief.
  3. If the proxy chooses as you did, that is the decision. If not (including a new option of its own), start a second fresh `owner-proxy` with the same brief plus both argued positions, labelled A and B without saying whose each is. Its answer is the decision.
  4. Log it as « decision by proxy (Fable) » (« (Opus) » under the fallback below), never as Salah's, with every reading, its scope, its reversibility and the commits it allows. Name the model that served each proxy reading when it is known; a reading not served by Fable is recorded as such and not labelled « (Fable) ». When Fable is unavailable (its budget spent, or not yet available), start the proxy with a model override to Opus 5.5 (owner instruction, 2026-11-20: « s'il n'y a plus de budget Fable 5.2, utilise opus 5.5 »), and label the reading « decision by proxy (Opus) ». Each reading is posted word for word as its own comment on #75, and the decision links them.
  5. Before a Tightened line or a fix prompt quotes the decision, give each fact about a file that its conditions state the check of "Check the premise before you route". A condition the command contradicts goes back to a fresh `owner-proxy`, with the brief, the decision, the command and its output. Its answer is the decision, and the entry that logs it links the first. Each statement that the decision requires a text or a ticket line to make ("each says … that the Comparison stops being pending") is read the same way, against the decision's other items, the cases of the criteria that quote them, and the code the statement describes (`decide`'s writes, for "nothing else is written"). A statement that one of them contradicts goes back to a fresh `owner-proxy` in the same way. When the decision replaces a sentence, the fix prompt that applies it lists each occurrence of the replaced phrase that `grep -rnoE` prints over `src/`, `tests/`, `examples/`, `docs/`, `GLOSSARY.md` and `README.md`, beyond the copies the decision names, and asks for each.
- **Decision log.** One issue on chadlis/hypotrail, chadlis/hypotrail#75, linked from a comment on #1; one comment per decision. A slice's state comment links its entries. The log is what Salah reviews at the end. Every drive decision inside the delegation ("Delegated implementation choices") that a ticket line, a builder or a reader relies on is posted on the slice issue or on its ticket, and each slice gets one entry here, labelled "drive decision (delegated)", with its own D-number, posted once before the closing register and never edited, linked from the state comment, that lists every such choice by comment ID with its case and the lines it replaces. Each item of a choice says which case of "Delegated, for example" it is, or why it is none of the "Not delegated" cases. A choice that replaces an earlier one names it, and in the same turn every live ticket line that follows the earlier one is rewritten under the Tightened rule. `check_record.py` refuses the merge while a comment of the slice issue or of one of its tickets whose first line names the drive is absent from that entry.
- **Learning loop.** The protocol comment says learning notes and `hypotrail-study` suggestions are « not required by this run ». How this run applies that line is decision D-001 of the log: each slice's state comment says « learning steps skipped; learning records not read ».
- **Reports and briefs.** Each axis report of a review of record is kept word for word, for the final review: save the reader's hand-back to a file and post that file unchanged as its own comment on the slice issue (`gh api repos/chadlis/hypotrail/issues/<n>/comments -F body=@<file>`), under one heading line of yours: `## <slice>, round <r>: <axis> axis (review of record, <invocation>, base <sha>, head <sha>), its report word for word`; `check_record.py` finds the round by that line (D-065 on chadlis/hypotrail#75, item 6). A report over 65,536 characters is split at section boundaries into numbered comments, never trimmed. The ticket-gate reading (step 3) is kept the same way: its hand-back file, posted unchanged on the slice issue under `## <slice>: ticket gate, <tickets> (slice-gate, <model>), its report word for word`, split as an axis report is when it exceeds a comment. Your answers to it go in a later comment that links it. The routing comment links the reports and holds the routing table (D-065 on chadlis/hypotrail#75, item 4). No STOP outside the cases above. Ordinary briefs are short terminal notes. The brief page ("The brief page") is written once, at the very end, for the final review, covering the whole run and the decision log; a STOP for one of the cases above gets its own.
- **A missing `owner-proxy` type** (Preflight) is an apparatus floor that no proxy can answer: it is a STOP, whose remedy is a new session opened on `chadlis/hypotrail`.
- **Checks Salah reserved for the final review** (VS Code themes, Copilot chat, end state item 2): written in the slice's PR body as « owner check, final review », never claimed as passed.

## Floors

Each ends the run and produces the brief early:

- review round 5 ends with an unresolved finding routed to row 1 or 2, or an unresolved dispute about whether a finding belongs to either row. Stop after that review, before another correction. A fifth review with no unresolved blocker does not itself trigger a floor. A documentation-only finding follows "Documentation findings from round 5 on" and does not trigger this floor;
- the same preserved acceptance or regression check, tied to an accepted requirement, still fails after two consecutive completed fix attempts explicitly intended to satisfy it. Changing or deleting the check is not a fix. If the requirement or check is disputed, resolve that dispute rather than treating the result as evidence of non-convergence;
- an explicitly owner-set review/fix budget is exhausted;
- drive identifies a concrete reason why another bounded correction is not justified, such as incompatible requirements, repairs that reverse an earlier accepted decision, or an expanding change with no credible verification plan. Record the evidence and the decision needed. No numeric threshold must be reached before invoking this floor;
- a finding that fits no row of the routing table;
- two consecutive subagent failures on one step;
- a decision beyond your delegated authority (see "Who decides"). Name the limit it crosses, or the uncertainty the sources leave open. Weighing several options inside the delegation is not this floor;
- a **second** invented behaviour in the same run (per chain under `chain`);
- an apparatus change the slice cannot proceed without;
- leaving a native primitive;
- a paid live campaign beyond the slice issue's scope, or before Salah has reviewed the References.

### Review rounds

**Counting.** Round 1 is the first review of record. The two axis readers together make one round. A correction followed by a new review opens the next round. A disposition check or a targeted routing check on the same head belongs to the round in progress; it never stands in for a new correction-and-review cycle.

**Each reviewed head is on the remote.** Step 4 ends with the branch pushed to chadlis/hypotrail, and each later round's head is pushed before its review of record. A refused push is recorded with its message in that round's `Refusals:` line. A reviewed head stays on the remote as it was reviewed; if it must be rewritten, the state comment and the PR body name the lost SHAs and the tree comparison that replaces them (D-090 on chadlis/hypotrail#75, item 7).

**An anchor ticket is its own slice.** An anchor is a ticket with a criterion that no later ticket changes its commit (#127: "no later ticket of #120 changes it"). It is planned as its own slice at step 2, with its own round count. D-052 on chadlis/hypotrail#75: "a slice that reaches a floor is never split again to reset its count of review rounds."

**Five is a cap, not a target.** It is an experimental cap, to be re-evaluated with the data the routing comments and the state comment record (D-065 on chadlis/hypotrail#75, item 4). As soon as blockers and decisions are settled and the required checks pass, finish in the authorised mode, without further rounds. An empty report does not close earlier blockers that are still open. Never rerun an unchanged review in the hope of a kinder report.

**Fix attempts.** A fix attempt is a completed correction (committed, full suite run) that names the check it means to satisfy. Running the same command twice on the same head is not two attempts. A test kept red on purpose before implementation (test-first) is not a completed attempt. The check must test an accepted requirement, not a constraint the test invented.

**Budgets.** These rules create no numeric budget. If Salah set a specific review/fix budget, apply it, and if its consumption cannot be established, say so before the spending that depends on it. Unknown usage stays unknown.

**Round 3 checkpoint.** If review round 3 ends with unresolved blockers, record a short internal checkpoint: which accepted requirements remain unmet, and which earlier rounds had blockers citing the same requirement, what changed, whether a regression is demonstrated, the bounded correction scope, the verification plan, and any unresolved owner decision. If the next correction remains within delegated authority and no floor applies, continue without asking for routine approval, up to round 5. The checkpoint uses the existing reports and state comment. It does not create another standing reviewer or a separate approval ceremony.

**Diagnostics, not floors.** Repeated file paths, counts that do not decrease, and lines that `git blame` attributes to the previous fix are recorded as signals. They can support the judgement-based floor above, with its evidence. None of them stops the run on its own.

**Documentation findings from round 5 on.** Bounded delegation adopted by Salah on 2026-11-06 (chadlis/hypotrail#8, comment 6690134319, point 4; readings confirmed on 2026-11-07). From review round 5 on, a finding that touches documentation only (handbook, docstrings, comments, README), with no behaviour change, is fixed by a `slice-builder` and verified by the axis reader that raised it (continued, otherwise a fresh `slice-gate` given that axis). The verification also confirms that the fix diff changes no behaviour, and checks each citation the fix adds against its quoted source. No new full round runs and the floor is not triggered. Of code findings, the path covers only a rename of a test identifier that changes no behaviour, verified by the axis reader that raised the finding together with the diff; that verification also greps the tickets and the docs for the old name, and the routing row says "documentation" in the `row` cell (for example `1 (documentation: test rename)`), so that the record check asks for its verification comment (D-061 on chadlis/hypotrail#75, as amended by D-063 on chadlis/hypotrail#75). It never covers any other code finding, under `src/` or `tests/`, nor `GLOSSARY.md` or an ADR line (D-061 on chadlis/hypotrail#75, as amended by D-063 on chadlis/hypotrail#75). The drive posts one verification comment per reader, headed `## <slice>, round <r>: <axis> verification` with `<axis>` `Standards` or `Spec`, and the record check looks for exactly that form. The PR body names the commits verified this way, apart from those a review of record covered.

### After a floor

A floor ends with the STOP brief and a concrete recommendation. It is never a request for Salah to debug.

Every owner decision gets its own dated comment on the slice issue: his words quoted, the option text he chose quoted from the brief, its scope, any budget, and the commits it allows. Any consequence or summary of yours goes under a separate « Drive reading » line. The state comment links it. Steps 7 to 10 then run as usual, and the PR body names the floor.

Review counters, fix attempts per check, open findings, unresolved decisions and floors survive resumes and history rewrites. A new review or a session restart cannot erase an earlier floor, and a later change to these rules does not lift a floor already reached: that needs Salah's explicit answer.

Under `chain`, finish the slice in hand if it can be finished honestly, then stop. Ending a run is not a failure. Grinding past a floor under `merge` produces a `main` nobody can throw away.

## Who decides: delegated choices, owner decisions, learning occasions (in `.claude/skills/drive/learning.md`)

Salah wants system-wide orientation, participation in consequential choices, and deep practice on a few transferable mechanisms. He does not follow every implementation detail. Keep the delivery and learning loops separate. A lesson, chapter or unanswered recall exercise never becomes a merge gate. Every choice is either delegated to you or an owner decision. A few choices are also learning occasions (`.claude/skills/drive/learning.md`), which changes neither who decides nor when.

**Inspect first** (owner instruction, chadlis/hypotrail#8 comment 6677520862). Before you recommend a design choice, to Salah or as a delegated decision, read how the pinned `inspect-ai` (version in `pyproject.toml`) implements the same thing, in its installed source. State in the recommendation what it does, with the file, and whether you follow it or depart from it, and why. When Inspect has no counterpart, say so. Inspect's behaviour is an input, never a binding rule: ADR 0001 keeps scoring in Hypotrail.

### Delegated implementation choices

**Decide and continue** when the choice keeps to the accepted contract, stays inside the authorised budget and scope, meets no owner reservation or other floor, and can be verified by suitable checks. That the repository does not prescribe an implementation detail does not make it a product decision. Record a structuring choice briefly in a comment of the slice issue or of its ticket, with its reason, limit and reversibility, and list it in the slice's "drive decision (delegated)" entry of the decision log ("Decision log", under "Autonomous protocol"). An ADR only when the routing table asks for one.

Delegated, for example: repairing incomplete validation so that it meets an already accepted requirement, renaming an internal symbol, choosing the structure of a test. Not delegated, however easy to code or to undo: changing the scope of a public refusal, a methodological guarantee, an evaluation protocol that is not settled, the name or shape of a field in a record that a Study persists (anything a Study writer writes), a gap a decided definition leaves in a public contract, even when filled with that decision's own rule, or a reading that reconciles two accepted requirements an axis reader reports in conflict. That reading goes to the owner-decision gate (under the autonomous protocol, the proxy) before any fix is delegated.

### Owner decisions

Ask when the choice touches a limit that is not delegated: product goal, scope, public guarantees, an unsettled methodological trade-off, hard-to-reverse effects, spending not authorised, or a choice Salah reserved. The other floors still apply, whatever their teaching value. The brief says precisely what existing authority cannot settle, the consequences, the viable options and the recommendation. An implementation preference, or the ordinary uncertainty of a technical choice, is not enough. Reuse earlier decisions whose scope still covers the case.

When the same category of question recurs, propose a bounded delegation (its conditions and exclusions) inside a brief that is already due. It holds only after an explicit instruction. Once adopted, it saves asking the same permission for each occurrence. Silence is never authorisation.

An owner-reserved decision is different from a learning suggestion. Salah reserves a choice explicitly, in a product instruction or a `before` session, with its scope. Record that scope and the answer required in its own dated comment on the source issue, linked from the state comment. Stop before implementing work that depends on it, including under `merge` or `chain`. Continue independent work only within the already authorized slice. A reservation does not lapse with time or silence, and an Anki score or a completed lesson is never the answer. If the owner explicitly delegates the decision, record that delegation and apply the stated bounds.

Unsettled product semantics, public contracts or hard-to-reverse choices follow this owner-decision gate even if the owner did not reserve them for learning. Routine reversible choices do not acquire a new gate merely because they illustrate a concept.

## The banner: first line of every turn, in French

```
▶︎ EXÉCUTION — rien à décider
```

```
⏸︎ STOP — j'ai besoin de toi · <ce que tu dois produire> · ~<n> min
```

- At most one STOP per turn, and a STOP turn carries nothing else.
- Running a command, even a long one that can fail, is EXÉCUTION.
- Under the autonomous protocol, only its four owner-only cases (live spending beyond the agreed budget, an irreversible act other than a pull-request merge, the licence, and a change of a Reference to improve a score, which is refused rather than asked) and case (v), "end of #173's build, owner's demonstration" (D-068 on chadlis/hypotrail#75, as amended by D-088), qualify for a STOP; see "Autonomous protocol".
- Otherwise, only these qualify for a STOP: an owner decision as defined in "Who decides" (including an explicitly owner-reserved decision), something irreversible beyond the mode's floor, a floor being hit. A choice inside the delegation is not a STOP. Optional learning preparation ends normally and is not a STOP.

A STOP explains from scratch: what the thing is, why it is on the table now, the options with what each costs, what you already checked, and what answer you need (« 1A ou 1B », « PASS ou corrections »). Assume he remembers no earlier turn, decision or slice. **Every doubt carries at least two options and an argued recommendation.** Never infer PASS from a missing option or an absent answer. Distinguish a routine information brief from a STOP that requires an owner decision.

### How a STOP is written

Salah asked for this level of explanation for every decision he is asked to take. Each decision point is self-contained, in this order, each part a short labelled paragraph or a short list:

- *Contexte*: what the thing is, where it comes from (issue, amendment, specification section, ADR) and why it matters to the project. Define every term on first use: spike, scorer, Inspect, a check's number, a limit's purpose. Never point back to an earlier turn, decision or slice: quote the decision with its date and link.
- *Ce qui a été fait*: what the code, the ticket or you did, and what you checked yourself.
- *Le problème*: the gap and its consequence, by its mechanism (what goes wrong, for whom, when).
- *Options*: at least two, each with what it costs.
- *Recommandation*: one option, argued from the sources, with what Inspect does for the same thing (see "Inspect first").

A decision brief opens with a framing section: what the slice is for, what was done, and why he is being asked now.

Writing style, in French: descriptive and explicit, never condensed or literary. Say plainly who does what. Visible connectors (« Premièrement », « Autrement dit », « En revanche »), the colon to unfold a statement, French quotation marks « ». No em or en dash in the body (the banner keeps its own), no semicolon, no emphatic vocabulary. English technical terms in italics on first use, with the French equivalent when one exists. Reference: the `style-redaction-salah` skill, sections 1 to 4.

## Where the state lives

**Unconditional authority check, including resumes.** Before dependent implementation and again before merge, read the current source issue and parent, their new comments since the last verified state, the linked slice notes, selected learning objectives and relevant `before` records. If no reliable checkpoint exists, read all relevant comments. Reconcile newly reserved, decided or delegated choices with the current contract. Record the last checked owner evidence and source excerpts in the state comment. Reading only that comment or Git is insufficient. A preparation session can have added a reservation after the preceding execution stopped.

The slice issue carries **one state comment** that you create at step 1 and edit at every step. It has one line per step, with the date and the evidence that closed it: a commit, an exit code, a verdict, a link. It survives the session. Because it is edited, it is an index, never the only copy: a decision, a finding ID or a gate reading lives in its own comment and the state comment links it. Step lines are added, never merged. Under `chain`, also keep the chain's starting issue, links to its completed slices and the cumulative paid live-run count. Restore that count on resume rather than treating the current slice as a new budget.

When a comment of yours replaces another, post in the same turn the correction of every comment that names the replaced comment's ID, on the slice issue, on its tickets and on the issue the replaced comment sits on; list them on each of those issues with `gh api --paginate repos/chadlis/hypotrail/issues/<n>/comments --jq '.[]|select(.body|contains("<old id>"))|.id'` (D-090 on chadlis/hypotrail#75, item 6).

From the first review of record on, each round's routing comment (`## <slice>, round <r>: routing`) carries, for that round (D-065 on chadlis/hypotrail#75, item 4):
- the reviewed base and head;
- raw and deduplicated finding counts by routing row, and the cited paths;
- pre-existing defects, incomplete fixes and demonstrated regressions, and for rounds 4 and 5 the defects resolved and introduced;
- `Changed:` what the correction since the last reviewed head changed, from `git diff --numstat <base> <head>`: lines under `src/` and `clients/*/src/`, under tests only, in other text only, or `none`;
- the models actually used if known, the available token or cost telemetry and durations (unknown stays unknown);
- the auto-mode refusals of hook-rewritten commands that the hand-backs list and those of the drive's own commands (the cost D-048 on chadlis/hypotrail#75 accepted);
- each human interruption, its reason, and whether the existing delegation could already have settled it.

The last three items are four lines, each starting with its label and giving a value: `Models:`, `Telemetry:` (tokens, cost, durations), `Refusals:` and `Interruptions:`; `Models:` and `Telemetry:` may say `unknown`, while `Refusals:` and `Interruptions:` say `none` or list the entries, since you know them (D-065 on chadlis/hypotrail#75, item 4). `check_record.py` refuses the merge while a routing comment lacks one of them, for every slice but those merged before that change (D-065 on chadlis/hypotrail#75, item 4).

The state comment carries one line per round linking its comment, the open IDs of the **findings register** (see "Routing findings"), the human interruptions and the defects found after acceptance. Edit it in the same turn as each routing comment, decision-log entry and pull request, never later (D-065 on chadlis/hypotrail#75, item 4).

Defects found after acceptance are added when someone reports them. This record is what will be used to re-evaluate the five-round cap. Build no other tracking for it, and open no issue to hold it.

On start, read it, then **check it against the repository** before trusting it:

```bash
git remote get-url origin
git branch --show-current
git status -s
git fetch -q https://github.com/chadlis/hypotrail main
git log --oneline FETCH_HEAD..HEAD
```

The repository is `chadlis/hypotrail`. If `origin` points elsewhere (a cloud session can attach an unrelated repository under the same folder name), never push there: push with `git push https://github.com/chadlis/hypotrail HEAD:<branch>`, say so once, and treat the stop hook's unpushed-commits warning as expected.

Use Git to verify technical execution state. Use the current accepted contract and explicit owner instructions to verify authority. Code that disagrees with the contract does not silently amend it. Reconcile the state comment with both sources and say what disagreed.

## Picking the slice

With `/drive #n`, the slice is `#n`. With a bare `/drive`:

1. **A slice already in progress wins.** An open issue with label `in-progress` and a state comment is resumed.
2. Otherwise take the **first startable slice**: an open sub-issue of the open milestone (the oldest open parent issue whose title starts with `L<n>`), in sub-issue order, whose blockers are all closed. Blockers are declared only by the issue's first line, `Blocked by: #a, #b`; GitHub's native dependency links are not used in this repository.
3. If no slice is startable, the run ends: say which slices are open and what blocks each. This is not a STOP.

Announce the pick in an EXÉCUTION turn: « je prends #n (<titre>), parce que <raison> ; pour une autre : `/drive #m` ». Never ask him to choose. Picking by size or by what looks easiest is not a reason.

## Architecture review (owner decision, 2026-11-21)

A review of record reads one slice's diff. Drift across slices (parallel modules that diverge, one change scattered over many files, a check written three times) is read by a separate **architecture review** of the whole codebase.

**When.** Between slices, never inside one, at these points:
- at every milestone boundary, before the first slice of the next milestone starts;
- once more after L2.1 (#104) merges.

A pending architecture review comes before « Picking the slice ».

**Steps.**
1. **Two readings, in parallel.** Each is a fresh `slice-gate`, reading `src/`, `tests/`, `GLOSSARY.md` and `docs/adr/` at `main`'s head. Neither prompt names a candidate, and neither reader sees the other's report.
   - **Depth.** The first reader follows `~/.claude/plugins/cache/*/mattpocock-skills/*/skills/engineering/improve-codebase-architecture/SKILL.md` up to its HTML report, and stops before the grilling step. Its candidates are named in the vocabulary of `mattpocock-skills:codebase-design`.
   - **Coherence.** The second reader applies the Standards brief and the smell baseline of `mattpocock-skills:code-review`, using that skill's text, to the whole tree instead of a diff. It looks for parallel modules that diverge, a rule written in several places, and one change scattered across many files.
   - Each candidate names its files, the problem, the proposed change, its cost, and whether a test can enforce the rule.
   - **Done** when every module under `src/` has been read and is named in each report.
2. **Evidence.** Check each candidate's premise with one command, as under "Routing findings". A candidate the command contradicts goes back to its reader.
3. **Record.** One issue, label `needs-triage`, lists the candidates of both readings with their evidence and which reading raised each. Both reports are posted on it word for word, split as under the review of record when one exceeds a comment. Publish the depth reader's HTML report as an artifact and give Salah its link. This review's readings and decisions are recorded on that issue and on #75, not on a slice issue.
4. **Choice.** The `owner-proxy` stands in for the grilling. It picks which candidates to do now, later or never, in one decision-log entry, with a sealed drive choice posted first. It also decides each open `needs-triage` issue a review of record filed (#106, #114 and #115 today). A check such an issue proposes is a fitness-test candidate.
   - A candidate that changes a public contract (a command's output, a refusal, a record format) is a product decision, not a refactoring. It goes to the owner-decision gate.
5. **Refactoring slice.** The candidates picked for now become one slice under the current milestone, driven like any other: tickets, ticket gate, build, review of record, merge.
   - Its tickets state that behaviour is unchanged. The full existing suite is the witness.
6. **Fitness tests.** A rule that a test can enforce (an import boundary, one check order shared by every writer, a duplication bound) becomes a test in `tests/test_architecture.py`. It is shown red once on a planted violation. The architecture is then checked on every commit, not only at the next review.

**Bounds.** No paid live run. At most one refactoring slice per review. The review's counters go into the state comment of the next slice.

## Preflight: before step 0 and on every resume

1. The checkout is `chadlis/hypotrail` (`git remote get-url origin`, or the fallback push in "Where the state lives").
2. `slice-planner`, `slice-gate` and `slice-builder` are among the subagent types this session offers, and `owner-proxy` too under the autonomous protocol.

If either fails, stop under the apparatus floor before reading the slice. The STOP says that agent types load from the checkout's `.claude/agents/` when a session starts, so the remedy is a new session opened on `chadlis/hypotrail`. `prepare` needs only point 1.

## Step 0: briefing

When there is no state comment yet, read the following yourself and say what each told you:

1. the slice issue, then its parent (the milestone and its amendments, which override the original specification);
2. the specification sections the slice cites, quoted from the kit the parent links to;
3. `GLOSSARY.md` and the ADRs the slice touches;
4. the slice's blockers: are they closed?

Then brief him in French in four short sections: **Ce que la tranche livre**, **Ce qui est déjà tranché** (with the rejected alternative), **Ce qui bloque ou manque**, **Ce que le modèle risque d'inventer**.

If a blocker is open, say which and stop implementation. Preparation, which writes only its note and comment, may still proceed when explicitly requested, with unresolved dependencies identified. Check owner-reserved decisions and any linked preparation evidence before starting dependent work.

## The loop

| # | Step | Who | Done when |
|---|---|---|---|
| 1 | Branch from an up-to-date `main` (the branch the session imposes, otherwise `slice/<n>-<slug>`). Create the state comment; add label `in-progress` | you | `git branch --show-current` |
| 2 | `to-tickets` on the slice issue: tracer-bullet tickets as sub-issues of the slice, each starting with a line `Blocked by: #a, #b` (or `Blocked by: none`) instead of native dependency links; each ticket that changes behaviour has a criterion that the handbook chapter describes the change, its prose restating no table row, and that any README line it affects is updated, in the same pull request (ADR 0003, AGENTS.md) | `slice-planner` | the tickets exist |
| 3 | **Ticket gate**: does any ticket promise more or less than the slice issue, the parent's amendments and the cited specification sections, or state something no test can witness? Does a criterion say that a set of code is complete or closed ("the one refusal this ticket adds", "every writer", "no other code") without a witness that lists that code mechanically and compares it with the test's list both ways ("A criterion that quantifies over code", below the table)? That clause is a witness « none ». Does a ticket contradict a line of an ADR under `docs/adr/`? The gate reader reads the ADRs the ticket cites, and greps the others for the commands, records and refusals the ticket changes. A contradiction is reported `contradicts ADR`, and the ticket gains a criterion that adds the ADR's dated line. Does a fact a ticket states about a file hold? The gate reader checks each such fact with a command (`grep -n`, `sed -n`) and reports a false one as `premise false` (D-065 on chadlis/hypotrail#75, item 3: "The premise check also covers the ticket-gate points and the options of a decision-log entry."). Does a live line state a property without a condition while a case of a criterion of the slice's tickets contradicts it ("the Comparison then stops being pending" beside a case where "a Decision that cites it and does not apply" leaves it pending)? The gate reader reads each unconditional statement of a ticket against every case list of the slice, and reports a contradiction as `contradicts criterion`, both lines quoted. Does a ticket's live text name a concept with a word its `GLOSSARY.md` entry lists under _Avoid_ (builders copy ticket sentences into code, docs and tests)? Text quoted from a source, and « paid live run » where it names the budget unit this skill defines, are exempt. A criterion that asks prose to name what a table lists is marked `INFERRED`. Each doubted ticket is marked `INFERRED`. Then, across all tickets: name each parent amendment or specification rule that governs the slice's inputs or outcomes (for example "every abnormal outcome carries a **Reason**") and the ticket whose criteria witness it; a rule no ticket witnesses is `UNCOVERED` | `slice-gate`, fresh | its reading is posted word for word, every governing rule mapped to a ticket or marked `UNCOVERED` |
| 4 | You follow `implement-spec` on the slice as its orchestrator: every implementer and merger it starts is a `slice-builder`. With at most two tickets, `implement` per ticket, each in one `slice-builder`. Affected product documentation is part of the work: the handbook (`docs/handbook/`) describes what changed and the README is still true | you, then `slice-builder` | tickets resolved, full test suite green, each criterion's witness shown red in a builder's hand-back, affected product documentation complete; the branch pushed to chadlis/hypotrail ("Each reviewed head is on the remote", under "Review rounds"); the red runs the tickets name and every witness a ticket or decision gives to the pull request are posted word for word from the hand-back as one comment on the slice issue, `## <slice>: witnesses outside the diff, from the builder's hand-back`, before round 1, and the PR body links it once the pull request is written (step 8). A routing row whose requirement is a PR-body line is checked in round 1 against that comment; it keeps the words "PR body" and takes no settled status until the PR body names its finding ID. When no reader raises a row, nothing mechanical holds the PR-body line: writing it in the PR body stays a prose duty; for a ticket with a user-facing surface, the builder's hand-back links the sheet that `verify-panel` (`.claude/skills/verify-panel/`) produces on its head, and the UX review and the Spec reader receive that sheet |
| 5 | **Review of record, round 1**: you invoke `/mattpocock-skills:code-review main`, bare; each axis reader it starts is a fresh `slice-gate` | you, then 2 × `slice-gate` | each axis report posted as its own comment from the hand-back file and linked from the routing comment (D-065 on chadlis/hypotrail#75, item 4); each finding entered in the register, its ID assigned only in the routing table |
| 6 | Route each finding through the register (see "Routing findings"); fixes go to `slice-builder`, each prompt naming its finding IDs, their cited paths, and what stays as it is (other commands, other Tracks, work filed for later; a prompt that rewrites text a ticket criterion governs quotes that criterion under "what stays as it is"), and saying the finding IDs are for the commit message and hand-back; a prompt that adds or removes a witnessed case, or changes a stated behaviour, first follows "A fix rewrites the ticket lines it makes stale", below the table; the prompt also asks the builder's hand-back to list every file touched beyond those paths. Each fix prompt is posted by `.claude/skills/drive/post_fix_prompt.sh`, before the builder starts; it posts nothing while `premises.py` or `fix_prompt_check.py --strict` refuses the prompt (see "Check the premise before you route"); where the session refuses its `gh api` post, `--out <file>` writes the comment, which you post unchanged and check with `post_fix_prompt.sh --compare <comment id> <file>`; the hook's own run at the Agent call ("Quote a decision whole") is added to that comment only when its warnings differ (D-090 on chadlis/hypotrail#75, item 2); the routing comment of the next round links it (D-065 on chadlis/hypotrail#75, item 4). A round whose correction no `slice-builder` prompt made (your own ADR or glossary line) is headed `## <slice>, round <r>: fix prompt: none, because …` instead. Every `slice-builder` delegation between round r's routing and round r+1's review is round r's correction, whatever starts it (a finding, a UX review, a new ticket's build): its prompt contains "This is a review fix", names the finding IDs it serves, and is posted under round r's fix-prompt heading before the builder starts. `check_record.py` refuses the merge while a round followed by another, or whose documentation fixes a verification reads, has no such comment holding that phrase and a `--strict` line with no warning. After posting each routing comment, run `python3 -I .claude/skills/drive/check_record.py --slice <n>` and settle each reason it prints before the next delegation. Where this skill already has a reader verify a fix (round-5 documentation fixes, a correction decided at a floor), that reader also confirms the fix's diff changes no behaviour outside its finding; in rounds 1 to 4 the next review of record reads the fix's diff. No new reader is added. A correction followed by a review opens the next round: `/mattpocock-skills:code-review <head of the last reviewed round>`, bare. Checkpoint after round 3, plan before rounds 4 and 5, and stop at any floor (see "Review rounds") | you, then subagent | every finding fixed and verified, refuted with evidence, linked as a duplicate, or escalated; the accepted head is named |
| 7 | Learning notes and links: update concise slice notes in `chadlis/hypotrail-learning` (`notes/<slice>.md`, direct push, with the learning-storage fallback of `.claude/skills/drive/learning.md`). The PR names which acceptance tests (T-xx) it proves | `slice-builder` | learning notes are saved or preserved in the named fallback |
| 8 | PR, body shaped by `/pr`, closing the slice's tickets, not the slice. After the last round, edit the state comment: it names the accepted head and every deviation | you | the PR exists, and its body names each deviation the state comment records |
| 9 | Finalise and link the slice note, retaining preparation and owner decisions. Enrich a selected learning issue only if one exists. Create no learning issue. Offer `after` with the selected learning issue, or with the qualified source issue if a later session is wanted | you | note/fallback linked, existing selected objective updated or explicitly none |
| 10 | `retro` on this session: a suggestion becomes an apparatus diff once a second slice shows the same failure, otherwise it is kept as a candidate in the retro's comment, from the retro after L2.5's on (L2.5's retro, whose adopted proposals 1a, 2a, 4c, 5 and 6 rest on that slice alone, is the exception D-105 on chadlis/hypotrail#75 names); the retro also lists the rules of `SKILL.md` that fired in none of the last three slices, and the apparatus pull request keeps `SKILL.md` at or under 14,775 words (`LC_ALL=C wc -w`) | `slice-planner`, with a model override to Opus (D-063 on chadlis/hypotrail#75) | its list comes back, with the review of record's recall: of the defects found after round 1 by another reader (the UX review, the owner, a later slice), how many a review of record raised and how many it kept open |
| 11 | Check pending decisions and authority. Default mode: give the brief with the open PR and stop. `merge`/`chain`: a pending decision gets a STOP and waits. Step 11 ends with a separate closing register comment, which lists every ID with its final status and a link. Continue to step 12 only with a completed review on the accepted head, required checks passing, no unresolved blocker, no unmet owner reservation and no other floor | you | no unresolved decision or blocker is passed over |
| 12 | *(`merge`)* `.claude/skills/drive/check_record.py` runs before the merge tool, `gh pr merge` and `gh api …/pulls/<n>/merge`, and refuses the merge (exit 2) while the state comment's round count, a routing comment for each round (headed `## <slice>, round <r>: routing`), the round-5 verifications of the documentation path, the four lines `Models:`, `Telemetry:`, `Refusals:` and `Interruptions:` of each routing comment of a slice merged after D-065 on chadlis/hypotrail#75, item 4, the closing register comment, a status that settles each `behaviour, no line` row in it, a PR-body line the register promised, the ID, in the slice's "drive decision (delegated)" entry on #75 that the state comment links, of each comment of the slice issue or of one of its tickets whose first line names the drive, for a slice merged after T1 (chadlis/hypotrail#150) (D-076 on chadlis/hypotrail#75, item 2), a `## <slice>, round <r>: fix prompt` comment for each round followed by another, for a slice merged after L2.3 (chadlis/hypotrail#159), and for each round a documentation verification reads, after L2.5b (chadlis/hypotrail#186), or, for a requirement with row-1 findings in two rounds, a line `Structural option for <requirement>: …` or `Gate for <requirement>: D-nnn` in the routing comment of its second round or a later one (D-063 on chadlis/hypotrail#75) is missing (a row's status is the one in the latest routing or closing register comment that lists its ID, so the closing register settles a row the routing comment left open and no other comment settles one), or, after L2.5b, while a table row of a routing or register comment holds no finding ID the check reads; a pull request titled `drive:` that changes no file under `src/` or `examples/` and names no slice issue (the subject's `(#n)`, the body's `Part of #n` or `Slice … (#n)`) is an apparatus pull request and passes with a note; once a slice issue is named, the record check applies whatever the title (D-055 on chadlis/hypotrail#75, item 3). Squash-merge with subject `feat: <what the slice does> (#<slice>)`, close the slice, add the squash SHA to the note and any already linked selected objective. Give the ordinary brief now, or once at the end under `chain` | you | merged state and learning reference are truthful |

You tighten the slice's tickets once, after the build, so that their live lines describe what was delivered; no gate reading of that tightening follows. A tightening goes in a dated `## Tightened` section of the ticket body, because a body is read without its comments, and only the history it replaces leaves the body, for a history comment of the ticket (the move rule below); edit a local copy of the body (`docs/agents/issue-tracker.md`, « Changing part of a long body »). A line without a source is your decision: it goes to brief item 2, not into the ticket. A vocabulary correction moves the whole sentence, by the move rule below, and writes the corrected sentence after its pointer, never a "read X as Y" line; text you write into an issue (slice body, amendment, decision log, state comment) uses `GLOSSARY.md` terms the same way; « paid live run » as the budget unit this skill defines is exempt everywhere until #82 is settled.

An `UNCOVERED` rule is tightened into the ticket that owns the input it governs, quoting the rule. For a refusal rule, the tightened criteria list the neighbouring cases of "Fixing a family of defects".

A criterion that quantifies over code ("every Study writer", "each path", "every check before the lock") names a witness that lists that code mechanically and compares it with the test's list both ways, as #127's parser walk does for leaf commands. When no mechanical listing can be built, the Tightened line says why and the criterion is marked `INFERRED`; a criterion whose completeness is left to "the review of record" has no witness, so it counts as a witness « none » (D-063 on chadlis/hypotrail#75, item 3). When the quantifier ranges over uses of a name (calls through any alias, receiver or import), no static listing is complete: the Tightened line names the conventions that bound it and quotes D-054 on chadlis/hypotrail#75 word for word: "**Stop rule.** A later escape that code under `src/` actually uses is a blocker. An escape that is only planted is a stated limit, written down in the test's docstring and in the PR body."

Every Tightened line names its witness: the test or kept file that would show it holds, or « none ». At the ticket gate, each clause of a criterion that states a property names its own witness and the grain at which that witness holds; a clause without one counts as a witness « none », not only marked `INFERRED` (D-061 on chadlis/hypotrail#75, as amended by D-063 on chadlis/hypotrail#75). A grain in a ticket line written or rewritten from now on names its unit and the list that unit ranges over ("one call per row of the matrix in TA-U4"), never a total of the cases the witness lists (D-090 on chadlis/hypotrail#75, item 3, which narrows the reading of "grain" in D-061 and D-063). Any live line a Tightened line replaces or narrows, in the body or in an earlier Tightened section, moves to a history comment of the ticket (`## <ticket> history, <date>`, one per tightening, its lines struck), posted first, and in the same turn the body edit puts a pointer `(replaced by <Tightened ID>: history, comment <id>)` in its place, so the body holds only live text. A move covers a whole sentence or list item, never a clause, and the replacing line restates in full what stays live. A Tightened line cites a source outside the ticket: a decision-log entry by comment and point, any other source by its sentence, quoted; a correction whose only source is another Tightened line of the same ticket is a rewrite of that line, made in place, keeping that line's source.

Between steps 3 and 4, a ticket that touches `.github/workflows/` has that change built first, as its own commit, and pushed at once. A push refused for the `workflow` scope is recorded with its message, and you ask the owner in one line to push that commit. The refusal is an access limit; the owner's push is the only way past it, never another tool or token (the contents API, the MCP `push_files` or `create_or_update_file`). That request is not a STOP case and carries no decision. Work that does not depend on the file continues, and a merge that depends on it waits at the open pull request, recorded under `Interruptions:` (D-090 on chadlis/hypotrail#75, item 10).

**One gate reading, then the build** (D-114 on chadlis/hypotrail#75, owner decision, 2026-11-24). D-114 supersedes the regimes of D-101, D-102 change 4 and D-110. Every slice gets one ticket-gate reading (step 3), then its build, and the tickets as live are the build's mandate. The reading's findings go to the builder as known traps; a point it leaves open in a public contract, refusal, record or package is decided in the log before the build. A contradiction between tickets found while building is a builder hand-back, answered inside your delegation or by proxy and posted on the slice issue. Tickets cite decisions as `D-0nn on chadlis/hypotrail#75, comment <id>, <point>`, not quoted, and hold no closed "and no other" list of tests or lines; the builder may change existing tests and fixtures, each listed with its reason in its hand-back. Its fixed limits stand in every slice: "the public contracts, refusals, records and packages a ticket does not name change only through a decision of this log; the owner criteria keep their tests; the review of record (up to five rounds) and the UX review of user-facing slices (D-106) run as before."

A slice with a user-facing surface (L2.5, L2.7, each such slice of #173) gets the UX review of D-091 on chadlis/hypotrail#75, as D-098 extends it. It runs on the build's head before round 1: its findings enter the register as round-1 findings, routed in round 1's routing comment beside the two axis reports, and its report is posted word for word as its own comment on the slice issue; the rerun on the fix's head stays (D-106 on chadlis/hypotrail#75, owner decision, 2026-11-24, amending D-091 and D-098 item 2: "Run the UX review of D-091 on the build's head **before round 1**, and enter its findings in the register as round-1 findings. Keep the rerun on the fix's head.").

Complete affected product documentation before the first review of record. When the handbook lists what the code defines (codes and the details each carries, declaration keys, limits, which entry point reads what), it is a table whose rows carry data attributes, and a test in `tests/test_handbook.py` compares each row with the code that defines it, as `test_the_sheet_limits_are_the_effective_values_with_their_state` does for the spike's limits. Prose around such a table may name a row to point at it, and says only what no row says. Step 7 finalises learning notes and links. Any later change affecting product behaviour or its documented contract requires appropriate verification and review before acceptance.

`implement-spec` runs its own `code-review` from the author's side. That is hygiene. Step 5 is the review of record.

**A fix rewrites the ticket lines it makes stale.** When a fix prompt adds a case to a witness or removes one, or changes a stated behaviour (what a branch accepts, refuses or gives back), search the slice's live ticket bodies and `docs/handbook/` for that witness's `Grain:` line and for each sentence that states the behaviour. Before the builder starts, rewrite each stale ticket line. The Tightened rule governs only the move, the history comment and the cited source: the rewritten line does not go back to its `slice-gate` before implementation, because the next round's Spec reader reads it live. A line that no source outside the drive settles goes to the owner-decision gate. The prompt lists each handbook occurrence under its finding (D-090 on chadlis/hypotrail#75, item 1).

## Routing findings

A citation and a line number support investigation, but do not by themselves establish a valid finding. Missing behaviour may be cited without an existing implementation line. A finding that only proposes an improvement is out of scope, whoever raised it.

**Check the premise before you route.** When a finding states what a file holds (a declaration present or absent, a value, a line), run one command that shows it (`grep -n`, `sed -n`) before the finding gets a row, and put the command and its output in the register's evidence column. A premise the command contradicts goes back to the reader who raised it as a disposition check, never into a fix prompt. Every fact your own fix prompt states about a file gets the same check. A fix prompt that says who calls a function carries a line `callers(<package.module.function>) = {<package.module:function>, …}`, and `python3 -I .claude/skills/drive/premises.py <prompt file> <worktree>` compares it with the callers that `tests/_architecture.py` finds; it exits 2 on a difference, and on a sentence of the form "called from … only" that has no such line. The prompt is posted only when it exits 0, and the sheet it prints goes under the prompt (D-055 on chadlis/hypotrail#75, item 2). A fix prompt that says a test checks some code ("checked by", "checked at runtime by", "covered by" a test) carries a line `checked_by(<package.module.function>) = {<tests/file.py::test_name>, …}`: `premises.py` extracts `HEAD` of the worktree into a scratch folder, makes that function raise on entry there and never in the worktree, runs each named test with `<worktree>/.venv/bin/python` and `PYTHONPATH=<copy>/src`, and exits 2 when a named test still passes, on a "checked by … test" sentence that has no such line, and, with a message of its own, when the runs do not end within 90 s (D-065 on chadlis/hypotrail#75, item 2). A test that fails only with the plant shows that it reaches the function, not that it asserts the claimed property (D-065 on chadlis/hypotrail#75, item 2). When a finding states an absence or hedges ("does not seem", "looks like"), that is the premise to check: run the command over the whole span the absence claims (for a call path, every function on it) and quote its output; a check of the finding's other facts leaves the premise unchecked. Every citation a fix prompt asks for carries its quoted source sentence; with none to quote, the prompt asks for none.

**Quote a decision whole, with its verbs.** A fix prompt that applies or cites a decision item (a decision-log entry, a Tightened line) quotes the whole item, each bullet as its own quotation, never one sentence of it. For each row, test or case the item touches, the prompt says `add`, `replace` or `remove`, and names under "what stays as it is" each existing one it keeps. A fix prompt asks the builder to add no explanatory prose and dictates no wording (a docstring, a comment, a heading's text), unless a criterion or a decision requires that text; the quoted source sentence of a citation that a requirement asks a comment to carry is such text (D-061 on chadlis/hypotrail#75, as amended by D-063 on chadlis/hypotrail#75). A decision you log names the same verb for each change it makes. Before the next round, check each removal the builder's hand-back lists against the prompt line that asks for it; a removal no line asks for is undone first. The PreToolUse hook `.claude/skills/drive/fix_prompt_check.py` on the Agent tool runs on a prompt that contains "This is a review fix": it warns about a quotation that is not word for word a whole sentence or item of its source, and about a prompt that names no finding ID, then lets the call through (D-055 on chadlis/hypotrail#75, item 1). The warnings of its run at the Agent call reach you as additional context; post them beside the prompt only when they differ from those of its run on the prompt file. A quotation of a criterion or decision that it calls not whole is made whole before the prompt is posted, text the prompt removes included, since `fix_prompt_check.py --strict` refuses it (D-090 on chadlis/hypotrail#75, item 2, as D-105 on chadlis/hypotrail#75 narrows it).

Take the first row that applies:

| the finding is… | it goes… |
|---|---|
| a requirement missing, partial or implemented wrong | a fix, via `slice-builder` |
| behaviour in the code that nobody asked for | **removed** if removing it costs nothing; otherwise it is an invented behaviour: a dated amendment comment on the milestone issue, plus a `GLOSSARY.md` or ADR line if a term or decision changed. One per run |
| a decision with a rejected alternative | an ADR if it is hard to reverse, surprising and a real trade-off; otherwise a line in the PR body |
| identified work outside this slice | a new issue, label `needs-triage` |
| something about the tooling (flaky test, broken script) | the brief, not the code |
| none of the above | the brief, under "non classé" |

Eight readings of this table that it does not say on its face:
- Missing required documentation is a requirement, row 1.
- Duplicated code or an unflattering name is not, by itself, behaviour nobody asked for. Row 2 is about what the code does.
- A product ambiguity is not settled by routing it to row 1, row 2 or row 3. It follows the owner-decision gate of "Who decides". A finding that a decided definition (a decision-log entry, a Tightened line) does not say how it treats a case, and that no quoted source settles, is one: the decision is a new log entry naming the one it amends (a Tightened line is still rewritten under the Tightened rule), and the fix prompt quotes that entry instead of a reading of its own. A dispute over what a word of a criterion covers, when that word is not a `GLOSSARY.md` term (« recorded », « exact », « own output »), is one too: it goes to the gate in the round where it is first raised, before any fix for it (a finding that applies a criterion to a case an earlier fix did not cover is this dispute only once the structural-option rule fires, and it then goes to the gate in the round where that rule fires, not one round later: D-061 on chadlis/hypotrail#75). When both fire for one finding, the gate decision comes first, and the fix prompt quotes it beside the structural option. A `GLOSSARY.md` term follows the next reading.
- A finding that turns on what a `GLOSSARY.md` term covers (its definition and its relationships disagree, or the readers do) is a product ambiguity from its second round on. It goes to the owner-decision gate, which may choose a `needs-triage` issue for `/domain-modeling`, not to another wording fix; the reader who raised it verifies that the decided disposition was applied.
- A wording finding (a word a `GLOSSARY.md` entry lists under _Avoid_, or a term applied to what it does not cover) is row 1 only for text the diff adds or changes, or an identifier it adds or renames, unless it turns on what a term covers from its second round on (the reading above). The same word in text the diff leaves alone goes to row 4, as one `needs-triage` issue for all of it. The structural option for a wording class covers the same diff text; widening the rule to the whole corpus is a decision for the owner-decision gate (under the autonomous protocol, the proxy), never a fix.
- A finding its reader labels a judgement call, baseline smells included, goes to row 1 only when it quotes a requirement the diff breaks. Otherwise it is an improvement only, recorded as `out of scope` (D-065 on chadlis/hypotrail#75, item 7). The disposition check still applies: an axis reader verifies any disposition that dismisses a potential row-1 blocker.
- A row-2 removal that changes what a public contract (a link form, a command's output, a refusal) accepts or refuses, where no quoted source says what the contract does with those inputs, goes to the owner-decision gate in the round it is raised, before any fix prompt removes it (D-090 on chadlis/hypotrail#75, item 4).
- A finding about what a user sees or can do (a control, a notice, a state, a layout) is never refuted by a reading of a decision's or a criterion's words. When no live line covers it, it takes the row `behaviour, no line`, status `open`, and the rendered panel settles it: the UX review of D-091 on chadlis/hypotrail#75 in the same slice, or the proxy as an improvement (D-091: "A finding that only improves goes, as one decision, to the proxy"). A disposition check on it gives the reader the finding and the render, not your reason.

### The findings register

Keep each original finding with a stable ID, its cited requirement, routing row, status and verification evidence. Link duplicates explicitly. Record reclassifications and their reasons. After its initial bare review, an axis reader must verify any disposition that dismisses or downgrades a potential row-1 or row-2 blocker. Drive cannot clear it alone.

- **Where it lives.** Each round's routing table assigns IDs; it is in the comment headed `## <slice>, round <r>: routing`, with the columns `ID | round | axis | requirement | row | status | evidence` and no `origin` column. The `requirement` cell holds only sentences quoted word for word from a source outside the drive, each with its location (the slice issue, a ticket or its Tightened line, a decision-log entry, the specification, or a documented standard at `file:line`), never a fix prompt, a routing note or your own paraphrase (D-065 on chadlis/hypotrail#75, item 1). A finding that a fix did not do what its prompt asked cites the source sentence the prompt quoted (D-065 on chadlis/hypotrail#75, item 1). The state comment lists the open IDs with their current status and links. An ID is assigned at first sighting and kept when a file is renamed or a remark is reworded.
- **Statuses.** `open`, `confirmed`, `fixed-verified`, `refuted` (with its evidence), `duplicate of <ID>`, `disputed`, `out of scope`. A finding you fix yourself (an issue comment, a record) stays `open` until the reader of the axis that raised it verifies it.
- **Disposition checks.** They go to the axis reader that raised the finding, continued when possible, otherwise a fresh `slice-gate` given that axis. They belong to the round in progress. A disposition check or a verification message quotes whole, as "Quote a decision whole" asks of a fix prompt, the decision-log entry and the fix-prompt items that asked for the change the reader reads, the items for other readers' findings marked as context, since the reader verifies only its own findings (D-065 on chadlis/hypotrail#75, item 5). Disposition checks and round-5 verifications are posted word for word, each as its own comment, when they run (a round-5 verification is headed `## <slice>, round <r>: <axis> verification`). Add no standing third reviewer and no chain of appeals: a dispute that the reader does not settle stays a blocker. If the contract itself is undecided, the owner-decision gate applies.

Record the reviewed base and head, raw and deduplicated counts by routing row, one count line per round (every routing comment holds one (D-065 on chadlis/hypotrail#75, item 4): it places each ID under build text, fix text, older text or no cited line, using `git blame <head> -L <line>`), cited paths, and available token/cost telemetry. Unknown usage stays unknown. Counts, repeated paths and blame attribution are diagnostic signals, not automatic floors. Raw and deduplicated counts are kept apart, and neither has to decrease.

For a suspected regression, distinguish demonstrated before/after failure, an older defect newly discovered, an incomplete fix, and unknown origin. Use reproducible checks where possible, otherwise a concrete contract-based causal explanation.

Before rounds 4 and 5, record the outstanding requirements, bounded correction scope and verification plan. Include tests for the relevant failure class. Do not add unrelated refactoring or change product scope.

When one requirement has produced row-1 blockers in two or more rounds, the next fix prompt sets a structural option (one that removes the class of defect, such as reading input once into typed objects) beside the point fix, whatever the round, and that round's routing comment says why the chosen one converges (D-065 on chadlis/hypotrail#75, item 4). That round's routing comment, or a later round's, records it in a line `Structural option for <requirement>: …`, or `Gate for <requirement>: D-nnn` when the owner-decision gate settles the requirement, where `<requirement>` is the requirement cell up to its first ": " (a colon followed by a space), without the word "Tightened", its line numbers kept, and the line has text after its ": "; `.claude/skills/drive/check_record.py` refuses the merge while a requirement with row-1 findings in two rounds has neither line in the routing comment of its second round or a later one (D-063 on chadlis/hypotrail#75). That check is a backstop to your own count, which stays the rule: its key is textual, so two different rules cited from one file under the same text before ": " (`` `AGENTS.md` ``) get one key, two spans of one comment block (`decisions.py:30-31` and `:28-31`) get two, `#142 B (Tightened)` and `#142 B` get two, and any text after a clearing line's ": " clears it. When it refuses two requirements that are not one, the routing comment says so in the clearing form, with the reason: `Structural option for <key>: not one requirement, because …`. When the structural option replaces or qualifies a phrase, its witness is `grep -rnoE '<phrase>|…'` over the paths it names, run on the head the fix starts from. The routing comment quotes each occurrence it prints (path, line, phrase), not a count of lines. The fix prompt lists each occurrence under its finding, and the next round's routing comment quotes the same command run on the fix's head. If only the structural option is credible, that is the judgement floor, with this record as its evidence. Findings that cite different lines of one rule (a body line, its Tightened lines, the specification sentence they quote) count as one requirement here, and so do findings on the same comment block or function at HEAD in two consecutive rounds, whatever each cites. For prose that restates code, the structural option is less prose: keep the sentences a criterion asks for, beside what the criterion names, and delete the rest. A finding that applies a criterion to a case the earlier fix did not cover is a row-1 fix, as in "Fixing a family of defects"; it becomes a word dispute for the owner-decision gate only once its requirement has had row-1 blockers in two rounds, that is, when this rule fires, and the gate is applied in the round where this rule fires, not one round later (D-061 on chadlis/hypotrail#75). When the gate and this rule both fire for one finding, the gate decision comes first: the fix prompt then quotes that decision and sets the structural option.

The structural option covers every case the requirement's quantifier names (every row of every table, every path), not only the cases the last findings cite.

Incremental review includes affected dependencies and verification of earlier blockers. From round 2 on, the Spec reader's sources include the register's open entries as written (finding and cited requirement), without your disposition. The Spec reader is given each ticket by its issue number and reads it live with `gh api` when it starts, never from a local copy of a body (D-090 on chadlis/hypotrail#75, item 5). Both readers start from the diff since the last reviewed head, and may read the callers, dependencies, tests and requirements a fix affects. Acceptance names the exact reviewed head and requires all blockers to be resolved, required checks to pass, and no later unreviewed change affecting behaviour or the accepted contract.

### Fixing a family of defects

When a defect reveals a family of mishandled inputs, the fix verifies the neighbouring cases the contract covers, not only the first counterexample. For a declaration validator, that can mean:
- missing required keys and wrong types;
- unknown keys in closed objects;
- mixed Configuration kinds and retired keys.

Check the coded refusal at the public entry point concerned, and that no forbidden effect happens before it. Keep valid cases, so that a validator that refuses everything fails. Optional keys, defaults and extension points follow the accepted contract: a removed or added key is not always a refusal. Parametrised tests are enough, and no property-based tool is required.

When the defect is in what an outcome carries or where something may not reach (a scan for a secret, the warnings an error carries, a Reason), the family is a **matrix**: every exit path of the command (a refusal before the first write, success, a Hypotrail error, an OS error, any other exception) crossed with every output the rule names (stderr, the `--json` object, the exception a library caller catches, each file written, the terminal manifest included). The fix prompt lists the matrix with each cell's required result and marks cells outside the rule's scope with their source; a cell the contract does not settle goes to the owner-decision gate. The witness is one parametrised test over the matrix.

**A rule found inside a slice belongs outside it.** If a subagent justifies a choice with a criterion that would apply to every later slice, that criterion goes to an ADR or the brief's apparatus list, not into one slice's code comments.

## The brief

Use a STOP banner only if a decision is required. Otherwise use EXÉCUTION and provide an information brief, without asking for a ceremonial PASS. The ordinary brief follows the placement defined by `merge` and `chain`. A decision brief starts with framing, then a numbered decision list in French, each point written as in "How a STOP is written":

0. **The ticket gate, for real.** For each ticket marked `INFERRED`:
   - the source sentence, quoted (slice issue, amendment, or specification);
   - what the ticket makes the code do;
   - the gap, explained by its mechanism: which test would pass while the claim is false;
   - options `1A`, `1B` with their cost;
   - your recommendation, argued.

   Any unresolved requirement or owner decision is handled before dependent work or merge. Never describe an unresolved ticket gate as retrospectively approved. Cite how each previously `INFERRED` ticket was settled, rather than asserting « ce ticket tient ».
1. **What is waiting to reach `main`**: deferred apparatus diffs (including `retro`'s), invented behaviours, anything kept off `main`. One line each, with the cost of dropping it.
2. What shipped, what you decided alone, what you filed instead of asking, what is still open. Add the review rounds used and the register in brief (unique findings, reclassifications, demonstrated regressions against older defects), and a proposed bounded delegation if a category of question keeps coming back (see "Who decides").
3. **L'ordre recommandé**: the order in which Salah should take the brief's items and the actions around them. Name which decisions he can answer now, which depend on an explicit owner decision or review of References, and which learning activities are merely optional preparation, which merges wait on which answer, and which later choice would make a chapter or a note false. One numbered list, each step with its reason.

Under `chain`, this is one brief for the whole chain, numbered continuously, each line naming its slice. Append at most one learning occasion and its link as information (see "Learning occasions" in `.claude/skills/drive/learning.md`). Do not make every `learn:` issue another decision for Salah.

### The brief page

Salah asked for every brief, STOP or ordinary, to also reach him as one self-contained HTML page. Publish it with the Artifact tool (private), starting from its quickstart, and give its link in the turn beside the numbered decision list. If the Artifact tool is unavailable, write the page in the session's scratchpad and send it as a file.

**The reference level** is the D1/D2 brief of chadlis/hypotrail#8 from its version 4 (https://claude.ai/artifact/55j5JT8Rd1ipufSq1FC5xM; owner instruction, #8 comment 6677416282: « partir de 0 à chaque fois … animation ou schémas »). Read it before writing a session's first brief and match its depth.

- **From zero.** The page opens with what Hypotrail is and what this slice is for. Then comes a glossary of every term the page uses: the `GLOSSARY.md` definition quoted, then its plain-French meaning. Then each earlier decision the page relies on, quoted with its date and link.
- **Same explanation as the turn**, section by section: framing, each decision point in the order of "How a STOP is written", then *L'ordre recommandé*. French, the writing style above.
- **Charter.** Load the `anthropic-skills:cosmic-couture` skill and build from its document template, including its « Navigation du document » block. Its design overrides the quickstart's. Light by default.
- **One animated or interactive diagram per decision point** that shows its mechanism: what flows where, what is refused, what changes from one option to the other. Options whose consequence is visible get a toggle that shows each one. A finding is replayed on its real input (the JSON, the command, the dates). An information brief illustrates what shipped the same way.
- **True numbers.** Charts are drawn to scale, from the repository or from a run you made. Illustrative values are labelled as such.
- **Checked once** before the link is given: load it headless at phone width, with no script error and no horizontal overflow, and run the navigation checks the cosmic-couture skill lists.

## The trail

- Every commit carries the attribution trailers this session was given, and a session URL only if one exists. **Never invent a link.**
- The squash subject ends with `(#<slice>)`, so `git log --grep '#<slice>'` finds it without the tracker.
- The PR body names the last commit a review of record covered, and lists every later commit as not reviewed.
- Before you open any pull request, an apparatus one included, re-run the full suite yourself on its head. You re-run it only then, not after each fix: the builder's run on the committed head stands for the rounds (D-061 on chadlis/hypotrail#75). For that, check that the hand-back's head equals the branch head, and that the hand-back's run was on a clean tree (D-063 on chadlis/hypotrail#75). The PR body gives that head and the suite's final line, never a hand-back's.
- Apparatus changes never travel in a slice's squash: they go on their own branch and pull request, after Salah agrees.

## What goes wrong

- Holding a gate because you are already there and it seems quicker.
- Writing the slice's code yourself because you have the tools.
- Appending anything to `/mattpocock-skills:code-review main`, or sending the bare `/code-review` instead.
- Opening a turn without a banner, or crying STOP for something you could decide.
- Raising a doubt without options.
- Forwarding to Salah a question your delegation already covers, or deciding alone one that it does not.
- Clearing or downgrading a row-1 or row-2 finding without an axis reader's verification.
- Rerunning an unchanged review, or calling a head accepted when a later change was not reviewed.
- Adding rounds to reach five when nothing is left to fix.
- Applying an apparatus change instead of deferring it.
- Stating the slice's position from memory instead of from the repository.
