"""The CLI reads the kept Bike figures without a lock and matches the pinned reader.

The expected findings for the numeric cases are recorded from OLD at 4ef4925.
The tests use those literals so CI does not need an OLD checkout.
"""

import io
from pathlib import Path

import pytest
from _assess_helpers import assess, fresh_study, observation_set_id, references_id, snapshot
from _study_helpers import run_json

from hypotrail.core import attempts as attempt_records
from hypotrail.core import figures, lock
from hypotrail.core import study as layout


def _synthetic_results(values, *, differences=(), units=(), rates=()):
    """Give the pinned and ported readers identical synthetic result data."""
    def result(record_id, entries):
        return {"result_id": record_id, "values": entries, "current": True, "integrity": "ok", "n_rows": None}

    results = {"fixture.read": result("fixture", {"values": list(values), "deltas": list(differences), "rates": list(rates)})}
    for index, unit in enumerate(units):
        key = f"unit.{index}"
        results[key] = result(key, {"unit": unit})
    return results


def _synthetic_findings(text, values, *, differences=(), units=(), rates=()):
    from hypotrail.core.numtrace import findings

    reported = findings(text, _synthetic_results(values, differences=differences, units=units, rates=rates))
    assert all(text[item["start"]:item["end"]] == item["number"] for item in reported)
    return reported


def test_numbers_check_is_a_read_of_the_kept_bike_study(tmp_path, monkeypatch):
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    observations = observation_set_id(study, attempts["seasonal_7"])
    code, payload, err = assess(study, observations, "regression_mae_v1", references_id(study))
    assert code == 0, (payload, err)
    [metric] = payload["assessment"]["metrics"]
    assert metric["id"] == "mae" and f'{metric["value"]:,.2f}' == "1,090.79"

    original = snapshot(study)
    text_file = tmp_path / "draft.txt"
    user_file = tmp_path / "user.txt"
    text_file.write_text("The recorded MAE is 1,090.79 rentals per day.", encoding="utf-8")
    user_file.write_text("Our external target is 43.125 rentals per day.", encoding="utf-8")
    original_open = Path.open

    def no_lock(*args, **kwargs):
        pytest.fail("a number check must never take or probe the Study lock")

    def safe_open(path, *args, **kwargs):
        if path.is_relative_to(study):
            assert path.name in {"study.json", "attempt.json", "observation_set.json", "assessment.json", "comparison.json"}, path.name
            mode = args[0] if args else kwargs.get("mode", "r")
            assert mode in {"r", "rb"}
        return original_open(path, *args, **kwargs)

    command = ("numbers", "check", "--study", study)
    with monkeypatch.context() as patch:
        patch.setattr(lock, "_fcntl", no_lock)
        patch.setattr(lock, "writer_lock", no_lock)
        patch.setattr(lock, "is_held", no_lock)
        patch.setattr(Path, "open", safe_open)
        code, payload, err = run_json(*command, "--text", text_file)
        assert (code, payload, err) == (0, {"ok": True, "clean": True, "findings": []}, "")

        wrong = "The recorded MAE is 1,090.80 rentals per day. We used five folds."
        patch.setattr("sys.stdin", io.StringIO(wrong))
        code, payload, err = run_json(*command, "--text", "-")
        assert code == 0 and not err and not payload["clean"]
        assert [item["code"] for item in payload["findings"]] == ["untraceable_number"] * 2
        assert [item["number"] for item in payload["findings"]] == ["1,090.80", "five"]

        text_file.write_text("Our external target is 43.125 rentals per day.", encoding="utf-8")
        assert run_json(*command, "--text", text_file)[1]["findings"][0]["number"] == "43.125"
        assert run_json(*command, "--text", text_file, "--user-text", user_file) == (
            0, {"ok": True, "clean": True, "findings": []}, ""
        )
    assert snapshot(study) == original


def test_protected_study_refuses_the_check_before_reading_text(tmp_path, monkeypatch):
    monkeypatch.setattr("hypotrail.core.study.read_spec", lambda study: {"domain": "ranking", "partition": "held_out"})

    class UnreadableInput:
        def read(self):
            pytest.fail("the command read a text before refusing its protected Study")

    monkeypatch.setattr("sys.stdin", UnreadableInput())
    code, payload, _ = run_json("numbers", "check", "--study", tmp_path, "--text", "-")
    assert code == 2 and payload["error"]["code"] == "RANKING_HELD_OUT_REFUSED"


