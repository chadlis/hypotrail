Blocked by: none

## Parent

#120 (R1, milestone #103). Decided by [D-043](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7062406813) on chadlis/hypotrail#75, slice R1 (decision by proxy), widened by the [owner instruction on the fitness functions](https://github.com/chadlis/hypotrail/issues/1#issuecomment-7063639489) (#1, 2026-11-21, the slice's amendment). The orders it pins: [D-037](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7059507757) on chadlis/hypotrail#75, item 2, and [D-038](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7060924563) on chadlis/hypotrail#75, item 2. Evidence: #117 (candidate A1, question Q1, the coherence report's F1).

## What to build

Before any code moves, one test pins the order in which every command that writes to a Study refuses. ~~Each Study writer is called with the Study's writer lock held by another process and a `--read-sequence` below the Study's Write sequence: once with arguments that pass every check before the lock, and once for each of its checks that come before the lock.~~ (narrowed by Tightened B and C; Tightened A adds a part with the lock free) ~~One table holds the code each call gives today, and the Study's files are left as they were.~~ (replaced by Tightened C)

A second test walks every leaf command of the parser and classifies each one as a Study writer or a non-writer. "Every writer" is then a list a test checks, not one typed by hand. Together the two tests are F4 of the owner instruction.

~~The table `checks-before-the-lock` of handbook chapter 04 lists every writer's checks that come before the lock, and a test compares it with the probe's table.~~ (narrowed by Tightened B)

This ticket changes no file under `src/`: behaviour is unchanged. The next tickets of #120 refactor against this table. No model is called.

## Acceptance criteria

- [ ] ~~A probe calls every Study writer with the Study's writer lock held by another process and a `--read-sequence` below the Study's Write sequence: once with arguments that pass every check before the lock, and once for each check that comes before the lock, provoked. One table holds the exit code and error code each call gives today. A writer that refuses `--read-sequence` (`init` creating a Study) has the row it gives today. Every call leaves the Study's files as they were.~~ (replaced by Tightened C)
  ~~Source: #120 "A « lock held, stale value » probe runs on every writer against one table of expected codes, and is shown red first. It pins each writer's order as it is today (D-037 and D-038 on chadlis/hypotrail#75)." D-043 "**First, a witness written before the refactor.** A « lock held, stale value » probe runs on every writer against one table of expected codes, shown red first."~~ (amended by Tightened I, D-047)
  ~~Witness: the probe, passing at this ticket's commit; shown red once in the builder's hand-back on a planted change of one writer's order (for example `compare`'s `--factor` check moved under the lock), reverted before the commit.~~ (amended by Tightened I, D-047)
  ~~Proves: no T-xx.~~ (amended by Tightened I, D-047)
- [ ] The probe passes with the same table before and after the refactor: the table is written in this ticket, and no later ticket of #120 changes it.
  Source: #120, first acceptance criterion: "The order probe passes before and after the refactor with the same table."
  Witness: the probe at this ticket's commit and at the pull request's head; `git diff <this ticket's commit> HEAD` shows no change to the table.
  Proves: no T-xx.
- [ ] Every leaf command of `build_parser()` is classified, in one list, as a Study writer or a non-writer. A leaf command missing from the list fails the test, and so does a Study writer that the probe does not call. At `6c2827c` the leaf commands are `data verify`, `data fetch`, `init`, `run ml`, `run agent`, `import ml`, `import agent`, `assess`, `compare`, `status`, `decide`, `recover`, `report` and `spike live`.
  Source: #120 amendment "**Rule 2.** Every leaf command of `build_parser()` is classified as a Study writer or a non-writer. Together with the order probe already listed above, this is F4." Owner instruction, rule 2, method: "behavioural probe + parser walk".
  Witness: that test, passing at this ticket's commit; shown red once in the builder's hand-back on a planted leaf command left out of the list, and once on a Study writer left out of the probe.
  Proves: no T-xx.
