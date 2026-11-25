"""`import agent`: adopt agent answers, written elsewhere as JSONL, as an Import Attempt of a Chinook Study.

The file is data: nothing in it is executed or deserialised as code (SPEC IMP-06). This module
imports neither Inspect, scikit-learn nor NumPy, so a JSONL import and its `assess` run where none of
them is installed. A source with the extension `.eval` is an Inspect log (#69): it is read by
`hypotrail.agentic.inspect_log`, loaded only for it, through Inspect's public log API; without
Inspect it is refused before the lock is taken (`INSPECT_UNAVAILABLE`, exit 5). A log gives the same
Observations as a JSONL file (the final answer as `raw_answer`, the projected steps as `trace`, plus
the `reason` of an Episode that failed), and an Episode the log does not hold is `missing`. It follows the shape of `import ml` (`hypotrail.ml.imports`, #67) and fixes the same
order; nothing is written before the checks that precede it, and a refusal publishes no Observation
set and no Attempt:

1. the Study exists, is a Study of the agent Track, and the command holds its writer lock (a second
   writer: `STUDY_LOCKED`, exit 6);
2. the Workload's data is verified against its lock, and every Study artifact read is read back
   against its digest (exit 3);
3. the two input files are read and their digests taken; the request is identified
   (`hypotrail.core.requests`): the same `request_id` with the same request returns the recorded
   Import, comparing the recomputed digests and nothing else; with another request it is
   `REQUEST_CONFLICT` (exit 6);
4. for a new request, the Protocol of the Workload must still be the Study's (`PROTOCOL_CHANGED`);
5. the population, then the lines of the source, are checked (exit 2): the expected keys are the
   (case_id, repeat) pairs the population file lists, all Cases of one Partition of the Protocol, and
   the source must hold exactly one line for each, a `failed` or `missing` line included;
6. the manifest is written `running`; the original files, the validation report, the normalized
   Observations and the Observation set record are published atomically; the manifest is replaced by
   the terminal one, last. An error inside the live process leaves a `failed` Attempt.

A line is a JSON object: `case_id`, `repeat`, `observation_status` (`produced`, `failed` or
`missing`) and, when `produced`, one of `raw_answer` (the text the system returned) or `final_answer`
(an already-parsed JSON object, scored as its canonical JSON text); an optional `trace` is a list of
the projected steps the Scorer reads (plain records with a `kind`). The optional `origin`, `mode` and
`producer` (`model`, `generation_time`, `historical_protocol`, `tool_use`) say what the file claims.

What the import cannot establish is recorded as `unknown`; what the file claims is `declared`, and
only when every line says the same. Nothing is `verified`, and no record says the producer worked
independently.
"""

import json
from importlib import metadata
from pathlib import Path

from hypotrail.agentic.declaration import load_workload
from hypotrail.agentic.study import DOMAIN, PROTOCOL_CHANGED_MESSAGE, dataset_sha256, protocol_content
from hypotrail.core import artifacts, attempts, canonical, data, environment, protocol_check, study_write
from hypotrail.core import study as layout
from hypotrail.core.attempts import ITEM_STATUSES, now
from hypotrail.core.errors import EXIT_CAPABILITY_UNAVAILABLE, HypotrailError, InvalidInputError

COMMAND = study_write.IMPORT_AGENT
MODE = "external_unknown"
STAGE = "import"
UNKNOWN = "unknown"
DECLARED = "declared"
POPULATION_KEY = "episodes"
LOG_SUFFIX = ".eval"  # a source with this extension is an Inspect log; any other source is JSON Lines
INSPECT_UNAVAILABLE = "INSPECT_UNAVAILABLE"
LOG_VERSION_UNSUPPORTED = "LOG_INSPECT_VERSION_UNSUPPORTED"
SUPPORTED_INSPECT = "0.3.287"  # the Inspect version `pyproject.toml` pins (a test keeps the two equal): installed and written by the log
OBSERVATIONS_NAME = "observations.jsonl"
SERIALIZED_SUFFIXES = (".pkl", ".pickle", ".joblib", ".npy", ".npz")
SERIALIZED_MAGIC = b"\x80"  # pickle protocol 2 and later

