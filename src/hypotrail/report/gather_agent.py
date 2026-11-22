"""What `report` reads of a Study of the tool-using agent Track: the common records of `gather`, plus Episodes, self-checks and traces.

Nothing here opens an Inspect log or the Chinook database: a trace is a reference (its Study-relative path and SHA-256)
that the page links to (ADR 0001, SPEC ENV-03). The Observations are the normalized lines the Study keeps; the run
record (`run.json`) and the self-check are Hypotrail's own records.
"""

import json

from hypotrail.core import canonical, revisions, write_journal
from hypotrail.core import study as layout
from hypotrail.report import gather

INSPECT_LOG_SUFFIX = ".eval"


def _lines(data: bytes) -> list:
    return [canonical.loads(text) for text in data.decode("utf-8").splitlines() if text.strip()]


def _json_record(reader: gather.Reader, manifest: dict, role: str):
    """The JSON record an Attempt published under `role`, or None when it published none or it is not readable JSON."""
    ref = next((r for r in manifest.get("output_refs", []) if r["role"] == role), None)
    if ref is None:
        return None
    try:
        return json.loads(reader.bytes_of(ref))
    except ValueError:
        return None


def trace_of(observation_set):
    """`{"ref", "kind"}` of the one artifact an Episode's trace is read from, or None.

    `log` is an Inspect log (a native Attempt's, or the `.eval` source of an Import); `source` is the JSON Lines file of an
    Import, whose lines hold the steps themselves. The log is linked, never read.
    """
    if observation_set is None:
        return None
    for ref in observation_set["raw_refs"]:
        if ref["path"].endswith(INSPECT_LOG_SUFFIX):
            return {"ref": ref, "kind": "log"}
    return {"ref": observation_set["raw_refs"][0], "kind": "source"} if observation_set["raw_refs"] else None


def load(study, spec: dict, reader: gather.Reader) -> dict:
    memberships_ref = next(entry["ref"] for entry in spec["artifacts"] if entry["ref"]["role"] == "memberships")
    memberships = layout.partition_of(reader.bytes_of(memberships_ref), "case_id")
    attempts = gather.attempts_of(study, reader)
    for attempt in attempts:
        observation_set, manifest = attempt["observation_set"], attempt["manifest"]
        attempt["entries"] = (
            {(e["case_id"], e["repeat"]): e for e in _lines(reader.bytes_of(observation_set["normalized_ref"]))} if observation_set is not None else {}
        )
        attempt["trace"] = trace_of(observation_set)
        attempt["self_check"] = _json_record(reader, manifest, "self_check")
        attempt["run_record"] = _json_record(reader, manifest, "run_record")
    by_observation_set = {a["observation_set"]["observation_set_id"]: a for a in attempts if a["observation_set"] is not None}

    order = write_journal.assessment_order(study)
    assessments = []
    for record in layout.assessment_records(study):
        detailed = reader.bytes_of(record["detailed_metrics_ref"]) if record.get("detailed_metrics_ref") else None
        assessments.append(
            {
                "record": record,
                "attempt": by_observation_set.get(record["observation_set_id"]),
                "per_item": gather._rows(reader.bytes_of(record["per_item_ref"])),
                "detailed": json.loads(detailed) if detailed is not None else {"criteria": {}},
            }
        )
    assessments.sort(key=lambda a: order(a["record"]))

    comparisons = gather.comparisons_of(study, reader)
    paired = {}
    for record in comparisons:
        ref = record.get("paired_deltas_ref")
        paired[record["comparison_id"]] = gather._rows(reader.bytes_of(ref)) if ref is not None else None

    return {
        "domain": gather.AGENTIC,
        "spec": spec,
        "revision_number": revisions.revision_number(spec),
        "memberships": memberships,
        "attempts": attempts,
        "assessments": assessments,
        "comparisons": comparisons,
        "paired": paired,
        "exposure": gather.exposure_of(study),
    }


def partitions(model: dict) -> list:
    """`[(Partition, Cases, their IDs)]` read from the Study's population (memberships)."""
    found = {}
    for case_id, partition in model["memberships"].items():
        found.setdefault(partition, []).append(case_id)
    return [(name, len(cases), ", ".join(sorted(cases))) for name, cases in sorted(found.items())]


def episodes(assessment: dict) -> dict:
    """`{(case_id, repeat): {"status", "answer_given_as", "answer_read_from", "criteria": {name: row}}}` from the Assessment's per-Item file."""
    out = {}
    for row in assessment["per_item"]:
        key = (row["case_id"], int(row["repeat"]))
        entry = out.setdefault(
            key, {"status": row["execution_status"], "answer_given_as": row["answer_given_as"], "answer_read_from": row["answer_read_from"], "criteria": {}}
        )
        entry["criteria"][row["criterion"]] = row
    return out


def non_scores(assessment: dict, criterion: str) -> dict:
    """`{Reason: Episodes}` of the Episodes whose state for `criterion` is not `scored`, counted from the per-Item file."""
    tally = {}
    for row in assessment["per_item"]:
        if row["criterion"] == criterion and row["state"] != "scored":
            tally[row["reason"] or None] = tally.get(row["reason"] or None, 0) + 1
    return dict(sorted(tally.items(), key=lambda kv: kv[0] or ""))
