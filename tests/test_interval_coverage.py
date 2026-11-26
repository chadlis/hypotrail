"""The coverage simulation of the paired interval: the development script runs, and its kept result names the sizes the Workloads use."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "docs" / "handbook" / "simulations" / "interval_coverage.py"
KEPT = ROOT / "docs" / "handbook" / "simulations" / "interval-coverage.json"
SIZES = [("case", 12, 1), ("case", 12, 3), ("case", 100, 1), ("case", 100, 3), ("item", 3000, None)]


def sizes_of(result) -> list:
    return [(size["unit"], size["units"], size["repeats"]) for size in result["sizes"]]


def test_the_script_runs_at_a_reduced_count_and_gives_a_share_for_each_size(tmp_path):
    out = tmp_path / "coverage.json"
    subprocess.run([sys.executable, str(SCRIPT), "--replications", "3", "--out", str(out)], check=True, capture_output=True, text=True)
    result = json.loads(out.read_text(encoding="utf-8"))
    assert sizes_of(result) == SIZES
    assert all(size["replications"] == 3 and 0 <= size["coverage"] <= 1 for size in result["sizes"])


def test_the_kept_file_names_the_sizes_the_settings_the_seed_the_replications_and_the_commit():
    kept = json.loads(KEPT.read_text(encoding="utf-8"))
    assert sizes_of(kept) == SIZES
    assert (kept["level"], kept["resamples"], kept["method"]) == (0.95, 2000, "percentile_bootstrap")
    assert isinstance(kept["seed"], int) and kept["commit"] and set(kept["settings"]) == {"case", "item"}
    assert all(size["replications"] >= 300 and "true_delta" in size and "coverage" in size for size in kept["sizes"])
    assert set(kept["timing"]) == {"units", "resamples", "seconds", "python"} and kept["timing"]["units"] == 3000
