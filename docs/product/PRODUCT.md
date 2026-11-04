# Hypotrail product direction

Hypotrail helps an applied AI team review studies of predictive models and LLM agents when code and candidate Configurations can be produced faster than people can examine their assumptions. Its purpose is to make the evidence behind a Comparison inspectable, keep decisions traceable, and state what remains unknown.

This is the target product direction. Delivered capabilities are described in the [README](../../README.md) and [handbook](../handbook/handbook.html). The committed scope is [L1, issue #1](https://github.com/chadlis/hypotrail/issues/1), including its dated amendments. This page does not expand that scope.

## Users and the decision they need to make

The primary user is an ML or applied AI engineer who produces or adopts model predictions or agent answers, often with a coding agent. A reviewer needs to understand what was evaluated, whether two results are comparable, and what evidence supports keeping, changing or rejecting a Configuration.

The product should support a small new proof of concept and the assessment of work that already exists. Adoption should begin with retained outputs and a declared Protocol when replacing the producer would be unnecessary.

Success means that a reviewer can reconstruct the basis and limits of a conclusion with less searching and less reliance on the original chat. More generated code, more recorded events or a higher model Metric alone do not demonstrate product value.

## Main user journeys

These are product needs, not eight implementation tickets. A journey can span several slices. The [roadmap](ROADMAP.md) selects which parts become committed work.

| ID | User need | Observable outcome |
|---|---|---|
| P01 | Frame the question before trusting a result. | The intended decision, population, prediction or action context, available information and known limits are explicit. |
| P02 | Evaluate outputs from an existing script or agent. | An Import retains the input artifacts, identifies the Items, exposes missing outputs and keeps unverified provenance declared or unknown. |
| P03 | Produce a controlled alternative. | Supported native execution records the Configuration, output population, limits and failures under the Study's Protocol. |
| P04 | Inspect whether the method supports the claim. | Applicable controls name their scope and evidence. Unchecked conditions and human assumptions remain visible. |
| P05 | Compare two Configurations fairly. | A Comparison aligns the permitted population and scoring conditions, exposes denominators and separates execution failures from scoring failures. |
| P06 | Reassess retained outputs. | A new Assessment uses identified Scorer and Reference versions without silently rerunning the model, tools or fitting. Earlier Assessments remain available. |
| P07 | Review consequential choices and resume later. | The reviewer sees the pending decision, evidence, alternatives and consequences. A later session recovers the saved state and next action. |
| P08 | Hand a study to another person. | A readable view links the conclusion to its outputs, decisions, limitations and reproducible commands where available. |

Keeping the Control or concluding that the evidence is insufficient are useful outcomes.

## Two ways into the same evaluation core

**Direct evaluation:** use the supported commands to run or import, assess, compare and report. This path remains usable without a chat session or a guided workflow.

**Guided study:** an optional interaction layer helps frame the question, inspect evidence and record decisions. It calls the same application operations as direct evaluation. It may guide a new Study or begin from an existing one without pretending that earlier production steps were observed.

A native Attempt can establish facts that an imported file cannot establish. A human confirmation records a decision or assertion. It does not turn unknown provenance into verified provenance.

## Recover the useful parts of the original Hypotrail

The original repository supplies interaction designs, methodological controls, rendering patterns and potentially reusable implementation. The new product should recover the useful behaviour through its own contracts.

- Keep a visible study position, a clear next action and contextual explanations of charts.
- Keep the decision loop: inspect the proposal and its evidence, adopt it, change it or ask for an explanation.
- Keep the distinction between automatic proposals, explicit delegation and human decisions.
- Keep resumption, decision history and the visibility of changed or stale evidence.
- Reuse methodological controls only where their assumptions match the supported Track.
- Rebuild the visual companion as a client of the new Study operations. Reports and clients must not maintain competing results or decision state.

The target visual view shows the question and scope, what needs attention, the next decision, the relevant evidence and the decision history. A minimal view belongs with the first guided workflow. Rich notebook editing and additional IDE integrations can follow demonstrated need.

[Legacy reuse choices and sources](ROADMAP.md#legacy-reuse) specify what to adapt, evaluate or leave behind. Existing interface code is not evidence that the interaction has been validated with users.

## Product boundaries

The core remains independent of Inspect. Inspect executes supported agentic Episodes. ML fitting and preprocessing remain with appropriate ML libraries. Hypotrail adds the study contracts, evidence links and review context that those operations need. See [ADR 0001](../adr/0001-core-independent-of-inspect.md).

Keep an open [package shortlist](PACKAGE-CANDIDATES.md) now. Perform focused research for a milestone's substantial capabilities before freezing its specifications, alongside targeted legacy reuse. Prefer the smallest integration that meets the actual requirement. A library can suggest a new capability, but that capability first needs a user need and an evaluation protocol. The [reuse assessment](ROADMAP.md#package-reuse-decisions) is revisited for a new method or boundary, not repeated for every PR.

Use the domain terms in [GLOSSARY.md](../../GLOSSARY.md). In particular, execution Mode describes how outputs arose. Guidance depth is a separate interaction preference and must not reuse Mode with a different meaning.

Supported Workloads are declarative. Missing capabilities are added explicitly to Track code when a concrete Workload requires them, following [ADR 0002](../adr/0002-workloads-are-declarative.md).

A passed control is evidence about its stated condition. Hypotrail does not certify the absence of every leak, the correctness of every assumption, or suitability for deployment. Historical or public evaluation data do not become unseen through a new folder, session or interface.

The direction does not require old Study migration, complete feature parity with the old engine, a new agent execution framework or a dynamic plugin system. Each addition must earn its place in a demonstrated user journey.

## Evidence of usefulness

Use a complete Study to observe whether another team member can identify the Protocol, trace a result, notice an unsupported conclusion and make or defer a decision. Record the assistance needed, the review time and the misunderstandings encountered.

Compare this experience with the team's ordinary scripts, logs and explanations on similar work. Initial observations are a pilot, not a general productivity claim. They decide the next milestone's priority.
