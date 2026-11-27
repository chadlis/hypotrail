"""The paired resampling interval of the core (`hypotrail.core.intervals`): one function, a fixed seed, the quantile rule of `figures`."""

import random

import pytest

from hypotrail.core import intervals

# 100 deltas spread over [-0.45, 0.55), one per unit.
DELTAS = [((i * 7919) % 101) / 101 - 0.45 for i in range(100)]
SEED = 12345


def twelve(value: float) -> str:
    return f"{value:.12g}"


def test_on_100_deltas_a_fixed_seed_and_2000_resamples_the_bounds_are_pinned_around_the_mean_and_the_same_on_a_second_call():
    first = intervals.percentile_interval(DELTAS, seed=SEED, resamples=2000, level=0.95)
    assert (twelve(first["lower"]), twelve(first["upper"]), first["reason"]) == ("-0.014853960396", "0.0979282178218", None)
    assert first["lower"] <= sum(DELTAS) / len(DELTAS) <= first["upper"]
    assert intervals.percentile_interval(DELTAS, seed=SEED, resamples=2000, level=0.95) == first


def test_the_defaults_are_2000_resamples_at_level_0_95():
    assert intervals.percentile_interval(DELTAS, seed=SEED) == intervals.percentile_interval(DELTAS, seed=SEED, resamples=2000, level=0.95)
    assert (intervals.RESAMPLES, intervals.LEVEL, intervals.METHOD) == (2000, 0.95, "percentile_bootstrap")


def test_fewer_than_two_units_give_no_bounds_with_too_few_units():
    for deltas in ([], [0.25]):
        assert intervals.percentile_interval(deltas, seed=SEED) == {"lower": None, "upper": None, "reason": "too_few_units"}


def test_units_whose_deltas_are_all_equal_give_bounds_equal_to_that_value():
    assert intervals.percentile_interval([0.1] * 30, seed=SEED) == {"lower": 0.1, "upper": 0.1, "reason": None}


# --- circular blocks over ordered deltas ----------------------------------------------------------------------------------------

