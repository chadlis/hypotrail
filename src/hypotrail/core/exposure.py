"""The freeze record, the Exposure journal and `check_informed` (SPEC §2, freeze and exposure; chadlis/hypotrail#73).

An Exposure is any Assessment or Comparison that touches `public_check` Items, native or imported, for
either Track (GLOSSARY, #1 amendment). Before the first one of a Study revision, the revision holds a
freeze record; every Exposure is then appended to the Study's journal. Both live in the Study:

```
revisions/<n>/freeze.json       the freeze record of revision n, written once, before its first journal entry
exposures/<seq>-<entry_id>.json one journal entry each, published atomically and never rewritten
```

The freeze record holds the digest of the Protocol (the revision's own), of every Configuration the Workload
declares, of the environment (Python and the dependency lock) and of the code (revision and dirty state). The
first command that would touch `public_check` Items in a revision writes it, before it computes anything, when
none exists (Tightened A). A journal entry names the freeze record it follows, and the IDs of the Attempts,
Assessments and Comparisons it touches. The journal belongs to the Study, not to a revision: the Study's first
Exposure, whatever its revision, is the one that counts (Tightened C).

`check_informed` marks what the Exposure may have informed:

- a revision created after the Study's first Exposure (`hypotrail.core.revisions.check_informed_mark`);
- every Attempt, Assessment and Comparison that uses a Configuration whose digest is not in the freeze record
  written before the first Exposure (Tightened E2). A Configuration changed after the first Exposure is a new
  revision of that Configuration, identified by its new digest; it is not refused. An Import has no
  Configuration digest, so it is never marked through this rule, and its producer's exposure to `public_check`
  stays `unknown`.

A Study with no entry has recorded no Exposure *in this Study*; that says nothing about what the user or an
Import's producer saw elsewhere (SPEC §2), and no record here claims that `public_check` was never seen.

Commands that write call `record` under the Study's writer lock. It refuses (`PROTOCOL_CHANGED`, exit 3,
nothing written) when the Workload's live Protocol is not the revision's. Which Items an entry point may
compute on is the entry point's own rule; this module only records.
"""

import datetime
import uuid
from pathlib import Path

from hypotrail.core import artifacts, canonical, contracts, data, environment
from hypotrail.core import study as layout
from hypotrail.core.errors import IntegrityError

STAGE = "exposure"
FREEZE_NAME = "freeze.json"
JOURNAL_DIR = "exposures"
REVISIONS_DIR = "revisions"
UNKNOWN_EARLIER = "unknown"
EARLIER_EXPOSURE_STATEMENT = (
    "This count is of the Exposures this Study recorded. Any earlier exposure to public_check, by the user or by the "
    "producer of an Import, is unknown: no local lock proves that it never happened."
)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def freeze_path(number: int) -> str:
    return f"{REVISIONS_DIR}/{number}/{FREEZE_NAME}"


def read_freeze(study, number: int):
    """The freeze record of revision `number`, or None."""
    if not artifacts.resolve(study, freeze_path(number)).is_file():
        return None
    return layout.read_record(study, freeze_path(number))


def freeze_records(study) -> list:
    """Every freeze record of the Study, in order of revision number."""
    folder = Path(study) / REVISIONS_DIR
    numbers = sorted(int(p.name) for p in folder.iterdir() if p.name.isdigit() and (p / FREEZE_NAME).is_file()) if folder.is_dir() else []
    return [layout.read_record(study, freeze_path(number)) for number in numbers]


def entries(study) -> list:
    """The journal entries, in the order they were appended."""
    folder = Path(study) / JOURNAL_DIR
    names = sorted(p.name for p in folder.iterdir() if p.name.endswith(".json") and not p.name.startswith(".")) if folder.is_dir() else []
    return [layout.read_record(study, f"{JOURNAL_DIR}/{name}") for name in names]


def first_freeze(study):
    """The freeze record the Study's first journal entry follows, or None while the journal is empty."""
    journal = entries(study)
    if not journal:
        return None
    return next(freeze for freeze in freeze_records(study) if freeze["freeze_id"] == journal[0]["freeze_id"])


def summary(study) -> dict:
    """What the Study records of its Exposures, with the statement that earlier exposure is unknown."""
    journal = entries(study)
    return {
        "recorded_in_this_study": len(journal),
        "earlier_exposure": UNKNOWN_EARLIER,
        "statement": EARLIER_EXPOSURE_STATEMENT,
        "entries": journal,
    }


