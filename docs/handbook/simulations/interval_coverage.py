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
- Days (`unit` "item" by circular blocks of 7, the length the Bike Workload declares): a series of daily deltas of true mean 0, at the
  182 and 184 days of Bike's `dev` and `public_check`, under four dependences: independent standard normal noise; a first-order
  autoregression x[t] = phi x[t-1] + e[t] with phi 0.5 and 0.9, started from its stationary distribution; and a weekly pattern,
  sin(2 pi (t + phase) / 7) with a phase drawn per series, plus standard normal noise.

Unless `--no-block-length` is given, it also records the length `arch.bootstrap.optimal_block_length` gives for the circular variant on
the target of Bike's `train` Partition, beside the declared length, as agreement or disagreement; it never changes the declared length.

Run from the repository root: `uv run python docs/handbook/simulations/interval_coverage.py` writes `interval-coverage.json` beside this
file; `--replications N --out PATH` runs a smaller count elsewhere.
"""

import argparse
import csv
import datetime
import json
import math
import platform
import random
import subprocess
import time
from pathlib import Path

from hypotrail.core import intervals

HERE = Path(__file__).resolve().parent
KEPT = HERE / "interval-coverage.json"
SEED = 238
ROOT = HERE.parent.parent.parent
# (unit, units, repeats, replications of the kept run)
SIZES = [("case", 12, 1, 1000), ("case", 12, 3, 1000), ("case", 100, 1, 1000), ("case", 100, 3, 1000), ("item", 3000, None, 300)]
BLOCK_LENGTH = 7
DEPENDENCES = ["independent", "ar1_0.5", "ar1_0.9", "weekly"]
# (days, dependence, replications of the kept run)
BLOCK_SIZES = [(days, dependence, 1000) for days in (182, 184) for dependence in DEPENDENCES]
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


def day_deltas(generator: random.Random, days: int, dependence: str) -> list:
    if dependence == "independent":
        return [generator.gauss(0.0, 1.0) for _ in range(days)]
    if dependence == "weekly":
        phase = generator.randrange(BLOCK_LENGTH)
        return [math.sin(2 * math.pi * (t + phase) / BLOCK_LENGTH) + generator.gauss(0.0, 1.0) for t in range(days)]
    phi = float(dependence.split("_")[1])
    value = generator.gauss(0.0, 1.0 / math.sqrt(1 - phi * phi))
    series = []
    for _ in range(days):
        series.append(value)
        value = phi * value + generator.gauss(0.0, 1.0)
    return series


def block_coverage(days: int, dependence: str, replications: int, generator: random.Random) -> dict:
    held = 0
    for _ in range(replications):
        deltas = day_deltas(generator, days, dependence)
        bounds = intervals.circular_block_interval(deltas, length=BLOCK_LENGTH, seed=generator.randrange(2**31))
        held += bounds["lower"] <= 0.0 <= bounds["upper"]
    return {
        "unit": "item",
        "units": days,
        "variant": intervals.CIRCULAR,
        "block_length": BLOCK_LENGTH,
        "dependence": dependence,
        "replications": replications,
        "true_delta": 0.0,
        "coverage": held / replications,
    }


def optimal_block_length() -> dict:
    """The circular length arch advises on the target of Bike's `train` Partition (a development dependency, the `dev` group)."""
    from arch.bootstrap import optimal_block_length as advise

    workload = json.loads((ROOT / "examples" / "bike_day" / "workload.json").read_text(encoding="utf-8"))
    first, last = workload["partitions"]["train"]
    with (ROOT / "examples" / "bike_day" / workload["data_file"]).open(encoding="utf-8", newline="") as handle:
        target = [float(row[workload["target_column"]]) for row in csv.DictReader(handle) if first <= row[workload["date_column"]] <= last]
    advised = float(advise(target)["circular"].iloc[0])
    declared = workload["resampling"]["block"]["length"]
    return {
        "partition": "train",
        "days": len(target),
        "circular": advised,
        "declared": declared,
        "agreement": round(advised) == declared,
        "computed_on": datetime.date.today().isoformat(),
    }


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


def run(replications: int | None, block_length: bool = True) -> dict:
    generator = random.Random(SEED)
    result = {
        "level": intervals.LEVEL,
        "resamples": intervals.RESAMPLES,
        "method": intervals.METHOD,
        "seed": SEED,
        "commit": commit(),
        "settings": {
            "case": f"Control rate uniform on [{CASE_RATE[0]}, {CASE_RATE[1]}], Candidate rate + {CASE_EFFECT}; the Repeats of a Case share "
            "its rates and the two sides of an Episode share one uniform draw",
            "item": f"independent Item deltas, exponential of mean 1 minus {ITEM_SHIFT}",
            "days": "daily deltas of mean 0: independent standard normal; x[t] = phi x[t-1] + e[t] with phi 0.5 and 0.9, from the stationary "
            f"distribution; sin(2 pi (t + phase) / {BLOCK_LENGTH}) with a random phase plus standard normal noise",
        },
        "sizes": [coverage(unit, units, repeats, replications or count, generator) for unit, units, repeats, count in SIZES],
        "block_sizes": [block_coverage(days, dependence, replications or count, generator) for days, dependence, count in BLOCK_SIZES],
        "timing": timing(),
    }
    if block_length:
        result["optimal_block_length"] = optimal_block_length()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--replications", type=int, help="the same count at every size, instead of the kept run's counts")
    parser.add_argument("--out", type=Path, default=KEPT)
    parser.add_argument("--no-block-length", action="store_true", help="do not ask arch for the advised block length on train")
    args = parser.parse_args()
    args.out.write_text(json.dumps(run(args.replications, not args.no_block_length), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
