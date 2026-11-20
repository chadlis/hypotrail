"""Ticket #70 (T11): a corrected References set gives a new Assessment, old files unchanged, the cause of the delta stated.

The corrected set is added through a new StudySpec revision (#70 Tightened A2, `init --new-revision`). The
new Assessment scores the same Observation set under the new revision's Protocol, and names the earlier
Assessment, the cause and the Items whose verdict changed with both verdicts. Nothing here calls a model.
"""

import dataclasses
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from _assess_helpers import assess as assess_ml
from _assess_helpers import fresh_study, observation_set_id, per_item
from _assess_helpers import references_id as ml_references_id
from _chinook_helpers import FIXTURE, fixture_lines, fixture_population, import_agent, init_chinook, references_id, write_lines
from _revision_helpers import corrected_chinook_references, error_of, new_revision, snapshot_files, spec_of
from _study_helpers import examples_copy, run_cli, run_json

from hypotrail.core import contracts, scorers

SCORER = "chinook_contract_v1"


def imported(tmp_path, lines=None, *, name="study"):
    """(study, Observation set ID) of a Chinook Study that imported `lines` (the kit's authored answers by default)."""
    study = init_chinook(tmp_path, name=name)[0]
    source = FIXTURE if lines is None else write_lines(tmp_path / f"{name}-answers.jsonl", lines)
    code, payload, err = import_agent(study, source, fixture_population(tmp_path, f"{name}-population.json"), "imp")
    assert code == 0, (payload, err)
    folder = Path(study) / "attempts" / payload["attempt"]["attempt_id"]
    return study, json.loads((folder / "observation_set.json").read_text())["observation_set_id"]


def assess_agent(study, observation_set, references, *more):
    return run_json("assess", "--study", study, "--observations", observation_set, "--scorer", SCORER, "--references", references, *more)


def assessed(study, observation_set, references=None):
    code, payload, err = assess_agent(study, observation_set, references or references_id(study))
    assert code == 0, (payload, err)
    return payload["assessment"]


def revised(study, edit, tmp_path, name):
    code, payload, err = new_revision(study, "--examples-dir", corrected_chinook_references(tmp_path, edit, name=name))
    assert code == 0, (payload, err)
    return payload["study"]


def correct_d03(records):
    records["D03"].update(rows=[[1300]], reference_version="chinook-references/2")


def tolerate_one_on_d01(records):
    records["D01"].update(numeric_absolute_tolerance=1, reference_version="chinook-references/2")


def off_by_one_on_d01():
    lines = fixture_lines()
    d01 = next(line for line in lines if line["case_id"] == "D01")
    d01["final_answer"] = {**d01["final_answer"], "rows": [[3504]]}
    return lines


def changed(record):
    return {(c["item_id"], c["criterion"]): (c["earlier"], c["now"]) for c in record["rescoring"]["changed_items"]}


def verdict(state, score, reason=None):
    return {"state": state, "score": score, "reason": reason}


# --- AC1, AC2: the corrected set is a new artifact, and the new Assessment is another record of the same Observation set -------


def test_the_new_assessment_scores_the_same_observation_set_against_the_corrected_set_and_every_earlier_file_keeps_its_digest(tmp_path):
    study, observation_set = imported(tmp_path)
    first = assessed(study, observation_set)
    old_references = first["references_ref"]
    before = snapshot_files(study)
    revised(study, correct_d03, tmp_path, "corrected")
    second = assessed(study, observation_set)
    contracts.validate(second)
    assert second["assessment_id"] != first["assessment_id"]
    assert second["observation_set_id"] == first["observation_set_id"] == observation_set
    assert second["references_ref"] != old_references and second["references_ref"]["sha256"] != old_references["sha256"]
    after = snapshot_files(study)
    assert {path: digest for path, digest in after.items() if path in before and path != "study.json"} == {
        path: digest for path, digest in before.items() if path != "study.json"
    }
    assert after[old_references["path"]] == old_references["sha256"]  # the earlier References, same digest
    assert after[second["references_ref"]["path"]] == second["references_ref"]["sha256"]  # and the corrected set beside it
    assert (study / first["per_item_ref"]["path"]).is_file() and (study / first["detailed_metrics_ref"]["path"]).is_file()


