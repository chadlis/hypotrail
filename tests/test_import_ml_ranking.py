"""Bring the accepted ranking export and all its named refusals through import ml."""

import json

import pytest

from _ranking_helpers import CONTRACT, command, initialize, ranking_paths

REFUSALS = (
    "dataset-digest-mismatch",
    "mapping-key-unknown",
    "population-immature-item",
    "population-item-absent",
    "population-mixed-partitions",
    "prediction-not-finite",
    "row-id-duplicate",
    "row-id-outside-population",
)


def import_scores(paths, *, folder=CONTRACT, mapping=None, scores=None, population=None, request_id="one-ranking-import"):
    examples, _, study = paths
    return command(
        "import", "ml", "--study", study, "--examples-dir", examples, "--request-id", request_id,
        "--source", scores or folder / "scores.csv", "--mapping", mapping or folder / "mapping.json",
        "--population", population or folder / "population.json",
    )


@pytest.mark.parametrize("case", REFUSALS)
def test_each_refused_score_file_is_refused_by_import_ml_with_its_code(case, ranking_paths):
    assert initialize(ranking_paths)[0] == 0
    folder = CONTRACT / "refused" / case
    expectation = json.loads((folder / "expected.json").read_bytes())
    code, refused, _ = import_scores(ranking_paths, folder=folder)
    assert (code, refused["error"]["code"]) == (expectation["exit"], expectation["code"])
    assert not (ranking_paths[2] / "attempts").exists()


def test_import_ml_refuses_y_pred_raw_for_a_ranking_workload_with_mapping_key_unknown(ranking_paths, tmp_path):
    assert initialize(ranking_paths)[0] == 0
    mapping = json.loads((CONTRACT / "mapping.json").read_bytes())
    mapping["y_pred_raw"] = "raw_score"
    source = tmp_path / "mapping.json"
    source.write_text(json.dumps(mapping), encoding="utf-8")
    code, refused, _ = import_scores(ranking_paths, mapping=source)
    assert (code, refused["error"]["code"]) == (2, "MAPPING_KEY_UNKNOWN")


def test_ranking_import_joins_by_item_and_replays_one_request(ranking_paths, tmp_path):
    assert initialize(ranking_paths)[0] == 0
    mapping = json.loads((CONTRACT / "mapping.json").read_bytes())
    mapping["settings"] = {"solver": "declared by fixture", "steps": 12}
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(json.dumps(mapping), encoding="utf-8")
    scores = tmp_path / "scores.csv"
    scores.write_text(
        "item_id,score,unmapped\n12348@2011-01-01,3,own\n12346@2011-01-01,1,program\n12347@2011-01-01,2,note\n",
        encoding="utf-8",
    )
    args = {"scores": scores, "mapping": mapping_file}
    code, imported, err = import_scores(ranking_paths, **args)
    assert code == 0, (imported, err)
    study = ranking_paths[2]
    attempt = imported["attempt"]
    files = {ref["role"]: study / ref["path"] for ref in attempt["output_refs"]}
    observations = json.loads(files["observation_set"].read_bytes())
    assert observations["domain"] == "ranking"
    assert observations["provenance"]["settings"] == {"origin": "declared", "value": mapping["settings"]}
    report = json.loads(files["validation_report"].read_bytes())
    assert report["unmapped_columns"] == ["unmapped"]
    normalized = (study / observations["normalized_ref"]["path"]).read_text(encoding="utf-8").splitlines()
    assert normalized == ["item_id,score", "12346@2011-01-01,1", "12347@2011-01-01,2", "12348@2011-01-01,3"]
    code, replay, err = import_scores(ranking_paths, **args)
    assert code == 0 and replay["replayed"] and replay["observation_set_id"] == imported["observation_set_id"], (replay, err)
    scores.write_text("item_id,score\n12346@2011-01-01,0\n", encoding="utf-8")
    code, conflict, _ = import_scores(ranking_paths, **args)
    assert (code, conflict["error"]["code"]) == (6, "REQUEST_CONFLICT")


def test_ranking_import_refuses_an_immature_id_before_looking_up_membership(ranking_paths, tmp_path):
    assert initialize(ranking_paths)[0] == 0
    population = tmp_path / "population.json"
    population.write_text(json.dumps({"item_ids": ["very-late@2011-10-01"]}), encoding="utf-8")
    code, refused, _ = import_scores(ranking_paths, population=population)
    assert (code, refused["error"]["code"]) == (2, "POPULATION_ITEM_IMMATURE")


def test_import_rejects_a_non_dev_population_before_opening_the_score_file(ranking_paths, monkeypatch):
    from pathlib import Path

    assert initialize(ranking_paths)[0] == 0
    case = CONTRACT / "refused" / "population-mixed-partitions"
    sentinel = case / "scores.csv"
    read_bytes = Path.read_bytes

    def checked_read(path):
        if path == sentinel:
            pytest.fail("a non-development score source was opened")
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", checked_read)
    code, refused, _ = import_scores(ranking_paths, folder=case)
    assert (code, refused["error"]["code"]) == (2, "POPULATION_MIXED_PARTITIONS")
