"""Shared by the ML Track tests (#32, #33): the fit probe.

`fit_probe` replaces the fit entry points of scikit-learn (estimator,
preprocessing, column transformer, pipeline) with recorders. Each call is
recorded by label in `probe.calls` and with a copy of the table it received in
`probe.inputs`. With `strict=True` a call raises. A test that expects no fit
asserts `probe.calls == []`; its positive control runs the same probe while
`ridge_v1` is produced, so an empty list means something.
"""

import numpy as np

import contextlib
import importlib

FIT_TARGETS = [
    ("sklearn.linear_model", "Ridge", "fit"),
    ("sklearn.preprocessing", "StandardScaler", "fit"),
    ("sklearn.preprocessing", "StandardScaler", "fit_transform"),
    ("sklearn.preprocessing", "StandardScaler", "partial_fit"),
    ("sklearn.preprocessing", "OneHotEncoder", "fit"),
    ("sklearn.preprocessing", "OneHotEncoder", "fit_transform"),
    ("sklearn.compose", "ColumnTransformer", "fit"),
    ("sklearn.compose", "ColumnTransformer", "fit_transform"),
    ("sklearn.pipeline", "Pipeline", "fit"),
    ("sklearn.pipeline", "Pipeline", "fit_transform"),
    ("sklearn.pipeline", "Pipeline", "fit_predict"),
]


class FitProbe:
    def __init__(self):
        self.calls: list[str] = []
        self.inputs: list[tuple[str, np.ndarray]] = []  # (label, copy of the table received)


@contextlib.contextmanager
def fit_probe(*, strict: bool = False):
    probe = FitProbe()
    saved = []
    for module_name, class_name, method in FIT_TARGETS:
        cls = getattr(importlib.import_module(module_name), class_name)
        original = getattr(cls, method, None)
        if original is None:
            continue
        own = cls.__dict__.get(method)  # None when the method is inherited
        saved.append((cls, method, own))

        def make(label, original):
            def recorder(self, X, *args, **kwargs):
                probe.calls.append(label)
                probe.inputs.append((label, np.array(X, copy=True)))
                if strict:
                    raise AssertionError(f"fit called: {label}")
                return original(self, X, *args, **kwargs)
            return recorder

        setattr(cls, method, make(f"{class_name}.{method}", original))
    try:
        yield probe
    finally:
        for cls, method, own in saved:
            if own is None:
                delattr(cls, method)
            else:
                setattr(cls, method, own)


def write_small_workload(directory, csv_text, *, extra=None):
    """A tiny Workload (date column `day`, target `visits`, k=1) around the given CSV text."""
    import json
    from pathlib import Path

    directory = Path(directory)
    (directory / "data").mkdir(parents=True)
    (directory / "data" / "series.csv").write_text(csv_text, encoding="utf-8")
    declaration = {
        "schema_version": "workload/1", "data_file": "data/series.csv",
        "licence_notice": "none.md", "id_prefix": "shop-day", "date_column": "day",
        "target_column": "visits", "period_k": 1, "target_unit": "visits per day",
        "forbidden_features": [], "allowed_target_features": [], "configurations": {},
        "partitions": {"train": ["2020-01-02", "2020-01-03"]},
        **(extra or {}),
    }
    (directory / "workload.json").write_text(json.dumps(declaration), encoding="utf-8")
    return directory


def fitted_row_ids(probe, workload_dir, config_id):
    """The row_ids of the Items the whole pipeline was fitted on, read back from what it received.

    Rows are told apart by their values: the model inputs of every Item of every Partition are
    rebuilt, and a row the probe saw must match exactly one of them.
    """
    from hypotrail.ml.ridge import build_inputs

    owner = {}
    for partition in ("train", "dev", "public_check"):
        inputs = build_inputs(workload_dir, config_id, partition)
        for row_id, line in zip(inputs.row_ids, inputs.matrix):
            assert line.tobytes() not in owner
            owner[line.tobytes()] = row_id
    seen = set()
    for label, X in probe.inputs:
        if label.startswith(("Pipeline", "ColumnTransformer")):
            seen |= {owner[line.tobytes()] for line in X}
    return seen


def canonical_digest(value):
    """sha256 of a CSV file (given as a path) or of JSON-able data, floats rounded to 6 decimals.

    The rounding keeps a digest recorded on one machine true on another (BLAS may differ in the last bit).
    """
    import csv
    import hashlib
    import json
    from pathlib import Path

    def rounded(node):
        if isinstance(node, float):
            return round(node, 6)
        if isinstance(node, dict):
            return {key: rounded(item) for key, item in node.items()}
        if isinstance(node, list):
            return [rounded(item) for item in node]
        return node

    def cell(text):
        try:
            return float(text)
        except ValueError:
            return text

    if isinstance(value, Path):
        with value.open(newline="", encoding="utf-8") as handle:
            value = [[cell(c) for c in row] for row in csv.reader(handle)]
    return hashlib.sha256(json.dumps(rounded(value), sort_keys=True).encode()).hexdigest()
