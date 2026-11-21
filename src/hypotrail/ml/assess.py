"""`assess` for the temporal regression Track: one registered Scorer, one kept Observation set, one References set.

Assessing fits nothing, predicts nothing and calls no model or tool: it reads the Observation set and
the References set the Study keeps and writes a new Assessment. This module imports neither
scikit-learn nor NumPy, and not `hypotrail.ml.run` either.

The order is fixed, and nothing is written before the checks that precede it:

1. the Scorer is looked up in the closed registry (`SCORER_NOT_REGISTERED`, exit 2);
2. the Observation set and the References set are found in the Study (exit 2) and the Scorer must
   belong to the Observation set's domain (`UNSUPPORTED_CAPABILITY`, exit 2);
3. every artifact read (Observation set record, normalized outputs, raw predictions, population,
   References) is read back against its digest (`ARTIFACT_INTEGRITY`, exit 3);
4. the Partition of the Items is `dev` or `public_check` (`ASSESSMENT_PARTITION_NOT_DEV` otherwise). An Assessment of
   `public_check` Items is an Exposure: once the structure of the Observation set has passed, and before any Item is
   scored, the Study's freeze record is written if the revision has none and one journal entry is appended
   (`hypotrail.core.exposure`; `PROTOCOL_CHANGED`, exit 3, when the Workload's Protocol is no longer the revision's);
5. every expected Item gets its Criterion (the absolute error of the day) in a state; the Metric is
   aggregated from the scored ones;
6. `per_item.csv` is published, then `assessment.json` last. Another Assessment of the same
   Observation set never changes an earlier one: a new `assessment_id` each time.
7. the record names the revision whose Protocol it applied (`study_revision`) and, when an earlier Assessment of the
   same Observation set and Scorer differs by its References or its Scorer, that Assessment, the cause and the
   Items whose verdict changed (`rescoring`, `hypotrail.core.rescoring`).
"""

import csv
import io
import math
import datetime
import uuid
from pathlib import Path

from hypotrail.core import artifacts, canonical, contracts, exposure, lock, rescoring, revisions, scorers, write_journal
from hypotrail.core import study as layout
from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.partitions import requires_exposure
from hypotrail.ml.study import live_basis as _live_basis

COMMAND = "assess"
STAGE = "assess"
PER_ITEM_COLUMNS = ["row_id", "execution_status", "criterion", "state", "value", "reason"]
LIMITATIONS = [
    "Daily observations are dependent: the Metric carries no confidence interval and no significance claim.",
]

REASON_FAILED = "item_failed"
REASON_MISSING = "item_missing"
REASON_REFERENCE_MISSING = "reference_missing"
REASON_REFERENCE_INVALID = "reference_invalid"
REASON_PREDICTION_INVALID = "prediction_invalid"
REASON_SCORING_FAILED = "scoring_failed"
REASON_NO_SCORED_ITEM = "no_scored_item"


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage=STAGE, details=details)


def _rows(data: bytes) -> list:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"), newline="")))


def _finite(cell):
    """The finite float a cell holds, or None."""
    try:
        value = float(cell)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def criterion(execution_status, prediction_cell, reference_cell):
    """(state, value, reason) of the absolute error of one Item."""
    if execution_status == "failed":
        return "unscored", None, REASON_FAILED
    if execution_status == "missing":
        return "unscored", None, REASON_MISSING
    if reference_cell is None:
        return "unscored", None, REASON_REFERENCE_MISSING
    reference = _finite(reference_cell)
    if reference is None:
        return "unscored", None, REASON_REFERENCE_INVALID
    prediction = _finite(prediction_cell)
    if prediction is None:
        return "unscored", None, REASON_PREDICTION_INVALID
    error = abs(prediction - reference)
    if not math.isfinite(error):  # finite cells whose difference overflows: the machinery broke
        return "errored", None, REASON_SCORING_FAILED
    return "scored", error, None


def _metric(scorer, scored_values, unit):
    base = {"id": scorer.metric_id, "unit": unit, "direction": "lower_is_better", "denominator": len(scored_values)}
    if not scored_values:
        return {**base, "value": None, "status": "unscored", "reason": REASON_NO_SCORED_ITEM}
    try:
        value = scorer.aggregate(scored_values)
    except OverflowError:
        value = math.inf
    if not math.isfinite(value):
        return {**base, "value": None, "status": "errored", "reason": REASON_SCORING_FAILED}
    return {**base, "value": value, "status": "scored", "reason": None}


def _per_item_csv(entries) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(PER_ITEM_COLUMNS)
    for row_id, execution_status, state, value, reason in entries:
        writer.writerow([row_id, execution_status, scorers.ABSOLUTE_ERROR, state, "" if value is None else repr(value), reason or ""])
    return out.getvalue().encode("utf-8")


def assess(study: Path, observation_set_id: str, scorer_id: str, references_id: str, *, examples_dir: Path | None = None, read_sequence: int | None = None) -> dict:
    """Write and return a new Assessment of the Observation set by the Scorer, against the References set.

    Holds the Study's writer lock for the whole command: a second writer is refused at once. `examples_dir` is
    read only for an Assessment of `public_check` Items, to freeze the Workload's digests (default: the repository's).
    """
    study = Path(study)
    write_journal.require_valid_read_sequence(read_sequence, "assess")
    layout.read_spec(study)  # a folder that is no Study is refused before a lock file is created in it
    with lock.writer_lock(study), write_journal.writing(study, "assess"):
        write_journal.require_current(study, read_sequence)
        return _assess_locked(study, observation_set_id, scorer_id, references_id, examples_dir)


