**Preparation mode**, only on an explicit `/drive #n prepare` request: read the slice and its sources, create or update the slice preparation note below, then finish normally with `/hypotrail-study before <fully-qualified-source-issue>` as the next command, to run in a session opened on `chadlis/hypotrail-learning` so that its repository skill is used, not a same-named personal skill. Do not enter steps 1–12, create a delivery branch, add an `in-progress` label, open implementation tickets, merge, or start a chain. Save the note and its link only. Create no learning issue in this mode. Do not mark an implementation step done because preparation happened. If `prepare` is combined with `merge` or `chain`, preparation takes precedence and the next execution needs a new explicit command. Preparation is optional. A plain `/drive` does not start a course or wait for a learning session.

### Learning occasions

Select occasions by durable competency, never by the number of PRs or defects: contracts and invariants, interfaces and dependencies, discriminating tests, state and persistence, provenance, reproducibility and evaluation validity. The aim is that Salah can explain a trade-off, predict a failure and verify a property on code.

- Propose at most one occasion at a time, in an orientation brief or an existing note, naming the competency and why it is useful now. It is not a quota per slice, an issue or a STOP. Prefer objectives already selected: one structuring choice can serve several slices and sessions, within the tutor's limit on active competencies.
- A suggested occasion reserves nothing. Without a reservation, delegated decisions go ahead, and the tutor may later run a retrospective or counterfactual exercise announced as such. A decision already taken is never replayed as if Salah could still take it before delivery.
- The tutor (`/hypotrail-study` in `chadlis/hypotrail-learning`) owns sessions, calibration, the short production asked before the detailed recommendation, and records. You never start a session, and you do not ask a teaching question at each interruption.
- Never withhold information a real decision needs in order to protect an exercise. An urgent or required decision gets a full brief. A teaching result is never a product approval, and a teaching suggestion never becomes a merge restriction. Delegating a routine choice never waives tests, independent readers or reserved decisions. Teaching value never permits going past the accepted contract or the authorised budget, and never widens an authorisation.
- Salah's agreement rate with your recommendations, his number of approvals, his declared confidence or his Anki scores alone are not evidence of competence. The tutor observes predictions, counterexamples, diagnoses, tests and delayed application, with the help received.

Example, the declaration validation of chadlis/hypotrail#7: fixing coded refusals that were already required is delegated; where structural validation sits before domain checks is a good learning occasion if it matches a selected objective; an undecided change to the guarantees around `public_check`, the freeze or Exposure stays an owner decision.

## Learning notes and selected objectives, version 2

**Do not create a learning issue automatically for a PR or a delivery slice.** Delivery tickets remain unchanged. Record the useful learning material in the slice notes. Only the tutor creates a `learn: <competency>` issue when a learning objective is selected in a requested session, or when Salah explicitly asks to track that objective. One such issue can cover several slices and several sessions.

For every slice, reuse its existing `notes/<slice>.md` in `chadlis/hypotrail-learning`. If no path is already recorded, first look in `notes/` for a note that cites the source issue, then use `notes/hypotrail-<source-issue-number>.md`. Keep the field labels below in English and write their content in French, per that repository's `AGENTS.md`. Put the fully qualified source issue in the note and link the note from the source issue's state comment. In `prepare`, save that pointer in a short preparation comment on the existing source issue, without marking implementation started. Do not make another file for each update or another issue to hold the note.

On every start and resume, read the note, any linked selected objective and relevant `before` records, following the unconditional authority check of `SKILL.md` ("Where the state lives"). Also search selected learning issues by the source issue reference if no backlink exists. A tutor can have prepared the objective directly before `drive` ran. A suggested focus in a note is not an activated learning objective. If the focus clearly matches an active objective listed in `apprentissage/parcours.md` that does not cite this slice yet, add the note to that issue as a candidate source (« candidate, not assessed »), without changing the objective. If Salah asks `drive` itself to track an objective, record the request in the note and point to `/hypotrail-study`: the tutor creates the issue.

