"""T01 checks for capturing the pinned legacy reference."""

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def capture():
    entry = ROOT / "scripts" / "parity" / "capture_old.py"
    spec = importlib.util.spec_from_file_location("parity_capture_old", entry)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def state(name, kind, step, options):
    return {
        "name": name, "payload": {"summary": {"next_action": {
            "kind": kind, "pause": {"position": {"step_id": step}, "options": options},
        }}},
    }


def test_replay_equality_covers_order_kind_position_and_options(capture):
    discovery = state("01-discover_data", "show_data_card", "discover_data", ["continue", "explain"])
    decision = state("02-prediction_time-pause", "await_user_words", "prediction_time", ["adopt", "change", "explain"])
    original = [discovery, {"name": "running-not-a-screen"}, decision]
    assert capture.replay_signature(original) == capture.replay_signature([discovery, decision])
    assert capture.replay_signature(original) != capture.replay_signature([decision, discovery])
    for changed in (
        state(decision["name"], "propose", "prediction_time", ["adopt", "change", "explain"]),
        state(decision["name"], "await_user_words", "split", ["adopt", "change", "explain"]),
        state(decision["name"], "await_user_words", "prediction_time", ["change", "adopt", "explain"]),
    ):
        assert capture.replay_signature(original) != capture.replay_signature([discovery, changed])


def test_off_default_captures_keep_every_legacy_change_and_choice():
    folder = ROOT / "tests/fixtures/parity/reference-en"
    expected = {
        "02-prediction_time-pause.change", "03-feature_availability-pause.change",
        "04-split-pause.change", "05-error_metric-pause.change", "06-success_criterion-pause.change",
        "08-preprocessing-pause.change", "12-model_variant-pause.change", "14-model_choice-pause.change",
        "16-final_test-pause.change", "17-conclusion-pause.change",
        "06-success_criterion-pause.20-percent", "14-model_choice-pause.ebm",
        "14-model_choice-pause.reference", "17-conclusion-pause.keep-reference",
        "17-conclusion-pause.do-not-conclude", "02-prediction_time-pause.refusal",
    }
    actual = {file.stem for file in folder.glob("*.*.json")} - {
        file.stem for suffix in ("dom", "chat") for file in folder.glob(f"*.{suffix}.json")
    }
    assert expected == actual
    alternatives = {
        "06-success_criterion-pause.20-percent": ("success_criterion", "min_share", 0.2),
        "14-model_choice-pause.ebm": ("model_choice", None, "fit.variant:2"),
        "14-model_choice-pause.reference": ("model_choice", None, "fit.baseline"),
        "17-conclusion-pause.keep-reference": ("conclusion", "verdict", "keep_baseline"),
        "17-conclusion-pause.do-not-conclude": ("conclusion", "verdict", "inconclusive"),
    }
    for fixture, (decision, field, value) in alternatives.items():
        capture = json.loads((folder / f"{fixture}.json").read_text(encoding="utf-8"))
        assert capture["proposal"]["ok"], fixture
        summary = capture["summary"]
        assert summary["next_action"]["decision"] == decision, fixture
        proposal = next(p for p in summary["open_proposals"]
                        if p["proposal_id"] == summary["next_action"]["proposal_id"])
        assert (proposal["value"][field] if field else proposal["value"]) == value, fixture
    for file in folder.glob("*.change.json"):
        change = json.loads(file.read_text(encoding="utf-8"))
        observation = change["observation"]
        assert observation["selected"] == {"id": "change", "label": "Change something"}, file.name
        assert observation["prompt"] == "What do you want to change?", file.name
        assert observation["revisionBefore"] == observation["revisionAfter"], file.name
        assert observation["confirmation_count"] == 0, file.name
        assert change["pause"]["option_labels"]["change"] == observation["selected"]["label"], file.name
        assert "_synthetic" not in change["before_proposal"], file.name
    refusal = json.loads((folder / "02-prediction_time-pause.refusal.json").read_text(encoding="utf-8"))
    assert refusal["refusal"]["ok"] is False
    assert refusal["refusal"]["error"]["code"] == "ambiguous_confirmation"
    assert refusal["refusal"]["error"]["message"] == "There is no proposal missing-proposal; propose first."
    assert refusal["summary"]["next_action"]["kind"] == "await_user_words"


