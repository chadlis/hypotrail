"""A period the Workload declares: a number of days that shifts a date back itself.

A period is a number of days and knows where it is declared (`key`, and `path`, the dotted path in
`workload.json`). A period within the span of the data can still miss a value (the readers refuse
that with their own codes); a period beyond the calendar leaves no date to land on at all. That is
refused here as the declaration's fault, naming the key and the path of the period and the declared
number of days, instead of ending in the `OverflowError` of the standard library. The refusal has the
stage `periods`, not `declaration`: it depends on the calendar, not on the declaration's shape, so a
caller can tell it from a refusal raised when the declaration is loaded.

Two periods of the same length are equal wherever they are declared.
"""

import datetime
from collections.abc import Iterator
from dataclasses import dataclass, field

from hypotrail.core.errors import InvalidInputError


@dataclass(frozen=True)
class Period:
    days: int
    key: str = field(default="period_k", compare=False)
    path: str = field(default="period_k", compare=False)

    def _before(self, date: datetime.date, offset: int) -> datetime.date:
        try:
            return date - datetime.timedelta(days=offset)
        except OverflowError:
            raise InvalidInputError(
                "DECLARATION_VALUE_NOT_ALLOWED",
                f"{self.path} is not allowed: reaching {self.days} days before {date.isoformat()} leaves the calendar",
                stage="periods",
                details={"key": self.key, "path": self.path, "days": self.days, "date": date.isoformat()},
            ) from None

    def earlier(self, date: datetime.date) -> datetime.date:
        """`date` minus the period; a shift that leaves the calendar is an `InvalidInputError`."""
        return self._before(date, self.days)

    def window(self, date: datetime.date) -> Iterator[datetime.date]:
        """The dates 1 .. `days` before `date`, nearest first and one at a time.

        A date that leaves the calendar is refused when it is reached, naming the whole period.
        """
        for offset in range(1, self.days + 1):
            yield self._before(date, offset)
