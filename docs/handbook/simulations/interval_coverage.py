"""The coverage of the paired interval of `hypotrail.core.intervals` for independent units, at the sizes the Workloads use.

A development script, never run by a command of Hypotrail. For each size it simulates `replications` paired data sets whose true delta is
known, computes the interval each would get (the core's function, the level and the count of resamples of the core), and counts the share
of intervals that hold the true delta. It also times one interval of 2,000 resamples at 3,000 units on this machine.

The data-generating settings:

- Cases (`unit` "case"): each Case draws a Control success rate p uniform on [0.2, 0.8], and the Candidate's rate is p + 0.1, so the true
  delta over the population of Cases is 0.1. Each Repeat of a Case is one paired Episode: one uniform number u is drawn and the Control
  succeeds when u < p, the Candidate when u < p + 0.1. The within-Case dependence: the Repeats of a Case share its rates, and the two sides
  of an Episode share u. A Case's delta is the mean over its Repeats of Candidate minus Control, as `paired_deltas.csv` holds it.
- Items (`unit` "item"): each Item's delta is an exponential variable of mean 1 minus 0.8, independent of the others: a skewed delta
  whose true mean is 0.2.

Run from the repository root: `uv run python docs/handbook/simulations/interval_coverage.py` writes `interval-coverage.json` beside this
file; `--replications N --out PATH` runs a smaller count elsewhere.
"""

import argparse
import json
import platform
import random
import subprocess
import time
from pathlib import Path

from hypotrail.core import intervals

HERE = Path(__file__).resolve().parent
KEPT = HERE / "interval-coverage.json"
SEED = 238
# (unit, units, repeats, replications of the kept run)
SIZES = [("case", 12, 1, 1000), ("case", 12, 3, 1000), ("case", 100, 1, 1000), ("case", 100, 3, 1000), ("item", 3000, None, 300)]
CASE_RATE = (0.2, 0.8)
CASE_EFFECT = 0.1
ITEM_SHIFT = 0.8


def case_deltas(generator: random.Random, cases: int, repeats: int) -> list:
    deltas = []
    for _ in range(cases):
        rate = generator.uniform(*CASE_RATE)
        pairs = [generator.random() for _ in range(repeats)]
        deltas.append(sum(float(u < rate + CASE_EFFECT) - float(u < rate) for u in pairs) / repeats)
    return deltas


def item_deltas(generator: random.Random, items: int) -> list:
    return [generator.expovariate(1.0) - ITEM_SHIFT for _ in range(items)]


def coverage(unit: str, units: int, repeats, replications: int, generator: random.Random) -> dict:
    truth = CASE_EFFECT if unit == "case" else 1.0 - ITEM_SHIFT
    held = 0
    for _ in range(replications):
        deltas = case_deltas(generator, units, repeats) if unit == "case" else item_deltas(generator, units)
        bounds = intervals.percentile_interval(deltas, seed=generator.randrange(2**31))
        held += bounds["lower"] <= truth <= bounds["upper"]
    return {"unit": unit, "units": units, "repeats": repeats, "replications": replications, "true_delta": truth, "coverage": held / replications}


def timing() -> dict:
    deltas = item_deltas(random.Random(SEED), 3000)
    start = time.perf_counter()
    intervals.percentile_interval(deltas, seed=SEED)
    return {"units": 3000, "resamples": intervals.RESAMPLES, "seconds": round(time.perf_counter() - start, 2), "python": platform.python_version()}


def commit() -> str:
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=HERE).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, cwd=HERE).stdout.strip()
    return head + ("-dirty" if dirty else "")


def run(replications: int | None) -> dict:
    generator = random.Random(SEED)
    return {
        "level": intervals.LEVEL,
        "resamples": intervals.RESAMPLES,
        "method": intervals.METHOD,
        "seed": SEED,
        "commit": commit(),
        "settings": {
            "case": f"Control rate uniform on [{CASE_RATE[0]}, {CASE_RATE[1]}], Candidate rate + {CASE_EFFECT}; the Repeats of a Case share "
            "its rates and the two sides of an Episode share one uniform draw",
            "item": f"independent Item deltas, exponential of mean 1 minus {ITEM_SHIFT}",
        },
        "sizes": [coverage(unit, units, repeats, replications or count, generator) for unit, units, repeats, count in SIZES],
        "timing": timing(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--replications", type=int, help="the same count at every size, instead of the kept run's counts")
    parser.add_argument("--out", type=Path, default=KEPT)
    args = parser.parse_args()
    args.out.write_text(json.dumps(run(args.replications), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
