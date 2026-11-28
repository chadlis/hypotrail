import json
from pathlib import Path

import pytest

from hypotrail.core.cite import CitedValue, Unavailable
from hypotrail.core.journey import enrich, pause


REFERENCE = Path(__file__).parent / "fixtures/parity/reference-en"
ADOPTION_OPTIONS = [
    {"id": "adopt", "label": "I adopt this decision", "recommended": True},
    {"id": "change", "label": "Change something", "recommended": False},
    {"id": "explain", "label": "Explain first", "recommended": False},
]
REVISION = "test-revision"
BLOCKED = {
    "kind": "blocked",
    "position": {"step_id": "prediction_time", "completed": 0, "total": 1},
    "options": [],
    "option_labels": {},
    "recommended_option": None,
    "question": None,
}
# Pinned OLD state._reconfirm_action and junior._question on a synthetic prediction moment.
RECONFIRM_VALUE = "Predict before the outcome is measured."
RECONFIRM_QUESTION = "Do you confirm the prediction moment again?"
# Pinned OLD guidance.pause on the same synthetic prediction moment with review=True.
REVIEW = {
    "kind": "decision",
    "position": {"step_id": "prediction_time", "completed": 0, "total": 1},
    "options": ["adopt", "change", "explain"],
    "option_labels": {"adopt": "I adopt this decision", "change": "Change something", "explain": "Explain first"},
    "recommended_option": None,
    "proposal_text": (
        "The prediction moment: Predict before the outcome is measured. "
        "(value recorded by the automatic mode, not yet in your words)."
    ),
    "question": (
        "The prediction moment: Predict before the outcome is measured. "
        "(value recorded by the automatic mode, not yet in your words).\n\nDo you adopt this decision?"
    ),
}


def one_step(*, reopened=False):
    return {
        "total": 1, "current": {"step": "prediction_time", "n": 1},
        "list": [{"step": "prediction_time", "n": 1, "state": "current", "reopened": reopened}],
    }


def legacy_options(captured):
    options = []
    for item in captured["options"]:
        option = {
            "id": item, "label": captured["option_labels"][item],
            "recommended": item == captured["recommended_option"],
        }
        if item == "adopt":
            # The v2 option description comes from the legacy pause's restatement.
            option["description"] = captured["proposal_text"]
        options.append(option)
    return options


@pytest.mark.parametrize(
    ("name", "kind", "step"),
    [
        ("01-discover_data", "action", "discover_data"),
        ("07-structural_eda-run", "action", "structural_eda"),
        ("02-prediction_time-pause", "decision", "prediction_time"),
        ("14-model_choice-pause.change", "choice", "model_choice"),
        ("18-done", "complete", None),
    ],
)
def test_pause_frame_matches_the_t01_english_capture(name, kind, step):
    captured = json.loads((REFERENCE / f"{name}.json").read_text(encoding="utf-8"))
    if "before_proposal" in captured:
        action = captured["before_proposal"]
        # The normal capture supplies the same step order and done states at this position.
        summary = json.loads((REFERENCE / f"{name.removesuffix('.change')}.json").read_text(encoding="utf-8"))["summary"]
    else:
        summary = captured["summary"]
        action = summary["next_action"]
    expected = action["pause"]
    rows = [
        {"step": row["id"], "state": row["status"], "n": n, "reopened": False}
        for n, row in enumerate(summary["plan"], 1)
    ]
    position = next(({"step": row["step"], "n": row["n"]} for row in rows if row["step"] == step), None)
    step_view = {"total": len(rows), "current": position, "list": rows}
    proposal = next(
        (p for p in summary["open_proposals"] if p["proposal_id"] == action.get("proposal_id")),
        {},
    )
    choice_options = action.get("choice_options", [])
    context = {"question": action.get("question") or action.get("junior_message"), "choice_options": choice_options}
    if proposal:
        context["restatement"] = proposal.get("label") or proposal.get("restatement")
    assert expected["kind"] == kind
    assert expected["position"]["step_id"] == step
    assert pause(step_view, REVISION, context) == {
        "schema_version": "journey-pause/1",
        "id": step,
        "kind": expected["kind"],
        "position": {**expected["position"], "n": position["n"] if position else None},
        "question": expected["question"],
        "options": legacy_options(expected),
        "choice_options": choice_options,
        "cited_ids": [REVISION] if step is not None else [],
        "delegable": False,
    }


def test_blocked_matches_the_pinned_legacy_pause_on_synthetic_input():
    # Pinned OLD guidance.pause maps blocked, outcome_unknown and acknowledge_interruption
    # to this frame for a one-step prediction_time plan with status awaiting_confirmation.
    result = pause(one_step(), REVISION, {"availability": "blocked", "question": "Ready?"})
    assert result["kind"] == BLOCKED["kind"]
    assert result["position"] == {**BLOCKED["position"], "n": 1}
    assert result["question"] == BLOCKED["question"]
    assert result["options"] == legacy_options(BLOCKED)
    assert result["choice_options"] == []
    assert not result["delegable"]


