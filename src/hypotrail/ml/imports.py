"""`import ml`: adopt a complete predictions CSV, written elsewhere, as an Import Attempt of a Study.

The file is data: nothing in it, in the mapping or in the population file is executed or
deserialised as code (SPEC IMP-06). This module imports neither scikit-learn, NumPy nor Inspect, so
an import and its `assess` run where none of them is installed.

The order is fixed, and nothing is written before the checks that precede it. A refusal publishes
no Observation set and no Attempt:

1. the Study exists and the command holds its writer lock (a second writer: `STUDY_LOCKED`, exit 6);
2. the Workload's data is verified against its lock, and every Study artifact read is read back
   against its digest (exit 3);
3. the three input files are read and their digests taken; the request is identified
   (`hypotrail.core.requests`, #67 Tightened D2): the same `request_id` with the same request
   returns the recorded Import, comparing the recomputed digests and nothing else (the source is not
   validated again, nothing is written or scored); with another request it is `REQUEST_CONFLICT`
   (exit 6);
4. for a new request, the Protocol of the Workload must still be the Study's (`PROTOCOL_CHANGED`);
5. the mapping, then the source file, then the population are checked (exit 2), the dataset digest
   the mapping declares is compared with the Workload's lock (`DATASET_DIGEST_MISMATCH`, exit 3),
   and every row of the source is joined to the population by ID, never by position;
6. the manifest is written `running`; the original files, the validation report, the normalized
   Observations and the Observation set record are published atomically; the manifest is replaced by
   the terminal one, last. An error inside the live process leaves a `failed` Attempt, as in `run ml`.

What the import cannot establish is recorded as `unknown`; what the mapping claims about the
producer is recorded as `declared`. Nothing is `verified`, and no record says the producer worked
independently.
"""

import csv
import datetime
import io
import json
import math
import re
import uuid
from pathlib import Path

from hypotrail.core import artifacts, canonical, contracts, data, decisions, environment, lock, requests, write_journal
from hypotrail.core import study as layout
from hypotrail.core.errors import IntegrityError, InvalidInputError
from hypotrail.ml.declaration import load_declaration
from hypotrail.ml.run import ITEM_STATUSES, OBSERVATIONS_COLUMNS, _record_failure, _verify_recorded
from hypotrail.ml.study import DOMAIN, protocol_content

COMMAND = "import ml"
MODE = "external_unknown"
STAGE = "import"
UNKNOWN = "unknown"
DECLARED = "declared"

# The keys a mapping may hold, and whether each is required. The first three name columns of the
# source file; the others are what the mapping declares about the producer.
MAPPING_KEYS = {
    "row_id": True,
    "y_pred": True,
    "dataset_sha256": True,
    "y_pred_raw": False,
    "model": False,
    "generated_at": False,
    "historical_protocol": False,
    "tool_use": False,
}
COLUMN_KEYS = ("row_id", "y_pred", "y_pred_raw")
CLAIM_KEYS = ("model", "generated_at", "historical_protocol", "tool_use")
# The producer fields of the provenance, and the mapping key each is declared by (none for the last).
PRODUCER_FIELDS = {
    "model": "model",
    "generation_time": "generated_at",
    "historical_protocol": "historical_protocol",
    "tool_use": "tool_use",
    "saw_public_check": None,
}
POPULATION_KEY = layout.IMPORT_POPULATION_KEY
SERIALIZED_SUFFIXES = (".pkl", ".pickle", ".joblib", ".npy", ".npz")
SERIALIZED_MAGIC = b"\x80"  # pickle protocol 2 and later
_SHA256 = re.compile(r"[0-9a-f]{64}")
# A value that names a callable or a module (`os.system`, `pickle:loads`, `f(x)`) is not a column name.
_EXECUTABLE = re.compile(r"[():;/\\]|^__|^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$|^(lambda|eval|exec|import)\b")


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage=STAGE, details=details)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _read(path, code, what) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError:
        raise _refuse(code, f"the {what} file cannot be read: {path}", **{what: str(path)}) from None


