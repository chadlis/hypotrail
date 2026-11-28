"""The number check uses the kept Bike MAE without taking a Study lock."""

import io
from pathlib import Path

import pytest
from _assess_helpers import assess, fresh_study, observation_set_id, references_id, snapshot
from _study_helpers import run_json

from hypotrail.core import lock


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
    from hypotrail.core.numtrace import findings

    text = "The rates were twenty-one percent and one in nine. Five folds used three quarters of the rows."
    assert findings(text, [0.209, 0.111, 4.8, 0.749]) == []
    assert [finding["number"] for finding in findings(text, [])] == [
        "twenty-one percent", "one in nine", "Five", "three quarters"
    ]

    text = "The difference was −2.75, the sample 1.5M, and the rate .5%. See section 6 on 2026-11-28."
    assert findings(text, [-2.746, 1_530_000, 0.0051]) == []
    assert [finding["number"] for finding in findings(text, [])] == ["−2.75", "1.5M", ".5%"]

    text = "The first step fits one model and both predictors."
    assert findings(text, []) == []


def test_malformed_scales_are_untraceable_as_a_whole():
    from hypotrail.core.numtrace import findings

    text = "The two claims are 1×10⁻⁺ and 1e999. We also wrote 241_000."
    assert [item["number"] for item in findings(text, [1, 10, 241_000])] == ["1×10⁻⁺", "1e999", "241_000"]
