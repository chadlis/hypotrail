"""The figures of a Study's Comparisons, read only: `figures` reads them, for both Tracks.

For each Comparison, in the order `status` lists them, the read gives the lines of its `paired_deltas.csv` (per Item on the Regression
Track, per Case on the Agent Track) and, from its paired deltas, the five numbers of a box and the bins of a histogram, computed when the
Study is read and never stored; or the reason why its entry holds none. It reads the Study as `status` reads it, and so refuses what
`status` refuses, then the `paired_deltas.csv` of each Comparison whose delta is not withheld. It writes nothing and holds no lock;
it probes whether a writer holds the lock (`lock.is_held`) with a non-blocking shared lock taken and dropped at once, so a writer starting at
that instant is refused.
"""

import csv
import io
import math
from bisect import bisect_right
from pathlib import Path

from hypotrail.core import artifacts, state
from hypotrail.core.agent_comparison import PAIRED_COLUMNS as CASE_COLUMNS
from hypotrail.core.comparison import PAIRED_COLUMNS as ITEM_COLUMNS
from hypotrail.core.errors import IntegrityError

DELTA_WITHHELD = "delta_withheld"
ARTIFACT_MISSING = "artifact_missing"
ARTIFACT_INTEGRITY = "artifact_integrity"
ARTIFACT_MALFORMED = "artifact_malformed"
VALUE_NOT_FINITE = "value_not_finite"
# The reasons an entry holds no figures, in the order they are looked for: an entry holds the first that applies.
REASONS = (DELTA_WITHHELD, ARTIFACT_MISSING, ARTIFACT_INTEGRITY, ARTIFACT_MALFORMED, VALUE_NOT_FINITE)

QUARTILES = {"q1": 0.25, "median": 0.5, "q3": 0.75}
# The functions that state the definitions of the numbers; handbook chapter 17 gives each with its expression, its docstring.
RULES = ("quantile_position", "quantile_value", "bin_count", "bin_edge", "bin_of")

_ID_COLUMN = 0
_INTEGER_COLUMNS = ("repeats",)


def quantile_position(n: int, p: float) -> float:
    """(n − 1) × p, over the values sorted in ascending order and numbered from 0"""
    return (n - 1) * p


def quantile_value(a: float, b: float, t: float) -> float:
    """a × (1 − t) + b × t, where a and b are the values at the two positions around the quantile position and t its fractional part"""
    return a * (1 - t) + b * t


def bin_count(n: int) -> int:
    """ceil(log2 n) + 1"""
    return math.ceil(math.log2(n)) + 1


def bin_edge(minimum: float, maximum: float, bins: int, k: int) -> float:
    """minimum + k × ((maximum − minimum) / bins) for 0 < k < bins; the minimum for k = 0 and the maximum for k = bins"""
    if k == 0:
        return minimum
    if k == bins:
        return maximum
    return minimum + k * ((maximum - minimum) / bins)


def bin_of(edges: list, v: float) -> int:
    """the bin whose low ≤ v < high, the last bin also holding its high"""
    return bisect_right(edges, v, 1, len(edges) - 1) - 1


def _quantile(ordered: list, p: float) -> float:
    position = quantile_position(len(ordered), p)
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return quantile_value(ordered[lower], ordered[upper], position - lower)


def _unavailable(reason: str) -> dict:
    return {"unavailable": reason, "histogram": None, "quartiles": None}


def figures_of(values: list) -> dict:
    """The bins and the five numbers of `values` (at least one), or `value_not_finite` when a value or a computed number is not finite."""
    if not all(math.isfinite(v) for v in values):
        return _unavailable(VALUE_NOT_FINITE)
    ordered = sorted(values)
    low, high = ordered[0], ordered[-1]
    if low == high:
        return {
            "unavailable": None,
            "histogram": [{"low": low, "high": high, "count": len(ordered)}],
            "quartiles": {"min": low, **dict.fromkeys(QUARTILES, low), "max": high},
        }
    bins = bin_count(len(ordered))
    if not math.isfinite((high - low) / bins):
        return _unavailable(VALUE_NOT_FINITE)
    edges = [bin_edge(low, high, bins, k) for k in range(bins + 1)]
    quartiles = {"min": low, **{name: _quantile(ordered, p) for name, p in QUARTILES.items()}, "max": high}
    if not all(math.isfinite(number) for number in [*edges, *quartiles.values()]):
        return _unavailable(VALUE_NOT_FINITE)
    counts = [0] * bins
    for v in ordered:
        counts[bin_of(edges, v)] += 1
    return {
        "unavailable": None,
        "histogram": [{"low": edges[i], "high": edges[i + 1], "count": counts[i]} for i in range(bins)],
        "quartiles": quartiles,
    }


def _number(name: str, cell: str):
    value = float(cell)
    return int(value) if name in _INTEGER_COLUMNS and value.is_integer() else value


def _lines(data: bytes, columns: list) -> list | None:
    """The lines of a `paired_deltas.csv`, each keyed by its column names, or None when its header is not `columns`, a value cell is not
    parsed by `float()`, a line has another number of cells, or it has no line of data."""
    try:
        header, *rows = csv.reader(io.StringIO(data.decode("utf-8")))
    except (UnicodeDecodeError, ValueError, csv.Error):
        return None
    if header != columns or not rows or any(len(row) != len(columns) for row in rows):
        return None
    try:
        return [{name: cell if index == _ID_COLUMN else _number(name, cell) for index, (name, cell) in enumerate(zip(columns, row))} for row in rows]
    except ValueError:
        return None


def _marked(comparison_id: str, reason: str) -> dict:
    return {"comparison_id": comparison_id, "unavailable": reason, "paired_deltas": None, "histogram": None, "quartiles": None}


def _paired_lines(study: Path, record: dict) -> tuple:
    """(the reason the Comparison's lines cannot be given, or None; its lines; the column of its paired deltas)."""
    if record["delta"]["value"] is None:
        return DELTA_WITHHELD, None, None
    ref = record.get("paired_deltas_ref")
    if ref is None:
        return ARTIFACT_MISSING, None, None
    try:
        data = artifacts.read_verified(study, ref)
    except IntegrityError as error:
        return (ARTIFACT_MISSING if error.code == "ARTIFACT_MISSING" else ARTIFACT_INTEGRITY), None, None
    columns = CASE_COLUMNS if "primary_criterion" in record else ITEM_COLUMNS
    lines = _lines(data, columns)
    if lines is None:
        return ARTIFACT_MALFORMED, None, None
    if not all(math.isfinite(line[name]) for line in lines for name in columns[1:]):
        return VALUE_NOT_FINITE, None, None
    return None, lines, columns[-1]  # both Tracks write the paired delta in the last column


def entry(study: Path, record: dict) -> dict:
    """The entry of one Comparison record: its lines and its numbers, or the first reason that applies."""
    reason, lines, column = _paired_lines(study, record)
    if reason is not None:
        return _marked(record["comparison_id"], reason)
    computed = figures_of([line[column] for line in lines])
    if computed["unavailable"] is not None:
        return _marked(record["comparison_id"], computed["unavailable"])
    return {"comparison_id": record["comparison_id"], "unavailable": None, "paired_deltas": lines, "histogram": computed["histogram"], "quartiles": computed["quartiles"]}


def read(study) -> dict:
    """The write sequence of the Study and one entry per Comparison, in the order `status` lists them; refuses the Study as `status` does."""
    study = Path(study)
    listing = state.status(study)
    return {"write_sequence": listing["write_sequence"], "comparisons": [entry(study, record) for record in listing["comparisons"]]}
