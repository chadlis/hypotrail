"""The Scorer registry: static and closed (SPEC §8).

A `SCORER_ID` is a key of `REGISTRY`, looked up as a string. Nothing is imported, evaluated or
looked up by name from the given text, so no Python can be loaded through it. It registers the two
Scorers of the temporal regression Track and the two of the agent Track, `chinook_contract_v1` (#68)
and `text_facts_v1` (#265), and the ranking Scorer. A Scorer carries the `domain` of the Observation sets it can score and a
`config` that is hashed into `config_digest`. A regression Scorer has one Criterion and the pure
function that aggregates it into its Metric. An agent Scorer has its Criteria, its per-Episode
function (`episode`) and the role of the Study artifact that function reads (`reads`: the answer
schema or the scoring config), and no aggregation of its own: the shares of an agent Assessment are
counted from the states of its Criteria. Each scoring function stays in its own module of the core
(ADR 0001): `hypotrail.core.chinook_contract` and `hypotrail.core.text_facts`.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

from hypotrail.core import canonical
from hypotrail.core.chinook_contract import CRITERIA as CHINOOK_CRITERIA
from hypotrail.core.chinook_contract import SCORER_NAME as CHINOOK_SCORER
from hypotrail.core.chinook_contract import SCORER_VERSION as CHINOOK_VERSION
from hypotrail.core import chinook_contract, text_facts
from hypotrail.core.errors import InvalidInputError

REGRESSION = "regression"
AGENTIC = "agentic"
RANKING = "ranking"
RANKING_SCORER = "ranking_recall_at_top_v1"
RANKING_METRIC = "recall_at_top_fraction"
RANKING_NO_POSITIVES = "no_dates_with_positives"
ABSOLUTE_ERROR = "absolute_error"
ANSWER_SCHEMA = "answer_schema"
SCORING_CONFIG = "scoring_config"


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
    # agent Scorers: the function of one Episode, (answer text, Reference record or None, what `reads` names, normalized entry) -> {"criteria": [...]}
    episode: Callable | None = None
    reads: str | None = None
    limitations: tuple = ()

    @property
    def config(self) -> dict:
        if self.domain == AGENTIC and self.reads == SCORING_CONFIG:
            return {"criteria": list(self.criteria), "answer_shape": "text", "reads": SCORING_CONFIG}
        if self.domain == AGENTIC:
            return {"criteria": list(self.criteria), "answer_schema": "table-answer/1"}
        if self.domain == RANKING:
            return {"metric": self.metric_id, "direction": "higher_is_better", "fraction": "0.1", "tie_break": "item_id"}
        return {"criterion": self.criterion, "metric": self.metric_id, "direction": "lower_is_better"}

    @property
    def config_digest(self) -> str:
        return canonical.digest(self.config)

    def config_digest_for(self, scoring_config_sha256: str | None) -> str:
        """The digest an Assessment records: the registry config, together with the Study's scoring config for a Scorer that reads one."""
        if self.reads != SCORING_CONFIG:
            return self.config_digest
        return canonical.digest({"registry": self.config, "scoring_config_sha256": scoring_config_sha256})


def _chinook_episode(text, reference, schema, entry):
    return chinook_contract.apply_scorer(chinook_contract.score_episode, text, reference, schema, entry["trace"])


def _text_facts_episode(text, reference, config, entry):
    return text_facts.apply(text, reference, config, entry.get("outcome"))


TEXT_FACTS_LIMITATIONS = (
    "The Repeats of a Case are not independent samples, nor are the paraphrases of a group: the shares carry no confidence interval and no significance claim.",
    "The Criteria read identifiers, numbers, dates, texts and phrases in the answer; they do not judge whether the rest of the prose is right.",
    "The shares describe the Cases of this Workload, not assistants in general.",
)


REGISTRY: dict[str, Scorer] = {
    scorer.id: scorer
    for scorer in (
        Scorer("regression_mae_v1", "1", REGRESSION, ABSOLUTE_ERROR, "mae", mean_absolute_error),
        Scorer("regression_rmse_v1", "1", REGRESSION, ABSOLUTE_ERROR, "rmse", root_mean_squared_error),
        Scorer(RANKING_SCORER, "1", RANKING, None, RANKING_METRIC, None),
        Scorer(CHINOOK_SCORER, CHINOOK_VERSION, AGENTIC, None, None, None, criteria=CHINOOK_CRITERIA, episode=_chinook_episode, reads=ANSWER_SCHEMA),
        Scorer(
            text_facts.SCORER_NAME,
            text_facts.SCORER_VERSION,
            AGENTIC,
            None,
            None,
            None,
            criteria=text_facts.CRITERIA,
            episode=_text_facts_episode,
            reads=SCORING_CONFIG,
            limitations=TEXT_FACTS_LIMITATIONS,
        ),
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
