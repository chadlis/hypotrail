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
import io
import math
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from hypotrail.core import artifacts, attempts, canonical, data, environment, exposure, protocol_check, requests, study_write
from hypotrail.core import study as layout
from hypotrail.core.errors import IntegrityError, InvalidInputError
from hypotrail.core.imports import UNKNOWN, producer_entry, read_input, require_not_serialized, strict_json_or_none
from hypotrail.ml import ranking_study
from hypotrail.ml.declaration import load_declaration
from hypotrail.ml.run import OBSERVATIONS_COLUMNS
from hypotrail.ml.study import DOMAIN, PROTOCOL_CHANGED_MESSAGE, protocol_content

COMMAND = study_write.IMPORT_ML
MODE = "external_unknown"
STAGE = "import"

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
RANKING_MAPPING_KEYS = {key: required for key, required in MAPPING_KEYS.items() if key != "y_pred_raw"} | {"settings": False}
RANKING_SCORE = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
# The producer fields of the provenance, and the mapping key each is declared by (none for the last).
PRODUCER_FIELDS = {
    "model": "model",
    "generation_time": "generated_at",
    "historical_protocol": "historical_protocol",
    "tool_use": "tool_use",
    "saw_public_check": None,
}
POPULATION_KEY = layout.IMPORT_POPULATION_KEY
_SHA256 = re.compile(r"[0-9a-f]{64}")
# A value that names a callable or a module (`os.system`, `pickle:loads`, `f(x)`) is not a column name.
_EXECUTABLE = re.compile(r"[():;/\\]|^__|^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$|^(lambda|eval|exec|import)\b")


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage=STAGE, details=details)


def _partition_or_none(population, partition_of: dict):
    """The one Partition that the Items of a population value belong to, or None when it has no Items, an Item of no Partition or Items of several."""
    items = population.get(POPULATION_KEY) if isinstance(population, dict) else None
    if not isinstance(items, list) or not items or not all(isinstance(i, str) for i in items):
        return None
    partitions = {partition_of.get(i) for i in items}
    return partitions.pop() if len(partitions) == 1 and None not in partitions else None


def _checked_mapping(raw: bytes, mapping_path, *, ranking=False) -> dict:
    allowed = RANKING_MAPPING_KEYS if ranking else MAPPING_KEYS
    try:
        mapping = canonical.loads(raw)
    except InvalidInputError:
        raise _refuse("MAPPING_INVALID", "the mapping is not a JSON document in UTF-8", mapping=str(mapping_path), problem="not_json") from None
    if not isinstance(mapping, dict):
        raise _refuse("MAPPING_INVALID", "the mapping must be a JSON object", mapping=str(mapping_path), problem="not_an_object")
    for key in mapping:
        if key not in allowed:
            raise _refuse(
                "MAPPING_KEY_UNKNOWN", f"the mapping holds a key that is not one of its keys: {key!r}", key=key, allowed=sorted(allowed)
            )
    for key, required in allowed.items():
        if required and key not in mapping:
            raise _refuse("MAPPING_KEY_MISSING", f"the mapping has no {key!r}", key=key, required=sorted(k for k, r in allowed.items() if r))
    for key, value in mapping.items():
        if ranking and key == "settings":
            if not isinstance(value, dict) or any(
                not name or (item is not None and not isinstance(item, (str, bool, int, float)))
                for name, item in value.items()
            ):
                raise _refuse("MAPPING_VALUE_INVALID", "settings must be an object of named scalar values", key=key)
            continue
        if not isinstance(value, str) or not value.strip():
            raise _refuse("MAPPING_VALUE_INVALID", f"the mapping value of {key!r} must be a non-empty string", key=key)
        if key in COLUMN_KEYS and _EXECUTABLE.search(value):
            raise _refuse(
                "MAPPING_VALUE_EXECUTABLE",
                f"the mapping value of {key!r} names a callable or a module, not a column; nothing in an import is executed",
                key=key,
            )
    if ranking:
        for key, value in (("row_id", "item_id"), ("y_pred", "score")):
            if mapping[key] != value:
                raise _refuse("MAPPING_VALUE_INVALID", f"ranking requires {key} to name {value!r}", key=key)
    if not _SHA256.fullmatch(mapping["dataset_sha256"]):
        raise _refuse("MAPPING_VALUE_INVALID", "dataset_sha256 must be 64 lowercase hexadecimal digits", key="dataset_sha256")
    return mapping


def _checked_source(raw: bytes, source_path, mapping: dict):
    """(header, rows) of the source CSV, once it is known to be data in UTF-8 that holds the mapped columns."""
    name = str(source_path)
    require_not_serialized(raw, source_path, adopts="a CSV of predictions")
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


def _population_ids(raw: bytes, population_path):
    """Read the requested Item IDs in the population file, before checking membership."""
    name = str(population_path)
    try:
        document = canonical.loads(raw)
    except InvalidInputError:
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
    return items


