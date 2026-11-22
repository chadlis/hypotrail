## Architecture review after L2.1, `main` at `2b00922`

This is the first architecture review under the drive skill (« Architecture review », PRs #112 and #113; owner instruction on chadlis/hypotrail#1). Two fresh `slice-gate` readers ran in parallel and did not see each other's report.

- **Depth.** The reader followed `improve-codebase-architecture` up to its report. Its HTML report is published as an artifact for the owner.
- **Coherence.** The reader applied `code-review`'s Standards brief and smell baseline to the whole tree.

Both reports follow below as their own comments, word for word. The drive checked each premise listed here by command.

## Candidates: refactorings that leave behaviour unchanged

| ID | candidate | raised by | evidence (checked) | cost | fitness test |
|---|---|---|---|---|---|
| A1 | One Study-write module: argument check, lock, journal, replay, decision namespace, stale check, `begin`/end. Each writer supplies its replay lookup and its writes. The D-037 and D-038 orders are kept exactly. | depth (c1, top), coherence (F1) | the replay, decision-namespace and stale block is written four times (`ml/run.py:147-157`, `ml/imports.py:346-354`, `agentic/run.py:263-271`, `agentic/imports.py:492-500`); `REQUEST_ID_EMPTY` is raised in 5 places | medium | yes: `writer_lock`, `require_current` and `begin` are called only from that module |
| A2 | Attempt recording in the core (replay, `PROTOCOL_CHANGED`, running then terminal or failed manifest) | depth (c2), coherence (F1, F8) | `ml/imports.py:44` imports `_record_failure` and `_verify_recorded` from `ml/run` | medium-high; builds on A1 | yes: no Track module imports `core.requests` or holds `"PROTOCOL_CHANGED"` |
| A3 | One Exposure gate in `core/exposure` | depth (c3), coherence (F6) | the dev/public_check rule is coded in `ml/partitions.py`, `core/comparison.py:235`, `report/gather.py:161` and `agentic/partitions.py` | low-medium. **Conflicts with ADR 0002's amendment** (Partition roles defined once in the Track) | yes |
| A4 | An explicit Track seam: one adapter per Track, chosen once, with the registry outside `core/` | depth (c4), coherence (F2) | `AGENTIC = "agentic"` is defined 3 times; the domain string is switched on in `cli.py`, `core/comparison.py`, `core/scorers.py` and `report/`. Adding a Track touches about 10 files, which matters for L3's five Tracks | high | yes: Track literals appear only in the registry |
| A5 | One reader of Inspect logs | depth (c5) | 5 modules import `inspect_ai.log`; `live.usage_of` carries `cost` and `inspect_log.usage_by_key` does not | medium. **Changes a record format** (B4) | yes: one module imports `inspect_ai.log` |
| A6 | One regression Scorer function | depth (c6), coherence (F7) | MAE is computed in `core/scorers.py`, `ml/metrics.py` and `core/regression.py`; the last two are used only by tests | low, after Q3 | after Q3 |
| A7 | One StudySpec writer for both Tracks | coherence (F3) | `live_basis`, `protocol_id` and the StudySpec dict are the same in `ml/study.py` and `agentic/study.py` | medium | partly: both Tracks produce the same key set |
| A8 | Partition roles defined once per Track, and no import between `hypotrail.ml` and `hypotrail.agentic`. **Hard violation of ADR 0002's amendment** | coherence (H1) | `agentic/run.py:62` `PARTITIONS = ("dev", "public_check")`; `agentic/assess.py:48` imports `hypotrail.ml.partitions` | small | yes: neither Track imports the other, and role literals appear only in the partitions modules |
| A9 | Small repeats | coherence (F8), depth | `_now` written 6 times; the schema-to-refusal mapper written twice; atomic publication written 3 times; `--examples-dir` help written 8 times; `run agent` uses `import agent` helpers | small | partly |

## Behaviour defects: product decisions, not refactorings

| ID | defect | evidence (checked) |
|---|---|---|
| B1 | `import ml` parses inputs with `json.loads`, so it accepts duplicate keys, which `canonical.loads` refuses (`NON_CANONICAL_VALUE`). It can record a population that `assess` later refuses | `ml/imports.py:116, :176`; `agentic/imports.py:135` uses `canonical.loads`. The reader ran the case |
| B2 | « The later Assessment » has two orders: `core/decisions.py` uses write-journal position first, while `core/rescoring.py` and `report/gather.py` use `recorded_at`. They can name different Assessments | `decisions.py` `_reasons.order`; `rescoring.py:56` |
| B3 | `report/command.py` writes its page atomically but does not fsync the directory, unlike `core/artifacts.py` | `report/command.py:47-60` |
| B4 | A native and an imported Observation set record `usage` in two shapes: one with `cost`, one without | `agentic/live.py:264`, `agentic/inspect_log.py` |

## Questions the readers left open

- **Q1.** Is the `checks-before-the-lock` table of handbook chapter 04 meant to list every check that comes before the lock? The pre-lock checks of `report`, `run agent` and `import agent` appear in no table.
- **Q2.** Where do the core's copies of the role names (`core/comparison.py:44-45`, `report/gather.py:14`) belong, given that the core imports no Track?
- **Q3.** Are the Study-less library paths (`ml/comparison.py`, `ml/metrics.compute_metrics`, `core/regression.py`, `agentic/rescore.py`), used only by tests, product surface to keep?

## Open issues the same decision settles (D-042 item 1)

- #106: one check for bare decision IDs (options A and B).
- #114: the structure findings from the L2.1 review: R1-S-06 to R1-S-10, R2-S-06, R5-S-01 to R5-S-04.
- #115: the scope of the « » scan.

## Acceptance criteria

- [ ] One decision-log entry on #75 decides each candidate, defect, question and issue above as now, later or never, with a sealed drive choice posted first.
- [ ] The candidates picked for now form one refactoring slice under the current milestone, with behaviour unchanged.


---
_Generated by [Claude Code](https://claude.ai/code)_