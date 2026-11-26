"""The data profile of a Study of the temporal regression Track, read only: `profile` reads it.

The read gives, from the Study's `train` Items only: the target over time with the Partition band, one distribution per profiled
column, the association matrix of the profiled columns (the target is in none of its pairs) in clustering order, and the target
against each allowed column and each allowed target feature. Every value comes from the Study's own dataset copy and memberships,
each read back against its digest; the Workload gives only the names, the marks (`forbidden_features`, `allowed_target_features`)
and the band. The read compares the Workload's Protocol digest with the Study's (`workload_protocol`) and answers either way. It
takes no lock, writes nothing and records no Exposure: no value of a `dev` or `public_check` day is given.

The kinds are derived: every data column but the date and the target is profiled; a column whose `train` cells are not all finite
numbers is categorical, an integer column with at most 12 values on `train` is categorical too, and the others are numeric.

The measures are those of the earlier implementation, on SciPy: Spearman's rank correlation for two numeric columns, Cramér's V with
Bergsma's bias correction for two categorical columns (computed here: SciPy's `correction` flag is Yates'), and the correlation ratio
(eta) of the numeric column's ranks across the categories for one of each. No p-value is computed.
"""

import csv
import datetime
import io
import math
from pathlib import Path

import numpy as np
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform
from scipy.stats import rankdata, spearmanr
from scipy.stats.contingency import crosstab

from hypotrail.core import artifacts, data, write_journal
from hypotrail.core import study as layout
from hypotrail.core.figures import figures_of
from hypotrail.ml.declaration import load_declaration, require_keys
from hypotrail.ml.lags import compute_lags
from hypotrail.ml.partitions import DEV, PUBLIC_CHECK, TRAIN
from hypotrail.ml.series import target_series
from hypotrail.ml.study import DOMAIN, freeze_basis
from hypotrail.ml.table import table_of

COMMAND = "profile"
SAME, DIFFERS = "same", "differs"
NUMERIC, CATEGORICAL = "numeric", "categorical"

LEVEL = 0.8  # a pair whose |value| reaches it is flagged
MIN_ROWS = 10  # a pair is measured on at least this many rows
CATEGORICAL_MAX_VALUES = 12  # an integer column with at most this many values on `train` is categorical

SPEARMAN, CRAMERS_V, ETA = "spearman", "cramers_v", "eta"
MEASURES = {
    SPEARMAN: "Spearman's rank correlation (two numeric columns; signed, from -1 to 1)",
    CRAMERS_V: "Cramér's V with Bergsma's bias correction (two categorical columns; from 0 to 1)",
    ETA: "the correlation ratio of the numeric column's ranks across the categories (a numeric and a categorical column; from 0 to 1)",
}

FORBIDDEN_FEATURE = "forbidden_feature"
TOO_FEW_ROWS = "too_few_rows"
CONSTANT_COLUMN = "constant_column"
CORRECTION_UNDEFINED = "correction_undefined"
# The reasons of the read: a column's (`unavailable`), then a pair's, in the order a pair's are looked for.
REASONS = (FORBIDDEN_FEATURE, TOO_FEW_ROWS, CONSTANT_COLUMN, CORRECTION_UNDEFINED)


# --- the measures ---------------------------------------------------------------------------------------------------------------


def bergsma_v(table) -> float | None:
    """Cramér's V of a contingency table with Bergsma's bias correction, or None when a dimension holds one category or the
    corrected denominator is not positive."""
    table = np.asarray(table, dtype=float)
    r, k = table.shape
    if r < 2 or k < 2:
        return None
    n = table.sum()
    expected = table.sum(axis=1, keepdims=True) * table.sum(axis=0, keepdims=True) / n
    phi2 = float(((table - expected) ** 2 / expected).sum()) / n
    phi2_corrected = max(0.0, phi2 - (k - 1) * (r - 1) / (n - 1))
    r_corrected = r - (r - 1) ** 2 / (n - 1)
    k_corrected = k - (k - 1) ** 2 / (n - 1)
    denominator = min(k_corrected - 1, r_corrected - 1)
    if denominator <= 0:
        return None
    return min(1.0, math.sqrt(phi2_corrected / denominator))


def cramers_v(a: list, b: list) -> tuple:
    """(value, reason) of two categorical columns of equal length."""
    if len(a) < MIN_ROWS:
        return None, TOO_FEW_ROWS
    if len(set(a)) < 2 or len(set(b)) < 2:
        return None, CONSTANT_COLUMN
    value = bergsma_v(crosstab(np.asarray(a, dtype=str), np.asarray(b, dtype=str)).count)
    return (None, CORRECTION_UNDEFINED) if value is None else (value, None)


