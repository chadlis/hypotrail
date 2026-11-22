Work in /home/user/hypotrail/.claude/worktrees/slice-80 (branch slice-120, head 04c9d38). This is a review fix for slice chadlis/hypotrail#138 (R1b), round 3. Nothing under `src/` changes, and `git diff 8bb621e HEAD -- tests/_order_table.py` stays empty.

1. **add**: D-054 on chadlis/hypotrail#75 (comment 7071065436). It says:
   > The check gains three rules:
   > 1. `study_write.locked(...)` appears only as the item of a `with` statement.
   > 2. The bound name is used nowhere outside its block. This includes a function defined before the block that captures the name.
   > 3. `Write` is constructed only inside the Study-write module.
   >
   > **Stop rule.** A later escape that code under `src/` actually uses is a blocker. An escape that is only planted is a stated limit, written down in the test's docstring and in the PR body.

   Add the three rules to the receiver check in `tests/_architecture.py`, with the resolver.
   - **Red cases.** Each rule gets planted red cases. Cover at least the two round-3 escapes: `w = write` after the block, and `cm = study_write.locked(...)` followed by `with cm as w`. Also cover a function defined before the block that captures `write`, and a `Write(...)` built outside the module.
   - **Limits.** The test's docstring names, as stated limits, the patterns the check still cannot see.
   - **What stays as it is:** the closed world inside the block, the rule that the binding is named `write`, and the literal check.
2. **add**: #134 c2. The allowed callers of `write_journal.read_sequence_fault` are `study_write:check_read_sequence` and `cli:_read_sequence_value`, but nothing checks who calls `_read_sequence_value`. Add a check that `_read_sequence_value` is used in `src/` only as the value of a `type=` keyword argument, never called directly. Red case: a planted direct call in `cli.py`. What stays as it is: the caller set.
3. **replace**: in `hand_over` (`tests/_architecture.py`), the positional index drops `self` but not `cls`, and a call through the class (`C.n(self, write)`) is reported as "has no parameter for it". Both give false failures. Fix both, and add a planted case for each that must pass. What stays as it is: every red case that exists today.
4. **replace**: the module docstring of `tests/_architecture.py`. It must say that the module also holds the receiver rule of the Study-write contract.

Your hand-back lists every test, table row or assertion you removed or replaced, beside the line above that asks for it. Each new witness has its red run. Commit with messages saying what changed and why, each ending with:

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014N3DRHr6Mxdp96QxHJy1m5

Then run the full suite on a clean tree with `uv run --locked --all-extras pytest`, and report its exact final line beside `git rev-parse --short HEAD`. Do not push. Leave no background process running.

If the repository does not settle a question, stop and hand back with the question. Do not decide in my place.
