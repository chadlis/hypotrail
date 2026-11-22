# Hypotrail milestone direction

This roadmap keeps the target visible while only the active milestone is specified for execution. L1 is committed. L2 and L3 below are planning candidates whose scope and order may change after use.

Product purpose: [PRODUCT.md](PRODUCT.md). Current requirements: [L1 issue #1](https://github.com/chadlis/hypotrail/issues/1), its amendments and the specification it references. This document neither replaces that specification nor changes an existing slice's acceptance criteria.

## Direction at a glance

| Horizon | Result for the user | Commitment |
|---|---|---|
| L1 | Evaluate Bike and Chinook from outputs to an inspectable Comparison and report. | Existing committed milestone. |
| L2 | Make one review decision, end to end, in a VS Code webview panel that is a client of the CLI, and find it again in a fresh session. | Selected by the owner, then narrowed (D-062 on chadlis/hypotrail#75, change 3). "Built, not demonstrated" until the owner's demonstration; "usable" waits for an engineer who did not implement it (D-063, D-068 and D-077 on chadlis/hypotrail#75). |
| L3 | Use the product on five further Tracks or Workloads, each with its evaluation contract written first. | Selected by the owner. No construction before the owner's demonstration of L2 (D-068 on chadlis/hypotrail#75). Its breadth waits on the decision pilot, a pending gate without a date (D-062 on chadlis/hypotrail#75, changes 4 and 5). |
| Later options | Richer notebook and IDE interaction, clustering, pipeline integrations and public distribution. | Unordered options, not promised releases. |

These identifiers describe direction, not release numbers or calendar dates.

**Owner selection, 2026-11-20.** The owner selected L2 and L3 in the end state on #1 ([comment 7043566976](https://github.com/chadlis/hypotrail/issues/1#issuecomment-7043566976), « H3 »; [comment 7043774378](https://github.com/chadlis/hypotrail/issues/1#issuecomment-7043774378), items 2 and 3).
- L2 is a VS Code webview panel for guided review, client of the CLI.
- L3 is five further Tracks or Workloads.

This was decided without pilot evidence. The pilot in « Demonstration before calling L2 usable » stays the gate for calling L2 usable ([D-031](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7058866422), decision by proxy). The sections below keep the candidate text as it was written. Where the selection and that text disagree, the selection prevails.

**Decisions of 2026-11-22.** Three owner decisions and one decision by proxy on chadlis/hypotrail#75 change L2 and L3 as selected above:
- [D-062](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7074979450), change 3: "L2 is narrowed to one review decision, end to end." The L2 section below is rewritten for it.
- D-062, change 4, as amended by [D-063](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7075198791): a decision pilot gates how far L3 widens, and L2 is recorded as "built, not demonstrated". See "Pending gate: the decision pilot" below.
- [D-068](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7076156755): the chain stops at the end of L2 for the owner's demonstration, before any L3 construction.
- [D-077](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7080379605) (decision by proxy): the eleven points the rewrite left open, among them which decision L2 delivers and what the owner's demonstration lifts.

Where these decisions and the text below disagree, the decisions prevail.

## L1 complete the current evaluation milestone

The agreed endpoint is two public Workloads, temporal regression on Bike and a tool-using agent on Chinook, with native execution, Imports, retained outputs, Assessments, Comparisons, rescoring and an offline report.

Keep the existing issues:

| Slice | Existing issue | Demonstration |
|---|---|---|
| L1.0 feasibility | [#6](https://github.com/chadlis/hypotrail/issues/6) | Environment, data, retained Inspect log and feasibility evidence. |
| L1.1 Bike | [#7](https://github.com/chadlis/hypotrail/issues/7) | Compare seasonal_7 and ridge_v1 on the declared dates and inspect the temporal controls. |
| L1.2 Chinook | [#8](https://github.com/chadlis/hypotrail/issues/8) | Inspect supported agent answers, tool traces, limits and scoring outcomes. |
| L1.3 shared contracts | [#9](https://github.com/chadlis/hypotrail/issues/9) | Import external outputs, enforce the Comparison contract, rescore and expose interruption. |
| L1.4 report and acceptance | [#10](https://github.com/chadlis/hypotrail/issues/10) | Read the complete Study and walk the acceptance evidence from a clean installation. |

At the 2026-11-04 source check, #6 was closed and [PR #25](https://github.com/chadlis/hypotrail/pull/25) was merged. #7 to #10 remained open. Use the live tracker for current status.

Keep OFFLINE_ACCEPTED, LIVE_ACCEPTED and USABILITY_REVIEW_PENDING distinct. Do not replace T01–T24 with a shorter checklist from this roadmap. The existing gaps [#22](https://github.com/chadlis/hypotrail/issues/22) about data fetch and [#23](https://github.com/chadlis/hypotrail/issues/23) about installed Workload discovery must be assigned or explicitly resolved through the existing milestone process.

The owner amendment limits the pre-campaign semantic Reference review to D07, D08, E11 and E12. Retain that decision and any later amendment rather than restarting a full review by default.

Use the L1 report to collect interaction feedback. Building the L2 workflow is not a new condition for closing L1.

## L2 one review decision, end to end

**Outcome:** a reviewer can understand a Study, resolve a consequential choice and return later without reconstructing its history from a chat.

The new engine supplies evaluation evidence. A small workflow layer supplies the current review question, the decision record and the next permitted action. This layer remains optional for direct evaluation.

*Rewritten 2026-11-22.* The owner narrowed L2 (D-062 on chadlis/hypotrail#75, change 3):

> L2 is narrowed to one review decision, end to end. That decision distinguishes "evidence rescored" from "result changed", and shows the Assessments a Comparison depends on.

The earlier candidate scope named several decision points, on Bike and on retained Chinook outputs. L2 now delivers one decision type, the decision on a Comparison (D-077 on chadlis/hypotrail#75, Q2). The owner's demonstration uses Bike's first Comparison, `seasonal_7` against `ridge_v1` on `dev`, and the tests run the same decision on Chinook fixture Studies. The parent issue chadlis/hypotrail#103 owns the acceptance.

### Scope

- One review decision, taken from the pending question to the recorded Decision, and found again in a fresh session.
- The evidence of that decision: the Comparison it is about, the Assessments that Comparison depends on, and the limits recorded with them.
- When the evidence of a recorded Decision changes, the review says what happened: "evidence rescored", "result changed" or, for a repeated Assessment, "repeated, nothing changed" (D-077, Q3).
- A VS Code webview panel that shows the pending decision, its evidence and its history. It reads the Study and records the Decision through the CLI, and keeps no state of its own ([ADR 0004](../adr/0004-panel-cli-contract.md)).
- The two chat channels, limited to that one decision: a Claude Code hook and a Copilot tool, so that the next chat turn knows a Decision recorded in the panel (D-077, Q1).
- Reconstruct the pending work in a fresh session without rerunning an operation whose outcome is unknown.

Delivered: the Decision record, the Write sequence and the contract between a client and the CLI (L2.1, chadlis/hypotrail#104).

For a change to population, Partitions or availability rules, define the transition explicitly before implementation. Do not edit a frozen Protocol in place. A new Study must retain links to the earlier work and relevant exposure disclosures. Corrections to References and rescoring retain L1's versioned Assessment semantics.

### Interface direction

Recover the original companion's useful information hierarchy: what needs attention, what changed, what happens now, the study path and the supporting artifacts.

Start with chat or CLI actions and a read-only generated Study view. Folding sections, following evidence links and copying the next question are useful interactions. A static HTML export cannot persist a decision. If a later panel records one, it must call a documented application command and handle stale state through the same contract as the CLI.

This is already a visual product increment. Choosing a VS Code webview or a local web application is a later implementation decision informed by the pilot, not a prerequisite for this first view. No private UI database, duplicated Scorer or separate decision authority is introduced.

*Amended 2026-11-21:* the owner's selection above settles the choice, without a pilot. L2 is a VS Code webview panel that records decisions through a documented CLI command, as this section requires. The read-only generated view is not a separate first step.

### Demonstration before calling L2 usable

One engineer who did not implement the slice can identify the pending decision, inspect its evidence, record an answer and recover it in a fresh session. The view shows a real limitation and an outdated conclusion when its supporting evidence changes. It agrees with the CLI on artifact identities and status. Direct evaluation remains usable without the workflow.

Observe the pilot and record remaining confusion. Do not infer validated usability from screenshots or automated tests alone.

*Amended 2026-11-22:* three things are kept apart (D-077 on chadlis/hypotrail#75, Q9).
- **"Built, not demonstrated".** L2 is recorded so until someone who did not build it has demonstrated it (D-063 on chadlis/hypotrail#75, "D-062, amended", item 3). The owner demonstrates it himself, before any L3 construction: « Je fais moi-même la démo et les tests de L2 avant toute construction de L3. » (D-068 on chadlis/hypotrail#75). His demonstration lifts this status, and he is the one who lifts it. The demonstration protocol is written before the demonstration, in L2's milestone acceptance. Each blocker the owner reports becomes an issue, and a blocker that prevents a task of the protocol is fixed in a slice of its own, before L3.
- **"Usable".** The owner's demonstration does not make L2 usable. That still waits for the engineer of the first paragraph of this section, who did not implement it.
- **The decision pilot.** It is a distinct gate, on L3's breadth: see "Pending gate: the decision pilot" below.

~~The next specification should choose a few consequential decision points.~~ *Amended 2026-11-22:* L2 has one decision point (D-062, change 3). It should not reproduce every old confirmation or require a lesson at every step. No generic workflow editor, universal invalidation engine or full notebook editor is required.

## Pending gate: the decision pilot

A decision pilot with ML engineers, against a control condition (the team's usual tools and a review sheet), will gate how far L3 widens (D-062 on chadlis/hypotrail#75, change 4). It has no date: no engineers are available now. L2 and L3 go ahead without pilot evidence, and the pilot runs when engineers are available.

This gate is neither the owner's demonstration of L2 nor the engineer's walk that lets L2 be called usable (D-077 on chadlis/hypotrail#75, Q9).

## L3 reuse on another project

**Outcome:** another Study can use the same contracts without copying the engine.

First onboard a second Workload in an existing Track, initially with public data. This tests whether framing, Import mapping, reports and the guided review are tied to Bike or Chinook.

~~Then select one additional Track only if it serves a concrete need. Multiclass classification is a useful candidate.~~ *Amended 2026-11-22* (D-063 on chadlis/hypotrail#75, "D-062, amended", item 4): the owner selected five Tracks or Workloads ([end state, item 3](https://github.com/chadlis/hypotrail/issues/1#issuecomment-7043774378)), and D-062, change 5, keeps them: "L3 keeps its five Tracks, with Track D widened. Its breadth may be revised after the pilot."
- A: multiclass tabular classification.
- B: binary classification with a declared decision threshold and error costs.
- Regression: read by the drive as a non-temporal tabular regression Track; the owner may correct this reading.
- C: a second agent Workload without SQL, with answers checkable without an LLM judge.
- D: multi-horizon forecasting over several series ([owner instruction of 2026-11-21](https://github.com/chadlis/hypotrail/issues/1#issuecomment-7060192445)).

Before committing each one, state the population, classes, Reference meaning, Metrics, baselines, missing-output treatment, appropriate Partitions and the interpretation of the Comparison. A reuse table alone is not that specification.

A regression result, a classification probability and a cluster assignment do not share the same scientific meaning. Clustering therefore remains an option requiring its own evaluation question, stability or external criteria where justified, and honest limits when no Reference labels exist.

Exit evidence is a completed pilot with the new Workload, its effort to configure, its unsupported conditions and regressions checked on Bike and Chinook. Additional generality is justified by those concrete requirements.

## Legacy reuse

Use hypotrail/hypotrail as a source of behaviour and selected implementation. Own any reused code in the new repository and retain relevant provenance and notices. Do not import the old package or migrate its Study state by default.

The source snapshot below is b92a74ddd7deded09b5592b1df21f827dab66048. Its docs distinguish target specifications from implementation and explicitly report no human junior use and no real VS Code validation. Reassess those limits if newer evidence appears.

| Legacy asset | What to retain | Adaptation in the new product |
|---|---|---|
| [Guidance loop and study resumption](https://github.com/hypotrail/hypotrail/blob/b92a74ddd7deded09b5592b1df21f827dab66048/docs/specs/JUNIOR-WORKFLOW.md) | Context before choices, one main question, visible evidence, explicit decisions and a useful next action. | L2 consumes the new Study artifacts. Adapt each decision to its Track. A guided explanation is optional. |
| [Automatic decisions and review](https://github.com/hypotrail/hypotrail/blob/b92a74ddd7deded09b5592b1df21f827dab66048/docs/handoff/IMPLEMENTATION.md) | Clearly distinguish an automatic proposal, a delegation and a human decision. | Preserve the distinction. Later review cannot undo prior Exposure or prove how imported outputs were produced. |
| [Methodological requirements](https://github.com/hypotrail/hypotrail/blob/b92a74ddd7deded09b5592b1df21f827dab66048/docs/specs/JUNIOR-WORKFLOW.md) | Time and group awareness, feature availability, training-only fitting, selection history and limitations. | Select controls required by the Workload. State the observed boundary of each control. Extend L1 only through an explicit scope amendment. |
| [Visual Study panel](https://github.com/hypotrail/hypotrail/blob/b92a74ddd7deded09b5592b1df21f827dab66048/clients/vscode-companion/README.md) | Current position, attention items, evidence in context, history and artifact navigation. | Rebuild against the new view and command contracts. Validate with a real user before investing in every old drawer or control. |
| [Report and notebook patterns](https://github.com/hypotrail/hypotrail/blob/b92a74ddd7deded09b5592b1df21f827dab66048/docs/handoff/IMPLEMENTATION.md) | Explain why a chart exists, how to read it and what it establishes. Preserve personal edits. | L1 owns the report. L2 adds review context. Rich Marimo editing remains optional and follows a separate demonstrated need. |
| [Companion as a CLI client](https://github.com/hypotrail/hypotrail/blob/b92a74ddd7deded09b5592b1df21f827dab66048/docs/decisions/0002-companion-as-cli-client.md) | One authoritative state and shared mutation rules across clients. | Reuse the boundary, not the old SQLite companion protocol or old state files. Document the new contract in an ADR when implemented. |
| [Current permission to reuse infrastructure](https://github.com/chadlis/hypotrail/issues/1) | Canonical serialization, atomic publication and writer locking where appropriate. | Inspect small components and their tests. Use a suitable dependency where it meets the requirement. Verify changed assumptions in the new codebase. |
| [Declared limits of the old implementation](https://github.com/hypotrail/hypotrail/blob/b92a74ddd7deded09b5592b1df21f827dab66048/docs/handoff/IMPLEMENTATION.md) | Known failure cases and lessons from earlier review. | Keep them as design inputs. Do not port lexical confirmation checks as proof of understanding, rigid historical decision counts or unverified usability claims. |

The old closed-test interaction cannot simply rename L1's public_check Partition. Public or previously inspected data remain exposed. Any future holdout mechanism needs its own explicit protocol and threat boundary.

The old repository's visual charter is inspiration. The new repository's accepted design and accessibility requirements take precedence. Copying CSS does not require copying the old renderer or state model.

## Package reuse decisions

Library reuse serves two purposes: avoid rebuilding an existing capability, and discover a useful capability the current product lacks. For the second, first state the user's decision it would improve. Package availability alone does not justify a feature.

### When to examine candidates

- Keep a lightweight, open shortlist now. During milestone preparation, research the substantial capabilities it needs before freezing its specifications. Search current primary sources beyond the shortlist, then compare only the relevant options.
- Before specifying a slice that adds a statistical method, diagnostic suite, execution engine, notebook interaction or integration boundary, compare the relevant options. Record the result before to-tickets turns the requirement into implementation work.
- Reopen a decision when requirements change, an integration fails, an upstream change affects the contract or new evidence could change the choice. Ordinary fixes and PRs reuse the existing decision.

This fits the current Matt Pocock workflow. The milestone or slice records the choice and sources, the ticket gate checks the resulting scope, and the review verifies the implementation. No additional standing review or exhaustive package survey is required for every PR.

### A small decision record

Compare a short list against the actual Workload and the simplest adequate alternative, including deferring the feature. Consider the old implementation as well as external packages. A small original implementation remains possible when it is simpler and does not duplicate a native primitive the repository has already delegated.

Record in the milestone or slice:

| Field | What the agent must establish |
|---|---|
| User need and requirement | The capability needed now and what would count as success. |
| Candidates and sources | Current upstream docs and the versions actually examined. |
| Method fit | Input population, sampling or calibration assumptions, output meaning and failure behaviour. |
| Integration and ownership | What the package owns, what Hypotrail owns, retained outputs, dependency footprint, installation, license and maintenance considerations. |
| Evidence and decision | Representative normal and failure cases, options rejected, remaining uncertainty and the trigger for reconsidering. |

Use a short spike only when uncertainty could change the choice. For an adapter, verify identities, units, missing values, error propagation and saved raw outputs. For a statistical claim, examine the applicable assumptions and suitable simulations or reference calculations. Successful installation or a green import test is insufficient evidence for that claim.

An architecture decision goes in an ADR when it introduces a lasting boundary or important trade-off. Otherwise a short section of the existing issue is enough. This is not a new package backlog.

### Candidates tied to concrete needs

The open list in [PACKAGE-CANDIDATES.md](PACKAGE-CANDIDATES.md) keeps the earlier leads: Deepchecks, Evidently, OpenML, Kedro, MLflow, AIDE ML, MLZero, MAPIE, GLIDE and Inspect. Inspect and scikit-learn remain existing L1 choices. The list is neither exhaustive nor a dependency plan. A future milestone can discover a better option.

Keep research conclusions in the milestone or slice that needed them, with the versions, evidence and review date. Reuse a still-applicable decision rather than performing the same comparison again.

Do not add both Deepchecks and Evidently without a distinct requirement for each. Keep deterministic Chinook scoring when the Reference is computable. GLIDE becomes a candidate when the Study genuinely needs human/proxy estimation. MAPIE becomes a candidate when the decision needs calibrated uncertainty, not merely because Bike is a regression Workload.

### Integrate at the right boundary

Use an explicit call, an artifact Import or a small adapter before considering an extension framework. Keep optional dependencies optional. Preserve the new repository's prohibition on dynamically loaded Workload code.

These capabilities have different roles. Execution produces observations. Calibration may change a predictive Configuration and its outputs. Diagnostics inspect data or results. Aggregate inference estimates a population quantity. Do not force all four into a per-Item Scorer interface. Define any necessary new result contract when that capability is selected, while preserving source artifacts and software versions.

Hypotrail retains its Protocol, the trace from evidence to decision, and the distinction between measured, declared and unknown information. A dependency can supply the computation behind those records without becoming their competing authority.

## Later options

- Richer notebook interaction and an IDE panel, selected by observed review needs.
- Further classification, clustering or agentic Tracks with explicit acceptance contracts.
- Azure ML and Databricks adoption, initially through retained artifacts and Imports. Dedicated execution integrations require a concrete pipeline and supported contract.
- Public distribution after a clean installation and independent walkthrough work, the supported scope is honest, maintenance expectations are stated and the owner has chosen the project license.

These options do not authorize implementation or make other projects depend on Hypotrail being finished.

## Where the plan lives and how it becomes work

- PRODUCT.md owns purpose, users and journeys. ROADMAP.md owns the planning horizons. PACKAGE-CANDIDATES.md preserves research leads, without prescribing dependencies. All three live in docs/product/.
- GitHub milestone parent issues own committed outcomes and links to their specifications. L1 already has #1. Dated owner amendments remain authoritative under the existing repository rules.
- Slice issues own their bounded scope and acceptance evidence. The Matt Pocock workflow used by drive creates implementation tickets with to-tickets, then orchestrates implementation, independent review, documentation and PRs.
- ADRs record adopted architecture decisions. The handbook documents delivered behaviour. The French learning repository follows selected learning objectives, independently of product scope.

~~For now, keep L2 and L3 in this file. Do not create execution parent issues or child tickets merely to represent these candidates.~~ *Amended 2026-11-21:* L2 and L3 are selected (see « Owner selection » above). Each gets its parent issue when it is next, L2 first. The drive starts their slices with an explicit `/drive #n` while #1 stays open for the owner and pilot reviews ([D-031](https://github.com/chadlis/hypotrail/issues/75#issuecomment-7058866422)). In the current drive selector, an open parent titled L<n> can become executable once earlier work is closed. A future label or a native GitHub Milestone object is not an activation guard.

When the owner selects the next milestone, reconcile the proposal with pilot evidence, then create its parent issue with the outcome, scope, exclusions and observable acceptance. Define only the next slices that have enough evidence. Use the existing Blocked by: convention for execution dependencies. Let drive do the technical ticket decomposition.

An optional GitHub Milestone object can group issues for display later. It is not an additional specification or a replacement for the parent issue that drive reads.
