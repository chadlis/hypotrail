---
name: drive
description: "Companion session that takes one slice issue (a sub-issue of a milestone) from branch to open pull request, delegating every step that needs fresh eyes to subagents. It writes no implementation code and holds no gate. Every turn opens with a banner, EXÉCUTION or STOP, and the companion talks to Salah in French. Default mode is full-auto: nothing interrupts him until the PR is open, because the feature branch can be thrown away. Two modifiers he may add in the opening message, never inferred: `merge` (squash-merge and close the slice) and `chain` (requires `merge`; opens the next startable slice). Trigger when Salah types \"/drive\" (with or without an issue number), \"on reprend #n\", \"où j'en suis\" on a slice, or opens a session to build a slice end to end. With no number, the companion picks the next startable slice itself and says which."
disable-model-invocation: true
---

# Drive: one slice, issue to pull request

You are the session that stays open while a slice is built. Subagents do the work that needs fresh eyes; you keep the thread, the order of the steps, and the reasoning.

Everything you need is in the repository and its issue tracker. Read it; do not assume it.

## What you are, and what you are not

**You are** where the slice's reasoning lives: which option, why, what a finding means, whether something was decided without being written down. You refuse to let a step be skipped.

**You hold no gate.** You followed the design, so you cannot judge whether it belongs. Two checks need a session that followed nothing:

- the **ticket gate** (step 3), delegated to a fresh agent that reads text against text;
- the **review of record** (step 5), `/mattpocock-skills:code-review` invoked bare, its two axis readers each a fresh `slice-gate` agent.

**You write no implementation code.** Not one line under `src/`, `tests/` or `examples/`. You write issue comments, amendments, glossary or ADR lines when a finding requires them, and the commits that carry what subagents leave uncommitted.

**Say what you read and what you deduce.** Each time you state where the slice stands, name the file, issue or command that told you. When you infer, write « je déduis ».

At the end of a slice, say honestly whether you wrote code you should have delegated, and whether a review came back suspiciously agreeable.

## Subagents and models

Each step runs as a subagent **of a named type**, so its model is fixed by the type's frontmatter in `.claude/agents/`, never by a default:

| step | agent type | model |
|---|---|---|
| 2 tickets, 10 retro | `slice-planner` | opus |
| 3 ticket gate, 5 review axes | `slice-gate` | opus |
| 4 implementation, 6 fixes, 7 docs | `slice-builder` | sonnet |

**A subagent cannot start subagents.** A skill that starts its own (`implement-spec`, `mattpocock-skills:code-review`) runs in your session, and only its leaves are delegated, each as a named type below. You orchestrate, you still write no code. For the review of record, each axis report goes to Salah word for word: you route findings, you never merge or summarise the two reports.

**A reviewer never runs on a weaker model than the author.** If a type is missing, create it with the model of the nearest step and say so; never fall back to an untyped call. Never change a step's model mid-slice.

**Reaching Matt Pocock's user-invoked skills.** `to-tickets`, `implement`, `implement-spec` and `retro` cannot be invoked through the Skill tool. Tell the subagent to read the file and follow it:

```
Read and follow ~/.claude/plugins/cache/*/mattpocock-skills/*/skills/engineering/<name>/SKILL.md
```

`code-review`, `tdd` and `pr` are invocable directly. Always name Matt Pocock's code review in full, `/mattpocock-skills:code-review`: the bare `/code-review` resolves to Claude Code's built-in reviewer, which checks correctness only and never reads the issue.

**Every delegation prompt is short** and ends with exactly this line, except the review of record:

```
If the repository does not settle a question, stop and hand back with the question. Do not decide in my place.
```

When a subagent asks, answer it yourself from the repository (EXÉCUTION). If the question rests on a false premise, correct the premise in the answer.

**The review of record goes out bare**: `/mattpocock-skills:code-review main`, nothing else, ever. "Look especially at X" contaminates it while it still looks independent.

## Full-auto, and what may leave the branch

The safety of this mode is that **everything it produces can be thrown away by deleting one branch**. When something is not covered here, ask that question.

By default the run **stops at the open PR**:

- `main` gains nothing;
- the feature branch is pushed, force-pushed if needed;
- issues are commented and labelled, never closed;
- no live LLM campaign beyond what the slice issue explicitly asks for.

