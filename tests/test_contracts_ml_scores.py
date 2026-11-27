"""Consumer conformance of `ml-scores/1`, `ranking-items/1` and `ranking-reference/1` (C1 and C2 of D-172 on chadlis/hypotrail#75).

The examples are accepted by the schemas; each refused case is refused by the schemas when `expected.json` says `schema`, and is schema-valid
when it says `import`, so that the import alone refuses it. The import of the examples into a ranking Workload is M1's to add. No model is called.
"""

import csv
import hashlib
import io
import json
from pathlib import Path

import jsonschema
import pytest

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.imports import MAPPING_KEYS, _checked_mapping

CONTRACT = Path(__file__).resolve().parents[1] / "src" / "hypotrail" / "ml" / "contracts" / "ml-scores-1"
EXAMPLES = CONTRACT / "examples"
REFUSED = sorted(path for path in (EXAMPLES / "refused").iterdir() if path.is_dir())
SCHEMA_OF = {
    "mapping.json": "mapping.schema.json",
    "population.json": "population.schema.json",
    "scores.csv": "scores.schema.json",
    "items.csv": "ranking-items.schema.json",
    "references-dev.csv": "ranking-reference.schema.json",
    "build.json": "ranking-build.schema.json",
}
# D-180 on chadlis/hypotrail#75, item 3: "References content is refused by `init` and `init --new-revision`, exit 2." and
# "`population-immature-item` stays with `import`, exit 2." The other cases keep the code, exit and layer they had.
REFUSALS = {
    "dataset-digest-mismatch": ("ml-scores/1", "DATASET_DIGEST_MISMATCH", 3, "import"),
    "mapping-key-unknown": ("ml-scores/1", "MAPPING_KEY_UNKNOWN", 2, "schema"),
    "population-immature-item": ("ml-scores/1", "POPULATION_ITEM_IMMATURE", 2, "import"),
    "population-item-absent": ("ml-scores/1", "POPULATION_ITEM_ABSENT", 2, "import"),
    "population-mixed-partitions": ("ml-scores/1", "POPULATION_MIXED_PARTITIONS", 2, "import"),
    "prediction-not-finite": ("ml-scores/1", "PREDICTION_NOT_FINITE", 2, "schema"),
    "reference-duplicate": ("ranking-reference/1", "REFERENCE_ROW_DUPLICATE", 2, "init"),
    "reference-immature-item": ("ranking-reference/1", "REFERENCE_ITEM_IMMATURE", 2, "init"),
    "reference-item-unknown": ("ranking-reference/1", "REFERENCE_ITEM_UNKNOWN", 2, "init"),
    "reference-label-not-binary": ("ranking-reference/1", "REFERENCE_LABEL_NOT_BINARY", 2, "schema"),
    "row-id-duplicate": ("ml-scores/1", "ROW_ID_DUPLICATE", 2, "import"),
    "row-id-outside-population": ("ml-scores/1", "ROW_ID_OUTSIDE_POPULATION", 2, "import"),
}


def schema(name):
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