# The producer fields of the provenance, and where in a line each is declared.
PRODUCER_FIELDS = {
    "model": ("producer", "model"),
    "generation_time": ("producer", "generation_time"),
    "historical_protocol": ("producer", "historical_protocol"),
    "tool_use": ("producer", "tool_use"),
    "saw_public_check": None,
    "file_origin": ("origin",),
    "file_mode": ("mode",),
}
CLAIMED_IN_PRODUCER = ("model", "generation_time", "historical_protocol", "tool_use")
# What an Inspect log header states beyond the producer fields, each recorded under `log` with its origin.
LOG_FIELDS = ("configuration", "system_text", "limits", "inspect_version", "log_format_version", "log_status")
# The keys of a line, and when each is required: always, only for a `produced` line (one of the two answers), or never.
ALWAYS, WHEN_PRODUCED, OPTIONAL = "always", "produced", "no"
LINE_KEYS = {
    "case_id": ALWAYS,
    "repeat": ALWAYS,
    "observation_status": ALWAYS,
    "raw_answer": WHEN_PRODUCED,
    "final_answer": WHEN_PRODUCED,
    "trace": OPTIONAL,
    "origin": OPTIONAL,
    "mode": OPTIONAL,
    "producer": OPTIONAL,
}


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage=STAGE, details=details)


def _read(path, code, what) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError:
        raise _refuse(code, f"the {what} file cannot be read: {path}", **{what: str(path)}) from None


def _loose_json(raw: bytes):
    """The JSON value of `raw`, or None: used only to identify a request, never to accept an input."""
    try:
        return canonical.loads(raw)
    except InvalidInputError:
        return None


def _loose_episodes(population):
    episodes = population.get(POPULATION_KEY) if isinstance(population, dict) else None
    if not isinstance(episodes, list):
        return []
    return [e for e in episodes if isinstance(e, dict) and isinstance(e.get("case_id"), str) and type(e.get("repeat")) is int]


def _loose_model(raw: bytes) -> str:
    """The model every line of the source declares, or `unknown`: used only to identify a request."""
    models = set()
    for text in raw.decode("utf-8", errors="replace").splitlines():
        line = _loose_json(text.encode("utf-8")) if text.strip() else None
        producer = line.get("producer") if isinstance(line, dict) else None
        models.add(producer.get("model") if isinstance(producer, dict) else None)
    only = next(iter(models)) if len(models) == 1 else None
    return only.strip() if isinstance(only, str) and only.strip() else UNKNOWN


def _checked_population(raw: bytes, population_path, partition_of: dict):
    """(partition, sorted (case_id, repeat) keys) of the population file, every Case taken from one Partition of the Protocol."""
    name = str(population_path)
    try:
        document = canonical.loads(raw)
    except InvalidInputError:
        raise _refuse("POPULATION_INVALID", "the population is not a JSON document in UTF-8", population=name, problem="not_json") from None
    if not isinstance(document, dict) or set(document) != {POPULATION_KEY}:
        raise _refuse(
            "POPULATION_INVALID", f"the population must be an object with the one key {POPULATION_KEY!r}", population=name, problem="bad_shape"
        )
    episodes = document[POPULATION_KEY]
    if not isinstance(episodes, list) or not episodes:
        raise _refuse("POPULATION_INVALID", f"{POPULATION_KEY} must be a non-empty list of Episodes", population=name, problem="bad_episodes")
    keys = []
    for episode in episodes:
        if (
            not isinstance(episode, dict)
            or set(episode) != {"case_id", "repeat"}
            or not isinstance(episode["case_id"], str)
            or not episode["case_id"]
            or type(episode["repeat"]) is not int
            or episode["repeat"] < 0
        ):
            raise _refuse(
                "POPULATION_INVALID",
                'each Episode must be {"case_id": a Case ID, "repeat": a non-negative integer}',
                population=name,
                problem="bad_episodes",
            )
        keys.append((episode["case_id"], episode["repeat"]))
    if len(set(keys)) != len(keys):
        raise _refuse("POPULATION_INVALID", "the population lists an Episode twice", population=name, problem="duplicate_episode")
    for case_id, _ in keys:
        if case_id not in partition_of:
            raise _refuse("POPULATION_CASE_UNKNOWN", f"{case_id} is not a Case of any Partition of the Study's Protocol", case_id=case_id)
    partitions = sorted({partition_of[case_id] for case_id, _ in keys})
    if len(partitions) != 1:
        raise _refuse("POPULATION_MIXED_PARTITIONS", "the population mixes Cases of several Partitions", partitions=partitions)
    return partitions[0], sorted(keys)


