# Workloads are declarative; generic code grows one parameter at a time

Status: accepted

A Workload (data, licence, References, declared settings) holds no Python: everything it needs to run, such as the target column, the lag period, the Partition date ranges or the forbidden features, is a parameter of generic Track code in `src/hypotrail/`. We chose this over keeping workload-specific code next to its data, as `inspect_evals` does, because the long-term goal is a generic engine and a Workload that needs its own code is the clearest signal that a generic capability is missing. We still generalise incrementally: a capability becomes a parameter when a Workload needs it, with no plugin system and no dynamically loaded code.

## Consequences

- When a Workload cannot be expressed through existing parameters, the missing capability is added to the Track explicitly, never as code inside `examples/`.
- `examples/external/` is the deliberate exception: it is Python that stands in for someone else's program and never imports `hypotrail`.

## Amendment, 2026-11-04

Track code fixes two kinds of vocabulary, and only these. The Partition roles of a Track (`train`, `dev` and `public_check` for temporal regression: fit on `train`, measure on `dev`, keep `public_check` for the Exposure-tracked check) are protocol vocabulary, defined once in the Track, because a Workload that could choose where to fit could fit on the check (SPEC §2, ML-05). The kinds of Configuration a Track runs (for example `seasonal_baseline` and `ridge_pipeline`), with the keys each kind takes, are Track capabilities. Everything else stays a Workload parameter, including the Partition date ranges. Decided by the owner on chadlis/hypotrail#7 (option 3A).

Clarification, 2026-11-04: the keys a Workload declaration may hold, and the domain of each value (its type, allowed values and bounds), are the parameters of generic Track code in the sense of this ADR. The Track fixes them in one JSON Schema wherever JSON Schema can express them; the Workload sets their values. Two kinds of check stay in Track code, next to their use: whether a key is required by the entry point that reads it, and whether a period can be applied to actual dates. The Partition roles and the Configuration kinds above remain the only vocabulary fixed beyond those parameters. Settled by the drive session on chadlis/hypotrail#39 (round-4 finding 5 on chadlis/hypotrail#7).

Note, 2026-11-08: the clarification of 2026-11-04 above was rewritten in place during chadlis/hypotrail#7 (commit `12c882a`), after a review of record had read it, instead of being followed by a dated line. The first wording, recovered from commit `708a8a1`, differed in two sentences. It read: « The Track fixes them in one JSON Schema; the Workload sets their values. », and it had no sentence on checks that stay in Track code. The text above is kept as it stands now. Recorded by the drive session of chadlis/hypotrail#9 under chadlis/hypotrail#40 (H6).
