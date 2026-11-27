"""The paired resampling interval on the delta of a Comparison, with the standard library only.

`percentile_interval` takes the paired deltas of a Comparison, one number per unit (a Case of the agent Track, or an Item), draws as
many units as there are with replacement, takes the mean of each draw, and returns the two percentiles of those means with the quantile
rule of `hypotrail.core.figures`. `circular_block_interval` does the same over ordered deltas (the days of a series) by blocks: each
resample draws ceil(n / L) start positions with replacement, takes L consecutive deltas from each, wrapping from the last to the first,
and keeps the first n. `cluster_interval` draws whole groups of Cases: as many groups as there are, with replacement, taken in the
sorted order of their ids, and the mean of the drawn groups' per-Case deltas. The level, the count of resamples and the method are fixed here; the unit, the block and the seed are declared by
the Workload (`resampling`) and copied into the StudySpec, and `record` writes the `interval` key of a Comparison from that declaration.
"""

import math
import random

LEVEL = 0.95
RESAMPLES = 2000
METHOD = "percentile_bootstrap"
CIRCULAR = "circular"
GROUP = "group"
ENTITY = "entity"
TOO_FEW_UNITS = "too_few_units"
NOT_DECLARED = "resampling_not_declared"
DELTA_WITHHELD = "delta_withheld"
SERIES_NOT_CONTIGUOUS = "series_not_contiguous"


def block_indices(n: int, length: int, generator: random.Random) -> list:
    """The positions of one circular block resample of n ordered units: runs of `length` consecutive positions modulo n, cut to n."""
    starts = [math.floor(generator.random() * n) for _ in range(math.ceil(n / length))]
    return [(start + offset) % n for start in starts for offset in range(length)][:n]


def percentile_bounds(estimates: list, level: float) -> dict:
    """Interpolate the two percentile bounds over a non-empty list of bootstrap estimates."""
    from hypotrail.core import figures  # figures imports both comparison modules, which import this one

    estimates = sorted(estimates)
    tail = (1 - level) / 2

    def percentile(p):
        position = figures.quantile_position(len(estimates), p)
        lower = int(position)
        upper = min(lower + 1, len(estimates) - 1)
        return figures.quantile_value(estimates[lower], estimates[upper], position - lower)

    return {"lower": percentile(tail), "upper": percentile(1 - tail), "reason": None}


def _interval(deltas: list, length: int, seed: int, resamples: int, level: float) -> dict:
    n = len(deltas)
    if n < 2:
        return {"lower": None, "upper": None, "reason": TOO_FEW_UNITS}
    if all(delta == deltas[0] for delta in deltas):
        return {"lower": deltas[0], "upper": deltas[0], "reason": None}
    generator = random.Random(seed)
    return percentile_bounds([sum(deltas[i] for i in block_indices(n, length, generator)) / n for _ in range(resamples)], level)


def percentile_interval(deltas: list, *, seed: int, resamples: int = RESAMPLES, level: float = LEVEL) -> dict:
    """{lower, upper, reason}: the percentile bounds of the means of `resamples` draws of the units, or no bounds with `too_few_units`."""
    return _interval(deltas, 1, seed, resamples, level)


def circular_block_interval(deltas: list, *, length: int, seed: int, resamples: int = RESAMPLES, level: float = LEVEL) -> dict:
    """{lower, upper, reason}: as `percentile_interval`, over `deltas` in their order, resampled by circular blocks of `length`."""
    return _interval(deltas, length, seed, resamples, level)


def group_totals(deltas: list, groups: list) -> list:
    """(sum, count) of the deltas of each group, in the sorted order of the group ids; a group's deltas are summed in sorted order."""
    members = {}
    for delta, group in zip(deltas, groups, strict=True):
        members.setdefault(group, []).append(delta)
    return [(sum(sorted(members[group])), len(members[group])) for group in sorted(members)]


def pooled_mean(totals: list, draw) -> float:
    """The mean of the deltas of the groups at the positions `draw` of `totals`, a group drawn twice counting twice."""
    drawn = [totals[i] for i in draw]
    return sum(total for total, _ in drawn) / sum(count for _, count in drawn)


def cluster_interval(deltas: list, groups: list, *, seed: int, resamples: int = RESAMPLES, level: float = LEVEL) -> dict:
    """{lower, upper, reason}: the percentile bounds of the pooled means of `resamples` draws of G groups out of G with replacement.

    `groups` gives the group of each delta. A draw takes whole groups: the mean of the drawn groups' deltas weighs each Case once, so a
    group weighs its number of Cases. Fewer than two groups give `too_few_units`.
    """
    totals = group_totals(deltas, groups)
    count = len(totals)
    if count < 2:
        return {"lower": None, "upper": None, "reason": TOO_FEW_UNITS}
    if all(delta == deltas[0] for delta in deltas):
        return {"lower": deltas[0], "upper": deltas[0], "reason": None}
    generator = random.Random(seed)
    return percentile_bounds([pooled_mean(totals, block_indices(count, 1, generator)) for _ in range(resamples)], level)


def record(resampling: dict | None, deltas: list | None, *, groups: list | None = None, missing: str = DELTA_WITHHELD) -> dict:
    """The `interval` key of a Comparison: over `deltas` (one per unit, in order) when the Study declares `resampling` and they exist.

    With no declaration, `unit`, `seed` and `units` are null and `reason` is `resampling_not_declared`. With `deltas` None, the bounds
    are null and `reason` is `missing`: `delta_withheld`, or `series_not_contiguous` for a block declaration over a series with gaps.
    Under the unit `group`, `groups` gives the group of each Case in the population, in delta order when deltas exist. `units` counts
    the groups and `cases` the Cases, even when the delta is withheld. For other units, `cases` is null and `units` needs deltas.
    """
    base = {"level": LEVEL, "method": METHOD, "variant": None, "block_length": None, "resamples": RESAMPLES, "cases": None}
    if resampling is None:
        return {**base, "lower": None, "upper": None, "unit": None, "units": None, "seed": None, "reason": NOT_DECLARED}
    block = resampling.get("block")
    declared = {"unit": resampling["unit"], "seed": resampling["seed"]}
    if block is not None:
        declared.update(variant=block["variant"], block_length=block["length"])
    if resampling["unit"] == GROUP:
        declared.update(units=len(set(groups)), cases=len(groups))
        if deltas is not None:
            return {**base, **declared, **cluster_interval(deltas, groups, seed=resampling["seed"])}
    if deltas is None:
        return {**base, "units": None, **declared, "lower": None, "upper": None, "reason": missing}
    length = 1 if block is None else block["length"]
    return {**base, **declared, "units": len(deltas), **_interval(deltas, length, resampling["seed"], RESAMPLES, LEVEL)}
