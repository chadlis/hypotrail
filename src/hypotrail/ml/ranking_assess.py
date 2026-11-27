"""Assess one frozen development ranking without fitting or calling a model."""

import csv
import io
import math
import uuid
from collections import defaultdict
from decimal import Decimal
from fractions import Fraction

from hypotrail.core import artifacts, canonical, contracts, exposure, rescoring, revisions, study_write
from hypotrail.core import study as layout
from hypotrail.core.attempts import now
from hypotrail.core.errors import InvalidInputError
from hypotrail.ml import ranking_study

COLUMNS = ("item_id", "entity_id", "as_of", "score", "label")


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="assess", details=details)


def _rows(raw):
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"), newline="")))


def _entries(study, observed, memberships, references):
    raw = artifacts.read_verified(study, observed["normalized_ref"])
    population = canonical.loads(artifacts.read_verified(study, observed["population_ref"]))["item_ids"]
    labels = {row["item_id"]: row["label"] for row in _rows(artifacts.read_verified(study, references))}
    scores = {row["item_id"]: row["score"] for row in _rows(raw)}
    if set(population) != set(scores) or not set(population) <= (labels.keys() & memberships.keys()):
        raise _refuse("OBSERVATIONS_INVALID", "the ranking Observation set does not align with the development Items and their References")
    return [
        (
            item_id,
            memberships[item_id]["entity_id"],
            memberships[item_id]["as_of"],
            scores[item_id],
            labels[item_id],
        )
        for item_id in sorted(population)
    ]


def _measure(entries, fraction):
    by_date = defaultdict(list)
    for item_id, _, as_of, score, label in entries:
        by_date[as_of].append((item_id, Decimal(score), int(label)))
    recalls = []
    scored_items = 0
    for day in by_date.values():
        positives = sum(row[2] for row in day)
        if positives:
            ordered = sorted(day, key=lambda row: row[1], reverse=True)  # stable, with incoming Items ordered by ID
            k = math.ceil(fraction * len(ordered))
            recalls.append(Fraction(sum(row[2] for row in ordered[:k]), positives))
            scored_items += len(day)
    return recalls, len(by_date) - len(recalls), scored_items


def assess_locked(study, write, spec, observation_set_id, scorer, references_id):
    found = layout.find_observation_set(study, observation_set_id)
    if found is None:
        raise _refuse("OBSERVATION_SET_NOT_FOUND", "the Study does not keep that Observation set", observation_set_id=str(observation_set_id))
    observation_set, manifest = found
    references = next((entry["ref"] for entry in spec["artifacts"] if entry["artifact_id"] == references_id and entry["ref"]["role"] == "references"), None)
    if references is None:
        raise _refuse("REFERENCES_NOT_FOUND", "the current revision does not keep that References set", references_id=str(references_id))
    if observation_set["domain"] != scorer.domain:
        raise _refuse(
            "UNSUPPORTED_CAPABILITY", "the Scorer does not match the ranking Observation set",
            scorer=scorer.id, scorer_domain=scorer.domain, observation_set_domain=observation_set["domain"],
        )
    if observation_set["provenance"].get("partition") != ranking_study.DEV:
        raise _refuse("ASSESSMENT_PARTITION_NOT_DEV", "the ranking Study assesses only its development Partition")

    for ref in observation_set["raw_refs"]:
        artifacts.read_verified(study, ref)
    _, memberships = ranking_study.read_dataset(study, spec)
    entries = _entries(study, observation_set, memberships, references)
    recalls, omitted, scored_items = _measure(entries, Fraction(scorer.config["fraction"]))
    value = float(sum(recalls) / len(recalls)) if recalls else None
    metric = {
        "id": scorer.metric_id,
        "value": value,
        "unit": "proportion",
        "direction": "higher_is_better",
        "denominator": len(recalls),
        "status": "unscored" if value is None else "scored",
        "reason": "no_dates_with_positives" if value is None else None,
    }
    assess_id = str(uuid.uuid4())
    folder = f"{layout.ASSESSMENTS_DIR}/{assess_id}"
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(entries)
    per_item = out.getvalue().encode("utf-8")
    per_item_ref = {
        "path": f"{folder}/per_item.csv",
        "sha256": canonical.sha256_hex(per_item),
        "size_bytes": len(per_item),
        "media_type": "text/csv",
        "role": "per_item",
    }
    scorer_record = {"id": scorer.id, "version": scorer.version, "config_digest": scorer.config_digest}
    record = {
        "kind": "assessment",
        "schema_version": "assessment/1",
        "assessment_id": assess_id,
        "observation_set_id": observation_set["observation_set_id"],
        "references_ref": references,
        "scorer": scorer_record,
        "counts": {
            "expected": len(entries),
            "attempted": len(entries),
            "produced": len(entries),
            "scored": scored_items,
            "correct": None,
            "incorrect": None,
            "unscored": len(entries) - scored_items,
            "errored": 0,
        },
        "metrics": [metric],
        "ranking_dates": {"scored": len(recalls), "omitted_no_positives": omitted},
        "per_item_ref": per_item_ref,
        "limitations": list(spec["limitations"]),
        "study_revision": revisions.identity(spec),
        **exposure.marks(study, [manifest]),
        "recorded_at": now(),
        "rescoring": rescoring.describe(
            study,
            observation_set_id=observation_set["observation_set_id"],
            scorer=scorer_record,
            references_ref=references,
            per_item=per_item,
        ),
    }
    contracts.validate(record)
    write.begin()
    artifacts.publish_bytes(study, per_item_ref["path"], per_item, media_type="text/csv", role="per_item")
    write.wrote(study_write.ASSESSMENT, assess_id)
    artifacts.publish_record(study, f"{folder}/assessment.json", record, role="assessment")
    return record
