"""The one place where a date is shifted back by a period the Workload declares.

A period is a number of days. A period within the span of the data can still miss a value (the
readers refuse that with their own codes); a period beyond the calendar leaves no date to land on
at all. Both are refused here as the declaration's fault, naming the key and the path of the
period, instead of ending in the `OverflowError` of the standard library.
"""

import datetime

from hypotrail.core.errors import InvalidInputError


def shift_back(date: datetime.date, period: int, *, key: str, path: str) -> datetime.date:
    """`date` minus `period` days; a shift no date can apply is an `InvalidInputError`.

    `key` and `path` say where the period is declared (`path` is the dotted path in `workload.json`).
    """
    try:
        return date - datetime.timedelta(days=period)
    except OverflowError:
        raise InvalidInputError(
            "DECLARATION_VALUE_NOT_ALLOWED",
            f"{path} is not allowed: {period} days before {date.isoformat()} is outside the calendar",
            stage="declaration",
            details={"key": key, "path": path, "period": period, "date": date.isoformat()},
        ) from None
