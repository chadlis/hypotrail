"""`init` for the tool-using agent Track: create a Study that holds the Chinook Protocol.

`init_study` verifies the Workload's data against its lock, keeps a copy of the database in the Study
(an artifact referenced by its digest) and publishes three Study artifacts with an ID each: the
memberships (which Partition each Case belongs to), the References set exactly as the Workload
declares it, and the answer schema the Scorer checks answers against. The StudySpec is written last,
so a Study that was interrupted before that has no `study.json`. The Workload stays where it is
declared: its Configurations can change after the Study exists.

A Workload whose data lives outside the repository declares no `database`: the Study keeps a copy of its
data manifest instead (role `data_manifest`), the Protocol holds that copy's digest as
`data_manifest_sha256` in place of `dataset_sha256`, and the answer schema is published only when the
Workload declares one. A declared scoring config is checked against `text-facts.schema.json`, the one scoring
config a Scorer reads, and refused `SCORING_CONFIG_INVALID` before anything is written.

The Protocol digest (`protocol_digest`) is the canonical digest of what binds every Attempt: the
Cases of each Partition by their bytes, the memberships, the References, the answer schema and the
database by their bytes, the primary Criterion, and the `resampling` the Workload declares, when it
declares one. It holds no Configuration. The primary
Criterion is declared as data by the Workload (`primary_criterion`, ADR 0002; owner decision 1A on
chadlis/hypotrail#9) and becomes the Study's `primary_metric`.

`new_revision` adds a revision to an existing Study (`init --study DIR --new-revision`), for example after a
corrected References file: `hypotrail.core.revisions` keeps the earlier revision and its artifacts as they
were and publishes what changed beside them.

Nothing here imports Inspect, and the database is never opened as a database: it is copied and hashed.
"""

import csv
import io
import json
import uuid
from pathlib import Path

from hypotrail.agentic.declaration import Workload, load_workload, read_json
from hypotrail.agentic.partitions import ROLES
from hypotrail.core import artifacts, canonical, contracts, data, exposure, revisions, study_write
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
SCORING_CONFIG_PATH = f"{ARTIFACTS_DIR}/scoring-config.json"
DATASET_ROLE = "dataset"
MANIFEST_ROLE = "data_manifest"
PRIMARY_DIRECTION = "higher_is_better"
PRIMARY_UNIT = "share of Episodes"
# What `run agent` and `import agent` say when the Protocol check refuses (`hypotrail.core.protocol_check`).
PROTOCOL_CHANGED_MESSAGE = "the Workload's Protocol is no longer the one of this Study (Cases, References, answer schema, database or primary Criterion)"


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


def required_by_init(workload: Workload) -> tuple:
    """The keys `init` reads: the answer schema only for a Workload that declares a database."""
    keys = ("question", "objective", "limitations", "primary_criterion")
    return (*keys, "answer_schema") if declares_database(workload) else keys


def _reference_texts(workload: Workload) -> dict:
    """{case_id: reference_text} of the Workload's References file, for the records that hold one."""
    texts = {}
    for line in references_path(workload).read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(record, dict) and isinstance(record.get("case_id"), str) and "reference_text" in record:
            texts[record["case_id"]] = record["reference_text"]
    return texts


def _history_refusal(code, message, case_id, turn, **details):
    return InvalidInputError(code, message, stage="declaration", details={"case_id": case_id, "turn": turn, **details})


def check_histories(workload: Workload) -> None:
    """Refuse a scripted history that would show a Case its own Reference, or that is not the Reference text it names.

    D-154 on chadlis/hypotrail#75, item 1: "A later turn may receive a scripted history built from earlier turns' Reference
    texts, as frozen Case input that the Protocol declares. Its own Reference is never shown." A turn naming the Case itself
    in `from_case`, or holding the Case's own `reference_text`, is HISTORY_SHOWS_OWN_REFERENCE; a turn whose `from_case`
    names no Case of the Workload, a Case of another Partition, a Case after this one in its Cases file, or whose text
    differs from that Case's `reference_text`, is HISTORY_SOURCE_MISMATCH.
    """
    by_role = {role: workload.cases(role) for role in ROLES if role in workload.declaration["cases"]}
    cases = [case for role_cases in by_role.values() for case in role_cases]
    if not any("history" in case for case in cases):
        return
    texts = _reference_texts(workload)
    # (Partition, position in its Cases file) of every Case: a source must be in the same Partition and come before.
    place = {case["case_id"]: (role, position) for role, role_cases in by_role.items() for position, case in enumerate(role_cases)}
    for case in cases:
        case_id = case["case_id"]
        role, position = place[case_id]
        for turn_number, turn in enumerate(case.get("history", [])):
            source = turn.get("from_case")
            if source == case_id or (case_id in texts and turn["content"] == texts[case_id]):
                raise _history_refusal(
                    "HISTORY_SHOWS_OWN_REFERENCE", f"the history of Case {case_id} shows its own Reference (turn {turn_number})", case_id, turn_number
                )
            if source is None:
                continue
            earlier = source in place and place[source][0] == role and place[source][1] < position
            if not earlier or turn["content"] != texts.get(source):
                raise _history_refusal(
                    "HISTORY_SOURCE_MISMATCH",
                    f"turn {turn_number} of the history of Case {case_id} is not the reference_text of an earlier Case {source!r} of its Partition",
                    case_id,
                    turn_number,
                    from_case=source,
                )


