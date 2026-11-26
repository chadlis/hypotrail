# Lesson content per Track

Status: accepted

## Context

The workshop's feedback, in the owner's words recorded by D-164 on chadlis/hypotrail#75, is that what was liked was the teaching and accompanied side of the old tool, with its visuals. D-165 on chadlis/hypotrail#75, item 4, runs a Wizard-of-Oz trial "with lesson cards copied from the old tool" before T0, adding no code to the product. If the product is to carry such cards, three boundaries already hold:

- **The core imports no Track.** `tests/test_architecture.py` gives each package a layer (`LAYERS`) and what it may import (`MAY_IMPORT`): `core` may import nothing of `hypotrail`, and a Track (`ml`, `agentic`) may import `core` only. A card that names a Partition, a Metric or a lag belongs to one Track, so the core cannot hold it.
- **ADR 0003 separates two books.** The handbook here is an English reference that "never teaches concepts"; the learning book lives in chadlis/hypotrail-learning, in French by default, and "never restates a decision". Everything committed here is in English (`AGENTS.md`).
- **The panel computes nothing that tells the reader what to do** (D-136 on chadlis/hypotrail#75), and "No stages" means "no feature level, and nothing that a setting hides" (D-136, C3). The choices and Record sit in the first screen at 420 px; the charts fold after Record (D-148 item 4; D-151 answer 3).

The precedent for a read that one Track serves is the data profile: `hypotrail profile --study DIR --json` dispatches to `hypotrail.ml.profile`, which refuses a Study of another domain with `UNSUPPORTED_CAPABILITY` (`require_domain`, `src/hypotrail/core/study.py:70`). The open points of the draft were answered by the owner's proxy (D-168 on chadlis/hypotrail#75).

## Decision

1. **A short `lesson` read, served by the Track.** Each Track with lesson content serves it through one read, `lesson`, built like `profile`: the CLI dispatches to the Track's module, and the core holds no lesson text. The read takes no lock, writes nothing, records no Exposure and does not advance the Write sequence. A Track that serves no cards refuses the read with `UNSUPPORTED_CAPABILITY`, as `profile` does, and a client draws nothing on that code, as `report` already does for the profile (`src/hypotrail/cli.py:747`). An empty list means that the Track serves cards and none applies here.
2. **What a card is.** One card per kind of step shown (Study, Attempts, Assessments, Comparisons, Decisions, in the order of D-161 item 1), each a title and a few sentences that say what the step is and how to read it. A card is keyed by that kind, never by `next_step.kind`: `next_step` says what waits, and a card keyed on it would drift toward telling the reader what to do (D-136). A card explains the step shown. It does not teach a concept, measure a learning or recommend an option.
3. **No number of the Study in a card.** A card may hold key paths to values of `status` or `figures`. A client may link to or highlight the value, but never writes it into the card's text.
4. **Who reads it.** The panel and the Copilot read tool read `lesson`, and Claude Code reads it through the CLI, so that an agent explains with the same text instead of its own. The report does not read it: the teaching that was liked belongs to the accompanied path (D-164), and the report serves a reviewer.
5. **Where the texts live.** As data files of the Track, in English, checked against a schema kept beside them, as `src/hypotrail/ml/workload.schema.json` is. Cards are per Track: there is no `lesson --workload` and no card inside a Workload declaration. The free-text agent Workload of D-154 reads the agentic Track's cards.
6. **English in the product.** Every card served by the product is in English. The French booklet and the journey map live in chadlis/hypotrail-learning, under ADR 0003's boundary: they link to the code at a pinned commit and to this ADR, and the product does not serve them.
7. **The panel draws the cards folded, after Record.** A card is a closed `<details>` placed after the choices and Record, in the same way the charts fold (D-151 answer 3). It is always present when the read gives it, and no setting hides or shows it (D-136: nothing that a setting hides). It never pushes the question, the delta, a warning, the limitations line, the options or Record out of the first screen.

## Consequences

- **Durable formats.** None among the records of a Study: a card is not a record, and no record cites one. The shape of the `lesson` read's JSON object is a client contract, like `figures`; it is additive and can be removed as a block.
- ADR 0004 gains a dated line: a client also reads `lesson`. ADR 0003 gains a dated line: explaining a step that the product shows is not teaching a concept, and the handbook rule "never teaches concepts" stands.
- Each Track carries its own cards, their schema and their tests, and a test resolves every key path of a card on the kept reads. A Track without cards adds nothing to the core.
- The `verify-panel` sheets cover the folded cards in the four themes at 420 and 900 px, and the first-screen measure stays as D-151 answer 5 orders it.
- The cards of the Wizard-of-Oz trial (D-165 item 4) stay outside the product. Whether texts copied from the old tool enter the product is a licence question, and it stays with the owner (D-166, D-168).
- If J0-a shows that people need the cards before Record, Decision 7 is reopened.

## Alternatives rejected

- **The cards in the core** (rejected): the core would import a Track's vocabulary, which the layering rule of `tests/test_architecture.py` forbids.
- **The cards as keys of `status --json`** (rejected): every kept read of `status` would change, and a Track's text would enter a read the core builds.
- **The cards as static files of the VS Code client** (rejected): Claude Code and the CLI would not see them, and the client would choose what to show, which D-136 forbids.
- **The cards open before Record** (rejected): they would push the choices and Record out of the first screen at 420 px (D-148 item 4).
- **A setting that shows or hides the cards** (rejected): D-136, C3, "nothing that a setting hides".
- **The cards in French, or in two languages, in the product** (rejected): everything committed here is in English, and the French material belongs to the learning repository (ADR 0003).
- **Cards keyed by `next_step.kind`** (rejected, D-168): a card would then follow what waits, and drift toward telling the reader what to do.
- **Numbers written into a card** (rejected, D-168): the client would compose a sentence about the Study's values, which D-136 leaves to the core.
- **An empty list for a Track without cards** (rejected, D-168): it would not tell "no cards here" from "this Track serves none".
- **Cards per Workload** (rejected, D-168): the cards explain the steps of a Track, which every Workload of it shares.
- **The report as a reader** (not now, D-168): it serves a reviewer, not the accompanied path.
