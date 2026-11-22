Blocked by: #133

## Parent

#120 (R1, milestone #103), candidate A1 and the #114 items D-043 on chadlis/hypotrail#75 maps to R1. The third of three tickets that replace #128, split by [D-046](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7064224123) on chadlis/hypotrail#75, item 13: expand (#132), migrate (#133), contract (this ticket). Evidence: #117 (candidate A1; the coherence report's F1 and F8) and #114.

## What to build

Every writer now runs through the Study-write module. This ticket removes the old paths, so that the steps every writer shares exist once, and adds the tests that keep it that way. Each test is written first and shown red while an old path remains, or on a planted violation where none remains.

The walk from a manifest to its Observation set is written once. A test checks that every public entry of the module serves at least two Study writers, against the "pass-through with one hook per writer" that D-043 on chadlis/hypotrail#75 rules out. The handbook, the README and the docstrings say where the protocol lives.

Behaviour is unchanged: the probe of #127 passes with its table unchanged. No model is called.

## Acceptance criteria

- [ ] The old paths are gone: no writer outside the Study-write module runs a step the module owns, and the functions the module replaced are removed or are the module's own.
  Source: D-046, item 13: "**contract:** remove the old paths and add the AST tests and the docs." #120 "**A1.** One Study-write module owns the argument check, the lock, the journal, the replay, the decision namespace, the stale check and the `begin` and end entries."
  Witness: the AST tests of the next four criteria; rule 3 (F2) of #130 at the pull request's head.
  Proves: no T-xx.
