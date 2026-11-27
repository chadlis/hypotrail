"""The accompanied Bike path as one end-to-end test: the demonstration to its Pending decision, then the reads a guide gives the person,
through the CLI; and the accompanied agent path, on the demonstration's Chinook Study and on a `chinook_prose` Study. No model is called."""

import json

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


def agentic_reads(study) -> dict:
    """{read: the object it printed} of `status`, `figures` and `lesson` on the Study, through the CLI; each exits 0."""
    reads = {}
    for read in ("status", "figures", "lesson"):
        code, reads[read], err = run_json(read, "--study", study)
        assert code == 0, (read, err)
    return reads


def chinook_prose_compared(tmp_path):
    """A `chinook_prose` Study with its two kept fixtures imported on its dev Cases, each assessed with `text_facts_v1`, and one
    Comparison of the two."""
    from _chinook_helpers import episodes_file, import_agent
    from _study_helpers import EXAMPLES

    prose = EXAMPLES / "chinook_prose"
    study = tmp_path / "prose"
    code, payload, err = run_json("init", "--workload", "chinook_prose", "--study", study)
    assert code == 0, err
    references = payload["references_id"]
    dev = [json.loads(line)["case_id"] for line in (prose / "cases" / "chinook-prose-dev.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    population = episodes_file(tmp_path, [(case_id, 0) for case_id in dev])
    assessments = []
    for name in ("concise", "verbose"):
        code, attempt, err = import_agent(study, prose / "fixtures" / f"answers-{name}.jsonl", population, f"import-{name}")
        assert code == 0, err
        code, payload, err = run_json(
            "assess", "--study", study, "--observations", attempt["observation_set_id"], "--scorer", "text_facts_v1", "--references", references
        )
        assert code == 0, err
        assessments.append(payload["assessment"]["assessment_id"])
    code, _, err = run_json("compare", "--study", study, "--control", assessments[0], "--candidate", assessments[1])
    assert code == 0, err
    return study


def test_an_agentic_study_serves_its_cards_and_every_key_path_resolves(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPOTRAIL_ANTHROPIC_API_KEY", raising=False)
    work = tmp_path / "work"
    demonstration_until(work, "CAMPAIGN", first_step="CAMPAIGN")
    studies = {"chinook": work / "chinook-campaign", "chinook_prose": chinook_prose_compared(tmp_path)}
    served = {}
    for workload, study in studies.items():
        reads = agentic_reads(study)
        read = reads["lesson"]
        assert reads["status"]["study"]["workload"] == workload
        assert (read["ok"], read["track"], read["write_sequence"]) == (True, "tool_using_agent", reads["status"]["write_sequence"])
        served[workload] = read["cards"]
        for card in read["cards"]:
            assert card["key_paths"], (workload, card["kind"])
            for key_path in card["key_paths"]:
                assert resolved(reads[key_path["read"]], key_path["path"]) != [], (workload, card["kind"], key_path)
        assert run_json("status", "--study", study)[1] == reads["status"]
    assert [card["kind"] for card in served["chinook"]] == ["study", "attempts", "assessments", "comparisons", "decisions"]
    assert [card["kind"] for card in served["chinook_prose"]] == ["study", "attempts", "assessments", "comparisons"]
    # One set of cards for the Track: the free-text Workload is served the Chinook Study's cards of the same kinds.
    assert served["chinook_prose"] == served["chinook"][:-1]
