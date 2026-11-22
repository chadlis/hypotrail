Work in /home/user/hypotrail/.claude/worktrees/slice-80 (branch slice-120, head 2735967). Ticket: chadlis/hypotrail#127, body via `gh api repos/chadlis/hypotrail/issues/127 --jq .body`. Nothing under `src/` changes. This is a review fix: the hand-back lists every file you touched beyond the cited paths, and why.

1. In `tests/test_handbook.py:4194-4195`, the `PROSE_MAY_NAME` entries cite "#108 Tightened M … (kept by D-041 on chadlis/hypotrail#75)" without quoting either. `.claude/agents/slice-builder.md` says: "A comment cites a requirement only by quoting the source sentence the prompt gives." The source sentence is D-041 item 2 on chadlis/hypotrail#75: "The order paragraph names the two checks by command, `compare --factor` and `report --out`, and points to the `checks-before-the-lock` table." Quote it, or cite nothing.
2. Rename `test_handbook.py:4243` so that the name says everything the test checks: the paragraph names both commands, points to the table, names no code the table gives, and states no count.
3. Chapter 04, lines 227-230, say "the scripted fixture Mode" and "the live Mode". `GLOSSARY.md` gives the Mode values as `scripted_fixture` and `llm_live`; use those. `docs/agents/domain.md` says: "use the term as defined in `GLOSSARY.md`".
4. Tightened C says: "A probe calls every Study writer with the Study's writer lock held … once with arguments that pass every check before the lock". `assess` has a lock-held row only on the bike path (`ml/assess.py`), while `agentic/assess.py:148` takes the lock on a separate path. Add the agent path's row, and the rows Tightened B and C give it for checks before the lock that read more than the arguments.
5. Tightened A says: "once with the first check after the stale check provoked".
   - In `ml/study.py:228-232` and `agentic/study.py:241-245`, the first refusal that can be reached after `require_current` is `resolve_examples_dir` (`EXAMPLES_DIR_NOT_FOUND`). The rows `init --new-revision data` and `init --new-revision agent data` provoke `DATA_INTEGRITY` instead, which comes later.
   - `report Protocol` passes through `live_basis(spec)` (`core/exposure.py:166`) before `PROTOCOL_CHANGED`.
   - Check every `AFTER` row against its path's code, and make each one provoke the first refusal that can be reached.
6. Structural option, alongside points 4 and 5. Tightened A and C have produced row-1 findings in two rounds, and all of them fall into two classes: a Track path that is never called, and a wrong "first check after". Make both classes mechanical failures. Use the stdlib `ast` only, add no dependency, and import no module that is not already in the tests.
   - **Inventory of locked paths.** Keep one inventory in the tests of every function under `src/hypotrail` that takes the writer lock (`lock.writer_lock`), each with its writer, its Track and whether it takes `--read-sequence`. An AST test checks that this inventory equals the set of such functions in `src/`, both ways.
   - **Rows per path.** Every path in the inventory has its lock-held row, and every path that takes `--read-sequence` has its `AFTER` row. A test checks this.
   - **The call each `AFTER` row provokes.** Each `AFTER` row names the call it provokes. An AST test checks that this call is the first call after `require_current` in that path's code, skipping only the calls the row names as unable to refuse, each with a one-line reason. Where `require_current` sits in a function that the locked function calls, follow that one call.
   - The hand-back lists the inventory, and for each `AFTER` row the calls it skips and why.
7. Chapter 04's paragraph that introduces `checks-before-the-lock` says the table lists the checks before the lock that come beyond the general order the paragraph states (arguments, the Study, the lock), and that read more than the arguments. Struck option 2B of #127, which D-046's 3B adopts, says: "The rows are the checks before the lock beyond the general order the prose states". Add no count and restate no row.

Each new or changed witness has its red run, as `.claude/agents/slice-builder.md` requires. That includes the inventory test, red on a planted missing path and on a planted extra entry, and the `AFTER` test, red on a row that names a later call. Run the full suite with `uv run --locked --all-extras pytest` and report its exact final line. Commit with a message saying what changed and why, ending with:

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014N3DRHr6Mxdp96QxHJy1m5

Do not push.

If the repository does not settle a question, stop and hand back with the question. Do not decide in my place.
