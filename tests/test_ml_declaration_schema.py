"""Ticket #39: `workload.json` is checked as a whole against one JSON Schema, and every malformed value is refused with a code.

Seams: `load_declaration` (the load), and the six public entry points that read a declaration
(memberships, References, the seasonal baseline, the Ridge outputs, metrics, the Comparison).
A refusal comes before any file is written and before anything is fitted.
"""

import copy
import csv
import json
import shutil
from pathlib import Path

import pytest

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.baselines import write_seasonal_baseline
from hypotrail.ml.comparison import compare
from hypotrail.ml.memberships import load_declaration, write_memberships
from hypotrail.ml.metrics import compute_metrics
from hypotrail.ml.references import write_references
from hypotrail.ml.ridge import fit_configuration, write_outputs

from _ml_helpers import fit_probe

BIKE = Path(__file__).resolve().parent.parent / "examples" / "bike_day"
DECLARATION = json.loads((BIKE / "workload.json").read_text(encoding="utf-8"))
RIDGE = ("configurations", "ridge_v1")
SEASONAL = ("configurations", "seasonal_7")
WRONG_TYPE = "DECLARATION_WRONG_TYPE"
NOT_ALLOWED = "DECLARATION_VALUE_NOT_ALLOWED"


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


def setter(path, value):
    return lambda d: at(d, path[:-1]).__setitem__(path[-1], value)


def label(path):
    return ".".join(str(p) for p in path)


def load_refusal(workload):
    with pytest.raises(InvalidInputError) as caught:
        load_declaration(workload)
    return caught.value


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory):
    """Valid memberships, References and predictions, so metrics and the Comparison have files to read."""
    out = tmp_path_factory.mktemp("artifacts")
    write_memberships(BIKE, out)
    write_references(BIKE, out)
    control, candidate = out / "control", out / "candidate"
    write_seasonal_baseline(BIKE, control, "seasonal_7", "dev")
    write_outputs(BIKE, candidate, "ridge_v1", "dev")
    return out, control, candidate


def entry_points(artifacts, out):
    shared, control, candidate = artifacts
    return {
        "memberships": lambda w: write_memberships(w, out),
        "references": lambda w: write_references(w, out),
        "seasonal_baseline": lambda w: write_seasonal_baseline(w, out, "seasonal_7", "dev"),
        "ridge": lambda w: write_outputs(w, out, "ridge_v1", "dev"),
        "metrics": lambda w: compute_metrics(
            control / "predictions.csv", shared / "references.csv", shared / "memberships.csv", w
        ),
        "comparison": lambda w: compare(
            control / "predictions.csv",
            candidate / "predictions.csv",
            shared / "references.csv",
            shared / "memberships.csv",
            out,
            w,
        ),
    }


# --- the values named by the ticket ---------------------------------------------------

