"""The core Study writer and public reads for ranking Comparisons (D-233)."""

import copy
import uuid
from types import SimpleNamespace

import pytest

from hypotrail import cli
from hypotrail.core import artifacts, comparison, contracts, figures, write_journal
from hypotrail.core.errors import IntegrityError, InvalidInputError
from hypotrail.report import command as report, gather, markup


FIRST = "2025-01-01"
SECOND = "2025-02-01"
METRIC = "recall_at_top_fraction"


def _ranking_side(role, first, second, value):
    return {
        "role": role,
        "assessment": {
            "assessment_id": str(uuid.uuid4()),
            "references_ref": {"sha256": "1" * 64},
            "scorer": {"id": "ranking_recall_at_top_v1", "version": "1", "config_digest": "0" * 64},
        },
        "manifest": {"attempt_id": str(uuid.uuid4()), "mode": "external_unknown", "code_environment": {}, "effective_config": {}},
        "observation_set": {"mode": "external_unknown", "domain": "ranking"},
        "partition": "dev",
        "population_sha256": "01234567" * 8,
        "expected_items": [f"a@{FIRST}", f"b@{FIRST}", f"b@{SECOND}"],
        "per_item": [
            {"item_id": f"a@{FIRST}", "entity_id": "a", "as_of": FIRST, "label": "1", "score": first},
            {"item_id": f"b@{FIRST}", "entity_id": "b", "as_of": FIRST, "label": "0", "score": second},
            {"item_id": f"b@{SECOND}", "entity_id": "b", "as_of": SECOND, "label": "0", "score": "0"},
        ],
        "metric": {"id": METRIC, "unit": "proportion", "value": value, "direction": "higher_is_better"},
    }


@pytest.fixture
def sides(monkeypatch):
    data = {
        "control": _ranking_side("control", "0", "1", 0.0),
        "candidate": _ranking_side("candidate", "1", "0", 1.0),
    }
    monkeypatch.setattr(comparison.layout, "read_spec", lambda _: {"domain": "ranking", "artifacts": []})
    monkeypatch.setattr(comparison, "_side", lambda _, role, _id, **__: copy.deepcopy(data[role]))
    return data


def test_ranking_comparison_records_the_paired_entity_interval_and_counts(tmp_path, sides):
    record = comparison.compare(tmp_path, "control", "candidate")
    contracts.validate(record)
    assert record["comparability"]["status"] == "descriptive_only"
    assert record["delta"]["metric"] == METRIC
    assert record["delta"]["value"] == 1.0
    assert "Candidate is better" in record["delta"]["definition"]
    assert record["coverage"] == {"expected": 3, "control_scored": 3, "candidate_scored": 3, "paired": 3}
    assert record["paired_deltas_ref"] is None
    interval = record["interval"]
    assert (interval["unit"], interval["units"], interval["resamples"], interval["level"]) == ("entity", 2, 2000, 0.95)
    assert (interval["lower"], interval["upper"]) == (0.0, 1.0)
    assert 0 < interval["usable_resamples"] < 2000
    assert interval["omitted_dates"] == 2000 + 2000 - interval["usable_resamples"]
    read = comparison.layout.read_record(tmp_path, f"comparisons/{record['comparison_id']}/comparison.json")
    assert read == record
    assert write_journal.write_sequence(tmp_path) == 2


def test_ranking_comparison_rejects_an_item_on_only_one_side_before_writing(tmp_path, sides):
    sides["candidate"]["per_item"].pop()
    with pytest.raises(IntegrityError) as error:
        comparison.compare(tmp_path, "control", "candidate")
    assert error.value.code == "COMPARISON_ITEMS_DIFFER"
    assert not (tmp_path / "comparisons").exists()


def test_ranking_comparison_rejects_an_item_missing_from_both_sides(tmp_path, sides):
    for side in sides.values():
        side["per_item"].pop()
    with pytest.raises(IntegrityError) as error:
        comparison.compare(tmp_path, "control", "candidate")
    assert error.value.code == "COMPARISON_ITEMS_DIFFER"
    assert write_journal.write_sequence(tmp_path) == 0


def test_ranking_comparison_rejects_a_different_reference_label_for_a_paired_item(tmp_path, sides):
    sides["candidate"]["per_item"][0]["label"] = "0"
    with pytest.raises(IntegrityError) as error:
        comparison.compare(tmp_path, "control", "candidate")
    assert error.value.code == "COMPARISON_ITEMS_DIFFER"
    assert not (tmp_path / "comparisons").exists()


def test_ranking_comparison_publishes_counts_when_all_draws_are_undefined(tmp_path, sides):
    for side in sides.values():
        side["metric"].update(value=None, reason="no_positive_dates")
        for item in side["per_item"]:
            item["label"] = "0"
    record = comparison.compare(tmp_path, "control", "candidate")
    assert record["delta"]["value"] is None
    assert record["delta"]["reason"] == "no_positive_dates"
    interval = record["interval"]
    assert (interval["lower"], interval["upper"], interval["reason"]) == (None, None, "no_usable_resamples")
    assert (interval["usable_resamples"], interval["omitted_dates"]) == (0, 4000)
    assert "0/2000 usable draws, 4000 date omissions" in markup.interval(record)


