"""`init` for the temporal regression Track: create a Study that holds the Bike Protocol.

`init_study` verifies the Workload's data against its lock, keeps a copy of the dataset in the Study
(an artifact referenced by its digest), derives the population and the References set with the
Track's own writers, publishes them as Study artifacts with an ID each, and writes the StudySpec
last, so a Study that was interrupted before that has no `study.json`. The Workload stays where it
is declared: Configurations can change after the Study exists.

The Protocol digest (`protocol_digest`) is the canonical digest of what binds every Attempt: the
Partitions and their ranges, the population (memberships) and the References by their bytes, the
data file by its bytes, the columns and the rules on when information is available
(`period_k`, the forbidden and the allowed target features) and the primary metric. It does not hold
a Configuration: changing a Configuration never changes it.

`new_revision` adds a revision to an existing Study (`init --study DIR --new-revision`): it derives the
Protocol the Workload declares now, and `hypotrail.core.revisions` keeps the earlier revision and its
artifacts as they were and publishes what changed beside them.
"""

import tempfile
import uuid
from pathlib import Path

from hypotrail.core import artifacts, canonical, contracts, data, lock, revisions
from hypotrail.core import study as layout
from hypotrail.core.errors import InvalidInputError
from hypotrail.core.study import (
    ARTIFACTS_DIR,
    DATASETS_DIR,
    STUDY_FILE,
    declared_track,
    media_type_of,
)
from hypotrail.ml.declaration import Declaration, load_declaration, plain, require_keys
from hypotrail.ml.memberships import MEMBERSHIPS_NAME, write_memberships
from hypotrail.ml.metrics import DIRECTION, PRIMARY
from hypotrail.ml.references import REFERENCES_NAME, write_references

TRACK = "temporal_regression"
DOMAIN = "regression"
MODE = "native_ml"
SPEC_VERSION = "study/1"
MEMBERSHIPS_PATH = f"{ARTIFACTS_DIR}/{MEMBERSHIPS_NAME}"
REFERENCES_PATH = f"{ARTIFACTS_DIR}/{REFERENCES_NAME}"


def protocol_id(workload: str) -> str:
    return f"{workload}:protocol"


def protocol_content(declaration: Declaration, *, dataset_sha256: str, memberships_sha256: str, references_sha256: str) -> dict:
    """What the Protocol is made of, from the typed declaration and the bytes of the Study artifacts."""
    require_keys(
        declaration,
        "data_file", "id_prefix", "date_column", "target_column", "target_unit",
        "period_k", "forbidden_features", "allowed_target_features",
    )
    return {
        "track": TRACK,
        "partitions": {p.name: [p.first.isoformat(), p.last.isoformat()] for p in declaration.partitions},
        "id_prefix": declaration.id_prefix,
        "date_column": declaration.date_column,
        "target_column": declaration.target_column,
        "target_unit": declaration.target_unit,
        "availability": {
            "period_k": declaration.period_k.days,
            "forbidden_features": sorted(declaration.forbidden_features),
            "allowed_target_features": sorted(plain(declaration.allowed_target_features), key=lambda f: f["name"]),
        },
        "primary_metric": {"id": PRIMARY, "direction": DIRECTION},
        "dataset_sha256": dataset_sha256,
        "population_sha256": memberships_sha256,
        "references_sha256": references_sha256,
    }


def freeze_basis(spec: dict, source: Path) -> dict:
    """What a freeze record takes of the Workload as it is declared now (`hypotrail.core.exposure`).

    The Protocol digest is computed as `run ml` computes it (the declaration, the dataset's bytes and the
    Study's own population and References); a Configuration's digest is the one of its declared content,
    which is what an Attempt records as `effective_config.configuration.declared`.
    """
    declaration = load_declaration(source)
    require_keys(declaration, "data_file", "configurations")
    by_role = {entry["ref"]["role"]: entry["ref"] for entry in spec["artifacts"]}
    protocol = protocol_content(
        declaration,
        dataset_sha256=data.sha256_file(source / declaration.data_file),
        memberships_sha256=by_role["memberships"]["sha256"],
        references_sha256=by_role["references"]["sha256"],
    )
    return {
        "protocol_digest": canonical.digest(protocol),
        "configuration_digests": {name: canonical.digest(plain(c)) for name, c in sorted(declaration.configurations.items())},
    }


def live_basis(spec: dict, examples_dir: Path | None = None):
    """A function with no argument that returns `freeze_basis` of this Study's Workload under `examples_dir`.

    `hypotrail.core.exposure` takes it instead of importing the Track; it reads the Workload only when called.
    """

    def basis() -> dict:
        examples = Path(examples_dir) if examples_dir is not None else data.default_examples_dir()
        return freeze_basis(spec, examples / spec["workload"])

    return basis


def _exists(study: Path) -> InvalidInputError:
    return InvalidInputError(
        "STUDY_EXISTS", f"a Study already exists in {study}", stage="study", details={"study": str(study)}
    )


def _derived_bytes(source: Path) -> tuple:
    """The population and the References set the Track's own writers derive from the Workload, as bytes."""
    with tempfile.TemporaryDirectory() as scratch:
        write_memberships(source, Path(scratch))
        write_references(source, Path(scratch))
        return (Path(scratch) / MEMBERSHIPS_NAME).read_bytes(), (Path(scratch) / REFERENCES_NAME).read_bytes()


