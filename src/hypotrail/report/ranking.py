"""Aggregate-only output for a protected ranking Study."""

from hypotrail.core import evaluator, write_journal
from hypotrail.core import study as layout


def assessment(record):
    return {key: record[key] for key in ("assessment_id", "counts", "metrics", "ranking_dates")}


def comparison(record):
    interval = record["interval"]
    return {
        "comparison_id": record["comparison_id"],
        **record["roles"],
        "delta": record["delta"],
        "coverage": record["coverage"],
        "interval": {key: interval[key] for key in (
            "level", "method", "unit", "resamples", "units", "lower", "upper", "reason", "usable_resamples", "omitted_dates"
        )},
    }


def aggregates(study):
    """Project the validated records under the caller's Study lock."""
    return {
        "partition": evaluator.HELD_OUT,
        "write_sequence": write_journal.write_sequence(study),
        "assessments": [assessment(record) for record in layout.assessment_records(study)],
        "comparisons": [comparison(record) for record in layout.comparison_records(study)],
    }
