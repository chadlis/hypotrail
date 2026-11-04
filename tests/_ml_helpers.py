"""Shared by the ML Track tests (#32, #33): the fit probe.

`fit_probe` replaces the fit entry points of scikit-learn (estimator,
preprocessing, column transformer, pipeline) with recorders. With
`strict=True` a call raises. A test that expects no fit asserts
`probe.calls == []`; a positive control shows the probe fires on a real fit,
so an empty list means something.
"""

import contextlib
import importlib

FIT_TARGETS = [
    ("sklearn.linear_model", "Ridge", "fit"),
    ("sklearn.preprocessing", "StandardScaler", "fit"),
    ("sklearn.preprocessing", "OneHotEncoder", "fit"),
    ("sklearn.compose", "ColumnTransformer", "fit"),
    ("sklearn.compose", "ColumnTransformer", "fit_transform"),
    ("sklearn.pipeline", "Pipeline", "fit"),
]


class FitProbe:
    def __init__(self):
        self.calls: list[str] = []


@contextlib.contextmanager
def fit_probe(*, strict: bool = False):
    probe = FitProbe()
    saved = []
    for module_name, class_name, method in FIT_TARGETS:
        cls = getattr(importlib.import_module(module_name), class_name)
        own = cls.__dict__.get(method)  # None when the method is inherited
        original = getattr(cls, method)
        saved.append((cls, method, own))

        def make(label, original):
            def recorder(self, *args, **kwargs):
                probe.calls.append(label)
                if strict:
                    raise AssertionError(f"fit called: {label}")
                return original(self, *args, **kwargs)
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
        "target_column": "visits", "period_k": 1,
        "partitions": {"train": ["2020-01-02", "2020-01-03"]},
        **(extra or {}),
    }
    (directory / "workload.json").write_text(json.dumps(declaration), encoding="utf-8")
    return directory