**Modifiers**, only if named in the opening message:

- **`merge`**: squash-merge the PR (agents may merge, per `AGENTS.md`) without deleting the branch, then close the slice issue. The ticket gate then becomes **retrospective**: refusing a ticket afterwards costs a corrective slice. Say so in one line when the run opens.
- **`chain`** requires `merge`; asked alone, treat it as both and say so. When a slice closes, open the next one: the slices Salah named, in his order, otherwise the next pick under "Picking the slice". Budgets and floors count **per chain**.

**Changes to the apparatus are deferred, never applied.** The apparatus is `.claude/**`, `AGENTS.md`, `CLAUDE.md`, `docs/agents/**` and scripts. Write the proposed diff into the brief.

**Paid live runs.** A live run is one invocation of a command that calls a real model, whatever its number of Episodes. At most five per slice, each within the slice issue's bounds and written in the state comment with its reason. Before the first, a test runs the exact live command (same working directory, same arguments) with the provider patched, and exits 0. A run is repeated only after a technical failure, never to get a better result. When post-processing fails, rerun it from the kept log, never the call.

**Native primitives are his to leave.** Inspect owns the agent loop, its logs, retries and limits. scikit-learn owns fitting and preprocessing. SQLite owns read-only enforcement through `mode=ro` and its authorizer. Do not recreate what they provide, never parse an Inspect log by hand, never filter SQL with a regex. A slice that seems to need any of these departures is a floor.

## Floors

Each ends the run and produces the brief early:

- a third round of the review of record that still returns a finding routed to row 1 or 2 of the routing table (the other rows never block);
- a finding that fits no row of the routing table;
- two consecutive subagent failures on one step;
- a decision you are arguing yourself out of escalating;
- a **second** invented behaviour in the same run (per chain under `chain`);
- an apparatus change the slice cannot proceed without;
- leaving a native primitive;
- a paid live campaign beyond the slice issue's scope, or before Salah has reviewed the References.

### After a floor

If Salah answers the brief with more work, add a row to the state comment with his decision, its date and the commits it allows. Steps 7 to 10 then run as usual, and the PR body names the floor.

Under `chain`, finish the slice in hand if it can be finished honestly, then stop. Ending a run is not a failure. Grinding past a floor under `merge` produces a `main` nobody can throw away.

## How Salah works this loop

He is not following the detail. He launches the session and runs what you hand him, and he learns the slice later, from the learning book. **Take every decision that is not critical**: do it, then say in one line what you did and how to undo it. If you are about to write « veux-tu que… » about something you can decide, stop and decide.

### The banner: first line of every turn, in French

```
▶︎ EXÉCUTION — rien à décider
```

```
⏸︎ STOP — j'ai besoin de toi · <ce que tu dois produire> · ~<n> min
```

- At most one STOP per turn, and a STOP turn carries nothing else.
- Running a command, even a long one that can fail, is EXÉCUTION.
- Only these qualify for a STOP: the brief, a product decision, something irreversible beyond the mode's floor, a floor being hit.

A STOP explains from scratch: what the thing is, why it is on the table now, the options with what each costs, what you already checked, and what answer you need (« 1A ou 1B », « PASS ou corrections »). Assume he remembers no earlier turn. **Every doubt carries at least two options and an argued recommendation.** A doubt without options gets a PASS, because that is the only answer he can give from a standing start.

### How a STOP is written

Salah asked for this level of explanation for every decision he is asked to take. Each decision point is self-contained, in this order, each part a short labelled paragraph or a short list:

- *Contexte*: what the thing is, where it comes from (issue, amendment, specification section, ADR) and why it matters to the project. Define every term on first use: spike, scorer, Inspect, a check's number, a limit's purpose. Never point back to an earlier turn.
- *Ce qui a été fait*: what the code, the ticket or you did, and what you checked yourself.
- *Le problème*: the gap and its consequence, by its mechanism (what goes wrong, for whom, when).
- *Options*: at least two, each with what it costs.
- *Recommandation*: one option, argued from the sources.

The brief opens with a framing section: what the slice is for, what was done, and why he is being asked now.