SPECIFIC = [
    # wrongly typed values (round 4, finding 1)
    (RIDGE + ("post_processing", "clip_min"), "zero", WRONG_TYPE, "clip_min"),
    (RIDGE + ("post_processing", "clip_min"), None, WRONG_TYPE, "clip_min"),
    (("period_k",), "7", WRONG_TYPE, "period_k"),
    (("data_file",), 7, WRONG_TYPE, "data_file"),
    (RIDGE + ("calendar_columns",), [{}], WRONG_TYPE, "calendar_columns"),
    (RIDGE + ("ridge", "alpha"), "one", WRONG_TYPE, "alpha"),
    # values of the right type that are not allowed
    (RIDGE + ("ridge", "solver"), "bogus", NOT_ALLOWED, "solver"),
    (RIDGE + ("encoder", "handle_unknown"), "bogus", NOT_ALLOWED, "handle_unknown"),
    (RIDGE + ("encoder", "sparse_output"), True, NOT_ALLOWED, "sparse_output"),
    (RIDGE + ("ridge", "alpha"), -1.0, NOT_ALLOWED, "alpha"),
    # malformed values accepted silently (round 4, finding 2)
    (("id_prefix",), None, WRONG_TYPE, "id_prefix"),
    (("id_prefix",), "", NOT_ALLOWED, "id_prefix"),
    (("forbidden_features",), [["casual"]], WRONG_TYPE, "forbidden_features"),
    (("track",), "agentic", NOT_ALLOWED, "track"),
    # the period of the baseline (round 4, finding 6)
    (("period_k",), 0, NOT_ALLOWED, "period_k"),
    (("period_k",), -1, NOT_ALLOWED, "period_k"),
    (("period_k",), True, WRONG_TYPE, "period_k"),
    (("period_k",), 7.5, WRONG_TYPE, "period_k"),
    (("period_k",), 7.0, WRONG_TYPE, "period_k"),
    # the kinds of lag feature the Track can compute (round 5, G3)
    (("allowed_target_features", 0, "kind"), "bogus", NOT_ALLOWED, "kind"),
    (RIDGE + ("lag_features", 0, "kind"), "bogus", NOT_ALLOWED, "kind"),
    (RIDGE + ("lag_features", 0, "kind"), "", NOT_ALLOWED, "kind"),
    # a name that must name something (round 5, G8): features and every column
    (("allowed_target_features", 0, "name"), "", NOT_ALLOWED, "name"),
    (RIDGE + ("lag_features", 0, "name"), "", NOT_ALLOWED, "name"),
    (RIDGE + ("calendar_columns", 0), "", NOT_ALLOWED, "calendar_columns"),
    (RIDGE + ("encoder", "columns", 0), "", NOT_ALLOWED, "columns"),
    (RIDGE + ("scaler", "columns", 0), "", NOT_ALLOWED, "columns"),
    (("forbidden_features", 0), "", NOT_ALLOWED, "forbidden_features"),
    (("date_column",), "", NOT_ALLOWED, "date_column"),
    (("target_column",), "", NOT_ALLOWED, "target_column"),
    (("data_file",), "", NOT_ALLOWED, "data_file"),
    # dates of a Partition
    (("partitions", "dev", 0), "2012-02-30", NOT_ALLOWED, "dev"),
    (("partitions", "dev", 0), "20120101", NOT_ALLOWED, "dev"),
    (("partitions", "dev"), ["2012-01-01"], NOT_ALLOWED, "dev"),
]


@pytest.mark.parametrize("path, value, code, key", SPECIFIC, ids=[f"{label(p)}={v!r}" for p, v, _, _ in SPECIFIC])
def test_a_malformed_value_is_refused_at_load_with_a_code_naming_its_path(tmp_path, path, value, code, key):
    error = load_refusal(workload_with(tmp_path, setter(path, value)))
    assert error.code == code
    assert error.stage == "declaration"
    assert error.details["key"] == key
    assert error.details["path"] == label(path) + (".0" if value in ([{}], [["casual"]]) else "")


def test_schema_version_is_an_optional_string_with_no_value_check(tmp_path):
    assert load_declaration(workload_with(tmp_path, setter(("schema_version",), "workload/2")))
    assert load_refusal(workload_with(tmp_path / "x", setter(("schema_version",), 2))).code == WRONG_TYPE


def test_the_declared_track_is_accepted_and_may_be_absent(tmp_path):
    assert load_declaration(workload_with(tmp_path, setter(("track",), "temporal_regression")))
    assert load_declaration(workload_with(tmp_path / "x", lambda d: d.pop("track")))


@pytest.mark.parametrize("solver", ["auto", "svd", "cholesky", "lsqr", "sparse_cg", "sag", "saga"])
def test_every_solver_the_schema_allows_runs(tmp_path, solver):
    workload = workload_with(tmp_path, setter(RIDGE + ("ridge", "solver"), solver))
    assert fit_configuration(workload, "ridge_v1").pipeline


@pytest.mark.parametrize("handle_unknown", ["ignore", "error"])
def test_every_handle_unknown_the_schema_allows_runs(tmp_path, handle_unknown):
    workload = workload_with(tmp_path, setter(RIDGE + ("encoder", "handle_unknown"), handle_unknown))
    assert fit_configuration(workload, "ridge_v1").pipeline


def test_a_zero_alpha_is_allowed(tmp_path):
    assert load_declaration(workload_with(tmp_path, setter(RIDGE + ("ridge", "alpha"), 0)))


