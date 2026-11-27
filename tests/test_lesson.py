"""`lesson --study=DIR --json`: the cards the Study's Track serves, one per kind of step the Study's `status` holds a record of. It takes
no lock, writes nothing and records no Exposure. No model is called."""

import copy
import json
import re
from pathlib import Path

import jsonschema
import pytest
from _chinook_helpers import init_chinook
from _compare_helpers import assessed, compare
from _lesson_helpers import LESSON, demonstration_until, lesson, resolved
from _review_helpers import decide
from _study_helpers import ROOT, init_study, run_cli

KEPT = ROOT / "clients" / "vscode" / "test" / "cli" / "demonstration"
CLIENT_KEPT = KEPT.parent
DATA = ROOT / "src" / "hypotrail" / "ml" / "lesson.json"
AGENTIC_DATA = ROOT / "src" / "hypotrail" / "agentic" / "lesson.json"
# The cards of each Track, by the name of its module under `hypotrail`.
TRACK_DATA = {"ml": DATA, "agentic": AGENTIC_DATA}
# The kept reads of the client's Chinook Studies: each kept `status` read, with the kept `figures` read of the same Study when one is kept.
CHINOOK_KEPT = {
    "status-chinook-pending": "figures-chinook-pending",
    "status-chinook-decided": None,
    "status-chinook-withheld": "figures-chinook-withheld",
    "status-chinook-spread": "figures-chinook-spread",
}
STUDY = "{work}/bike"
LESSON_READ = {"cli": [LESSON, "--study", STUDY, "--json"], "expect": {"exit": 0}}
# The kept states of the demonstration's second Bike Study, each with the step that keeps it.
STATES = {"after-compare": "A5", "after-decide": "task 3"}


