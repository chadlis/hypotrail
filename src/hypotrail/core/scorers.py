"""The Scorer registry: static and closed (SPEC §8).

A `SCORER_ID` is a key of `REGISTRY`, looked up as a string. Nothing is imported, evaluated or
looked up by name from the given text, so no Python can be loaded through it. It registers the two
Scorers of the temporal regression Track and `chinook_contract_v1` of the agent Track (#68). A Scorer
carries the `domain` of the Observation sets it can score and a `config` that is hashed into
`config_digest`. A regression Scorer has one Criterion and the pure function that aggregates it into
its Metric; `chinook_contract_v1` has four Criteria and no aggregation of its own: the shares of an
agent Assessment are counted from the states of its Criteria, and the one scoring function stays in
`hypotrail.core.chinook_contract` (ADR 0001). The module needs the standard library and, for that
Scorer's name and version, `hypotrail.core.chinook_contract`.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

from hypotrail.core import canonical
from hypotrail.core.chinook_contract import CRITERIA as CHINOOK_CRITERIA
from hypotrail.core.chinook_contract import SCORER_NAME as CHINOOK_SCORER
from hypotrail.core.chinook_contract import SCORER_VERSION as CHINOOK_VERSION
from hypotrail.core.errors import InvalidInputError

REGRESSION = "regression"
AGENTIC = "agentic"
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
    criterion: str | None
    metric_id: str | None
    aggregate: Callable[[list], float] | None
    criteria: tuple = ()

    @property
    def config(self) -> dict:
        if self.domain == AGENTIC:
            return {"criteria": list(self.criteria), "answer_schema": "table-answer/1"}
        return {"criterion": self.criterion, "metric": self.metric_id, "direction": "lower_is_better"}

    @property
    def config_digest(self) -> str:
        return canonical.digest(self.config)


REGISTRY: dict[str, Scorer] = {
    scorer.id: scorer
    for scorer in (
        Scorer("regression_mae_v1", "1", REGRESSION, ABSOLUTE_ERROR, "mae", mean_absolute_error),
        Scorer("regression_rmse_v1", "1", REGRESSION, ABSOLUTE_ERROR, "rmse", root_mean_squared_error),
        Scorer(CHINOOK_SCORER, CHINOOK_VERSION, AGENTIC, None, None, None, criteria=CHINOOK_CRITERIA),
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