In explicit `prepare`, collect the note now and finish with `/hypotrail-study before chadlis/hypotrail#N`. In normal execution, update it at steps 7 and 9. A disposition check on a finding about learning notes quotes the note's content, since axis readers may be unable to read `chadlis/hypotrail-learning`. If a selected learning issue already covers this source, add the new evidence to that issue without changing the objective, closing it or creating a duplicate. If none exists, stop at the note. A missing learning issue is a normal completed state.

Use these compact fields in the note, omitting empty optional sections:

```text
Source: chadlis/hypotrail#N, parent issue, relevant ADRs
Code: <base SHA>; <PR URL and head SHA, or not implemented>; <squash SHA when available>
Delivered behaviour: <one sentence, or preparation only>
Focus suggestion: <one durable competency and at most two concepts, or reference-only>
Why: <durable value for SWE or evaluation work, one sentence>
Before: <optional problem and preparation question, not asked by drive>
Owner decision: none | reserved | decided | delegated
Decision evidence: <exact owner statement/link, affected scope, requirement excerpt and consultation date, or none>
Evidence: <1–3 fixed code/test/ADR pointers; observed result vs unrun command>
Selected objective: <existing qualified learn issue and record links, or none — not selected>
After: <only if selected: exercise property and plausible error to distinguish>
```

Use existing decisions as examples of reasoning, not as fictional open choices. Label an alternative invented for teaching `hypothetical`. For a genuinely open choice, write the problem and a preparation question in `Before`, without asking Salah to solve it in `drive`. The tutor owns calibration, the first attempt and the detailed pedagogical explanation. Reuse any spontaneous answer with its context and assistance level rather than asking it twice. A necessary product-decision brief still supplies the argued recommendation and remains separate from teaching.

During implementation, keep at most three consequential choices in the slice notes: constraint, chosen option, actual alternative if considered, evidence, reversibility. The PR and ADRs remain the sources of truth. Do not invent a rejected option to fill a template.

If a preparation record's source has changed, compare only the relevant requirements, code boundary or decision. Keep unaffected learning evidence. For an editable issue requirement that underpins a reservation, preserve only the relevant excerpt, URL, consultation date and an available revision timestamp. A code SHA alone does not freeze an issue body. A material change makes the affected recommendation stale. If the old requirement cannot be recovered, state that uncertainty and seek resolution only if it prevents honoring the reserved decision. A changed owner-reserved scope requires a new owner answer before dependent work. An educational prediction is never silently promoted to a product decision.

The short focus list in `chadlis/hypotrail-learning/apprentissage/parcours.md`, when present, belongs to the tutor. `drive` may read/link it but must not activate a topic or mark a skill acquired. Existing `learn: <slice>` issues remain readable as historical references. If one already tracks a selected objective, enrich it without renaming or closing it. Otherwise leave it unchanged until the tutor selects an objective. Do not bulk-migrate old issues, count them as a personal debt or send reminders.

If learning-repository access fails, keep the short note in a preparation/delivery comment on the **existing source issue** in `chadlis/hypotrail` (English, without personal Anki data), then reference that comment from the state. Update the same fallback comment on resume. Do not create a fallback `learn:` issue just to store it. If issue writes also fail, preserve the note locally and include its path/content in the delivery brief as unsaved. Do not block delivery solely on learning storage, and never claim that a failed save succeeded. If the learning repository cannot be read, take owner authority from the source issue, its comments and the state comment, and record that learning records were not read. Under `merge` or `chain`, do not merge until they are read or Salah confirms that no reservation is recorded there. Once access returns, reconcile into the same note and preserve its links. A reference-only note needs no exercise or promise to make one later.

## Learning anti-patterns

- Requiring a lesson, Anki access or a generated chapter before routine implementation or merge.
- Treating a successful lesson as acceptance of a product decision.
- Starting a course automatically, or treating `prepare` as permission to execute.
- Creating a learning issue per PR/slice, duplicating a selected objective on resume, or overwriting a tutor record.
- Sending production Reference answers to the agent being evaluated as part of a teaching exercise.
- Recording an unrun command as a passed test, or claiming that a hypothesis is a documented design decision.
