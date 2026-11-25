"""`assess` for the tool-using agent Track: `chinook_contract_v1` applied to one kept Observation set.

Assessing runs no model and no tool, opens no database and reads no Workload file: the frozen
References, the answer schema and the Observation set the Study keeps are enough (RES-01, T10). This
module imports neither Inspect, scikit-learn nor NumPy, and neither the runner nor the log projection.
The one scoring function stays in `hypotrail.core.chinook_contract` (ADR 0001); the Criteria of an
Episode without an answer come from `hypotrail.agentic.unproduced`, the same rule that rescores a
kept log.

The order is fixed, and nothing is written before the checks that precede it:

1. the Observation set and the References set are found in the Study, and the Scorer must belong to
   the Observation set's domain (`UNSUPPORTED_CAPABILITY`, exit 2);
2. every artifact read (raw answers, normalized Observations, population, References, answer
   schema) is read back against its digest (`ARTIFACT_INTEGRITY`, exit 3);
3. the Partition of the Episodes is `dev` or `public_check` (`ASSESSMENT_PARTITION_NOT_DEV` otherwise). An Assessment of
   `public_check` Episodes is an Exposure: once the structure of the Observation set has passed, and before any
   Episode is scored, the Study's freeze record is written if the revision has none and one journal entry is
   appended (`hypotrail.core.exposure`; `PROTOCOL_CHANGED`, exit 3, when the Workload's Protocol is no longer the revision's);
4. every expected Episode gets a state for each of the four Criteria, with a Reason for every
   non-score: an answer is scored (a `final_answer` object as its canonical JSON text), a `failed`
   Episode is `unscored` with `execution_failed`, a `missing` one with `observation_missing`;
5. the counters of each Criterion are counted from those states (CMP-03) and the two named rates
   follow (CMP-04); the primary Criterion, declared by the Workload and frozen as the Study's primary
   metric (owner decision 1A on chadlis/hypotrail#9), is the envelope's, the others are kept apart;
6. `per_item.csv` and `metrics.json` are published, then `assessment.json` last. Another Assessment
   of the same Observation set never changes an earlier one: a new `assessment_id` each time.
7. the record names the revision whose Protocol it applied (`study_revision`) and, when an earlier Assessment of the
   same Observation set and Scorer differs by its References or its Scorer, that Assessment, the cause and the
   Items whose verdict changed (`rescoring`, `hypotrail.core.rescoring`).
"""

import csv
import io
import json
import uuid
from collections import Counter
from pathlib import Path

from hypotrail.agentic.counts import counters
from hypotrail.agentic.unproduced import criteria_of_unproduced
from hypotrail.core import artifacts, canonical, contracts, exposure, rescoring, revisions, scorers, study_write
from hypotrail.core import study as layout
from hypotrail.core.attempts import now
from hypotrail.core.chinook_contract import CRITERIA, apply_scorer, score_episode
from hypotrail.core.errors import InvalidInputError
from hypotrail.agentic.study import live_basis as _live_basis
from hypotrail.agentic.partitions import requires_exposure

STAGE = "assess"
SCENARIO_MODE = "scripted_fixture"
PER_ITEM_COLUMNS = ["case_id", "repeat", "execution_status", "answer_given_as", "answer_read_from", "criterion", "state", "score", "reason"]
RATE_UNIT = "share of Episodes"
QUALITY = "quality_among_scored"
CONFIRMED_SHARE = "confirmed_share_of_expected"
REASON_NO_SCORED = "no_scored_episode"
REASON_NO_EXPECTED = "no_expected_episode"
LIMITATIONS = [
    "The Repeats of a Case are not independent samples: the shares carry no confidence interval and no significance claim.",
    "evidence_link_valid checks that the IDs an answer cites designate successful calls of its own trace; it does not prove that every claim follows from the trace.",
    "The shares describe the Cases of this Workload, not agents in general.",
]


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage=STAGE, details=details)


def _lines(data: bytes) -> list:
    return [canonical.loads(text) for text in data.decode("utf-8").splitlines() if text.strip()]


def _expected(population: bytes) -> list:
    document = canonical.loads(population)
    return sorted((e["case_id"], e["repeat"]) for e in document["episodes"])


def _counts(verdicts: list, name: str) -> dict:
    """The counters of one Criterion under the contract schema's keys (`N_x` is the key `x`)."""
    return {key[2:]: value for key, value in counters(verdicts, name).items()}


