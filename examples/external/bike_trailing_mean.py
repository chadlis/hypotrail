"""A stand-in for someone else's program: daily bike-rental predictions in a CSV of its own.

It uses the standard library only and never imports `hypotrail` (ADR 0002 exception). It knows the
daily file (`day.csv`), the first and last day to predict, and how this team names its days; it
predicts every day of the window with the mean of the 28 days that precede the window, which are
the only counts it looks at. Its columns are its own:

    day_key,forecast_rentals,forecast_unrounded

Usage:

    python bike_trailing_mean.py --data day.csv --first 2012-01-01 --last 2012-06-30 \
        --id-prefix bike-day --out predictions.csv

It also prints the sha256 of the data file it read, which is what a program that wants its
predictions imported would declare about its input.
"""

import argparse
import csv
import datetime
import hashlib
import sys
from pathlib import Path

HISTORY_DAYS = 28


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--first", required=True, type=datetime.date.fromisoformat)
    parser.add_argument("--last", required=True, type=datetime.date.fromisoformat)
    parser.add_argument("--id-prefix", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    raw = args.data.read_bytes()
    counts = {}
    for row in csv.DictReader(raw.decode("utf-8").splitlines()):
        counts[datetime.date.fromisoformat(row["dteday"])] = float(row["cnt"])
    history = [counts[args.first - datetime.timedelta(days=n)] for n in range(1, HISTORY_DAYS + 1)]
    forecast = sum(history) / len(history)

    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["day_key", "forecast_rentals", "forecast_unrounded"])
        day = args.first
        while day <= args.last:
            writer.writerow([f"{args.id_prefix}:{day.isoformat()}", round(forecast), repr(forecast)])
            day += datetime.timedelta(days=1)
    print(hashlib.sha256(raw).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
