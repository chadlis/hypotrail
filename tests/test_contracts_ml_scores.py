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
    assert expected["caught_by"] in {"schema", "import"} and expected["exit"] in {2, 3}
    found = {path.name: problems(path) for path in sorted(case.iterdir()) if path.name in SCHEMA_OF}
    assert found
    if expected["caught_by"] == "schema":
        assert any(found.values()), f"{case.name} should be refused by a schema"
    else:
        assert not any(found.values()), f"{case.name} should be schema-valid, and refused by the import alone: {found}"


def test_the_mapping_schema_agrees_with_mapping_keys_except_settings_and_y_pred_raw():
    """`y_pred_raw` is a key of the regression Track that the contract leaves out; `settings` is refused until M1 (the next test)."""
    loaded = schema("mapping.schema.json")
    assert set(loaded["required"]) == {key for key, required in MAPPING_KEYS.items() if required}
    assert set(loaded["properties"]) - {"settings"} == set(MAPPING_KEYS) - {"y_pred_raw"}


def test_import_ml_refuses_the_example_mappings_settings_key_with_mapping_key_unknown_until_m1():
    """A pinned known difference: the contract has `settings`, `import ml` on `main` refuses it. M1 (chadlis/hypotrail#277) turns it around and changes this test."""
    with pytest.raises(InvalidInputError) as refused:
        _checked_mapping((EXAMPLES / "mapping.json").read_bytes(), EXAMPLES / "mapping.json")
    assert (refused.value.code, refused.value.details["key"]) == ("MAPPING_KEY_UNKNOWN", "settings")
