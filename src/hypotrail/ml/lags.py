"""Lag features of a declared target, computed from dates.

The target values are keyed by date, never by row position, so the order of the
input rows cannot change a feature. For a date t only values strictly before t are
read. The features come from the typed declaration (`TargetFeature`). Their kinds are
listed in the schema only, which refuses any other; their periods shift the dates
themselves (`periods.Period`):

- `lag`: the value at t - period days.
- `mean_previous`: the mean of the values at t - period .. t - 1.
"""

import datetime

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.declaration import TargetFeature, typed


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="features", details=details)


def _value_at(values: dict, day: datetime.date, source: datetime.date, feature: str) -> float:
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


def compute_lags(values: dict, day: datetime.date, features) -> dict[str, float]:
    """`values` maps a date to the target; returns each declared feature for `day`."""
    computed = {}
    for feature in features:
        typed(feature, TargetFeature)
        period = feature.period
        if feature.kind == "lag":
            computed[feature.name] = float(_value_at(values, day, period.earlier(day), feature.name))
        else:  # mean_previous: the schema allows no other kind
            period.earlier(day)  # refuse a shift off the calendar at once, not after walking to it
            window = [_value_at(values, day, source, feature.name) for source in reversed(list(period.window(day)))]
            computed[feature.name] = sum(window) / period.days
    return computed