def is_log(source) -> bool:
    return Path(source).suffix.lower() == LOG_SUFFIX


def require_inspect(stage: str = STAGE, what: str = "importing an Inspect log") -> None:
    """The supported Inspect must be importable (ENV-02): refused with `INSPECT_UNAVAILABLE`, exit 5, before anything is written."""
    try:
        import inspect_ai  # noqa: F401
    except ImportError:
        raise HypotrailError(
            INSPECT_UNAVAILABLE,
            f"`{what}` needs the supported Inspect (the agent extra); it is not importable here",
            stage=stage,
            details={"package": "inspect-ai"},
            exit_code=EXIT_CAPABILITY_UNAVAILABLE,
        ) from None
    installed = metadata.version("inspect-ai")
    if installed != SUPPORTED_INSPECT:
        raise HypotrailError(
            INSPECT_UNAVAILABLE,
            f"`{what}` needs the supported Inspect {SUPPORTED_INSPECT}; {installed} is installed",
            stage=stage,
            details={"package": "inspect-ai", "installed": installed, "supported": SUPPORTED_INSPECT},
            exit_code=EXIT_CAPABILITY_UNAVAILABLE,
        )


def _stated(value) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else UNKNOWN


def _log_identity(source) -> tuple:
    """(model, Configuration) the log header declares, or `unknown`, once its Inspect version is the supported one (else refused)."""
    from hypotrail.agentic import inspect_log

    header = inspect_log.header_of(inspect_log.read(source, header_only=True))
    if header["inspect_version"] != SUPPORTED_INSPECT:
        raise InvalidInputError(
            LOG_VERSION_UNSUPPORTED,
            f"the log was written by Inspect {_stated(header['inspect_version'])}; only logs of the supported Inspect {SUPPORTED_INSPECT} are imported",
            stage=STAGE,
            details={"source": str(source), "log_inspect_version": header["inspect_version"], "supported": SUPPORTED_INSPECT},
        )
    return _stated(header["model"]), _stated(header["configuration"])


def _log_producer(header: dict) -> tuple:
    """(producer, log): what the log header states, all `declared`, and what it leaves out, `unknown`."""
    from hypotrail.agentic import inspect_log

    def entry(value):
        return {"value": value, "origin": UNKNOWN if value in (None, "") else DECLARED}

    mode = header["mode"] if isinstance(header["mode"], str) else None
    if mode == "llm_live" and inspect_log.is_mock(header["model"]):
        mode = None  # Inspect's mock model never ran a live model, whatever the header says
    producer = {field: entry(None) for field in PRODUCER_FIELDS}
    producer["model"] = entry(header["model"])
    producer["generation_time"] = entry(header["generation_time"])
    producer["file_mode"] = entry(mode)
    log = {name: entry(header[name]) for name in LOG_FIELDS}
    return producer, log


def log_entries(episodes: list, usage: dict) -> dict:
    """The normalized Observations of projected Episodes: the answer text is the `raw_answer`, the steps are the trace.

    `usage` is what the log states for each Episode it holds (latency and tokens); an Episode it lacks has none.
    """
    entries = {}
    for episode in episodes:
        answered = episode["status"] == "produced" and episode["final_answer"] is not None
        entries[(episode["case_id"], episode["repeat"])] = {
            "case_id": episode["case_id"],
            "repeat": episode["repeat"],
            "status": episode["status"],
            "reason": episode["reason"],
            "answer_given_as": "raw_answer" if answered else None,
            "raw_answer": episode["final_answer"] if answered else None,
            "final_answer": None,
            "trace": episode["steps"] or None,
            "usage": usage.get((episode["case_id"], episode["repeat"])),
        }
    return entries


def _field(line, number, name, kinds, *, nullable=True):
    value = line.get(name)
    if value is None and nullable:
        return None
    if not isinstance(value, kinds) or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        raise _refuse("LINE_FIELD_INVALID", f"line {number}: {name!r} is not valid", line=number, field=name)
    return value


