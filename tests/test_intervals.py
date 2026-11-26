"""The paired resampling interval of the core (`hypotrail.core.intervals`): one function, a fixed seed, the quantile rule of `figures`."""

import random

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