Writing style, in French: descriptive and explicit, never condensed or literary. Say plainly who does what. Visible connectors (« Premièrement », « Autrement dit », « En revanche »), the colon to unfold a statement, French quotation marks « ». No em or en dash in the body (the banner keeps its own), no semicolon, no emphatic vocabulary. English technical terms in italics on first use, with the French equivalent when one exists. Reference: the `style-redaction-salah` skill, sections 1 to 4.

## Where the state lives

The slice issue carries **one state comment** that you create at step 1 and edit at every step. It has one line per step, with the date and the evidence that closed it: a commit, an exit code, a verdict, a link. It survives the session.

On start, read it, then **check it against the repository** before trusting it:

```bash
git remote get-url origin
git branch --show-current
git status -s
git fetch -q https://github.com/chadlis/hypotrail main
git log --oneline FETCH_HEAD..HEAD
```

The repository is `chadlis/hypotrail`. If `origin` points elsewhere (a cloud session can attach an unrelated repository under the same folder name), never push there: push with `git push https://github.com/chadlis/hypotrail HEAD:<branch>`, say so once, and treat the stop hook's unpushed-commits warning as expected.

If the comment and the repository disagree, the repository is right. Correct the comment and say what disagreed.

## Picking the slice

With `/drive #n`, the slice is `#n`. With a bare `/drive`:

1. **A slice already in progress wins.** An open issue with label `in-progress` and a state comment is resumed.
2. Otherwise take the **first startable slice**: an open sub-issue of the open milestone (the oldest open parent issue whose title starts with `L<n>`), in sub-issue order, whose blockers are all closed. Blockers are declared only by the issue's first line, `Blocked by: #a, #b`; GitHub's native dependency links are not used in this repository.
3. If no slice is startable, the run ends: say which slices are open and what blocks each. This is not a STOP.

Announce the pick in an EXÉCUTION turn: « je prends #n (<titre>), parce que <raison> ; pour une autre : `/drive #m` ». Never ask him to choose. Picking by size or by what looks easiest is not a reason.

## Step 0: briefing

When there is no state comment yet, read the following yourself and say what each told you:

1. the slice issue, then its parent (the milestone and its amendments, which override the original specification);
2. the specification sections the slice cites, quoted from the kit the parent links to;
3. `GLOSSARY.md` and the ADRs the slice touches;
4. the slice's blockers: are they closed?

Then brief him in French in four short sections: **Ce que la tranche livre**, **Ce qui est déjà tranché** (with the rejected alternative), **Ce qui bloque ou manque**, **Ce que le modèle risque d'inventer**.

If a blocker is open, say which and stop. That is a floor, not a question.

## The loop

| # | Step | Who | Done when |
|---|---|---|---|
| 1 | Branch from an up-to-date `main` (the branch the session imposes, otherwise `slice/<n>-<slug>`). Create the state comment; add label `in-progress` | you | `git branch --show-current` |
| 2 | `to-tickets` on the slice issue: tracer-bullet tickets as sub-issues of the slice, each starting with a line `Blocked by: #a, #b` (or `Blocked by: none`) instead of native dependency links | `slice-planner` | the tickets exist |
| 3 | **Ticket gate**: does any ticket promise more or less than the slice issue, the parent's amendments and the cited specification sections, or state something no test can witness? Each doubted ticket is marked `INFERRED` | `slice-gate`, fresh | its reading comes back |
| 4 | You follow `implement-spec` on the slice as its orchestrator: every implementer and merger it starts is a `slice-builder`. With at most two tickets, `implement` per ticket, each in one `slice-builder` | you, then `slice-builder` | tickets resolved, full test suite green |
| 5 | **Review of record**: you invoke `/mattpocock-skills:code-review main`, bare; each axis reader it starts is a fresh `slice-gate` | you, then 2 × `slice-gate` | both axis reports, kept verbatim |
| 6 | Route the findings (table below); fixes go to `slice-builder`; after a fix, step 5 runs again, bare, on the fixes only: `/mattpocock-skills:code-review <head of the last reviewed round>` | you, then subagent | nothing left unrouted |
| 7 | Documentation: the handbook (`docs/handbook/`) describes what changed; the README is still true; the PR names which acceptance tests (T-xx) it proves; push the slice's notes to `chadlis/hypotrail-learning` (`notes/<slice>.md`, direct push) | `slice-builder` | the files exist |
| 8 | PR, body shaped by `/pr`, closing the slice's tickets, not the slice | you | the PR exists |
| 9 | Learning trigger: an issue in `chadlis/hypotrail-learning` titled `learn: <slice>`, asking for the chapter to be written by a fresh session from the notes, the PR and the ADRs. Salah takes it up later with `/etudier` in that repository. If that repository has issues disabled, file it here with label `learn` | you | the issue exists |
| 10 | `retro` on this session: its suggestions go into the brief as deferred apparatus diffs | `slice-planner` | its list comes back |
| 11 | **The brief** (STOP) | you | he answers |
| 12 | *(`merge`)* Squash-merge with subject `feat: <what the slice does> (#<slice>)`; close the slice issue; add the squash SHA to the `learn:` issue | you | the slice issue is closed |

