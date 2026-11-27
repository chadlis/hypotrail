"""The intervals of the core against two development-only oracles, which Hypotrail never calls at runtime: Inspect's clustered bootstrap
for the Case interval and for the group interval, and `arch`'s circular block bootstrap for the interval over days.

Inspect's `ci(method="bootstrap", cluster=...)` resamples whole clusters and takes the mean of the pooled values, which weighs a cluster by
its number of samples; with the same number of Repeats in every Case that mean is the mean of the per-Case deltas the core resamples.
"""

import math
import random

import pytest

np = pytest.importorskip("numpy", reason="the oracles need NumPy (the `ml` or the `agent` extra)")

from hypotrail.core import intervals  # noqa: E402

RESAMPLES = 2000
LEVEL = 0.95


def paired_set(cases: int, repeats: int, seed: int) -> dict:
    """{case_id: [Candidate minus Control, one per Repeat]}: binary outcomes, each Case with its own success rate on each side."""
    generator = random.Random(seed)
    episodes = {}
    for number in range(cases):
        control_rate = generator.random()
        candidate_rate = min(1.0, control_rate + generator.uniform(-0.1, 0.3))
        episodes[f"C{number:03d}"] = [
            float(generator.random() < candidate_rate) - float(generator.random() < control_rate) for _ in range(repeats)
        ]
    return episodes


def inspect_bounds(episodes: dict, numpy_seed: int) -> tuple:
    inspect_scorer = pytest.importorskip("inspect_ai.scorer", reason="the oracle needs the `agent` extra (Inspect)")
    scores = [
        inspect_scorer.SampleScore(score=inspect_scorer.Score(value=value), sample_id=f"{case_id}#{repeat}", sample_metadata={"case": case_id})
        for case_id, values in episodes.items()
        for repeat, value in enumerate(values)
    ]
    np.random.seed(numpy_seed)
    result = inspect_scorer.ci(level=LEVEL, method="bootstrap", num_samples=RESAMPLES, cluster="case")(scores)
    return result["lower"], result["upper"]


def tolerance(case_deltas: list) -> float:
    """Four standard errors of the difference of two independent percentile estimates, each from `RESAMPLES` resampled means.

    The resampled means spread with the standard deviation of the per-Case deltas over the square root of the number of Cases; the
    standard error of a percentile at the tail p is sqrt(p (1 - p) / B) / phi(z) times that spread, phi the normal density at z.
    """
    count = len(case_deltas)
    mean = sum(case_deltas) / count
    spread = math.sqrt(sum((d - mean) ** 2 for d in case_deltas) / count) / math.sqrt(count)
    tail = (1 - LEVEL) / 2
    z = 1.959963984540054
    density = math.exp(-z * z / 2) / math.sqrt(2 * math.pi)
    return 4 * math.sqrt(2) * math.sqrt(tail * (1 - tail) / RESAMPLES) / density * spread


@pytest.mark.parametrize(("cases", "repeats", "seed"), [(100, 3, 1), (40, 5, 2), (12, 3, 3)], ids=["100 Cases x 3", "40 Cases x 5", "12 Cases x 3"])
def test_the_case_interval_agrees_with_inspects_clustered_bootstrap_within_the_resampling_error(cases, repeats, seed):
    episodes = paired_set(cases, repeats, seed)
    case_deltas = [sum(values) / len(values) for values in episodes.values()]
    ours = intervals.percentile_interval(case_deltas, seed=seed, resamples=RESAMPLES, level=LEVEL)
    lower, upper = inspect_bounds(episodes, numpy_seed=seed)
    # Not equal: Inspect draws from NumPy's global generator and the core from `random.Random`, so the two sets of resampled means differ.
    allowed = tolerance(case_deltas)
    assert abs(ours["lower"] - lower) < allowed and abs(ours["upper"] - upper) < allowed, (ours, (lower, upper), allowed)


# --- the group interval against Inspect's clustered bootstrap over groups --------------------------------------------------------


def grouped_set(groups: int, size: int, repeats: int, seed: int) -> dict:
    """{(group, case_id): [Candidate minus Control, one per Repeat]}: binary outcomes, the Cases of a group sharing its success rates."""
    generator = random.Random(seed)
    episodes = {}
    for group in range(groups):
        control_rate = generator.uniform(0.1, 0.9)
        candidate_rate = min(1.0, control_rate + generator.uniform(-0.1, 0.3))
        for case in range(size):
            shift = generator.uniform(-0.05, 0.05)
            episodes[(f"G{group:02d}", f"G{group:02d}C{case}")] = [
                float(generator.random() < min(1.0, candidate_rate + shift)) - float(generator.random() < max(0.0, control_rate + shift)) for _ in range(repeats)
            ]
    return episodes


