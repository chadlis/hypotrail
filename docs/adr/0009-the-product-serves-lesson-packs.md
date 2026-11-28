# The product serves lesson packs; it authors none

Status: accepted (D-203 on chadlis/hypotrail#75)

## Decision

The Tracks keep their existing cards unchanged. Track cards explain what a step of a Study shows and how to read it. Lesson packs teach how to do a step of the method. Pack authors develop teaching content in chadlis/hypotrail-lessons. Hypotrail ships a format and checks, loads and serves the content verbatim. The core has no dependency on packs. The CLI reads them from the explicit directory list in `HYPOTRAIL_LESSON_PACKS`, in discovery order. Packs are JSON data.

The panel stays here because it is the other half of the read contract and the Python suite regenerates its kept reads. With a Study, it draws pack content in a closed section after Record and the Track cards, before "The Study so far". The panel adds nothing above its first block. The section identifies the installed packs, including when there are none. Without a Study, a person chooses a Track to see its stations. `next_step` remains the sole indication of what waits. The read computes no current station.

## Format and reads

A `lesson-pack/1` directory contains `pack.json` and `lessons.json`. The schema ships at `src/hypotrail/lessons/lesson-pack.schema.json`. The manifest declares its identity and semantic version, title, English language, licence, supported Tracks, the Hypotrail commit it was checked against and eight ordered stations: intake, framing, data, baseline, iterate, compare and decide, held-out pass, and delivery. The manifest gives each station a title, purpose, location and chat flag. The held-out pass takes place at the evaluator and has no chat or lesson.

A lesson has a unique identifier, station, Track and title. It explains why the step matters, what to do, how to read the evidence and what can go wrong. It may include one question, key paths into `status` or `figures` and up to three HTTPS links. Lessons are shown under stations. The format has no `step_kind` field.

`lesson check` reports these rules:

- `SCHEMA`: the JSON Schema fails.
- `DIGIT`: an ASCII digit appears in a station title or purpose, or in a lesson field other than `id`, `key_paths` and `links`.
- `UNRESOLVED_PATH`: no kept read of that read kind and Track resolves the key path.
- `FORBIDDEN_PATH`: a path segment, after stripping `[]`, contains `reference`, `case`, `per_item`, `public_check` or `held_out`.
- `HELD_OUT_LESSON`: a lesson names the held-out station.
- `CHAT_FLAG`: a station disables chat outside the held-out pass or enables it at that pass.
- `DUPLICATE_LESSON_ID`: two lessons share an identifier.

The CLI reports invalid packs without their content. The first valid pack for the Track supplies its stations and lessons. Each lesson identifies its source with the pack id and version.

With a Study, the station marks come from `status`: at least one dev Assessment for baseline, at least two for iterate, and a Comparison or Decision for compare and decide. All other marks are null. `lesson --track` reads the pack without a Study, with no Track cards and all marks null. These reads write nothing, acquire no lock and record no Exposure.

## Alternatives rejected

- Track-owned method lessons under D-202. D-203 assigns that content to separately maintained data packs.
- Packs as code plugins. Code running in the CLI could access the Study across the held-out boundary.
- Agent-side files only. Their content would escape the pack checks and be invisible to the panel.
- A French pack. ADR 0007 keeps teaching content served by the product in English.

## Amendment — 2026-11-27

D-209 adds teaching figures to the accompanied journey. The panel can show the interval of an eligible development Comparison using the stored estimate and bounds. The renderer owns the chart and its text equivalent, and pack key paths do not select its data. When the interval is unavailable, the lesson can lead to the existing aggregate distribution.

`lesson-pack/2` extends the base schema by accepting an optional `illustration` object on a lesson. It carries a layout, labels and a caption. A flow takes two to four labels and a comparison takes two. Each label has at most sixty-four characters and a caption has at most two hundred and forty. These fields use plain single-line text without digits. The extension schema is `src/hypotrail/lessons/lesson-pack-illustration.schema.json`. The first format still accepts the original fields. Diagrams share the panel's theme and work before a Study exists.

## Amendment — 2026-11-27 (closeout)

`lesson check` applies the D-204 per-Track allowlist of exact Track, read and path triples. Each listed path names a safe aggregate or metadata leaf. A path outside the allowlist is `FORBIDDEN_PATH` even if none of its segments matches a forbidden term. Discovery applies the same rule offline, and `lesson check` additionally resolves allowed paths against the Track's kept reads.

`lesson-pack/2` remains merged, pending owner approval (G1).

## Amendment — 2026-11-28

ADR 0010 adds the accompanied journey beside the packs (D-278 on chadlis/hypotrail#75). On a Track that serves a journey:

- the panel draws the journey, not the stations: the sentences "The panel adds nothing above its first block" and "in a closed section after Record" no longer bind it;
- the core computes the current step (ADR 0010, point 2); "The read computes no current station" still describes the `lesson` read;
- the `DIGIT` rule still binds packs. Journey content is checked by its own lint: no hand-written digit, slots allowed.

Packs, `lesson check` and `lesson --track` are unchanged. The command "Hypotrail: Show stations" stays.