def spearman(x: list, y: list) -> tuple:
    """(value, reason) of two numeric columns of equal length; SciPy's p-value is dropped."""
    if len(x) < MIN_ROWS:
        return None, TOO_FEW_ROWS
    if len(set(x)) < 2 or len(set(y)) < 2:
        return None, CONSTANT_COLUMN
    return float(spearmanr(x, y).statistic), None


def eta(numeric: list, categories: list) -> tuple:
    """(value, reason) of a numeric column against a categorical one: the correlation ratio of the numeric column's ranks."""
    if len(numeric) < MIN_ROWS:
        return None, TOO_FEW_ROWS
    if len(set(numeric)) < 2 or len(set(categories)) < 2:
        return None, CONSTANT_COLUMN
    ranks = rankdata(numeric)
    mean = ranks.mean()
    total = float(((ranks - mean) ** 2).sum())
    groups = {}
    for rank, category in zip(ranks, categories):
        groups.setdefault(category, []).append(rank)
    between = sum(len(members) * (sum(members) / len(members) - mean) ** 2 for members in groups.values())
    return min(1.0, math.sqrt(between / total)), None


def measure_of(kind_a: str, kind_b: str) -> str:
    if kind_a == NUMERIC and kind_b == NUMERIC:
        return SPEARMAN
    if kind_a == CATEGORICAL and kind_b == CATEGORICAL:
        return CRAMERS_V
    return ETA


def associate(kind_a: str, a: list, kind_b: str, b: list) -> tuple:
    """(measure, value, reason) of two columns of the given kinds."""
    measure = measure_of(kind_a, kind_b)
    if measure == SPEARMAN:
        return measure, *spearman(a, b)
    if measure == CRAMERS_V:
        return measure, *cramers_v(a, b)
    numeric, categories = (a, b) if kind_a == NUMERIC else (b, a)
    return measure, *eta(numeric, categories)


def clustering_order(names: list, values: dict) -> list:
    """The names in the leaf order of an average-linkage clustering on 1 - |value|, a pair with no value at distance 1; fewer than
    three names are kept as given. `values` maps each pair (a, b), in either order, to its value or None."""
    if len(names) < 3:
        return list(names)
    distance = np.ones((len(names), len(names)))
    np.fill_diagonal(distance, 0.0)
    for i, a in enumerate(names):
        for j, b in enumerate(names):
            value = values.get((a, b), values.get((b, a)))
            if i != j and value is not None:
                distance[i, j] = max(0.0, 1.0 - abs(value))
    tree = linkage(squareform(distance, checks=False), method="average")
    return [names[i] for i in leaves_list(tree)]


# --- the kinds and the distributions ---------------------------------------------------------------------------------------------


def _finite_number(cell: str) -> bool:
    try:
        return math.isfinite(float(cell))
    except ValueError:
        return False


def _integer(cell: str) -> bool:
    try:
        int(cell)
    except ValueError:
        return False
    return True


def kind_of(cells: list) -> str:
    """The kind of a column from its `train` cells."""
    if not all(_finite_number(cell) for cell in cells):
        return CATEGORICAL
    if all(_integer(cell) for cell in cells) and len({int(cell) for cell in cells}) <= CATEGORICAL_MAX_VALUES:
        return CATEGORICAL
    return NUMERIC


def _number(cell: str):
    return int(cell) if _integer(cell) else float(cell)


def _labels_in_order(cells: list) -> list:
    """The distinct values of a categorical column: by number when every cell is an integer, else by text."""
    distinct = set(cells)
    if all(_integer(cell) for cell in distinct):
        return sorted(distinct, key=lambda cell: (int(cell), cell))
    return sorted(distinct)


def distribution(kind: str, cells: list) -> dict:
    """The bins and five numbers of a numeric column (`figures_of`), or the count per value of a categorical one."""
    if kind == NUMERIC:
        return {**figures_of([_number(cell) for cell in cells]), "counts": None}
    return {"unavailable": None, "histogram": None, "quartiles": None, "counts": [{"value": v, "count": cells.count(v)} for v in _labels_in_order(cells)]}


# --- the read -------------------------------------------------------------------------------------------------------------------


def _memberships_ref(spec: dict) -> dict:
    return next(entry["ref"] for entry in spec["artifacts"] if entry["ref"]["role"] == "memberships")