def configuration_digest_of(manifest: dict):
    """The digest of the Configuration an Attempt ran, or None for an Import (it records no declared Configuration)."""
    configuration = manifest["effective_config"].get("configuration")
    declared = configuration.get("declared") if isinstance(configuration, dict) else None
    return None if declared is None else canonical.digest(declared)


def is_informed(study, configuration_digest) -> bool:
    """True when the Study has had its first Exposure and its first freeze record does not hold this Configuration."""
    if configuration_digest is None:
        return False
    first = first_freeze(study)
    return first is not None and configuration_digest not in first["configuration_digests"].values()


def marks(study, manifests=(), assessments=()) -> dict:
    """`{"check_informed": True}` when a Configuration used by these records is marked, `{}` otherwise.

    A record already marked stays so; a Configuration is judged by its digest against the Study's first freeze
    record at the time of writing.
    """
    marked = any(a.get("check_informed") for a in assessments) or any(
        m.get("check_informed") or is_informed(study, configuration_digest_of(m)) for m in manifests
    )
    return {"check_informed": True} if marked else {}


def _track(spec: dict):
    if spec["domain"] == "agentic":
        from hypotrail.agentic import study as track
    else:
        from hypotrail.ml import study as track
    return track


def basis(spec: dict, examples_dir) -> dict:
    """The Protocol digest and the Configuration digests of the Workload as it is declared now.

    Refuses with `PROTOCOL_CHANGED` (exit 3) when that Protocol is not the revision's: nothing has been written.
    """
    examples = Path(examples_dir) if examples_dir is not None else data.default_examples_dir()
    live = _track(spec).freeze_basis(spec, examples / spec["workload"])
    if live["protocol_digest"] != spec["protocol_digest"]:
        raise IntegrityError(
            "PROTOCOL_CHANGED",
            "the Workload's Protocol is no longer the one of this Study's current revision: "
            "a Protocol change is made with `init --new-revision`",
            stage=STAGE,
            details={"expected_protocol_digest": spec["protocol_digest"], "actual_protocol_digest": live["protocol_digest"]},
        )
    return live


def _write_freeze(study, spec: dict, live: dict) -> dict:
    code = environment.code_environment()
    number = spec.get("revision_number", 1)
    record = {
        "kind": "freeze",
        "schema_version": "freeze/1",
        "freeze_id": str(uuid.uuid4()),
        "study_id": spec["study_id"],
        "revision_number": number,
        "protocol_digest": live["protocol_digest"],
        "configuration_digests": live["configuration_digests"],
        "environment": {"python": code["python"], "dependency_lock_sha256": code["dependency_lock"]["sha256"]},
        "code": {"revision": code["code_revision"]["commit"], "dirty": code["code_revision"]["dirty"]},
        "recorded_at": _now(),
    }
    contracts.validate(record)
    artifacts.publish_record(study, freeze_path(number), record, role="freeze")
    return record


def record(study, spec: dict, *, examples_dir=None, attempt_ids=(), assessment_ids=(), comparison_ids=()) -> dict:
    """Append one journal entry for an Exposure, after the freeze record of the current revision (written first if absent).

    The caller holds the Study's writer lock and has finished every refusal that needs no value of `public_check`
    Items; this is called before it computes anything on them.
    """
    live = basis(spec, examples_dir)
    freeze = read_freeze(study, spec.get("revision_number", 1)) or _write_freeze(study, spec, live)
    folder = Path(study) / JOURNAL_DIR
    sequence = (sum(1 for p in folder.iterdir() if p.name.endswith(".json") and not p.name.startswith(".")) if folder.is_dir() else 0) + 1
    entry = {
        "kind": "exposure",
        "schema_version": "exposure/1",
        "entry_id": str(uuid.uuid4()),
        "freeze_id": freeze["freeze_id"],
        "recorded_at": _now(),
        "attempt_ids": sorted(set(attempt_ids)),
        "assessment_ids": sorted(set(assessment_ids)),
        "comparison_ids": sorted(set(comparison_ids)),
    }
    contracts.validate(entry)
    artifacts.publish_record(study, f"{JOURNAL_DIR}/{sequence:06d}-{entry['entry_id']}.json", entry, role="exposure")
    return entry