def _rate(rate_id: str, numerator, denominator: int, empty_reason: str) -> dict:
    base = {"id": rate_id, "unit": RATE_UNIT, "direction": "higher_is_better", "denominator": denominator}
    if denominator == 0:
        return {**base, "value": None, "status": "unscored", "reason": empty_reason}
    return {**base, "value": numerator / denominator, "status": "scored", "reason": None}


def _rates(counts: dict) -> list:
    """The two named rates of CMP-04; a zero denominator is a null with its Reason, never 0."""
    return [
        _rate(QUALITY, counts["correct"], counts["scored"], REASON_NO_SCORED),
        _rate(CONFIRMED_SHARE, counts["correct"], counts["expected"], REASON_NO_EXPECTED),
    ]


def _verdict(entry, key, references, schema) -> dict:
    case_id, repeat = key
    status = entry["status"] if entry is not None else "missing"  # absent from the outputs
    if status == "produced" and entry["answer_given_as"] is not None:
        text = entry["raw_answer"] if entry["answer_given_as"] == "raw_answer" else canonical.dumps(entry["final_answer"]).decode("utf-8")
        result = apply_scorer(score_episode, text, references.get(case_id), schema, entry["trace"])
        return {
            "case_id": case_id,
            "repeat": repeat,
            "status": status,
            "answer_given_as": entry["answer_given_as"],
            "answer_read_from": result.get("answer_read_from"),
            "criteria": result["criteria"],
        }
    return {
        "case_id": case_id,
        "repeat": repeat,
        "status": status,
        "answer_given_as": None,
        "answer_read_from": None,
        # the Reason an import kept for the Episode (a limit, the output cap), the same rule as the rescoring of a log
        "criteria": criteria_of_unproduced({"status": status, "reason": entry.get("reason") if entry is not None else None}),
    }


def _per_item_csv(verdicts: list) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(PER_ITEM_COLUMNS)
    for verdict in verdicts:
        for criterion in verdict["criteria"]:
            score = "" if criterion["score"] is None else ("true" if criterion["score"] else "false")
            writer.writerow(
                [
                    verdict["case_id"], verdict["repeat"], verdict["status"], verdict["answer_given_as"] or "", verdict["answer_read_from"] or "",
                    criterion["name"], criterion["state"], score, criterion["reason"] or "",
                ]
            )
    return out.getvalue().encode("utf-8")


def assess(study: Path, observation_set_id: str, scorer_id: str, references_id: str, *, examples_dir: Path | None = None, read_sequence: int | None = None) -> dict:
    """Write and return a new Assessment of the Observation set by the Scorer, against the References set.

    Holds the Study's writer lock for the whole command: a second writer is refused at once. `examples_dir` is
    read only for an Assessment of `public_check` Episodes, to freeze the Workload's digests (default: the repository's).
    """
    study = Path(study)
    study_write.check_read_sequence(study_write.ASSESS, read_sequence)
    layout.read_spec(study)  # a folder that is no Study is refused before a lock file is created in it
    with study_write.locked(study, study_write.ASSESS, read_sequence=read_sequence) as write:
        write.require_current()
        return _assess_locked(study, write, observation_set_id, scorer_id, references_id, examples_dir)


