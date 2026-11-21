"""`decide`: one decision, kept in the Study (chadlis/hypotrail#109, slice #104; D-031 on chadlis/hypotrail#75 and the decisions that follow it on that issue).

The Study is the only decision authority: a decision is a record of the Study, and nowhere else. It is one file,

```
decisions/<seq>-<decision_id>.json   one decision each, published atomically and never rewritten
```

`<seq>` is the decision's position among the Study's decisions, count + 1, six digits, as in `exposures/`. The record (`DecisionRecord` of the
contract schema) holds the question it answers and the option chosen, both free text and never empty; the author, `human` or `proxy`, recorded by
its kind only; a declared `source` text, or null; the ids it cites, de-duplicated and sorted, at least one; its `request_id`; the `revision` of the
Study's current StudySpec; and two numbers of the write sequence (`hypotrail.core.write_journal`): the `read_sequence` its author read and its
own `write_sequence`, the position of the `begin` entry of the command that recorded it, always one above the first.

The order of the checks, under the writer lock, is that of every writer: the arguments (`REQUEST_ID_EMPTY`, `DECISION_FIELD_EMPTY`, the author and the
sequence); `STUDY_NOT_FOUND`; the lock; the request identity; the stale sequence (`require_current`); then `CITED_ID_NOT_FOUND`. A refusal appends nothing to
the write journal. The request identity is shared with the Attempts of the Study (one namespace, `hypotrail.core.requests`): the same `request_id` with
the same decision (question, option, author, source and cited ids; the read sequence is not part of it) returns the recorded decision and writes
nothing, even when the sequence has moved on; with another decision, or when it names an Attempt, it is `REQUEST_CONFLICT`.

An id is citable when the Study holds a record with that id, of one of these kinds: Attempt, Observation set, Assessment, Comparison, Study artifact,
revision (by its `revision` value, never its `revision_number`), freeze record, Exposure entry or decision. A `request_id`, the `study_id`, a path
and a file's content digest (`sha256`, `protocol_digest`) are not citable.

`status` lists the decisions with whether each still applies (chadlis/hypotrail#110; D-033 on chadlis/hypotrail#75, amended by D-034 on chadlis/hypotrail#75, D-035 on chadlis/hypotrail#75, D-036 on chadlis/hypotrail#75 and D-037 on chadlis/hypotrail#75): `history(study)`.
Whether a decision applies is computed when the Study is read, from the ids it cites and the records of the Study, and is never stored: no record is written
or changed when it changes. A decision no longer applies when a cited id is no longer held (`cited_id_not_held`), when the Study's current revision differs
from the `revision` its record stores (`revision_changed`, its `id` the current `revision`), or when a cited Assessment has a later Assessment of the same
Observation set and the same Scorer id, whatever its version (`assessment_superseded`, its `id` the latest of the later Assessments). "Later" is the
position in the write journal (the `end` entry that names the Assessment in its `written` list); a record that no `end` entry names is at position 0,
before every journaled record, and ties are broken by `(recorded_at, id)`. A later decision on the same question changes nothing.
"""

import contextlib
import uuid
from pathlib import Path

from hypotrail.core import artifacts, contracts, exposure, lock, requests, revisions, write_journal
from hypotrail.core import study as layout
from hypotrail.core.errors import InvalidInputError

COMMAND = "decide"
DECISIONS_DIR = "decisions"
STAGE = "decision"
AUTHORS = ("human", "proxy")
# the fields that make "the same decision" (D-034 on chadlis/hypotrail#75), in the order `differs` lists them
IDENTITY_FIELDS = ("question", "option", "author", "source", "cited_ids")


def _names(study) -> list:
    folder = Path(study) / DECISIONS_DIR
    return sorted(p.name for p in folder.iterdir() if p.name.endswith(".json") and not p.name.startswith(".")) if folder.is_dir() else []


def records(study) -> list:
    """The Study's decisions, in the order they were recorded; each is validated after it is read."""
    return [layout.read_record(study, f"{DECISIONS_DIR}/{name}") for name in _names(study)]


def find_by_request(study, request_id: str):
    """The decision recorded under `request_id`, or None."""
    return next((record for record in records(study) if record["request_id"] == request_id), None)


def refuse_if_a_decision_holds(study, request_id: str) -> None:
    """Refuse a `run` or an `import` whose `request_id` names a decision: a Study has one request_id namespace."""
    recorded = find_by_request(study, request_id)
    if recorded is not None:
        raise requests.conflict_with_a_decision(request_id, recorded["decision_id"])


def held_ids(study) -> set:
    """The ids of the records of the Study that a decision may cite."""
    study = Path(study)
    found = set(layout.attempt_ids(study))
    for attempt_id in layout.attempt_ids(study):
        for ref in layout.read_manifest(study, attempt_id).get("output_refs", []):
            if ref["role"] == "observation_set":
                with contextlib.suppress(OSError):  # a referenced record that is missing holds no id
                    found.add(layout.read_record(study, ref["path"])["observation_set_id"])
    found |= {record["assessment_id"] for record in layout.assessment_records(study)}
    found |= {record["comparison_id"] for record in layout.comparison_records(study)}
    for spec in revisions.revision_specs(study):
        found.add(spec["revision"])
        found |= {entry["artifact_id"] for entry in spec["artifacts"]}
    found |= {record["freeze_id"] for record in exposure.freeze_records(study)}
    found |= {record["entry_id"] for record in exposure.entries(study)}
    found |= {record["decision_id"] for record in records(study)}
    return found


