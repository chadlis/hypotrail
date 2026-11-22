# Fixtures of the drive scripts

- `fix-prompts/`: the fix prompts given to the `slice-builder` in the first two slices, word for word, as posted in the comments that start "the fix prompt given to the `slice-builder`, word for word" on chadlis/hypotrail#120 (comments 7067621287, 7068086757, 7068469893, 7068749877: `r1-round-1` to `r1-round-4`) and on chadlis/hypotrail#138 (comments 7070672317, 7070861085, 7071070961, 7071276599: `r1b-round-1` to `r1b-round-4`). For F1, the third slice: the text inside the fence of the fix-prompt comments on chadlis/hypotrail#121 (comments 7073494290, 7073748468, 7073997610, 7074315935: `f1-round-1` to `f1-round-4`), and `f1-d060`, the prompt of the wording fix under D-060 (chadlis/hypotrail#75, comment 7074747777), as the drive kept it.
- `sources/`: the texts that those prompts quote, as read on 2026-11-22, named after where they come from: `issue-<n>-body` (an issue body), `issue-<n>-comment-<id>` (a comment), `repo-<name>` (a file of the repository before the change that quotes it). Only the sources that a quotation of a prompt is found in are kept. `issue-121-comment-7073490371` is a record, not a source: `f1-round-1` quotes handbook chapter 14, an HTML file the hook does not read, and on GitHub only comments of #121 hold that text (this one, the routing comment 7073490550 and the prompt's own comment); this one is kept.

`tests/test_fix_prompt_check.py` runs the quotation check on them.

## Known gap

The warnings "finding IDs: the prompt names none" posted for F1's rounds 1 and 2 (comments 7073497019 and 7073750373 on chadlis/hypotrail#121) do not reproduce on the posted prompt text: the checker finds the IDs of `f1-round-1` and `f1-round-2`. No fixture covers them. Deduction, not checked: the Agent call carried a short prompt that contained "This is a review fix" and pointed to the prompt file, so the hook checked that short prompt, which names no ID, and not the file.