# --- the codes keep their meaning, and every load refusal has stage declaration ---------------


def test_the_kind_errors_are_declaration_refusals_naming_the_path(tmp_path):
    error = load_refusal(workload_with(tmp_path / "a", setter(SEASONAL + ("kind",), "theta")))
    assert (error.code, error.stage) == ("CONFIGURATION_KIND_UNKNOWN", "declaration")
    assert error.details["config_id"] == "seasonal_7" and error.details["path"] == label(SEASONAL + ("kind",))

    error = load_refusal(workload_with(tmp_path / "b", lambda d: at(d, SEASONAL).update(lag_features=[])))
    assert (error.code, error.stage) == ("CONFIGURATION_KEY_NOT_FOR_KIND", "declaration")
    assert error.details["key"] == "lag_features" and error.details["path"] == label(SEASONAL)

    error = load_refusal(workload_with(tmp_path / "c", lambda d: at(d, RIDGE).pop("scaler")))
    assert (error.code, error.stage) == ("DECLARATION_INCOMPLETE", "declaration")
    assert error.details["key"] == "scaler" and error.details["path"] == label(RIDGE)

    error = load_refusal(workload_with(tmp_path / "d", lambda d: at(d, RIDGE + ("ridge",)).update(bogus=1)))
    assert (error.code, error.stage) == ("DECLARATION_KEY_UNKNOWN", "declaration")
    assert error.details["key"] == "bogus"


def test_a_workload_without_train_is_refused_by_a_declaration_check_whatever_its_configurations(tmp_path):
    def edit(declaration):
        declaration["partitions"].pop("train")
        declaration["configurations"] = {}

    error = load_refusal(workload_with(tmp_path, edit))
    assert (error.code, error.stage) == ("TRAIN_PARTITION_NOT_DECLARED", "declaration")
    assert error.details["key"] == "train"
    assert "every Configuration" not in error.message


def test_the_semantic_rules_keep_their_own_codes_after_the_schema_passed(tmp_path):
    cases = [
        (RIDGE + ("lag_features", 0, "period"), 0, "TARGET_FEATURE_NOT_PAST"),
        (SEASONAL + ("period_k",), -1, "TARGET_FEATURE_NOT_PAST"),
        (SEASONAL + ("period_k",), 14, "TARGET_TRANSFORMATION_NOT_ALLOWED"),
    ]
    for index, (path, value, code) in enumerate(cases):
        workload = workload_with(tmp_path / str(index), setter(path, value))
        assert load_declaration(workload)  # the schema lets the value through
        with pytest.raises(InvalidInputError) as caught:
            write_seasonal_baseline(workload, tmp_path / "out", "seasonal_7", "dev") if path[1] == "seasonal_7" else (
                write_outputs(workload, tmp_path / "out", "ridge_v1", "dev")
            )
        assert caught.value.code == code


# --- every entry point refuses before any file is written or any model is fitted ------------

MALFORMED = [
    (RIDGE + ("post_processing", "clip_min"), None),
    (("period_k",), "7"),
    (("period_k",), 0),
    (RIDGE + ("ridge", "solver"), "bogus"),
    (("allowed_target_features", 0, "kind"), "bogus"),
    (RIDGE + ("lag_features", 0, "kind"), "bogus"),
    (("allowed_target_features", 0, "name"), ""),
    (RIDGE + ("lag_features", 0, "name"), ""),
    (RIDGE + ("calendar_columns", 0), ""),
    (RIDGE + ("encoder", "columns", 0), ""),
    (RIDGE + ("scaler", "columns", 0), ""),
    (("forbidden_features", 0), ""),
    (RIDGE + ("encoder", "sparse_output"), True),
    (("id_prefix",), ""),
    (("partitions", "dev", 0), "2012-02-30"),
    (RIDGE + ("calendar_columns",), [{}]),
]


