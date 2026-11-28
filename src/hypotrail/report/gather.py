"""What `report` reads of a Study: its records, each artifact read back against its digest, nothing recomputed from a model.

Every ArtifactRef the page shows is read with `artifacts.read_verified` (a changed byte is `ARTIFACT_INTEGRITY`, exit 3).
The Workload is never read here: the page is made from the Study alone.
2026-11-26: the page also shows the data profile the command hands it, which the Track reads from the Workload (`hypotrail.ml.profile`).
"""

import csv
import io
import math

from hypotrail.core import artifacts, canonical, contracts, evaluator, exposure, revisions, state, write_journal
from hypotrail.core import study as layout
from hypotrail.report import ranking
from hypotrail.core.attempts import SCENARIO_MODE
from hypotrail.core.errors import InvalidInputError

DEV = "dev"
PUBLIC_CHECK = "public_check"
REGRESSION = "regression"
AGENTIC = "agentic"
RANKING = "ranking"
TOP_ERRORS = 10


def _rows(data: bytes) -> list:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"), newline="")))


def finite(cell):
    """The finite float a cell holds, or None: a null, an empty cell, a non-number and `nan` or `inf` are all unknown."""
    try:
        value = float(cell)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class Reader:
    """Reads each artifact once, against its digest."""

    def __init__(self, study):
        self.study = study
        self._seen = {}

    def bytes_of(self, ref: dict) -> bytes:
        key = (ref["path"], ref["sha256"], ref["size_bytes"])
        if key not in self._seen:
            self._seen[key] = artifacts.read_verified(self.study, ref)
        return self._seen[key]


def observation_set_of(reader: Reader, manifest: dict):
    refs = layout.observation_set_refs(manifest)
    if not refs:
        return None
    record = canonical.loads(reader.bytes_of(refs[0]))
    contracts.validate(record)
    return record


def _licence_notice(reader: Reader, manifest: dict):
    """The path of the licence notice the Workload declared, from the copy of its declaration the Attempt kept, or None."""
    ref = next((r for r in manifest["input_refs"] if r["role"] == "workload_declaration"), None)
    if ref is None:
        return None
    declaration = canonical.loads(reader.bytes_of(ref))
    notice = declaration.get("licence_notice") if isinstance(declaration, dict) else None
    return notice if isinstance(notice, str) else None


def partition_of(manifest: dict, observation_set):
    """The Partition an Attempt's outputs belong to: the Observation set's, else the one the manifest records."""
    if observation_set is not None:
        return observation_set["provenance"].get("partition")
    return manifest["effective_config"].get("partition")


def attempts_of(study, reader: Reader, *, ranking: bool = False) -> list:
    """Every Attempt with its verified Observation set, in a fixed order. The aggregate ranking report uses metadata files."""
    attempts = []
    for attempt_id in layout.attempt_ids(study):
        manifest = layout.read_manifest(study, attempt_id)
        if ranking and manifest["effective_config"].get("partition") != DEV:
            raise _ranking_scope("attempt", attempt_id)
        if not ranking:
            for ref in [*manifest["input_refs"], *manifest.get("output_refs", [])]:
                reader.bytes_of(ref)
        observation_set = observation_set_of(reader, manifest)
        partition = partition_of(manifest, observation_set)
        if ranking and (observation_set is None or partition != DEV):
            raise _ranking_scope("attempt", attempt_id)
        attempts.append(
            {
                "manifest": manifest,
                "observation_set": observation_set,
                "partition": partition,
                "licence_notice": _licence_notice(reader, manifest),
            }
        )
    attempts.sort(key=lambda a: (a["manifest"]["started_at"], a["manifest"]["attempt_id"]))
    return attempts


def comparisons_of(study, reader: Reader) -> list:
    comparisons = []
    for record in layout.comparison_records(study):
        for ref in (record["population_ref"], record.get("paired_deltas_ref"), record.get("matrix_ref")):
            if ref is not None:
                reader.bytes_of(ref)
        comparisons.append(record)
    return comparisons


def _unverified_scope(kind: str, record_id: str) -> InvalidInputError:
    return InvalidInputError(
        "REPORT_SCOPE_UNVERIFIED",
        "the run tool cannot establish the report's Partition from the Study records",
        stage="report",
        details={"kind": kind, "record_id": record_id},
    )


def _ranking_scope(kind: str, record_id: str) -> InvalidInputError:
    return InvalidInputError(
        "REPORT_SCOPE_UNVERIFIED", "the ranking report requires a development population", stage="report",
        details={"kind": kind, "record_id": record_id},
    )


def _partition_metadata_valid(partition) -> bool:
    """Accept an absent value or a declared name, including custom regression Partitions."""
    return partition is None or (isinstance(partition, str) and bool(partition.strip()))


