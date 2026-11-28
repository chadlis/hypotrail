---
name: verify-panel
description: "Render the Study panel of the VS Code client at a given head as headless Chrome draws it. The regular contact sheet uses VS Code's four default themes. The parity sheet compares the frozen French and English reference panels with the build in both board themes at 420 and 900 px. The builder links the sheet in the hand-back for review."
---

# Verify the panel: a contact sheet of a head

The client's tests assert what a document holds and a few drawn properties. They show no picture. This skill draws every state of the panel so that a reader can look at it.

## Run

From a checkout of chadlis/hypotrail, with Chrome at `/usr/bin/google-chrome` (or the path in `HYPOTRAIL_CHROME`):

```bash
node .claude/skills/verify-panel/render.js <output folder> <head>
```

- `<head>` is any revision Git resolves (`HEAD`, a SHA, a branch). The script extracts `clients/vscode/` at that revision into a scratch folder, runs `npm ci` and the TypeScript build there, and never touches the checkout. It needs no package beyond the client's own: it draws through the client's `test/chrome.ts` and makes the documents with its `test/panel-harness.ts` on its kept CLI output (`test/cli/`).
- `<output folder>` receives `sheet.html`, one PNG per shot, the documents under `html/`, and `contrast.json`, `positions.json` and `keyboard.json`. Put it in the session's scratchpad, not in the repository.
- The last line printed names the sheet, the number of documents and shots, and the head. A missing Chrome, a failed build or a failed step exits 1.

## Parity sheet

```bash
node .claude/skills/verify-panel/render.js <output folder> <head> --parity <reference folder>
```

The reference folder holds the approved `reference/index.html` and
`reference-en/index.html`. The command replays their stored panels offline
in Chromium, including each screen's default view and the archival Annex.
It captures the full panel in the two board themes at both exact widths and
records the input SHA-256 values in `parity.html`.

For a screen that has build evidence, place its self-contained rendered HTML
under `<output folder>/parity-mpg/<full Git SHA>/`, named for the English DOM
fixture and theme, for example `01-discover_data--blackboard.html`. Supply the
matching `01-discover_data.dom-differences.json` as an array of messages from
the DOM check. An empty array records a check with no reported differences.
The sheet draws the pre-rendered HTML with scripts disabled and lists the
DOM findings under the image pair. A missing rendered document is shown as
"no build state". Supply only approved parity artifacts from the kept-state
harness. The command opens the archived references and those rendered
documents, with their reported DOM findings.

The output folder contains `parity.html` and its `parity-shots/`. Each row
shows the French reference and English twin on the left and the matching
build on the right, with an AA list for each drawn panel. Keep the sheet
and its images together in the scratchpad.

## What the sheet shows

- Every read the harness can make from the kept output (each read of its `KEPT_READS` with the figures of the kept `figures-*` read made beside it, or a failed figures call where none is kept, a read whose figures call fails, a refused read, a read with no answer, a Decision a link names, a Comparison two Decisions cite) and every step of a write (in flight, recorded, refused, invalid, with no answer, sent again), each in Light+, Dark+, High Contrast and High Contrast Light at 420 and 900 px, full page.
- At 420 px, each text whose contrast with what it stands on is under WCAG's AA, and where the first pending question, its first number and its Record control stand.
- On the read of status-success at 420 by 700 px: the Tab stops up to the first radio, then Space, Tab, Enter and the pointer over the options, each shot, with the messages the document posted.
- Every kept state of the journey (`test/cli/journey/`), drawn like the reads above, and on each, in each theme at 420 by 700 px, the keyboard path: where Now holds a pending decision, Tab to its first radio, Space and Tab to Record, shot with focus, and whether each was reached; otherwise the page's Tab stops.

## Its limits

- VS Code is not run. The theme variables are VS Code's registry defaults; a variable a theme leaves undefined is left out, and the injected default webview style is approximated.
- The states are those the harness and the kept output give. A state they cannot make is not on the sheet; say so beside the sheet when a ticket's surface needs it.
- The sheet is evidence to look at, not a test. A finding it shows goes into the review's register like any other.
