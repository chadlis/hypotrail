# Fixtures of the drive scripts

- `fix-prompts/`: the fix prompts given to the `slice-builder` in the first two slices, word for word, as posted in the comments that start "the fix prompt given to the `slice-builder`, word for word" on chadlis/hypotrail#120 (comments 7067621287, 7068086757, 7068469893, 7068749877: `r1-round-1` to `r1-round-4`) and on chadlis/hypotrail#138 (comments 7070672317, 7070861085, 7071070961, 7071276599: `r1b-round-1` to `r1b-round-4`). For F1, the third slice: the text inside the fence of the fix-prompt comments on chadlis/hypotrail#121 (comments 7073494290, 7073748468, 7073997610, 7074315935: `f1-round-1` to `f1-round-4`), and `f1-d060`, the prompt of the wording fix under D-060 (chadlis/hypotrail#75, comment 7074747777), as the drive kept it.
- `sources/`: the texts that those prompts quote, as read on 2026-11-22, named after where they come from: `issue-<n>-body` (an issue body), `issue-<n>-comment-<id>` (a comment), `repo-<name>` (a file of the repository before the change that quotes it). Only the sources that a quotation of a prompt is found in are kept. `issue-121-comment-7073490371` is a record, not a source: `f1-round-1` quotes handbook chapter 14, an HTML file the hook does not read, and on GitHub only comments of #121 hold that text (this one, the routing comment 7073490550 and the prompt's own comment); this one is kept.

`tests/test_fix_prompt_check.py` runs the quotation check on them.

## Stated limit: the hook as it ran and its fixtures

D-061 on chadlis/hypotrail#75, as amended by D-063 on chadlis/hypotrail#75, item 5: "Before the fixtures are trusted, the divergence between the hook as it ran and its fixtures is explained or stated as a limit."

Known facts:
- On F1's rounds 1 and 2, the hook as it ran printed one warning each, "finding IDs: the prompt names none" (comments 7073497019 and 7073750373 on chadlis/hypotrail#121), and no quotation warning.
- On the posted prompt text (`f1-round-1`, `f1-round-2`), the checker of c77b9a6 (`git log` gives it no other version before this branch) finds the prompts' finding IDs and gives 5 quotation warnings that the tests hold true: 4 on round 1 and 1 on round 2. So the hook as it ran missed those 5 true warnings and raised 2 false ones.
- On rounds 3 and 4 and on the D-060 prompt, the checker of c77b9a6 gives on the fixtures exactly what the hook printed (comments 7074001592 and 7074322178 on #121, and the D-060 warning).
- No fixture covers the 2 "names none" warnings.

Deduction, not checked: in rounds 1 and 2, the Agent call carried a short prompt that contained "This is a review fix" and pointed to the prompt file. The hook then checked that short prompt, which names no ID and quotes nothing, and not the file.

## Stated limits of the quotation check

- The label exemption accepts a quotation of at most five words that any source the check reads sets in double quotes or as a bold label, not only the source the prompt cites.
- A run of lines of a list item that spreads over several lines is whole when every other line of the item is found inside some quotation of the prompt. So line 1 of a two-line item passes when line 2 appears only as a substring of another quotation, not quoted on its own.
- A list item whose wrapped line is not indented under its marker is not read as one item. With the source "- The order is defined once, in one\nfunction of `core/write_journal.py`.", each half passes when quoted alone. The checker of c77b9a6 warned on both.