def _checked_population(raw: bytes, population_path, partition_of: dict):
    """(partition, Item IDs) of the population file, every ID taken from one Partition of the Protocol."""
    items = _population_ids(raw, population_path)
    for item in items:
        if item not in partition_of:
            raise _refuse("POPULATION_ITEM_UNKNOWN", f"{item} is not an Item of any Partition of the Study's Protocol", row_id=item)
    partitions = sorted({partition_of[i] for i in items})
    if len(partitions) != 1:
        raise _refuse("POPULATION_MIXED_PARTITIONS", "the population mixes Items of several Partitions", partitions=partitions)
    return partitions[0], sorted(items)


def _ranking_population(raw, population_path, partition_of, dataset, partition):
    items = _population_ids(raw, population_path)
    try:
        dates = [ranking_study.item_date(item) for item in items]
    except ValueError:
        raise _refuse("POPULATION_INVALID", "a ranking population Item needs an entity and an ISO date", problem="bad_item_id") from None
    cutoff = date.fromisoformat(dataset["label_cutoff"])
    if any((cutoff - as_of).days < dataset["horizon_days"] for as_of in dates):
        raise _refuse("POPULATION_ITEM_IMMATURE", "the population contains an immature Item")

    scope = "development" if partition == ranking_study.DEV else "held-out"
    known_other = set(dataset["other_partition_items"])
    outside = set(items) - set(partition_of)
    known = {item for item in outside if ranking_study.item_digest(item) in known_other}
    if known and len(outside) != len(items):
        raise _refuse("POPULATION_MIXED_PARTITIONS", f"the ranking population mixes {scope} and other Items")
    if outside:
        raise _refuse("POPULATION_ITEM_UNKNOWN", f"the ranking population contains an Item outside the Study's {scope} Partition")
    return sorted(items)


def _ranking_preflight(write, request_id, path, partition_of, dataset, partition):
    raw = read_input(path, "POPULATION_NOT_FOUND", "population")
    try:
        return raw, _ranking_population(raw, path, partition_of, dataset, partition)
    except InvalidInputError:
        def refuse_reused_request(recorded):
            raise requests.conflict(request_id, recorded["attempt_id"], ["input_digests"])

        write.replay_attempt(refuse_reused_request)
        raise


def _finite(cell):
    if cell is None or "_" in cell:  # Python reads `1_000` as a number; a CSV does not
        return None
    try:
        value = float(cell)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _ranking_score(cell):
    if cell is not None and RANKING_SCORE.fullmatch(cell):
        try:
            if Decimal(cell).is_finite():
                return cell
        except InvalidOperation:
            return None
    return None


def _joined(rows: list, mapping: dict, items: list, *, ranking=False):
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
            if ranking:
                raise _refuse("ROW_ID_OUTSIDE_POPULATION", "the ranking score file has a row outside its development population", line=number)
            raise _refuse("ROW_ID_OUTSIDE_POPULATION", f"{row_id} is not an Item of the population", row_id=row_id)
        cell = row[mapping["y_pred"]]
        value = _ranking_score(cell) if ranking else _finite(cell)
        if value is None:
            raise _refuse(
                "PREDICTION_NOT_FINITE",
                f"{row_id} has no finite number in {mapping['y_pred']!r}",
                row_id=row_id,
                column=mapping["y_pred"],
            )
        raw = row[mapping["y_pred_raw"]] if "y_pred_raw" in mapping else ""
        found[row_id] = ((raw or "").strip(), value if ranking else repr(value))
    absent = sorted(expected - set(found))
    if absent:
        raise _refuse("POPULATION_ITEM_ABSENT", f"{absent[0]} is an Item of the population and is absent from the source", row_id=absent[0], absent=len(absent))
    return found


def _normalized(items: list, joined: dict, *, ranking=False) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(("item_id", "score") if ranking else OBSERVATIONS_COLUMNS)
    for row_id in items:
        raw, value = joined[row_id]
        writer.writerow((row_id, value) if ranking else (row_id, "produced", "", raw, value))
    return out.getvalue().encode("utf-8")


def _producer(mapping: dict) -> dict:
    """What the import says about how the outputs were made: `declared` by the mapping, otherwise `unknown`."""
    producer = {field: producer_entry(mapping[key].strip() if key is not None and key in mapping else None) for field, key in PRODUCER_FIELDS.items()}
    if "settings" in mapping:
        producer["settings"] = producer_entry(mapping["settings"])
    return producer


def _report(source_ref, mapping_ref, population_ref, header, mapping, rows, items, partition, *, ranking=False) -> dict:
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
                "dataset_digest_equals_ranking_items" if ranking else "dataset_digest_equals_the_workload_lock",
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
    study_write.check_arguments(COMMAND, read_sequence, request_id)
    layout.read_spec(study)  # a folder that is no Study is refused before a lock file is created in it
    with study_write.locked(study, COMMAND, request_id, read_sequence=read_sequence, has_attempt=True, evaluator_stage=STAGE) as write:
        return _import_locked(study, write, Path(source), Path(mapping), Path(population), request_id, examples_dir=examples_dir)


