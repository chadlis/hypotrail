Work in /home/user/hypotrail/.claude/worktrees/slice-121 (branch slice-121, head ab3c53d). This is a review fix for slice chadlis/hypotrail#121 (F1), round 4. The routing is in comment 7074310380 on #121. Finding IDs: F4-P-02, F2-S-03, F4-P-01.

#142 Tightened B, each line quoted whole as its own quotation:
> **B** (the matrix; replaces the second criterion). The neighbouring cases of the same family are refused the same way, for each of the two inputs. The test's matrix is: input (mapping, population) crossed with fault (a duplicate key at the top level; a duplicate key inside a nested object; `NaN`; `Infinity` and `-Infinity`; an integer outside the range `canonical.loads` accepts), each refused with the input's own code of Tightened A (`MAPPING_INVALID` or `POPULATION_INVALID`, `problem` `not_json`), exit 2 and no file changed; plus one accepted call per input with the fault removed. A cell's result today, for comparison: a duplicate key at the top level is accepted; a non-finite or out-of-range value in the mapping is `MAPPING_VALUE_INVALID`; inside `item_ids` it is `POPULATION_INVALID` with `problem` `bad_items`.

> Source: D-056 item 1: "**#142, the code.** Every refusal of the strict reader keeps the input's own code: `MAPPING_INVALID` or `POPULATION_INVALID`, with `problem` `not_json`. The ml rows of the handbook for `not_json` add "(`NaN`, a repeated key or an out-of-range number included)". The phrase "with `NON_CANONICAL_VALUE`" in #121 is recorded as not holding." Drive skill, "Fixing a family of defects": "When a defect reveals a family of mishandled inputs, the fix verifies the neighbouring cases the contract covers, not only the first counterexample." "Check the coded refusal at the public entry point concerned, and that no forbidden effect happens before it. Keep valid cases, so that a validator that refuses everything fails." `core/canonical.py`, `loads` docstring: "Parse JSON strictly (duplicates, `NaN`, `Infinity`, out-of-range numbers refused)."

> Witness: the parametrised test of the first criterion (`python -m hypotrail import ml ... --json`, with a snapshot of the Study's files before and after each refused call), over the whole matrix; shown red in the builder's hand-back at `c77b9a6` on every cell whose result differs today.

> Proves: no T-xx.

D-058 (chadlis/hypotrail#75, comment 7074306651), which settles what "with the fault removed" asks; its decision section, quoted whole:

> ### Decision: L-prime, with the second reading's conditions
> 
> For #142 Tightened B, "with the fault removed" is read at the grain of one item. The faulty file the product reads differs from the clean file the accepted call writes by exactly one item: one top-level pair or one element of `item_ids`. That item holds the fault.
> 
> The decision makes these changes in `tests/test_import_ml.py`:
> - **add**, in the accepted test, one check per fault of the input:
>   - read both whole texts leniently, with `json.loads(..., object_pairs_hook=list, parse_constant=...)` and `NaN`, `Infinity` and `-Infinity` mapped through `parse_constant`;
>   - assert that removing exactly one item (one top-level pair, which covers a first copy, or one element of `item_ids`) from the faulty reading gives the clean reading;
>   - use nothing from `fragment_and_place`.
> - **add**, in that test's docstring, the check's limit: the grain is one member or one element. Nothing checks what the fault's own value holds inside that item.
> - **What stays as it is:**
>   - the computed fragments (`fragment_and_place`, `text_with_fault`);
>   - the text equality `faulty.replace(fragment, "", 1) == clean`;
>   - one accepted call per input;
>   - the 12 refusal cells and their expected results.
> 
> **Witness:** the check shown red in the hand-back on one planted widened fragment for each input, for example `, "model": NaN, "x": "y"` and `, NaN, "z"`. The plants are not committed.
> 
> **Scope:** F1 (#121), ticket #142, review round 4. Nothing under `src/` changes.
> 
> **Reversibility:** one commit.
> 
> **Commits it allows:** the round-4 fix on `slice-121` that carries these changes.

1. **add** (F4-P-02). Apply D-058 above in the accepted test of `tests/test_import_ml.py` (`test_each_fault_cell_of_an_input_minus_its_fragment_is_its_clean_text_and_the_clean_mapping_and_population_are_accepted_and_recorded`): the check and the docstring line it names. The test's name says what it now checks too. **What stays as it is:** what D-058 lists under "What stays as it is".
2. **replace** (F2-S-03). The section heading at `tests/test_architecture.py:486` keeps only its first clause: the functions under `src/` that raise `INVALID_ARGUMENTS`, with their numbers of calls, are the listed ones and no others. **remove:** its second clause, about `details.command`. Use no noun the suite refuses (`tests/test_run_noun.py` refuses "run" as a noun under `tests/`).
3. **replace** (F4-P-01). The name of the test at `tests/test_architecture.py:532` says "each" refusal, but its cases reach neither `core.study_write:invalid_arguments` nor `core.decisions._invalid`. Its name says what it checks: the `details.command` of each case it lists. **What stays as it is:** its cases, their expected values and its assertions; `INVALID_ARGUMENTS_BUILDERS` and its comments; the two other tests of that section.

Witnesses, each in your hand-back with its command and output:
- the check of item 1 shown red on one planted widened fragment for each input (for example `, "model": NaN, "x": "y"` for the mapping and `, NaN, "z"` for the population), then the plants removed. Do not commit the plants.

Your hand-back lists every test, row or assertion you removed or replaced, each beside the item above that asks for it. Commit with messages that say what changed and why, each ending with:

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014N3DRHr6Mxdp96QxHJy1m5

Then run the full suite on a clean tree, in the foreground with a 600 s timeout, and report its final line beside `git rev-parse --short HEAD`. Do not push, and leave no background process running.

If a command is refused, stop and hand back with the refusal. If the repository does not settle a question, stop and hand back with the question. Do not decide in my place.
