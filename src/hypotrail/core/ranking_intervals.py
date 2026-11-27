"""Paired bootstrap of the ranking Metric over whole entity histories (D-233)."""

import random
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import NamedTuple

from hypotrail.core import intervals


class RankingPair(NamedTuple):
    """The Reference and the two aligned scores for one Item."""

    item_id: str
    entity_id: str
    as_of: str
    label: bool
    control_score: Decimal
    candidate_score: Decimal


class _DateRanking(NamedTuple):
    entities: tuple[int, ...]
    positives: tuple[int, ...]
    control: tuple[tuple[int, bool], ...]
    candidate: tuple[tuple[int, bool], ...]


def _rank_dates(rows: list[RankingPair], entities: dict[str, int]) -> list[_DateRanking]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.as_of].append(row)

    rankings = []
    for day in sorted(grouped):
        items = sorted(grouped[day], key=lambda row: row.item_id)
        indexes = tuple(entities[row.entity_id] for row in items)
        if len(set(indexes)) != len(items):
            raise ValueError("A ranking Comparison requires one Item per entity and date")
        # Stable sorts preserve the Item ID tie break and compare Decimal scores at full precision.
        # Removing or repeating entities leaves the relative ranking intact.
        control = sorted(items, key=lambda row: row.control_score, reverse=True)
        candidate = sorted(items, key=lambda row: row.candidate_score, reverse=True)
        rankings.append(
            _DateRanking(
                indexes,
                tuple(entities[row.entity_id] for row in items if row.label),
                tuple((entities[row.entity_id], row.label) for row in control),
                tuple((entities[row.entity_id], row.label) for row in candidate),
            )
        )
    return rankings


def _hits_in_top(order: tuple[tuple[int, bool], ...], multiplicity: list[int], remaining: int) -> int:
    hits = 0
    for entity, positive in order:
        copies = multiplicity[entity]
        if copies >= remaining:
            return hits + remaining * positive
        hits += copies * positive
        remaining -= copies
    return hits


def _draw_delta(rankings: list[_DateRanking], multiplicity: list[int]) -> tuple[float | None, int]:
    total, dates = 0.0, 0
    for ranking in rankings:
        positives = sum(multiplicity[entity] for entity in ranking.positives)
        if positives == 0:
            continue
        count = sum(multiplicity[entity] for entity in ranking.entities)
        # The ranking Track keeps the ceiling of exactly one tenth of the drawn Items.
        top = (count + 9) // 10
        control_hits = _hits_in_top(ranking.control, multiplicity, top)
        candidate_hits = _hits_in_top(ranking.candidate, multiplicity, top)
        total += (candidate_hits - control_hits) / positives
        dates += 1
    return (total / dates if dates else None), len(rankings) - dates


def paired_interval(
    rows: Iterable[RankingPair], *, seed: int, resamples: int = intervals.RESAMPLES, level: float = intervals.LEVEL,
) -> dict:
    """Bounds of Candidate minus Control recall from shared draws of whole entities.

    The date count totals omissions across all draws over the original date set.
    A draw contributes one mean over its dates with positives, if it has any.
    """
    rows = list(rows)
    entities = {entity: i for i, entity in enumerate(sorted({row.entity_id for row in rows}))}
    rankings = _rank_dates(rows, entities)
    generator = random.Random(seed)
    estimates = []
    omitted_dates = 0
    for _ in range(resamples):
        multiplicity = [0] * len(entities)
        for entity in intervals.block_indices(len(entities), 1, generator):
            multiplicity[entity] += 1
        estimate, omitted = _draw_delta(rankings, multiplicity)
        omitted_dates += omitted
        if estimate is not None:
            estimates.append(estimate)

    bounds = intervals.percentile_bounds(estimates, level) if estimates else {
        "lower": None, "upper": None, "reason": "no_usable_resamples",
    }
    return {**bounds, "units": len(entities), "usable_resamples": len(estimates), "omitted_dates": omitted_dates}


def record(rows: Iterable[RankingPair], population_sha256: str) -> dict:
    """A ranking Comparison's interval on the shared population, with a reproducible seed."""
    seed = int(population_sha256[:8], 16)
    return {
        "level": intervals.LEVEL,
        "method": intervals.METHOD,
        "unit": intervals.ENTITY,
        "variant": None,
        "block_length": None,
        "resamples": intervals.RESAMPLES,
        "seed": seed,
        "cases": None,
        **paired_interval(rows, seed=seed),
    }
