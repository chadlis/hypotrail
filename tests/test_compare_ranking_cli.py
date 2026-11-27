"""Real CLI workflow on a synthetic development ranking build (D-233)."""

import json

from _ranking_helpers import CONTRACT, command, initialize, metadata, write_build


def _add_scores(paths, work, role, score_a, score_b):
    examples, build, study = paths
    mapping = json.loads((CONTRACT / "mapping.json").read_bytes())
    mapping["dataset_sha256"] = metadata((build / "items.csv").read_bytes())["sha256"]
    mapping_file = work / f"mapping-{role}.json"
    mapping_file.write_text(json.dumps(mapping), encoding="utf-8")
    population = work / f"population-{role}.json"
    population.write_text(json.dumps({"item_ids": ["a@2011-01-01", "b@2011-01-01", "b@2011-02-01"]}), encoding="utf-8")
    scores = work / f"scores-{role}.csv"
    scores.write_text(f"item_id,score\nb@2011-02-01,0\nb@2011-01-01,{score_b}\na@2011-01-01,{score_a}\n", encoding="utf-8")
    code, payload, err = command(
        "import", "ml", "--study", study, "--examples-dir", examples, "--request-id", f"rank-{role}",
        "--source", scores, "--mapping", mapping_file, "--population", population,
    )
    assert code == 0, (payload, err)
    return payload["observation_set_id"]


def test_the_cli_compares_two_real_ranking_assessments(tmp_path):
    items = b"item_id,entity_id,as_of,partition,mature\na@2011-01-01,a,2011-01-01,dev,true\nb@2011-01-01,b,2011-01-01,dev,true\nb@2011-02-01,b,2011-02-01,dev,true\n"
    references = b"item_id,label\na@2011-01-01,1\nb@2011-01-01,0\nb@2011-02-01,0\n"
    examples, build = write_build(tmp_path, items=items, references=references)
    study = tmp_path / "study"
    paths = (examples, build, study)
    code, initialized, err = initialize(paths)
    assert code == 0, (initialized, err)
    lower = "0.123456789012345678901234567801"
    upper = "0.123456789012345678901234567802"
    assessments = []
    for role, score_a, score_b, recall in [("control", lower, upper, 0), ("candidate", upper, lower, 1)]:
        observations = _add_scores(paths, tmp_path, role, score_a, score_b)
        code, payload, err = command(
            "assess", "--study", study, "--observations", observations,
            "--references", initialized["references_id"], "--scorer", "ranking_recall_at_top_v1",
        )
        assert code == 0, (payload, err)
        assert payload["assessment"]["metrics"][0]["value"] == recall
        assessments.append(payload["assessment"]["assessment_id"])

    code, payload, err = command("compare", "--study", study, "--control", assessments[0], "--candidate", assessments[1])
    assert code == 0, (payload, err)
    record = payload["comparison"]
    assert record["delta"]["value"] == 1
    assert record["interval"]["upper"] == 1
    assert record["interval"]["unit"] == "entity"
    assert record["interval"]["omitted_dates"] == 4000 - record["interval"]["usable_resamples"]
    code, shown, err = command("status", "--study", study)
    assert code == 0, (shown, err)
    assert shown["comparisons"] == [record]
    code, read, err = command("figures", "--study", study)
    assert code == 0, (read, err)
    assert read["comparisons"][0]["unavailable"] == "no_item_level_ranking_delta"
    page = tmp_path / "report.html"
    code, rendered, err = command("report", "--study", study, "--out", page)
    assert code == 0, (rendered, err)
    text = page.read_text(encoding="utf-8")
    assert "usable draws" in text and "date omissions" in text and "Candidate has higher recall" in text
    assert "per_item.csv" not in text and "references-dev.csv" not in text