- [ ] ~~The table `checks-before-the-lock` of chapter 04 lists every Study writer's checks that come before the lock, as the code gives them today. It keeps its two rows (`compare --factor`, `report --out`) and gains the others, among them the checks of `report`, `run agent` and `import agent` that #117 found in no table. Each row is one call of the probe, and a test compares the table's rows with the probe's calls of checks before the lock, both ways.~~ (replaced by Tightened B)
  ~~Source: #120 "**Q1.** The `checks-before-the-lock` table in handbook chapter 04 lists every writer's checks that come before the lock, and a test provokes each row." #120, fourth acceptance criterion: "The `checks-before-the-lock` table matches the probe." D-043 "**Q1:** the `checks-before-the-lock` table lists every writer's checks that come before the lock, and A1's fitness test pins it (ADR 0003)." #117, Q1: "The pre-lock checks of `report`, `run agent` and `import agent` appear in no table."~~ (amended by Tightened I, D-047)
  ~~Witness: the table test, shown red once in the builder's hand-back on a row removed from chapter 04, and once on a probe call with no row; `docs/handbook/chapters/04-study-and-attempts.html` (kept file).~~ (amended by Tightened I, D-047)
  ~~Proves: no T-xx.~~ (amended by Tightened I, D-047)
- [ ] The prose of chapter 04 around the table says only what no row says, and names no count of rows. Today's sentence "Two checks, `compare --factor` and `report --out`, keep their place before the lock" is rewritten so that it stays true when the table grows.
  ~~Source: drive skill, step 2: "the handbook chapter describes the change, its prose restating no table row". ADR 0003 "The product handbook follows current behaviour and is updated in the relevant pull request."~~ (amended by Tightened G, D-047)
  Witness: `docs/handbook/chapters/04-study-and-attempts.html` (kept file), read by the review of record; the table test of Tightened B.
  Proves: no T-xx.
- [ ] No file under `src/` changes in this ticket, and the full existing suite passes.
  Source: #120 "One refactoring slice, behaviour unchanged". #120 "**First witness, before anything moves.**" Drive skill, "Architecture review", step 5: "Its tickets state that behaviour is unchanged. The full existing suite is the witness."
  Witness: `git diff main -- src/` at this ticket's commit is empty; the full suite at that commit.
  Proves: no T-xx.

### INFERRED (no source settles these; the ticket gate chooses)

- [ ] ~~**INFERRED: what the probe pins of D-037 on chadlis/hypotrail#75.** With the lock held, no check after the lock is reached. The probe as worded therefore pins each writer's checks before the lock and the lock itself (D-038 on chadlis/hypotrail#75, item 2). It cannot reach D-037 on chadlis/hypotrail#75, item 2, which orders checks under the lock: "In both `run` commands, the stale check comes straight after the request-identity step, including its replay lookup. For `run agent`, `DATA_INTEGRITY` and the `ARTIFACT_*` codes therefore fall in step 6."~~
  ~~Options:~~
  - ~~**1A.** The probe's one table has a second part: with the lock free and the older value, each writer is called once for each check that comes under the lock before the stale check (the replay, `REQUEST_CONFLICT`, and the reads the request identity needs, such as `DATA_INTEGRITY` in `run ml`), and once for the first check after it. Cost: more calls, close to the "Tightened L" rows of `tests/test_stale_sequence.py` widened to every writer; the probe then pins every writer's order, which the "Wrong if" of D-043 on chadlis/hypotrail#75 asks of the first witness.~~
  - ~~**1B.** The probe stays lock-held only, as worded. The order under the lock stays pinned by the tests that pin it today (`tests/test_stale_sequence.py`: the replay and conflict rows, and the "Tightened L" rows), which pass unchanged. Cost: for `assess`, `compare`, `recover`, `report`, `init --new-revision` and `decide`, no test pins where the stale check sits relative to their other refusals under the lock.~~
  ~~Source: #120 "It pins each writer's order as it is today (D-037 and D-038 on chadlis/hypotrail#75)." D-043 "It pins the D-037 and D-038 orders before anything moves." D-043, "Wrong if": "**A1 now:** the suite does not pin every writer's order before the refactor, or the module becomes a pass-through with one hook per writer. R1's first witness is there to prevent this."~~
  ~~Witness: 1A, the probe's second part, shown red once on a planted stale check moved before one writer's replay lookup; 1B, the tests of `tests/test_stale_sequence.py` named above, passing unchanged.~~ (settled by Tightened A)
