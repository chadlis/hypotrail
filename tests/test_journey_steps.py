import copy
import json
from pathlib import Path

from hypotrail.core.journey import steps


KEPT_STATUS = Path(__file__).resolve().parents[1] / "clients/vscode/test/cli/journey"
ORDER = [
    {"step": "error_metric", "name": "Error measure", "short": "Measure",
     "title": "Choose the error measure", "moment": "frame", "decision": True, "depends_on": []},
    {"step": "model_choice", "name": "Model choice", "short": "Choice",
     "title": "Choose the model", "moment": "work", "decision": True, "depends_on": ["error_metric"]},
    {"step": "models", "name": "Models", "short": "Models",
     "title": "Compare the models", "moment": "work", "decision": False, "depends_on": []},
]
MOMENTS = [{"id": "frame", "title": "Frame the change"}, {"id": "work", "title": "Work and compare"}]
RECAP = "The plan, in order: Frame the change (Error measure); Work and compare (Model choice, Models)."


def kept_status(state):
    payload = json.loads((KEPT_STATUS / f"{state}.status.out").read_text(encoding="utf-8"))
    assert payload["exposures"]["entries"] == []
    assert all(attempt["partition"] == "dev" for attempt in payload["attempts"])
    return payload


def completion(status):
    assessments = [assessment["assessment_id"] for assessment in status["assessments"]]
    comparisons = [comparison["comparison_id"] for comparison in status["comparisons"]]
    return {
        "error_metric": {"complete": True, "results": []},
        "model_choice": {"complete": len(assessments) == 2, "results": assessments},
        "models": {"complete": bool(comparisons), "results": comparisons},
    }


def decision(step, option_id, option, sequence, *, applies=True):
    # The journey Decision writer arrives in T10. These rows extend an unchanged kept read in memory.
    return {
        "question_id": f"journey:{step}",
        "decision_id": f"test-decision-{sequence}",
        "option_id": option_id,
        "option": option,
        "write_sequence": sequence,
        "applies": applies,
        "level": "panel",
    }


def with_decisions(status, *rows):
    sequence = max([status["write_sequence"], *(row["write_sequence"] + 1 for row in rows)])
    return {**status, "write_sequence": sequence, "decisions": [*status["decisions"], *rows]}


def test_kept_bike_development_records_determine_the_journey_steps():
    initial = kept_status("01-init")
    assessed = kept_status("03-assessments")
    compared = kept_status("05-decided")
    measure = decision("error_metric", "mae", "Mean absolute error", 15)
    choice = decision("model_choice", "ridge", "Ridge", 17)
    newer_measure = decision("error_metric", "rmse", "Root mean squared error", 19)

    view = steps(initial, ORDER, MOMENTS, completion(initial))
    assert view == {
        "total": 3,
        "current": {"step": "error_metric", "n": 1},
        "recap": RECAP + " Current step: Error measure (1 of 3).",
        "moments": [
            {"id": "frame", "title": "Frame the change", "steps": ["error_metric"]},
            {"id": "work", "title": "Work and compare", "steps": ["model_choice", "models"]},
        ],
        "list": [
            {"step": step["step"], "n": n, "name": step["name"], "short": step["short"],
             "title": step["title"], "moment": step["moment"], "state": state,
             "value_words": None, "decision": None, "results": [], "reopened": False}
            for n, (step, state) in enumerate(zip(ORDER, ("current", "upcoming", "upcoming"), strict=True), 1)
        ],
    }
    # Even with an adoption, this step lacks the Track's required Assessments in the initial read.
    view = steps(with_decisions(initial, measure, choice), ORDER, MOMENTS, completion(initial))
    assert view["current"] == {"step": "model_choice", "n": 2}
    assert view["recap"] == RECAP + " Current step: Model choice (2 of 3)."

    view = steps(with_decisions(assessed, measure, choice), ORDER, MOMENTS, completion(assessed))
    assert view["current"] == {"step": "models", "n": 3}
    assert view["list"][1]["results"] == completion(assessed)["model_choice"]["results"]
    assert view["recap"] == RECAP + " Current step: Models (3 of 3)."

    view = steps(with_decisions(compared, measure, choice), ORDER, MOMENTS, completion(compared))
    assert view["current"] is None
    assert view["recap"] == RECAP + " Every step of the plan is done."
    assert [step["state"] for step in view["list"]] == ["done", "done", "done"]
    assert view["list"][2]["decision"] is None
    assert view["list"][2]["results"] == completion(compared)["models"]["results"]

    # Give the Decisions in a different order so the Write sequence decides which option is in force.
    status = with_decisions(compared, newer_measure, choice, measure)
    facts = completion(status)
    before = copy.deepcopy((status, ORDER, MOMENTS, facts))
    view = steps(status, ORDER, MOMENTS, facts)
    assert (status, ORDER, MOMENTS, facts) == before
    first, second, third = view["list"]
    assert first["value_words"] == "Root mean squared error"
    assert first["decision"] == {"decision_id": newer_measure["decision_id"], "option_id": "rmse", "level": "panel"}
    assert second["value_words"] == "Ridge"
    assert second["reopened"]
    assert not first["reopened"] and not third["reopened"]
    assert [step["state"] for step in view["list"]] == ["done", "current", "done"]
    assert view["current"] == {"step": "model_choice", "n": 2}
    assert view["recap"] == RECAP + " Current step: Model choice (2 of 3)."


def test_an_inapplicable_decision_reopens_the_step_until_it_is_adopted_again():
    compared = kept_status("05-decided")
    measure = decision("error_metric", "mae", "Mean absolute error", 15)
    choice = decision("model_choice", "ridge", "Ridge", 17)
    inapplicable = decision("model_choice", "seasonal", "Seasonal", 19, applies=False)
    status = with_decisions(compared, measure, inapplicable, choice)

    view = steps(status, ORDER, MOMENTS, completion(status))
    second = view["list"][1]
    assert second["value_words"] == "Ridge"
    assert second["decision"]["decision_id"] == choice["decision_id"]
    assert second["reopened"]
    assert view["current"] == {"step": "model_choice", "n": 2}

    status = with_decisions(compared, measure, inapplicable)
    view = steps(status, ORDER, MOMENTS, completion(status))
    assert view["list"][1]["reopened"]
    assert view["list"][1]["value_words"] is None
    assert view["list"][1]["decision"] is None

    renewed = decision("model_choice", "ridge", "Ridge", 21)
    status = with_decisions(status, renewed)
    view = steps(status, ORDER, MOMENTS, completion(status))
    assert not view["list"][1]["reopened"]
    assert view["list"][1]["decision"]["decision_id"] == renewed["decision_id"]
    assert view["current"] is None


def test_a_later_dependency_write_reopens_the_dependent_even_when_it_does_not_apply():
    compared = kept_status("05-decided")
    measure = decision("error_metric", "mae", "Mean absolute error", 15)
    choice = decision("model_choice", "ridge", "Ridge", 17)
    later = decision("error_metric", "rmse", "Root mean squared error", 19, applies=False)
    status = with_decisions(compared, later, measure, choice)

    view = steps(status, ORDER, MOMENTS, completion(status))
    measure_step, choice_step, models_step = view["list"]
    assert measure_step["value_words"] == "Mean absolute error"
    assert measure_step["reopened"] and choice_step["reopened"]
    assert not models_step["reopened"]
    assert [step["state"] for step in view["list"]] == ["current", "upcoming", "done"]
