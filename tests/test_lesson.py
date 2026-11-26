"""`lesson --study=DIR --json`: the cards the Study's Track serves, one per kind of step the Study's `status` holds a record of. It takes
no lock, writes nothing and records no Exposure. No model is called."""

import copy
import json
import re
from pathlib import Path

import jsonschema
import pytest
from _chinook_helpers import init_chinook
from _lesson_helpers import LESSON, demonstration_until, lesson, resolved
from _study_helpers import ROOT, run_cli

KEPT = ROOT / "clients" / "vscode" / "test" / "cli" / "demonstration"
DATA = ROOT / "src" / "hypotrail" / "ml" / "lesson.json"
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


def test_no_card_text_holds_a_number(walked):
    reads, _ = walked
    served = [card for read in reads.values() for card in read["cards"]]
    declared = json.loads(DATA.read_text(encoding="utf-8"))["cards"]
    assert served and declared
    assert [(card["kind"], part) for card in served + declared for part in ("title", "text") if re.search(r"\d", card[part])] == []


def test_the_schema_refuses_a_planted_card():
    from hypotrail.ml import lesson as module

    data = json.loads(DATA.read_text(encoding="utf-8"))
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


def test_a_track_with_no_cards_refuses(tmp_path):
    study, _ = init_chinook(tmp_path)
    code, refused, _ = lesson(study)
    profile_code, profile_out, _ = run_cli("profile", f"--study={study}", "--json")
    expected = json.loads(profile_out.replace("`profile`", f"`{LESSON}`").replace('"command": "profile"', f'"command": "{LESSON}"'))
    assert (code, refused["error"]["code"]) == (profile_code, "UNSUPPORTED_CAPABILITY")
    assert refused == expected


def test_the_read_writes_nothing(walked):
    _, study = walked

    def every_file(folder: Path) -> dict:
        return {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}

    before, sequence = every_file(study), run_cli("status", f"--study={study}", "--json")[1]
    assert lesson(study)[0] == 0
    assert run_cli(LESSON, f"--study={study}")[0] == 0
    assert every_file(study) == before
    assert run_cli("status", f"--study={study}", "--json")[1] == sequence