def document(path: Path):
    """A JSON file as parsed; a CSV file as `{"columns": header, "rows": [row objects of strings]}`."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    rows = list(reader)
    return {"columns": list(reader.fieldnames or []), "rows": rows}


def problems(path: Path):
    validator = jsonschema.Draft202012Validator(schema(SCHEMA_OF[path.name]))
    return [error.message for error in validator.iter_errors(document(path))]


@pytest.mark.parametrize("name", sorted(set(SCHEMA_OF.values())))
def test_each_schema_is_a_valid_draft_2020_12_schema_whose_id_names_its_directory(name):
    loaded = schema(name)
    jsonschema.Draft202012Validator.check_schema(loaded)
    assert loaded["$id"].endswith(f"/src/hypotrail/ml/contracts/ml-scores-1/{name}")


@pytest.mark.parametrize("name", sorted(SCHEMA_OF))
def test_each_example_file_is_accepted_by_its_schema(name):
    assert problems(EXAMPLES / name) == []


def test_the_examples_keep_the_rules_a_schema_cannot_say():
    items = document(EXAMPLES / "items.csv")["rows"]
    assert all(row["item_id"] == f"{row['entity_id']}@{row['as_of']}" for row in items)
    mapping = json.loads((EXAMPLES / "mapping.json").read_text(encoding="utf-8"))
    assert mapping["dataset_sha256"] == hashlib.sha256((EXAMPLES / "items.csv").read_bytes()).hexdigest()
    partition = {row["item_id"]: row["partition"] for row in items}
    population = json.loads((EXAMPLES / "population.json").read_text(encoding="utf-8"))["item_ids"]
    assert len({partition[item] for item in population}) == 1 and "" not in {partition[item] for item in population}
    assert [row["item_id"] for row in document(EXAMPLES / "scores.csv")["rows"]] == population
    mature_dev = sorted(row["item_id"] for row in items if row["partition"] == "dev" and row["mature"] == "true")
    assert sorted(row["item_id"] for row in document(EXAMPLES / "references-dev.csv")["rows"]) == mature_dev


@pytest.mark.parametrize("case", REFUSED, ids=[path.name for path in REFUSED])
def test_each_refused_case_is_refused_by_the_schemas_exactly_when_it_says_schema(case):
    expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
    assert expected["caught_by"] in {"schema", "import", "init"} and expected["exit"] in {2, 3}
    found = {path.name: problems(path) for path in sorted(case.iterdir()) if path.name in SCHEMA_OF}
    assert found
    if expected["caught_by"] == "schema":
        assert any(found.values()), f"{case.name} should be refused by a schema"
    else:
        assert not any(found.values()), f"{case.name} should be schema-valid, and refused by {expected['caught_by']} alone: {found}"


def test_each_refused_case_names_its_contract_code_exit_and_the_layer_that_refuses_it():
    found = {}
    for case in REFUSED:
        expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
        found[case.name] = (expected["contract"], expected["code"], expected["exit"], expected["caught_by"])
    assert found == REFUSALS


def test_the_build_example_gives_the_digest_and_size_of_each_example_file_it_lists():
    build = json.loads((EXAMPLES / "build.json").read_text(encoding="utf-8"))
    assert build["files"] == {
        name: {"sha256": hashlib.sha256((EXAMPLES / name).read_bytes()).hexdigest(), "size_bytes": (EXAMPLES / name).stat().st_size}
        for name in ("items.csv", "references-dev.csv")
    }


def _set(path, value):
    """A change to the example `build.json`: `path` is a list of keys; a value of None removes the last key."""

    def change(build):
        *parents, last = path
        for key in parents:
            build = build[key]
        if value is None:
            del build[last]
        else:
            build[last] = value

    return change


# D-180 on chadlis/hypotrail#75, item 2: "Required keys: `schema_version`, `label_cutoff`, `frame_digest`, `source.sha256`, and `files` as name →
# `{sha256, size_bytes}`. Other keys are allowed."
BUILD_CHANGES = [
    ("schema_version removed", _set(["schema_version"], None), False),
    ("schema_version of another contract", _set(["schema_version"], "ranking-build/2"), False),
    ("label_cutoff removed", _set(["label_cutoff"], None), False),
    ("label_cutoff not a date", _set(["label_cutoff"], "2011-12"), False),
    ("frame_digest removed", _set(["frame_digest"], None), False),
    ("frame_digest not a sha256", _set(["frame_digest"], "c07d"), False),
    ("source removed", _set(["source"], None), False),
    ("source.sha256 removed", _set(["source", "sha256"], None), False),
    ("files removed", _set(["files"], None), False),
    ("a file without its sha256", _set(["files", "items.csv", "sha256"], None), False),
    ("a file without its size", _set(["files", "items.csv", "size_bytes"], None), False),
    ("a file whose size is not an integer", _set(["files", "items.csv", "size_bytes"], "263"), False),
    ("a key the kit adds", _set(["positive_rate"], {"2011-01-01": 0.33}), True),
    ("a key the kit adds to source", _set(["source", "member"], "online_retail_II.xlsx"), True),
    ("a key the kit adds to a file", _set(["files", "items.csv", "rows"], 5), True),
]


@pytest.mark.parametrize(("change", "accepted"), [(c, a) for _, c, a in BUILD_CHANGES], ids=[name for name, _, _ in BUILD_CHANGES])
def test_ranking_build_requires_each_key_it_names_and_allows_the_others(change, accepted):
    build = json.loads((EXAMPLES / "build.json").read_text(encoding="utf-8"))
    change(build)
    validator = jsonschema.Draft202012Validator(schema("ranking-build.schema.json"))
    assert validator.is_valid(build) == accepted


def test_the_mapping_schema_agrees_with_mapping_keys_except_settings_and_y_pred_raw():
    """`y_pred_raw` is a key of the regression Track that the contract leaves out; `settings` is refused until M1 (the next test)."""
    loaded = schema("mapping.schema.json")
    assert set(loaded["required"]) == {key for key, required in MAPPING_KEYS.items() if required}
    assert set(loaded["properties"]) - {"settings"} == set(MAPPING_KEYS) - {"y_pred_raw"}


def test_import_ml_refuses_the_example_mappings_settings_key_with_mapping_key_unknown_until_m1():
    """A pinned known difference: the contract has `settings`, `import ml` on `main` refuses it. M1 turns it around and changes this test."""
    with pytest.raises(InvalidInputError) as refused:
        _checked_mapping((EXAMPLES / "mapping.json").read_bytes(), EXAMPLES / "mapping.json")
    assert (refused.value.code, refused.value.details["key"]) == ("MAPPING_KEY_UNKNOWN", "settings")
