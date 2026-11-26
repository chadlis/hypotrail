"""The paired resampling interval on the delta of a Comparison, with the standard library only.

`percentile_interval` takes the paired deltas of a Comparison, one number per unit (a Case of the agent Track, or an Item), draws as
many units as there are with replacement, takes the mean of each draw, and returns the two percentiles of those means with the quantile
rule of `hypotrail.core.figures`. `circular_block_interval` does the same over ordered deltas (the days of a series) by blocks: each
resample draws ceil(n / L) start positions with replacement, takes L consecutive deltas from each, wrapping from the last to the first,
and keeps the first n. The level, the count of resamples and the method are fixed here; the unit, the block and the seed are declared by
the Workload (`resampling`) and copied into the StudySpec, and `record` writes the `interval` key of a Comparison from that declaration.
"""

import math
import random

LEVEL = 0.95
RESAMPLES = 2000
METHOD = "percentile_bootstrap"
CIRCULAR = "circular"
TOO_FEW_UNITS = "too_few_units"
NOT_DECLARED = "resampling_not_declared"
DELTA_WITHHELD = "delta_withheld"
SERIES_NOT_CONTIGUOUS = "series_not_contiguous"


def block_indices(n: int, length: int, generator: random.Random) -> list:
    """The positions of one circular block resample of n ordered units: runs of `length` consecutive positions modulo n, cut to n."""
    starts = [math.floor(generator.random() * n) for _ in range(math.ceil(n / length))]
    return [(start + offset) % n for start in starts for offset in range(length)][:n]


def _interval(deltas: list, length: int, seed: int, resamples: int, level: float) -> dict:
    from hypotrail.core import figures  # figures imports both comparison modules, which import this one

    n = len(deltas)
    if n < 2:
        return {"lower": None, "upper": None, "reason": TOO_FEW_UNITS}
    if all(delta == deltas[0] for delta in deltas):
        return {"lower": deltas[0], "upper": deltas[0], "reason": None}
    generator = random.Random(seed)
    means = sorted(sum(deltas[i] for i in block_indices(n, length, generator)) / n for _ in range(resamples))
    tail = (1 - level) / 2

    def percentile(p):
        position = figures.quantile_position(len(means), p)
        lower = int(position)
        upper = min(lower + 1, len(means) - 1)
        return figures.quantile_value(means[lower], means[upper], position - lower)

    return {"lower": percentile(tail), "upper": percentile(1 - tail), "reason": None}


def percentile_interval(deltas: list, *, seed: int, resamples: int = RESAMPLES, level: float = LEVEL) -> dict:
    """{lower, upper, reason}: the percentile bounds of the means of `resamples` draws of the units, or no bounds with `too_few_units`."""
    return _interval(deltas, 1, seed, resamples, level)


def circular_block_interval(deltas: list, *, length: int, seed: int, resamples: int = RESAMPLES, level: float = LEVEL) -> dict:
    """{lower, upper, reason}: as `percentile_interval`, over `deltas` in their order, resampled by circular blocks of `length`."""
    return _interval(deltas, length, seed, resamples, level)


def record(resampling: dict | None, deltas: list | None, *, missing: str = DELTA_WITHHELD) -> dict:
    """The `interval` key of a Comparison: over `deltas` (one per unit, in order) when the Study declares `resampling` and they exist.

    With no declaration, `unit`, `seed` and `units` are null and `reason` is `resampling_not_declared`. With `deltas` None, `units` is
    null and `reason` is `missing`: `delta_withheld`, or `series_not_contiguous` for a block declaration over a series with gaps.
    """
    base = {"level": LEVEL, "method": METHOD, "variant": None, "block_length": None, "resamples": RESAMPLES}
    if resampling is None:
        return {**base, "lower": None, "upper": None, "unit": None, "units": None, "seed": None, "reason": NOT_DECLARED}
    block = resampling.get("block")
    declared = {"unit": resampling["unit"], "seed": resampling["seed"]}
    if block is not None:
        declared.update(variant=block["variant"], block_length=block["length"])
    if deltas is None:
        return {**base, **declared, "lower": None, "upper": None, "units": None, "reason": missing}
    length = 1 if block is None else block["length"]
    return {**base, **declared, "units": len(deltas), **_interval(deltas, length, resampling["seed"], RESAMPLES, LEVEL)}