def _membership_rows(raw: bytes) -> list:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"), newline="")))


def lag_series(series: dict, memberships: list) -> dict:
    """The part of the target series that the lags of the `train` Items are computed from: no day of `dev` or `public_check`."""
    left_out = {row["date"] for row in memberships if row["partition"] in (DEV, PUBLIC_CHECK)}
    return {day: value for day, value in series.items() if day.isoformat() not in left_out}


def _against_target(name: str, kind: str, values: list, row_ids: list, target: list) -> dict:
    measure, value, reason = associate(kind, values, NUMERIC, target)
    entry = {"name": name, "kind": kind, "measure": measure, "value": value, "rows": len(values), "reason": reason, "points": None, "values": None}
    if kind == NUMERIC:
        entry["points"] = [{"row_id": row_id, "feature": x, "target": y} for row_id, x, y in zip(row_ids, values, target)]
    else:
        entry["values"] = [
            {"value": label, "count": len(ys), "figures": figures_of(ys)}
            for label in _labels_in_order(values)
            for ys in [[y for v, y in zip(values, target) if v == label]]
        ]
    return entry


def profile(study, examples_dir=None) -> dict:
    """The data profile of the Study's `train` Items; refuses a Study of another domain and a Workload column the data lacks."""
    study = Path(study)
    spec = layout.read_spec(study)
    layout.require_domain(spec, DOMAIN, COMMAND)
    source = data.resolve_examples_dir(examples_dir) / spec["workload"]
    declaration = load_declaration(source)
    require_keys(declaration, "date_column", "target_column", "target_unit", "forbidden_features", "allowed_target_features")
    protocol = SAME if freeze_basis(spec, source)["protocol_digest"] == spec["protocol_digest"] else DIFFERS

    dataset = artifacts.read_verified(study, layout.dataset_ref(spec))
    memberships = _membership_rows(artifacts.read_verified(study, _memberships_ref(spec)))
    table = table_of(dataset, declaration, [declaration.target_column])
    history = lag_series(target_series(dataset, declaration), memberships)
    items = [(row["row_id"], day) for row in memberships if row["partition"] == TRAIN and not row["exclusion_reason"] for day in [datetime.date.fromisoformat(row["date"])]]
    row_ids = [row_id for row_id, _ in items]
    target = [history[day] for _, day in items]

    header = list(next(iter(table.values()), {}))
    names = [name for name in header if name not in (declaration.date_column, declaration.target_column)]
    forbidden = set(declaration.forbidden_features)
    cells = {name: [table[day][name] for _, day in items] for name in names}
    kinds = {name: kind_of(cells[name]) for name in names}
    measured = {name: cells[name] if kinds[name] == CATEGORICAL else [_number(cell) for cell in cells[name]] for name in names}

    columns = [
        {"name": name, "kind": kinds[name], "available": name not in forbidden, "unavailable": FORBIDDEN_FEATURE if name in forbidden else None,
         "distribution": distribution(kinds[name], cells[name])}
        for name in names
    ]
    pairs, values = [], {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            measure, value, reason = associate(kinds[a], measured[a], kinds[b], measured[b])
            values[(a, b)] = value
            pairs.append({"a": a, "b": b, "measure": measure, "value": value, "rows": len(items), "flagged": value is not None and abs(value) >= LEVEL, "reason": reason})

    against = [_against_target(name, kinds[name], measured[name], row_ids, target) for name in names if name not in forbidden]
    for feature in declaration.allowed_target_features:
        lagged = [compute_lags(history, day, [feature])[feature.name] for _, day in items]
        against.append(_against_target(feature.name, NUMERIC, lagged, row_ids, target))

    return {
        "write_sequence": write_journal.write_sequence(study),
        "revision_number": spec["revision_number"],
        "workload_protocol": protocol,
        "partition": TRAIN,
        "items": len(items),
        "band": [{"name": p.name, "first": p.first.isoformat(), "last": p.last.isoformat()} for p in declaration.partitions],
        "target": {
            "column": declaration.target_column,
            "unit": declaration.target_unit,
            "series": [{"row_id": row_id, "date": day.isoformat(), "value": value} for (row_id, day), value in zip(items, target)],
            "figures": figures_of(target),
        },
        "columns": columns,
        "associations": {"order": clustering_order(names, values), "pairs": pairs, "level": LEVEL, "measures": dict(MEASURES)},
        "against_target": against,
    }