def test_the_first_assessment_names_no_earlier_one_and_each_records_the_revision_it_applied(tmp_path):
    study, observation_set = imported(tmp_path)
    first = assessed(study, observation_set)
    assert first["rescoring"] is None
    revision_one = spec_of(study)
    assert first["study_revision"] == {"number": 1, "revision": revision_one["revision"], "protocol_digest": revision_one["protocol_digest"]}
    revision_two = revised(study, correct_d03, tmp_path, "corrected")
    second = assessed(study, observation_set)
    assert second["study_revision"] == {"number": 2, "revision": revision_two["revision"], "protocol_digest": revision_two["protocol_digest"]}
    assert first["recorded_at"] < second["recorded_at"]


def test_an_assessment_applies_the_references_of_its_own_revision(tmp_path):
    study, observation_set = imported(tmp_path)
    old_id = references_id(study)
    revised(study, correct_d03, tmp_path, "corrected")
    code, payload, _ = assess_agent(study, observation_set, old_id)
    error = error_of(payload)
    assert (code, error["code"]) == (2, "REFERENCES_NOT_FOUND")
    assert error["details"]["available"] == [references_id(study)] and old_id not in error["details"]["available"]


# --- AC3: the earlier Assessment, the cause and the Items whose verdict changed ------------------------------------------------


def test_a_corrected_reference_version_flips_the_expected_item_and_the_new_assessment_says_why(tmp_path):
    study, observation_set = imported(tmp_path)
    first = assessed(study, observation_set)
    revised(study, correct_d03, tmp_path, "corrected")
    second = assessed(study, observation_set)
    rescoring = second["rescoring"]
    assert rescoring["earlier_assessment_id"] == first["assessment_id"] and rescoring["cause"] == "references_version"
    assert "other_changes" not in rescoring
    assert changed(second) == {
        ("D03#0", "exact_table"): (verdict("scored", True), verdict("scored", False)),
        ("D03#0", "contract_success"): (verdict("unscored", None, "trace_missing"), verdict("scored", False)),
    }
    assert (first["counts"]["incorrect"], second["counts"]["incorrect"]) == (0, 1)  # the verdicts moved, the answers did not
    assert first["counts"]["correct"] == second["counts"]["correct"]


def test_a_changed_numeric_tolerance_flips_the_expected_item_and_both_versions_are_kept(tmp_path):
    study, observation_set = imported(tmp_path, off_by_one_on_d01())
    first = assessed(study, observation_set)
    old_references = (study / first["references_ref"]["path"]).read_bytes()
    revised(study, tolerate_one_on_d01, tmp_path, "tolerant")
    second = assessed(study, observation_set)
    assert second["rescoring"]["earlier_assessment_id"] == first["assessment_id"] and second["rescoring"]["cause"] == "references_version"
    assert changed(second) == {
        ("D01#0", "exact_table"): (verdict("scored", False), verdict("scored", True)),
        ("D01#0", "contract_success"): (verdict("scored", False), verdict("unscored", None, "trace_missing")),
    }
    old_record = json.loads(old_references.decode().splitlines()[0])
    new_record = json.loads((study / second["references_ref"]["path"]).read_text().splitlines()[0])
    assert (old_record["numeric_absolute_tolerance"], new_record["numeric_absolute_tolerance"]) == (0, 1)
    assert (study / first["references_ref"]["path"]).read_bytes() == old_references  # both versions are kept


def test_an_unchanged_reference_changes_no_item_and_the_record_says_so(tmp_path):
    study, observation_set = imported(tmp_path)
    first = assessed(study, observation_set)

    def correct_d04(records):  # a Case the answers do not cover: the Protocol changes, no verdict does
        records["D04"].update(rows=[[7]])

    revised(study, correct_d04, tmp_path, "elsewhere")
    second = assessed(study, observation_set)
    assert second["rescoring"] == {"earlier_assessment_id": first["assessment_id"], "cause": "references_version", "changed_items": []}


