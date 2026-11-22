Work in /home/user/hypotrail/.claude/worktrees/slice-80 (branch slice-120, head 1979cde). This is a review fix for slice chadlis/hypotrail#138 (R1b), round 1. Nothing under `src/` changes except point 2. `git diff 8bb621e HEAD -- tests/_order_table.py` stays empty.

1. **replace**: `tests/test_architecture.py` around lines 134-136, 198 and 206. "Q2 of #117", `Q2_FILES` and `…_two_files_of_q2…` label things by a question ID. The comment also cites line numbers.
   - Name the constant and the tests by what they hold. For example, `CORE_COPIES_OF_THE_ROLE_NAMES`: `core/comparison.py` and `report/gather.py`, named by file and symbol, not by line.
   - The comment quotes the source sentence whole. That sentence is chadlis/hypotrail#117, Q2: "Where do the core's copies of the role names (`core/comparison.py:44-45`, `report/gather.py:14`) belong, given that the core imports no Track?"
   - Rule: `.claude/agents/slice-builder.md`: "A comment cites a requirement only by quoting the source sentence the prompt gives".
   - What stays as it is: the two files remain the only exemption, with their reason.
2. **remove**: `COMMAND = study_write.ASSESS` in `src/hypotrail/ml/assess.py:40`. Nothing reads it (`grep -rn "assess\.COMMAND"` finds nothing). What stays as it is: every use of `study_write.ASSESS`.
3. **replace**: the guard check in `tests/test_study_write_contract.py`, around line 37. It looks only for the removed name `require_valid_read_sequence`.
   - #134 c2: "`require_valid_read_sequence` is called from the Study-write module only". That guard is now `write_journal.read_sequence_fault`.
   - #133 Tightened C: creating a Study keeps "the refusal at `cli.py:406`". So `read_sequence_fault` may be called from `core/study_write.py` and, for `init`'s refusal, from `cli.py` only. The check asserts that, through the resolver.
   - What stays as it is: the `REQUEST_ID_EMPTY` half of the test.
   - Red run: a planted call of `write_journal.read_sequence_fault` in `ml/assess.py`.
4. **add**, structural. #134 c4: "No call into the Study-write module passes a command name or a journal kind as a string literal". The check sees a `Write` only through the receiver spelled `write` (`WRITE_RECEIVER`).
   - Add an AST test, through `tests/_architecture.py`. Every `with study_write.locked(...) as <name>` binds `write`. Every function that receives the session as a parameter, that is every function a locked body passes `write` to, names that parameter `write`.
   - Then the receiver-spelling check sees every `Write`.
   - What stays as it is: the existing literal check.
   - Red runs: a planted `with study_write.locked(...) as w:`, and a planted helper whose parameter is named `w`.
5. **remove**: the assertion `assert role_sets(trees) == {"agentic": {…}, "ml": {…}}` in `tests/test_architecture.py`, around line 200. #130 c4: "the test reads each Track's role set from its partitions module, never from a list typed in the test". What stays as it is: every other assertion of rule 4.
6. **replace**: the schema red cases of rule 4. #130 Tightened B's witness: "shown red once in the builder's hand-back on a role removed from the `cases` of a copy of the agent schema, and once on a role name planted in a copy of the `ml` schema".
   - The planted-tree test copies the two real schema files (`shutil.copy` or a JSON load of the real files), edits the copy, and runs the rule on it.
   - What stays as it is: the passing run on the real schemas.
7. **replace**: the comment in `tests/_order_inventory.py`, around lines 115-116, "for the five writers that share the write protocol (…), by `study_write.locked`". After #133, every writer takes the lock through `study_write.locked`. #134 c8 asks that docstrings "say what the code does after the move".

Your hand-back lists, beside the line above that asks for it, every test, table row or assertion you removed or replaced. Each new or changed witness has its red run. Commit with messages saying what changed and why, each ending with:

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014N3DRHr6Mxdp96QxHJy1m5

Then run the full suite on a clean tree with `uv run --locked --all-extras pytest`, and report its exact final line beside `git rev-parse --short HEAD`. Do not push. Leave no background process running.

If the repository does not settle a question, stop and hand back with the question. Do not decide in my place.
