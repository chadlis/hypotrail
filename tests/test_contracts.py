"""Ticket #64: the repository's contract schema, the single validator of every record (Tightened A2)."""

import copy

import pytest

from hypotrail.core import contracts
from hypotrail.core.errors import EXIT_INTEGRITY_REFUSED, IntegrityError

DIGEST = "a" * 64
REF = {"path": "x/y.csv", "sha256": DIGEST, "size_bytes": 3, "media_type": "text/csv", "role": "r"}

# SPEC section 5, table "Contrats persistés": the fields of each record.
SPEC_FIELDS = {
    "StudySpec": "schema_version study_id revision question domain objective protocol_id protocol_digest dataset_refs primary_metric limitations",
    "AttemptManifest": "attempt_id request_id operation mode technical_status started_at finished_at effective_config input_refs code_environment outcome_unknown retry_of",
    "ObservationSet": "observation_set_id attempt_id domain origin mode population_ref raw_refs normalized_ref provenance unknown_fields",
    "Assessment": "assessment_id observation_set_id references_ref scorer counts per_item_ref metrics limitations",
    "Comparison": "left_assessment_id right_assessment_id comparability population_ref paired_deltas_ref coverage limitations",
}

# What the Tightened lines and acceptance criteria of #64 to #73 name, one entry each (A2).
TICKET_FIELDS = {
    "StudySpec": "workload artifacts check_informed",  # #64: the Workload by name and the Study artifacts, each with an ID; #73: a revision created after the first Exposure
    "AttemptManifest": "item_counts output_refs reason check_informed",  # #64 C; #65 B; #73
    "Assessment": "rescoring check_informed primary_criterion unknowns operational_errors detailed_metrics_ref",  # #70: the earlier Assessment, the cause, the changed Items; #73; #68 K2, CMP-04, G: the primary Criterion, the unknowns beside the rates, failed and missing Episodes apart, the secondary Criteria
    "Comparison": "roles declared_factor descriptive check_informed delta code_environment warnings secondary_deltas primary_criterion matrix_ref rates",  # #71 Control and Candidate, the delta, ID-03, the scope warning; #72 factor; CMP-06; #72 the matrix, the rates, the secondary deltas
    "FreezeRecord": "protocol_digest configuration_digests environment code",  # #73
    "ExposureEntry": "freeze_id attempt_ids assessment_ids comparison_ids",  # #73
}


def attempt(**changes):
    record = {
        "kind": "attempt",
        "schema_version": "attempt/1",
        "attempt_id": "3f0c1b3e-0000-4000-8000-000000000001",
        "request_id": "r1",
        "operation": "execute",
        "mode": "native_ml",
        "technical_status": "completed",
        "started_at": "2026-11-08T10:00:00+00:00",
        "finished_at": "2026-11-08T10:00:01+00:00",
        "effective_config": {},
        "effective_config_digest": DIGEST,
        "input_refs": [REF],
        "code_environment": {},
        "outcome_unknown": False,
        "retry_of": None,
        "item_counts": {"produced": 182, "failed": 0, "missing": 0},
        "output_refs": [REF],
    }
    record.update(changes)
    return record


def test_the_schema_is_a_valid_draft_2020_12_schema_and_the_validator_is_jsonschema():
    contracts.schema()  # check_schema runs when it loads


@pytest.mark.parametrize("record_name", sorted(SPEC_FIELDS))
def test_every_field_of_section_5_is_defined_and_required(record_name):
    definition = contracts.schema()["$defs"][record_name]
    for field in SPEC_FIELDS[record_name].split():
        assert field in definition["properties"], (record_name, field)
        assert field in definition["required"], (record_name, field)


@pytest.mark.parametrize("record_name", sorted(TICKET_FIELDS))
def test_every_field_a_9_ticket_requires_is_defined(record_name):
    definition = contracts.schema()["$defs"][record_name]
    for field in TICKET_FIELDS[record_name].split():
        assert field in definition["properties"], (record_name, field)


def test_the_criterion_states_and_counters_are_those_of_the_1_amendment():
    defs = contracts.schema()["$defs"]
    assert defs["Metric"]["properties"]["status"]["enum"] == ["scored", "unscored", "errored"]
    counters = set(defs["Counts"]["properties"])
    assert {"unscored", "errored"} <= counters
    assert not counters & {"unscorable", "scoring_error"}
    assert set(defs["Counts"]["required"]) == counters  # the kit's keys, renamed: expected attempted produced scored correct incorrect