- [ ] The guard line and the empty `request_id` refusal are written once. `require_valid_read_sequence` is called from the Study-write module only, and `REQUEST_ID_EMPTY` is raised from one place only. Their codes, stages, `details` and order are unchanged.
  Source: #114, R2-S-06: "the guard line repeated in 12 writers, each with a command string typed by hand." #117, A1: "`REQUEST_ID_EMPTY` is raised in 5 places". D-046, fixed by the drive: "#128 counts 12 writer functions." Sealed drive choice of D-046 on chadlis/hypotrail#75: "It counts 12 writer functions; `WRITERS` holds 11 commands."
  Witness: a test over the AST of `src/`, written first and shown red once (on an old call left by #133, or on a planted call), green at the end; `TWO_FAULTS`, `DECIDE_SINGLE_FAULTS` and `test_an_empty_request_id_with_no_study_is_refused_as_request_id_empty` (`tests/test_stale_sequence.py`) passing unchanged.
  Proves: no T-xx.
- [ ] The guard on the shared `request_id` namespace, in both directions, is defined in the Study-write module and called from nowhere else.
  Source: #114, R1-S-09: "`core/decisions.py` holds three unrelated things: the `decide` command, the computation of whether a decision still applies (`history`, `_reasons`), and the guard on the shared `request_id` namespace for `run` and `import`." D-046 item 7: "**7A.** Both directions of the `request_id` namespace guard move into the module."
  Witness: a test over the AST of `src/`, written first and shown red once (on `refuse_if_a_decision_holds` while it is still in `core/decisions.py`, or on a planted call), green at the end; `tests/test_decide.py` passing unchanged.
  Proves: no T-xx.
- [ ] No call into the Study-write module passes a command name or a journal kind as a string literal: every such argument is a name of the module's constants.
  Source: #120 "R1-S-08: the write module owns the command and journal-kind constants." #114, R1-S-08: "the journal's `kind` values (`"assessment"`, `"comparison"`, `"freeze"`, …) and the command names (`"assess"`, `"init --new-revision"`) are bare strings." #114, R5-S-04: "`decisions.decide` passes the literal `"decide"` to `require_valid_read_sequence`, next to the constant `COMMAND`."
  Witness: a test over the AST of `src/`, written first and shown red once on a planted literal, green at the end; `tests/test_write_sequence.py` passing unchanged.
  Proves: no T-xx.
- [ ] The builder of an `INVALID_ARGUMENTS` refusal is not in the module that keeps the write journal.
  Source: #120 "R5-S-03 and R5-S-04." #114, R5-S-03: "`invalid_arguments` lives in `write_journal.py`, while `decisions.py` calls it for refusals that have nothing to do with the journal."
  Witness: a test over the AST of `src/`, written first and shown red on `write_journal.invalid_arguments` while it exists, green once it is removed; `DECIDE_SINGLE_FAULTS` and `TWO_FAULTS` of `tests/test_stale_sequence.py` passing unchanged.
  Proves: no T-xx.
- [ ] The walk from a manifest's `output_refs` to its Observation set is written once, in the core. ~~The four places that walk it today (`core/study.py:185`, `core/write_journal.py:141`, `core/decisions.py:73`, `report/gather.py:48` at `6c2827c`) call it, and each keeps its own reading of the record and its own handling of a record that cannot be read.~~ (amended by Tightened C, D-047)
  Source: #120 "R1-S-06: the walk to a manifest's Observation set is written once." #114, R1-S-06 (part): "Finding an Attempt's Observation set from `output_refs` is written twice: in `_Session._written` and in `decisions.held_ids`." Coherence report on #117, F8: "The "find the `observation_set` ref in a manifest" walk appears 4 times: `study.py:185`, `write_journal.py:141`, `decisions.py:73`, `gather.py:48`." D-043, readings: "the Observation-set walk goes in R1".
  Witness: a test over the AST of `src/`, written first and shown red (four functions), that one function compares an output ref's role with the Observation set's role; `tests/test_write_sequence.py`, `tests/test_decision_history.py`, `tests/test_report.py` and `tests/test_report_agent.py` passing unchanged.
  Proves: no T-xx.
- [ ] Behaviour is unchanged: the probe of #127 passes with its table unchanged, and the full existing suite passes, unchanged apart from tests that named moved private functions, each listed in the builder's hand-back with the function it named.
  Source: #120 "One refactoring slice, behaviour unchanged". #120, first and third acceptance criteria: "The order probe passes before and after the refactor with the same table." "The full existing suite passes, unchanged apart from tests that named moved private functions."
  Witness: the probe of #127 and the full suite at this ticket's commit; `git diff` of the probe's table since #127 is empty.
  Proves: no T-xx.
- [ ] What the handbook, the README and the docstrings say about where the write protocol lives stays true. Chapter 04 names the file that holds the writer lock and the one that holds the write journal (today `core/lock.py` and `core/write_journal.py`). The docstrings of the modules #132, #133 and this ticket change say what the code does after the move; `core/decisions.py` no longer claims that its order "is that of every writer". If the Study-write module is a new package, the README's layout line names it.
  Source: D-046, item 13: "**contract:** remove the old paths and add the AST tests and the docs." ADR 0003 "The product handbook follows current behaviour and is updated in the relevant pull request." AGENTS.md "Keep `README.md` short and true: update it in the same pull request when a change affects what it says (purpose, status, install, usage, layout or where to look)." Coherence report on #117, F1: "`core/decisions.py:15` claims "The order of the checks is that of every writer"."
  Witness: `docs/handbook/chapters/04-study-and-attempts.html`, `README.md` and the changed modules (kept files), read by the review of record; `tests/test_handbook.py` passing.
  Proves: no T-xx.

## Tightened (2026-11-21, from D-046)

From [D-046](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7064224123) on chadlis/hypotrail#75 (decision by proxy, two readings).

- [ ] **A** (no pass-through). A test over the AST of `src/` checks that every public entry of the Study-write module is called from at least two Study writers. Each exception is named in the test with its reason.
  Source: D-046 item 8: "**8C, with 8A's review on top.** An AST test checks that every public entry of the module is called from at least two Study writers. Each exception is named with its reason."
  Witness: that test, passing at the pull request's head; shown red once in the builder's hand-back on a planted public entry called from one writer only.
- [ ] **B** (the review of the interface). The review of record reads the Study-write module's interface for per-writer hooks among the callbacks writers pass in (their replay lookup, their own checks, their writes), which a count of callers cannot see. The builder's hand-back lists the module's public entries and the callbacks each takes.
  Source: D-046 item 8: "The review of record also reads the interface, which covers the callbacks a caller count cannot see (reading 2's own caveat)." D-046, "Wrong if (point 8)": "the named exceptions grow past one or two, or the hooks are the callbacks passed in. The review of the interface is there for that case."
  Witness: the Study-write module (kept file) and the hand-back's list, read by the review of record.

## Tightened (2026-11-21, from D-047)

From [D-047](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7064433430) on chadlis/hypotrail#75 (decision by proxy, two readings), which settles what the second reading of the ticket gate left open.

- [ ] **C** (the sixth criterion's callers). The four places that walk it today (`core/study.py:185`, `core/write_journal.py:141`, `core/decisions.py:73`, `report/gather.py:48` at `6c2827c`) call the one walk. It is in the core because three of the four walks are in `core/`, and the core imports no other package. That each caller keeps its own reading of the record is not a separate claim: "behaviour unchanged" covers it.
  Source: D-047 item 4: "**#134 c6.** The walk is written once, in the core: three of the four walks are in `core/`, and core imports no other package. « Each keeps its own reading … handling » is dropped, because « behaviour unchanged » covers it."
  Witness: the sixth criterion's AST test (one function compares an output ref's role with the Observation set's role), shown red on the four walks; the seventh criterion's probe and suite; rule 1 of #130 (the core imports no other package).
- [ ] **D** (the replay lookups). A test over the AST of `src/` checks that no writer calls `layout.find_by_request` (`core/study.py`) or `decisions.find_by_request` (`core/decisions.py`) outside the Study-write module. The test resolves each called function, through imports, aliases and bare names, rather than matching its spelling, so a bare-name call inside `core/decisions.py` counts too. It is also a witness of the first criterion for the replay.
  Source: D-047 item 5: "**Replay-lookup witness.** An AST test in #134 checks that no writer calls `layout.find_by_request` or `decisions.find_by_request` outside the module. The test resolves each function rather than matching its spelling, so it also catches bare-name calls inside `decisions.py`." D-047, "Wrong if (point 5)": "#120 meant `decide`'s replay to stay in `decide`, or the test matches text instead of resolved functions."
  Witness: that test, passing at the pull request's head; shown red once in the builder's hand-back while an old lookup remains (or on a planted call), once on a planted call through an alias, and once on a planted bare-name call of `find_by_request` inside `core/decisions.py`.


---
_Generated by [Claude Code](https://claude.ai/code)_