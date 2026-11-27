# The product serves lesson packs; it authors none

Status: accepted (D-203 on chadlis/hypotrail#75)

## Decision

Track cards explain what a step of a Study shows and how to read it. Lesson packs teach how to do a step of the method. Pack authors develop teaching content in chadlis/hypotrail-lessons. Hypotrail ships a format and checks, loads and serves the content verbatim. The core has no dependency on packs. The CLI reads them from the explicit directory list in `HYPOTRAIL_LESSON_PACKS`, in discovery order. Packs are JSON data.

The panel stays here because it is the other half of the read contract and the Python suite regenerates its kept reads. With a Study, it draws pack content in a closed section after Record and the Track cards, before "The Study so far". The section identifies the installed packs, including when there are none. Without a Study, a person chooses a Track to see its stations. `next_step` remains the sole indication of what waits. The read computes no current station.

## Format and reads

A `lesson-pack/1` directory contains `pack.json` and `lessons.json`. The manifest declares its identity and semantic version, title, English language, licence, supported Tracks, the Hypotrail commit it was checked against and eight ordered stations: intake, framing, data, baseline, iterate, compare and decide, held-out pass, and delivery. The manifest gives each station a title, purpose, location and chat flag. The held-out pass takes place at the evaluator and has no chat or lesson.

A lesson has a unique identifier, station, Track and title. It explains why the step matters, what to do, how to read the evidence and what can go wrong. It may include one question, key paths into `status` or `figures` and up to three HTTPS links. Lessons are shown under stations. Text carries no Study value, and key paths cannot reach References, Cases, per-item results, `public_check` or held-out records.

`lesson check` validates the schema, text, chat flags, unique lesson identifiers and permitted key paths against kept reads. The CLI reports invalid packs without their content. The first valid pack for the Track supplies its stations and lessons. Each lesson identifies its source with the pack id and version.

With a Study, the station marks come from `status`: at least one dev Assessment for baseline, at least two for iterate, and a Comparison or Decision for compare and decide. All other marks are null. `lesson --track` reads the pack without a Study, with no Track cards and all marks null. These reads write nothing, acquire no lock and record no Exposure.

## Alternatives rejected

- Track-owned method lessons under D-202. D-203 assigns that content to separately maintained data packs.
- Packs as code plugins. Code running in the CLI could access the Study across the held-out boundary.
- Agent-side files only. Their content would escape the pack checks and be invisible to the panel.
- A French pack. ADR 0007 keeps teaching content served by the product in English.
