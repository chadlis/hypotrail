"""Revisions of a Study: a Protocol change is a new StudySpec revision inside the same Study.

A Study holds one frozen Protocol per revision (owner decision 2A on chadlis/hypotrail#9, 2026-11-20).
A corrected References set, a corrected data file or any other change of what the Protocol freezes is
added with `init --study DIR --new-revision`; it never edits what an earlier revision references.

```
study.json                        the StudySpec of the current revision
revisions/<n>/study.json          the StudySpec of revision n, written once and never changed
artifacts/<stem>-<sha16>.<ext>    a Protocol artifact whose bytes changed, beside the earlier one
```

`study.json` always holds the current revision, so every command keeps reading one file. A revision's
StudySpec is copied into `revisions/` when the next revision is made, so the earlier ones stay readable
byte for byte. A Protocol artifact whose bytes did not change is carried over as it is (same path, same
digest, same ID, same version); one that changed is published beside the earlier one under a path that
names its digest, with the next version number. The steps run in this order, so a writer killed
between two of them is completed by running the command again: the new artifacts, the copy of the
current StudySpec, the new revision's StudySpec, and last the replacement of `study.json`.

Not built here, and where it attaches (chadlis/hypotrail#73): each revision's freeze record belongs
beside its StudySpec, in `revisions/<n>/`; the Exposure journal is what `check_informed_mark` reads to
mark a revision created after the Study's first Exposure.
"""

from pathlib import Path, PurePosixPath

from hypotrail.core import artifacts, canonical, contracts
from hypotrail.core import study as layout
from hypotrail.core.errors import InvalidInputError

REVISIONS_DIR = "revisions"


def revision_number(spec: dict) -> int:
    """The number of a revision: 1 for the first, and for a StudySpec written before revisions existed."""
    return spec.get("revision_number", 1)


def identity(spec: dict) -> dict:
    """What an Assessment records of the revision whose Protocol it applied."""
    return {"number": revision_number(spec), "revision": spec["revision"], "protocol_digest": spec["protocol_digest"]}


def version_of(entry: dict) -> int:
    return entry.get("version", 1)


def revision_path(number: int) -> str:
    return f"{REVISIONS_DIR}/{number}/{layout.STUDY_FILE}"


def revision_specs(study) -> list:
    """Every revision's StudySpec, the current one included, in order of revision number."""
    study = Path(study)
    by_number = {}
    folder = study / REVISIONS_DIR
    if folder.is_dir():
        for candidate in folder.iterdir():
            if candidate.name.isdigit() and (candidate / layout.STUDY_FILE).is_file():
                spec = layout.read_record(study, revision_path(int(candidate.name)))
                by_number[revision_number(spec)] = spec
    current = layout.read_spec(study)
    by_number[revision_number(current)] = current
    return [by_number[number] for number in sorted(by_number)]


def place(study, previous_ref, relative, data: bytes, *, media_type: str, role: str) -> tuple:
    """(ArtifactRef, changed) of a Protocol artifact whose bytes are `data`.

    With no earlier artifact (the first revision) it is published at `relative`. When the earlier one holds
    the same bytes it is carried over untouched. Otherwise the new bytes are published beside it, under a
    path that names their digest: an earlier artifact is never replaced.
    """
    if previous_ref is None:
        return artifacts.publish_bytes(study, relative, data, media_type=media_type, role=role), False
    sha256 = canonical.sha256_hex(data)
    if previous_ref["sha256"] == sha256:
        return previous_ref, False
    path = PurePosixPath(relative)
    named = path.with_name(f"{path.stem}-{sha256[:16]}{path.suffix}")
    return artifacts.publish_bytes(study, named, data, media_type=media_type, role=role), True


def artifact_entry(study, prefix: str, previous_entry, relative, data: bytes, *, media_type: str, role: str) -> dict:
    """The StudySpec entry of one Protocol artifact, carried over or published as `place` says."""
    ref, changed = place(study, previous_entry["ref"] if previous_entry else None, relative, data, media_type=media_type, role=role)
    version = 1 if previous_entry is None else version_of(previous_entry) + (1 if changed else 0)
    return {"artifact_id": layout.short_id(prefix, ref["sha256"]), "ref": ref, "version": version}


def refuse_unchanged(previous: dict, protocol_digest: str) -> None:
    """A revision that freezes the Protocol the current one already freezes is no revision."""
    if protocol_digest == previous["protocol_digest"]:
        raise InvalidInputError(
            "PROTOCOL_UNCHANGED",
            f"the Workload's Protocol is the one revision {revision_number(previous)} already holds: there is nothing to add",
            stage="study",
            details={"protocol_digest": protocol_digest, "revision_number": revision_number(previous)},
        )


def check_informed_mark(study) -> dict:
    """The fields that mark a new revision as informed by `public_check`; none until the Exposure journal exists.

    #73 replaces this body: it returns `{"check_informed": True}` when the Study already has its first
    Exposure. Today no Assessment, Comparison or count touches `public_check` Items, so no Study has one.
    """
    return {}


def next_fields(study, previous: dict) -> dict:
    """The fields of a StudySpec that make it the revision after `previous`."""
    return {
        "revision_number": revision_number(previous) + 1,
        "previous_revision": previous["revision"],
        **check_informed_mark(study),
    }


def publish(study, previous: dict, spec: dict) -> None:
    """Keep `previous` readable, publish `spec` as the next revision, then make it the current one."""
    study = Path(study)
    current_bytes = (study / layout.STUDY_FILE).read_bytes()
    artifacts.publish_bytes(study, revision_path(revision_number(previous)), current_bytes, media_type="application/json", role="study_spec")
    contracts.validate(spec)
    artifacts.publish_record(study, revision_path(revision_number(spec)), spec, role="study_spec")
    artifacts.replace_bytes(study, layout.STUDY_FILE, canonical.dumps(spec))
