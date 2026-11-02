# Workloads are declarative; generic code grows one parameter at a time

Status: accepted

A Workload (data, licence, References, declared settings) holds no Python: everything it needs to run, such as the target column, the lag period, the Partition date ranges or the forbidden features, is a parameter of generic Track code in `src/hypotrail/`. We chose this over keeping workload-specific code next to its data, as `inspect_evals` does, because the long-term goal is a generic engine and a Workload that needs its own code is the clearest signal that a generic capability is missing. We still generalise incrementally: a capability becomes a parameter when a Workload needs it, with no plugin system and no dynamically loaded code.

## Consequences

- When a Workload cannot be expressed through existing parameters, the missing capability is added to the Track explicitly, never as code inside `examples/`.
- `examples/external/` is the deliberate exception: it is Python that stands in for someone else's program and never imports `hypotrail`.