def test_english_forms_keep_the_value_and_precision_of_the_whole_number():
    text = "The rates were twenty-one percent and one in nine. Five folds used three quarters of the rows."
    assert _synthetic_findings(text, [0.209, 0.111, 4.8, 0.749]) == []
    assert [finding["number"] for finding in _synthetic_findings(text, [])] == [
        "twenty-one percent", "one in nine", "Five", "three quarters"
    ]

    text = "The difference was −2.75, the sample 1.5M, and the rate .5%. See section 6 on 2026-11-28."
    assert _synthetic_findings(text, [-2.746, 1_530_000], rates=[0.0051]) == []
    assert [finding["number"] for finding in _synthetic_findings(text, [])] == ["−2.75", "1.5M", ".5%"]

    text = "The first step fits one model and both predictors."
    assert _synthetic_findings(text, []) == []


def test_malformed_scales_report_the_pinned_readers_lexemes():
    text = "The two claims are 1×10⁻⁺ and 1e999. We also wrote 241_000."
    assert [item["number"] for item in _synthetic_findings(text, [1, 10, 241_000])] == ["10⁻⁺", "1e999", "241_000"]


def test_a_scaled_denominator_prevents_a_partial_ratio_match():
    text = "One in five hundred customers."
    [finding] = _synthetic_findings(text, [0.2])
    assert finding["code"] == "untraceable_number" and finding["number"] == "five hundred"


@pytest.mark.parametrize(
    ("text", "value", "shown"),
    [
        ("We had five-hundred rows.", 5, "five-hundred"),
        ("One in five-hundred customers.", 0.2, "five-hundred"),
        ("We used five-hundred and twenty rows.", 20, "five-hundred and twenty"),
        ("Twenty-one-thousand calls.", 21, "Twenty-one-thousand"),
        ("We counted two thousand five-hundred clients.", 500, "two thousand five-hundred"),
        ("We had five and hundred rows.", 100, "five and hundred"),
        ("We had two and five-hundred rows.", 5, "two and five-hundred"),
    ],
)
def test_spoken_scales_joined_by_hyphens_or_spaces_are_reported_as_a_whole(text, value, shown):
    assert [(item["code"], item["number"]) for item in _synthetic_findings(text, [value])] == [("untraceable_number", shown)]


def test_bare_points_use_the_studys_unit_when_it_is_points():
    assert _synthetic_findings("The result is 7 points.", [7], units=["points"]) == []
    assert _synthetic_findings("The result is 7 points.", [7], units=[" Points  (score) "]) == []
    assert _synthetic_findings("The result is 7 points.", [7])[0]["number"] == "7"
    assert _synthetic_findings("The result is 7 percentage points.", [7], units=["points"])[0]["number"] == "7"
    assert _synthetic_findings("The difference is 7 percentage points.", [], differences=[0.07], units=["points"]) == []


@pytest.mark.parametrize(
    ("shown", "value"),
    [
        ("7-per-cent", 0.07),
        ("7 per-cent", 0.07),
        ("7\u00a0per\u00a0cent", 0.07),
        ("7 per\u00a0mille", 0.007),
        ("7\u202f- per\u2009mil", 0.007),
        ("7 per cent", 0.07),
        ("7‰", 0.007),
    ],
)
def test_written_rates_trace_as_a_whole_at_their_rate_scale(shown, value):
    text = f"The result was {shown}."
    assert [item["number"] for item in _synthetic_findings(text, [7])] == [shown]
    assert _synthetic_findings(text, [value]) == []


@pytest.mark.parametrize("shown", ["7percent", "7permille"])
def test_glued_word_rates_are_reported_as_unsupported(shown):
    assert [item["number"] for item in _synthetic_findings(f"The result was {shown}.", [7, 0.07, 0.007])] == [shown]


@pytest.mark.parametrize(
    ("shown", "value"),
    [("7\t%", 0.07), ("7\n%", 0.07), ("7\u2003%", 0.07), ("7\t‰", 0.007), ("7%increase", 0.07), ("7‰increase", 0.007)],
)
def test_symbol_rates_keep_the_pinned_engines_legacy_boundaries(shown, value):
    text = f"The result was {shown}."
    [item] = _synthetic_findings(text, [7])
    assert item["code"] == "untraceable_number"
    assert item["number"] == shown.removesuffix("increase")
    assert _synthetic_findings(text, [value]) == []


