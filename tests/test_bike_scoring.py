"""Ticket #17 (spike check 4): score a Bike predictions CSV without Inspect.

This reads a CSV and scores it. It creates no Attempt and is not an Import:
the Import contract belongs to a later slice.
"""

import csv
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DAY_CSV = ROOT / "examples" / "bike_day" / "data" / "day.csv"

# Runs a scoring in a fresh interpreter where the optional dependencies cannot
# be imported, whether or not they are installed in this environment.
_WITHOUT_OPTIONAL_DEPENDENCIES = """
import importlib.abc, json, sys

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in {"inspect_ai", "sklearn", "numpy", "anthropic"}:
            raise ImportError(f"{name} is blocked in this environment")

sys.meta_path.insert(0, Blocker())
try:
    import inspect_ai
except ImportError:
    pass
else:
    raise SystemExit("inspect_ai is importable: the blocker does not work")

from pathlib import Path
from hypotrail.core.regression import mean_absolute_error_by_date

mae = mean_absolute_error_by_date(Path(sys.argv[1]), Path(sys.argv[2]))
print(json.dumps({"mae": mae, "loaded": sorted(m for m in sys.modules if m.split(".")[0] in {"inspect_ai", "sklearn", "numpy"})}))
"""


def read_targets():
    with DAY_CSV.open(newline="") as handle:
        return {row["dteday"]: int(row["cnt"]) for row in csv.DictReader(handle)}


def write_predictions(path, predictions):
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "y_pred"])
        writer.writerows(predictions)


@pytest.fixture
def predictions():
    """Dev-period predictions with known errors: +10 on even days, -30 on odd."""
    targets = read_targets()
    dev = sorted(d for d in targets if "2012-01-01" <= d <= "2012-06-30")
    rows = [
        (d, targets[d] + 10 if i % 2 == 0 else targets[d] - 30)
        for i, d in enumerate(dev)
    ]
    assert len(rows) == 182
    return rows