def kept_read(state: str, read: str) -> dict:
    return json.loads((KEPT / f"{state}.{read}.out").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def walked(tmp_path_factory):
    """The demonstration up to its Decision, with a `lesson` read at each kept state: {state: the object it printed}, and the Study."""
    work = tmp_path_factory.mktemp("lesson") / "work"
    recording = demonstration_until(work, "task 3", after={step: [copy.deepcopy(LESSON_READ)] for step in STATES.values()})
    reads = [call for call in recording.calls if call["args"][:1] == [LESSON]]
    assert [call["code"] for call in reads] == [0] * len(STATES), [call["err"] for call in reads]
    return dict(zip(STATES, [call["payload"] for call in reads])), work / "bike"


def test_every_key_path_of_every_card_resolves_on_the_kept_reads(walked):
    reads, _ = walked
    assert [card["kind"] for card in reads["after-compare"]["cards"]] == ["comparisons"]
    assert [card["kind"] for card in reads["after-decide"]["cards"]] == ["comparisons", "decisions"]
    for state, read in reads.items():
        assert read["track"] == "temporal_regression"
        assert read["write_sequence"] == kept_read(state, "status")["write_sequence"]
        for card in read["cards"]:
            assert card["key_paths"], card["kind"]
            for key_path in card["key_paths"]:
                assert resolved(kept_read(state, key_path["read"]), key_path["path"]) != [], (state, card["kind"], key_path)


def kept_option_texts() -> set:
    """The text of every option that a kept `status` read of the client or of the demonstration offers for a Pending decision."""
    texts = set()
    for path in [*CLIENT_KEPT.glob("status-*.out"), *KEPT.glob("*.status.out")]:
        read = json.loads(path.read_text(encoding="utf-8"))
        texts |= {option["text"] for pending in read.get("pending_decisions", []) for option in pending["options"]}
    return texts


def test_no_card_text_holds_a_number(walked):
    reads, _ = walked
    served = [card for read in reads.values() for card in read["cards"]]
    declared = {track: json.loads(path.read_text(encoding="utf-8"))["cards"] for track, path in TRACK_DATA.items()}
    assert served and all(declared.values())
    every = served + [card for cards in declared.values() for card in cards]
    assert [(card["kind"], part) for card in every for part in ("title", "text") if re.search(r"\d", card[part])] == []
    options = kept_option_texts()
    assert options
    assert [(card["kind"], option) for card in every for option in options if option.casefold() in card["text"].casefold()] == []


@pytest.mark.parametrize("track", sorted(TRACK_DATA))
def test_each_card_text_holds_at_most_one_sentence_on_how_to_read_it(track):
    for card in json.loads(TRACK_DATA[track].read_text(encoding="utf-8"))["cards"]:
        sentences = re.split(r"(?<=\.) ", card["text"])
        assert len([sentence for sentence in sentences if sentence.startswith("Read ")]) <= 1, card["kind"]


@pytest.mark.parametrize("track", sorted(TRACK_DATA))
def test_the_schema_refuses_a_planted_card(track):
    import importlib

    module = importlib.import_module(f"hypotrail.{track}.lesson")
    data = json.loads(TRACK_DATA[track].read_text(encoding="utf-8"))
    module.validator().validate(data)
    card = data["cards"][0]
    planted = [
        {**card, "kind": "rankings"},
        {key: value for key, value in card.items() if key != "key_paths"},
        {**card, "level": "beginner"},
    ]
    for wrong in planted:
        with pytest.raises(jsonschema.ValidationError):
            module.validator().validate({**data, "cards": [*data["cards"], wrong]})


def test_a_track_with_no_cards_refuses(tmp_path, monkeypatch):
    from hypotrail import cli

    study, _ = init_chinook(tmp_path)
    # A planted dispatch in which the agent Track serves no cards: both Tracks serve cards now.
    monkeypatch.setattr(cli, "_lesson_track", lambda domain: None)
    code, refused, _ = lesson(study)
    assert code == 2
    assert refused["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert refused["error"]["details"] == {"command": LESSON, "study_domain": "agentic"}


def test_every_agentic_key_path_resolves_on_the_kept_chinook_reads(tmp_path):
    from _client_helpers import STUDIES

    from hypotrail.agentic import lesson as module

    assert [card["kind"] for card in module.cards()] == list(module.KINDS)
    for name, figures in CHINOOK_KEPT.items():
        (tmp_path / name).mkdir()
        study = STUDIES[name](tmp_path / name)
        status = json.loads((CLIENT_KEPT / f"{name}.out").read_text(encoding="utf-8"))
        kept = {"status": status, "figures": None if figures is None else json.loads((CLIENT_KEPT / f"{figures}.out").read_text(encoding="utf-8"))}
        live = {read: run_cli(read, f"--study={study}", "--json") for read in ("status", "figures")}
        assert all(code == 0 for code, _, _ in live.values()), name
        code, read, err = lesson(study)
        assert code == 0, (name, err)
        assert (read["track"], read["write_sequence"]) == ("tool_using_agent", status["write_sequence"]), name
        assert [card["kind"] for card in read["cards"]] == [kind for kind in module.KINDS if status.get(kind)], name
        assert read["cards"][-1]["kind"] == ("decisions" if status["decisions"] else "comparisons"), name
        for card in read["cards"]:
            assert card["key_paths"], (name, card["kind"])
            for key_path in card["key_paths"]:
                where = kept[key_path["read"]] or json.loads(live[key_path["read"]][1])
                assert resolved(where, key_path["path"]) != [], (name, card["kind"], key_path)


def test_the_read_writes_nothing(tmp_path):
    study, _, assessments = assessed(tmp_path, "seasonal_7", "ridge_v1")
    code, payload, err = compare(study, assessments["seasonal_7"]["assessment_id"], assessments["ridge_v1"]["assessment_id"])
    assert code == 0, (payload, err)
    decide(study, [payload["comparison"]["comparison_id"]], request_id="lesson-writes-nothing")

    def every_file(folder: Path) -> dict:
        return {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}

    before, sequence = every_file(study), run_cli("status", f"--study={study}", "--json")[1]
    code, read, err = lesson(study)
    assert code == 0 and [card["kind"] for card in read["cards"]] == ["comparisons", "decisions"], err
    assert run_cli(LESSON, f"--study={study}")[0] == 0
    assert every_file(study) == before
    assert run_cli("status", f"--study={study}", "--json")[1] == sequence


def test_a_bike_study_with_no_comparison_gets_no_card_and_its_line_says_none_applies(tmp_path):
    study, _ = init_study(tmp_path)
    code, read, err = lesson(study)
    assert (code, read["ok"], read["cards"]) == (0, True, []), err
    code, out, err = run_cli(LESSON, f"--study={study}")
    assert (code, out.strip()) == (0, "no card applies to this Study yet"), err


def test_the_decisions_card_names_each_reason_a_decision_stops_applying():
    text = next(card["text"] for card in json.loads(DATA.read_text(encoding="utf-8"))["cards"] if card["kind"] == "decisions")
    for words in ("superseded", "no longer holds", "revision"):
        assert words in text, words
