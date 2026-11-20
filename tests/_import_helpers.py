"""Shared by the import tests (#67): run the stand-in exporter, build mapping and population files, run `import ml`."""

import csv
import json
import subprocess
import sys
from pathlib import Path

from _study_helpers import ROOT, run_json

EXPORTER = ROOT / "examples" / "external" / "bike_trailing_mean.py"
DAY_CSV = ROOT / "examples" / "bike_day" / "data" / "day.csv"
MAPPING = {"row_id": "day_key", "y_pred": "forecast_rentals", "y_pred_raw": "forecast_unrounded"}
WINDOWS = {"dev": ("2012-01-01", "2012-06-30"), "public_check": ("2012-07-01", "2012-12-31")}
FIELDS = ["day_key", "forecast_rentals", "forecast_unrounded"]


def export(tmp_path, *, partition="dev", name="predictions.csv", data=DAY_CSV):
    """Run the exporter as a separate program; return (CSV path, the sha256 it printed for its input)."""
    first, last = WINDOWS[partition]
    out = tmp_path / name
    done = subprocess.run(
        [sys.executable, str(EXPORTER), "--data", str(data), "--first", first, "--last", last, "--id-prefix", "bike-day", "--out", str(out)],
        capture_output=True, text=True, check=True,
    )
    return out, done.stdout.strip()


def rows_of(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(path, rows, fieldnames):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return Path(path)


def write_json(path, value):
    Path(path).write_text(json.dumps(value), encoding="utf-8")
    return Path(path)


def population_of(tmp_path, source, name="population.json"):
    return write_json(tmp_path / name, {"item_ids": [r["day_key"] for r in rows_of(source)]})


def mapping_of(tmp_path, digest, name="mapping.json", **extra):
    return write_json(tmp_path / name, {**MAPPING, "dataset_sha256": digest, **extra})


def import_ml(study, source, mapping, population, request_id, *more):
    return run_json(
        "import", "ml", "--study", study, "--source", source, "--mapping", mapping,
        "--population", population, "--request-id", request_id, *more,
    )


def ready(tmp_path, *, partition="dev", **extra):
    """(source, mapping, population, digest): a valid export with its mapping and population files."""
    source, digest = export(tmp_path, partition=partition)
    return source, mapping_of(tmp_path, digest, **extra), population_of(tmp_path, source), digest