def _write_spec(study: Path, workload: str, source: Path, declaration: Declaration, previous: dict | None) -> dict:
    """Publish the Protocol artifacts and the StudySpec of the first revision, or of the one after `previous`.

    The StudySpec is written last. An artifact the earlier revision already holds with the same bytes is
    carried over; one whose bytes changed is published beside it (`hypotrail.core.revisions`).
    """
    data_path = source / declaration.data_file
    dataset_bytes = data_path.read_bytes()
    memberships_bytes, references_bytes = _derived_bytes(source)
    protocol = protocol_content(
        declaration,
        dataset_sha256=canonical.sha256_hex(dataset_bytes),
        memberships_sha256=canonical.sha256_hex(memberships_bytes),
        references_sha256=canonical.sha256_hex(references_bytes),
    )
    if previous is not None:
        revisions.refuse_unchanged(previous, canonical.digest(protocol))
    before = {e["ref"]["role"]: e for e in previous["artifacts"]} if previous is not None else {}
    dataset, _ = revisions.place(
        study,
        previous["dataset_refs"][0] if previous is not None else None,
        f"{DATASETS_DIR}/{data_path.name}",
        dataset_bytes,
        media_type=media_type_of(data_path),
        role="dataset",
    )
    memberships = revisions.artifact_entry(
        study, "memberships", before.get("memberships"), MEMBERSHIPS_PATH, memberships_bytes, media_type="text/csv", role="memberships"
    )
    references = revisions.artifact_entry(
        study, "references", before.get("references"), REFERENCES_PATH, references_bytes, media_type="text/csv", role="references"
    )
    spec = {
        "kind": "study",
        "schema_version": SPEC_VERSION,
        "study_id": previous["study_id"] if previous is not None else str(uuid.uuid4()),
        "revision": "0" * 64,
        "question": declaration.question,
        "domain": DOMAIN,
        "objective": declaration.objective,
        "protocol_id": protocol_id(workload),
        "protocol_digest": canonical.digest(protocol),
        "dataset_refs": [dataset],
        "primary_metric": {"id": PRIMARY, "direction": DIRECTION, "unit": declaration.target_unit},
        "limitations": list(declaration.limitations),
        "workload": workload,
        "artifacts": [memberships, references],
        "revision_number": 1,
    }
    if previous is not None:
        spec.update(revisions.next_fields(study, previous))
    spec["revision"] = canonical.digest({key: value for key, value in spec.items() if key not in ("revision", "study_id")})
    contracts.validate(spec)
    if previous is None:
        artifacts.publish_record(study, STUDY_FILE, spec, role="study_spec")
    else:
        revisions.publish(study, previous, spec)
    return spec


def init_study(workload: str, study: Path, examples_dir: Path | None = None) -> dict:
    """Create the Study `study` for the Workload `workload` of `examples_dir`; return its StudySpec."""
    study = Path(study)
    examples = Path(examples_dir) if examples_dir is not None else data.default_examples_dir()
    if (study / STUDY_FILE).exists():
        with lock.writer_lock(study):  # a Study that has a writer answers with the lock first
            raise _exists(study)
    # Nothing is created before the bytes match the lock (T01 at this entry point).
    data.verify_workloads(examples, [workload])
    source = examples / workload
    track = declared_track(source)
    if track != TRACK:
        raise InvalidInputError(
            "WORKLOAD_TRACK_NOT_SUPPORTED",
            f"Workload {workload!r} declares the Track {track!r}; `init` creates Studies of the {TRACK!r} and 'tool_using_agent' Tracks only",
            stage="study",
            details={"workload": workload, "track": track, "supported": sorted([TRACK, "tool_using_agent"])},
        )
    declaration = load_declaration(source)
    require_keys(declaration, "data_file", "question", "objective", "limitations")

    study.mkdir(parents=True, exist_ok=True)
    with lock.writer_lock(study):
        if (study / STUDY_FILE).exists():
            raise _exists(study)
        return _write_spec(study, workload, source, declaration, None)


def new_revision(study: Path, examples_dir: Path | None = None) -> dict:
    """Add a revision to the Study `study`: the Protocol its Workload declares now; return the new StudySpec.

    The Workload is the one the Study names, read again from `examples_dir`. A Protocol equal to the
    current revision's is refused (`PROTOCOL_UNCHANGED`). Holds the Study's writer lock for the whole command.
    """
    study = Path(study)
    layout.read_spec(study)  # a folder that is no Study is refused before a lock file is created in it
    with lock.writer_lock(study):
        previous = layout.read_spec(study)
        layout.require_domain(previous, DOMAIN, "init --new-revision")
        examples = Path(examples_dir) if examples_dir is not None else data.default_examples_dir()
        workload = previous["workload"]
        data.verify_workloads(examples, [workload])  # T01 at this entry point: before anything is written
        source = examples / workload
        declaration = load_declaration(source)
        require_keys(declaration, "data_file", "question", "objective", "limitations")
        return _write_spec(study, workload, source, declaration, previous)
