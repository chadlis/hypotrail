# The Plan is a Study record outside the Protocol digest; the rules on when information is available stay inside it

Status: accepted

The owner adopted "a Plan outside the Protocol digest (`rule`, `budget`, `delegation`), with availability kept inside" (D-148 on chadlis/hypotrail#75, item 1). A Plan (GLOSSARY, **Plan**) holds what a person ratified about how a Study goes on: the rule a proxy applies, the budget of Assessments, and the delegation, the kinds of question a proxy may answer. The Protocol holds what binds every Attempt. This ADR records which of the two holds what, and why.

## Decision

- A Plan is a record of the Study outside the Protocol digest, kept in a file of its own and never rewritten, that holds `rule`, `budget` and `delegation`. It is not part of the Protocol content whose canonical digest is a StudySpec's `protocol_digest`, so recording a Plan opens no revision.
- The rules on when information is available stay inside the Protocol digest: for temporal regression, the key `availability` of the Protocol content (`period_k`, `forbidden_features`, `allowed_target_features`), as `protocol_content` in `src/hypotrail/ml/study.py` holds it. A change of them is a new revision, through `init --study DIR --new-revision`, which refuses a Protocol the current revision already holds.

The reason is what a revision does to the Decisions of a Study. A Decision no longer applies when the Study's current revision differs from the `revision` its record stores (`revision_changed`, as `core/decisions.py` names it). A change of rule or budget must not stop every Decision from applying: the third reading that D-148 on chadlis/hypotrail#75 adopts says "A rule or budget change must not stale every Decision." (chadlis/hypotrail-learning `notes/vision/revue-fable-3-plan-integre.md`, commit `8016e17`, section 5, item 1). A change of availability must stop them: it changes what an Attempt may use, and the second reading says that a change which "lets a column in, or takes `lag_1` out, changes `forbidden_features` or `allowed_target_features`, so it is a revision, and `revision_changed` stales every Decision" (`notes/vision/revue-fable-2-design-consolide.md`, commit `f345ada`, section 1, item 1). A Plan that also said what may be used would be a second place for it, so availability has one place only, the Protocol.

## Considered options

- **The Plan inside the Protocol digest** (not chosen): the second reading names it as the choice for an owner who wants every change of rule to stop every Decision, "He wants strict pre-registration: the Plan goes inside the digest (Option B)." (`notes/vision/revue-fable-2-design-consolide.md`, section 6). Every change of rule or budget would then be a revision, and every Decision would stop applying on `revision_changed`.
- **The Plan outside the digest, availability with it** (not chosen): a change of availability would then leave the Decisions applying although it changes what an Attempt may use.
- **The Plan outside the digest, availability inside** (chosen): a change of rule or budget leaves the Decisions applying, and a change of availability is a revision.

## Consequences

- The Plan record and the command that writes it are not built: the Plan slice that D-148 on chadlis/hypotrail#75 places after the panel redesign builds them.
- The rule outcome beside each pending decision, the budget refusal on `assess` on `dev` with Imports counted, and the mark on a proxy Decision that differs from the rule (D-148 on chadlis/hypotrail#75, item 1) are not built.
- A change of the rules on when information is available that a Claim causes reaches the Protocol through `init --new-revision`, which is to gain `--cites`: `--cites`, the Claim record and its command are not built. `revision_changed` already stops every Decision from applying on such a revision.
- The Validation record, by which a person adopts or rejects a Plan, a Claim, a revision or proxy Decisions, is not built.
