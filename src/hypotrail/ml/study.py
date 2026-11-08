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
"""

import shutil
import uuid
from pathlib import Path

from hypotrail.core import artifacts, canonical, contracts, data, lock
from hypotrail.core.errors import InvalidInputError
from hypotrail.core.study import (
    ARTIFACTS_DIR,
    DATASETS_DIR,
    SCRATCH_DIR,
    STUDY_FILE,
    declared_track,
    media_type_of,
    short_id,
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


def _exists(study: Path) -> InvalidInputError:
    return InvalidInputError(
        "STUDY_EXISTS", f"a Study already exists in {study}", stage="study", details={"study": str(study)}
    )


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
            f"Workload {workload!r} declares the Track {track!r}; `init` creates Studies of the {TRACK!r} Track only",
            stage="study",
            details={"workload": workload, "track": track, "supported": [TRACK]},
        )
    declaration = load_declaration(source)
    require_keys(declaration, "data_file", "question", "objective", "limitations")

    study.mkdir(parents=True, exist_ok=True)
    with lock.writer_lock(study):
        if (study / STUDY_FILE).exists():
            raise _exists(study)
        data_path = source / declaration.data_file
        dataset = artifacts.publish_bytes(
            study, f"{DATASETS_DIR}/{data_path.name}", data_path.read_bytes(), media_type=media_type_of(data_path), role="dataset"
        )
        scratch = study / SCRATCH_DIR / "init"
        try:
            write_memberships(source, scratch)
            write_references(source, scratch)
            memberships = artifacts.publish_file(study, scratch / MEMBERSHIPS_NAME, MEMBERSHIPS_PATH, media_type="text/csv", role="memberships")
            references = artifacts.publish_file(study, scratch / REFERENCES_NAME, REFERENCES_PATH, media_type="text/csv", role="references")
        finally:
            shutil.rmtree(study / SCRATCH_DIR, ignore_errors=True)

        protocol = protocol_content(
            declaration,
            dataset_sha256=dataset["sha256"],
            memberships_sha256=memberships["sha256"],
            references_sha256=references["sha256"],
        )
        spec = {
            "kind": "study",
            "schema_version": SPEC_VERSION,
            "study_id": str(uuid.uuid4()),
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
            "artifacts": [
                {"artifact_id": short_id("memberships", memberships["sha256"]), "ref": memberships},
                {"artifact_id": short_id("references", references["sha256"]), "ref": references},
            ],
        }
        spec["revision"] = canonical.digest({key: value for key, value in spec.items() if key not in ("revision", "study_id")})
        contracts.validate(spec)
        artifacts.publish_record(study, STUDY_FILE, spec, role="study_spec")
        return spec