def _verify_report_scope(study) -> None:
    manifests = [layout.read_manifest(study, attempt_id) for attempt_id in layout.attempt_ids(study)]
    for manifest in manifests:
        exposure.refuse_public_check(PUBLIC_CHECK, manifest["effective_config"].get("partition"))
    observation_ids = set()
    for manifest in manifests:
        declared = manifest["effective_config"].get("partition")
        refs = layout.observation_set_refs(manifest)
        fixture = manifest["mode"] == SCENARIO_MODE
        if not _partition_metadata_valid(declared) or (not refs and declared is None and not fixture):
            raise _unverified_scope("attempt", manifest["attempt_id"])
        for ref in refs:
            observation_set = layout.read_record(study, ref["path"])
            recorded = partition_of(manifest, observation_set)
            exposure.refuse_public_check(PUBLIC_CHECK, recorded)
            if not _partition_metadata_valid(recorded) or (recorded is None and declared is None and not fixture):
                raise _unverified_scope("attempt", manifest["attempt_id"])
            observation_ids.add(observation_set["observation_set_id"])
    assessment_ids = set()
    for assessment in layout.assessment_records(study):
        if assessment["observation_set_id"] not in observation_ids:
            raise _unverified_scope("assessment", assessment["assessment_id"])
        assessment_ids.add(assessment["assessment_id"])
    for comparison in layout.comparison_records(study):
        roles = comparison["roles"]
        if {roles["control_assessment_id"], roles["candidate_assessment_id"]} - assessment_ids:
            raise _unverified_scope("comparison", comparison["comparison_id"])


def load(study, *, guarded: bool = False, profile=None) -> dict:
    """The model of the page: every record of the Study the page shows, verified, in a fixed order."""
    spec = layout.read_spec(study)
    if evaluator.inside():
        evaluator.require_study(spec, stage="report", run_tool=guarded)
        return ranking.aggregates(study)
    evaluator.refuse_protected(spec, stage="report")
    if guarded:
        _verify_report_scope(study)
    reader = Reader(study)
    if spec["domain"] == RANKING:
        return _load_ranking(study, spec, reader)
    for ref in [*spec["dataset_refs"], *(entry["ref"] for entry in spec["artifacts"])]:
        reader.bytes_of(ref)
    if spec["domain"] == AGENTIC:
        from hypotrail.report import gather_agent

        return gather_agent.load(study, spec, reader)
    model = _load_regression(study, spec, reader)
    if profile is not None:
        model["profile"] = profile(study)
    return model


def _load_ranking(study, spec: dict, reader: Reader) -> dict:
    attempts = attempts_of(study, reader, ranking=True)
    by_observation = {a["observation_set"]["observation_set_id"]: a for a in attempts if a["observation_set"] is not None}
    assessments = []
    for record in layout.assessment_records(study):
        attempt = by_observation.get(record["observation_set_id"])
        if attempt is None:
            raise _ranking_scope("assessment", record["assessment_id"])
        assessments.append({"record": record, "attempt": attempt})
    order = write_journal.assessment_order(study)
    assessments.sort(key=lambda a: order(a["record"]))
    assessment_ids = {entry["record"]["assessment_id"] for entry in assessments}
    comparisons = layout.comparison_records(study)
    for record in comparisons:
        if set(record["roles"].values()) - assessment_ids:
            raise _ranking_scope("comparison", record["comparison_id"])

    memberships_ref = next(entry["ref"] for entry in spec["artifacts"] if entry["ref"]["role"] == "memberships")
    members = _rows(reader.bytes_of(memberships_ref))
    if any(row["partition"] != DEV for row in members):
        raise _ranking_scope("study", spec["study_id"])
    return {
        "domain": RANKING,
        "spec": spec,
        "revision_number": revisions.revision_number(spec),
        "memberships": {row["item_id"]: {"date": row["as_of"], "partition": row["partition"]} for row in members},
        "attempts": attempts,
        "assessments": assessments,
        "comparisons": comparisons,
        "exposure": exposure_of(study),
    }


def _load_regression(study, spec: dict, reader: Reader) -> dict:
    memberships_ref = next(entry["ref"] for entry in spec["artifacts"] if entry["ref"]["role"] == "memberships")
    memberships = {row["row_id"]: row for row in _rows(reader.bytes_of(memberships_ref))}
    attempts = attempts_of(study, reader)
    by_observation_set = {a["observation_set"]["observation_set_id"]: a for a in attempts if a["observation_set"] is not None}

    order = write_journal.assessment_order(study)
    assessments = []
    for record in layout.assessment_records(study):
        reader.bytes_of(record["per_item_ref"])
        references = reader.bytes_of(record["references_ref"])
        attempt = by_observation_set.get(record["observation_set_id"])
        assessments.append(
            {
                "record": record,
                "attempt": attempt,
                "per_item": _rows(reader.bytes_of(record["per_item_ref"])),
                "references": {row["row_id"]: row["y_true"] for row in _rows(references)},
                "predictions": _predictions(reader, attempt),
            }
        )
    assessments.sort(key=lambda a: order(a["record"]))

    return {
        "domain": REGRESSION,
        "spec": spec,
        "revision_number": revisions.revision_number(spec),
        "memberships": memberships,
        "attempts": attempts,
        "assessments": assessments,
        "comparisons": comparisons_of(study, reader),
        "exposure": exposure_of(study),
    }


