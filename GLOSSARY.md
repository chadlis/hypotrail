# Hypotrail

Hypotrail runs small, explicit studies of predictive and agentic systems: it produces or adopts their outputs, keeps them, scores them against frozen references, and compares two configurations under one protocol.

## Language

### Study structure

**Study**:
The folder-scoped record of one investigation of one Workload under one frozen Protocol; it holds native and imported Attempts alike.
Clarification, 2026-11-20: one frozen Protocol per revision; a Study holds successive revisions, and a Protocol change is a new revision inside the same Study (owner decision 2A on chadlis/hypotrail#9).
_Avoid_: project, run folder, experiment

**Study writer**:
A command that may write to a Study, creating it included, such as `run`, `assess` or `decide`; every other command, such as `status`, is a non-writer. A command is one by what it may do, not by what one call did: a call refused or replayed before its first write is still a call of a Study writer, and it leaves the Write sequence unchanged.
_Avoid_: mutating command, write command

**Write sequence**:
The value a Study keeps and every write to the Study advances: the number of entries of its write journal, two for each command that writes, or one when the writer was killed between its first write and its last. Nothing else changes it, and `status --json` shows it as `write_sequence`.
_Avoid_: revision

**Decision**:
One choice recorded in a Study: the question it answers, the option chosen, its author (`human` or `proxy`, with a declared source if any), the ids of the Study's records it cites, its `request_id` and the write sequence its author read. It is a record of the Study, kept in a file of its own and never rewritten; the Study is the only decision authority, and recording one is a write, so it advances the write sequence.
Clarification, 2026-11-26: a Decision may also hold the ids the core supplies for its question and its option (`question_id`, `option_id`) and the person's `words`: their own sentences, verbatim, with the channel they came through (`panel`, `choice` or `chat_relayed`) and a declared `by`; `authenticated` is false, and the agent's own wording is never `words`, it is the `source` (D-148 and D-149 on chadlis/hypotrail#75; built by chadlis/hypotrail#244).
Clarification, 2026-11-26: the `words` may also come through `file_relayed`: the caller read them from a file a person wrote and relays them. The `source` of such a Decision names the outside act the file comes from, a pull request citation or the job's run and its account, never the file's path or digest, and `decide` refuses it without one. `authenticated` stays false: a cited pull request raises only the level that `status` derives when it reads the Study (ADR 0006; D-168 and D-172 on chadlis/hypotrail#75; built by chadlis/hypotrail#276).
_Avoid_: note, verdict, conclusion

**Declared deviation**:
One known limit on what results of a Study show, declared in the Study because its records cannot establish it (for example an owner review of References still pending): what is declared, its author and the ids of the Study's records it cites. It is a record of the Study, never rewritten; a later record can withdraw it, and a derived deviation is a deviation but not a Declared deviation.
_Avoid_: caveat, waiver, limitation, warning

**Validation**:
One generic record of a Study by which a person adopts or rejects the records it cites, such as proxy Decisions, a Plan, a Claim or a revision, which it never rewrites.
_Avoid_: approval, sign-off, review (for the record)

**Pending decision**:
A Comparison of the current revision that no applying Decision cites and whose two Assessments have no later Assessment. It is derived when the Study is read and never stored, and it is not a **Decision**.
_Avoid_: open decision, pending choice

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

**Plan**:
The record of a Study, kept outside the Protocol digest, that holds the `rule`, the `budget` and the `delegation` a person ratified, the `delegation` being the kinds of question a proxy may answer; the rules on when information is available stay in the Protocol, and a Plan is not a Campaign's `plan.json`.
_Avoid_: methodology, strategy, policy

**Claim**:
One statement about the domain, recorded with what it is about, when it is available and its source embedded in the record, such as a local PDF, HTML or Markdown file named by its path, page, date and sha256.
_Avoid_: fact, finding, domain claim

**Exposure**:
Any Assessment, Comparison or report that touches Items of the `public_check` Partition; every Configuration created after the first Exposure is marked `check_informed`.
Clarification, 2026-11-21: a live view of artifacts already recorded is not a "report": such a view does not record an Exposure and does not write (D-031 item 9 on chadlis/hypotrail#75, ticket #111).
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
Clarification, 2026-11-22: "earlier" and "later", said of two Assessments of one Study, name one order, the order in which the Study recorded them; handbook chapter 10 states it (chadlis/hypotrail#121, B2).
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
- A **Decision** is a record of one **Study**: it cites at least one record the Study holds, is made on the **Write sequence** its author read, and advances that sequence when it is recorded.
- A **Study** admits the writes of one **Study writer** at a time, and each write advances the **Write sequence**.
- A **Declared deviation** is a record of one **Study**: it cites records the Study holds.
- A **Plan** is a record of one **Study** outside its **Protocol** digest: a new Plan is not a new revision, and a change of the rules on when information is available is.
- A **Claim** holds its source inside its own record; a **Validation** that cites it adopts or rejects it.
- A **Validation** is a record of one **Study**: it cites the records a person adopts or rejects, such as proxy **Decisions**, a **Plan**, a **Claim** or a revision.
- A data profile, a read of a **Workload**'s `train` data, is named here in lower case and has no entry: a read is not a term.

## Correspondence with Inspect

Inspect executes agentic Episodes; its words map onto Hypotrail's as follows. **Sample** ↔ Case, **epoch** ↔ Repeat, **sample × epoch** ↔ Episode, **eval log** ↔ the raw artifact behind an Observation set, **Inspect scorer** ↔ a display of a Hypotrail Scorer, never the authoritative verdict, **`Score.unscored()`** ↔ `unscored`. Inspect's `ERRORED` sample covers two of our cases at once: an execution that stopped (Item `failed`) and a scoring machinery failure (Criterion `errored`).
