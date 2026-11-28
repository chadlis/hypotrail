"""Aggregate-only output for a protected ranking Study."""

import uuid

from hypotrail.core import evaluator, intervals, scorers, write_journal
from hypotrail.core import study as layout
from hypotrail.core.comparison import RANKING_DELTA_DEFINITION
from hypotrail.core.errors import IntegrityError


ASSESSMENT_COUNTS = ("expected", "attempted", "produced", "scored", "unscored", "errored")
DATE_COUNTS = ("scored", "omitted_no_positives")
COVERAGE_COUNTS = ("expected", "control_scored", "candidate_scored", "paired")
INTERVAL_COUNTS = ("resamples", "units", "usable_resamples", "omitted_dates")
ASSESSMENT_ROLES = ("control_assessment_id", "candidate_assessment_id")


def _invalid_record():
    return IntegrityError("CONTRACT_VIOLATION", "The protected ranking record cannot supply an aggregate", stage="contract")


def _record_id(value):
    try:
        identifier = uuid.UUID(value)
    except ValueError:
        raise _invalid_record() from None
    if identifier.version != 4 or str(identifier) != value:
        raise _invalid_record()
    return value


def _counts(record, names):
    counts = {name: record.get(name) for name in names}
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise _invalid_record()
    return counts


def _metric(record):
    value = record["value"]
    return {
        "id": scorers.RANKING_METRIC,
        "value": value,
        "unit": "proportion",
        "direction": "higher_is_better",
        "denominator": record["denominator"],
        "status": "unscored" if value is None else "scored",
        "reason": scorers.RANKING_NO_POSITIVES if value is None else None,
    }


def _delta(record):
    value = record["value"]
    reason = record.get("reason")
    return {
        "metric": scorers.RANKING_METRIC,
        "value": value,
        "unit": "proportion",
        "definition": RANKING_DELTA_DEFINITION,
        **({"reason": reason} if value is None and reason in (scorers.RANKING_NO_POSITIVES, intervals.DELTA_WITHHELD) else {}),
    }


def _interval(record):
    if record.get("unit") != intervals.ENTITY:
        raise _invalid_record()
    return {
        "method": intervals.METHOD,
        "unit": intervals.ENTITY,
        **{key: record[key] for key in ("level", "lower", "upper", "reason")},
        **_counts(record, INTERVAL_COUNTS),
    }


def assessment(record):
    return {
        "assessment_id": _record_id(record["assessment_id"]),
        "counts": {**_counts(record["counts"], ASSESSMENT_COUNTS), "correct": None, "incorrect": None},
        "metrics": [_metric(record["metrics"][0])],
        "ranking_dates": _counts(record["ranking_dates"], DATE_COUNTS),
    }


def comparison(record):
    return {
        "comparison_id": _record_id(record["comparison_id"]),
        **{role: _record_id(record["roles"][role]) for role in ASSESSMENT_ROLES},
        "delta": _delta(record["delta"]),
        "coverage": _counts(record["coverage"], COVERAGE_COUNTS),
        "interval": _interval(record["interval"]),
    }


def aggregates(study):
    """Project the validated records under the caller's Study lock."""
    return {
        "partition": evaluator.HELD_OUT,
        "write_sequence": write_journal.write_sequence(study),
        "assessments": [assessment(record) for record in layout.assessment_records(study)],
        "comparisons": [comparison(record) for record in layout.comparison_records(study)],
    }
