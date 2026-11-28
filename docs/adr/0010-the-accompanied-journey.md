# The accompanied journey is the old tool's, served as Track data and computed by the core

Status: accepted (D-278 on chadlis/hypotrail#75)

## Context

The old Hypotrail (`hypotrail-companion` at `4ef4925`) guided a person through a study in ordered steps, in the chat and in a panel. Juniors and seniors used it and liked it. The owner decided that the first version of the new Hypotrail's accompanied path reproduces it exactly, on the new architecture, and approved a reproduction of it as the reference (D-278). Earlier decisions forbade parts of it: D-136 and D-151 (no position, no next step, no theme button, nothing a setting hides), ADR 0007 points 2, 3 and 7, ADR 0009 (stations, content after Record, no digit), and the round-3 line "no text of the old tool is copied".

## Decision

1. **The source of the texts is the old tool.** A Track that serves a journey ships the old tool's English content as JSON data, ported by script from `framework/mlkit/study/content/` and from the English strings of the old engine and panel. A test compares each ported text with the old files. A text is changed only by a dated line here that quotes the owner.
2. **The core computes what waits.** `core/journey.py` computes, when a Study is read and never stored: the position in the steps (step i of n), the pause, its one question, the default and its reason, the options and their labels, and the next step with its commands. It ports `next_action` and `hypotrail.pause/1`. The core receives the step order as data and imports no Track. A step's value in force is the option of its latest Decision that applies; a step is reopened when its Decision no longer applies or when a Decision of a step it depends on is later than its own. `status --json` and its `next_step` are unchanged.
3. **One read serves it: `journey`.** It takes no lock, writes nothing, records no Exposure and does not advance the Write sequence. A Track without a journey refuses it with `UNSUPPORTED_CAPABILITY`. Two commands write for it, through the existing writers: `journey answer` and `journey advance`.
4. **The client computes nothing that tells the reader what to do.** The panel and the chat show the core's position, question, default, options and next step. This keeps D-136's principle and moves the computation from "nowhere" to the core.
5. **Numbers enter a text only through slots.** A content file holds no hand-written digit. A slot is filled by the core from a record of the Study, and each filled number carries its record. A free sentence of the chat agent is checked by `numbers check`.
6. **The page is the old page.** In this order: a sticky header with the progress; "To handle"; "Since your last visit"; "Now" in four blocks (the step in one picture, what the step must establish, to answer look, what it does not say and next); the path; the tools as drawers. The pause's question sits in Now. Nothing is folded after a Record control: the journey panel has none.
7. **The reading has three parts again.** "What we see", "What we conclude", "What we cannot conclude", with "How to read it" and "Watch out". A "conclude" text never names an option of the open decision; a lint enforces it.
8. **The steps are the old plan's.** Fourteen steps under four moments for a regression study. The eight stations and the lesson packs of ADR 0009 are not drawn in the journey panel.
9. **Presentation settings are allowed.** The language menu, the panel theme (Auto, Dark, Light) and the learning layer are settings. No setting hides a piece of evidence, a warning, a limitation or a decision's level.
10. **Local state is allowed, outside the Study.** Folds, scroll, focus and the draft question live in the webview's state. Theme, learning-layer preferences, seen notions and prediction answers live in the extension's `globalState`. None of it is written to the Study, sent to the CLI or shown to the chat agent.

## Consequences

- **Durable formats.** None among the records of a Study. `journey/1`, `journey-pause/1` and `step-cards/1` are client contracts, additive, removable as a block. `decide` accepts the ids of a journey pause (ADR 0004, dated line).
- ADR 0003, 0004, 0006, 0007 and 0009 gain dated lines of the same day.
- The legacy panel (Now with Record, "The Study so far") stays for a Track without a journey.

## Alternatives rejected

- **The journey as keys of `status --json`**: every kept read of `status` would change, and a Track's text would enter a read the core builds (ADR 0007).
- **The journey as a lesson pack**: its texts are bound to slots and step ids of the engine; a pack is checked content with no slot.
- **Texts written afresh**: this is what produced the gap the owner refused.
- **Position kept in the client**: D-136.
