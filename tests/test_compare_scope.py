"""Ticket #71: what a Comparison says about its scope: Imports are descriptive, code environments are never hidden."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from _assess_helpers import assess, observation_set_id, references_id
from _compare_helpers import assessed, compare
from _import_helpers import import_ml, ready
from _study_helpers import run_json


@pytest.fixture
def native_and_import(tmp_path):
    study, attempts, a = assessed(tmp_path, "seasonal_7")
    source, mapping, population, _ = ready(tmp_path)
    code, payload, err = import_ml(study, source, mapping, population, "import-a")
    assert code == 0, (payload, err)
    code, scored, err = assess(study, observation_set_id(study, payload["attempt"]), "regression_mae_v1", references_id(study))
    assert code == 0, (scored, err)
    return study, a["seasonal_7"], scored["assessment"]


@pytest.mark.parametrize("import_is", ["candidate", "control"])
def test_a_comparison_against_an_import_is_descriptive_never_strict_and_carries_a_warning(native_and_import, import_is):
    study, native, imported = native_and_import
    control, candidate = (native, imported) if import_is == "candidate" else (imported, native)
    code, payload, err = compare(study, control["assessment_id"], candidate["assessment_id"])
    assert code == 0, (payload, err)
    record = payload["comparison"]
    assert record["comparability"]["status"] == "descriptive_only"
    mode = next(c for c in record["comparability"]["checks"] if c["check"] == "mode")
    assert mode == {"check": "mode", "passed": False, "reason": "provenance_unverified"}
    assert [w["code"] for w in record["warnings"]] == ["COMPARISON_DESCRIPTIVE_IMPORT"]
    assert import_is in record["warnings"][0]["message"] and "descriptive" in record["warnings"][0]["message"]
    assert record["warnings"][0]["message"] in record["limitations"]
    assert record["coverage"]["paired"] == 182
    assert "COMPARISON_DESCRIPTIVE_IMPORT" in err  # the warning also reaches the person who runs the command


def test_the_import_on_both_sides_is_descriptive_too(native_and_import):
    study, _, imported = native_and_import
    code, payload, _ = compare(study, imported["assessment_id"], imported["assessment_id"])
    assert code == 0 and payload["comparison"]["comparability"]["status"] == "descriptive_only"


def test_a_strict_comparison_of_seasonal_7_and_ridge_v1_carries_only_the_single_feature_warning_and_stderr_only_that_warning(tmp_path):
    study, _, a = assessed(tmp_path, "seasonal_7", "ridge_v1")
    _, payload, err = compare(study, a["seasonal_7"]["assessment_id"], a["ridge_v1"]["assessment_id"])
    warnings = payload["comparison"]["warnings"]
    assert [w["code"] for w in warnings] == ["COMPARISON_SINGLE_FEATURE_BEATS"]
    assert err == f"{warnings[0]['code']}: {warnings[0]['message']}\n"


def _rewrite_environment(study, attempt, edit):
    path = Path(study) / "attempts" / attempt["attempt_id"] / "attempt.json"
    manifest = json.loads(path.read_text())
    edit(manifest["code_environment"])
    path.write_text(json.dumps(manifest))


def test_different_code_environments_are_said_and_the_executions_are_never_called_identical(tmp_path):
    study, attempts, a = assessed(tmp_path, "seasonal_7", "ridge_v1")
    _rewrite_environment(study, attempts["ridge_v1"], lambda env: env.update(python="3.0.0"))
    code, payload, _ = compare(study, a["seasonal_7"]["assessment_id"], a["ridge_v1"]["assessment_id"])
    record = payload["comparison"]
    assert code == 0 and record["comparability"]["status"] == "compatible"  # a descriptive-or-strict verdict is not hidden by it
    assert record["code_environment"]["same"] is False and record["code_environment"]["differs"] == ["python"]
    assert record["code_environment"]["candidate"]["python"] == "3.0.0"
    text = " ".join(record["limitations"])
    assert "different code environments" in text and "not identical" in text


def test_the_same_code_environment_does_not_establish_identical_executions_either(tmp_path):
    study, _, a = assessed(tmp_path, "seasonal_7", "ridge_v1")
    _, payload, _ = compare(study, a["seasonal_7"]["assessment_id"], a["ridge_v1"]["assessment_id"])
    record = payload["comparison"]
    assert record["code_environment"]["same"] is True and record["code_environment"]["differs"] == []
    text = " ".join(record["limitations"])
    assert "does not establish" in text and "identical" in text and "not identical" not in text


def test_compare_runs_with_inspect_not_importable(tmp_path):
    script = textwrap.dedent(
        """
        import json, pathlib, sys
        sys.modules["inspect_ai"] = None  # importing Inspect now raises ImportError
        from hypotrail import cli
        study = pathlib.Path(sys.argv[1])
        def run(*args):
            assert cli.main([*map(str, args), "--json"]) == 0, args
        run("init", "--workload", "bike_day", "--study", study)
        ids = {}
        spec = json.loads((study / "study.json").read_text())
        refs = next(e["artifact_id"] for e in spec["artifacts"] if e["ref"]["role"] == "references")
        for config in ("seasonal_7", "ridge_v1"):
            run("run", "ml", "--study", study, "--config", config, "--partition", "dev", "--request-id", config)
            folder = next(p for p in (study / "attempts").iterdir() if json.loads((p / "attempt.json").read_text())["request_id"] == config)
            osid = json.loads((folder / "observation_set.json").read_text())["observation_set_id"]
            run("assess", "--study", study, "--observations", osid, "--scorer", "regression_mae_v1", "--references", refs)
            ids[config] = next(p.name for p in (study / "assessments").iterdir() if json.loads((p / "assessment.json").read_text())["observation_set_id"] == osid)
        run("compare", "--study", study, "--control", ids["seasonal_7"], "--candidate", ids["ridge_v1"])
        print("LOADED", sorted(m for m in sys.modules if sys.modules[m] is not None and m.split(".")[0] == "inspect_ai"))
        """
    )
    done = subprocess.run([sys.executable, "-c", script, str(tmp_path / "study")], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "LOADED []" in done.stdout


def test_with_json_stdout_holds_one_object_and_the_diagnostics_go_to_stderr(native_and_import):
    study, native, imported = native_and_import
    from _study_helpers import run_cli

    code, out, err = run_cli("compare", "--study", study, "--control", native["assessment_id"], "--candidate", imported["assessment_id"], "--json")
    assert code == 0 and set(json.loads(out)) == {"ok", "comparison"}  # one JSON object, nothing else
    assert "COMPARISON_DESCRIPTIVE_IMPORT" in err
    code, out, err = run_cli("compare", "--study", study, "--control", "nope", "--candidate", "nope", "--json")
    error = json.loads(out)["error"]
    assert code == 2 and set(error) == {"code", "message", "stage", "details"} and "ASSESSMENT_NOT_FOUND" in err
    code, out, err = run_cli("compare", "--study", study, "--control", "x", "--json")  # a missing flag is an error object too
    assert code == 2 and json.loads(out)["error"]["code"] == "INVALID_ARGUMENTS"


def test_a_folder_that_is_no_study_is_refused_without_creating_a_lock(tmp_path):
    code, payload, _ = run_json("compare", "--study", tmp_path / "empty", "--control", "a", "--candidate", "b")
    assert (code, payload["error"]["code"]) == (2, "STUDY_NOT_FOUND")
    assert not (tmp_path / "empty").exists()


# --- R1-13 (#72 Tightened C, ID-03): an Import records the importer's environment, not its producer's -------------------------------


@pytest.mark.parametrize("import_is", ["candidate", "control"])
def test_a_comparison_with_an_import_does_not_say_the_two_attempts_share_a_code_environment(native_and_import, import_is):
    study, native, imported = native_and_import
    control, candidate = (native, imported) if import_is == "candidate" else (imported, native)
    record = compare(study, control["assessment_id"], candidate["assessment_id"])[1]["comparison"]
    assert record["code_environment"]["same"] is None and "import_sides" not in record["code_environment"]
    text = " ".join(record["limitations"])
    assert "record the same code environment" not in text and "different code environments" not in text
    assert "importer" in text and "not established" in text


def test_a_bike_comparison_records_its_seven_checks_in_order_and_no_cases_check(tmp_path):
    study, _, a = assessed(tmp_path, "seasonal_7", "ridge_v1")
    code, payload, err = compare(study, a["seasonal_7"]["assessment_id"], a["ridge_v1"]["assessment_id"])
    assert code == 0, (payload, err)
    names = [c["check"] for c in payload["comparison"]["comparability"]["checks"]]
    assert names == ["population", "references", "scorer", "unit", "items", "mode", "coverage"]
