Work in /home/user/hypotrail/.claude/worktrees/slice-80 (branch slice-120, head 4a21209). This is a review fix for slice chadlis/hypotrail#138 (R1b), round 2. Nothing under `src/` changes. `git diff 8bb621e HEAD -- tests/_order_table.py` stays empty.

1. **replace**: the comment and constant `CORE_COPIES_OF_THE_ROLE_NAMES` in `tests/test_architecture.py` (around lines 134-139).
   - Name each exempt copy by file and symbol: `core/comparison.py` (`DEV`, `PUBLIC_CHECK`) and `report/gather.py` (`PUBLIC_CHECK`).
   - Say that the exemption holds while a question stays open. Quote that question whole and attribute it: chadlis/hypotrail#117, Q2: "Where do the core's copies of the role names (`core/comparison.py:44-45`, `report/gather.py:14`) belong, given that the core imports no Track?"
   - Also quote #130 c4's sentence: "A string constant of `src/` that equals a role of either Track is allowed only in that Track's partitions module and in the two files of Q2, `core/comparison.py` and `report/gather.py`, which the test names with the reason."
   - What stays as it is: the two files remain the only exemption.
2. **replace**: `READ_SEQUENCE_FAULT_CALLERS` and its comment in `tests/test_study_write_contract.py` (around lines 31-33). Structural fix.
   - `src/hypotrail/cli.py:35-42` shows that `_read_sequence_value` is argparse's `type=` for `--read-sequence` on every command: the command line judges the value at parse time. `init`'s own refusal (`cli.py:403`) does not call `read_sequence_fault`.
   - Name the allowed callers by function, exactly: `hypotrail.core.study_write:check_read_sequence` and `hypotrail.cli:_read_sequence_value`. The test asserts that the set of callers equals that set.
   - The comment says what the code does: the parse-time check of the command line, and the module's check for library callers.
   - **replace** the test's name with one that says what it checks.
   - What stays as it is: the `REQUEST_ID_EMPTY` half.
   - Red run: a planted call of `write_journal.read_sequence_fault` in another function of `cli.py`.
3. **replace**: the receiver check. Structural fix for #134 c4: "No call into the Study-write module passes a command name or a journal kind as a string literal".
   - Move `parameters_of`, `receiver_violations` and the binding walk into `tests/_architecture.py`, reusing `defined_functions` rather than repeating its walk. The test that asserts at least one binding is found then uses the same walk as the check.
   - Make the check a closed world. Each name bound to a `Write` is a `with … as` name of `study_write.locked`, or a parameter that receives one, at any depth, nested functions included, positional-only parameters included. Every use of such a name must be one of:
     - a method call on it (`write.x(...)`);
     - a bare positional or keyword argument to a call the resolver follows, including `self.m(write)` when `self`'s class is resolvable.
   - Any other use fails the test, naming the function and the use: a rebinding (`w = write`), `*args`, an attribute stored, a call that does not resolve.
   - What stays as it is: the existing literal check, and the rule that the binding is named `write`.
   - Red runs, one per case: a nested helper taking `w`; `w = write` followed by `w.wrote("assessment", …)`; a `write` passed in `*args`; a `write` passed to a call that does not resolve.
4. **replace**: in the agent-schema red case of rule 4 (`tests/test_architecture.py`, around line 236), assert the exact problem message, not only `len(...) == 1`. What stays as it is: the `ml` case, which already asserts its message.

Your hand-back lists every test, table row or assertion you removed or replaced, beside the line above that asks for it. Each new or changed witness has its red run. Commit with messages saying what changed and why, each ending with:

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014N3DRHr6Mxdp96QxHJy1m5

Then run the full suite on a clean tree with `uv run --locked --all-extras pytest`, and report its exact final line beside `git rev-parse --short HEAD`. Do not push. Leave no background process running.

If the repository does not settle a question, stop and hand back with the question. Do not decide in my place.
