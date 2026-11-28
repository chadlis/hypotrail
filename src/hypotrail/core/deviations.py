"""`deviation`: one Declared deviation, kept in the Study (chadlis/hypotrail#155).

A Declared deviation is one known limit on what results of a Study show, declared in the Study because its records cannot establish it (for
example an owner review of References still pending): what is declared, its author and the ids of the Study's records it cites. It follows
the decision record's shape (`hypotrail.core.decisions`). It is one file,

```
declared_deviations/<seq>-<declared_deviation_id>.json   one Declared deviation each, published atomically and never rewritten
```

`<seq>` is its position among the Study's Declared deviations, count + 1, six digits, as in `decisions/`. The record (`DeclaredDeviationRecord`
of the contract schema) holds the text of what is declared, never empty; the author, `human` or `proxy`; a declared `source` text, or null; the
ids it cites, de-duplicated and sorted, at least one; its `request_id`; the `revision` of the Study's current StudySpec; the `read_sequence`
its author read and its own `write_sequence`.

The command takes its steps in the order `hypotrail.core.study_write` gives a writer that has a `request_id`. Before the lock: the read
sequence value, `REQUEST_ID_EMPTY`, the author, that `--read-sequence` is given, that `--artifact` is given, `DEVIATION_TEXT_EMPTY`, then
`STUDY_NOT_FOUND`. Under the lock: the request identity and the stale sequence (`Write.replay_deviation` runs both), then the ids it cites.
The request identity is the Study's one namespace (`hypotrail.core.requests`): the same `request_id` with the same text, author, source and
cited ids returns the recorded Declared deviation and writes nothing; with another one, or when it names an Attempt or a decision, it is
`REQUEST_CONFLICT`.

A Declared deviation either declares, citing Attempts and References sets (of any revision), or withdraws, citing exactly one earlier
declaration and nothing else. `compare` reads the declarations in force (`in_force`) when it writes a Comparison
(`hypotrail.core.comparison.declared_deviation_warnings`).

`status` lists the Study's Declared deviations (`listing`), each with whether it is withdrawn and the id of the one that withdrew it, computed
when the Study is read and never stored.
"""

import uuid
from pathlib import Path

from hypotrail.core import artifacts, contracts, decisions, requests, revisions, study_write, write_journal
from hypotrail.core import study as layout
from hypotrail.core.errors import InvalidInputError

DEVIATIONS_DIR = "declared_deviations"
STAGE = "deviation"
REFERENCES = "references"
# the fields that make "the same Declared deviation", in the order `differs` lists them
IDENTITY_FIELDS = ("text", "author", "source", "cited_ids")


def records(study) -> list:
    """The Study's Declared deviations, in the order they were recorded; each is validated after it is read."""
    return layout.read_records(study, DEVIATIONS_DIR)


def find_by_request(study, request_id: str):
    """The Declared deviation recorded under `request_id`, or None."""
    return next((each for each in records(study) if each["request_id"] == request_id), None)


def _invalid(message: str) -> InvalidInputError:
    return study_write.invalid_arguments(message, study_write.DEVIATION)


def _refuse(code: str, message: str, **details) -> InvalidInputError:
    return InvalidInputError(code, f"{message}; nothing was written", stage=STAGE, details=details)


def check_arguments(*, text: str, author: str, cited_ids: list, request_id: str, read_sequence) -> None:
    """The command's checks of its own arguments, in their order; each refusal comes before the lock is asked for.

    `record` runs them first. The command line runs them before it calls `record`, so a refused argument enters no function that takes the lock.
    """
    study_write.check_arguments(study_write.DEVIATION, read_sequence, request_id)
    if author not in decisions.AUTHORS:
        raise _invalid(f"the author of a Declared deviation is one of {', '.join(decisions.AUTHORS)}, not {author!r}")
    if read_sequence is None:
        raise _invalid("a Declared deviation is recorded on the write sequence its author read: --read-sequence is required")
    if not cited_ids:
        raise _invalid("a Declared deviation cites at least one id: --artifact is required")
    if not text:
        raise InvalidInputError("DEVIATION_TEXT_EMPTY", "the text of a Declared deviation must not be empty", stage=STAGE, details={"field": "text"})


def record(study, *, text: str, author: str, source: str | None, cited_ids: list, request_id: str, read_sequence: int) -> tuple[dict, bool]:
    """Record (or replay) one Declared deviation under the Study's writer lock; return the record and whether it was recorded already."""
    study = Path(study)
    check_arguments(text=text, author=author, cited_ids=cited_ids, request_id=request_id, read_sequence=read_sequence)
    layout.read_spec(study)  # a folder that is no Study is refused before a lock file is created in it
    wanted = {"text": text, "author": author, "source": source, "cited_ids": sorted(set(cited_ids))}
    with study_write.locked(study, study_write.DEVIATION, request_id, read_sequence=read_sequence) as write:
        return _record_locked(study, write, wanted, request_id, read_sequence)