- [ ] ~~**INFERRED: which checks "the checks that come before the lock" are, and what witnesses that the table lists every one.** A test can provoke each row the table lists. No test can show that the code has no other check before the lock. The scope is open too: chapter 04's prose already gives a general order ("the arguments …; the Study; the lock"), and `run agent` alone checks the Track, the Workload and every flag before the lock (`agentic/run.py:217-221`).~~
  ~~Options:~~
  - ~~**2A.** Every refusal a writer can give before the lock is a row, argument refusals included (`INVALID_ARGUMENTS` of `--read-sequence`, `REQUEST_ID_EMPTY`, `STUDY_NOT_FOUND`, `decide`'s author and fields, each flag of `run agent`). Completeness is read by the review of record against each writer's code.~~
  - ~~**2B.** The rows are the checks before the lock beyond the general order the prose states: checks that read more than the command's own arguments (the spec, the Workload, the Study's records), such as `compare --factor`, `report --out`, `report`'s reading of every record, `run agent`'s Track and flags, and `import agent`'s check that Inspect is installed. Completeness is read by the review of record.~~
  - ~~**2C.** Either scope, and after #128 the Study-write module receives each writer's checks before the lock as named steps; a test compares those names with the table's rows, so completeness becomes mechanical. Cost: it ties the module's interface to the table.~~
  ~~Source: #120 "**Q1.** The `checks-before-the-lock` table in handbook chapter 04 lists every writer's checks that come before the lock, and a test provokes each row." #117, Q1: "Is the `checks-before-the-lock` table of handbook chapter 04 meant to list every check that comes before the lock?" Coherence report on #117, F1: "`report/command.py:72` reads and verifies every record before the lock, so a corrupt record answers `ARTIFACT_INTEGRITY` before `STUDY_LOCKED`." "`agentic/run.py:217-221` checks the Track and all its flags before the lock."~~
  ~~Witness: 2A and 2B, the table test of the fourth criterion and the review of record; 2C, that test plus the comparison with the module's named steps, shown red once on a planted step with no row.~~ (settled by Tightened B)
- [ ] ~~**INFERRED: the two tests that pin the table today.** `test_the_table_of_the_checks_before_the_lock_lists_the_checks_the_test_provokes` asserts that the table's commands equal its two `PROVOKED` entries, and `test_each_check_of_the_table_before_the_lock_gives_its_code_with_the_lock_held_and_an_older_value_and_writes_nothing` provokes those two (`tests/test_stale_sequence.py`). Once the table gains rows, the first fails unless it changes. #120 wants the existing suite "unchanged apart from tests that named moved private functions", and these two name none.~~
  ~~Options:~~
  - ~~**3A.** The probe replaces both tests: their two rows are rows of the probe's table, and the pull request names the two removed tests as a second exception to "unchanged", citing Q1.~~
  - ~~**3B.** Both tests stay, and their `PROVOKED` mapping is built from the probe's table instead of typed by hand; the pull request names that change as the exception.~~
  ~~Source: #120, third acceptance criterion: "The full existing suite passes, unchanged apart from tests that named moved private functions." #120 "**Q1.** … lists every writer's checks that come before the lock".~~
  ~~Witness: 3A, `tests/test_stale_sequence.py` at the pull request's head without the two tests, and the probe holding their two rows; 3B, the two tests passing at the head.~~ (settled by Tightened D)
- [ ] ~~**INFERRED: whether rule 2 uses the shared resolver.** The amendment says of `tests/_architecture.py`: "Every rule below uses it", and rule 2 is below it. Rule 2 is a parser walk with a behavioural probe; it resolves no import. The resolver is written in #130, after this ticket.~~
  ~~Options:~~
  - ~~**4A.** Rule 2 does not use the resolver: the resolver's two named jobs (relative imports, the `rglob` scan) have no part in a parser walk. The ticket gate records this reading of "Every rule below uses it".~~
  - ~~**4B.** #130 moves rule 2's list of modules or commands onto the resolver once it exists (for example, the modules that call into the Study-write module are found through it, and each must belong to a Study writer of the list).~~
  ~~Source: #120 amendment "**Shared resolver.** `tests/_architecture.py` resolves relative imports and scans with `rglob`. Every rule below uses it." Owner instruction, rule 2, method: "behavioural probe + parser walk".~~
  ~~Witness: 4A, none beyond the third criterion's test; 4B, the rule-2 test at the pull request's head importing `tests/_architecture.py`, shown red once on a planted call into the Study-write module from a module of no Study writer.~~ (settled by Tightened E)

## Tightened (2026-11-21, from D-046)