@pytest.mark.parametrize("path, value", MALFORMED, ids=[f"{label(p)}={v!r}" for p, v in MALFORMED])
@pytest.mark.parametrize("entry", ["memberships", "references", "seasonal_baseline", "ridge", "metrics", "comparison"])
def test_a_malformed_declaration_is_refused_by_every_entry_point_before_any_effect(
    tmp_path, artifacts, entry, path, value
):
    workload = workload_with(tmp_path, setter(path, value))
    out = tmp_path / "out"
    with fit_probe() as probe:
        with pytest.raises(InvalidInputError) as caught:
            entry_points(artifacts, out)[entry](workload)
    assert caught.value.stage == "declaration"
    assert caught.value.details["path"]
    assert probe.calls == []
    assert not out.exists() or not list(out.rglob("*"))


def test_the_probe_sees_the_fit_when_the_declaration_is_valid(tmp_path, artifacts):
    with fit_probe() as probe:
        entry_points(artifacts, tmp_path / "out")["ridge"](BIKE)
    assert probe.calls


# --- an empty name, and an empty unit, are not allowed (#40, H2, H2b, H2c) -----------------


def rename(path, old, new):
    def edit(d):
        parent = at(d, path)
        parent[new] = parent.pop(old)

    return edit


# (edit, key, path of the object that holds the empty name, or of the empty value)
EMPTY = {
    "configuration id": (rename(("configurations",), "seasonal_7", ""), "", "configurations"),
    "partition name": (rename(("partitions",), "public_check", ""), "", "partitions"),
    "target_unit": (setter(("target_unit",), ""), "target_unit", "target_unit"),
}


@pytest.mark.parametrize("case", sorted(EMPTY))
def test_an_empty_name_or_unit_is_refused_at_load_naming_the_value(tmp_path, case):
    edit, key, path = EMPTY[case]
    error = load_refusal(workload_with(tmp_path, edit))
    assert (error.code, error.stage) == (NOT_ALLOWED, "declaration")
    assert (error.details["key"], error.details["path"]) == (key, path)


@pytest.mark.parametrize("case", sorted(EMPTY))
@pytest.mark.parametrize("entry", ["memberships", "references", "seasonal_baseline", "ridge", "metrics", "comparison"])
def test_an_empty_name_or_unit_is_refused_by_every_entry_point_and_nothing_is_written(tmp_path, artifacts, entry, case):
    workload = workload_with(tmp_path, EMPTY[case][0])
    out = tmp_path / "out"
    with fit_probe() as probe:
        with pytest.raises(InvalidInputError) as caught:
            entry_points(artifacts, out)[entry](workload)
    assert (caught.value.code, caught.value.stage) == (NOT_ALLOWED, "declaration")
    assert probe.calls == []
    assert not out.exists() or not list(out.rglob("*"))