def _assess_locked(study: Path, observation_set_id: str, scorer_id: str, references_id: str, examples_dir) -> dict:
    spec = layout.read_spec(study)
    scorer = scorers.get(scorer_id)

    found = layout.find_observation_set(study, observation_set_id)
    if found is None:
        raise _refuse(
            "OBSERVATION_SET_NOT_FOUND",
            f"the Study keeps no Observation set {observation_set_id!r}",
            observation_set_id=str(observation_set_id),
        )
    observation_set, manifest = found
    references = next((e["ref"] for e in spec["artifacts"] if e["artifact_id"] == references_id and e["ref"]["role"] == "references"), None)
    if references is None:
        raise _refuse(
            "REFERENCES_NOT_FOUND",
            f"the Study keeps no References set {references_id!r}",
            references_id=str(references_id),
            available=sorted(e["artifact_id"] for e in spec["artifacts"] if e["ref"]["role"] == "references"),
        )
    if observation_set["domain"] != scorer.domain:
        raise _refuse(
            "UNSUPPORTED_CAPABILITY",
            f"Scorer {scorer.id} scores the {scorer.domain!r} Track, not an Observation set of the {observation_set['domain']!r} Track",
            scorer=scorer.id,
            scorer_domain=scorer.domain,
            observation_set_domain=observation_set["domain"],
        )

    for ref in observation_set["raw_refs"]:
        artifacts.read_verified(study, ref)  # the predictions the Observation set was normalized from
    normalized = artifacts.read_verified(study, observation_set["normalized_ref"])
    references_bytes = artifacts.read_verified(study, references)

    partition = observation_set["provenance"].get("partition")
    if partition is None:
        raise _refuse("OBSERVATIONS_INVALID", "the Observation set names no Partition", problem="unknown_partition", row_id=None)
    exposed = requires_exposure(partition, not_dev_code="ASSESSMENT_PARTITION_NOT_DEV", what="an Assessment", stage=STAGE)

    expected = layout.expected_row_ids(study, observation_set["population_ref"], partition)
    observed = {}
    for row in _rows(normalized):
        row_id = row["row_id"]
        if row_id in observed:
            raise _refuse("OBSERVATIONS_INVALID", f"{row_id} appears twice in the Observation set", problem="duplicate_item", row_id=row_id)
        if row["status"] not in ("produced", "failed", "missing"):
            raise _refuse("OBSERVATIONS_INVALID", f"{row_id} has the execution status {row['status']!r}", problem="bad_status", row_id=row_id)
        observed[row_id] = row
    stray = sorted(set(observed) - set(expected))
    if stray:
        raise _refuse("OBSERVATIONS_INVALID", f"{stray[0]} is not an Item of {partition}", problem="unexpected_item", row_id=stray[0])
    assessment_id = str(uuid.uuid4())
    if exposed:  # before any Item is scored
        exposure.record(study, spec, _live_basis(examples_dir), attempt_ids=[manifest["attempt_id"]], assessment_ids=[assessment_id])
    reference_cells = {row["row_id"]: row["y_true"] for row in _rows(references_bytes)}

    entries = []
    for row_id in expected:  # a fixed order, whatever the file order
        row = observed.get(row_id)
        status = row["status"] if row is not None else "missing"  # absent from the outputs
        state, value, reason = criterion(status, row["y_pred"] if row is not None else None, reference_cells.get(row_id))
        entries.append((row_id, status, state, value, reason))

    by_status = [e[1] for e in entries]
    by_state = [e[2] for e in entries]
    counts = {
        "expected": len(entries),
        "attempted": by_status.count("produced") + by_status.count("failed"),
        "produced": by_status.count("produced"),
        "scored": by_state.count("scored"),
        "correct": None,  # an absolute error is not a binary verdict
        "incorrect": None,
        "unscored": by_state.count("unscored"),
        "errored": by_state.count("errored"),
    }
    metric = _metric(scorer, [e[3] for e in entries if e[2] == "scored"], spec["primary_metric"]["unit"])

    folder = f"{layout.ASSESSMENTS_DIR}/{assessment_id}"
    per_item = _per_item_csv(entries)
    per_item_ref = {
        "path": f"{folder}/per_item.csv",
        "sha256": canonical.sha256_hex(per_item),
        "size_bytes": len(per_item),
        "media_type": "text/csv",
        "role": "per_item",
    }
    record = {
        "kind": "assessment",
        "schema_version": "assessment/1",
        "assessment_id": assessment_id,
        "observation_set_id": observation_set["observation_set_id"],
        "references_ref": references,
        "scorer": {"id": scorer.id, "version": scorer.version, "config_digest": scorer.config_digest},
        "counts": counts,
        "per_item_ref": per_item_ref,
        "metrics": [metric],
        "limitations": list(LIMITATIONS),
        "study_revision": revisions.identity(spec),
        **exposure.marks(study, [manifest]),
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rescoring": rescoring.describe(
            study,
            observation_set_id=observation_set["observation_set_id"],
            scorer={"id": scorer.id, "version": scorer.version, "config_digest": scorer.config_digest},
            references_ref=references,
            per_item=per_item,
        ),
    }
    contracts.validate(record)
    write_journal.begin()  # a dev Assessment writes nothing before this; an Exposure began the command already
    artifacts.publish_bytes(study, per_item_ref["path"], per_item, media_type="text/csv", role="per_item")
    write_journal.wrote("assessment", assessment_id)
    artifacts.publish_record(study, f"{folder}/assessment.json", record, role="assessment")
    return record