From [D-046](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7064224123) on chadlis/hypotrail#75 (decision by proxy, two readings), which settles this ticket's four `INFERRED` items and the ticket gate's point on `report`, and carries the drive's fix of the first criterion's source. D-046 numbers this ticket's items 2 to 5: its options 2A, 3B, 4B and 5A are this ticket's 1A, 2B, 3B and 4A.

- [ ] **A** (the order under the lock). The probe's table gains a part with the lock free. With a `--read-sequence` below the Study's, each Study writer is called once with each check that comes under the lock before the stale check provoked (the replay, `REQUEST_CONFLICT`, and the reads its request identity needs, such as `DATA_INTEGRITY` in `run ml`), and once with the first check after the stale check provoked. Each call's expected result is the one the writer gives today: the exit code and error code, or the recorded record for a replay. This part pins every writer's order under the lock.
  Source: D-046 item 2: "**2A.** The probe gains a part with the lock free, which pins the order under the lock for every writer." D-037 on chadlis/hypotrail#75, item 2: "In both `run` commands, the stale check comes straight after the request-identity step, including its replay lookup. For `run agent`, `DATA_INTEGRITY` and the `ARTIFACT_*` codes therefore fall in step 6."
  Witness: the probe's part with the lock free, passing at this ticket's commit; shown red once in the builder's hand-back on a planted stale check moved before one writer's replay lookup, reverted before the commit.
- [ ] **B** (which checks the table lists; replaces the fourth criterion). The table `checks-before-the-lock` of chapter 04 lists only the checks before the lock that read more than the command's own arguments: the spec, the Workload, the installed packages or the Study's records. It keeps its two rows (`compare --factor`, `report --out`) and gains every other such check of every Study writer as the code gives it today, among them `report`'s reading of every record, `run agent`'s checks of the Track, the Workload and its flags, and `import agent`'s check that Inspect is installed. The probe provokes each row, and a test compares the table's rows with the probe's calls of checks before the lock, both ways.
  Source: D-046 item 3: "**3B.** The table lists only checks that read more than the command's own arguments. The probe provokes each row." #120 "**Q1.** The `checks-before-the-lock` table in handbook chapter 04 lists every writer's checks that come before the lock, and a test provokes each row." #120, fourth acceptance criterion: "The `checks-before-the-lock` table matches the probe." #117, Q1: "The pre-lock checks of `report`, `run agent` and `import agent` appear in no table."
  Witness: the table test, shown red once in the builder's hand-back on a row removed from chapter 04, and once on a probe call with no row; `docs/handbook/chapters/04-study-and-attempts.html` (kept file), read by the review of record against each writer's code for a check of this kind with no row.
- [ ] **C** (the part with the lock held; replaces the first criterion). A probe calls every Study writer with the Study's writer lock held by another process and a `--read-sequence` below the Study's Write sequence: once with arguments that pass every check before the lock, and once with each check of the table `checks-before-the-lock` (Tightened B) provoked. One table holds the exit code and error code each call gives today. A writer that refuses `--read-sequence` (`init` creating a Study) has the row it gives today. `report`'s rows use a Study whose page records an Exposure. Every call writes nothing: the Study's files are left as they were.
  Source: D-046 item 3: "The probe provokes each row." D-046 item 6: "**6A.** `report` is a Study writer. Its probe row uses a Study whose page records an Exposure." #120 "A « lock held, stale value » probe runs on every writer against one table of expected codes, and is shown red first." ~~D-046, fixed by the drive: "#127 c1 now cites D-038's « Neither writes anything »."~~ (amended by Tightened H, D-047) D-038 on chadlis/hypotrail#75, item 2: "They write nothing (`core/comparison.py:221-228`, `report/command.py:69-70`)." D-037 on chadlis/hypotrail#75, item 2, where the words "Neither writes anything." stand.
  Witness: the probe, passing at this ticket's commit; shown red once in the builder's hand-back on a planted change of one writer's order (for example `compare`'s `--factor` check moved under the lock), reverted before the commit.