def inspect_group_bounds(episodes: dict, numpy_seed: int) -> tuple:
    inspect_scorer = pytest.importorskip("inspect_ai.scorer", reason="the oracle needs the `agent` extra (Inspect)")
    scores = [
        inspect_scorer.SampleScore(score=inspect_scorer.Score(value=value), sample_id=f"{case_id}#{repeat}", sample_metadata={"group": group})
        for (group, case_id), values in episodes.items()
        for repeat, value in enumerate(values)
    ]
    np.random.seed(numpy_seed)
    result = inspect_scorer.ci(level=LEVEL, method="bootstrap", num_samples=RESAMPLES, cluster="group")(scores)
    return result["lower"], result["upper"]


@pytest.mark.parametrize(
    ("groups", "size", "repeats", "seed"),
    [(10, 3, 1, 7), (10, 3, 3, 8), (40, 3, 1, 9)],
    ids=["10 groups of 3 x 1", "10 groups of 3 x 3", "40 groups of 3 x 1"],
)
def test_the_group_interval_agrees_with_inspects_clustered_bootstrap_over_groups_within_the_resampling_error(groups, size, repeats, seed):
    episodes = grouped_set(groups, size, repeats, seed)
    case_deltas = [sum(values) / len(values) for values in episodes.values()]
    ours = intervals.cluster_interval(case_deltas, [group for group, _ in episodes], seed=seed, resamples=RESAMPLES, level=LEVEL)
    lower, upper = inspect_group_bounds(episodes, numpy_seed=seed)
    # The resampled unit is the group: the spread is the one of the group means, as the Case oracle's is the one of the Case deltas.
    group_means = [sum(case_deltas[i * size : (i + 1) * size]) / size for i in range(groups)]
    allowed = tolerance(group_means)
    assert abs(ours["lower"] - lower) < allowed and abs(ours["upper"] - upper) < allowed, (ours, (lower, upper), allowed)


# --- the circular block interval against arch's CircularBlockBootstrap ------------------------------------------------------------


def ordered_series(kind: str, seed: int, days: int = 182) -> list:
    """An ordered series of daily deltas: independent noise, a first-order autoregression, or a weekly pattern plus noise."""
    generator = random.Random(seed)
    if kind == "independent":
        return [generator.gauss(0.3, 1.0) for _ in range(days)]
    if kind == "weekly":
        return [math.sin(2 * math.pi * t / 7) + generator.gauss(0.3, 1.0) for t in range(days)]
    value, series = 0.0, []
    for _ in range(days):
        value = 0.6 * value + generator.gauss(0.0, 1.0)
        series.append(value + 0.3)
    return series


@pytest.mark.parametrize(("kind", "seed"), [("independent", 4), ("autoregressive", 5), ("weekly", 6)])
def test_the_circular_block_interval_agrees_with_arch_within_the_resampling_error(kind, seed):
    bootstrap = pytest.importorskip("arch.bootstrap", reason="the oracle needs `arch`, in the `dev` group")
    series = ordered_series(kind, seed)
    ours = intervals.circular_block_interval(series, length=7, seed=seed, resamples=RESAMPLES, level=LEVEL)
    resampled = bootstrap.CircularBlockBootstrap(7, np.asarray(series), seed=np.random.default_rng(seed)).apply(np.mean, RESAMPLES).ravel()
    tail = (1 - LEVEL) / 2
    lower, upper = float(np.quantile(resampled, tail)), float(np.quantile(resampled, 1 - tail))
    # Not equal: arch draws its start positions from a NumPy generator and the core from `random.Random`.
    spread = float(np.std(resampled))
    z = 1.959963984540054
    density = math.exp(-z * z / 2) / math.sqrt(2 * math.pi)
    allowed = 4 * math.sqrt(2) * math.sqrt(tail * (1 - tail) / RESAMPLES) / density * spread
    assert abs(ours["lower"] - lower) < allowed and abs(ours["upper"] - upper) < allowed, (ours, (lower, upper), allowed)