def test_running_is_the_v2_non_waiting_pause_for_in_flight_work():
    assert pause(one_step(), REVISION, {
        "availability": "running", "question": "Ready?", "restatement": RECONFIRM_VALUE,
    }) == {
        "schema_version": "journey-pause/1",
        "id": "prediction_time",
        "kind": "running",
        "position": {"step_id": "prediction_time", "n": 1, "total": 1, "completed": 0},
        "question": None,
        "options": [],
        "choice_options": [],
        "cited_ids": [REVISION],
        "delegable": False,
    }


def test_reopened_unchanged_value_uses_the_pinned_old_reconfirmation_question():
    context = {
        "restatement": RECONFIRM_VALUE,
        "value_unchanged": True,
        "reconfirm_question": RECONFIRM_QUESTION,
        "cited_ids": ["assessment", REVISION, "comparison", "assessment"],
    }
    result = pause(one_step(reopened=True), REVISION, context)
    assert result["kind"] == "decision"
    assert result["question"] == f"{RECONFIRM_VALUE}\n\n{RECONFIRM_QUESTION}"
    assert result["options"] == [
        {**ADOPTION_OPTIONS[0], "description": RECONFIRM_VALUE}, *ADOPTION_OPTIONS[1:]
    ]
    assert result["cited_ids"] == [REVISION, "assessment", "comparison"]
    assert context["cited_ids"] == ["assessment", REVISION, "comparison", "assessment"]
    assert not result["delegable"]

    changed = pause(one_step(reopened=True), REVISION, {
        **context, "restatement": "Predict when the outcome is measured.", "value_unchanged": False,
    })
    assert changed["question"] == "Predict when the outcome is measured.\n\nDo you adopt this decision?"


def test_review_has_the_pinned_old_adoption_question_and_no_recommendation():
    result = pause(one_step(), REVISION, {"restatement": REVIEW["proposal_text"], "review": True})
    assert result["kind"] == REVIEW["kind"]
    assert result["position"] == {**REVIEW["position"], "n": 1}
    assert result["question"] == REVIEW["question"]
    assert result["options"] == legacy_options(REVIEW)
    assert not result["delegable"]


@pytest.mark.parametrize(
    ("reopened", "closed"),
    [(False, "Do you adopt this decision?"), (True, RECONFIRM_QUESTION)],
)
def test_decision_question_and_adopt_description_keep_the_restatement_citations(reopened, closed):
    restatement = [
        {"text": "You call the model useful if its out-of-fold mean absolute error is at least "},
        {"text": "10%", "value": 0.1, "path": "criterion.minimum", "record_id": "criterion", "format": "pct0"},
        {"text": " below that of the mean baseline, with the business bar of the brief, an error of at most "},
        {"text": "4.5", "value": 4.5, "path": "brief.business_bar", "record_id": "brief", "format": "f1"},
        {"text": " mpg."},
    ]
    original = [dict(segment) for segment in restatement]
    result = pause(one_step(reopened=reopened), REVISION, {
        "restatement": restatement, "value_unchanged": reopened, "reconfirm_question": RECONFIRM_QUESTION,
    })

    assert result["question"] == [*original, {"text": f"\n\n{closed}"}]
    assert result["options"] == [
        {**ADOPTION_OPTIONS[0], "description": original}, *ADOPTION_OPTIONS[1:]
    ]
    assert restatement == original


@pytest.mark.parametrize(
    ("kind", "choices"),
    [("action", []), ("choice", [{"id": "keep", "label": "Keep the reference"}])],
)
def test_action_and_choice_questions_keep_their_cited_segments(kind, choices):
    question = [
        {"text": "Do you evaluate with this "},
        {"text": "5", "value": 5, "path": "folds", "record_id": "split", "format": "int"},
        {"text": "-fold cross-validation?"},
    ]
    result = pause(one_step(), REVISION, {"question": question, "choice_options": choices})
    assert result["kind"] == kind
    assert result["question"] == question


def reference(name):
    return json.loads((REFERENCE / f"{name}.json").read_text(encoding="utf-8"))


def words(segments):
    return "".join(segment["text"] for segment in segments)


