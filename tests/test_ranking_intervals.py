"""Paired entity resampling on synthetic ranking panels (D-233)."""

import math
import random
from collections import defaultdict
from decimal import Decimal
from fractions import Fraction

import pytest

from hypotrail.core import intervals
from hypotrail.core.ranking_intervals import RankingPair, paired_interval


FIRST = "2025-01-01"
SECOND = "2025-02-01"
THIRD = "2025-03-01"


def pair(entity, day, label, control, candidate):
    return RankingPair(f"{entity}@{day}", entity, day, label, control, candidate)


def _oracle(rows, seed, resamples):
    """Expand each drawn entity into its Items and rank every resulting date afresh."""
    by_entity = defaultdict(list)
    for row in rows:
        by_entity[row.entity_id].append(row)
    entities = sorted(by_entity)
    original_dates = {row.as_of for row in rows}
    generator = random.Random(seed)
    omitted_dates = 0
    deltas = []
    for _ in range(resamples):
        drawn_dates = {day: [] for day in original_dates}
        for _ in entities:
            entity = entities[math.floor(len(entities) * generator.random())]
            for row in by_entity[entity]:
                drawn_dates[row.as_of].append(row)

        date_deltas = []
        for rows_on_date in drawn_dates.values():
            positives = sum(row.label for row in rows_on_date)
            if not positives:
                omitted_dates += 1
                continue
            top = math.ceil(Fraction(len(rows_on_date), 10))
            control = sorted(rows_on_date, key=lambda row: (-row.control_score, row.item_id))[:top]
            candidate = sorted(rows_on_date, key=lambda row: (-row.candidate_score, row.item_id))[:top]
            date_deltas.append(Fraction(sum(row.label for row in candidate) - sum(row.label for row in control), positives))
        if date_deltas:
            deltas.append(sum(date_deltas) / len(date_deltas))
    return sorted(deltas), omitted_dates


def _quantile(values, fraction):
    position = fraction * (len(values) - 1)
    left, right = math.floor(position), math.ceil(position)
    return float(values[left] + (values[right] - values[left]) * (position - left))


def test_paired_rankings_match_explicit_entity_copies_for_a_seeded_irregular_panel():
    first_date = [pair(f"e{i:02}", FIRST, i == 1, 5, (i + 1) % 4) for i in range(13)]
    second_date = [pair(f"e{i:02}", SECOND, i in (1, 6), i % 3, 5) for i in range(0, 15, 2)]
    rows = first_date + second_date + [pair("e16", THIRD, False, 0, 0)]
    deltas, omitted = _oracle(rows, seed=38, resamples=2000)
    assert 0 < len(deltas) < 2000
    assert 2000 < omitted < 6000

    expected = {
        "lower": pytest.approx(_quantile(deltas, Fraction(1, 40))),
        "upper": pytest.approx(_quantile(deltas, Fraction(39, 40))),
        "reason": None,
        "units": 15,
        "usable_resamples": len(deltas),
        "omitted_dates": omitted,
    }
    assert paired_interval(rows, seed=38) == expected
    random.Random(4).shuffle(rows)
    assert paired_interval(rows, seed=38) == expected


def test_identical_rankings_share_every_draw_even_when_a_date_or_draw_is_undefined():
    rows = [pair("a", FIRST, True, 1, 1), pair("b", FIRST, False, 2, 2), pair("b", SECOND, False, 2, 2)]
    deltas, omitted = _oracle(rows, seed=13, resamples=9)
    assert 0 < len(deltas) < 9
    assert paired_interval(rows, seed=13, resamples=9) == {
        "lower": 0,
        "upper": 0,
        "reason": None,
        "units": 2,
        "usable_resamples": len(deltas),
        "omitted_dates": omitted,
    }


def test_all_dates_without_positives_leave_every_draw_unusable():
    rows = [pair("a", FIRST, False, 8, 2), pair("b", SECOND, False, 1, 6)]
    assert paired_interval(rows, seed=42) == {
        "lower": None,
        "upper": None,
        "reason": "no_usable_resamples",
        "units": 2,
        "usable_resamples": 0,
        "omitted_dates": 4000,
    }


def _one_draw(rows, drawn_indexes, monkeypatch):
    def draw(size, length, _generator):
        assert (size, length) == (len(drawn_indexes), 1)
        return drawn_indexes

    monkeypatch.setattr(intervals, "block_indices", draw)
    return paired_interval(rows, seed=42, resamples=1)


def test_the_same_positive_entity_drawn_twice_counts_twice_in_the_date_denominator(monkeypatch):
    rows = [pair("a", FIRST, True, 1, 3), pair("b", FIRST, True, 1, 1), pair("c", FIRST, False, 3, 1)]
    result = _one_draw(rows, [0, 0, 2], monkeypatch)
    assert (result["lower"], result["upper"]) == (0.5, 0.5)


def test_tied_scores_rank_by_the_original_item_id(monkeypatch):
    rows = [pair("a", FIRST, True, 7, 4), pair("b", FIRST, False, 7, 9)]
    result = _one_draw(rows, [1, 0], monkeypatch)
    assert (result["lower"], result["upper"]) == (-1, -1)


def test_precision_beyond_the_decimal_context_does_not_create_an_item_id_tie(monkeypatch):
    first = Decimal("0.123456789012345678901234567801")
    second = Decimal("0.123456789012345678901234567802")
    rows = [pair("a", FIRST, True, first, second), pair("b", FIRST, False, second, first)]
    result = _one_draw(rows, [1, 0], monkeypatch)
    assert (result["lower"], result["upper"]) == (1, 1)


def test_top_tenth_uses_the_ceiling_of_the_resampled_date_size(monkeypatch):
    rows = [pair("a", FIRST, False, 3, 3), pair("b", FIRST, True, 2, 1), pair("c", FIRST, False, 1, 2)]
    rows += [pair(f"d{i}", FIRST, False, 0, 0) for i in range(8)]
    result = _one_draw(rows, list(range(len(rows))), monkeypatch)
    assert (result["lower"], result["upper"]) == (-1, -1)


def test_duplicate_items_cannot_be_mistaken_for_resampled_copies():
    first = pair("a", FIRST, True, 8, 2)
    with pytest.raises(ValueError, match="one Item per entity and date"):
        paired_interval([first, first], seed=42)