def _claims(line, number) -> dict:
    """What a line says about how it was produced: strings or nothing, never read as code."""
    claims = {"origin": _field(line, number, "origin", str), "mode": _field(line, number, "mode", str)}
    producer = line.get("producer")
    if producer is not None and not isinstance(producer, dict):
        raise _refuse("LINE_FIELD_INVALID", f"line {number}: 'producer' must be an object", line=number, field="producer")
    for name in CLAIMED_IN_PRODUCER:
        claims[name] = _field(producer or {}, number, name, str)
    return claims


def _trace(line, number):
    trace = line.get("trace")
    if trace is None:
        return None
    if not isinstance(trace, list) or not all(isinstance(step, dict) and isinstance(step.get("kind"), str) for step in trace):
        raise _refuse(
            "LINE_FIELD_INVALID", f"line {number}: 'trace' must be a list of steps, each an object with a 'kind'", line=number, field="trace"
        )
    return trace


def _decoded(raw: bytes, source_path) -> str:
    name = str(source_path)
    if Path(source_path).suffix.lower() in SERIALIZED_SUFFIXES or raw.startswith(SERIALIZED_MAGIC):
        raise _refuse(
            "SOURCE_SERIALIZED",
            "the source is a serialized object (pickle, joblib or an array dump); an import adopts JSON Lines and loads nothing",
            source=name,
        )
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse("SOURCE_NOT_UTF8", "the source is not valid UTF-8", source=name) from None


def _checked_lines(raw: bytes, source_path, partition: str, keys: list, partition_of: dict):
    """(entries by key, claims of every line): the lines of the source, each checked, joined to the population by key."""
    expected = set(keys)
    cases_listed = {case_id for case_id, _ in keys}
    entries, claims, count = {}, [], 0
    for number, text in enumerate(_decoded(raw, source_path).splitlines(), start=1):
        if not text.strip():
            continue
        count += 1
        try:
            line = canonical.loads(text)
        except InvalidInputError:
            raise _refuse("LINE_NOT_JSON", f"line {number} of the source is not JSON", line=number) from None
        if not isinstance(line, dict):
            raise _refuse("LINE_NOT_AN_OBJECT", f"line {number} of the source is not a JSON object", line=number)
        case_id = _field(line, number, "case_id", str, nullable=False)
        repeat = line.get("repeat")
        if type(repeat) is not int or repeat < 0:
            raise _refuse("LINE_FIELD_INVALID", f"line {number}: 'repeat' must be a non-negative integer", line=number, field="repeat")
        status = line.get("observation_status")
        if status not in ITEM_STATUSES:
            raise _refuse(
                "OBSERVATION_STATUS_UNKNOWN",
                f"line {number}: observation_status {status!r} is not one of {', '.join(ITEM_STATUSES)}",
                line=number,
                observation_status=status if isinstance(status, str) else None,
                allowed=list(ITEM_STATUSES),
            )
        raw_answer = _field(line, number, "raw_answer", str)
        final_answer = line.get("final_answer")
        if final_answer is not None and not isinstance(final_answer, dict):
            raise _refuse("LINE_FIELD_INVALID", f"line {number}: 'final_answer' must be a JSON object", line=number, field="final_answer")
        trace = _trace(line, number)
        claims.append(_claims(line, number))
        if raw_answer is not None and final_answer is not None:
            raise _refuse(
                "ANSWER_AMBIGUOUS", f"line {number} holds both raw_answer and final_answer", case_id=case_id, repeat=repeat, line=number
            )
        if status == "produced" and raw_answer is None and final_answer is None:
            raise _refuse("PRODUCED_WITHOUT_ANSWER", f"line {number}: {case_id} is produced and holds no answer", case_id=case_id, repeat=repeat, line=number)
        key = (case_id, repeat)
        if key not in expected:
            if case_id not in partition_of:
                problem = "unknown_case"
            elif partition_of[case_id] != partition:
                problem = "other_partition"
            elif case_id not in cases_listed:
                problem = "not_in_population"
            else:
                problem = "repeat_out_of_range"
            raise _refuse(
                "EPISODE_OUTSIDE_POPULATION",
                f"line {number}: ({case_id}, repeat {repeat}) is not an Episode of the population",
                case_id=case_id,
                repeat=repeat,
                line=number,
                problem=problem,
            )
        if key in entries:
            raise _refuse("EPISODE_DUPLICATE", f"({case_id}, repeat {repeat}) appears twice in the source", case_id=case_id, repeat=repeat, line=number)
        produced = status == "produced"
        entries[key] = {
            "case_id": case_id,
            "repeat": repeat,
            "status": status,
            "answer_given_as": ("raw_answer" if raw_answer is not None else "final_answer") if produced else None,
            "raw_answer": raw_answer if produced else None,
            "final_answer": final_answer if produced else None,
            "trace": trace,
        }
    absent = sorted(expected - set(entries))
    if absent:
        raise _refuse(
            "POPULATION_EPISODE_ABSENT",
            f"({absent[0][0]}, repeat {absent[0][1]}) is an Episode of the population and is absent from the source",
            case_id=absent[0][0],
            repeat=absent[0][1],
            absent=len(absent),
        )
    return entries, claims, count


