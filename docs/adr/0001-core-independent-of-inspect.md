# The core is independent of Inspect; Inspect only executes agentic Episodes

Status: accepted

Inspect can run, score and rescore evaluations, and even run without a model, so building it into the core was a real option. We keep the core (Attempts, Observation sets, Assessments, Comparisons, Imports, reports) free of any Inspect dependency because machine-learning Tracks, and imports of outputs produced elsewhere, must work without Inspect installed, and because fitting on a whole Partition and time-ordered availability do not fit Inspect's per-sample model. Inspect owns the agent loop, tool calls and its native log; Hypotrail owns every Scorer, and the authoritative verdict is always a Hypotrail Assessment.

## Considered options

- **Inspect as the core for every Track**: maximum reuse of its scoring, rescoring and viewer, at the cost of forcing ML fitting, temporal protocols and external imports into an LLM-shaped envelope and of making Inspect a hard dependency.
- **A core that copies Inspect's object model without the library**: the coupling costs of its formats without the benefit of its implementation.

## Consequences

- One scoring function per Scorer. An Inspect `@scorer` adapter may call it to display scores in Inspect's viewer, and a parity test must show both paths give identical verdicts; if parity fails, the adapter is removed.
- Agentic Observation sets are projections of Inspect eval logs read through Inspect's public log API, never through a hand-written parser.