- [ ] **D** (the two tests that pin the table today). `PROVOKED` in `tests/test_stale_sequence.py` is built from the probe's table instead of typed by hand, and both tests that read it stay. The pull request names this change as an exception to "unchanged apart from tests that named moved private functions".
  Source: D-046 item 4: "**4B.** `PROVOKED` is built from the probe's table. The PR names this as an exception to « suite unchanged »."
  Witness: `test_the_table_of_the_checks_before_the_lock_lists_the_checks_the_test_provokes` and `test_each_check_of_the_table_before_the_lock_gives_its_code_with_the_lock_held_and_an_older_value_and_writes_nothing` passing at the pull request's head; the pull request body naming the exception.
- [ ] **E** (rule 2 and the resolver). Rule 2 does not use `tests/_architecture.py`. Its witness is its own test, the one of the third criterion.
  Source: D-046 item 5: "**5A.** Rule 2 is exempt from the shared resolver. Its witness is its own test."
  Witness: the rule-2 test of the third criterion, passing at the pull request's head, with its red on the planted leaf command.
- [ ] **F** (`report` in rule 2). Rule 2 classifies `report` as a Study writer, and its test compares the list's Study writers with the probe's writers both ways.
  Source: D-046 item 6: "**6A.** `report` is a Study writer."
  Witness: the rule-2 test, shown red once in the builder's hand-back with `report` moved to the non-writers.

## Tightened (2026-11-21, from D-047)

From [D-047](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7064433430) on chadlis/hypotrail#75 (decision by proxy, two readings), which settles what the second reading of the ticket gate left open, and carries two of its "Fixed with a quoted source" lines.

- [ ] **G** (the fifth criterion's source). The fifth criterion stays. Its source is ADR 0003 "The product handbook follows current behaviour and is updated in the relevant pull request.", together with Tightened B: B grows the table, so chapter 04's sentence "Two checks, `compare --factor` and `report --out`, keep their place before the lock" would become false.
  Source: D-047 item 3: "**#127 c5.** c5 stays. Its source becomes ADR 0003, « The product handbook follows current behaviour », together with #127 Tightened B. Tightened B grows the table, so chapter 04:187's sentence would become false."
  Witness: the fifth criterion's witness: `docs/handbook/chapters/04-study-and-attempts.html` (kept file), read by the review of record; the table test of Tightened B.
- [ ] **H** (Tightened C's citation). Tightened C's two quotes, D-038 item 2 "They write nothing" and D-037 item 2 "Neither writes anything.", are cited through D-046 addendum 1, which corrects D-046's attribution: "Those words are in D-037 item 2. D-038 item 2 says « They write nothing ». #127 Tightened C quotes each of them under its own decision."
  Source: D-047, fixed with a quoted source: "#127 Tightened C cites D-046 addendum 1." [D-046 addendum 1](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7064352511) on chadlis/hypotrail#75, quoted above.
  Witness: D-046 addendum 1 (kept comment on chadlis/hypotrail#75); the probe of Tightened C, whose calls write nothing.
- [ ] **I** (the struck criteria's lines). The Source, Witness and Proves lines of the first and fourth criteria are struck with their criteria. Tightened C and Tightened B carry the sources and witnesses that stay live.
  Source: D-047, fixed with a quoted source: "#127 c1 and c4: their Source, Witness and Proves lines are struck as whole items."
  Witness: this body (kept text): the six lines are struck, and Tightened B and C each have a Source and a Witness line.

## Tightened (2026-11-21, from D-051)

From [D-051](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7068975824) on chadlis/hypotrail#75 (decision by proxy), after the floor of review round 5.

- [ ] **J** (what "the table" is, in the first criterion).
  - "The table" is the expected codes: `LOCK_HELD`, `CHECKS_BEFORE_THE_LOCK`, `UNDER_THE_LOCK`, `REPLAYED` and `STALE`, held in `tests/_order_table.py`.
  - The inventory of locked paths (`LOCKED_PATHS`, `ENTERS`, `ENTERS_NONE`, `SKIPPED_CALLS`) lives in its own module. Later tickets of #120 may change it when the lock moves.
  - Source: D-051, "The table is the codes: `LOCK_HELD`, `CHECKS_BEFORE_THE_LOCK`, `UNDER_THE_LOCK`, `REPLAYED` and `STALE`." #120 "The order probe passes before and after the refactor with the same table."
  - Witness: `git diff <this ticket's commit> HEAD -- tests/_order_table.py` at the pull request's head of #120 is empty. The inventory module's docstring says later tickets may change it.


---
_Generated by [Claude Code](https://claude.ai/code)_