def run_without_optional_dependencies(predictions_path):
    result = subprocess.run(
        [sys.executable, "-c", _WITHOUT_OPTIONAL_DEPENDENCIES, str(predictions_path), str(DAY_CSV)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_mae_is_computed_without_inspect_and_matches_an_independent_calculation(
    tmp_path, predictions
):
    path = tmp_path / "predictions.csv"
    write_predictions(path, predictions)

    result = run_without_optional_dependencies(path)

    # Independent: 91 days off by 10 and 91 days off by 30 -> (91*10 + 91*30) / 182.
    assert result["mae"] == 20.0
    # And from the rows themselves, with no code shared with the implementation.
    targets = read_targets()
    errors = [abs(pred - targets[date]) for date, pred in predictions]
    assert result["mae"] == pytest.approx(sum(errors) / len(errors), abs=1e-12)
    assert result["loaded"] == []


def test_shuffling_the_rows_gives_the_same_mae(tmp_path, predictions):
    ordered = tmp_path / "ordered.csv"
    shuffled = tmp_path / "shuffled.csv"
    write_predictions(ordered, predictions)
    mixed = list(predictions)
    random.Random(7).shuffle(mixed)
    assert mixed != predictions
    write_predictions(shuffled, mixed)

    assert (
        run_without_optional_dependencies(shuffled)["mae"]
        == run_without_optional_dependencies(ordered)["mae"]
    )


def test_a_prediction_is_joined_to_its_own_date_not_to_its_position(tmp_path):
    targets = read_targets()
    # Two predictions whose order is the reverse of the calendar.
    rows = [("2012-01-02", targets["2012-01-02"] + 4), ("2012-01-01", targets["2012-01-01"] + 2)]
    path = tmp_path / "p.csv"
    write_predictions(path, rows)
    assert run_without_optional_dependencies(path)["mae"] == 3.0


def test_a_date_outside_the_target_file_is_refused(tmp_path):
    from hypotrail.core.errors import InvalidInputError
    from hypotrail.core.regression import mean_absolute_error_by_date

    path = tmp_path / "p.csv"
    write_predictions(path, [("2030-01-01", 5)])
    with pytest.raises(InvalidInputError):
        mean_absolute_error_by_date(path, DAY_CSV)


@pytest.mark.parametrize("cell", ["nan", "NaN", "inf", "-inf", "Infinity", "1e999", "", "  ", "abc"])
def test_a_prediction_that_is_not_a_finite_number_is_refused(tmp_path, cell):
    from hypotrail.core.errors import InvalidInputError
    from hypotrail.core.regression import mean_absolute_error_by_date

    path = tmp_path / "p.csv"
    write_predictions(path, [("2012-01-01", 5), ("2012-01-02", cell)])
    with pytest.raises(InvalidInputError) as caught:
        mean_absolute_error_by_date(path, DAY_CSV)
    assert caught.value.stage == "score"
    assert caught.value.details["date"] == "2012-01-02"


def test_a_prediction_row_with_a_missing_cell_is_refused(tmp_path):
    from hypotrail.core.errors import InvalidInputError
    from hypotrail.core.regression import mean_absolute_error_by_date

    path = tmp_path / "p.csv"
    path.write_text("date,y_pred\n2012-01-01\n")
    with pytest.raises(InvalidInputError):
        mean_absolute_error_by_date(path, DAY_CSV)


@pytest.mark.parametrize("cell", ["nan", "inf", "-inf", "", "abc"])
def test_a_target_that_is_not_a_finite_integer_is_refused(tmp_path, cell):
    from hypotrail.core.errors import InvalidInputError
    from hypotrail.core.regression import mean_absolute_error_by_date

    targets = tmp_path / "targets.csv"
    targets.write_text(f"dteday,cnt\n2012-01-01,{cell}\n")
    path = tmp_path / "p.csv"
    write_predictions(path, [("2012-01-01", 5)])
    with pytest.raises(InvalidInputError) as caught:
        mean_absolute_error_by_date(path, targets)
    assert caught.value.stage == "score"


def test_a_repeated_date_is_refused_rather_than_counted_twice(tmp_path):
    from hypotrail.core.errors import InvalidInputError
    from hypotrail.core.regression import mean_absolute_error_by_date

    path = tmp_path / "p.csv"
    write_predictions(path, [("2012-01-01", 5), ("2012-01-01", 6)])
    with pytest.raises(InvalidInputError):
        mean_absolute_error_by_date(path, DAY_CSV)


@pytest.mark.parametrize(
    "rows",
    [
        [("2012-01-01", 1e308), ("2012-01-02", -1e308)],  # an error beyond the largest float
        [("2012-01-01", 1e308), ("2012-01-02", 1e308)],  # each error fits, their sum does not
    ],
)
def test_predictions_too_large_to_average_are_refused_not_an_overflow_or_an_infinite_mae(tmp_path, rows):
    from hypotrail.core.errors import InvalidInputError
    from hypotrail.core.regression import mean_absolute_error_by_date

    path = tmp_path / "p.csv"
    write_predictions(path, rows)
    with pytest.raises(InvalidInputError) as caught:
        mean_absolute_error_by_date(path, DAY_CSV)
    assert caught.value.stage == "score"
    assert caught.value.code == "NON_FINITE_ERROR"


def test_a_target_beyond_the_largest_float_is_refused_not_an_overflow(tmp_path):
    from hypotrail.core.errors import InvalidInputError
    from hypotrail.core.regression import mean_absolute_error_by_date

    targets = tmp_path / "targets.csv"
    targets.write_text("dteday,cnt\n2012-01-01,1" + "0" * 400 + "\n")
    path = tmp_path / "p.csv"
    write_predictions(path, [("2012-01-01", 5)])
    with pytest.raises(InvalidInputError) as caught:
        mean_absolute_error_by_date(path, targets)
    assert caught.value.stage == "score"
    assert caught.value.details["date"] == "2012-01-01"


def test_a_repeated_date_in_the_targets_is_refused(tmp_path):
    from hypotrail.core.errors import InvalidInputError
    from hypotrail.core.regression import mean_absolute_error_by_date

    targets = tmp_path / "targets.csv"
    targets.write_text("dteday,cnt\n2012-01-01,10\n2012-01-01,20\n")
    path = tmp_path / "p.csv"
    write_predictions(path, [("2012-01-01", 5)])
    with pytest.raises(InvalidInputError) as caught:
        mean_absolute_error_by_date(path, targets)
    assert caught.value.code == "DUPLICATE_DATE"
    assert caught.value.stage == "score"
    assert caught.value.details["date"] == "2012-01-01"


def test_inspect_is_declared_only_under_an_extra():
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert not any("inspect" in d for d in project["dependencies"])
    assert any("inspect-ai" in d for d in project["optional-dependencies"]["agent"])
