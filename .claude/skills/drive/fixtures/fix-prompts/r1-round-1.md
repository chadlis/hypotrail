Work in /home/user/hypotrail/.claude/worktrees/slice-80 (branch slice-120, head 422808d). Ticket: chadlis/hypotrail#127; read its body (`gh api repos/chadlis/hypotrail/issues/127 --jq .body`). Decision D-049 on chadlis/hypotrail#75 (comment 7067614117) settles two readings, quoted below. No file under `src/` changes.

Fix these, as a review fix (your hand-back lists every file touched beyond the cited paths, and why):

1. `tests/test_stale_sequence.py:559` and `:566`. The section header says "two checks that read only the arguments and the spec keep their place before the lock", and the docstring says `{command: code}`. Neither is true any more. Rewrite both so they say what the code does now.
2. Chapter 04, table `checks-before-the-lock`. The Check cells are probe labels set as code (for example `<code>init data</code>`), and a reader takes them for command syntax. Each Check cell describes its check in words that cannot be read as syntax. ADR 0003: "The product handbook follows current behaviour".
3. In `tests/_order_probe.py`, `flat()` and `of()` handle a `None` option value that no call passes. Remove that branch and its docstring sentences.
4. Tightened A, as a family. Tightened A says: "each Study writer is called once with each check that comes under the lock before the stale check provoked (the replay, `REQUEST_CONFLICT`, and the reads its request identity needs, such as `DATA_INTEGRITY` in `run ml`), and once with the first check after the stale check provoked."
   - For every Study writer, and on each Track path its code takes, read the code under the lock in order.
   - The lock-free part gets a row for every refusal that comes before `require_current`. Among those found in review: `EXAMPLES_DIR_NOT_FOUND` and `load_declaration`'s `FILE_NOT_FOUND`/`FILE_NOT_JSON` in `run ml` and `import ml`, `load_workload` in `import agent`, and a replay whose recorded artifacts fail verification in the three `run`/`import` writers.
   - It also gets one row for the first refusal after the stale check. `report` has none today: after `require_current` it calls `exposure.record`, which can refuse, for example with `WORKLOAD_BASIS_REQUIRED`.
   - Your hand-back lists, per writer and Track path, each refusal you found in code order (file:line), and the row that pins it, or why no row does.
5. Both Track paths of `init`. `init` on an agent Workload (`agentic/study.py`: `init_study`'s checks before the lock, such as `load_workload` and `require_declared`) and its `new_revision` are separate code that the probe never calls.
   - Their checks before the lock that read more than the arguments get rows in the table and in the lock-held part (Tightened B and C).
   - Their order under the lock gets lock-free rows (Tightened A).
6. D-041 item 2 on chadlis/hypotrail#75: "The order paragraph names the two checks by command, `compare --factor` and `report --out`, and points to the `checks-before-the-lock` table … The prose guard test exempts those two flags, citing Tightened M. A test checks that the paragraph names both."
   - The commit dropped this. Restore it: the paragraph names both commands, `PROSE_MAY_NAME` exempts the two flags again, and a test checks that the paragraph names both.
   - The fifth criterion still holds: the sentence stays true as the table grows and names no count of rows.
7. D-049 item 1: "The table `checks-before-the-lock`, and the probe's lock-held part, list only the checks before the lock that read more than the command's own arguments. `run agent`'s rows `PARTITION_REQUIRED`, `REPEATS_REQUIRED`, `MODEL_REQUIRED`, `PARTITION_NOT_ALLOWED`, `REPEATS_OUT_OF_BOUNDS`, `CASE_REPEATED` and the fixture-mode `UNSUPPORTED_CAPABILITY` leave both. The Workload reads stay: `CONFIGURATION_NOT_DECLARED`, `SCENARIOS_NOT_DECLARED`, the scenarios `FILE_NOT_FOUND`, `PARTITION_NOT_DECLARED` and `CASE_NOT_IN_PARTITION`."
8. D-049 item 2: "`init`'s check rows are called without `--read-sequence`. The first reading's optional row is adopted: one argument-clean `init` that creates a Study, called without the option and with the lock held, which pins `init`'s lock refusal."
   - Check in the code that creation takes the lock on each Track path.
   - On a path where it does not, give that path the row it gives today, and say so in the hand-back.
9. Tightened B: "a test compares the table's rows with the probe's calls of checks before the lock, both ways."
   - `test_order_probe.py:92`, `test_stale_sequence.py:569` and `test_handbook.py:4246` each parse the table with a regex that depends on the order of the attributes, so a row written in another order is skipped silently.
   - Replace the three with one parser of the table that all three files use. It reads the attributes by name and fails on any `<tr>` of the table that it cannot read.

Every new or changed witness has its red run, as `.claude/agents/slice-builder.md` requires. Run the full suite with `uv run --locked --all-extras pytest` and report its exact final line. Commit with a message that says what changed and why, ending with:

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014N3DRHr6Mxdp96QxHJy1m5

Do not push.

If the repository does not settle a question, stop and hand back with the question. Do not decide in my place.