@pytest.mark.parametrize(("observed", "declared"), [("held_out", "dev"), ("dev", "held_out"), ("dev", None), (None, "dev")])
def test_ranking_requires_dev_in_both_records_before_reading_its_artifact(tmp_path, monkeypatch, observed, declared):
    monkeypatch.setattr(comparison.layout, "find_assessment", lambda *args: {"observation_set_id": "protected", "per_item_ref": {}})
    provenance = {"partition": observed} if observed is not None else {}
    effective_config = {"partition": declared} if declared is not None else {}
    monkeypatch.setattr(
        comparison.layout, "find_observation_set",
        lambda *args: ({"domain": "ranking", "provenance": provenance}, {"effective_config": effective_config}),
    )

    def unread(*_):
        pytest.fail("The protected ranking artifact was read")

    monkeypatch.setattr(artifacts, "read_verified", unread)
    with pytest.raises(InvalidInputError) as error:
        comparison._side(tmp_path, "control", "synthetic")
    assert error.value.code == "COMPARISON_PARTITION_NOT_DEV"


def test_cli_and_interval_read_show_the_ranking_direction_and_omission_counts(tmp_path, sides, capsys):
    args = SimpleNamespace(study=tmp_path, control="control", candidate="candidate", factor=None, examples_dir=None, read_sequence=None, json=False)
    assert cli._compare(args) == 0
    line = capsys.readouterr().out
    assert "positive means the Candidate is better" in line
    assert "over 2 entities" in line
    assert "usable draws" in line and "date omissions" in line
    record = comparison.layout.comparison_records(tmp_path)[0]
    assert "usable draws" in markup.interval(record)
    assert "date omissions" in markup.interval(record)
    assert figures.entry(tmp_path, record)["unavailable"] == "no_item_level_ranking_delta"


def test_report_publishes_ranking_aggregates_without_opening_references_or_item_scores(tmp_path, sides, monkeypatch):
    study = tmp_path / "study"
    study.mkdir()
    record = comparison.compare(study, "control", "candidate")
    memberships = artifacts.publish_bytes(
        study, "artifacts/memberships.csv", b"item_id,entity_id,as_of,partition\na@2025-01-01,a,2025-01-01,dev\n",
        media_type="text/csv", role="memberships",
    )
    spec = {
        "domain": "ranking", "workload": "synthetic", "study_id": "synthetic", "question": "Rank synthetic entities?",
        "objective": "Measure recall", "primary_metric": sides["control"]["metric"], "protocol_id": "synthetic:protocol",
        "protocol_digest": "0" * 64, "revision": "0" * 64, "revision_number": 1, "dataset_refs": [], "limitations": [],
        "artifacts": [{"artifact_id": "membership", "ref": memberships},
                      {"artifact_id": "references", "ref": {"role": "references", "path": "no-reference-file.csv"}}],
    }
    monkeypatch.setattr(gather.layout, "read_spec", lambda _: spec)
    attempts, assessments = [], []
    for role, side in sides.items():
        attempts.append({
            "manifest": {**side["manifest"], "started_at": f"2025-01-0{1 if role == 'control' else 2}", "technical_status": "succeeded",
                         "request_id": role, "outcome_unknown": False, "item_counts": {"produced": 1, "missing": 0, "failed": 0}},
            "observation_set": {"observation_set_id": role}, "partition": "dev", "licence_notice": None,
        })
        assessments.append({
            **side["assessment"], "observation_set_id": role, "limitations": [], "metrics": [dict(side["metric"], denominator=1, status="scored")],
            "counts": dict.fromkeys(("expected", "attempted", "produced", "scored", "unscored", "errored", "correct", "incorrect"), 1),
            "per_item_ref": {"role": "per_item", "path": "no-item-file.csv"},
        })
    monkeypatch.setattr(gather, "attempts_of", lambda *_, **__: attempts)
    monkeypatch.setattr(gather.layout, "assessment_records", lambda _: assessments)
    page = tmp_path / "report.html"
    report.report(study, page)
    content = page.read_text()
    assert record["comparison_id"] in content
    assert "usable draws" in content and "date omissions" in content
    assert "A positive delta means the Candidate has higher recall" in content
    assert "Individual errors" not in content and "no-item-file.csv" not in content and "no-reference-file.csv" not in content


@pytest.mark.parametrize(
    ("observed", "declared"), [("held_out", "dev"), ("dev", "held_out"), ("dev", None), (None, "dev"), (None, "held_out")],
)
def test_report_requires_dev_in_both_records_before_reading_any_payload(tmp_path, monkeypatch, observed, declared):
    monkeypatch.setattr(gather.layout, "attempt_ids", lambda _: ["synthetic"])
    effective_config = {"partition": declared} if declared is not None else {}
    monkeypatch.setattr(gather.layout, "read_manifest", lambda *args: {
        "effective_config": effective_config, "input_refs": [{"role": "workload_declaration"}],
    })
    monkeypatch.setattr(
        gather, "observation_set_of", lambda *_: {"provenance": {"partition": observed}} if observed is not None else None,
    )

    def unread(*_):
        pytest.fail("The protected ranking artifact was read")

    monkeypatch.setattr(gather.Reader, "bytes_of", unread)
    with pytest.raises(InvalidInputError) as error:
        gather.attempts_of(tmp_path, gather.Reader(tmp_path), ranking=True)
    assert error.value.code == "REPORT_SCOPE_UNVERIFIED"