def _import_locked(study, write, source, mapping_path, population_path, request_id, *, examples_dir):
    spec = layout.read_spec(study)
    domain = spec["domain"]
    ranking = domain == ranking_study.TRACK
    workload = spec["workload"]
    by_role = {entry["ref"]["role"]: entry["ref"] for entry in spec["artifacts"]}
    study_refs = [*spec["dataset_refs"], *by_role.values()]
    if ranking:
        dataset, memberships = ranking_study.read_dataset(study, spec)
        artifacts.read_verified(study, by_role["references"])
        dataset_sha = dataset["items_sha256"]
        partition_of = {item_id: row["partition"] for item_id, row in memberships.items()}
    else:
        layout.require_domain(spec, DOMAIN, COMMAND)
        examples = data.resolve_examples_dir(examples_dir)
        data.verify_workloads(examples, [workload])
        for ref in study_refs:
            artifacts.read_verified(study, ref)
        workload_dir = examples / workload
        declaration = load_declaration(workload_dir)
        dataset_sha = data.sha256_file(workload_dir / declaration.data_file)
        memberships = artifacts.read_verified(study, by_role["memberships"])
        partition_of = layout.partition_of(memberships, "row_id")

    if ranking:
        partition = spec.get("partition", ranking_study.DEV)
        population_bytes, items = _ranking_preflight(write, request_id, population_path, partition_of, dataset, partition)
    source_bytes = read_input(source, "SOURCE_NOT_FOUND", "source")
    mapping_bytes = read_input(mapping_path, "MAPPING_NOT_FOUND", "mapping")
    if not ranking:
        population_bytes = read_input(population_path, "POPULATION_NOT_FOUND", "population")

    mapping_json_or_none = strict_json_or_none(mapping_bytes)
    model = mapping_json_or_none.get("model") if isinstance(mapping_json_or_none, dict) else None
    # The request: every element of the identity, with the import's value or `unknown`.
    effective_config = {
        "command": COMMAND,
        "workload": workload,
        "mode": MODE,
        "partition": _partition_or_none(strict_json_or_none(population_bytes), partition_of),
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
    recorded = attempts.replayed(study, write, request_id, effective_config, code_environment)
    if recorded is not None:
        return recorded, True

    if not ranking:
        protocol = protocol_content(
            declaration,
            dataset_sha256=dataset_sha,
            memberships_sha256=by_role["memberships"]["sha256"],
            references_sha256=by_role["references"]["sha256"],
        )
        protocol_check.require_unchanged(spec, canonical.digest(protocol), message=PROTOCOL_CHANGED_MESSAGE, stage="request")

    mapping = _checked_mapping(mapping_bytes, mapping_path, ranking=ranking)
    header, rows = _checked_source(source_bytes, source, mapping)
    if not ranking:
        partition, items = _checked_population(population_bytes, population_path, partition_of)
    if mapping["dataset_sha256"] != dataset_sha:
        raise IntegrityError(
            "DATASET_DIGEST_MISMATCH",
            "the mapping digest differs from the Study's ranking Items digest" if ranking
            else "the dataset digest the mapping declares is not the Workload lock's digest of the data file",
            stage=STAGE,
            details={"declared_sha256": mapping["dataset_sha256"], "locked_sha256": dataset_sha},
        )
    joined = _joined(rows, mapping, items, ranking=ranking)
    normalized = _normalized(items, joined, ranking=ranking)
    effective_config = {**effective_config, "partition": partition}

    producer = _producer(mapping)
    import_time = attempts.now()
    effective_config = {**effective_config, "import_time": import_time, "producer": producer}

    def produce(recording: attempts.Recording) -> attempts.Produced:
        folder, writes = recording.folder, recording.writes
        original = Path(source).name or "source.csv"
        source_ref = writes.publish(f"{folder}/source/{original}", source_bytes, media_type=layout.media_type_of(original), role="import_source")
        mapping_ref = writes.publish(f"{folder}/mapping.json", mapping_bytes, media_type="application/json", role="import_mapping")
        population_ref = writes.publish(f"{folder}/population.json", population_bytes, media_type="application/json", role="import_population")
        report_ref = writes.publish_record(
            f"{folder}/validation_report.json",
            _report(source_ref, mapping_ref, population_ref, header, mapping, rows, items, partition, ranking=ranking),
            role="validation_report",
        )
        recording.observations(
            "observations.csv",
            normalized,
            ["produced"] * len(items),
            media_type="text/csv",
            domain=domain,
            origin="imported",
            population_ref=population_ref,
            raw_refs=[source_ref],
            provenance={"produced_by": "external", "partition": partition, "import_time": import_time, **producer},
            unknown_fields=[field for field, entry in producer.items() if entry["origin"] == UNKNOWN],
        )
        return attempts.Produced(inputs=[source_ref, mapping_ref, population_ref], outputs=[report_ref], effective_config=effective_config)

    terminal = attempts.record(
        study,
        write,
        request_id=request_id,
        operation="import",
        mode=MODE,
        effective_config=effective_config,
        code_environment=code_environment,
        input_refs=study_refs,
        produce=produce,
        started_at=import_time,
        marks=exposure.import_mark(study),
    )
    return terminal, False