def test_an_assessment_under_the_same_inputs_names_no_earlier_assessment(tmp_path):
    study, observation_set = imported(tmp_path)
    assessed(study, observation_set)
    assert assessed(study, observation_set)["rescoring"] is None  # nothing differs: this is a repeat, not a rescoring


def test_each_revision_names_the_assessment_of_the_one_before(tmp_path):
    study, observation_set = imported(tmp_path)
    first = assessed(study, observation_set)
    revised(study, correct_d03, tmp_path, "one")
    second = assessed(study, observation_set)

    def correct_again(records):
        correct_d03(records)
        records["D03"].update(rows=[[1297]])  # back to the first answer

    revised(study, correct_again, tmp_path, "two")
    third = assessed(study, observation_set)
    assert second["rescoring"]["earlier_assessment_id"] == first["assessment_id"]
    assert third["rescoring"]["earlier_assessment_id"] == second["assessment_id"]
    assert third["study_revision"]["number"] == 3
    assert changed(third)[("D03#0", "exact_table")] == (verdict("scored", False), verdict("scored", True))


# --- the Scorer as the cause --------------------------------------------------------------------------------------------------


def with_scorer(monkeypatch, **changes):
    monkeypatch.setitem(scorers.REGISTRY, SCORER, dataclasses.replace(scorers.REGISTRY[SCORER], **changes))


@pytest.mark.parametrize(
    ("changes", "cause"),
    [
        ({"version": "4"}, "scorer_version"),
        ({"criteria": tuple(reversed(scorers.REGISTRY[SCORER].criteria))}, "scorer_config_digest"),
    ],
)
def test_a_changed_scorer_version_or_configuration_is_named_as_the_cause(tmp_path, monkeypatch, changes, cause):
    study, observation_set = imported(tmp_path)
    first = assessed(study, observation_set)
    with_scorer(monkeypatch, **changes)
    second = assessed(study, observation_set)
    assert second["rescoring"] == {"earlier_assessment_id": first["assessment_id"], "cause": cause, "changed_items": []}
    assert second["references_ref"] == first["references_ref"]


def test_an_assessment_recorded_under_version_two_gives_the_cause_scorer_version_when_assessed_again(tmp_path, monkeypatch):
    """#61 AC5 (Tightened D): the version moved from 2 to the current one."""
    study, observation_set = imported(tmp_path)
    with_scorer(monkeypatch, version="2")
    first = assessed(study, observation_set)
    assert first["scorer"]["version"] == "2"
    monkeypatch.undo()
    second = assessed(study, observation_set)
    assert second["scorer"]["version"] == "3"
    assert second["rescoring"] == {"earlier_assessment_id": first["assessment_id"], "cause": "scorer_version", "changed_items": []}


def test_when_several_things_changed_the_first_is_the_cause_and_the_others_are_listed(tmp_path, monkeypatch):
    study, observation_set = imported(tmp_path)
    assessed(study, observation_set)
    revised(study, correct_d03, tmp_path, "corrected")
    with_scorer(monkeypatch, version="4", criteria=tuple(reversed(scorers.REGISTRY[SCORER].criteria)))
    rescoring = assessed(study, observation_set)["rescoring"]
    assert rescoring["cause"] == "references_version" and rescoring["other_changes"] == ["scorer_version", "scorer_config_digest"]


# --- RES-01: no model, no tool, not the Chinook file --------------------------------------------------------------------------


