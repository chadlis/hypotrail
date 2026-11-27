"""An Import Attempt written after the Study's first Exposure is marked `check_informed` (chadlis/hypotrail#294).

The mark says when the Import was written, not what its producer saw: the producer's exposure to `public_check` stays
`unknown`, and nothing is refused.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from _assess_helpers import assess, observation_set_id, references_id
from _chinook_helpers import FIXTURE, fixture_population, import_agent, init_chinook
from _exposure_helpers import assess_agent, compare_ids, correct_e01, edit_chinook_references, import_public, journal
from _import_helpers import import_ml, ready
from _revision_helpers import new_revision, spec_of
from _study_helpers import ROOT, init_study, run_json, run_ml

from hypotrail.core import canonical, contracts, exposure

MAE = "regression_mae_v1"
TRACES = ROOT / "docs" / "handbook" / "traces"
# sha256 of `EARLIER_EXPOSURE_STATEMENT` as UTF-8, as it stood before Imports were marked
STATEMENT_SHA256 = "9c3eb7634c9222134fdfe1f1cc6173807f8180f33126f1d66aded052934bbd20"


def ok(result) -> dict:
    code, payload, err = result
    assert code == 0, (payload, err)
    return payload


def status_of(study) -> dict:
    return ok(run_json("status", "--study", study))


def marked_ids(study) -> set:
    return {(mark["kind"], mark["id"]) for mark in status_of(study)["check_informed"]}


# --- each command: an Import, then the Study's first Exposure, then the same Import again --------------------------------------


def agent_study(tmp_path):
    study, _ = init_chinook(tmp_path, name="s2e-agent")
    population = fixture_population(tmp_path, name="s2e-population.json")
    again = lambda name: ok(import_agent(study, FIXTURE, population, name))["attempt"]  # noqa: E731
    expose = lambda: ok(assess_agent(study, import_public(tmp_path, study, "s2e-public")))  # noqa: E731
    return study, again, expose


def ml_study(tmp_path):
    study, _ = init_study(tmp_path, name="s2e-ml")
    source, mapping, population, _ = ready(tmp_path)
    again = lambda name: ok(import_ml(study, source, mapping, population, name))["attempt"]  # noqa: E731

    def expose():
        attempt = ok(run_ml(study, "seasonal_7", "public_check", "s2e-public"))["attempt"]
        ok(assess(study, observation_set_id(study, attempt), MAE, references_id(study)))

    return study, again, expose


COMMANDS = {"import agent": agent_study, "import ml": ml_study}


@pytest.mark.parametrize("command", list(COMMANDS))
def test_an_import_written_after_the_first_exposure_is_marked_and_the_same_import_written_before_is_not(tmp_path, command):
    study, again, expose = COMMANDS[command](tmp_path)
    before = again("s2e-before")
    assert "check_informed" not in before
    expose()
    after = again("s2e-after")
    assert after.get("check_informed") is True
    contracts.validate(after)
    assert ("attempt", after["attempt_id"]) in marked_ids(study) and ("attempt", before["attempt_id"]) not in marked_ids(study)


# --- what follows: the existing rule marks what uses a marked Import -----------------------------------------------------------


def test_an_assessment_and_a_comparison_that_use_a_marked_import_are_marked_and_an_unmarked_imports_assessment_is_not(tmp_path):
    study, again, expose = agent_study(tmp_path)
    unmarked = again("s2e-before")
    expose()
    marked = again("s2e-after")
    control = ok(assess_agent(study, unmarked))["assessment"]  # made after the Exposure, of an Import written before it
    candidate = ok(assess_agent(study, marked))["assessment"]
    comparison = ok(compare_ids(study, control["assessment_id"], candidate["assessment_id"]))["comparison"]
    assert "check_informed" not in control
    assert candidate.get("check_informed") is True and comparison.get("check_informed") is True
    listed = marked_ids(study)
    assert ("assessment", candidate["assessment_id"]) in listed and ("comparison", comparison["comparison_id"]) in listed
    assert ("assessment", control["assessment_id"]) not in listed


def test_a_marked_import_leaves_the_producers_earlier_exposure_unknown(tmp_path):
    study, again, expose = agent_study(tmp_path)
    expose()
    assert again("s2e-after").get("check_informed") is True
    exposures = status_of(study)["exposures"]
    assert exposures["earlier_exposure"] == "unknown" and exposures["statement"] == exposure.EARLIER_EXPOSURE_STATEMENT


# --- records written before: read and validated as stored ----------------------------------------------------------------------


def test_the_earlier_exposure_statement_is_byte_identical():
    assert hashlib.sha256(exposure.EARLIER_EXPOSURE_STATEMENT.encode("utf-8")).hexdigest() == STATEMENT_SHA256


def test_an_import_stored_without_the_mark_after_an_exposure_validates_and_is_read_as_stored(tmp_path):
    study, again, expose = agent_study(tmp_path)
    expose()
    attempt = again("s2e-stored")
    path = Path(study) / "attempts" / attempt["attempt_id"] / "attempt.json"
    stored = {key: value for key, value in json.loads(path.read_text(encoding="utf-8")).items() if key != "check_informed"}
    path.write_bytes(canonical.dumps(stored))  # as the Import was written before the mark existed
    contracts.validate(stored)
    assert ("attempt", attempt["attempt_id"]) not in marked_ids(study)


KEPT_MANIFESTS = sorted(TRACES.glob("*/study/attempts/*/attempt.json"))


@pytest.mark.parametrize("manifest", KEPT_MANIFESTS, ids=lambda p: p.relative_to(TRACES).parts[0] + "/" + p.parent.name[:8])
def test_each_kept_attempt_manifest_validates_as_stored(manifest):
    contracts.validate(json.loads(manifest.read_text(encoding="utf-8")))


@pytest.mark.parametrize("kept", sorted({p.parents[2] for p in KEPT_MANIFESTS}), ids=lambda p: p.parent.name)
def test_each_kept_study_lists_the_marks_it_stores(tmp_path, kept):
    copy = tmp_path / "s2e-kept"
    shutil.copytree(kept, copy)
    stored = [m for m in (json.loads(p.read_text(encoding="utf-8")) for p in sorted(copy.glob("attempts/*/attempt.json"))) if m.get("check_informed")]
    assert sum(mark["kind"] == "attempt" for mark in status_of(copy)["check_informed"]) == len(stored)


# --- across revisions: the Study's first Exposure counts (Tightened C) ---------------------------------------------------------


def test_an_import_into_revision_2_is_marked_when_the_only_exposure_was_in_revision_1(tmp_path):
    study, _ = init_chinook(tmp_path, name="s2e-revisions")
    ok(assess_agent(study, import_public(tmp_path, study, "s2e-public")))  # the Study's first Exposure, under revision 1
    corrected = edit_chinook_references(tmp_path, correct_e01, name="s2e-corrected")
    ok(new_revision(study, "--examples-dir", corrected))
    attempt = ok(import_agent(study, FIXTURE, fixture_population(tmp_path, name="s2e-population.json"), "s2e-rev2", "--examples-dir", corrected))["attempt"]
    assert spec_of(study)["revision_number"] == 2 and {entry["freeze_id"] for entry in journal(study)} == {exposure.freeze_records(study)[0]["freeze_id"]}
    assert attempt.get("check_informed") is True