def _predictions(reader: Reader, attempt):
    if attempt is None or attempt["observation_set"] is None:
        return {}
    return {row["row_id"]: row["y_pred"] for row in _rows(reader.bytes_of(attempt["observation_set"]["normalized_ref"]))}


def exposure_of(study) -> dict:
    """The journal, the statement that an earlier exposure is unknown and every `check_informed` mark."""
    return {**exposure.summary(study), "check_informed": state.check_informed(study)}


def touched(model: dict) -> dict:
    """The records of `public_check` Items the page shows: `{"attempts", "assessments", "comparisons"}`, each a sorted list of IDs.

    An Attempt is shown with its Item counts, an Assessment with its counts and errors, a Comparison with its deltas: each
    shows Items of its Partition. An Attempt that has no outputs shows no Item.
    """
    attempts = {a["manifest"]["attempt_id"] for a in model["attempts"] if a["partition"] == PUBLIC_CHECK and a["manifest"].get("item_counts") is not None}
    assessments = {
        a["record"]["assessment_id"] for a in model["assessments"] if a["attempt"] is not None and a["attempt"]["partition"] == PUBLIC_CHECK
    }
    comparisons = {
        c["comparison_id"]
        for c in model["comparisons"]
        if {c["roles"]["control_assessment_id"], c["roles"]["candidate_assessment_id"]} & assessments
    }
    attempts |= {a["attempt"]["manifest"]["attempt_id"] for a in model["assessments"] if a["record"]["assessment_id"] in assessments}
    return {"attempts": sorted(attempts), "assessments": sorted(assessments), "comparisons": sorted(comparisons)}


def monthly(assessment: dict, memberships: dict) -> list:
    """`[(month, items, scored, mean absolute error or None)]` from the Assessment's per-Item absolute errors, in month order."""
    months = {}
    for row in assessment["per_item"]:
        date = memberships.get(row["row_id"], {}).get("date") or ""
        month = date[:7] or None
        entry = months.setdefault(month, {"items": 0, "errors": []})
        entry["items"] += 1
        value = finite(row["value"]) if row["state"] == "scored" else None
        if value is not None:
            entry["errors"].append(value)
    return [
        (month, entry["items"], len(entry["errors"]), sum(entry["errors"]) / len(entry["errors"]) if entry["errors"] else None)
        for month, entry in sorted(months.items(), key=lambda kv: (kv[0] is None, kv[0] or ""))
    ]


def largest_errors(assessment: dict, memberships: dict, limit: int = TOP_ERRORS) -> list:
    """The `limit` scored Items with the largest absolute error, largest first (ties by Item ID), each with its date, true and predicted values."""
    scored = [(finite(row["value"]), row["row_id"]) for row in assessment["per_item"] if row["state"] == "scored"]
    scored = sorted(((error, row_id) for error, row_id in scored if error is not None), key=lambda e: (-e[0], e[1]))[:limit]
    out = []
    for error, row_id in scored:
        truth, predicted = finite(assessment["references"].get(row_id)), finite(assessment["predictions"].get(row_id))
        out.append(
            {
                "row_id": row_id,
                "date": memberships.get(row_id, {}).get("date"),
                "y_true": truth,
                "y_pred": predicted,
                "difference": None if truth is None or predicted is None else predicted - truth,
                "abs_error": error,
            }
        )
    return out


def reasons(assessment: dict) -> list:
    """`[(criterion, state, reason, items)]`: the per-Item states of an Assessment, counted."""
    tally = {}
    for row in assessment["per_item"]:
        key = (row["criterion"], row["state"], row["reason"] or None)
        tally[key] = tally.get(key, 0) + 1
    return [(*key, count) for key, count in sorted(tally.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or ""))]


def partitions(model: dict) -> list:
    """`[(Partition, Items, first date, last date)]` read from the Study's population (memberships)."""
    found = {}
    for row in model["memberships"].values():
        if row["partition"]:
            dates = found.setdefault(row["partition"], [])
            dates.append(row["date"])
    return [(name, len(dates), min(dates), max(dates)) for name, dates in sorted(found.items(), key=lambda kv: min(kv[1]))]
