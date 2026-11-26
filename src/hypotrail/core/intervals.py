"""The paired resampling interval on the delta of a Comparison, with the standard library only.

`percentile_interval` takes the paired deltas of a Comparison, one number per unit (a Case of the agent Track, or an Item), draws as
many units as there are with replacement, takes the mean of each draw, and returns the two percentiles of those means with the quantile
rule of `hypotrail.core.figures`. The level, the count of resamples and the method are fixed here; the unit and the seed are declared by
the Workload (`resampling`) and copied into the StudySpec, and `record` writes the `interval` key of a Comparison from that declaration.
"""

import random

LEVEL = 0.95
RESAMPLES = 2000
METHOD = "percentile_bootstrap"
TOO_FEW_UNITS = "too_few_units"
NOT_DECLARED = "resampling_not_declared"
DELTA_WITHHELD = "delta_withheld"


def percentile_interval(deltas: list, *, seed: int, resamples: int = RESAMPLES, level: float = LEVEL) -> dict:
    """{lower, upper, reason}: the percentile bounds of the means of `resamples` draws of the units, or no bounds with `too_few_units`."""
    from hypotrail.core import figures  # figures imports both comparison modules, which import this one

    n = len(deltas)
    if n < 2:
        return {"lower": None, "upper": None, "reason": TOO_FEW_UNITS}
    if all(delta == deltas[0] for delta in deltas):
        return {"lower": deltas[0], "upper": deltas[0], "reason": None}
    generator = random.Random(seed)
    means = sorted(sum(generator.choices(deltas, k=n)) / n for _ in range(resamples))
    tail = (1 - level) / 2

    def percentile(p):
        position = figures.quantile_position(len(means), p)
        lower = int(position)
        upper = min(lower + 1, len(means) - 1)
        return figures.quantile_value(means[lower], means[upper], position - lower)

    return {"lower": percentile(tail), "upper": percentile(1 - tail), "reason": None}


def record(resampling: dict | None, deltas: list | None) -> dict:
    """The `interval` key of a Comparison: over `deltas` (one per unit) when the Study declares `resampling` and the delta has a value.

    With no declaration, `unit`, `seed` and `units` are null and `reason` is `resampling_not_declared`; with a withheld delta (`deltas`
    None), `units` is null and `reason` is `delta_withheld`.
    """
    base = {"level": LEVEL, "method": METHOD, "variant": None, "block_length": None, "resamples": RESAMPLES}
    if resampling is None:
        return {**base, "lower": None, "upper": None, "unit": None, "units": None, "seed": None, "reason": NOT_DECLARED}
    declared = {"unit": resampling["unit"], "seed": resampling["seed"]}
    if deltas is None:
        return {**base, **declared, "lower": None, "upper": None, "units": None, "reason": DELTA_WITHHELD}
    return {**base, **declared, "units": len(deltas), **percentile_interval(deltas, seed=resampling["seed"])}
