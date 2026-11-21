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

`new_revision` adds a revision to an existing Study (`init --study DIR --new-revision`), for example after a
corrected References file: `hypotrail.core.revisions` keeps the earlier revision and its artifacts as they
were and publishes what changed beside them.

Nothing here imports Inspect, and the database is never opened as a database: it is copied and hashed.
"""

import csv
import io
import uuid
from pathlib import Path

from hypotrail.agentic.declaration import Workload, load_workload
from hypotrail.agentic.partitions import ROLES
from hypotrail.core import artifacts, canonical, contracts, data, exposure, lock, revisions, write_journal
from hypotrail.core import study as layout
from hypotrail.core.errors import InvalidInputError
from hypotrail.core.study import (
    ARTIFACTS_DIR,
    DATASETS_DIR,
    STUDY_FILE,
    media_type_of,
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


def dataset_sha256(spec: dict) -> str:
    """The dataset digest a Protocol is computed from after `init`: the Study's own copy, never the live database.

    `import agent` and `assess` never open the Chinook file (#69). The copy is read back against this digest by
    every command; `init`, `init --new-revision` and `data verify` are what read the live file.
    """
    return layout.dataset_ref(spec)["sha256"]


def freeze_basis(spec: dict, source: Path) -> dict:
    """What a freeze record takes of the Workload as it is declared now (`hypotrail.core.exposure`).

    The Protocol digest is computed as `import agent` computes it, from the bytes of the Workload's files. A
    Configuration's digest covers what it declares and the exact system text it resolves to, so a changed
    base Configuration changes the digest of the one that extends it. The database part of the Protocol digest is
    the Study's own copy (`dataset_source` says so in the freeze record): the live file is not opened.
    """
    workload = load_workload(source)
    protocol = protocol_content(workload, dataset_sha256=dataset_sha256(spec))
    declared = workload.declaration.get("configurations", {})
    return {
        "protocol_digest": canonical.digest(protocol),
        "dataset_source": "study_copy",
        "configuration_digests": {
            name: exposure.configuration_digest(declared[name], workload.system_text(name)) for name in sorted(declared)
        },
    }


def live_basis(examples_dir: Path | None = None):
    """A function of the Study's spec that returns `freeze_basis` of that Study's Workload under `examples_dir`.

    `hypotrail.core.exposure` takes it instead of importing the Track and calls it with the spec it read under the
    writer lock; it reads the Workload only when called.
    """

    def basis(spec: dict) -> dict:
        examples = data.resolve_examples_dir(examples_dir)
        return freeze_basis(spec, examples / spec["workload"])

    return basis


def _exists(study: Path) -> InvalidInputError:
    return InvalidInputError("STUDY_EXISTS", f"a Study already exists in {study}", stage="study", details={"study": str(study)})


def _write_spec(study: Path, workload_name: str, workload: Workload, previous: dict | None) -> dict:
    """Publish the Protocol artifacts and the StudySpec of the first revision, or of the one after `previous`.

    The StudySpec is written last. An artifact the earlier revision already holds with the same bytes is
    carried over; one whose bytes changed is published beside it (`hypotrail.core.revisions`).
    """
    database = workload.database_path
    references_file = references_path(workload)
    database_bytes = database.read_bytes()
    protocol = protocol_content(workload, dataset_sha256=canonical.sha256_hex(database_bytes))
    if previous is not None:
        revisions.refuse_unchanged(previous, canonical.digest(protocol))
    write_journal.begin()  # the first write of `init` and of `init --new-revision`
    before = {e["ref"]["role"]: e for e in previous["artifacts"]} if previous is not None else {}
    dataset, _ = revisions.place(
        study,
        layout.dataset_ref(previous) if previous is not None else None,
        f"{DATASETS_DIR}/{database.name}",
        database_bytes,
        media_type="application/vnd.sqlite3",
        role="dataset",
    )
    memberships = revisions.artifact_entry(
        study, "memberships", before.get("memberships"), MEMBERSHIPS_PATH, memberships_bytes(workload), media_type="text/csv", role="memberships"
    )
    references = revisions.artifact_entry(
        study,
        "references",
        before.get("references"),
        f"{ARTIFACTS_DIR}/{references_file.name}",
        references_file.read_bytes(),
        media_type="application/jsonl",
        role="references",
    )
    schema = revisions.artifact_entry(
        study,
        "answer-schema",
        before.get("answer_schema"),
        ANSWER_SCHEMA_PATH,
        workload.answer_schema_path.read_bytes(),
        media_type=media_type_of(ANSWER_SCHEMA_PATH),
        role="answer_schema",
    )
    spec = {
        "kind": "study",
        "schema_version": SPEC_VERSION,
        "study_id": previous["study_id"] if previous is not None else str(uuid.uuid4()),
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
        "artifacts": [memberships, references, schema],
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
    write_journal.wrote("revision", spec["revision"])
    return spec


def init_study(workload_name: str, study: Path, examples_dir: Path | None = None) -> dict:
    """Create the Study `study` for the Chinook-like Workload `workload_name` of `examples_dir`; return its StudySpec."""
    study = Path(study)
    examples = data.resolve_examples_dir(examples_dir)
    if (study / STUDY_FILE).exists():
        with lock.writer_lock(study):  # a Study that has a writer answers with the lock first
            raise _exists(study)
    # Nothing is created before the bytes match the lock (T01 at this entry point).
    data.verify_workloads(examples, [workload_name])
    workload = load_workload(examples / workload_name)
    require_declared(workload, "question", "objective", "limitations", "primary_criterion", "answer_schema")

    study.mkdir(parents=True, exist_ok=True)
    with lock.writer_lock(study), write_journal.writing(study, "init"):
        if (study / STUDY_FILE).exists():
            raise _exists(study)
        return _write_spec(study, workload_name, workload, None)


def new_revision(study: Path, examples_dir: Path | None = None, *, read_sequence: int | None = None) -> dict:
    """Add a revision to the Study `study`: the Protocol its Workload declares now; return the new StudySpec.

    The Workload is the one the Study names, read again from `examples_dir`. A Protocol equal to the
    current revision's is refused (`PROTOCOL_UNCHANGED`). Holds the Study's writer lock for the whole command.
    """
    study = Path(study)
    write_journal.require_valid_read_sequence(read_sequence, "init")
    layout.read_spec(study)  # a folder that is no Study is refused before a lock file is created in it
    with lock.writer_lock(study), write_journal.writing(study, "init --new-revision"):
        write_journal.require_current(study, read_sequence)
        previous = layout.read_spec(study)
        layout.require_domain(previous, DOMAIN, "init --new-revision")
        examples = data.resolve_examples_dir(examples_dir)
        workload_name = previous["workload"]
        data.verify_workloads(examples, [workload_name])  # T01 at this entry point: before anything is written
        workload = load_workload(examples / workload_name)
        require_declared(workload, "question", "objective", "limitations", "primary_criterion", "answer_schema")
        return _write_spec(study, workload_name, workload, previous)
