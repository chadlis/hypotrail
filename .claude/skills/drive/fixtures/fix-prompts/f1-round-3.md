Work in /home/user/hypotrail/.claude/worktrees/slice-121 (branch slice-121, head aeccc8d). This is a review fix for slice chadlis/hypotrail#121 (F1), round 3. The routing is in comment 7073987486 on #121. Finding IDs: F2-P-01, F3-S-01, F3-S-02, F3-P-01, F2-S-03.

#142 Tightened B, quoted whole:
> **B** (the matrix; replaces the second criterion). The neighbouring cases of the same family are refused the same way, for each of the two inputs. The test's matrix is: input (mapping, population) crossed with fault (a duplicate key at the top level; a duplicate key inside a nested object; `NaN`; `Infinity` and `-Infinity`; an integer outside the range `canonical.loads` accepts), each refused with the input's own code of Tightened A (`MAPPING_INVALID` or `POPULATION_INVALID`, `problem` `not_json`), exit 2 and no file changed; plus one accepted call per input with the fault removed. A cell's result today, for comparison: a duplicate key at the top level is accepted; a non-finite or out-of-range value in the mapping is `MAPPING_VALUE_INVALID`; inside `item_ids` it is `POPULATION_INVALID` with `problem` `bad_items`.

1. **replace** (F2-P-01, F3-S-01, F3-S-02, F3-P-01). This is the structural option of the routing comment. In `tests/test_import_ml.py`, rewrite `STRICT_FAULTS`, `INVALID_FIRST_COPY`, `FAULT_MARKER`, `text_with_fault` and `write_mapping_and_population` (about `:152-190`). The new shape: each fault cell is the input's clean JSON text (`json.dumps` of the clean mapping or population, as the accepted call writes it) with one fragment inserted at one place. The fragment carries the fault. Placements, unchanged in meaning from aeccc8d except the population is no longer shortened:
   - mapping, top-level duplicate: a first copy of an allowed key with an invalid value, before the valid copy (the last copy is the valid one);
   - mapping, nested duplicate: a member `"extra"` holding an object with a repeated key (no key of the mapping may hold an object: `ml/imports.py:129-131`);
   - mapping, `NaN`, `Infinity`, `-Infinity`, the out-of-range integer: the value of a member `"model"` (`"model"` is an allowed key, `ml/imports.py:59`; the clean mapping has no `"model"`);
   - population, top-level duplicate: a first copy of `"item_ids"` with an invalid value, before the valid copy;
   - population, the other faults: one more element appended to the full `item_ids` list, after its last Item.
   Every comment and docstring in that range says only what holds for every entry it describes.
2. **replace** (F2-P-01, F3-S-01). The accepted test at about `:215-223`. Per input, it asserts both of the following, and its name says both:
   - for every fault of that input, the faulty text with its fragment cut out once equals the clean text character for character;
   - the clean mapping and population are accepted (exit 0) and recorded (the attempt directory exists).
   Its docstring states no equivalence the test does not assert.
   **What stays as it is:** one accepted call per input, the parametrization on the input, the request ids distinct per input.
3. **replace** (F2-S-03). The section heading at `tests/test_architecture.py:486` names only what the section's tests assert: the functions under `src/` that raise `INVALID_ARGUMENTS`, with their numbers of calls, compared both ways with the list; and the `details.command` of the runs the section lists. It claims no form for a refusal no run reaches.
   **What stays as it is:** `INVALID_ARGUMENTS_BUILDERS` and its comments, the tests under the heading, their runs.

**What stays as it is, for items 1 and 2:** the 12 refusal cells (input × fault), their expected result at HEAD (`MAPPING_INVALID` or `POPULATION_INVALID`, stage `import`, `problem` `not_json`, `details` keys `{input, problem}`, exit 2), the "nothing is written" assertions, and the docstring's statement of each cell's result at c77b9a6 (correct it only where the new population placement changes a result there).

Witnesses, each in your hand-back with its command and output:
- the 12 cells and the accepted test run against the c77b9a6 source (from `git archive c77b9a6` into your scratchpad, with HEAD's test file): each refusal cell red, with its result at c77b9a6;
- the equality of item 2 shown red once on a planted mis-built cell (for example a population cell that also drops an Item), then the plant removed. Do not commit the plant.

Your hand-back lists every test, row or assertion you removed or replaced, each beside the item above that asks for it. Commit with messages that say what changed and why, each ending with:

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014N3DRHr6Mxdp96QxHJy1m5

Then run the full suite on a clean tree, in the foreground with a 600 s timeout, and report its final line beside `git rev-parse --short HEAD`. Do not push, and leave no background process running.

If a command is refused, stop and hand back with the refusal. If the repository does not settle a question, stop and hand back with the question. Do not decide in my place.