TEXT_FACTS_SCHEMA = "text-facts.schema.json"


def check_scoring_config(workload: Workload) -> None:
    """Refuse a declared scoring config that is not `text-facts-config/1`, the one scoring config a Scorer reads (`text_facts_v1`)."""
    if "scoring_config" not in workload.declaration:
        return
    file = workload.declaration["scoring_config"]
    config = read_json(scoring_config_path(workload), stage="declaration", noun="scoring config", key="scoring_config")
    fault = data.schema_fault(TEXT_FACTS_SCHEMA, config)
    if fault is not None:
        path, message = fault
        raise InvalidInputError(
            "SCORING_CONFIG_INVALID",
            f"the scoring config {file} does not match {TEXT_FACTS_SCHEMA} at {path or 'its root'}: {message}",
            stage="declaration",
            details={"file": file, "path": path, "message": message},
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


def declares_database(workload: Workload) -> bool:
    """Whether the Workload's data is a database it declares; otherwise its data manifest declares it."""
    return "database" in workload.declaration


def manifest_path(workload: Workload) -> Path:
    return workload.directory / data.MANIFEST_NAME


def protocol_content(workload: Workload, *, dataset_sha256: str) -> dict:
    """What the Protocol is made of, from the bytes of the Workload's files.

    `dataset_sha256` is the digest of the database, or of the data manifest when the Workload declares no database.
    A Workload that declares neither a database nor an answer schema has no `answer_schema_sha256`, and only one that declares a
    `scoring_config` has a `scoring_config_sha256`, so a Workload with a database and an answer schema and no
    scoring config, as Chinook is, keeps the keys it always had.
    """
    declaration = workload.declaration
    content = {
        "track": TRACK,
        "cases_sha256": {role: canonical.sha256_hex(workload.cases_path(role).read_bytes()) for role in ROLES if role in declaration["cases"]},
        "memberships_sha256": canonical.sha256_hex(memberships_bytes(workload)),
        "references_sha256": canonical.sha256_hex(references_path(workload).read_bytes()),
    }
    if "answer_schema" in declaration or declares_database(workload):  # with a database, an absent one is ANSWER_SCHEMA_NOT_DECLARED
        content["answer_schema_sha256"] = canonical.sha256_hex(workload.answer_schema_path.read_bytes())
    if "scoring_config" in declaration:
        content["scoring_config_sha256"] = canonical.sha256_hex(scoring_config_path(workload).read_bytes())
    content["dataset_sha256" if declares_database(workload) else "data_manifest_sha256"] = dataset_sha256
    content["primary_metric"] = {"id": declaration["primary_criterion"], "direction": PRIMARY_DIRECTION}
    if "resampling" in declaration:  # never a null: a Workload without it keeps the digest it had before the key existed
        content["resampling"] = declaration["resampling"]
    return content


def scoring_config_path(workload: Workload) -> Path:
    return workload.directory / workload.declaration["scoring_config"]


def data_ref(spec: dict) -> dict:
    """The Study's own copy of the Workload's data: its database (role `dataset`) or its data manifest (role `data_manifest`)."""
    return next(ref for ref in spec["dataset_refs"] if ref["role"] in (DATASET_ROLE, MANIFEST_ROLE))


def dataset_sha256(spec: dict) -> str:
    """The data digest a Protocol is computed from after `init`: the Study's own copy, never the live database.

    `import agent` and `assess` never open the Chinook file (#69). The copy is read back against this digest by
    every command; `init`, `init --new-revision` and `data verify` are what read the live file. For a Workload
    whose data lives outside the repository, the copy is of its data manifest.
    """
    return data_ref(spec)["sha256"]


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


def _write_spec(study: Path, workload_name: str, workload: Workload, previous: dict | None, write) -> dict:
    """Publish the Protocol artifacts and the StudySpec of the first revision, or of the one after `previous`.

    The StudySpec is written last. An artifact the earlier revision already holds with the same bytes is
    carried over; one whose bytes changed is published beside it (`hypotrail.core.revisions`).
    """
    if declares_database(workload):
        data_file, media_type, role = workload.database_path, "application/vnd.sqlite3", DATASET_ROLE
    else:
        data_file, media_type, role = manifest_path(workload), "application/json", MANIFEST_ROLE
    references_file = references_path(workload)
    data_bytes = data_file.read_bytes()
    protocol = protocol_content(workload, dataset_sha256=canonical.sha256_hex(data_bytes))
    if previous is not None:
        revisions.refuse_unchanged(previous, canonical.digest(protocol))
    write.begin()  # the first write of `init` and of `init --new-revision`
    before = {e["ref"]["role"]: e for e in previous["artifacts"]} if previous is not None else {}
    dataset, _ = revisions.place(
        study,
        next((ref for ref in previous["dataset_refs"] if ref["role"] == role), None) if previous is not None else None,
        f"{DATASETS_DIR}/{data_file.name}",
        data_bytes,
        media_type=media_type,
        role=role,
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
    entries = [memberships, references]
    if "scoring_config" in workload.declaration:
        entries.append(
            revisions.artifact_entry(
                study,
                "scoring-config",
                before.get("scoring_config"),
                SCORING_CONFIG_PATH,
                scoring_config_path(workload).read_bytes(),
                media_type="application/json",
                role="scoring_config",
            )
        )
    if "answer_schema" in workload.declaration:
        entries.append(
            revisions.artifact_entry(
                study,
                "answer-schema",
                before.get("answer_schema"),
                ANSWER_SCHEMA_PATH,
                workload.answer_schema_path.read_bytes(),
                media_type=media_type_of(ANSWER_SCHEMA_PATH),
                role="answer_schema",
            )
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
        "artifacts": entries,
        "revision_number": 1,
    }
    if "resampling" in workload.declaration:
        spec["resampling"] = workload.declaration["resampling"]
    if previous is not None:
        spec.update(revisions.next_fields(study, previous))
    spec["revision"] = canonical.digest({key: value for key, value in spec.items() if key not in ("revision", "study_id")})
    contracts.validate(spec)
    if previous is None:
        artifacts.publish_record(study, STUDY_FILE, spec, role="study_spec")
    else:
        revisions.publish(study, previous, spec)
    write.wrote(study_write.REVISION, spec["revision"])
    return spec


def init_study(workload_name: str, study: Path, examples_dir: Path | None = None) -> dict:
    """Create the Study `study` for the Chinook-like Workload `workload_name` of `examples_dir`; return its StudySpec."""
    study = Path(study)
    examples = data.resolve_examples_dir(examples_dir)
    if (study / STUDY_FILE).exists():
        with study_write.locked(study, study_write.INIT):  # a Study that has a writer answers with the lock first
            raise _exists(study)
    # Nothing is created before the bytes match the lock (T01 at this entry point).
    data.verify_workloads(examples, [workload_name])
    workload = load_workload(examples / workload_name)
    require_declared(workload, *required_by_init(workload))
    check_histories(workload)
    check_scoring_config(workload)

    study.mkdir(parents=True, exist_ok=True)
    with study_write.locked(study, study_write.INIT) as write:
        if (study / STUDY_FILE).exists():
            raise _exists(study)
        return _write_spec(study, workload_name, workload, None, write)


def new_revision(study: Path, examples_dir: Path | None = None, *, read_sequence: int | None = None) -> dict:
    """Add a revision to the Study `study`: the Protocol its Workload declares now; return the new StudySpec.

    The Workload is the one the Study names, read again from `examples_dir`. A Protocol equal to the
    current revision's is refused (`PROTOCOL_UNCHANGED`). Holds the Study's writer lock for the whole command.
    """
    study = Path(study)
    study_write.check_read_sequence(study_write.INIT, read_sequence)
    layout.read_spec(study)  # a folder that is no Study is refused before a lock file is created in it
    with study_write.locked(study, study_write.INIT_NEW_REVISION, read_sequence=read_sequence) as write:
        write.require_current()
        previous = layout.read_spec(study)
        layout.require_domain(previous, DOMAIN, study_write.INIT_NEW_REVISION)
        examples = data.resolve_examples_dir(examples_dir)
        workload_name = previous["workload"]
        data.verify_workloads(examples, [workload_name])  # T01 at this entry point: before anything is written
        workload = load_workload(examples / workload_name)
        require_declared(workload, *required_by_init(workload))
        check_histories(workload)
        check_scoring_config(workload)
        return _write_spec(study, workload_name, workload, previous, write)