def test_the_record_kinds_are_the_five_of_the_kit_plus_the_freeze_record_and_the_journal_entry():
    kinds = {definition["properties"]["kind"]["const"] for name, definition in contracts.schema()["$defs"].items() if "kind" in definition.get("properties", {})}
    assert kinds == {"study", "attempt", "observations", "assessment", "comparison", "freeze", "exposure", "decision", "declared_deviation"}  # #109, #155


def test_a_complete_terminal_attempt_manifest_is_valid():
    contracts.validate(attempt())


def test_a_terminal_manifest_has_finished_at_and_a_running_one_does_not():
    with pytest.raises(IntegrityError) as terminal:
        contracts.validate(attempt(finished_at=None))
    assert terminal.value.code == "CONTRACT_VIOLATION"
    running = attempt(technical_status="running", finished_at=None)
    del running["item_counts"], running["output_refs"]
    contracts.validate(running)
    with pytest.raises(IntegrityError):
        contracts.validate({**running, "finished_at": "2026-11-08T10:00:01+00:00"})


def test_a_completed_manifest_holds_the_counts_of_its_items_by_execution_status():
    record = attempt()
    del record["item_counts"]
    with pytest.raises(IntegrityError) as caught:
        contracts.validate(record)
    assert "item_counts" in caught.value.details["message"]
    bad = attempt(item_counts={"produced": 1, "failed": 0, "missing": 0, "scored": 1})
    with pytest.raises(IntegrityError):
        contracts.validate(bad)


def test_an_unknown_field_a_wrong_enum_or_an_unknown_kind_is_refused_with_a_code_and_the_path():
    for record in (
        attempt(extra=1),
        attempt(mode="llm"),
        attempt(attempt_id=""),
        attempt(input_refs=[{**REF, "sha256": "xyz"}]),
        {"kind": "nothing"},
    ):
        with pytest.raises(IntegrityError) as caught:
            contracts.validate(record)
        assert caught.value.code == "CONTRACT_VIOLATION"
        assert caught.value.exit_code == EXIT_INTEGRITY_REFUSED
        assert {"kind", "path", "message"} <= set(caught.value.details)


def test_validation_does_not_change_the_record():
    record = attempt()
    before = copy.deepcopy(record)
    contracts.validate(record)
    assert record == before


# The property names and `required` lists of five record definitions, written from the schema at `7db697f`, and of the `decision/2` definition added after it:
# "The Decision, Assessment and Comparison records, the write journal and the contract schema stay as they are" (chadlis/hypotrail#159, "Out of scope").
RECORD_DEFINITIONS_AT_7DB697F = {
    "Assessment": (
        "assessment_id check_informed counts detailed_metrics_ref kind limitations metrics observation_set_id operational_errors per_item_ref primary_criterion "
        "recorded_at references_ref rescoring schema_version scorer single_feature_check study_revision unknowns",
        "kind schema_version assessment_id observation_set_id references_ref scorer counts per_item_ref metrics limitations",
    ),
    "Comparison": (
        "check_informed code_environment comparability comparison_id coverage declared_factor delta descriptive kind left_assessment_id limitations matrix_ref "
        "paired_deltas_ref population_ref primary_criterion rates right_assessment_id roles schema_version secondary_deltas warnings",
        "kind schema_version comparison_id left_assessment_id right_assessment_id comparability population_ref paired_deltas_ref coverage limitations",
    ),
    "DecisionRecord": (
        "author cited_ids decision_id kind option question read_sequence request_id revision schema_version source write_sequence",
        "kind schema_version decision_id request_id question option author source cited_ids revision read_sequence write_sequence",
    ),
    "DecisionRecordV2": (
        "author cited_ids decision_id kind option option_id question question_id read_sequence request_id revision schema_version source words write_sequence",
        "kind schema_version decision_id request_id question option author source cited_ids revision read_sequence write_sequence question_id option_id words",
    ),
    "WriteJournalBegin": ("command phase request_id", "phase command request_id"),
    "WriteJournalEnd": ("command outcome phase request_id written", "phase command request_id outcome written"),
}


@pytest.mark.parametrize("name", list(RECORD_DEFINITIONS_AT_7DB697F))
def test_the_assessment_comparison_decision_and_write_journal_definitions_keep_their_properties_and_required_lists(name):
    definition = contracts.schema()["$defs"][name]
    properties, required = RECORD_DEFINITIONS_AT_7DB697F[name]
    assert sorted(definition["properties"]) == properties.split()
    assert definition["required"] == required.split()