def _producer(claims: list) -> dict:
    """What the import says about how the answers were made: `declared` when every line says the same, otherwise `unknown`."""
    producer = {}
    for field, place in PRODUCER_FIELDS.items():
        key = None if place is None else place[-1]
        values = {claim[key] for claim in claims} if key else {None}
        if key and len(values) == 1 and None not in values:
            producer[field] = {"value": next(iter(values)).strip(), "origin": DECLARED}
        else:
            producer[field] = {"value": None, "origin": UNKNOWN}
    return producer


def normalized(entries: dict) -> bytes:
    return b"".join(canonical.dumps(entries[key]) + b"\n" for key in sorted(entries))


JSONL_CHECKS = (
    "source_is_data_not_a_serialized_object",
    "source_is_utf8_json_lines",
    "population_episodes_in_one_partition_of_the_protocol",
    "observation_status_known",
    "produced_lines_hold_one_answer",
    "episodes_within_the_population",
    "episodes_unique",
    "population_covered",
)
LOG_CHECKS = (
    "source_is_read_through_inspects_public_log_api",
    "population_episodes_in_one_partition_of_the_protocol",
    "log_samples_within_the_population",
    "log_samples_unique",
    "population_episodes_absent_from_the_log_are_missing",
)


def _report(source_ref, population_ref, partition, count, keys, entries, *, log: bool = False) -> dict:
    statuses = [entry["status"] for entry in entries.values()]
    return {
        "report": "import_validation/1",
        "source_format": "inspect_log" if log else "jsonl",
        "source_sha256": source_ref["sha256"],
        "population_sha256": population_ref["sha256"],
        "partition": partition,
        "samples_read" if log else "lines_read": count,
        "population_episodes": len(keys),
        "execution_status_counts": {status: statuses.count(status) for status in ITEM_STATUSES},
        "checks": [{"check": check, "result": "passed"} for check in (LOG_CHECKS if log else JSONL_CHECKS)],
    }


def import_agent(
    study: Path, source: Path, population: Path, request_id: str, *, examples_dir: Path | None = None, read_sequence: int | None = None
) -> tuple[dict, bool]:
    """Import (or replay) one request under the Study's writer lock; return the Attempt manifest and whether it was recorded already."""
    study = Path(study)
    study_write.check_arguments(COMMAND, read_sequence, request_id)
    layout.read_spec(study)  # a folder that is no Study is refused before a lock file is created in it
    if is_log(source):
        require_inspect()  # before the lock, and before anything is read or written
    with study_write.locked(study, COMMAND, request_id, read_sequence=read_sequence, has_attempt=True) as write:
        return _import_locked(study, write, Path(source), Path(population), request_id, examples_dir=examples_dir)