def test_the_rescoring_calls_no_model_runs_no_tool_and_does_not_open_the_chinook_file(tmp_path):
    study, observation_set = imported(tmp_path)
    corrected = corrected_chinook_references(tmp_path, correct_d03, name="corrected")
    script = textwrap.dedent(
        """
        import json, shutil, sqlite3, sys
        BLOCKED = ("inspect_ai", "sklearn", "numpy", "scipy", "pandas", "anthropic", "openai")
        for name in BLOCKED:
            sys.modules[name] = None  # importing any of them now raises ImportError
        from hypotrail import cli
        study, observation_set, corrected = sys.argv[1:]

        def ref():
            return next(e["artifact_id"] for e in json.load(open(study + "/study.json"))["artifacts"] if e["ref"]["role"] == "references")

        def assess():
            return cli.main(["assess", "--study", study, "--observations", observation_set, "--scorer", "chinook_contract_v1", "--references", ref(), "--json"])

        assert assess() == 0
        assert cli.main(["init", "--study", study, "--new-revision", "--examples-dir", corrected, "--json"]) == 0
        shutil.rmtree(corrected + "/chinook")  # the Workload is gone: the Study's frozen files are enough
        used = []
        def never(*args, **kwargs):
            used.append("sqlite3.connect")
            raise AssertionError("the database was opened")
        sqlite3.connect = never
        assert assess() == 0
        loaded = sorted(m for m in sys.modules if sys.modules[m] is not None and m.split(".")[0] in BLOCKED)
        agentic = sorted(m for m in sys.modules if m in ("hypotrail.agentic.sql_tool", "hypotrail.agentic.runner", "hypotrail.agentic.projection", "hypotrail.agentic.live"))
        print("LOADED", loaded, agentic, used)
        """
    )
    done = subprocess.run([sys.executable, "-c", script, str(study), observation_set, str(corrected)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "LOADED [] [] []" in done.stdout


# --- the Bike Track: a numeric loss, no binary verdict --------------------------------------------------------------------------


def test_a_corrected_day_changes_the_absolute_error_of_that_item_only(tmp_path):
    study, attempts = fresh_study(tmp_path, "seasonal_7")
    observations = observation_set_id(study, attempts["seasonal_7"])
    _, payload, _ = assess_ml(study, observations, "regression_mae_v1", ml_references_id(study))
    first = payload["assessment"]
    assert first["rescoring"] is None

    def correct_a_day(table):
        row = next(r for r in table if r["dteday"] == "2012-03-15")
        row["cnt"], row["registered"] = str(int(row["cnt"]) + 1000), str(int(row["registered"]) + 1000)

    code, revised_payload, err = new_revision(study, "--examples-dir", examples_copy(tmp_path, rows=correct_a_day))
    assert code == 0, (revised_payload, err)
    _, payload, _ = assess_ml(study, observations, "regression_mae_v1", ml_references_id(study))
    second = payload["assessment"]
    contracts.validate(second)
    assert second["observation_set_id"] == first["observation_set_id"] and second["assessment_id"] != first["assessment_id"]
    rescoring = second["rescoring"]
    assert rescoring["earlier_assessment_id"] == first["assessment_id"] and rescoring["cause"] == "references_version"
    (item,) = rescoring["changed_items"]
    before, after = per_item(study, first)[item["item_id"]], per_item(study, second)[item["item_id"]]
    assert item["criterion"] == "absolute_error"
    assert item["earlier"] == verdict("scored", float(before["value"])) and item["now"] == verdict("scored", float(after["value"]))
    assert item["earlier"]["score"] != item["now"]["score"]
    assert second["metrics"][0]["value"] != first["metrics"][0]["value"]  # a corrected Reference moves the Metric: the system did not change


# --- the output ----------------------------------------------------------------------------------------------------------------


def test_the_human_line_names_the_earlier_assessment_and_the_cause(tmp_path):
    study, observation_set = imported(tmp_path)
    first = assessed(study, observation_set)
    revised(study, correct_d03, tmp_path, "corrected")
    code, out, err = run_cli("assess", "--study", study, "--observations", observation_set, "--scorer", SCORER, "--references", references_id(study))
    assert code == 0 and err == "" and out.count("\n") == 1
    assert first["assessment_id"] in out and "references_version" in out and "2 Criteria" in out


def test_with_json_stdout_holds_the_one_object_and_a_refusal_has_its_four_fields(tmp_path):
    study, observation_set = imported(tmp_path)
    assessed(study, observation_set)
    revised(study, correct_d03, tmp_path, "corrected")
    code, payload, err = assess_agent(study, observation_set, references_id(study))
    assert code == 0 and err == "" and set(payload) == {"ok", "assessment"} and payload["assessment"]["rescoring"]["changed_items"]
    code, payload, _ = assess_agent(study, observation_set, "nope")
    assert code == 2 and error_of(payload)["code"] == "REFERENCES_NOT_FOUND"