def _journal_positions(study) -> dict:
    """{Assessment id: position, from 1, of the first `end` entry of the write journal that names it}; an id that none names is absent (position 0)."""
    positions: dict = {}
    for position, entry in enumerate(write_journal.entries(study), 1):
        for item in entry.get("written", []):
            if item["kind"] == "assessment":
                positions.setdefault(item["id"], position)
    return positions


def _reasons(record: dict, *, held: set, revision: str, assessments: dict, positions: dict) -> list:
    """Why `record` no longer applies: `[{"reason", "id"}]`, empty when it applies."""

    def order(assessment: dict) -> tuple:
        return positions.get(assessment["assessment_id"], 0), assessment.get("recorded_at", ""), assessment["assessment_id"]

    reasons = [{"reason": "cited_id_not_held", "id": cited} for cited in record["cited_ids"] if cited not in held]
    if record["revision"] != revision:
        reasons.append({"reason": "revision_changed", "id": revision})
    for cited in record["cited_ids"]:
        cited_assessment = assessments.get(cited)
        if cited_assessment is None:
            continue
        later = [
            other
            for other in assessments.values()
            if other["observation_set_id"] == cited_assessment["observation_set_id"]
            and other["scorer"]["id"] == cited_assessment["scorer"]["id"]
            and order(other) > order(cited_assessment)
        ]
        if later:
            reasons.append({"reason": "assessment_superseded", "id": max(later, key=order)["assessment_id"]})
    return reasons


def history(study) -> list:
    """The Study's decisions in the order they were recorded, each with every field `decide` recorded, `applies` and `reasons` (read only)."""
    study = Path(study)
    recorded = records(study)
    if not recorded:
        return []
    shared = {
        "held": held_ids(study),
        "revision": layout.read_spec(study)["revision"],
        "assessments": {record["assessment_id"]: record for record in layout.assessment_records(study)},
        "positions": _journal_positions(study),
    }
    rows = []
    for record in recorded:
        reasons = _reasons(record, **shared)
        rows.append({**record, "applies": not reasons, "reasons": reasons})
    return rows


def _invalid(message: str) -> InvalidInputError:
    return InvalidInputError("INVALID_ARGUMENTS", message, stage="config", details={"command": COMMAND})


def decide(
    study,
    *,
    question: str,
    option: str,
    author: str,
    source: str | None,
    cited_ids: list,
    request_id: str,
    read_sequence: int,
) -> tuple[dict, bool]:
    """Record (or replay) one decision under the Study's writer lock; return the record and whether it was recorded already."""
    study = Path(study)
    if not request_id:
        raise InvalidInputError("REQUEST_ID_EMPTY", "--request-id must not be empty", stage="request", details={})
    if author not in AUTHORS:
        raise _invalid(f"the author of a decision is one of {', '.join(AUTHORS)}, not {author!r}")
    if read_sequence is None:
        raise _invalid("a decision is made on the write sequence its author read: --read-sequence is required")
    if not cited_ids:
        raise _invalid("a decision cites at least one id: --artifact is required")
    for field, value in (("question", question), ("option", option)):
        if not value:
            raise InvalidInputError("DECISION_FIELD_EMPTY", f"the {field} of a decision must not be empty", stage=STAGE, details={"field": field})
    layout.read_spec(study)  # a folder that is no Study is refused before a lock file is created in it
    wanted = {"question": question, "option": option, "author": author, "source": source, "cited_ids": sorted(set(cited_ids))}
    with lock.writer_lock(study), write_journal.writing(study, COMMAND, request_id):
        return _decide_locked(study, wanted, request_id, read_sequence)


def _decide_locked(study: Path, wanted: dict, request_id: str, read_sequence: int) -> tuple[dict, bool]:
    recorded = find_by_request(study, request_id)
    if recorded is not None:
        differs = [field for field in IDENTITY_FIELDS if recorded[field] != wanted[field]]
        if differs:
            raise requests.conflict_between_decisions(request_id, recorded["decision_id"], differs)
        return recorded, True
    attempt = layout.find_by_request(study, request_id)
    if attempt is not None:
        raise requests.conflict_with_an_attempt(request_id, attempt["attempt_id"])
    write_journal.require_current(study, read_sequence)
    spec = layout.read_spec(study)  # read under the lock, after the stale check
    unknown = sorted(set(wanted["cited_ids"]) - held_ids(study))
    if unknown:
        raise InvalidInputError(
            "CITED_ID_NOT_FOUND",
            f"the Study holds no record with the id {', '.join(map(repr, unknown))}; nothing was written",
            stage=STAGE,
            details={"ids": unknown},
        )
    decision_id = str(uuid.uuid4())
    record = {
        "kind": "decision",
        "schema_version": "decision/1",
        "decision_id": decision_id,
        "request_id": request_id,
        **wanted,
        "revision": spec["revision"],
        "read_sequence": read_sequence,
        "write_sequence": write_journal.write_sequence(study) + 1,  # the position of the `begin` entry that is appended next
    }
    contracts.validate(record)
    write_journal.begin()
    position = len(_names(study)) + 1
    artifacts.publish_record(study, f"{DECISIONS_DIR}/{position:06d}-{decision_id}.json", record, role="decision")
    write_journal.wrote("decision", decision_id)
    return record, False
