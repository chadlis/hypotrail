"""The Case interval of the core against Inspect's clustered bootstrap, a development-only oracle (Hypotrail never calls it at runtime).

Inspect's `ci(method="bootstrap", cluster=...)` resamples whole clusters and takes the mean of the pooled values, which weighs a cluster by
its number of samples; with the same number of Repeats in every Case that mean is the mean of the per-Case deltas the core resamples.
"""

import math
import random

import pytest

inspect_scorer = pytest.importorskip("inspect_ai.scorer", reason="the oracle needs the `agent` extra (Inspect)")
np = pytest.importorskip("numpy", reason="the oracle needs the `agent` extra (Inspect brings NumPy)")

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