def test_enriched_pause_matches_the_t01_split_capture_with_a_resolver():
    adopted = reference("04-split-pause")["summary"]["next_action"]
    change = reference("04-split-pause.change")
    offered = change["before_proposal"]
    chat = reference("04-split.chat")
    explanation = [part["text"] for part in chat[2]["explain"] if part["k"] == "eng"]
    # The old replay note exercises the field as test data. The new Track's note is not declared here.
    note = change["observation"]["replay_note"]
    why = offered["recommended"]["why"]
    value = adopted["pause"]["proposal_text"]
    proposal = chat[1]["parts"][1]["text"]
    next_text = chat[3]["parts"][1]["text"]
    panel_line = chat[3]["parts"][2]["text"]
    limitations = adopted["pause"]["limitations"]
    commands = [{"command": "explore", "arguments": ["--analysis=split"]}]
    digest = chat[0]["parts"][1]["text"]
    digest_template = digest.replace("318", "{{slot:data:dev|int}}").replace(
        "5 folds", "{{slot:split:folds|int}} folds"
    ).replace("80", "{{slot:data:sealed|int}}")
    templates = {
        "digest": [digest_template],
        "recommended": {"value_id": "declared", "why": why.replace("5 folds", "{{slot:split:folds|int}} folds")},
        "value": {"id": "declared", "words": value},
        "proposal": proposal.replace(value, "{restatement}"),
        "explain": explanation,
        "change_note": note,
        "then": {"text": next_text, "commands": commands},
        "panel_line": panel_line,
        "limitations": limitations,
    }
    numeric = {
        ("slot", "data", "dev"): CitedValue(318, "development.rows", "test-data-card"),
        ("slot", "data", "sealed"): CitedValue(80, "final_test.rows", "test-data-card"),
        ("slot", "split", "folds"): CitedValue(5, "provenance.folds", "test-split"),
    }
    frame = pause(one_step(), REVISION, {"restatement": value})
    result = enrich(frame, templates, lambda kind, key, path: numeric[kind, key, path], values={"restatement": value})
    assert {key: result[key] for key in frame} == frame
    assert "digest" not in frame
    assert words(result["digest"]) == digest
    assert [(s["record_id"], s["path"]) for s in result["digest"] if "record_id" in s] == [
        ("test-data-card", "development.rows"), ("test-split", "provenance.folds"),
        ("test-split", "provenance.folds"), ("test-data-card", "final_test.rows"),
    ]
    assert result["recommended"] == {
        "value_id": "declared",
        "why": [
            {"text": why.partition("5 folds")[0]},
            {"text": "5", "value": 5, "format": "int", "path": "provenance.folds", "record_id": "test-split"},
            {"text": " folds."},
        ],
    }
    assert result["value"] == {"id": "declared", "words": value}
    assert result["proposal"] == proposal
    assert words(result["explain"]) == "\n\n".join(explanation)
    assert result["change_note"] == note
    assert result["then"] == {"text": next_text, "commands": commands}
    assert result["panel_line"] == panel_line
    assert result["limitations"] == limitations


@pytest.mark.parametrize(
    ("availability", "message"),
    [(Unavailable.MISSING, "Not executed yet."), (Unavailable.STALE, "Stale, not cited.")],
)
def test_unavailable_slots_replace_the_individual_text(availability, message):
    template = "You evaluate with this {{slot:split:folds|int}}-fold cross-validation."
    templates = {
        "digest": [template],
        "recommended": {"value_id": "declared", "why": template},
        "value": {"id": "declared", "words": template},
        "proposal": template,
        "explain": [template],
        "change_note": template,
        "then": {"text": template, "commands": []},
        "panel_line": template,
        "limitations": [{"code": "split", "text": template}],
    }
    result = enrich({}, templates, lambda *_: availability)
    assert result == {
        "digest": [{"text": message}],
        "recommended": {"value_id": "declared", "why": [{"text": message}]},
        "value": {"id": "declared", "words": message},
        "proposal": message,
        "explain": [{"text": message}],
        "change_note": message,
        "then": {"text": message, "commands": []},
        "panel_line": message,
        "limitations": [{"code": "split", "text": message}],
    }


@pytest.mark.parametrize("fold_count", ["5", "\u0665"])
def test_numeric_workload_facts_keep_plain_segments_without_a_record_citation(fold_count):
    template = "{{fact:folds|unknown}} folds belong to the Workload."
    result = enrich({}, {"proposal": template}, lambda *_: pytest.fail("Workload facts use no record resolver."),
                    facts={"folds": fold_count})
    assert result["proposal"] == [{"text": f"{fold_count} folds belong to the Workload."}]


def test_digest_drops_whole_trailing_parts_as_in_the_legacy_capture():
    expected = reference("12-model_variant-pause.change")["before_proposal"]["junior_digest"]
    assert len(expected.split()) == 200
    result = enrich({}, {"digest": ["", expected, "A trailing part."]}, lambda *_: Unavailable.MISSING)
    assert words(result["digest"]) == expected


def test_single_long_digest_is_clipped_without_losing_the_remaining_citation():
    templates = {"digest": ["  Here\n {{slot:split:folds|int}} folds. " + " development\t" * 197 +
                            " {{slot:data:dev|int}} rows."]}
    numeric = {"split": CitedValue(5, "folds", "test-split"), "data": CitedValue(318, "rows", "test-data")}
    result = enrich({}, templates, lambda _, key, __: numeric[key])
    assert words(result["digest"]) == "Here 5 folds." + " development" * 197
    assert [segment for segment in result["digest"] if "record_id" in segment] == [
        {"text": "5", "value": 5, "path": "folds", "record_id": "test-split", "format": "int"},
    ]


def test_absent_templates_still_provide_the_enrichment_keys():
    assert enrich({}, {}, lambda *_: Unavailable.MISSING) == {
        "digest": [], "recommended": None, "value": None, "proposal": None, "explain": [],
        "change_note": None, "then": None, "panel_line": None, "limitations": [],
    }