def test_hyphenated_point_adjective_is_a_count_in_the_pinned_engine():
    assert _synthetic_findings("There was a 7-point improvement.", [7]) == []


@pytest.mark.parametrize("noun", ["steps", "pauses", "decisions"])
def test_an_unsupplied_read_does_not_authorize_a_zero_count(noun):
    assert [item["number"] for item in _synthetic_findings(f"The Study recorded 0 {noun}.", [])] == ["0"]


def test_numbers_check_reads_only_a_development_comparisons_aggregate_figures(tmp_path, monkeypatch):
    study, attempts = fresh_study(tmp_path, "seasonal_7", "ridge_v1")
    assessments = []
    for attempt in attempts.values():
        observations = observation_set_id(study, attempt)
        code, payload, err = assess(study, observations, "regression_mae_v1", references_id(study))
        assert code == 0, (payload, err)
        assessments.append(payload["assessment"])
    control, candidate = (assessment["assessment_id"] for assessment in assessments)
    code, payload, err = run_json("compare", "--study", study, "--control", control, "--candidate", candidate)
    assert code == 0, (payload, err)
    comparison = payload["comparison"]
    figure = figures.entry(study, comparison)
    assert figure["unavailable"] is None
    shown = f'{figure["quartiles"]["median"]:.3f}'
    (study / "protected-pairs.csv").write_text("Synthetic guard marker", encoding="utf-8")
    original = snapshot(study)
    allowed_pairs = study / comparison["paired_deltas_ref"]["path"]
    protected_comparison = {
        **comparison,
        "comparison_id": "protected-comparison",
        "roles": {**comparison["roles"], "candidate_assessment_id": "protected-assessment"},
        "paired_deltas_ref": {**comparison["paired_deltas_ref"], "path": "protected-pairs.csv"},
    }
    protected_assessment = {**assessments[1], "assessment_id": "protected-assessment", "observation_set_id": "protected-observations"}
    manifests = {identifier: layout.read_manifest(study, identifier) for identifier in layout.attempt_ids(study)}
    manifests["protected-attempt"] = {"attempt_id": "protected-attempt"}
    read_observation_set = attempt_records.read_observation_set
    open_path = Path.open
    read_pairs = []

    def read_observations(folder, manifest):
        if manifest["attempt_id"] == "protected-attempt":
            return {"observation_set_id": "protected-observations", "provenance": {"partition": "public_check"}}
        return read_observation_set(folder, manifest)

    def safe_open(path, *args, **kwargs):
        if path.is_relative_to(study):
            if path == allowed_pairs:
                read_pairs.append(path)
            else:
                assert path.name in {"study.json", "observation_set.json"}, path.name
            assert (args[0] if args else kwargs.get("mode", "r")) in {"r", "rb"}
        return open_path(path, *args, **kwargs)

    def no_lock(*args, **kwargs):
        pytest.fail("a number check must never take or probe the Study lock")

    with monkeypatch.context() as patch:
        patch.setattr(lock, "_fcntl", no_lock)
        patch.setattr(lock, "writer_lock", no_lock)
        patch.setattr(lock, "is_held", no_lock)
        patch.setattr(layout, "attempt_ids", lambda folder: manifests)
        patch.setattr(layout, "read_manifest", lambda folder, identifier: manifests[identifier])
        patch.setattr(layout, "assessment_records", lambda folder: [*assessments, protected_assessment])
        patch.setattr(layout, "comparison_records", lambda folder: [comparison, protected_comparison])
        patch.setattr(attempt_records, "read_observation_set", read_observations)
        patch.setattr(Path, "open", safe_open)
        patch.setattr("sys.stdin", io.StringIO(f"The median paired difference was {shown} rentals per day."))
        code, payload, err = run_json("numbers", "check", "--study", study, "--text", "-")
        assert (code, payload, err) == (0, {"ok": True, "clean": True, "findings": []}, "")
        assert read_pairs == [allowed_pairs]
    assert snapshot(study) == original
