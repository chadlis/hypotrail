Work in /home/user/hypotrail/.claude/worktrees/slice-80 (branch slice-120, head 41941f6). Ticket chadlis/hypotrail#127 (`gh api repos/chadlis/hypotrail/issues/127 --jq .body`); D-050 on chadlis/hypotrail#75 (comment 7068356043). Nothing under `src/` changes. This is a review fix: the hand-back lists every file you touched beyond the cited paths, and why.

1. `tests/test_handbook.py:4194-4195`. D-041 item 2 also says: "The prose guard test exempts those two flags, citing Tightened M." Quote that sentence too in the two entries.
2. The chapter-04 order-paragraph test (`test_handbook.py`, around line 4243) checks several properties: it names both commands, it points to the table, it names none of the table's codes, it states no count, and it says "beyond this general order" and "read more than the arguments". `.claude/agents/slice-builder.md` says: "a test name says what the test checks", and that name has failed it in two rounds. Split the test: one test per property, each name saying what that test checks.
3. Tightened C says: "A probe calls every Study writer…". No test reads `LOCKED_PATHS[...]["track"]`, and rows are matched to paths by name only, so a row named for one Track whose call takes the other Track's path would pass. For each lock-held row and each `AFTER` row, show that its call enters the locked function of its path: wrap that function (for example `unittest.mock.patch(..., wraps=...)`) and assert it was entered. Then the `track` field is either read by a test or removed.
4. D-050: "the first refusal that the arguments, the examples directory, the Workload's files or the installed packages can give". In `agentic/study.py:84-87`, `protocol_content` → `memberships_bytes` → `workload.cases` → `load_cases` can refuse `FILE_NOT_JSON` (`agentic/cases.py:26,34`) before `ANSWER_SCHEMA_NOT_DECLARED`, and the cases files are not in the Workload's lock. Make the `import agent` `AFTER` row provoke that first refusal. For every `AFTER` row, the hand-back gives the first refusal inside the named call under D-050 (file:line), and says whether the row provokes it.
5. Some skips rest on the command line's routing, not on the locked path's code: the `layout.require_domain` skips, and `scorers.get` for `assess agent` (`cli.py:558-559`). Add a test that pins each routing a skip rests on, so that the skip's reason cannot become false without a failure.
6. The `LOCKED_PATHS` comment says "Every function of `src/hypotrail`", while `SOURCE` scans `src` (`tests/_locked_paths.py:7`). Make the two agree.

Every new or changed witness has its red run, as `.claude/agents/slice-builder.md` requires: for point 3, a row whose call takes the other Track's path; for point 5, a planted change of routing. Run the full suite with `uv run --locked --all-extras pytest` and report its exact final line. Commit with a message that says what changed and why, ending with:

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014N3DRHr6Mxdp96QxHJy1m5

Do not push.

If the repository does not settle a question, stop and hand back with the question. Do not decide in my place.