def test_default_capture_preserves_the_eighteen_english_pauses():
    folder = ROOT / "tests/fixtures/parity/reference-en"
    keep = {
        "01-discover_data": "action",
        "02-prediction_time-pause": "decision",
        "03-feature_availability-pause": "decision",
        "04-split-pause": "decision",
        "05-error_metric-pause": "decision",
        "06-success_criterion-pause": "decision",
        "07-structural_eda-run": "action",
        "08-preprocessing-pause": "decision",
        "09-train_eda-run": "action",
        "10-train_eda-read": "action",
        "11-models-run": "action",
        "12-model_variant-pause": "decision",
        "13-model_choice-run": "action",
        "14-model_choice-pause": "decision",
        "15-final_test-run": "action",
        "16-final_test-pause": "decision",
        "17-conclusion-pause": "decision",
        "18-done": "complete",
    }
    files = {file.stem: file for file in folder.glob("*.json") if "." not in file.stem}
    files = {name: file for name, file in files.items() if "@" not in name}
    assert set(files) == set(keep)
    labels = {
        "action": {"continue": "Let's continue", "explain": "Explain first"},
        "decision": {"adopt": "I adopt this decision", "change": "Change something", "explain": "Explain first"},
        "complete": {},
    }
    for name, kind in keep.items():
        state = json.loads(files[name].read_text(encoding="utf-8"))
        assert state["summary"]["language"] == "en", name
        pause = state["summary"]["next_action"]["pause"]
        assert pause["kind"] == kind, name
        assert pause["options"] == list(labels[kind]), name
        assert pause["option_labels"] == labels[kind], name
        assert state["digest"]["revision"] == state["summary"]["revision"], name
        assert state["data_card"].strip(), name


def test_english_screen_dom_and_chat_corpus():
    folder = ROOT / "tests/fixtures/parity/reference-en"
    dom_files = sorted(folder.glob("*.dom.json"))
    assert len(dom_files) == 15
    assert {file.name.replace(".dom.", ".chat.") for file in dom_files} == {
        file.name for file in folder.glob("*.chat.json")
    }
    for file in dom_files:
        both = json.loads(file.read_text(encoding="utf-8"))
        assert set(both) == {"current", "review"}, file.name
        for surface, elements in both.items():
            assert elements, (file.name, surface)
            assert all(set(element) == {"tag", "classes", "data", "values", "text"} for element in elements)
            assert any(element["values"].get("data-anchor") == "now" for element in elements), (file.name, surface)
            assert any(value.startswith("sc-") for element in elements for value in element["classes"]), (file.name, surface)
        chat = json.loads(file.with_name(file.name.replace(".dom.", ".chat.")).read_text(encoding="utf-8"))
        assert chat, file.name
        for beat in chat:
            if beat["t"] == "picker" and beat["kind"] == "decision":
                assert [(option["id"], option["label"]) for option in beat["options"]] == [
                    ("adopt", "I adopt this decision"),
                    ("change", "Change something"),
                    ("explain", "Explain first"),
                ], file.name
                assert beat["record"]["capturedWords"], file.name


def test_three_what_if_states():
    folder = ROOT / "tests/fixtures/parity/reference-en"
    files = {file.stem: file for file in folder.glob("*@whatif.json")}
    assert set(files) == {
        "12-model_variant-pause@whatif", "14-model_choice-pause@whatif", "18-done@whatif",
    }
    for name, file in files.items():
        state = json.loads(file.read_text(encoding="utf-8"))
        assert state["source"] == name
        assert state["surface"] == "whatif"
        assert state["elements"]
