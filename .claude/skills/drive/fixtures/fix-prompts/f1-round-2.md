Work in /home/user/hypotrail/.claude/worktrees/slice-121 (branch slice-121, head 21db3bb). This is a review fix for slice chadlis/hypotrail#121 (F1), round 2. The routing is in comment 7073742879 on #121.

#142 Tightened B reads as follows. It is quoted whole, and items 1 and 2 below both answer it:
> **B** (the matrix; replaces the second criterion). The neighbouring cases of the same family are refused the same way, for each of the two inputs. The test's matrix is: input (mapping, population) crossed with fault (a duplicate key at the top level; a duplicate key inside a nested object; `NaN`; `Infinity` and `-Infinity`; an integer outside the range `canonical.loads` accepts), each refused with the input's own code of Tightened A (`MAPPING_INVALID` or `POPULATION_INVALID`, `problem` `not_json`), exit 2 and no file changed; plus one accepted call per input with the fault removed. A cell's result today, for comparison: a duplicate key at the top level is accepted; a non-finite or out-of-range value in the mapping is `MAPPING_VALUE_INVALID`; inside `item_ids` it is `POPULATION_INVALID` with `problem` `bad_items`.

1. **replace** (F2-P-02). In `tests/test_import_ml.py`, the faults other than the top-level duplicate sit in an `"extra"` member. Move each one to the place Tightened B describes.
   - **Mapping:** the value of an allowed key (`MAPPING_KEYS` in `ml/imports.py:54-63`). For the nested duplicate, use a key whose value may be an object, if one exists; if none does, say so.
   - **Population:** inside `item_ids`.
   - At c77b9a6, check that each cell gives the result Tightened B states for today. Write that result, and its true reason, in the test's docstring, in place of the current reason.
   - **What stays as it is:** the top-level duplicate cells, the expected codes at HEAD, and "no file changed".
2. **replace** (F2-P-01). The accepted test runs 6 identical calls per input. Make it one accepted call per input, the input "with the fault removed". If removing every fault gives the same document, say so in the docstring.
   - **remove:** the `fault` parameter of that test.
   - Rename `text_of` and `documents_of` so their names say what they build.
3. **replace** (F2-S-02). In `ml/imports.py` (about line 323), `mapping_or_none` can hold any JSON value. Give it a name that says so. Behaviour is unchanged.
4. **replace** (F2-S-03). The section heading at `tests/test_architecture.py:486` must say what the section's tests check. The table lists the builders and their numbers of calls. The forms of `details.command` are checked at runtime by the test about line 530.

Your hand-back lists every test, row or assertion you removed or replaced, each beside the line above that asks for it. Every new or changed witness gets its red run, including a run at c77b9a6 for item 1. Commit with messages that say what changed and why, each ending with:

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014N3DRHr6Mxdp96QxHJy1m5

Then run the full suite on a clean tree, and report its final line beside `git rev-parse --short HEAD`. Do not push, and leave no background process running.

If a command is refused, stop and hand back with the refusal. If the repository does not settle a question, stop and hand back with the question. Do not decide in my place.
