"""The accompanied Bike path as one end-to-end test: the demonstration to its Pending decision, then the reads a guide gives the person,
through the CLI. No model is called."""

import json

from _client_helpers import LESSON_KEPT, first_difference, lesson_outputs
from _lesson_helpers import demonstration_until, lesson, resolved
from _study_helpers import run_json


def test_bike_accompanied_from_the_demonstration_to_record(tmp_path):
    work = tmp_path / "work"
    demonstration_until(work, "task 1")
    study = work / "bike"
    code, status, err = run_json("status", "--study", study)
    assert code == 0 and status["pending_decisions"], err
    code, figures, err = run_json("figures", "--study", study)
    assert code == 0, err
    reads = {"status": status, "figures": figures}

    code, read, err = lesson(study)
    assert code == 0, err
    assert (read["ok"], read["track"], read["write_sequence"]) == (True, "temporal_regression", status["write_sequence"])
    assert [card["kind"] for card in read["cards"]] == ["comparisons"]
    for card in read["cards"]:
        for key_path in card["key_paths"]:
            assert resolved(reads[key_path["read"]], key_path["path"]) != [], (card["kind"], key_path)
    assert run_json("status", "--study", study)[1] == status

    # The `lesson` reads the client's tests are built from equal those a fresh run of the demonstration gives, both ways.
    made = lesson_outputs(tmp_path / "lesson-reads")
    names = sorted(path.name for path in LESSON_KEPT.iterdir())
    assert sorted(made) == names
    for name in names:
        kept = (LESSON_KEPT / name).read_text(encoding="utf-8")
        if name.endswith(".out"):
            assert first_difference(json.loads(kept), json.loads(made[name])) is None, name
        else:
            assert kept == made[name], name
