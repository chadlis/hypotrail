# Package candidates for future milestones

This is an open research shortlist, not a dependency list, implementation backlog or ranking. Keep it lightweight. A candidate becomes a choice only after evaluation against a concrete milestone's requirements.

[PRODUCT.md](PRODUCT.md) states the user needs. [ROADMAP.md](ROADMAP.md#package-reuse-decisions) states when and how to make a reuse decision.

## Existing choices

Inspect for supported agentic execution and scikit-learn for supported ML operations are existing L1 choices. Read the current [milestone](https://github.com/chadlis/hypotrail/issues/1) and [ADR 0001](../adr/0001-core-independent-of-inspect.md) before reopening them. The core remains independent of Inspect.

## Initial leads

The question column is an investigation prompt. It is not a statement that the package meets Hypotrail's full requirements. Upstream capabilities, supported versions and maintenance must be checked when the need becomes active.

| Area to investigate | Initial source | Question for the relevant milestone |
|---|---|---|
| Data and train/test diagnostics | [Deepchecks](https://docs.deepchecks.com/stable/tabular/index.html) | Which required controls can be reused with identifiable populations, detailed outputs and useful failures? |
| Metrics, drift and visual reports | [Evidently](https://docs.evidentlyai.com/docs/library/overview) | Can existing calculations or exported reports meet the need without creating a second authoritative Study record? |
| Public task definitions and reproducible evaluation material | [OpenML](https://docs.openml.org/) | Can its tasks, data or conventions supply suitable inputs or inspiration while preserving the Workload's actual decision context? |
| Pipeline intervention points | [Kedro](https://docs.kedro.org/en/stable/) | For a project already using Kedro, can its extension points host the required controls with less integration effort? |
| Tracking, evaluation and comparison artifacts | [MLflow](https://mlflow.org/docs/latest/) | Is an import or a small integration enough to reuse the team's existing tracking and evaluation work? |
| Automated ML code exploration | [AIDE ML](https://github.com/WecoAI/aideml) | Can retained outputs and execution evidence be adopted while Hypotrail keeps responsibility for its evaluation Protocol? |
| Automated ML production | [AutoGluon Assistant, also called MLZero](https://github.com/autogluon/autogluon-assistant) | Would it be a useful external producer for a selected Workload, with suitable operating constraints and reproducible artifacts? |
| Prediction intervals, prediction sets or risk calibration | [MAPIE](https://github.com/scikit-learn-contrib/MAPIE) | Does a method fit the data structure, calibration population and decision requirement? |
| Statistical estimation with human and proxy annotations | [GLIDE](https://github.com/EmertonData/glide) | Does a supported sampling and estimation method fit the annotation design and quantity being estimated? |
| Agentic execution and retained logs | [Inspect](https://inspect.aisi.org.uk/) | Does an existing native feature cover the new requirement before Hypotrail adds its own machinery? |

The list can gain new candidates during milestone preparation. Being named earlier gives a tool no priority over a better current alternative.

Additional names from earlier discussion, not yet qualified here: ppi_py, CJE, evalstats, truescore and ARES. Revisit them only if the selected milestone needs judge calibration, statistical inference or RAG-specific evaluation. Resolve the exact project and primary sources before making a technical claim or implementation choice.

## What to establish when a need becomes active

1. State the user outcome and the precise capability needed.
2. Search current primary sources beyond this list, then shortlist the most relevant options.
3. Compare those options with selected legacy reuse, a small original implementation, an artifact Import and deferring the feature.
4. Examine method assumptions, input and output semantics, failure handling, dependency and installation costs, maintenance and license requirements.
5. Run a small discriminating check only where uncertainty could change the choice.
6. Record the decision in the milestone or slice before to-tickets. Use an ADR for a lasting architecture trade-off.

Do not repeat the full search for every PR. Reopen a decision only when requirements, observed failures, upstream changes or new evidence could alter it. Reuse existing tests and evidence when still applicable.

## Boundaries to keep

A data diagnostic, a calibration method, an agent execution and an aggregate estimator are different capabilities. Do not flatten all of them into a per-Item Scorer interface.

An uncertainty method needs its own evaluation question. A prediction interval is not a confidence interval for average performance. A correction to an aggregate human/proxy estimate does not repair each individual proxy judgment.

A library's own state, UI or orchestration is optional. Start with the smallest adequate dependency, adapter or artifact Import. A suitable external tool may remove the need to build an equivalent Hypotrail feature.

Any feature discovered through this research returns to the product decision first. It is not added to the active slice simply because an integration is available.

## Evidence status

Updated 2026-11-04. The linked projects are starting points, not an integration test or comparative benchmark. Current L1 commitments come from the repository, not this table. Record exact versions, observations and the review date when a candidate is actually assessed.
