"""Lag features of a declared target, computed from dates.

Standard library only. The target values are keyed by date, never by row
position, so the order of the input rows cannot change a feature. For a date t
only values strictly before t are read. The kinds and periods come from the
declaration:

- `lag`: the value at t - period days.
- `mean_previous`: the mean of the values at t - period .. t - 1.
"""

import datetime

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.periods import shift_back


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="features", details=details)


def _value_at(values: dict, day: datetime.date, offset: int, feature: str, path: str) -> float:
    source = shift_back(day, offset, key="period", path=path)
    try:
        return values[source]
    except KeyError:
        raise _refuse(
            "LAG_SOURCE_MISSING",
            f"{feature} for {day.isoformat()} needs {source.isoformat()}, which is not in the series",
            feature=feature,
            date=day.isoformat(),
            source=source.isoformat(),
        ) from None


def compute_lags(
    values: dict, day: datetime.date, features: list[dict], *, where: str = "lag_features"
) -> dict[str, float]:
    """`values` maps a date to the target; returns each declared feature for `day`.

    `where` is the dotted path of `features` in `workload.json`, named when a period cannot be applied.
    """
    computed = {}
    for index, feature in enumerate(features):
        name, kind, period = feature["name"], feature["kind"], feature["period"]
        path = f"{where}.{index}.period"
        if kind == "lag":
            computed[name] = float(_value_at(values, day, period, name, path))
        elif kind == "mean_previous":
            window = [_value_at(values, day, offset, name, path) for offset in range(period, 0, -1)]
            computed[name] = sum(window) / period
        else:
            raise _refuse("UNKNOWN_FEATURE_KIND", f"unknown feature kind {kind!r}", feature=name, kind=kind)
    return computed