def _loose_json(raw: bytes):
    """The JSON value of `raw`, or None: used only to identify a request, never to accept an input."""
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _loose_partition(population, partition_of: dict):
    items = population.get(POPULATION_KEY) if isinstance(population, dict) else None
    if not isinstance(items, list) or not items or not all(isinstance(i, str) for i in items):
        return None
    partitions = {partition_of.get(i) for i in items}
    return partitions.pop() if len(partitions) == 1 and None not in partitions else None


def _checked_mapping(raw: bytes, mapping_path) -> dict:
    try:
        mapping = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _refuse("MAPPING_INVALID", "the mapping is not a JSON document in UTF-8", mapping=str(mapping_path), problem="not_json") from None
    if not isinstance(mapping, dict):
        raise _refuse("MAPPING_INVALID", "the mapping must be a JSON object", mapping=str(mapping_path), problem="not_an_object")
    for key in mapping:
        if key not in MAPPING_KEYS:
            raise _refuse(
                "MAPPING_KEY_UNKNOWN", f"the mapping holds a key that is not one of its keys: {key!r}", key=key, allowed=sorted(MAPPING_KEYS)
            )
    for key, required in MAPPING_KEYS.items():
        if required and key not in mapping:
            raise _refuse("MAPPING_KEY_MISSING", f"the mapping has no {key!r}", key=key, required=sorted(k for k, r in MAPPING_KEYS.items() if r))
    for key, value in mapping.items():
        if not isinstance(value, str) or not value.strip():
            raise _refuse("MAPPING_VALUE_INVALID", f"the mapping value of {key!r} must be a non-empty string", key=key)
        if key in COLUMN_KEYS and _EXECUTABLE.search(value):
            raise _refuse(
                "MAPPING_VALUE_EXECUTABLE",
                f"the mapping value of {key!r} names a callable or a module, not a column; nothing in an import is executed",
                key=key,
            )
    if not _SHA256.fullmatch(mapping["dataset_sha256"]):
        raise _refuse("MAPPING_VALUE_INVALID", "dataset_sha256 must be 64 lowercase hexadecimal digits", key="dataset_sha256")
    return mapping