def _import_locked(study, write, source, population_path, request_id, *, examples_dir):
    spec = layout.read_spec(study)
    layout.require_domain(spec, DOMAIN, COMMAND)
    examples = data.resolve_examples_dir(examples_dir)
    workload_name = spec["workload"]
    data.verify_workload_files(examples, workload_name)  # the Workload's other files and notices: the live database is never opened
    study_refs = [*spec["dataset_refs"], *(entry["ref"] for entry in spec["artifacts"])]
    for ref in study_refs:
        artifacts.read_verified(study, ref)
    by_role = {entry["ref"]["role"]: entry["ref"] for entry in spec["artifacts"]}
    workload = load_workload(examples / workload_name)
    dataset_sha = dataset_sha256(spec)  # the Study's own copy, read back above: the live database is never opened or hashed

    source_bytes = _read(source, "SOURCE_NOT_FOUND", "source")
    population_bytes = _read(population_path, "POPULATION_NOT_FOUND", "population")
    partition_of = layout.partition_of(artifacts.read_verified(study, by_role["memberships"]), "case_id")

    loose = _loose_json(population_bytes)
    episodes = _loose_episodes(loose)
    partitions = {partition_of.get(e["case_id"]) for e in episodes}
    log_import = is_log(source)
    model, configuration = _log_identity(source) if log_import else (_loose_model(source_bytes), UNKNOWN)
    # The request: every element of the identity, with the import's value or `unknown`.
    effective_config = {
        "command": COMMAND,
        "workload": workload_name,
        "mode": MODE,
        "partition": partitions.pop() if episodes and len(partitions) == 1 and None not in partitions else None,
        "configuration": configuration,
        "model": model,
        "repeats": max(e["repeat"] for e in episodes) + 1 if episodes else UNKNOWN,
        "protocol": {"protocol_id": spec["protocol_id"], "protocol_digest": spec["protocol_digest"]},
        "input_digests": {
            "dataset": dataset_sha,
            "source": canonical.sha256_hex(source_bytes),
            "population": canonical.sha256_hex(population_bytes),
        },
    }
    code_environment = environment.code_environment()
    recorded = attempts.replayed(study, write, request_id, effective_config, code_environment)
    if recorded is not None:
        return recorded, True

    protocol = protocol_content(workload, dataset_sha256=dataset_sha)
    protocol_check.require_unchanged(spec, canonical.digest(protocol), message=PROTOCOL_CHANGED_MESSAGE, stage="request")

    partition, keys = _checked_population(population_bytes, population_path, partition_of)
    declared_log = None
    if log_import:
        from hypotrail.agentic import inspect_log

        log = inspect_log.read(source)
        episodes, count = inspect_log.checked_episodes(log, keys, partition, partition_of)
        entries = log_entries(episodes, inspect_log.usage_by_key(log))
        producer, declared_log = _log_producer(inspect_log.header_of(log))
    else:
        entries, claims, count = _checked_lines(source_bytes, source, partition, keys, partition_of)
        producer = _producer(claims)
    effective_config = {**effective_config, "partition": partition, "repeats": max(r for _, r in keys) + 1}
    import_time = now()
    effective_config = {**effective_config, "import_time": import_time, "producer": producer}
    if declared_log is not None:
        effective_config["log"] = declared_log

    def produce(recording: attempts.Recording) -> attempts.Produced:
        folder, writes = recording.folder, recording.writes
        original = Path(source).name or "source.jsonl"
        source_ref = writes.publish(
            f"{folder}/source/{original}", source_bytes, media_type="application/zip" if log_import else "application/jsonl", role="import_source"
        )
        population_ref = writes.publish(f"{folder}/population.json", population_bytes, media_type="application/json", role="import_population")
        report_ref = writes.publish_record(
            f"{folder}/validation_report.json", _report(source_ref, population_ref, partition, count, keys, entries, log=log_import), role="validation_report"
        )
        recording.observations(
            OBSERVATIONS_NAME,
            normalized(entries),
            [entry["status"] for entry in entries.values()],
            media_type="application/jsonl",
            domain=DOMAIN,
            origin="imported",
            population_ref=population_ref,
            raw_refs=[source_ref],
            provenance={
                "produced_by": "external",
                "partition": partition,
                "import_time": import_time,
                **producer,
                **({} if declared_log is None else {"log": declared_log}),
            },
            unknown_fields=[field for field, entry in producer.items() if entry["origin"] == UNKNOWN]
            + [f"log.{name}" for name, entry in (declared_log or {}).items() if entry["origin"] == UNKNOWN],
        )
        return attempts.Produced(inputs=[source_ref, population_ref], outputs=[report_ref], effective_config=effective_config)

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
    )
    return terminal, False