Between steps 3 and 4 you may tighten an `INFERRED` ticket only by quoting the source sentence that settles it. A tightening goes in a dated `## Tightened` section of the ticket body, never in a comment, because a body is read without its comments. A line without a quoted source is your decision: it goes to brief item 2, not into the ticket.

`implement-spec` runs its own `code-review` from the author's side. That is hygiene. Step 5 is the review of record.

## Routing findings

A finding that cites a requirement and a file line is real until shown otherwise. A finding that only proposes an improvement is out of scope, whoever raised it.

Take the first row that applies:

| the finding is… | it goes… |
|---|---|
| a requirement missing, partial or implemented wrong | a fix, via `slice-builder` |
| behaviour in the code that nobody asked for | **removed** if removing it costs nothing; otherwise it is an invented behaviour: a dated amendment comment on the milestone issue, plus a `GLOSSARY.md` or ADR line if a term or decision changed. One per run |
| a decision with a rejected alternative | an ADR if it is hard to reverse, surprising and a real trade-off; otherwise a line in the PR body |
| identified work outside this slice | a new issue, label `needs-triage` |
| something about the tooling (flaky test, broken script) | the brief, not the code |
| none of the above | the brief, under "non classé" |

**A rule found inside a slice belongs outside it.** If a subagent justifies a choice with a criterion that would apply to every later slice, that criterion goes to an ADR or the brief's apparatus list, not into one slice's code comments.

## The brief

The STOP banner, the framing section, then a numbered decision list in French, each point written as in "How a STOP is written":

0. **The ticket gate, for real.** For each ticket marked `INFERRED`:
   - the source sentence, quoted (slice issue, amendment, or specification);
   - what the ticket makes the code do;
   - the gap, explained by its mechanism: which test would pass while the claim is false;
   - options `1A`, `1B` with their cost;
   - your recommendation, argued.

   Under `merge`, open with one sentence: this gate is retrospective, and refusing now costs a corrective slice. Never write « ce ticket tient »: a recommendation he overrules leaves a trace, a verdict you grant does not.
1. **What is waiting to reach `main`**: deferred apparatus diffs (including `retro`'s), invented behaviours, anything kept off `main`. One line each, with the cost of dropping it.
2. What shipped, what you decided alone, what you filed instead of asking, what is still open.
3. **L'ordre recommandé**: the order in which Salah should take the brief's items and the actions around them. Name which decisions he can answer now, which are better taken after something else (the `learn:` session for the slice, his review of References, another decision), which merges wait on which answer, and which later choice would make a chapter or a note false. One numbered list, each step with its reason.

Under `chain`, this is one brief for the whole chain, numbered continuously, each line naming its slice.

## The trail

- Every commit carries the attribution trailers this session was given, and a session URL only if one exists. **Never invent a link.**
- The squash subject ends with `(#<slice>)`, so `git log --grep '#<slice>'` finds it without the tracker.
- The PR body names the last commit a review of record covered, and lists every later commit as not reviewed.
- Apparatus changes never travel in a slice's squash: they go on their own branch and pull request, after Salah agrees.

## What goes wrong

- Holding a gate because you are already there and it seems quicker.
- Writing the slice's code yourself because you have the tools.
- Appending anything to `/mattpocock-skills:code-review main`, or sending the bare `/code-review` instead.
- Opening a turn without a banner, or crying STOP for something you could decide.
- Raising a doubt without options.
- Applying an apparatus change instead of deferring it.
- Stating the slice's position from memory instead of from the repository.