def _record_locked(study: Path, write, wanted: dict, request_id: str, read_sequence: int) -> tuple[dict, bool]:
    def check_recorded(recorded: dict) -> None:
        differs = [field for field in IDENTITY_FIELDS if recorded[field] != wanted[field]]
        if differs:
            raise requests.conflict_between_declared_deviations(request_id, recorded["declared_deviation_id"], differs)

    recorded = write.replay_deviation(check_recorded)
    if recorded is not None:
        return recorded, True
    _check_cited(study, wanted["cited_ids"])
    spec = layout.read_spec(study)  # read under the lock, after the stale check
    declared_deviation_id = str(uuid.uuid4())
    written = {
        "kind": "declared_deviation",
        "schema_version": "declared_deviation/1",
        "declared_deviation_id": declared_deviation_id,
        "request_id": request_id,
        **wanted,
        "revision": spec["revision"],
        "read_sequence": read_sequence,
        "write_sequence": write_journal.write_sequence(study) + 1,  # the position of the `begin` entry that is appended next
    }
    contracts.validate(written)
    write.begin()
    position = layout.next_position(study, DEVIATIONS_DIR)
    artifacts.publish_record(study, f"{DEVIATIONS_DIR}/{position:06d}-{declared_deviation_id}.json", written, role="declared_deviation")
    write.wrote(study_write.DECLARED_DEVIATION, declared_deviation_id)
    return written, False


def withdrawals(recorded: list) -> dict:
    """{the id of a withdrawn declaration: the id of the Declared deviation that withdrew it}, from the Study's Declared deviations.

    A withdrawal is a record that cites exactly one other Declared deviation, the command refuses any other record that cites one, so the
    first record to cite a declaration is the one that withdrew it.
    """
    ids = {each["declared_deviation_id"] for each in recorded}
    found: dict = {}
    for each in recorded:
        if len(each["cited_ids"]) == 1 and each["cited_ids"][0] in ids:
            found.setdefault(each["cited_ids"][0], each["declared_deviation_id"])
    return found


def listing(study) -> list:
    """The Study's Declared deviations in the order they were recorded, each with every field of its record, `withdrawn` and `withdrawn_by` (read only)."""
    recorded = records(study)
    withdrawn = withdrawals(recorded)
    return [
        {**each, "withdrawn": each["declared_deviation_id"] in withdrawn, "withdrawn_by": withdrawn.get(each["declared_deviation_id"])} for each in recorded
    ]


def in_force(study) -> list:
    """The Study's declarations that no withdrawal withdrew, in the order they were recorded: a withdrawal itself is none of them."""
    recorded = records(study)
    withdrawn = withdrawals(recorded)
    return [each for each in recorded if each["declared_deviation_id"] not in withdrawn and each["declared_deviation_id"] not in withdrawn.values()]


def references_sets(study) -> dict:
    """{artifact_id: sha256} of the References set of every revision of the Study."""
    return {
        entry["artifact_id"]: entry["ref"]["sha256"]
        for spec in revisions.revision_specs(study)
        for entry in spec["artifacts"]
        if entry["ref"]["role"] == REFERENCES
    }


def _check_cited(study: Path, cited: list) -> None:
    """Refuse the ids a record cites on the first check that fails, in the order of D-072 on chadlis/hypotrail#75, item 3.

    "an ID the Study does not hold;" | "mix: a Declared deviation ID cited with any other held ID;" | "several Declared deviations;" |
    "citing a withdrawal;" | "a kind that cannot be cited;" | "already withdrawn."
    """
    unknown = sorted(set(cited) - decisions.held_ids(study))
    if unknown:
        raise _refuse("CITED_ID_NOT_FOUND", f"the Study holds no record with the id {', '.join(map(repr, unknown))}", ids=unknown)
    recorded = records(study)
    by_id = {each["declared_deviation_id"]: each for each in recorded}
    deviations = [each for each in cited if each in by_id]
    others = [each for each in cited if each not in by_id]
    if deviations and others:
        raise _refuse(
            "DEVIATION_CITES_A_MIX",
            "a Declared deviation either declares, citing Attempts and References sets, or withdraws, citing one Declared deviation and nothing else",
            declared_deviation_ids=deviations,
            other_ids=others,
        )
    if len(deviations) > 1:
        raise _refuse("DEVIATION_CITES_SEVERAL_DEVIATIONS", "a withdrawal cites exactly one Declared deviation", declared_deviation_ids=deviations)
    withdrawn = withdrawals(recorded)
    if deviations and deviations[0] in set(withdrawn.values()):
        raise _refuse(
            "DEVIATION_CITES_A_WITHDRAWAL",
            f"{deviations[0]!r} is a withdrawal, which no Declared deviation may cite: to declare again, record a new declaration",
            id=deviations[0],
        )
    citable = set(layout.attempt_ids(study)) | set(references_sets(study))
    not_citable = sorted(each for each in others if each not in citable)
    if not_citable:
        raise _refuse(
            "CITED_KIND_NOT_CITABLE",
            f"a declaration cites Attempts and References sets only, not {', '.join(map(repr, not_citable))}",
            ids=not_citable,
        )
    if deviations and deviations[0] in withdrawn:
        raise _refuse(
            "DEVIATION_ALREADY_WITHDRAWN",
            f"the Declared deviation {deviations[0]!r} is withdrawn already, by {withdrawn[deviations[0]]!r}",
            id=deviations[0],
            withdrawn_by=withdrawn[deviations[0]],
        )
