Work in /home/user/hypotrail/.claude/worktrees/slice-121 (branch slice-121, head 5b6394e). This is a review fix for slice chadlis/hypotrail#121 (F1), round 1. The routing is comment 7073490550 on #121.

1. **F1-P-03, replace.** #142 B says "a duplicate key at the top level is accepted" today. In `tests/test_import_ml.py`, the top-level duplicate cell of the population repeats `"item_ids": []`. At c77b9a6 the last value wins, so that cell is already refused today, as `bad_items`.
   - Change the top-level duplicate of each input so that the old reader accepts it. The first copy is invalid and the last copy is the valid value, so that last-wins reading gives a valid document.
   - Run it at c77b9a6 to show that the old code accepts it. Then show it red there, on the code assertion.
   - Do the same for any other fault whose cell the old code already refuses. If a fault cannot be placed so that the old code accepts it, say so in the test's docstring with the reason, and keep the cell.
   - The handbook probe of the import table uses the same duplicate. Change it in the same way.
   - What stays as it is: the matrix, its expected codes, and "nothing written".
2. **F1-P-04, replace.** #142 B asks for "plus one accepted call per input with the fault removed". Make the accepted test run, for each input, the faulty document with only the fault removed. What stays as it is: the test's assertions.
3. **F1-P-01, replace.** #143 C says "do not restate it". Chapter 14, line 37, adds "the write-journal position first, not `recorded_at` alone". Remove that clause and keep the link. Rebuild the handbook.
4. **F1-P-05, replace.** #143 B says "The order is defined once". `src/hypotrail/core/decisions.py:28-31` spells the order out in the module docstring. Replace the spelled-out rule with a pointer to `write_journal.assessment_order`, as `rescoring.py` does.
5. **F1-P-02, replace.** #145 D reads "the 'When' cell of chapter 04's row … the `details` cell of chapter 10's row". `command_forms` in `tests/test_handbook.py`, around line 1680, searches the whole row. Make the test read each named cell by its column. Red run: the form moved into another cell.
6. **F1-S-01, replace.** The test `test_the_functions_that_raise_invalid_arguments_are_the_listed_builders_and_each_gives_hypotrail_command` in `tests/test_architecture.py` reads only counts. Remove the unused `tmp_path` parameter and the unused form element of `INVALID_ARGUMENTS_BUILDERS`. Keep each entry's reason as a comment, and rename the test to what it checks. `slice-builder.md` says "a test name says what the test checks".
7. **F1-S-02, replace.** `_loose_json`, `_loose_partition` and `loose_mapping` in `src/hypotrail/ml/imports.py` (lines 97, 105 and 322) are now strict. Rename them and correct their docstrings. What stays as it is: their behaviour.

Your hand-back lists, beside the line above that asks for it, every test, table row or assertion you removed or replaced. Each new or changed witness has its red run. Commit with messages that say what changed and why, each ending with:

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014N3DRHr6Mxdp96QxHJy1m5

Then run the full suite on a clean tree, and report its final line beside `git rev-parse --short HEAD`. Do not push. Leave no background process running. Never use `git stash pop`.

If a command is refused, stop and hand back with the refusal. If the repository does not settle a question, stop and hand back with the question. Do not decide in my place.
