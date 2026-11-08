"""The shape of a Workload declaration is checked as a whole, before any computation.

Witnessed systematically on `examples/bike_day/workload.json`: every key is removed one
at a time, at every level of the declaration and of each Configuration; an unknown key
is added at every level; every object or list is replaced by a wrongly typed value. Each
case must end in a coded `InvalidInputError`, never in a bare Python exception.
"""

import copy
import json
import shutil
from pathlib import Path

import pytest

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.baselines import write_seasonal_baseline
from hypotrail.ml.memberships import load_declaration
from hypotrail.ml.ridge import write_outputs

BIKE = Path(__file__).resolve().parent.parent / "examples" / "bike_day"
DECLARATION = json.loads((BIKE / "workload.json").read_text(encoding="utf-8"))

# Keys that may be absent from the declaration at load, with the reason. Only `partitions` may not.
# The optional keys that some entry point reads are refused by that entry point when absent
# (tests/test_ml_declaration_schema.py).
OPTIONAL = {
    ("schema_version",): "descriptive: no Track code reads it",
    ("track",): "descriptive: no Track code reads it",
    ("licence_notice",): "descriptive: no Track code reads it",
    **{
        (key,): "required by the entry points that read it, not by every entry point"
        for key in (
            "data_file", "id_prefix", "date_column", "target_column", "target_unit", "period_k",
            "forbidden_features", "allowed_target_features", "configurations",
        )
    },
}
# Maps whose keys are names the Workload chooses, so adding or removing a child is the
# Workload's own business, not a schema key. The one child the Track requires is listed
# in REQUIRED_CHILDREN.
OPEN_MAPS = {
    ("partitions",): "Partition names are the Workload's; only the `train` role is required",
    ("configurations",): "Configuration ids are the Workload's",
}
REQUIRED_CHILDREN = {("partitions", "train"): "TRAIN_PARTITION_NOT_DECLARED"}


def walk(node, path=()):
    """Yield (path, value) for every key of every object, and for the items of every list."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield path + (key,), value
            yield from walk(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, path + (index,))


def objects(node, path=()):
    """Yield (path, dict) for every object of the declaration."""
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from objects(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from objects(value, path + (index,))


def at(declaration, path):
    for step in path:
        declaration = declaration[step]
    return declaration


def workload_with(tmp_path, edit):
    target = tmp_path / "bike"
    shutil.copytree(BIKE, target)
    declaration = copy.deepcopy(DECLARATION)
    edit(declaration)
    (target / "workload.json").write_text(json.dumps(declaration), encoding="utf-8")
    return target


def refusal(workload):
    with pytest.raises(InvalidInputError) as caught:
        load_declaration(workload)
    assert caught.value.code
    return caught.value


def label(path):
    return ".".join(str(p) for p in path)


REMOVALS = [
    path for path, _ in walk(DECLARATION)
    if isinstance(path[-1], str)
    and path not in OPTIONAL
    and (path[:-1] not in OPEN_MAPS or path in REQUIRED_CHILDREN)
]
CONTAINERS = [path for path, value in walk(DECLARATION) if isinstance(value, (dict, list))]
UNKNOWN_KEY_LEVELS = [path for path, _ in objects(DECLARATION) if path not in OPEN_MAPS]


def test_the_witness_covers_every_level():
    assert ("configurations", "ridge_v1", "lag_features", 0, "period") in REMOVALS
    assert ("configurations", "ridge_v1", "ridge", "alpha") in REMOVALS
    assert ("configurations", "ridge_v1", "encoder", "handle_unknown") in REMOVALS
    assert ("configurations", "seasonal_7", "post_processing", "clip_min") in REMOVALS
    assert ("allowed_target_features", 0, "period") in REMOVALS
    assert ("period_k",) not in REMOVALS  # optional at load: the entry points that read it refuse its absence
    assert ("partitions",) in REMOVALS and ("partitions", "train") in REMOVALS


@pytest.mark.parametrize("path", REMOVALS, ids=label)
def test_a_missing_key_is_refused_with_a_code_naming_it(tmp_path, path):
    workload = workload_with(tmp_path, lambda d: at(d, path[:-1]).pop(path[-1]))
    error = refusal(workload)
    assert error.details["key"] == path[-1] or error.details.get("partition") == path[-1]
    assert str(path[-1]) in error.message
    expected = REQUIRED_CHILDREN.get(path)
    if expected:
        assert error.code == expected


@pytest.mark.parametrize("path", [p for p in REMOVALS if p[:1] == ("configurations",) and len(p) > 2], ids=label)
def test_a_missing_key_in_a_configuration_stops_every_entry_point_before_any_output(tmp_path, path):
    workload = workload_with(tmp_path, lambda d: at(d, path[:-1]).pop(path[-1]))
    out = tmp_path / "out"
    with pytest.raises(InvalidInputError):
        write_outputs(workload, out, "ridge_v1", "dev")
    with pytest.raises(InvalidInputError):
        write_seasonal_baseline(workload, out, "seasonal_7", "dev")
    assert not out.exists() or not list(out.rglob("*.csv"))


@pytest.mark.parametrize("path", UNKNOWN_KEY_LEVELS, ids=lambda p: label(p) or "root")
def test_an_unknown_key_is_refused_with_a_code_naming_it(tmp_path, path):
    workload = workload_with(tmp_path, lambda d: at(d, path).update(bogus_key=1))
    error = refusal(workload)
    assert error.details["key"] == "bogus_key"
    assert "bogus_key" in error.message


@pytest.mark.parametrize("wrong", ["oops", None, 7], ids=["string", "null", "number"])
@pytest.mark.parametrize("path", CONTAINERS, ids=label)
def test_a_wrongly_typed_value_is_refused_with_a_code_naming_the_key(tmp_path, path, wrong):
    workload = workload_with(tmp_path, lambda d: at(d, path[:-1]).__setitem__(path[-1], wrong))
    error = refusal(workload)
    assert label(path) in error.message


def test_the_optional_keys_are_exactly_those_listed(tmp_path):
    for path in OPTIONAL:
        workload = workload_with(tmp_path / label(path), lambda d: d.pop(path[0]))
        assert load_declaration(workload)  # accepted
    # and nothing else at the root is optional
    root = {p[0] for p in REMOVALS if len(p) == 1}
    assert root == set(DECLARATION) - {p[0] for p in OPTIONAL}


def test_the_unmodified_declaration_is_accepted_and_typed_from_the_file():
    declaration = load_declaration(BIKE)
    assert [p.name for p in declaration.partitions] == list(DECLARATION["partitions"])
    assert declaration.period_k.days == DECLARATION["period_k"]
    assert list(declaration.configurations) == list(DECLARATION["configurations"])
    assert (declaration.data_file, declaration.id_prefix, declaration.target_unit) == (
        DECLARATION["data_file"], DECLARATION["id_prefix"], DECLARATION["target_unit"],
    )
    assert list(declaration.forbidden_features) == DECLARATION["forbidden_features"]
