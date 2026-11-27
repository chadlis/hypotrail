"""A ranking Assessment computes recall by date on the frozen development population."""

import json

import pytest

from _ranking_helpers import CONTRACT, command, initialize, metadata, write_build


def import_scores(paths, tmp_path, scored):
    examples, build, study = paths
    mapping_file = tmp_path / "mapping.json"
    mapping = json.loads((CONTRACT / "mapping.json").read_bytes())
    mapping["dataset_sha256"] = metadata((build / "items.csv").read_bytes())["sha256"]
    mapping_file.write_text(json.dumps(mapping), encoding="utf-8")
    population = tmp_path / "population.json"
    population.write_text(json.dumps({"item_ids": list(scored)}), encoding="utf-8")
    scores = tmp_path / "scores.csv"
    scores.write_text("item_id,score\n" + "".join(f"{item},{scored[item]}\n" for item in reversed(scored)), encoding="utf-8")
    return command(
        "import", "ml", "--study", study, "--examples-dir", examples, "--request-id", "assess-ranking",
        "--source", scores, "--mapping", mapping_file, "--population", population,
    )


def assessment(paths, observations_id, references_id):
    return command(
        "assess", "--study", paths[2], "--observations", observations_id,
        "--references", references_id, "--scorer", "ranking_recall_at_top_v1",
    )


def write_panel(tmp_path, rows):
    items = "item_id,entity_id,as_of,partition,mature\n" + "".join(f"{entity}@{as_of},{entity},{as_of},dev,true\n" for entity, as_of, _, _ in rows)
    references = "item_id,label\n" + "".join(f"{entity}@{as_of},{label}\n" for entity, as_of, _, label in rows)
    return write_build(tmp_path, items=items.encode(), references=references.encode())


def test_assess_uses_exact_top_count_id_ties_and_skips_only_dates_without_positives(tmp_path):
    rows = [(f"C{number:02}", "2011-01-01", 1, int(number in (1, 2, 11))) for number in range(1, 12)]
    rows.extend([("A", "2011-01-02", 1, 0), ("A", "2011-01-03", 1, 0), ("B", "2011-01-03", 0, 1)])
    examples, build = write_panel(tmp_path, rows)
    paths = (examples, build, tmp_path / "study")
    code, initialized, err = initialize(paths)
    assert code == 0, (initialized, err)
    code, imported, err = import_scores(paths, tmp_path, {f"{entity}@{as_of}": score for entity, as_of, score, _ in rows})
    assert code == 0, (imported, err)
    code, payload, err = assessment(paths, imported["observation_set_id"], initialized["references_id"])
    assert code == 0, (payload, err)
    record = payload["assessment"]
    assert record["metrics"] == [{
        "id": "recall_at_top_fraction", "value": pytest.approx(1 / 3), "unit": "proportion",
        "direction": "higher_is_better", "denominator": 2, "status": "scored", "reason": None,
    }]
    assert record["ranking_dates"] == {"scored": 2, "omitted_no_positives": 1}
    per_item = (paths[2] / record["per_item_ref"]["path"]).read_text(encoding="utf-8").splitlines()
    assert per_item[0] == "item_id,entity_id,as_of,score,label"
    assert per_item[1] == "A@2011-01-02,A,2011-01-02,1,0"
    assert len(per_item) == len(rows) + 1


def test_an_undefined_ranking_metric_and_a_revised_reference_count_are_explicit(tmp_path):
    rows = [("A", "2011-01-01", 1, 0)]
    examples, build = write_panel(tmp_path, rows)
    paths = (examples, build, tmp_path / "study")
    code, initialized, err = initialize(paths)
    assert code == 0, (initialized, err)
    code, imported, err = import_scores(paths, tmp_path, {"A@2011-01-01": 1})
    assert code == 0, (imported, err)
    observations_id = imported["observation_set_id"]
    code, first, err = assessment(paths, observations_id, initialized["references_id"])
    assert code == 0, (first, err)
    assert first["assessment"]["metrics"][0]["value"] is None
    assert first["assessment"]["ranking_dates"] == {"scored": 0, "omitted_no_positives": 1}

    write_panel(tmp_path, [("A", "2011-01-01", 1, 1)])
    code, revised, err = initialize(paths, new_revision=True)
    assert code == 0, (revised, err)
    code, second, err = assessment(paths, observations_id, revised["references_id"])
    assert code == 0, (second, err)
    assert second["assessment"]["metrics"][0]["value"] == 1
    assert second["assessment"]["ranking_dates"] == {"scored": 1, "omitted_no_positives": 0}
    assert second["assessment"]["rescoring"]["cause"] == "references_version"
