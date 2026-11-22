Work in /home/user/hypotrail/.claude/worktrees/slice-80 (branch slice-120, head 5260fb1). This is a review fix for slice chadlis/hypotrail#138 (R1b), round 4. It changes text and one test only, never behaviour. Nothing under `src/` changes. `git diff 8bb621e HEAD -- tests/_order_table.py` stays empty.

1. **replace**: the docstring of limits of the receiver test (`tests/test_study_write_contract.py`, around lines 219-225).
   D-054 on chadlis/hypotrail#75 says:
   > **Stop rule.** A later escape that code under `src/` actually uses is a blocker. An escape that is only planted is a stated limit, written down in the test's docstring and in the PR body.

   The round-4 reader found escapes the docstring does not state. It planted and confirmed every one except the last, which it reasoned out from the code:
   - `study_write.locked.__wrapped__(study, 'x')`, a reference that is the base of an attribute;
   - `functools.partial(study_write.Write)`, a reference passed on without being called;
   - a captured read of `write` in a function that declares `nonlocal write`;
   - a comprehension that binds `write`, followed by a read;
   - `global write`, read from a module-level function;
   - a helper `g(write)` that returns a closure over `write`, called after the block;
   - `_read_sequence_value` passed as `type=` to a call other than argparse's `add_argument`.

   State the limits as classes, each with one example, so that the list does not grow by instance:
   - references that are the base of an attribute;
   - references passed on without a call;
   - Python's scope declarations (`nonlocal`, `global`) and comprehension bindings;
   - closures returned from a helper;
   - `type=` checked by keyword name only.

   Keep the stop rule's sentence beside them.

   What stays as it is: the limits already listed, and every check.
2. **replace**: the name of `test_every_with_study_write_locked_binds_write_and_every_function_it_is_passed_to_names_that_parameter_write_and_uses_it_in_the_closed_ways_only`. The new name must also say what D-054's three rules check: `locked(...)` only as the item of a `with`; the name not used outside its block; `Write` built only in its module. `.claude/agents/slice-builder.md` says "a test name says what the test checks".
3. **remove**: `test_the_module_of_the_architecture_checks_says_that_it_also_holds_the_receiver_rule_of_the_Study_write_contract`. It asserts a docstring phrase, and nothing asked for it. What stays as it is: the module docstring itself.

Your hand-back lists every test or assertion you removed or replaced, beside the line above that asks for it. Commit with a message saying what changed and why, ending with:

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014N3DRHr6Mxdp96QxHJy1m5

Then run the full suite on a clean tree with `uv run --locked --all-extras pytest`, and report its exact final line beside `git rev-parse --short HEAD`. Do not push. Leave no background process running.

If the repository does not settle a question, stop and hand back with the question. Do not decide in my place.
