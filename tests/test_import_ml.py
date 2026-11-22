"""Ticket #67: `import ml` adopts a complete predictions CSV, written by a program that never imports hypotrail."""

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from _assess_helpers import assess, observation_set_id, references_id
from _import_helpers import EXPORTER, FIELDS, MAPPING, export, import_ml, mapping_of, population_of, ready, rows_of, write_json, write_rows
from _study_helpers import ROOT, init_study, run_json, run_ml, sha256

from hypotrail.core import canonical, contracts, requests
from hypotrail.core.errors import EXIT_INTEGRITY_REFUSED, EXIT_INVALID_INPUT, EXIT_LOCK_OR_CONFLICT


def snapshot(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): sha256(p) for p in sorted(Path(folder).rglob("*")) if p.is_file()}


@pytest.fixture
def study(tmp_path):
    return init_study(tmp_path, name="study")[0]


def attempt_dir(study, attempt):
    return Path(study) / "attempts" / attempt["attempt_id"]


def measures(study, attempt, scorer="regression_mae_v1"):
    _, payload, err = assess(study, observation_set_id(study, attempt), scorer, references_id(study))
    assert payload.get("ok"), (payload, err)
    return payload["assessment"]


# --- AC1: the exporter never imports hypotrail ------------------------------------------------------------------------


def test_the_exporter_runs_where_hypotrail_cannot_be_imported_and_writes_its_csv(tmp_path):
    """T07 (SPEC §10)."""
    out = tmp_path / "out.csv"
    blocker = textwrap.dedent(
        """
        import runpy, sys
        sys.modules["hypotrail"] = None  # any `import hypotrail` now raises ImportError
        sys.argv = sys.argv[1:]
        runpy.run_path(sys.argv[0], run_name="__main__")
        """
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", blocker, str(EXPORTER), "--data", str(ROOT / "examples/bike_day/data/day.csv"),
         "--first", "2012-01-01", "--last", "2012-06-30", "--id-prefix", "bike-day", "--out", str(out)],
        capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr
    assert len(rows_of(out)) == 182 and list(rows_of(out)[0]) == FIELDS
    imported = {
        (n.names[0].name if isinstance(n, ast.Import) else (n.module or "")).split(".")[0]
        for n in ast.walk(ast.parse(EXPORTER.read_text()))
        if isinstance(n, (ast.Import, ast.ImportFrom))
    }
    assert "hypotrail" not in imported and "sklearn" not in imported


# --- AC2: accepted; permuted rows give the same measures --------------------------------------------------------------


def test_the_export_is_accepted_and_its_permutation_is_too_with_the_same_measures(tmp_path, study):
    """T07 (SPEC §10)."""
    source, mapping, population, digest = ready(tmp_path)
    code, payload, err = import_ml(study, source, mapping, population, "imp-a")
    assert code == 0, (payload, err)
    rows = rows_of(source)
    permuted = write_rows(tmp_path / "permuted.csv", list(reversed(rows[1:])) + rows[:1], FIELDS)
    assert permuted.read_bytes() != source.read_bytes()
    code, other, err = import_ml(study, permuted, mapping, population, "imp-b")
    assert code == 0, (other, err)
    first, second = measures(study, payload["attempt"]), measures(study, other["attempt"])
    assert first["metrics"] == second["metrics"] and first["counts"] == second["counts"]
    assert first["counts"]["scored"] == 182 and first["metrics"][0]["value"] is not None
    assert (attempt_dir(study, payload["attempt"]) / "observations.csv").read_bytes() == (attempt_dir(study, other["attempt"]) / "observations.csv").read_bytes()


def test_a_file_without_y_pred_raw_is_accepted(tmp_path, study):
    source, digest = export(tmp_path)
    rows = [{"day_key": r["day_key"], "forecast_rentals": r["forecast_rentals"]} for r in rows_of(source)]
    bare = write_rows(tmp_path / "bare.csv", rows, ["day_key", "forecast_rentals"])
    mapping = write_json(tmp_path / "m.json", {"row_id": "day_key", "y_pred": "forecast_rentals", "dataset_sha256": digest})
    code, payload, err = import_ml(study, bare, mapping, population_of(tmp_path, bare), "r")
    assert code == 0, (payload, err)
    assert {r["y_pred_raw"] for r in rows_of(attempt_dir(study, payload["attempt"]) / "observations.csv")} == {""}