def _checked_source(raw: bytes, source_path, mapping: dict):
    """(header, rows) of the source CSV, once it is known to be data in UTF-8 that holds the mapped columns."""
    name = str(source_path)
    if Path(source_path).suffix.lower() in SERIALIZED_SUFFIXES or raw.startswith(SERIALIZED_MAGIC):
        raise _refuse(
            "SOURCE_SERIALIZED",
            "the source is a serialized object (pickle, joblib or an array dump); an import adopts a CSV of predictions and loads nothing",
            source=name,
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse("SOURCE_NOT_UTF8", "the source is not valid UTF-8", source=name) from None
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        header = reader.fieldnames
        rows = list(reader)
    except csv.Error as error:
        raise _refuse("SOURCE_UNREADABLE", f"the source is not a readable CSV: {error}", source=name, problem="csv_error") from None
    if not header:
        raise _refuse("SOURCE_UNREADABLE", "the source has no header line", source=name, problem="no_header")
    for key in COLUMN_KEYS:
        if key in mapping and mapping[key] not in header:
            raise _refuse(
                "MAPPING_COLUMN_ABSENT", f"the mapped column {mapping[key]!r} ({key}) is not in the source", key=key, column=mapping[key]
            )
    return header, rows


def _checked_population(raw: bytes, population_path, partition_of: dict):
    """(partition, Item IDs) of the population file, every ID taken from one Partition of the Protocol."""
    name = str(population_path)
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _refuse("POPULATION_INVALID", "the population is not a JSON document in UTF-8", population=name, problem="not_json") from None
    if not isinstance(document, dict) or set(document) != {POPULATION_KEY}:
        raise _refuse(
            "POPULATION_INVALID", f"the population must be an object with the one key {POPULATION_KEY!r}", population=name, problem="bad_shape"
        )
    items = document[POPULATION_KEY]
    if not isinstance(items, list) or not items or not all(isinstance(i, str) and i for i in items):
        raise _refuse("POPULATION_INVALID", f"{POPULATION_KEY} must be a non-empty list of Item IDs", population=name, problem="bad_items")
    if len(set(items)) != len(items):
        raise _refuse("POPULATION_INVALID", "the population lists an Item twice", population=name, problem="duplicate_item")
    for item in items:
        if item not in partition_of:
            raise _refuse("POPULATION_ITEM_UNKNOWN", f"{item} is not an Item of any Partition of the Study's Protocol", row_id=item)
    partitions = sorted({partition_of[i] for i in items})
    if len(partitions) != 1:
        raise _refuse("POPULATION_MIXED_PARTITIONS", "the population mixes Items of several Partitions", partitions=partitions)
    return partitions[0], sorted(items)


def _finite(cell):
    if cell is None or "_" in cell:  # Python reads `1_000` as a number; a CSV does not
        return None
    try:
        value = float(cell)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _joined(rows: list, mapping: dict, items: list):
    """{row_id: (y_pred_raw, y_pred)} for every Item of the population; the file is joined by ID, never by position."""
    expected = set(items)
    found = {}
    for number, row in enumerate(rows, start=2):  # line 1 is the header
        row_id = row[mapping["row_id"]]
        if row_id is None or not row_id.strip():
            raise _refuse("ROW_ID_EMPTY", f"line {number} of the source has an empty row_id", line=number)
        if row_id in found:
            raise _refuse("ROW_ID_DUPLICATE", f"{row_id} appears twice in the source", row_id=row_id)
        if row_id not in expected:
            raise _refuse("ROW_ID_OUTSIDE_POPULATION", f"{row_id} is not an Item of the population", row_id=row_id)
        value = _finite(row[mapping["y_pred"]])
        if value is None:
            raise _refuse(
                "PREDICTION_NOT_FINITE",
                f"{row_id} has no finite number in {mapping['y_pred']!r}",
                row_id=row_id,
                column=mapping["y_pred"],
            )
        raw = row[mapping["y_pred_raw"]] if "y_pred_raw" in mapping else ""
        found[row_id] = ((raw or "").strip(), repr(value))
    absent = sorted(expected - set(found))
    if absent:
        raise _refuse("POPULATION_ITEM_ABSENT", f"{absent[0]} is an Item of the population and is absent from the source", row_id=absent[0], absent=len(absent))
    return found


def _normalized(items: list, joined: dict) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(OBSERVATIONS_COLUMNS)
    for row_id in items:
        raw, value = joined[row_id]
        writer.writerow([row_id, "produced", "", raw, value])
    return out.getvalue().encode("utf-8")


def _producer(mapping: dict) -> dict:
    """What the import says about how the outputs were made: `declared` by the mapping, otherwise `unknown`."""
    producer = {}
    for field, key in PRODUCER_FIELDS.items():
        if key is not None and key in mapping:
            producer[field] = {"value": mapping[key].strip(), "origin": DECLARED}
        else:
            producer[field] = {"value": None, "origin": UNKNOWN}
    return producer


def _report(source_ref, mapping_ref, population_ref, header, mapping, rows, items, partition) -> dict:
    return {
        "report": "import_validation/1",
        "source_sha256": source_ref["sha256"],
        "mapping_sha256": mapping_ref["sha256"],
        "population_sha256": population_ref["sha256"],
        "partition": partition,
        "rows_read": len(rows),
        "population_items": len(items),
        "mapped_columns": {key: mapping[key] for key in COLUMN_KEYS if key in mapping},
        "unmapped_columns": [c for c in header if c not in {mapping[k] for k in COLUMN_KEYS if k in mapping}],
        "checks": [
            {"check": check, "result": "passed"}
            for check in (
                "source_is_data_not_a_serialized_object",
                "source_is_utf8_csv",
                "mapping_keys_and_values",
                "mapped_columns_present",
                "population_items_in_one_partition_of_the_protocol",
                "dataset_digest_equals_the_workload_lock",
                "row_ids_non_empty_and_unique",
                "row_ids_within_the_population",
                "population_covered",
                "predictions_finite",
            )
        ],
    }


def import_ml(
    study: Path,
    source: Path,
    mapping: Path,
    population: Path,
    request_id: str,
    *,
    examples_dir: Path | None = None,
    read_sequence: int | None = None,
) -> tuple[dict, bool]:
    """Import (or replay) one request under the Study's writer lock; return the Attempt manifest and whether it was recorded already."""
    study = Path(study)
    if not request_id:
        raise InvalidInputError("REQUEST_ID_EMPTY", "--request-id must not be empty", stage="request", details={})
    layout.read_spec(study)  # a folder that is no Study is refused before a lock file is created in it
    with lock.writer_lock(study), write_journal.writing(study, COMMAND, request_id, has_attempt=True):
        return _import_locked(study, Path(source), Path(mapping), Path(population), request_id, examples_dir=examples_dir, read_sequence=read_sequence)


def _import_locked(study, source, mapping_path, population_path, request_id, *, examples_dir, read_sequence=None):
    spec = layout.read_spec(study)
    layout.require_domain(spec, DOMAIN, COMMAND)
    examples = data.resolve_examples_dir(examples_dir)
    workload = spec["workload"]
    data.verify_workloads(examples, [workload])
    study_refs = [*spec["dataset_refs"], *(entry["ref"] for entry in spec["artifacts"])]
    for ref in study_refs:
        artifacts.read_verified(study, ref)
    by_role = {entry["ref"]["role"]: entry["ref"] for entry in spec["artifacts"]}
    workload_dir = examples / workload
    declaration = load_declaration(workload_dir)
    dataset_sha = data.sha256_file(workload_dir / declaration.data_file)

    source_bytes = _read(source, "SOURCE_NOT_FOUND", "source")
    mapping_bytes = _read(mapping_path, "MAPPING_NOT_FOUND", "mapping")
    population_bytes = _read(population_path, "POPULATION_NOT_FOUND", "population")
    memberships = artifacts.read_verified(study, by_role["memberships"])
    partition_of = layout.partition_of(memberships, "row_id")

    loose_mapping = _loose_json(mapping_bytes)
    model = loose_mapping.get("model") if isinstance(loose_mapping, dict) else None
    # The request: every element of the identity, with the import's value or `unknown`.
    effective_config = {
        "command": COMMAND,
        "workload": workload,
        "mode": MODE,
        "partition": _loose_partition(_loose_json(population_bytes), partition_of),
        "configuration": UNKNOWN,
        "model": model.strip() if isinstance(model, str) and model.strip() else UNKNOWN,
        "repeats": UNKNOWN,
        "protocol": {"protocol_id": spec["protocol_id"], "protocol_digest": spec["protocol_digest"]},
        "input_digests": {
            "dataset": dataset_sha,
            "source": canonical.sha256_hex(source_bytes),
            "mapping": canonical.sha256_hex(mapping_bytes),
            "population": canonical.sha256_hex(population_bytes),
        },
    }
    code_environment = environment.code_environment()
    requested = requests.identity(effective_config, code_environment)
    recorded = layout.find_by_request(study, request_id)
    if recorded is not None:
        differs = requests.differences(requests.identity(recorded["effective_config"], recorded["code_environment"]), requested)
        if differs:
            raise requests.conflict(request_id, recorded["attempt_id"], differs)
        _verify_recorded(study, recorded)
        return recorded, True
    decisions.refuse_if_a_decision_holds(study, request_id)  # one request_id namespace for the Attempts and the decisions of a Study
    write_journal.require_current(study, read_sequence)  # straight after the request identity (D-033 on chadlis/hypotrail#75)

    protocol = protocol_content(
        declaration,
        dataset_sha256=dataset_sha,
        memberships_sha256=by_role["memberships"]["sha256"],
        references_sha256=by_role["references"]["sha256"],
    )
    if canonical.digest(protocol) != spec["protocol_digest"]:
        raise IntegrityError(
            "PROTOCOL_CHANGED",
            "the Workload's Protocol is no longer the one of this Study (Partitions, population, References or rules)",
            stage="request",
            details={"expected_protocol_digest": spec["protocol_digest"], "actual_protocol_digest": canonical.digest(protocol)},
        )

    mapping = _checked_mapping(mapping_bytes, mapping_path)
    header, rows = _checked_source(source_bytes, source, mapping)
    partition, items = _checked_population(population_bytes, population_path, partition_of)
    if mapping["dataset_sha256"] != dataset_sha:
        raise IntegrityError(
            "DATASET_DIGEST_MISMATCH",
            "the dataset digest the mapping declares is not the Workload lock's digest of the data file",
            stage=STAGE,
            details={"declared_sha256": mapping["dataset_sha256"], "locked_sha256": dataset_sha},
        )
    joined = _joined(rows, mapping, items)
    normalized = _normalized(items, joined)
    effective_config = {**effective_config, "partition": partition}

    producer = _producer(mapping)
    import_time = _now()
    effective_config = {**effective_config, "import_time": import_time, "producer": producer}
    attempt_id = str(uuid.uuid4())
    folder = f"{layout.ATTEMPTS_DIR}/{attempt_id}"
    manifest_path = layout.attempt_manifest_path(attempt_id)
    manifest = {
        "kind": "attempt",
        "schema_version": "attempt/1",
        "attempt_id": attempt_id,
        "request_id": request_id,
        "operation": "import",
        "mode": MODE,
        "technical_status": "running",
        "started_at": import_time,
        "finished_at": None,
        "effective_config": effective_config,
        "effective_config_digest": canonical.digest(effective_config),
        "input_refs": study_refs,
        "code_environment": code_environment,
        "outcome_unknown": False,
        "retry_of": None,
    }
    contracts.validate(manifest)
    write_journal.begin()  # the running manifest is the first write
    write_journal.attempt(attempt_id)
    artifacts.replace_bytes(study, manifest_path, canonical.dumps(manifest))
    try:
        original = Path(source).name or "source.csv"
        source_ref = artifacts.publish_bytes(
            study, f"{folder}/source/{original}", source_bytes, media_type=layout.media_type_of(original), role="import_source"
        )
        mapping_ref = artifacts.publish_bytes(study, f"{folder}/mapping.json", mapping_bytes, media_type="application/json", role="import_mapping")
        population_ref = artifacts.publish_bytes(
            study, f"{folder}/population.json", population_bytes, media_type="application/json", role="import_population"
        )
        report_ref = artifacts.publish_record(
            study,
            f"{folder}/validation_report.json",
            _report(source_ref, mapping_ref, population_ref, header, mapping, rows, items, partition),
            role="validation_report",
        )
        normalized_ref = artifacts.publish_bytes(study, f"{folder}/observations.csv", normalized, media_type="text/csv", role="observations")
        observation_set = {
            "kind": "observations",
            "schema_version": "observations/1",
            "observation_set_id": str(uuid.uuid4()),
            "attempt_id": attempt_id,
            "domain": DOMAIN,
            "origin": "imported",
            "mode": MODE,
            "population_ref": population_ref,
            "raw_refs": [source_ref],
            "normalized_ref": normalized_ref,
            "provenance": {"produced_by": "external", "partition": partition, "import_time": import_time, **producer},
            "unknown_fields": [field for field, entry in producer.items() if entry["origin"] == UNKNOWN],
        }
        contracts.validate(observation_set)
        observation_set_ref = artifacts.publish_record(study, f"{folder}/observation_set.json", observation_set, role="observation_set")
        counts = dict.fromkeys(ITEM_STATUSES, 0)
        counts["produced"] = len(items)
        terminal = {
            **manifest,
            "technical_status": "completed",
            "finished_at": _now(),
            "input_refs": [*study_refs, source_ref, mapping_ref, population_ref],
            "output_refs": [report_ref, normalized_ref, observation_set_ref],
            "item_counts": counts,
        }
        contracts.validate(terminal)
        artifacts.replace_bytes(study, manifest_path, canonical.dumps(terminal))
        return terminal, False
    except Exception as error:
        _record_failure(study, manifest_path, manifest, error)
        raise
