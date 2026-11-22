Work in /home/user/hypotrail/.claude/worktrees/slice-80 (branch slice-120, head a388817). Ticket chadlis/hypotrail#127 (`gh api repos/chadlis/hypotrail/issues/127 --jq .body`). Nothing under `src/` changes. This is a review fix: the hand-back lists every file you touched beyond the cited paths, and why.

1. Tightened C: "A probe calls every Study writer with the Study's writer lock held … once with each check of the table `checks-before-the-lock` (Tightened B) provoked."
   - The spy check of `tests/test_order_probe.py:129-142` covers only the `LOCK_HELD` rows and the `AFTER` rows. Extend it to every row of `CHECKS_BEFORE_THE_LOCK` and to every row of `UNDER_THE_LOCK`, including the `BEFORE`, `THE_CHECK` and replay rows. For example, `init data` and `init agent data` give the same code, so nothing shows which path each one takes.
   - Each row names its locked path. The test asserts that the call enters that path's locked function and no other one.
   - Some checks happen before the path's function is called at all, in `cli.py`. For each such row, record that in the table with a one-line reason. The test then asserts that no locked function is entered.
2. Structural fix for the citation in `tests/test_handbook.py:4194-4195`, the `PROSE_MAY_NAME` entries for `--factor` and `--out`. This requirement has failed in three rounds.
   - Define one constant that holds two separate quoted sentences: chadlis/hypotrail#108 Tightened M, "Chapter 04's order paragraph names these two exceptions.", and D-041 item 2 on chadlis/hypotrail#75, "The prose guard test exempts those two flags, citing Tightened M."
   - Both entries use the constant. Each sentence is quoted on its own and attributed to its own source: no joining of bullets, no paraphrase.
   - `.claude/agents/slice-builder.md` says: "A comment cites a requirement only by quoting the source sentence the prompt gives".
3. `docs/agents/domain.md`: "When your output names a domain concept (… a test name), use the term as defined in `GLOSSARY.md`". In `test_init_new_revision_enters_the_new_revision_of_the_domain_of_the_study_and_not_the_other`, "domain" names what GLOSSARY.md calls a **Track**. Rename the test.
4. `slice-builder.md`: "A comment says what the code alone does not show". The `SKIPPED_CALLS` reasons that rest on the command line's routing (`tests/_order_table.py`, around lines 180, 184 and 193) and the routing tests that pin them do not name each other. Make each point to the other.

Each new or changed witness has its red run, as `slice-builder.md` requires: for point 1, a check row whose call enters the other Track's path; for point 2, a constant that misquotes either source. Run the full suite with `uv run --locked --all-extras pytest` and report its exact final line. Commit with a message that says what changed and why, ending with:

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014N3DRHr6Mxdp96QxHJy1m5

Do not push.

If the repository does not settle a question, stop and hand back with the question. Do not decide in my place.
