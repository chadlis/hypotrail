---
name: verify-panel
description: "Render the Study panel of the VS Code client at a given head as headless Chrome draws it, in VS Code's four default themes at 420 and 900 px, and write a contact sheet of the shots with the texts under AA contrast and the keyboard path to Record. Use when a ticket has a user-facing surface: the builder links the sheet of its head in its hand-back, and the UX review and the Spec reader receive it."
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

## What the sheet shows

- Every read the harness can make from the kept output (each read of its `KEPT_READS` with the figures of the kept `figures-*` read made beside it, or a failed figures call where none is kept, a read whose figures call fails, a refused read, a read with no answer, a Decision a link names, a Comparison two Decisions cite) and every step of a write (in flight, recorded, refused, invalid, with no answer, sent again), each in Light+, Dark+, High Contrast and High Contrast Light at 420 and 900 px, full page.
- At 420 px, each text whose contrast with what it stands on is under WCAG's AA, and where the first pending question, its first number and its Record control stand.
- On the read of status-success at 420 by 700 px: the Tab stops up to the first radio, then Space, Tab, Enter and the pointer over the options, each shot, with the messages the document posted.
- Every kept state of the journey (`test/cli/journey/`), drawn like the reads above, and on each, in each theme at 420 by 700 px, the keyboard path: where Now holds a pending decision, Tab to its first radio, Space and Tab to Record, shot with focus, and whether each was reached; otherwise the page's Tab stops.

## Its limits

- VS Code is not run. The theme variables are VS Code's registry defaults; a variable a theme leaves undefined is left out, and the injected default webview style is approximated.
- The states are those the harness and the kept output give. A state they cannot make is not on the sheet; say so beside the sheet when a ticket's surface needs it.
- The sheet is evidence to look at, not a test. A finding it shows goes into the review's register like any other.
