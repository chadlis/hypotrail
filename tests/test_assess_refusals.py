"""Ticket #66: what `assess` refuses, and that it needs no fit, no model, no tool and no network."""

import json
import subprocess
import sys
import textwrap

import pytest
from _assess_helpers import assess, construct, fresh_study, observation_set_id, references_id, snapshot
from _study_helpers import run_cli

from hypotrail.core.errors import EXIT_INTEGRITY_REFUSED, EXIT_INVALID_INPUT


def refused(result, code, exit_code):
    status, payload, _ = result
    assert status == exit_code, payload
    assert payload["ok"] is False and payload["error"]["code"] == code, payload
    assert set(payload["error"]) == {"code", "message", "stage", "details"}
    return payload["error"]


@pytest.fixture
def kept(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    return study, attempts["seasonal_7"], observation_set_id(study, attempts["seasonal_7"])


# --- AC5: no fit, no prediction, no model, no tool, no network ----------------------------------------


def test_assess_succeeds_with_fit_prediction_and_tools_replaced_by_functions_that_fail(kept, monkeypatch):
    from hypotrail.agentic import sql_tool
    from hypotrail.ml import baselines, ridge, run

    study, _, obs = kept

    def forbidden(*args, **kwargs):
        raise AssertionError("assess called something that fits, predicts or uses a tool")

    monkeypatch.setattr(run, "run_ml", forbidden)
    monkeypatch.setattr(ridge, "write_outputs", forbidden)
    monkeypatch.setattr(baselines, "write_seasonal_baseline", forbidden)
    for name in ("execute", "run_query", "query"):
        if hasattr(sql_tool, name):
            monkeypatch.setattr(sql_tool, name, forbidden)
    # the estimators of scikit-learn fail too, through the probe of the Attempt tests
    from _ml_helpers import fit_probe

    with fit_probe(strict=True) as probe:
        status, payload, err = assess(study, obs, "regression_mae_v1", references_id(study))
    assert status == 0, (payload, err)
    assert probe.calls == []


def test_assess_does_not_import_scikit_learn_numpy_or_inspect(kept):
    study, _, obs = kept
    script = textwrap.dedent(
        """
        import json, sys
        from hypotrail import cli
        code = cli.main(["assess", "--study", sys.argv[1], "--observations", sys.argv[2],
                         "--scorer", "regression_rmse_v1", "--references", sys.argv[3], "--json"])
        loaded = sorted(m for m in sys.modules if m.split(".")[0] in ("sklearn", "numpy", "scipy", "inspect_ai", "pandas"))
        sys.stderr.write(json.dumps({"code": code, "loaded": loaded}))
        """
    )
    done = subprocess.run(
        [sys.executable, "-c", script, str(study), obs, references_id(study)], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    outcome = json.loads(done.stderr.splitlines()[-1])
    assert outcome == {"code": 0, "loaded": []}
    assert json.loads(done.stdout)["ok"] is True


# --- AC6: a closed registry ------------------------------------------------------------------------------


@pytest.mark.parametrize("scorer", ["no_such_scorer_v1", "chinook_contract_v2", "planted_scorer:run", "planted_scorer", "os.path:join", ""])
def test_a_scorer_not_in_the_registry_is_refused_and_nothing_is_imported_from_the_string(kept, tmp_path, monkeypatch, scorer):
    plant = tmp_path / "plant"
    plant.mkdir()
    (plant / "planted_scorer.py").write_text("raise SystemExit('imported')\n")
    monkeypatch.syspath_prepend(str(plant))
    study, _, obs = kept
    before = snapshot(study)
    error = refused(assess(study, obs, scorer, references_id(study)), "SCORER_NOT_REGISTERED", EXIT_INVALID_INPUT)
    assert error["stage"] == "assess" and error["details"]["registered"] == ["chinook_contract_v1", "regression_mae_v1", "regression_rmse_v1"]
    assert "planted_scorer" not in sys.modules
    assert snapshot(study) == before and not (study / "assessments").exists()


def test_a_scorer_of_another_track_applied_to_this_observation_set_is_refused_with_a_code(kept):
    study, attempt, _ = kept
    obs = construct(study, attempt, lambda rows: rows, domain="agentic")
    before = snapshot(study)
    error = refused(assess(study, obs, "regression_mae_v1", references_id(study)), "UNSUPPORTED_CAPABILITY", EXIT_INVALID_INPUT)
    assert error["details"] == {"scorer": "regression_mae_v1", "scorer_domain": "regression", "observation_set_domain": "agentic"}
    assert snapshot(study) == before


def test_an_unknown_observation_set_and_an_unknown_references_set_are_refused(kept):
    study, _, obs = kept
    refused(assess(study, "no-such-set", "regression_mae_v1", references_id(study)), "OBSERVATION_SET_NOT_FOUND", EXIT_INVALID_INPUT)
    error = refused(assess(study, obs, "regression_mae_v1", "references-0000"), "REFERENCES_NOT_FOUND", EXIT_INVALID_INPUT)
    assert error["details"]["available"] == [references_id(study)]
    refused(assess(study, obs, "regression_mae_v1", "memberships-" + references_id(study)[11:]), "REFERENCES_NOT_FOUND", EXIT_INVALID_INPUT)
    assert not (study / "assessments").exists()


def test_an_observation_set_with_an_item_outside_its_partition_or_twice_is_refused(kept):
    study, attempt, _ = kept
    stray = construct(study, attempt, lambda rows: [*rows, {**rows[0], "row_id": "bike-day:1999-01-01"}])
    refused(assess(study, stray, "regression_mae_v1", references_id(study)), "OBSERVATIONS_INVALID", EXIT_INVALID_INPUT)
    twice = construct(study, attempt, lambda rows: [*rows, rows[0]])
    error = refused(assess(study, twice, "regression_mae_v1", references_id(study)), "OBSERVATIONS_INVALID", EXIT_INVALID_INPUT)
    assert error["details"]["problem"] == "duplicate_item"
    assert not (study / "assessments").exists()


# --- AC7: integrity ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative",
    ["predictions.csv", "observations.csv", "observation_set.json", "../../artifacts/references.csv", "../../artifacts/memberships.csv"],
)
def test_a_referenced_artifact_that_no_longer_matches_its_digest_is_an_integrity_refusal_and_writes_nothing(kept, relative):
    study, attempt, obs = kept
    target = (study / "attempts" / attempt["attempt_id"] / relative).resolve()
    original = target.read_bytes()
    target.write_bytes(original + b"\n")
    before = snapshot(study)
    error = refused(assess(study, obs, "regression_mae_v1", references_id(study)), "ARTIFACT_INTEGRITY", EXIT_INTEGRITY_REFUSED)
    assert error["details"]["path"].endswith(target.name)
    assert snapshot(study) == before and not (study / "assessments").exists()


def test_a_missing_referenced_artifact_is_an_integrity_refusal(kept):
    study, attempt, obs = kept
    (study / "attempts" / attempt["attempt_id"] / "predictions.csv").unlink()
    refused(assess(study, obs, "regression_mae_v1", references_id(study)), "ARTIFACT_MISSING", EXIT_INTEGRITY_REFUSED)
    assert not (study / "assessments").exists()


# --- AC8 / Tightened B: which Partitions an Assessment may score ---------------------------------------------


def test_an_assessment_on_dev_is_scored_and_on_train_is_refused_with_a_code(kept):
    study, attempt, obs = kept
    status, payload, _ = assess(study, obs, "regression_mae_v1", references_id(study))
    assert status == 0
    on_train = construct(study, attempt, lambda rows: rows, provenance={"partition": "train"})
    before = set(p.name for p in (study / "assessments").iterdir())
    error = refused(assess(study, on_train, "regression_mae_v1", references_id(study)), "ASSESSMENT_PARTITION_NOT_DEV", EXIT_INVALID_INPUT)
    assert error["details"] == {"partition": "train"}
    assert set(p.name for p in (study / "assessments").iterdir()) == before


def test_an_assessment_on_public_check_is_refused_with_its_own_code_while_run_ml_on_public_check_stays_allowed(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7", partition="public_check")  # not an Exposure: it is allowed
    obs = observation_set_id(study, attempts["seasonal_7"])
    error = refused(assess(study, obs, "regression_mae_v1", references_id(study)), "ASSESSMENT_PUBLIC_CHECK_REFUSED", EXIT_INVALID_INPUT)
    assert error["details"] == {"partition": "public_check"}
    assert not (study / "assessments").exists()


# --- Tightened J: --json and errors -----------------------------------------------------------------------------------


def test_with_json_stdout_is_one_object_and_the_diagnostic_goes_to_stderr(kept):
    study, _, obs = kept
    for scorer, ok in (("regression_mae_v1", True), ("nope", False)):
        status, out, err = run_cli("assess", "--study", study, "--observations", obs, "--scorer", scorer, "--references", references_id(study), "--json")
        payload = json.loads(out)  # exactly one JSON object, nothing else on stdout
        assert payload["ok"] is ok
        assert (status == 0) is ok
        assert (err == "") if ok else err.startswith("SCORER_NOT_REGISTERED [assess]:")


def test_without_json_stdout_is_one_line_and_a_missing_flag_is_an_argument_error(kept):
    study, _, obs = kept
    status, out, err = run_cli("assess", "--study", study, "--observations", obs, "--scorer", "regression_mae_v1", "--references", references_id(study))
    assert status == 0 and len(out.strip().splitlines()) == 1 and out.startswith("Assessment ") and err == ""
    status, out, err = run_cli("assess", "--study", study, "--scorer", "regression_mae_v1", "--references", references_id(study), "--json")
    assert status == EXIT_INVALID_INPUT and json.loads(out)["error"]["code"] == "INVALID_ARGUMENTS"
    status, out, _ = run_cli("assess", "--study", study / "none", "--observations", obs, "--scorer", "regression_mae_v1", "--references", "r", "--json")
    assert status == EXIT_INVALID_INPUT and json.loads(out)["error"]["code"] == "STUDY_NOT_FOUND"
