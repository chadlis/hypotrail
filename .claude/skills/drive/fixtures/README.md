# Fixtures of the drive scripts

- `fix-prompts/`: the fix prompts given to the `slice-builder` in the first two slices, word for word, as posted in the comments that start "the fix prompt given to the `slice-builder`, word for word" on chadlis/hypotrail#120 (comments 7067621287, 7068086757, 7068469893, 7068749877: `r1-round-1` to `r1-round-4`) and on chadlis/hypotrail#138 (comments 7070672317, 7070861085, 7071070961, 7071276599: `r1b-round-1` to `r1b-round-4`).
- `sources/`: the texts that those prompts quote, as read on 2026-11-22, named after where they come from: `issue-<n>-body` (an issue body), `issue-<n>-comment-<id>` (a comment), `repo-<name>` (a file of the repository before the change that quotes it). Only the sources that a quotation of a prompt is found in are kept.

`tests/test_fix_prompt_check.py` runs the quotation check on them.