def test_references_has_one_row_per_item_of_every_partition(tmp_path):
    path = write_references(BIKE, tmp_path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 724 == 358 + 182 + 184  # train, dev, public_check: no Item is dropped
    write_memberships(BIKE, tmp_path)
    with (tmp_path / "memberships.csv").open(newline="", encoding="utf-8") as handle:
        items = {m["row_id"] for m in csv.DictReader(handle) if m["partition"]}
    assert {r["row_id"] for r in rows} == items


# --- a key is required by the schema only if every entry point reads it ----------------------

# What each entry point reads of the optional root keys (the keys not listed are not read).
READS = {
    "memberships": {"data_file", "date_column", "id_prefix", "period_k"},
    "references": {"data_file", "date_column", "id_prefix", "period_k", "target_column"},
    "seasonal_baseline": {
        "data_file", "date_column", "id_prefix", "period_k", "target_column",
        "forbidden_features", "allowed_target_features", "configurations",
    },
    "ridge": {
        "data_file", "date_column", "id_prefix", "period_k", "target_column",
        "forbidden_features", "allowed_target_features", "configurations",
    },
    "metrics": {"target_unit"},
    "comparison": {"target_unit"},
}
OPTIONAL_ROOT = sorted(set().union(*READS.values()))


def test_only_the_partitions_are_required_by_the_schema(tmp_path):
    for key in OPTIONAL_ROOT + ["schema_version", "track", "licence_notice", "question", "objective", "limitations"]:
        assert load_declaration(workload_with(tmp_path / key, lambda d: d.pop(key)))
    error = load_refusal(workload_with(tmp_path / "partitions", lambda d: d.pop("partitions")))
    assert (error.code, error.details["key"]) == ("DECLARATION_INCOMPLETE", "partitions")


@pytest.mark.parametrize("entry", sorted(READS))
@pytest.mark.parametrize("key", OPTIONAL_ROOT)
def test_an_entry_point_refuses_the_absence_of_a_key_it_reads_and_ignores_the_others(tmp_path, artifacts, entry, key):
    workload = workload_with(tmp_path, lambda d: d.pop(key))
    out = tmp_path / "out"
    run = entry_points(artifacts, out)[entry]
    if key in READS[entry]:
        with fit_probe() as probe:
            with pytest.raises(InvalidInputError) as caught:
                run(workload)
        assert caught.value.code == "DECLARATION_INCOMPLETE"
        assert caught.value.stage == "declaration"
        assert caught.value.details["key"] == key
        assert probe.calls == []
        assert not out.exists() or not list(out.rglob("*"))
    else:
        run(workload)


# --- the walk: every leaf, replaced in turn by a value of each other JSON type -----------


def leaves(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from leaves(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from leaves(value, path + (index,))
    else:
        yield path, node


INTEGER_KEYS = {"period", "period_k"}  # the leaves the schema types as integer; the others are numbers


def other_types(value, path):
    everything = {"string": "oops", "number": 7.5, "boolean": True, "null": None, "array": [], "object": {}}
    own = (
        "boolean" if isinstance(value, bool)
        else "number" if isinstance(value, (int, float))
        else "string"
    )
    replacements = [v for name, v in everything.items() if name != own]
    if own == "boolean":
        replacements += [0, 1.0]
    if path[-1] in INTEGER_KEYS:
        replacements += [float(value)]  # the integral float 7.0
    return replacements


WALK = [(path, wrong) for path, value in leaves(DECLARATION) for wrong in other_types(value, path)]


def expected_for(path):
    if len(path) == 3 and path[0] == "configurations" and path[2] == "kind":
        return "CONFIGURATION_KIND_UNKNOWN"
    return WRONG_TYPE


def last_key(path):
    return [step for step in path if isinstance(step, str)][-1]


def test_the_walk_covers_the_optional_keys_and_both_kinds():
    paths = {path for path, _ in WALK}
    assert ("schema_version",) in paths and ("licence_notice",) in paths and ("track",) in paths
    assert SEASONAL + ("period_k",) in paths and RIDGE + ("encoder", "sparse_output") in paths
    assert (("period_k",), 7.0) in WALK


@pytest.mark.parametrize("path, wrong", WALK, ids=[f"{label(p)}={w!r}" for p, w in WALK])
def test_a_leaf_of_another_type_is_refused_with_its_own_code_and_key(tmp_path, path, wrong):
    error = load_refusal(workload_with(tmp_path, setter(path, wrong)))
    assert error.code == expected_for(path)
    assert error.stage == "declaration"
    assert error.details["key"] == last_key(path)
    assert error.details["path"] == label(path)


# --- the two file-level refusals carry key and path too (round 5, G4) -------------------------


def test_a_missing_declaration_names_the_file_as_key_and_the_whole_document_as_path(tmp_path):
    error = load_refusal(tmp_path)
    assert (error.code, error.stage) == ("FILE_NOT_FOUND", "declaration")
    assert error.details["key"] == "workload.json" and error.details["path"] == ""
    assert error.details["file"] == str(tmp_path / "workload.json")


@pytest.mark.parametrize("text", ["{", "", "[1, NaN]", '{"period_k": 1e999}'])
def test_a_declaration_that_is_not_json_names_the_file_as_key_and_the_whole_document_as_path(tmp_path, text):
    (tmp_path / "workload.json").write_text(text, encoding="utf-8")
    error = load_refusal(tmp_path)
    assert (error.code, error.stage) == ("FILE_NOT_JSON", "declaration")
    assert error.details["key"] == "workload.json" and error.details["path"] == ""
    assert error.details["file"] == str(tmp_path / "workload.json")
