# Lesson content per Track

Status: proposed

## Context

The workshop's feedback, in the owner's words recorded by D-164 on chadlis/hypotrail#75, is that what was liked was the teaching and accompanied side of the old tool, with its visuals. D-165 on chadlis/hypotrail#75, item 4, runs a Wizard-of-Oz trial "with lesson cards copied from the old tool" before T0, adding no code to the product. If the product is to carry such cards, three boundaries already hold:

- **The core imports no Track.** `tests/test_architecture.py` gives each package a layer (`LAYERS`) and what it may import (`MAY_IMPORT`): `core` may import nothing of `hypotrail`, and a Track (`ml`, `agentic`) may import `core` only. A card that names a Partition, a Metric or a lag belongs to one Track, so the core cannot hold it.
- **ADR 0003 separates two books.** The handbook here is an English reference that "never teaches concepts"; the learning book lives in chadlis/hypotrail-learning, in French by default, and "never restates a decision". Everything committed here is in English (`AGENTS.md`).
- **The panel computes nothing that tells the reader what to do** (D-136 on chadlis/hypotrail#75), and "No stages" means "no feature level, and nothing that a setting hides" (D-136, C3). The choices and Record sit in the first screen at 420 px; the charts fold after Record (D-148 item 4; D-151 answer 3).

The precedent for a read that one Track serves is the data profile: `hypotrail profile --study DIR --json` dispatches to `hypotrail.ml.profile`, which refuses a Study of another domain with `UNSUPPORTED_CAPABILITY` (`require_domain`, `src/hypotrail/core/study.py:70`).

## Decision

1. **A short `lesson` read, served by the Track.** Each Track that has lesson content serves it through one read, `lesson`, built like `profile`: the CLI dispatches to the Track's module, and the core holds no lesson text. The read takes no lock, writes nothing, records no Exposure and does not advance the Write sequence. Its content is short: one card per step the panel shows, each a title and a few sentences that explain what the step is and how to read it.
2. **What a card does not do.** A card explains the step shown; it does not teach a concept, measure a learning, or recommend an option. It never says which option to choose.
3. **English in the product.** Every card served by the product is in English. The French booklet and the journey map live in chadlis/hypotrail-learning, under ADR 0003's boundary: they link to the code at a pinned commit and to this ADR, and are not served by the product.
4. **The panel draws the cards folded, after Record.** A card is a closed `<details>` placed after the choices and Record, in the same way the charts fold (D-151 answer 3). It is always present when the read gives it; no setting hides or shows it (D-136: nothing that a setting hides). It never pushes the question, the delta, a warning, the limitations line, the options or Record out of the first screen.

## Consequences

- **Durable formats.** None among the records of a Study: a card is not a record, and no record cites one. The shape of the `lesson` read's JSON object is a client contract, like `figures`; it is additive and can be removed as a block.
- ADR 0004 gains a dated line: a client also reads `lesson`. ADR 0003 gains a dated line: explaining a step that the product shows is not teaching a concept, and the handbook rule "never teaches concepts" stands.
- Each Track carries its own cards and their tests; a Track without cards adds nothing to the core.
- The `verify-panel` sheets cover the folded cards in the four themes at 420 and 900 px, and the first-screen measure stays as D-151 answer 5 orders it.
- The cards of the Wizard-of-Oz trial (D-165 item 4) stay outside the product; whether they enter it as written is a separate step.

## Alternatives rejected

- **The cards in the core** (rejected): the core would import a Track's vocabulary, which the layering rule of `tests/test_architecture.py` forbids.
- **The cards as keys of `status --json`** (rejected): every kept read of `status` would change, and a Track's text would enter a read the core builds.
- **The cards as static files of the VS Code client** (rejected): Claude Code, the CLI and the report would not see them, and the client would choose what to show, which D-136 forbids.
- **The cards open before Record** (rejected): they would push the choices and Record out of the first screen at 420 px (D-148 item 4).
- **A setting that shows or hides the cards** (rejected): D-136, C3, "nothing that a setting hides".
- **The cards in French, or in two languages, in the product** (rejected): everything committed here is in English, and the French material belongs to the learning repository (ADR 0003).

## Open

- **A Track without cards**: the read refuses with `UNSUPPORTED_CAPABILITY`, as `profile` does, or answers with an empty list of cards.
- **What keys a card**: the kind of the step shown (Study, Attempts, Assessments, Comparisons, Decisions, as D-161 orders them), the `next_step.kind`, or both.
- **Values in a card**: the card holds no number of the Study and points to values of other reads by key paths, or the read fills values in.
- **Which clients read `lesson`**: the panel only, or also the Copilot read tool and the report.
- **Where the card texts live inside the Track**: in its Python module, or as Workload-independent data files of the Track, checked against a schema.
- **Whether cards exist for a Workload rather than a Track**, for example the free-text agent Workload of D-154.
