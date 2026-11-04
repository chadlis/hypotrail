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


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="features", details=details)


def _value_at(values: dict, day: datetime.date, offset: int, feature: str) -> float:
    source = day - datetime.timedelta(days=offset)
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


def compute_lags(values: dict, day: datetime.date, features: list[dict]) -> dict[str, float]:
    """`values` maps a date to the target; returns each declared feature for `day`."""
    computed = {}
    for feature in features:
        name, kind, period = feature["name"], feature["kind"], feature["period"]
        if kind == "lag":
            computed[name] = float(_value_at(values, day, period, name))
        elif kind == "mean_previous":
            window = [_value_at(values, day, offset, name) for offset in range(period, 0, -1)]
            computed[name] = sum(window) / period
        else:
            raise _refuse("UNKNOWN_FEATURE_KIND", f"unknown feature kind {kind!r}", feature=name, kind=kind)
    return computed
