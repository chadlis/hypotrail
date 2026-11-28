import json
from pathlib import Path

import pytest

from hypotrail.core.cite import CitedValue, Unavailable, fill, fmt_number, parse_path


KEPT_STATUS = Path(__file__).resolve().parents[1] / "clients/vscode/test/cli/status-success.out"

# OLD/framework/mlkit/study/content/steps.yaml, cv_regression_steps.models.interpretation.
MODELS = (
    "Out of fold, the mean baseline has a mean absolute error of {{slot:fit.baseline:validation.mae|f2}} "
    "and the linear model of {{slot:fit.linear:validation.mae|f2}}, in the unit of the target."
)


def test_models_template_cites_the_kept_bike_assessments():
    status = json.loads(KEPT_STATUS.read_text(encoding="utf-8"))
    assert {attempt["partition"] for attempt in status["attempts"]} == {"dev"}
    assert status["exposures"]["entries"] == []
    comparison, = status["comparisons"]
    assessments = {assessment["assessment_id"]: assessment for assessment in status["assessments"]}
    # Adapt the legacy slot names to the two development Assessments for this test.
    slots = {"fit.baseline": "control_assessment_id", "fit.linear": "candidate_assessment_id"}

    def resolver(kind, slot, path):
        assert (kind, path) == ("slot", "validation.mae")
        record_id = comparison["roles"][slots[slot]]
        metric, = assessments[record_id]["metrics"]
        assert metric["id"] == "mae"
        return CitedValue(metric["value"], "metrics.0.value", record_id)

    segments = fill(MODELS, resolver)
    assert segments == [
        {"text": "Out of fold, the mean baseline has a mean absolute error of "},
        {"text": "1090.79", "value": 1090.7912087912089, "path": "metrics.0.value",
         "record_id": "00000000-0000-4000-8000-000000000006", "format": "f2"},
        {"text": " and the linear model of "},
        {"text": "1264.73", "value": 1264.730691775682, "path": "metrics.0.value",
         "record_id": "00000000-0000-4000-8000-000000000007", "format": "f2"},
        {"text": ", in the unit of the target."},
    ]
    assert "".join(segment["text"] for segment in segments) == (
        "Out of fold, the mean baseline has a mean absolute error of 1090.79 "
        "and the linear model of 1264.73, in the unit of the target."
    )


@pytest.mark.parametrize(("format_name", "expected"), [
    ("int", "0"), ("pct0", "12%"), ("pct1", "11.5%"), ("pct2", "11.53%"),
    ("f1", "0.1"), ("f2", "0.12"), ("f3", "0.115"), ("f4", "0.1153"),
    ("auto", "0.115"), ("pts0", "12"), ("pts1", "11.5"), ("pts2", "11.53"),
])
def test_legacy_english_formats(format_name, expected):
    assert fmt_number(0.11534, format_name) == expected


@pytest.mark.parametrize(("number", "format_name", "expected"), [
    (3164, "int", "3,164"), (3164.0, "auto", "3,164"), (3842.75, "auto", "3,842.8"),
    (-1234.56, "auto", "-1,234.6"), (-1.25, "auto", "-1.25"), (2.5, "int", "2"),
    (-0.05, "pts1", "-5.0"),
])
def test_legacy_formatting_at_larger_and_negative_values(number, format_name, expected):
    assert fmt_number(number, format_name) == expected


def test_legacy_path_components_keep_bracketed_dots_and_colons():
    assert parse_path("rules.capacity:20.models.[fit.logistic].precision") == [
        "rules", "capacity:20", "models", "fit.logistic", "precision",
    ]
    assert parse_path("metrics.0.value") == ["metrics", "0", "value"]
    assert parse_path("@n_rows") == ["@n_rows"]


@pytest.mark.parametrize("path", ["", "items..count", "items.", "items.[fit.linear"])
def test_malformed_value_paths_are_refused(path):
    with pytest.raises(ValueError, match="path"):
        parse_path(path)


def test_facts_and_named_values_preserve_text_and_numeric_sources():
    def resolver(*reference):
        pytest.fail(f"Unexpected lookup: {reference!r}")

    template = "{{fact:target|a fallback}} / {{fact:unrecorded|Not stated}} / {unit} / {count}."
    assert fill(template, resolver, facts={"target": "Rentals {literal}"}, values={
        "unit": "per day", "count": CitedValue(182, "counts.produced", "assessment", "int"),
    }) == [
        {"text": "Rentals {literal} / Not stated / per day / "},
        {"text": "182", "value": 182, "path": "counts.produced", "record_id": "assessment", "format": "int"},
        {"text": "."},
    ]


def test_references_use_the_longest_known_slot_and_preserve_path_colons():
    def resolver(kind, key, path):
        if kind == "slot":
            assert (key, path) == ("eda.rate_by:origin", "rules.capacity:20.rate")
            return CitedValue(0.11534, "value", "new-record")
        assert (kind, key, path) == ("r", "old-record", "metrics.[fit.linear].mae")
        return CitedValue(1.125, "metrics.0.value", "mapped-record")

    segments = fill("{{slot:eda.rate_by:origin:rules.capacity:20.rate|pct1}} / {{r:old-record.metrics.[fit.linear].mae}}",
                    resolver, slots=("eda.rate_by", "eda.rate_by:origin"))
    assert segments == [
        {"text": "11.5%", "value": 0.11534, "path": "value", "record_id": "new-record", "format": "pct1"},
        {"text": " / "},
        {"text": "1.12", "value": 1.125, "path": "metrics.0.value", "record_id": "mapped-record", "format": "auto"},
    ]


@pytest.mark.parametrize(("unavailable", "expected"), [
    (Unavailable.MISSING, "Not executed yet."),
    (Unavailable.STALE, "Stale, not cited."),
])
def test_an_unavailable_slot_replaces_the_whole_sentence(unavailable, expected):
    def resolver(kind, key, path):
        return CitedValue(182, "counts.produced", "assessment") if key == "computed" else unavailable

    assert fill("{{slot:computed:rows|int}} rows, with MAE {{slot:waiting:mae|f2}}.", resolver) == [{"text": expected}]


def test_an_absent_named_value_is_pending():
    assert fill("Missing {count}.", lambda *_: pytest.fail("Unexpected lookup")) == [{"text": "Not executed yet."}]


@pytest.mark.parametrize("number", [True, float("nan"), float("inf"), "2"])
def test_invalid_numbers_are_refused(number):
    with pytest.raises(ValueError, match="number"):
        fmt_number(number)


def test_unknown_formats_are_refused():
    with pytest.raises(ValueError, match="format"):
        fmt_number(1, "bogus")
