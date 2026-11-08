"""The Scorer registry: static and closed (SPEC §8).

A `SCORER_ID` is a key of `REGISTRY`, looked up as a string. Nothing is imported, evaluated or
looked up by name from the given text, so no Python can be loaded through it. This ticket registers
the two Scorers of the temporal regression Track; `chinook_contract_v1` joins with the Chinook
ticket. A Scorer carries the `domain` of the Observation sets it can score, a `config` that is
hashed into `config_digest`, and the pure function that aggregates the Criterion into its Metric.
The module needs only the standard library.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

from hypotrail.core import canonical
from hypotrail.core.errors import InvalidInputError

REGRESSION = "regression"
ABSOLUTE_ERROR = "absolute_error"


def mean_absolute_error(absolute_errors: list) -> float:
    return math.fsum(absolute_errors) / len(absolute_errors)


def root_mean_squared_error(absolute_errors: list) -> float:
    # |e|**2 == e**2: the absolute error of the day is enough to compute the RMSE.
    return math.sqrt(math.fsum(e * e for e in absolute_errors) / len(absolute_errors))


@dataclass(frozen=True)
class Scorer:
    id: str
    version: str
    domain: str
    criterion: str
    metric_id: str
    aggregate: Callable[[list], float]

    @property
    def config(self) -> dict:
        return {"criterion": self.criterion, "metric": self.metric_id, "direction": "lower_is_better"}

    @property
    def config_digest(self) -> str:
        return canonical.digest(self.config)


REGISTRY: dict[str, Scorer] = {
    scorer.id: scorer
    for scorer in (
        Scorer("regression_mae_v1", "1", REGRESSION, ABSOLUTE_ERROR, "mae", mean_absolute_error),
        Scorer("regression_rmse_v1", "1", REGRESSION, ABSOLUTE_ERROR, "rmse", root_mean_squared_error),
    )
}


def get(scorer_id) -> Scorer:
    scorer = REGISTRY.get(scorer_id) if isinstance(scorer_id, str) else None
    if scorer is None:
        raise InvalidInputError(
            "SCORER_NOT_REGISTERED",
            f"{scorer_id!r} is not a registered Scorer (the registry is closed: {', '.join(sorted(REGISTRY))})",
            stage="assess",
            details={"scorer": str(scorer_id), "registered": sorted(REGISTRY)},
        )
    return scorer