# 182 ordered deltas whose level moves by alternate weeks.
SERIES = [((i * 7919) % 101) / 101 - 0.45 + (0.3 if (i // 7) % 2 else 0) for i in range(182)]


def test_on_an_ordered_list_a_fixed_seed_and_blocks_of_7_the_bounds_are_pinned_and_blocks_of_1_give_the_independent_bounds():
    blocks = intervals.circular_block_interval(SERIES, length=7, seed=SEED, resamples=2000, level=0.95)
    assert (twelve(blocks["lower"]), twelve(blocks["upper"]), blocks["reason"]) == ("0.147984985312", "0.231146094005", None)
    assert intervals.circular_block_interval(SERIES, length=1, seed=SEED, resamples=2000, level=0.95) == intervals.percentile_interval(
        SERIES, seed=SEED, resamples=2000, level=0.95
    )


def test_each_resample_is_runs_of_length_consecutive_positions_modulo_n_the_last_cut_to_reach_n():

    generator = random.Random(SEED)
    for n, length in ((182, 7), (184, 7), (10, 3)):
        for _ in range(20):
            indices = intervals.block_indices(n, length, generator)
            assert len(indices) == n and all(0 <= i < n for i in indices)
            starts = range(0, n, length)
            for start in starts:  # each block, read from its start, is consecutive modulo n
                block = indices[start : start + length]
                assert block == [(block[0] + k) % n for k in range(len(block))]
            assert [len(indices[start : start + length]) for start in starts][-1] == n - length * (len(starts) - 1)


def test_a_block_crosses_from_the_last_position_to_the_first():

    generator = random.Random(SEED)
    resamples = [intervals.block_indices(10, 4, generator) for _ in range(200)]
    assert any(a == 9 and b == 0 for indices in resamples for a, b in zip(indices, indices[1:]))


# --- the cluster interval over groups of Cases ----------------------------------------------------------------------------------

# 30 per-Case deltas in 10 groups of 3, the group effect shared by the Cases of a group.
EQUAL = [round(((g * 37) % 11) / 11 - 0.4 + ((c * 13) % 5) / 25, 6) for g in range(10) for c in range(3)]
EQUAL_GROUPS = [f"g{g:02d}" for g in range(10) for _ in range(3)]
# 12 per-Case deltas in 4 groups of 6, 3, 2 and 1 Cases.
UNEQUAL = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, -0.25, 0.0, 0.25, 1.0, 0.75, -0.5]
UNEQUAL_GROUPS = ["a"] * 6 + ["b"] * 3 + ["c"] * 2 + ["d"]


def shuffled(deltas, groups, seed=7):
    pairs = list(zip(deltas, groups))
    random.Random(seed).shuffle(pairs)
    return [d for d, _ in pairs], [g for _, g in pairs]


def bounds_of(deltas, groups, seed=SEED):
    return intervals.cluster_interval(deltas, groups, seed=seed)


def case_weighted(deltas, groups):
    totals = intervals.group_totals(deltas, groups)
    return intervals.pooled_mean(totals, range(len(totals)))


def check_equal_size(deltas, groups):
    result = bounds_of(deltas, groups)
    assert result["reason"] is None and result["lower"] < sum(deltas) / len(deltas) < result["upper"]
    # Groups of one Case each draw exactly as the Case interval does over the same deltas.
    assert intervals.cluster_interval(deltas, [f"c{i:02d}" for i in range(len(deltas))], seed=SEED) == intervals.percentile_interval(deltas, seed=SEED)


def check_unequal_size(deltas, groups):
    mean_of_group_means = sum(sum(d for d, g in zip(deltas, groups) if g == name) / groups.count(name) for name in set(groups)) / len(set(groups))
    assert case_weighted(deltas, groups) == pytest.approx(sum(deltas) / len(deltas))
    assert case_weighted(deltas, groups) != pytest.approx(mean_of_group_means)
    result = bounds_of(deltas, groups)
    assert result["reason"] is None and result["lower"] < sum(deltas) / len(deltas) < result["upper"]


def check_one_group(deltas, groups):
    assert bounds_of(deltas, groups) == {"lower": None, "upper": None, "reason": "too_few_units"}


def check_all_equal(deltas, groups):
    assert bounds_of(deltas, groups) == {"lower": deltas[0], "upper": deltas[0], "reason": None}


def check_another_order(deltas, groups):
    assert bounds_of(*shuffled(deltas, groups)) == bounds_of(deltas, groups)
    assert bounds_of(*shuffled(UNEQUAL, UNEQUAL_GROUPS)) == bounds_of(UNEQUAL, UNEQUAL_GROUPS)


def check_same_seed(deltas, groups):
    assert bounds_of(deltas, groups) == bounds_of(deltas, groups)
    assert bounds_of(deltas, groups, seed=SEED + 1) != bounds_of(deltas, groups)


CLUSTER_ROWS = {
    "groups of equal size": (EQUAL, EQUAL_GROUPS, check_equal_size),
    "groups of unequal size: the pooled mean is the Case-weighted delta": (UNEQUAL, UNEQUAL_GROUPS, check_unequal_size),
    "one group: too_few_units": ([0.25, -0.5, 1.0], ["only"] * 3, check_one_group),
    "all deltas equal: the bounds are the delta": ([0.1] * 9, [f"g{i // 3}" for i in range(9)], check_all_equal),
    "the same deltas in another order: the same bounds": (EQUAL, EQUAL_GROUPS, check_another_order),
    "the same seed twice: the same bounds": (EQUAL, EQUAL_GROUPS, check_same_seed),
}


@pytest.mark.parametrize(("deltas", "groups", "check"), CLUSTER_ROWS.values(), ids=CLUSTER_ROWS.keys())
def test_the_cluster_interval_draws_whole_groups_and_pools_their_case_deltas(deltas, groups, check):
    check(deltas, groups)


def test_a_record_under_the_group_unit_counts_groups_in_units_and_cases_in_cases_and_the_other_units_hold_cases_null():
    grouped = intervals.record({"unit": "group", "seed": SEED}, EQUAL, groups=EQUAL_GROUPS)
    assert (grouped["unit"], grouped["units"], grouped["cases"], grouped["seed"]) == ("group", 10, 30, SEED)
    assert (grouped["lower"], grouped["upper"]) == (bounds_of(EQUAL, EQUAL_GROUPS)["lower"], bounds_of(EQUAL, EQUAL_GROUPS)["upper"])
    one = intervals.record({"unit": "group", "seed": SEED}, [0.1, 0.2], groups=["g", "g"])
    assert (one["units"], one["cases"], one["lower"], one["reason"]) == (1, 2, None, "too_few_units")
    withheld = intervals.record({"unit": "group", "seed": SEED}, None)
    assert (withheld["units"], withheld["cases"], withheld["reason"]) == (None, None, "delta_withheld")
    assert intervals.record({"unit": "case", "seed": SEED}, EQUAL)["cases"] is None
    assert intervals.record(None, EQUAL)["cases"] is None
