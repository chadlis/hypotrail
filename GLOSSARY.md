# Hypotrail

Hypotrail runs small, explicit studies of predictive and agentic systems: it produces or adopts their outputs, keeps them, scores them against frozen references, and compares two configurations under one protocol.

## Language

### Study structure

**Study**:
The folder-scoped record of one investigation of one Workload under one frozen Protocol; it holds native and imported Attempts alike.
Clarification, 2026-11-20: one frozen Protocol per revision; a Study holds successive revisions, and a Protocol change is a new revision inside the same Study (owner decision 2A on chadlis/hypotrail#9).
_Avoid_: project, run folder, experiment

**Track**:
A family of studies the software supports end to end, such as temporal regression or tool-using agent; a request outside every supported Track is refused, never routed elsewhere.
_Avoid_: case (for this meaning), task type, family, pipeline

**Workload**:
One Track applied to concrete data, with its population, Partitions, References and declared settings (for example daily bike rentals, or the Chinook analyst questions); a demonstration Workload is still a Workload.
_Avoid_: benchmark, dataset (for the whole), use case, example (as a domain term)

**Protocol**:
What a Study evaluates and how it scores it: the population, Partitions, References, Scorers and the rules on when information is available; it binds every Attempt, while how an imported Attempt's outputs were produced stays `declared` or `unknown`.
Clarification, 2026-11-20: an Assessment applies the Protocol of its revision, also to outputs recorded under an earlier revision (owner decision 2A on chadlis/hypotrail#9).
_Avoid_: pipeline, method, setup

**Exposure**:
Any Assessment, Comparison or report that touches Items of the `public_check` Partition; every Configuration created after the first Exposure is marked `check_informed`.
_Avoid_: use, peek, leak

**Partition**:
A named, disjoint subset of a Track's population with a fixed role in the protocol, such as `train`, `dev` or `public_check`.
_Avoid_: split, fold

**Item**:
The unit that is produced, scored and counted one at a time, identified by a stable ID that never depends on file order.
_Avoid_: row, sample, example

**Case**:
One question of an agentic Track, with its requested columns and unit; it carries no expected answer.
_Avoid_: task, prompt, question item

**Episode**:
The Item of an agentic Track: one Case answered once, identified by Case and Repeat.
_Avoid_: sample, trial, run

**Repeat**:
The index distinguishing fresh, independent executions of the same Case under the same Configuration.
_Avoid_: epoch, retry, copy

### Producing outputs

**Configuration**:
The complete, named description of what is executed for a Track (for example `seasonal_7`, `ridge_v1`, `plain` or `verify`), excluding the role it later plays in a Comparison.
_Avoid_: variant, model (when the whole setup is meant)

**Mode**:
How an Attempt's outputs came to exist: `native_ml`, `scripted_fixture`, `llm_live` or `external_unknown`.
_Avoid_: profile, backend

**Scenario**:
A technical script of the `scripted_fixture` Mode, kept as Workload data, that drives a mock model through the real tools to exercise one outcome (good result, wrong result, invalid format, recovered tool error, budget exhausted, missing Reference); its Episodes are never outputs of a Workload's Cases.
_Avoid_: test case, fixture case

**Attempt**:
One execution or one import of exactly one Configuration on one population, with an identity that is never derived from its inputs.
Clarification, 2026-11-20: an Attempt is always recorded in a Study, with its manifest and Observation set. A `spike live` execution and the library fixture's execution (`fixture.run_fixture`) record nothing in a Study, so they are not Attempts; the command that records the live path as an Attempt is `run agent --mode llm_live`. The `mode` and `this_attempt` values those executions write in their records are format values, not claims that they are Attempts (owner decision by proxy D-011 on chadlis/hypotrail#75, ticket #77).
_Avoid_: run, job, execution record

**Import**:
An Attempt that adopts outputs produced outside Hypotrail, keeping the original files and marking everything it cannot establish as unknown.
_Avoid_: migration, resume, recovery

**Campaign**:
A named group of Attempts planned together, such as both Configurations over the same Cases and Repeats; it is a label, not a container of its own.
_Avoid_: batch, eval set

**Observation set**:
The outputs of one Attempt, one per Item, each marked `produced`, `failed` (execution stopped without an output) or `missing` (absent from imported outputs); this execution status is separate from how the Item is scored.
Clarification, 2026-11-06: a final answer cut by the output cap is not an output, so its Episode is `failed` with the Reason `output_cap`, and the cut raw text stays in the trace (owner decision D1 on chadlis/hypotrail#8).
_Avoid_: results, predictions (as a generic term), log

### Scoring and comparing

**Reference**:
The frozen expected outcome for an Item, versioned as a whole set and never shown to the system being evaluated.
_Avoid_: ground truth, gold, label, oracle

**Scorer**:
A versioned, registered scoring rule that turns an Observation set and a Reference set into Criteria per Item.
_Avoid_: grader, judge, evaluator

**Criterion**:
One property a Scorer checks for each Item (for example `exact_table`, `format_valid`, `evidence_link_valid`, or the absolute error of a day), in state `scored`, `unscored` or `errored`.
_Avoid_: check, test, sub-score

**Score**:
The value a scored Criterion gives one Item: a boolean (correct or incorrect) or a number such as an absolute error; a numeric loss is never counted as correct or incorrect.
_Avoid_: grade, mark, verdict (for numeric values)

**Reason**:
The machine-readable code attached to every abnormal outcome, such as `invalid_response_format`, `reference_missing`, `reference_invalid` or `scoring_failed`.
_Avoid_: error message, explanation (for the code)

**Wrapped answer**:
A final answer that is not exactly one JSON object but contains exactly one: with prose before or after it, a Markdown fence around it, an array holding it, or braces around it that are not JSON. It fails `format_valid` and `contract_success`; `exact_table` and `evidence_link_valid` are scored on its one object.
_Avoid_: embedded answer, extracted answer

**Instrument failure**:
A Criterion left `unscored` (the Scorer ran but had no usable reading) or `errored` (the scoring machinery broke); it is never held against the evaluated system.
_Avoid_: grader error, harness error

**Metric**:
A number aggregated over Items from one Criterion, such as MAE or the share of Items with a correct Score.
_Avoid_: score (for the aggregate), KPI

**Assessment**:
One application of one Scorer version to one Observation set and one Reference set; rescoring always creates a new Assessment.
_Avoid_: evaluation, result, score

**Comparison**:
Two Assessments of the same population, Scorer, units and Mode, aligned Item by Item, with a Control and a Candidate.
Clarification, 2026-11-20: for an agent, the Items are Episodes aligned by Case and Repeat, and the planned Repeats, tools, model and budgets are shared except for one declared intentional factor (chadlis/hypotrail#72).
_Avoid_: benchmark, diff

**Control**:
The Assessment a Comparison measures against.
_Avoid_: baseline (as a role), reference (as a role)

**Candidate**:
The Assessment a Comparison measures; a positive loss delta means the Candidate is worse.
_Avoid_: variant (as a role), challenger, treatment

## Relationships

- A **Workload** instantiates one **Track**; a **Study** investigates one **Workload** and holds many **Attempts**.
- An **Attempt** runs one **Configuration** in one **Mode** and yields exactly one **Observation set**.
- An **Assessment** applies one **Scorer** to one **Observation set** and one **Reference** set; one Observation set can have many Assessments.
- A **Comparison** pairs two **Assessments** as **Control** and **Candidate**.

## Correspondence with Inspect

Inspect executes agentic Episodes; its words map onto Hypotrail's as follows. **Sample** ↔ Case, **epoch** ↔ Repeat, **sample × epoch** ↔ Episode, **eval log** ↔ the raw artifact behind an Observation set, **Inspect scorer** ↔ a display of a Hypotrail Scorer, never the authoritative verdict, **`Score.unscored()`** ↔ `unscored`. Inspect's `ERRORED` sample covers two of our cases at once: an execution that stopped (Item `failed`) and a scoring machinery failure (Criterion `errored`).
