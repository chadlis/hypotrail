"""`init` for the tool-using agent Track: create a Study that holds the Chinook Protocol.

`init_study` verifies the Workload's data against its lock, keeps a copy of the database in the Study
(an artifact referenced by its digest) and publishes three Study artifacts with an ID each: the
memberships (which Partition each Case belongs to), the References set exactly as the Workload
declares it, and the answer schema the Scorer checks answers against. The StudySpec is written last,
so a Study that was interrupted before that has no `study.json`. The Workload stays where it is
declared: its Configurations can change after the Study exists.

The Protocol digest (`protocol_digest`) is the canonical digest of what binds every Attempt: the
Cases of each Partition by their bytes, the memberships, the References, the answer schema and the
database by their bytes, and the primary Criterion. It holds no Configuration. The primary
Criterion is declared as data by the Workload (`primary_criterion`, ADR 0002; owner decision 1A on
chadlis/hypotrail#9) and becomes the Study's `primary_metric`.

Nothing here imports Inspect, and the database is never opened as a database: it is copied and hashed.
"""

import csv
import io
import uuid
from pathlib import Path

from hypotrail.agentic.declaration import Workload, load_workload
from hypotrail.agentic.partitions import ROLES
from hypotrail.core import artifacts, canonical, contracts, data, lock
from hypotrail.core.errors import InvalidInputError
from hypotrail.core.study import (
    ARTIFACTS_DIR,
    DATASETS_DIR,
    STUDY_FILE,
    media_type_of,
    short_id,
)

TRACK = "tool_using_agent"
DOMAIN = "agentic"
SPEC_VERSION = "study/1"
MEMBERSHIPS_PATH = f"{ARTIFACTS_DIR}/memberships.csv"
ANSWER_SCHEMA_PATH = f"{ARTIFACTS_DIR}/answer-schema.json"
PRIMARY_DIRECTION = "higher_is_better"
PRIMARY_UNIT = "share of Episodes"


def protocol_id(workload: str) -> str:
    return f"{workload}:protocol"


def require_declared(workload: Workload, *keys: str) -> None:
    """Refuse the absence of a key `init` reads and the schema leaves optional."""
    for key in keys:
        if key not in workload.declaration:
            raise InvalidInputError(
                "DECLARATION_INCOMPLETE",
                f"declaration lacks {key!r}",
                stage="declaration",
                details={"key": key, "path": ""},
            )


def memberships_bytes(workload: Workload) -> bytes:
    """The Partition of every Case of the Workload, one line per Case in ID order."""
    rows = sorted((case["case_id"], role) for role in ROLES if role in workload.declaration["cases"] for case in workload.cases(role))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["case_id", "partition"])
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def references_path(workload: Workload) -> Path:
    return workload.directory / workload.declaration["references"]


def protocol_content(workload: Workload, *, dataset_sha256: str) -> dict:
    """What the Protocol is made of, from the bytes of the Workload's files."""
    declaration = workload.declaration
    return {
        "track": TRACK,
        "cases_sha256": {role: canonical.sha256_hex(workload.cases_path(role).read_bytes()) for role in ROLES if role in declaration["cases"]},
        "memberships_sha256": canonical.sha256_hex(memberships_bytes(workload)),
        "references_sha256": canonical.sha256_hex(references_path(workload).read_bytes()),
        "answer_schema_sha256": canonical.sha256_hex(workload.answer_schema_path.read_bytes()),
        "dataset_sha256": dataset_sha256,
        "primary_metric": {"id": declaration["primary_criterion"], "direction": PRIMARY_DIRECTION},
    }


def _exists(study: Path) -> InvalidInputError:
    return InvalidInputError("STUDY_EXISTS", f"a Study already exists in {study}", stage="study", details={"study": str(study)})


def init_study(workload_name: str, study: Path, examples_dir: Path | None = None) -> dict:
    """Create the Study `study` for the Chinook-like Workload `workload_name` of `examples_dir`; return its StudySpec."""
    study = Path(study)
    examples = Path(examples_dir) if examples_dir is not None else data.default_examples_dir()
    if (study / STUDY_FILE).exists():
        with lock.writer_lock(study):  # a Study that has a writer answers with the lock first
            raise _exists(study)
    # Nothing is created before the bytes match the lock (T01 at this entry point).
    data.verify_workloads(examples, [workload_name])
    workload = load_workload(examples / workload_name)
    require_declared(workload, "question", "objective", "limitations", "primary_criterion", "answer_schema")

    study.mkdir(parents=True, exist_ok=True)
    with lock.writer_lock(study):
        if (study / STUDY_FILE).exists():
            raise _exists(study)
        database = workload.database_path
        dataset = artifacts.publish_bytes(
            study, f"{DATASETS_DIR}/{database.name}", database.read_bytes(), media_type="application/vnd.sqlite3", role="dataset"
        )
        memberships = artifacts.publish_bytes(study, MEMBERSHIPS_PATH, memberships_bytes(workload), media_type="text/csv", role="memberships")
        references_file = references_path(workload)
        references = artifacts.publish_bytes(
            study,
            f"{ARTIFACTS_DIR}/{references_file.name}",
            references_file.read_bytes(),
            media_type="application/jsonl",
            role="references",
        )
        schema = artifacts.publish_bytes(
            study, ANSWER_SCHEMA_PATH, workload.answer_schema_path.read_bytes(), media_type=media_type_of(ANSWER_SCHEMA_PATH), role="answer_schema"
        )
        protocol = protocol_content(workload, dataset_sha256=dataset["sha256"])
        spec = {
            "kind": "study",
            "schema_version": SPEC_VERSION,
            "study_id": str(uuid.uuid4()),
            "revision": "0" * 64,
            "question": workload.declaration["question"],
            "domain": DOMAIN,
            "objective": workload.declaration["objective"],
            "protocol_id": protocol_id(workload_name),
            "protocol_digest": canonical.digest(protocol),
            "dataset_refs": [dataset],
            "primary_metric": {"id": workload.declaration["primary_criterion"], "direction": PRIMARY_DIRECTION, "unit": PRIMARY_UNIT},
            "limitations": list(workload.declaration["limitations"]),
            "workload": workload_name,
            "artifacts": [
                {"artifact_id": short_id("memberships", memberships["sha256"]), "ref": memberships},
                {"artifact_id": short_id("references", references["sha256"]), "ref": references},
                {"artifact_id": short_id("answer-schema", schema["sha256"]), "ref": schema},
            ],
        }
        spec["revision"] = canonical.digest({key: value for key, value in spec.items() if key not in ("revision", "study_id")})
        contracts.validate(spec)
        artifacts.publish_record(study, STUDY_FILE, spec, role="study_spec")
        return spec