# --- AC3 and Tightened A, C: each refusal has its own code, and publishes nothing -------------------------------------


def with_first(**change):
    return lambda rows: [{**rows[0], **change}, *rows[1:]]


CASES = {
    "duplicate": (lambda rows: [*rows, rows[0]], "ROW_ID_DUPLICATE"),
    "empty_id": (with_first(day_key=""), "ROW_ID_EMPTY"),
    "missing_item": (lambda rows: rows[1:], "POPULATION_ITEM_ABSENT"),
    "outside": (lambda rows: [*rows, {**rows[0], "day_key": "bike-day:2030-01-01"}], "ROW_ID_OUTSIDE_POPULATION"),
    "nan": (with_first(forecast_rentals="nan"), "PREDICTION_NOT_FINITE"),
    "inf": (with_first(forecast_rentals="inf"), "PREDICTION_NOT_FINITE"),
    "text": (with_first(forecast_rentals="many"), "PREDICTION_NOT_FINITE"),
    "blank": (with_first(forecast_rentals=""), "PREDICTION_NOT_FINITE"),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_each_fault_of_the_file_is_refused_with_exit_2_its_code_and_nothing_is_published(tmp_path, study, case):
    """T08 (SPEC §10)."""
    edit, expected = CASES[case]
    good, digest = export(tmp_path)
    source = write_rows(tmp_path / "broken.csv", edit(rows_of(good)), FIELDS)
    population = population_of(tmp_path, good)
    before = snapshot(study)
    code, payload, _ = import_ml(study, source, mapping_of(tmp_path, digest), population, f"r-{case}")
    assert (code, payload["error"]["code"], payload["error"]["stage"]) == (EXIT_INVALID_INPUT, expected, "import")
    assert snapshot(study) == before and not (study / "attempts").exists()


def test_the_faults_that_name_a_kind_of_refusal_have_a_code_each():
    assert {code for _, code in CASES.values()} == {
        "ROW_ID_DUPLICATE", "ROW_ID_EMPTY", "POPULATION_ITEM_ABSENT", "ROW_ID_OUTSIDE_POPULATION", "PREDICTION_NOT_FINITE",
    }


@pytest.mark.parametrize(
    "mapping, expected",
    [
        ({"y_pred": "forecast_rentals"}, "MAPPING_KEY_MISSING"),
        ({"row_id": "day_key"}, "MAPPING_KEY_MISSING"),
        ({"row_id": "day_key", "y_pred": "forecast_rentals", "color": "red"}, "MAPPING_KEY_UNKNOWN"),
        ({"row_id": "day_key", "y_pred": "forecast_rentals", "loader": "pickle.load"}, "MAPPING_KEY_UNKNOWN"),
        ({"row_id": "day_key", "y_pred": "nope"}, "MAPPING_COLUMN_ABSENT"),
        ({"row_id": "day_key", "y_pred": 3}, "MAPPING_VALUE_INVALID"),
    ],
)
def test_a_mapping_without_row_id_or_y_pred_or_with_an_unknown_key_is_refused_with_a_code(tmp_path, study, mapping, expected):
    source, digest = export(tmp_path)
    before = snapshot(study)
    code, payload, _ = import_ml(study, source, write_json(tmp_path / "m.json", {**mapping, "dataset_sha256": digest}), population_of(tmp_path, source), "r")
    assert (code, payload["error"]["code"]) == (EXIT_INVALID_INPUT, expected)
    assert snapshot(study) == before


# The JSON text of a value that strict JSON refuses, for each fault other than the top-level duplicate.
NOT_STRICT_VALUES = {
    "nested_duplicate": '{"a": 1, "a": 2}',
    "nan": "NaN",
    "infinity": "Infinity",
    "minus_infinity": "-Infinity",
    "integer_out_of_range": "9007199254740993",
}
STRICT_FAULTS = ["top_level_duplicate", *NOT_STRICT_VALUES]
# A top-level duplicate is a first copy of a key of the input, holding an invalid value, placed before the valid copy: the last
# copy is the valid one.
INVALID_FIRST_COPY = {"mapping": '"row_id": 3, ', "population": '"item_ids": [], '}


def clean_documents(source, digest) -> dict:
    """The clean mapping and the clean population."""
    return {"mapping": {**MAPPING, "dataset_sha256": digest}, "population": {"item_ids": [r["day_key"] for r in rows_of(source)]}}


def fragment_and_place(which: str, clean: str, fault: str) -> tuple[str, int]:
    """The fragment of JSON text that carries `fault`, and the index in `clean`, the clean JSON text of the input `which`, where it
    is inserted."""
    if fault == "top_level_duplicate":
        return INVALID_FIRST_COPY[which], clean.index("{") + 1
    value = NOT_STRICT_VALUES[fault]
    if which == "population":
        # One more element of `item_ids`, after its last Item.
        return f", {value}", clean.rindex("]")
    # A last member of the mapping. No key of the mapping may hold an object, so the nested duplicate is the value of `extra`, a
    # key the mapping does not allow; each other value is the value of `model`, an allowed key the clean mapping does not hold.
    member = "extra" if fault == "nested_duplicate" else "model"
    return f", {json.dumps(member)}: {value}", clean.rindex("}")


def text_with_fault(which: str, clean: str, fault: str) -> str:
    """The clean JSON text `clean` of the input `which` with the fragment that carries `fault` inserted at its place."""
    fragment, place = fragment_and_place(which, clean, fault)
    return clean[:place] + fragment + clean[place:]


def write_mapping_and_population(folder, source, digest, faulty: str | None = None, fault: str | None = None):
    """The mapping and the population files, each the clean JSON text of its input, except that the input named by `faulty`, if
    any, carries `fault`."""
    paths = {}
    for name, document in clean_documents(source, digest).items():
        clean = json.dumps(document)
        paths[name] = Path(folder) / f"{name}.json"
        paths[name].write_text(text_with_fault(name, clean, fault) if name == faulty else clean, encoding="utf-8")
    return paths["mapping"], paths["population"]


@pytest.mark.parametrize("fault", sorted(STRICT_FAULTS))
@pytest.mark.parametrize("which", ["mapping", "population"])
def test_a_mapping_or_a_population_that_is_json_but_not_strict_json_is_refused_as_not_json_and_nothing_is_written(tmp_path, study, which, fault):
    """Each fault sits where a reader that is not strict would reach it, and is refused with the input's own code. A cell
at c77b9a6, for comparison: a top-level duplicate (the last copy wins) is accepted; `NaN`, `Infinity`, `-Infinity` and
an integer out of range as the value of `model` are `MAPPING_VALUE_INVALID` (the value is not a string), and as an element
of `item_ids` are `POPULATION_INVALID` with `problem` `bad_items` (the element is not an Item ID); a nested duplicate as an
element of `item_ids` is `bad_items` too. No key of the mapping holds an object, so its nested duplicate stays in an
`extra` member the mapping does not allow, where c77b9a6 gives `MAPPING_KEY_UNKNOWN`: the strict reader refuses it before
the key check."""
    source, digest = export(tmp_path)
    mapping_path, population_path = write_mapping_and_population(tmp_path, source, digest, faulty=which, fault=fault)
    before = snapshot(study)
    code, payload, _ = import_ml(study, source, mapping_path, population_path, f"r-{which}-{fault}")
    error = payload.get("error", {})
    details = error.get("details", {})
    assert (code, error.get("code"), error.get("stage"), details.get("problem"), set(details)) == (
        EXIT_INVALID_INPUT, f"{which.upper()}_INVALID", "import", "not_json", {which, "problem"}
    )
    assert snapshot(study) == before and not (study / "attempts").exists()


@pytest.mark.parametrize("which", ["mapping", "population"])
def test_each_fault_cell_of_an_input_minus_its_fragment_is_its_clean_text_and_the_clean_mapping_and_population_are_accepted_and_recorded(tmp_path, study, which):
    """For every fault of `which`, the text of the faulty file with its fragment cut out once is the text of the clean file,
    character for character; and the clean mapping and population are accepted and recorded."""
    source, digest = export(tmp_path)
    mapping_path, population_path = write_mapping_and_population(tmp_path, source, digest)
    clean = {"mapping": mapping_path, "population": population_path}[which].read_text(encoding="utf-8")
    for fault in STRICT_FAULTS:
        folder = tmp_path / fault
        folder.mkdir()
        faulty_mapping, faulty_population = write_mapping_and_population(folder, source, digest, faulty=which, fault=fault)
        faulty = {"mapping": faulty_mapping, "population": faulty_population}[which].read_text(encoding="utf-8")
        fragment, _ = fragment_and_place(which, clean, fault)
        assert faulty.replace(fragment, "", 1) == clean, fault
    code, payload, err = import_ml(study, source, mapping_path, population_path, f"r-ok-{which}")
    assert code == 0, (payload, err)
    assert (study / "attempts" / payload["attempt"]["attempt_id"]).is_dir()


def test_a_mapping_without_the_dataset_digest_is_refused_with_a_code_exit_2(tmp_path, study):
    source, _ = export(tmp_path)
    code, payload, _ = import_ml(study, source, write_json(tmp_path / "m.json", MAPPING), population_of(tmp_path, source), "r")
    assert (code, payload["error"]["code"], payload["error"]["details"]["key"]) == (EXIT_INVALID_INPUT, "MAPPING_KEY_MISSING", "dataset_sha256")


def test_a_dataset_digest_other_than_the_workload_locks_is_an_integrity_refusal_exit_3_and_publishes_nothing(tmp_path, study):
    """T08 (SPEC §10)."""
    source, digest = export(tmp_path)
    wrong = ("0" if digest[0] != "0" else "1") + digest[1:]
    before = snapshot(study)
    code, payload, _ = import_ml(study, source, mapping_of(tmp_path, wrong), population_of(tmp_path, source), "r")
    assert (code, payload["error"]["code"]) == (EXIT_INTEGRITY_REFUSED, "DATASET_DIGEST_MISMATCH")
    assert payload["error"]["details"] == {"declared_sha256": wrong, "locked_sha256": digest}
    assert snapshot(study) == before


def test_a_source_that_is_not_utf8_is_refused_with_a_code(tmp_path, study):
    source, digest = export(tmp_path)
    latin = tmp_path / "latin.csv"
    latin.write_bytes(source.read_bytes().replace(b"forecast_unrounded", "prévision".encode("latin-1"), 1))
    code, payload, _ = import_ml(study, latin, mapping_of(tmp_path, digest), population_of(tmp_path, source), "r")
    assert (code, payload["error"]["code"]) == (EXIT_INVALID_INPUT, "SOURCE_NOT_UTF8")


def test_a_missing_file_is_refused_with_a_code_for_each_of_the_three(tmp_path, study):
    source, mapping, population, _ = ready(tmp_path)
    gone = tmp_path / "gone"
    found = [
        import_ml(study, gone, mapping, population, "r")[1],
        import_ml(study, source, gone, population, "r")[1],
        import_ml(study, source, mapping, gone, "r")[1],
    ]
    assert [p["error"]["code"] for p in found] == ["SOURCE_NOT_FOUND", "MAPPING_NOT_FOUND", "POPULATION_NOT_FOUND"]


# --- AC4 and Tightened B2: the population comes from the Protocol -----------------------------------------------------


def test_a_population_item_outside_the_protocol_or_mixing_partitions_is_refused(tmp_path, study):
    source, mapping, _, _ = ready(tmp_path)
    ids = [r["day_key"] for r in rows_of(source)]
    cases = {
        "POPULATION_ITEM_UNKNOWN": [*ids, "bike-day:2030-01-01"],
        "POPULATION_MIXED_PARTITIONS": [*ids, "bike-day:2012-07-01"],
        "POPULATION_INVALID": [*ids, ids[0]],
    }
    for expected, items in cases.items():
        population = write_json(tmp_path / f"{expected}.json", {"item_ids": items})
        code, payload, _ = import_ml(study, source, mapping, population, "r")
        assert (code, payload["error"]["code"]) == (EXIT_INVALID_INPUT, expected)
    warm_up = write_json(tmp_path / "warm.json", {"item_ids": ["bike-day:2011-01-01"]})  # an Item of no Partition
    assert import_ml(study, source, mapping, warm_up, "r")[1]["error"]["code"] == "POPULATION_ITEM_UNKNOWN"
    assert not (study / "attempts").exists()


def test_the_source_never_supplies_or_widens_the_population_and_its_name_decides_nothing(tmp_path, study):
    source, digest = export(tmp_path, name="public_check.csv")  # named like another Partition, holds dev rows
    population = population_of(tmp_path, source)
    code, payload, err = import_ml(study, source, mapping_of(tmp_path, digest), population, "r")
    assert code == 0, (payload, err)
    assert payload["attempt"]["effective_config"]["partition"] == "dev"
    # a file that holds real Items of the Protocol that the population does not list is refused: it widens nothing
    narrower = write_json(tmp_path / "narrow.json", {"item_ids": [r["day_key"] for r in rows_of(source)][:10]})
    code, payload, _ = import_ml(study, source, mapping_of(tmp_path, digest, name="m2.json"), narrower, "r2")
    assert payload["error"]["code"] == "ROW_ID_OUTSIDE_POPULATION"


# --- AC5: the Import is in the same Study, and keeps what it was given -----------------------------------------------


def test_the_import_is_an_attempt_of_the_same_study_with_the_original_files_the_mapping_and_a_report(tmp_path, study):
    run_ml(study, "seasonal_7", "dev", "native")
    source, mapping, population, digest = ready(tmp_path, model="team-x trailing mean", generated_at="2026-10-01T08:00:00Z")
    code, payload, err = import_ml(study, source, mapping, population, "imp")
    assert code == 0, (payload, err)
    attempt = payload["attempt"]
    contracts.validate(attempt)
    assert (attempt["operation"], attempt["mode"], attempt["technical_status"]) == ("import", "external_unknown", "completed")
    assert (study / "attempts" / attempt["attempt_id"] / "attempt.json").read_bytes() == canonical.dumps(attempt)
    assert len(list((study / "attempts").iterdir())) == 2  # the native Attempt and the Import, one Study
    refs = {r["role"]: r for r in [*attempt["input_refs"], *attempt["output_refs"]]}
    folder = attempt_dir(study, attempt)
    assert (folder / "source" / "predictions.csv").read_bytes() == source.read_bytes()
    assert refs["import_source"]["sha256"] == sha256(source)
    assert refs["import_source"]["path"] == f"attempts/{attempt['attempt_id']}/source/predictions.csv"
    assert (folder / "mapping.json").read_bytes() == mapping.read_bytes() and refs["import_mapping"]["sha256"] == sha256(mapping)
    assert (folder / "population.json").read_bytes() == population.read_bytes() and refs["import_population"]["sha256"] == sha256(population)
    report = json.loads((folder / "validation_report.json").read_text())
    assert report["rows_read"] == 182 and all(c["result"] == "passed" for c in report["checks"]) and report["source_sha256"] == sha256(source)
    assert attempt["item_counts"] == {"produced": 182, "failed": 0, "missing": 0}
    config = attempt["effective_config"]
    assert config["import_time"] == attempt["started_at"]
    assert config["producer"]["generation_time"] == {"value": "2026-10-01T08:00:00Z", "origin": "declared"}
    assert config["producer"]["model"] == {"value": "team-x trailing mean", "origin": "declared"}
    assert config["producer"]["historical_protocol"] == {"value": None, "origin": "unknown"}
    assert config["producer"]["tool_use"] == {"value": None, "origin": "unknown"}
    assert not any(e["origin"] == "verified" for e in config["producer"].values())


def test_the_observation_set_of_an_import_is_imported_and_scored_like_a_native_one(tmp_path, study):
    _, native, _ = run_ml(study, "seasonal_7", "dev", "native")
    source, mapping, population, _ = ready(tmp_path)
    _, payload, _ = import_ml(study, source, mapping, population, "imp")
    record = json.loads((attempt_dir(study, payload["attempt"]) / "observation_set.json").read_text())
    assert (record["origin"], record["mode"], record["domain"]) == ("imported", "external_unknown", "regression")
    assert record["raw_refs"][0]["role"] == "import_source"
    assessment = measures(study, payload["attempt"], "regression_rmse_v1")
    assert assessment["observation_set_id"] == record["observation_set_id"] and assessment["counts"]["expected"] == 182
    assert measures(study, native["attempt"])["counts"]["expected"] == 182


# --- AC6: unknowns stay unknown, independence is never claimed -------------------------------------------------------


def test_an_import_with_no_producer_information_keeps_its_unknowns_can_be_assessed_and_claims_no_independence(tmp_path, study):
    """T09 (SPEC §10)."""
    source, mapping, population, _ = ready(tmp_path)
    _, payload, _ = import_ml(study, source, mapping, population, "imp")
    folder = attempt_dir(study, payload["attempt"])
    record = json.loads((folder / "observation_set.json").read_text())
    assert record["unknown_fields"] == ["model", "generation_time", "historical_protocol", "tool_use", "saw_public_check"]
    assert record["provenance"]["saw_public_check"] == {"value": None, "origin": "unknown"}
    assert measures(study, payload["attempt"])["metrics"][0]["status"] == "scored"
    for path in (folder / "attempt.json", folder / "observation_set.json", folder / "validation_report.json"):
        assert "independen" not in path.read_text().lower(), path


def test_whether_the_producer_saw_public_check_stays_unknown_even_when_the_mapping_declares_the_rest(tmp_path, study):
    """T09 (SPEC §10)."""
    source, mapping, population, _ = ready(tmp_path, model="m", generated_at="2026-10-01", historical_protocol="rolling", tool_use="none")
    _, payload, _ = import_ml(study, source, mapping, population, "imp")
    record = json.loads((attempt_dir(study, payload["attempt"]) / "observation_set.json").read_text())
    assert record["unknown_fields"] == ["saw_public_check"]


# --- AC7: nothing is executed or deserialised ------------------------------------------------------------------------


@pytest.mark.parametrize("name, content", [("model.pkl", b"\x80\x04N."), ("model.joblib", b"anything"), ("renamed.csv", b"\x80\x04\x95")])
def test_a_pickle_or_joblib_source_is_refused_with_a_code_and_never_loaded(tmp_path, study, name, content):
    _, mapping, population, _ = ready(tmp_path)
    serialized = tmp_path / name
    serialized.write_bytes(content)
    code, payload, _ = import_ml(study, serialized, mapping, population, "r")
    assert (code, payload["error"]["code"]) == (EXIT_INVALID_INPUT, "SOURCE_SERIALIZED")
    assert not (study / "attempts").exists()


@pytest.mark.parametrize("value", ["os.system", "pickle:loads", "__import__('os')", "builtins.eval", "lambda x: x", "../x"])
def test_a_mapping_value_naming_a_callable_or_a_module_is_refused_with_a_code(tmp_path, study, value):
    source, digest = export(tmp_path)
    mapping = write_json(tmp_path / "m.json", {"row_id": "day_key", "y_pred": value, "dataset_sha256": digest})
    code, payload, _ = import_ml(study, source, mapping, population_of(tmp_path, source), "r")
    assert (code, payload["error"]["code"]) == (EXIT_INVALID_INPUT, "MAPPING_VALUE_EXECUTABLE")


# --- AC8: no Inspect, no scikit-learn, offline -----------------------------------------------------------------------


def test_import_and_assess_run_with_neither_inspect_nor_scikit_learn_importable(tmp_path, study):
    source, mapping, population, _ = ready(tmp_path)
    script = textwrap.dedent(
        """
        import json, pathlib, sys
        BLOCKED = ("sklearn", "inspect_ai", "numpy", "scipy", "pandas")
        for name in BLOCKED:
            sys.modules[name] = None  # importing any of them now raises ImportError
        from hypotrail import cli
        a = sys.argv[1:]
        assert cli.main(["import", "ml", "--study", a[0], "--source", a[1], "--mapping", a[2], "--population", a[3], "--request-id", "x", "--json"]) == 0
        folder = next((pathlib.Path(a[0]) / "attempts").iterdir())
        osid = json.loads((folder / "observation_set.json").read_text())["observation_set_id"]
        spec = json.loads((pathlib.Path(a[0]) / "study.json").read_text())
        ref = next(e["artifact_id"] for e in spec["artifacts"] if e["ref"]["role"] == "references")
        assert cli.main(["assess", "--study", a[0], "--observations", osid, "--scorer", "regression_mae_v1", "--references", ref, "--json"]) == 0
        print("LOADED", sorted(m for m in sys.modules if sys.modules[m] is not None and m.split(".")[0] in BLOCKED))
        """
    )
    done = subprocess.run([sys.executable, "-c", script, str(study), str(source), str(mapping), str(population)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "LOADED []" in done.stdout


# --- AC9 and Tightened D2: the request identity ----------------------------------------------------------------------


def test_request_id_is_required_for_import(tmp_path, study):
    source, mapping, population, _ = ready(tmp_path)
    code, payload, _ = run_json("import", "ml", "--study", study, "--source", source, "--mapping", mapping, "--population", population)
    assert (code, payload["error"]["code"]) == (EXIT_INVALID_INPUT, "INVALID_ARGUMENTS")
    code, payload, _ = import_ml(study, source, mapping, population, "")
    assert (code, payload["error"]["code"]) == (EXIT_INVALID_INPUT, "REQUEST_ID_EMPTY")


def test_the_identity_holds_every_element_with_its_value_or_unknown(tmp_path, study):
    source, mapping, population, digest = ready(tmp_path)
    _, payload, _ = import_ml(study, source, mapping, population, "imp")
    attempt = payload["attempt"]
    identity = requests.identity(attempt["effective_config"], attempt["code_environment"])
    assert set(identity) == set(requests.ELEMENTS)
    assert (identity["command"], identity["workload"], identity["mode"], identity["partition"]) == ("import ml", "bike_day", "external_unknown", "dev")
    assert (identity["configuration"], identity["model"], identity["repeats"]) == ("unknown", "unknown", "unknown")
    assert identity["input_digests"] == {"dataset": digest, "source": sha256(source), "mapping": sha256(mapping), "population": sha256(population)}
    assert set(identity["code_revision"]) == {"commit", "dirty", "local_code_fingerprint"}


def test_the_same_request_returns_the_recorded_import_and_validates_reads_and_writes_nothing(tmp_path, study, monkeypatch):
    from hypotrail.ml import imports

    source, mapping, population, _ = ready(tmp_path)
    _, first, _ = import_ml(study, source, mapping, population, "imp")
    before = snapshot(study)

    def never(*args, **kwargs):
        raise AssertionError("the source was validated again")

    for name in ("_checked_source", "_checked_mapping", "_checked_population", "_joined"):
        monkeypatch.setattr(imports, name, never)
    code, again, err = import_ml(study, source, mapping, population, "imp")
    assert code == 0, (again, err)
    assert again["replayed"] is True and again["attempt"] == first["attempt"]
    assert snapshot(study) == before


@pytest.mark.parametrize("what", ["source", "mapping", "population", "model", "dirty"])
def test_the_same_request_id_with_another_request_is_request_conflict_exit_6(tmp_path, study, monkeypatch, what):
    source, mapping, population, digest = ready(tmp_path)
    _, first, _ = import_ml(study, source, mapping, population, "imp")
    before = snapshot(study)
    if what == "source":
        rows = rows_of(source)
        rows[0]["forecast_rentals"] = "1"
        source = write_rows(tmp_path / "other.csv", rows, FIELDS)
        expect = ["input_digests"]
    elif what == "mapping":
        mapping = mapping_of(tmp_path, digest, name="other-mapping.json", tool_use="none")
        expect = ["input_digests"]
    elif what == "population":
        population = write_json(tmp_path / "pop2.json", {"item_ids": json.loads(population.read_text())["item_ids"][::-1]})
        expect = ["input_digests"]
    elif what == "model":
        mapping = mapping_of(tmp_path, digest, name="model-mapping.json", model="other")
        expect = ["model", "input_digests"]
    else:
        from hypotrail.core import environment

        real = environment.code_environment()
        dirty = {**real, "code_revision": {**real["code_revision"], "dirty": True, "local_code_fingerprint": "f" * 64}}
        monkeypatch.setattr(environment, "code_environment", lambda *a, **k: dirty)
        expect = ["code_revision"]
    code, payload, _ = import_ml(study, source, mapping, population, "imp")
    assert (code, payload["error"]["code"]) == (EXIT_LOCK_OR_CONFLICT, "REQUEST_CONFLICT")
    assert payload["error"]["details"]["differs"] == expect
    assert payload["error"]["details"]["decision_id"] is None and payload["error"]["details"]["attempt_id"]  # #109 Tightened K
    assert snapshot(study) == before


def test_a_request_id_that_names_a_native_attempt_conflicts_with_an_import(tmp_path, study):
    run_ml(study, "seasonal_7", "dev", "shared")
    source, mapping, population, _ = ready(tmp_path)
    code, payload, _ = import_ml(study, source, mapping, population, "shared")
    assert (code, payload["error"]["code"]) == (EXIT_LOCK_OR_CONFLICT, "REQUEST_CONFLICT")
    assert "command" in payload["error"]["details"]["differs"]


# --- an error inside the live process, and the output forms -------------------------------------------------------------


def test_an_error_inside_the_process_leaves_a_failed_attempt_with_a_reason(tmp_path, study, monkeypatch):
    from hypotrail.core import artifacts

    source, mapping, population, _ = ready(tmp_path)
    real = artifacts.publish_record

    def broken_record(study_, relative, record, *, role):
        if role == "observation_set":
            raise OSError("disk full")
        return real(study_, relative, record, role=role)

    monkeypatch.setattr(artifacts, "publish_record", broken_record)
    code, payload, _ = import_ml(study, source, mapping, population, "imp")
    assert code == 4 and payload["error"]["code"] == "INFRASTRUCTURE_FAILURE"
    (folder,) = (study / "attempts").iterdir()
    manifest = json.loads((folder / "attempt.json").read_text())
    assert manifest["technical_status"] == "failed" and "disk full" in manifest["reason"]


def test_the_cli_reports_an_os_error_of_import_ml_as_it_always_did_by_type_and_message(tmp_path, study, monkeypatch):
    """R5-03, #81 keeps the other commands: only `run agent` reports an OS error by its type alone."""
    from hypotrail.core import artifacts

    source, mapping, population, _ = ready(tmp_path)
    real = artifacts.publish_record

    def broken_record(study_, relative, record, *, role):
        if role == "observation_set":
            raise OSError("disk full")
        return real(study_, relative, record, role=role)

    monkeypatch.setattr(artifacts, "publish_record", broken_record)
    code, payload, _ = import_ml(study, source, mapping, population, "imp")
    assert code == 4 and payload["error"]["code"] == "INFRASTRUCTURE_FAILURE"
    assert payload["error"]["message"] == "OSError: disk full" and payload["error"]["details"] == {}


def test_without_json_the_human_line_goes_to_stdout_and_a_refusal_to_stderr(tmp_path, study):
    from _study_helpers import run_cli

    source, mapping, population, _ = ready(tmp_path)
    code, out, err = run_cli("import", "ml", "--study", study, "--source", source, "--mapping", mapping, "--population", population, "--request-id", "h")
    assert code == 0 and out.startswith("Import ") and err == ""
    code, out, err = run_cli("import", "ml", "--study", study, "--source", tmp_path / "gone", "--mapping", mapping, "--population", population, "--request-id", "h2")
    assert code == 2 and out == "" and "SOURCE_NOT_FOUND" in err


# --- R1-12 (#67 Tightened B2): the population the import was given is the expected set of its Assessment -----------------


def test_assess_expects_the_items_of_the_imported_population_not_the_whole_partition(tmp_path, study):
    source, digest = export(tmp_path)
    ids = [r["day_key"] for r in rows_of(source)][:10]
    subset = write_rows(tmp_path / "subset.csv", rows_of(source)[:10], FIELDS)
    population = write_json(tmp_path / "ten.json", {"item_ids": ids})
    code, payload, err = import_ml(study, subset, mapping_of(tmp_path, digest), population, "ten")
    assert code == 0, (payload, err)
    assessment = measures(study, payload["attempt"])
    assert assessment["counts"]["expected"] == 10
    assert assessment["counts"]["attempted"] == 10 and assessment["counts"]["scored"] == 10
    assert assessment["counts"]["missing"] == 0 if "missing" in assessment["counts"] else True
    per_item = rows_of(Path(study) / assessment["per_item_ref"]["path"])
    assert sorted(r["row_id"] for r in per_item) == sorted(ids)