def _assess_locked(study: Path, write, observation_set_id: str, scorer_id: str, references_id: str, examples_dir) -> dict:
    spec = layout.read_spec(study)
    scorer = scorers.get(scorer_id)

    found = layout.find_observation_set(study, observation_set_id)
    if found is None:
        raise _refuse(
            "OBSERVATION_SET_NOT_FOUND", f"the Study keeps no Observation set {observation_set_id!r}", observation_set_id=str(observation_set_id)
        )
    observation_set, manifest = found
    if observation_set["mode"] == SCENARIO_MODE:  # the first check once the Observation set is found: before any check on its content
        raise _refuse(
            "UNSUPPORTED_CAPABILITY",
            "an Observation set of the scripted_fixture Mode records scenarios, not the Workload's Cases: it is neither assessed nor compared",
            mode=observation_set["mode"],
            observation_set_id=observation_set["observation_set_id"],
        )
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
    schema_ref = next((e["ref"] for e in spec["artifacts"] if e["ref"]["role"] == "answer_schema"), None)
    if schema_ref is None:
        raise _refuse("ANSWER_SCHEMA_NOT_KEPT", "the Study keeps no answer schema to score against", study=str(study))

    for ref in observation_set["raw_refs"]:
        artifacts.read_verified(study, ref)  # the answers the Observation set was normalized from
    normalized = artifacts.read_verified(study, observation_set["normalized_ref"])
    population = artifacts.read_verified(study, observation_set["population_ref"])
    references_bytes = artifacts.read_verified(study, references)
    schema = json.loads(artifacts.read_verified(study, schema_ref))

    partition = observation_set["provenance"].get("partition")
    if partition is None:
        raise _refuse("OBSERVATIONS_INVALID", "the Observation set names no Partition", problem="unknown_partition")
    exposed = requires_exposure(partition, not_dev_code="ASSESSMENT_PARTITION_NOT_DEV", what="an Assessment", stage=STAGE)

    expected = _expected(population)
    observed = {}
    for entry in _lines(normalized):
        key = (entry["case_id"], entry["repeat"])
        if key in observed:
            raise _refuse("OBSERVATIONS_INVALID", f"{key} appears twice in the Observation set", problem="duplicate_item", case_id=key[0], repeat=key[1])
        if entry["status"] not in ("produced", "failed", "missing"):
            raise _refuse("OBSERVATIONS_INVALID", f"{key} has the execution status {entry['status']!r}", problem="bad_status", case_id=key[0], repeat=key[1])
        observed[key] = entry
    stray = sorted(set(observed) - set(expected))
    if stray:
        raise _refuse("OBSERVATIONS_INVALID", f"{stray[0]} is not an Episode of the population", problem="unexpected_item", case_id=stray[0][0], repeat=stray[0][1])
    assessment_id = str(uuid.uuid4())
    if exposed:  # before any Episode is scored
        exposure.record(study, write, spec, _live_basis(examples_dir), attempt_ids=[manifest["attempt_id"]], assessment_ids=[assessment_id])
    reference_of = {record["case_id"]: record for record in _lines(references_bytes)}

    verdicts = [_verdict(observed.get(key), key, reference_of, schema) for key in expected]  # a fixed order, whatever the file order

    primary = spec["primary_metric"]["id"]
    counts = _counts(verdicts, primary)
    non_scores = Counter(
        criterion["reason"]
        for verdict in verdicts
        for criterion in verdict["criteria"]
        if criterion["name"] == primary and criterion["state"] != "scored"
    )
    statuses = [verdict["status"] for verdict in verdicts]
    secondary = [name for name in CRITERIA if name != primary]
    detailed = {
        "primary_criterion": primary,
        "criteria": {name: {"counts": _counts(verdicts, name), "metrics": _rates(_counts(verdicts, name))} for name in secondary},
    }

    folder = f"{layout.ASSESSMENTS_DIR}/{assessment_id}"
    per_item = _per_item_csv(verdicts)
    per_item_ref = {
        "path": f"{folder}/per_item.csv",
        "sha256": canonical.sha256_hex(per_item),
        "size_bytes": len(per_item),
        "media_type": "text/csv",
        "role": "per_item",
    }
    detailed_bytes = canonical.dumps(detailed)
    detailed_ref = {
        "path": f"{folder}/metrics.json",
        "sha256": canonical.sha256_hex(detailed_bytes),
        "size_bytes": len(detailed_bytes),
        "media_type": "application/json",
        "role": "detailed_metrics",
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
        "metrics": _rates(counts),
        "limitations": list(LIMITATIONS),
        "study_revision": revisions.identity(spec),
        **exposure.marks(study, [manifest]),
        "recorded_at": now(),
        "rescoring": rescoring.describe(
            study,
            observation_set_id=observation_set["observation_set_id"],
            scorer={"id": scorer.id, "version": scorer.version, "config_digest": scorer.config_digest},
            references_ref=references,
            per_item=per_item,
        ),
        "primary_criterion": primary,
        "unknowns": {"unscored": counts["unscored"], "errored": counts["errored"], "reasons": dict(sorted(non_scores.items()))},
        "operational_errors": {"failed": statuses.count("failed"), "missing": statuses.count("missing")},
        "detailed_metrics_ref": detailed_ref,
    }
    contracts.validate(record)
    write.begin()  # a dev Assessment writes nothing before this; an Exposure began the command already
    artifacts.publish_bytes(study, per_item_ref["path"], per_item, media_type="text/csv", role="per_item")
    write.wrote(study_write.ASSESSMENT, assessment_id)
    artifacts.publish_bytes(study, detailed_ref["path"], detailed_bytes, media_type="application/json", role="detailed_metrics")
    artifacts.publish_record(study, f"{folder}/assessment.json", record, role="assessment")
    return record
