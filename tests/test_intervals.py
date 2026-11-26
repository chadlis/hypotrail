"""The paired resampling interval of the core (`hypotrail.core.intervals`): one function, a fixed seed, the quantile rule of `figures`."""

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
