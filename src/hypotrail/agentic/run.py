"""`run agent`: one Configuration of the tool-using agent Track run as one native Attempt of a Study.

It records the Attempt from the Inspect log of the run, the way `run ml` records a Bike Attempt: the same request
identity and replay, the same running-then-terminal manifest, the same atomic artifacts, the same writer lock, `status`
and `recover`. It has two Modes:

- `scripted_fixture` runs the Workload's technical scenarios with Inspect's mock model and the real tools
  (`hypotrail.agentic.fixture`) and records the scenario Attempt. Its statuses and counters are kept as a labelled
  self-check that carries the banner; it is neither assessed nor compared. It never reads the key.
- `llm_live` runs one Configuration on one Partition (`dev` or `public_check`), optionally on a subset of its Cases,
  for 1 to 3 Repeats, against an explicit Anthropic model. It is opt-in (the Mode and the key) and bounded: the
  Partition's Cases times 3 Episodes at most, which follows from the refusals below.

The order is fixed, and nothing is run before the checks that precede it (chadlis/hypotrail#74, Tightened K):

1. the flag checks (exit 2): the flags of the other Mode, the Configuration, the Partition, the Repeats, the model and
   the Cases are checked against the Workload's declaration, before the key is read and before Inspect is imported;
2. the writer lock (`STUDY_LOCKED`, exit 6), then `RETRY_OF_UNKNOWN` (exit 2);
3. the request is identified (`hypotrail.core.requests`): the same `request_id` with the same request returns the
   recorded Attempt here, with no key, no Inspect and no provider call; with another request it is `REQUEST_CONFLICT`
   (exit 6). The identity is taken before the data is verified, so a changed live database is a changed input;
4. the Workload's data is verified against its lock (`DATA_INTEGRITY`, exit 3) and every Study artifact read is read
   back against its digest (`ARTIFACT_INTEGRITY`, exit 3);
5. for a new request, the Protocol of the Workload must still be the Study's (`PROTOCOL_CHANGED`, exit 3);
6. Inspect must be importable (`INSPECT_UNAVAILABLE`, exit 5), then, for `llm_live`, the key must be present
   (`LIVE_UNAVAILABLE`, exit 5);
7. the manifest is written `running`; the run is made with Inspect writing its log outside the Study; the Chinook file
   is hashed before and after (`DATABASE_CHANGED`, exit 3); the log is scanned for the key and read through Inspect's
   public log API; the artifacts are published atomically; the terminal manifest is written last.

An `llm_live` Attempt never keeps the key. Every file the Attempt writes, its manifests included, is scanned for it
before it is written (`SECRET_IN_OUTPUT`, exit 4): a hit before the `running` manifest writes nothing, a later hit
ends the Attempt `failed`. After the run, failed or not, the whole Study folder is scanned, and a hit elsewhere is a warning that
changes no recorded Attempt (after a failed run it is on stderr and in the error's `details.warnings`).

An Attempt stopped between the running manifest and the terminal one keeps what it published and is never shown as
completed; `recover` records it `interrupted`, with `outcome_unknown: true` for `llm_live`.

This module imports neither Inspect nor scikit-learn at load time: a replay and every refusal that precedes the
Inspect check run where Inspect cannot be imported.
"""

import json
import os
import tempfile
import uuid
from pathlib import Path

from hypotrail.agentic.declaration import load_workload, read_json
from hypotrail.agentic.study import DOMAIN, protocol_content
from hypotrail.core import artifacts, canonical, contracts, data, environment, exposure, lock, requests
from hypotrail.core import live as core_live
from hypotrail.core import study as layout
from hypotrail.core.attempts import ITEM_STATUSES, now, record_failure, verify_recorded
from hypotrail.core.errors import HypotrailError, IntegrityError, InvalidInputError

COMMAND = "run agent"
FIXTURE, LIVE = "scripted_fixture", "llm_live"
MODES = (FIXTURE, LIVE)
PARTITIONS = ("dev", "public_check")
REPEATS_BOUNDS = (1, 3)
FIXTURE_MODEL = "mockllm/model"
FLAGS_OF_LIVE = {"partition": "--partition", "repeats": "--repeats", "model": "--model", "cases": "--cases"}
INSPECT_STAGE = "capability"
LOG_NAME = "inspect"
POPULATION_NAME = "population.json"
OBSERVATIONS_NAME = "observations.jsonl"
SELF_CHECK_NAME = "self_check.json"


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="config", details=details)


# --- The flag checks ----------------------------------------------------------------------------------------------------------------


def _checked_flags(workload, mode, config, partition, repeats, model, cases) -> dict:
    """The request as the flags and the Workload's declaration fix it, or a refusal of exit 2. Nothing is read but the declaration."""
    given = {"partition": partition, "repeats": repeats, "model": model, "cases": cases}
    if mode == FIXTURE:
        for name, value in given.items():
            if value is not None:
                raise InvalidInputError(
                    "UNSUPPORTED_CAPABILITY",
                    f"{FLAGS_OF_LIVE[name]} belongs to the {LIVE} Mode: the {FIXTURE} Mode runs the Workload's scenarios, not its Cases (no fallback)",
                    stage="config",
                    details={"flag": FLAGS_OF_LIVE[name], "mode": mode},
                )
    else:
        if partition is None:
            raise _refuse("PARTITION_REQUIRED", f"--partition is required with --mode {LIVE}", flag="--partition")
        if repeats is None:
            raise _refuse("REPEATS_REQUIRED", f"--repeats is required with --mode {LIVE}", flag="--repeats")
        core_live.require_model(model)  # MODEL_REQUIRED: explicit, anthropic/<model>, no default
    system_text = workload.system_text(config)  # CONFIGURATION_NOT_DECLARED
    configuration = {"id": config, "declared": workload.declaration["configurations"][config], "system_text": system_text}
    if mode == FIXTURE:
        if workload.scenarios_path is None:
            raise InvalidInputError(
                "SCENARIOS_NOT_DECLARED",
                f"the Workload {workload.workload_id!r} declares no scenarios",
                stage="fixture",
                details={"path": "scenarios"},
            )
        read_json(workload.scenarios_path, stage="fixture", noun="scenarios file", key="scenarios")
        return {"configuration": configuration, "partition": None, "cases": None, "repeats": 1, "model": FIXTURE_MODEL, "cases_file": None}
    if partition not in PARTITIONS:
        raise _refuse("PARTITION_NOT_ALLOWED", f"a run takes the Partition dev or public_check, not {partition!r}", partition=partition, allowed=list(PARTITIONS))
    low, high = REPEATS_BOUNDS
    if not isinstance(repeats, int) or isinstance(repeats, bool) or not low <= repeats <= high:
        raise _refuse("REPEATS_OUT_OF_BOUNDS", f"--repeats is an integer from {low} to {high}, not {repeats!r}", repeats=repeats, minimum=low, maximum=high)
    in_partition = [case["case_id"] for case in workload.cases(partition)]  # PARTITION_NOT_DECLARED
    asked = list(cases) if cases is not None else None
    if asked is not None:
        repeated = sorted({c for c in asked if asked.count(c) > 1})
        if repeated:
            raise _refuse("CASE_REPEATED", f"a Case is given twice: {', '.join(repeated)}", cases=repeated)
        outside = [c for c in asked if c not in in_partition]
        if outside:
            raise _refuse(
                "CASE_NOT_IN_PARTITION", f"not Cases of the Partition {partition!r}: {', '.join(outside)}", cases=outside, partition=partition
            )
    selected = in_partition if asked is None else [c for c in in_partition if c in set(asked)]  # the Partition's order: one spelling
    return {
        "configuration": configuration,
        "partition": partition,
        "cases": selected,
        "repeats": repeats,
        "model": model,
        "cases_file": workload.cases_path(partition),
    }


# --- What is written, scanned for the key first -----------------------------------------------------------------------------------


class _Writes:
    """The Attempt's writes. With a `secret`, each file is scanned for it before it is written (`SECRET_IN_OUTPUT`, exit 4)."""

    def __init__(self, study: Path, secret: str | None):
        self.study, self.secret = study, secret

    def _scanned(self, data, where: str) -> None:
        if self.secret and self.secret.encode() in data:
            raise leak([where])

    def replace(self, relative: str, data) -> None:
        self._scanned(data, relative)
        artifacts.replace_bytes(self.study, relative, data)

    def publish(self, relative: str, data, *, media_type: str, role: str) -> dict:
        self._scanned(data, relative)
        return artifacts.publish_bytes(self.study, relative, data, media_type=media_type, role=role)

    def publish_record(self, relative: str, record: dict, *, role: str) -> dict:
        return self.publish(relative, canonical.dumps(record), media_type="application/json", role=role)

    def publish_file(self, source: Path, relative: str, *, media_type: str, role: str) -> dict:
        return self.publish(relative, Path(source).read_bytes(), media_type=media_type, role=role)


def leak(files: list) -> HypotrailError:
    return HypotrailError(
        "SECRET_IN_OUTPUT",
        f"the API key was found in what this Attempt would write: {', '.join(files)}; nothing holding it was kept",
        stage="live",
        details={"files": files},
    )


def _warnings_of(study: Path, secret: str | None) -> list:
    """What a scan of the whole Study finds after the run: a warning for each file holding the key, never a change to an Attempt."""
    if not secret:
        return []
    from hypotrail.agentic import live as agentic_live

    try:
        found = agentic_live.scan_for_secret(study, secret)
    except HypotrailError as error:  # a log that cannot be fully scanned is said, not reported clean
        return [{"code": error.code, "message": error.message, "file": ", ".join(error.details.get("files", []))}]
    return [
        {"code": "SECRET_IN_STUDY", "message": f"the API key was found in {name}, outside this Attempt's artifacts; do not keep or commit it", "file": name}
        for name in found
    ]


# --- The command ----------------------------------------------------------------------------------------------------------------


def run_agent(
    study: Path,
    *,
    mode: str,
    config: str,
    request_id: str,
    partition: str | None = None,
    repeats: int | None = None,
    model: str | None = None,
    cases: list | None = None,
    retry_of: str | None = None,
    examples_dir: Path | None = None,
    environ=None,
) -> tuple[dict, bool, list]:
    """Run (or replay) one request under the Study's writer lock: (the Attempt manifest, whether it was recorded already, warnings)."""
    study = Path(study)
    if not request_id:
        raise InvalidInputError("REQUEST_ID_EMPTY", "--request-id must not be empty", stage="request", details={})
    spec = layout.read_spec(study)  # a folder that is no Study is refused before a lock file is created in it
    layout.require_domain(spec, DOMAIN, COMMAND)
    examples = Path(examples_dir) if examples_dir is not None else data.default_examples_dir()
    workload = load_workload(examples / spec["workload"])
    plan = _checked_flags(workload, mode, config, partition, repeats, model, cases)
    with lock.writer_lock(study):
        return _run_locked(study, examples, workload, mode, plan, request_id, retry_of, os.environ if environ is None else environ)


def _digest_of(path: Path):
    try:
        return data.sha256_file(path)
    except OSError:
        return None  # a file that is not there is `DATA_INTEGRITY` at the data verification, not an input of the identity


def _run_locked(study, examples, workload, mode, plan, request_id, retry_of, environ):
    spec = layout.read_spec(study)
    layout.require_domain(spec, DOMAIN, COMMAND)
    if retry_of is not None and retry_of not in layout.attempt_ids(study):
        raise InvalidInputError(
            "RETRY_OF_UNKNOWN", f"retry_of names no Attempt of this Study: {retry_of!r}", stage="request", details={"retry_of": retry_of}
        )
    workload_name = spec["workload"]
    study_refs = [*spec["dataset_refs"], *(entry["ref"] for entry in spec["artifacts"])]
    by_role = {entry["ref"]["role"]: entry["ref"] for entry in spec["artifacts"]}
    dataset_sha = _digest_of(workload.database_path)  # the live file, before it is verified: a changed file is a changed request
    input_digests = {"dataset": dataset_sha, "population": by_role["memberships"]["sha256"], "references": by_role["references"]["sha256"]}
    if mode == FIXTURE:
        input_digests["scenarios"] = canonical.sha256_hex(workload.scenarios_path.read_bytes())
    else:
        input_digests["cases"] = canonical.sha256_hex(plan["cases_file"].read_bytes())
    effective_config = {
        "command": COMMAND,
        "workload": workload_name,
        "mode": mode,
        "partition": plan["partition"],
        "cases": plan["cases"],
        "repeats": plan["repeats"],
        "model": plan["model"],
        "configuration": plan["configuration"],
        "protocol": {"protocol_id": spec["protocol_id"], "protocol_digest": spec["protocol_digest"]},
        "input_digests": input_digests,
    }
    code_environment = environment.code_environment()
    requested = requests.identity(effective_config, code_environment)
    recorded = layout.find_by_request(study, request_id)
    if recorded is not None:
        differs = requests.differences(requests.identity(recorded["effective_config"], recorded["code_environment"]), requested)
        if differs:
            raise requests.conflict(request_id, recorded["attempt_id"], differs)
        verify_recorded(study, recorded)
        return recorded, True, []  # no key, no Inspect, no provider, no scan

    data.verify_workloads(examples, [workload_name])
    for ref in study_refs:
        artifacts.read_verified(study, ref)
    protocol = protocol_content(workload, dataset_sha256=dataset_sha)
    if canonical.digest(protocol) != spec["protocol_digest"]:
        raise IntegrityError(
            "PROTOCOL_CHANGED",
            "the Workload's Protocol is no longer the one of this Study (Cases, References, answer schema, database or primary Criterion)",
            stage="request",
            details={"expected_protocol_digest": spec["protocol_digest"], "actual_protocol_digest": canonical.digest(protocol)},
        )
    from hypotrail.agentic import imports

    imports.require_inspect(INSPECT_STAGE, COMMAND)
    api_key = core_live.read_api_key(environ) if mode == LIVE else None

    writes = _Writes(study, api_key)
    attempt_id = str(uuid.uuid4())
    manifest_path = layout.attempt_manifest_path(attempt_id)
    manifest = {
        "kind": "attempt",
        "schema_version": "attempt/1",
        "attempt_id": attempt_id,
        "request_id": request_id,
        "operation": "execute",
        "mode": mode,
        "technical_status": "running",
        "started_at": now(),
        "finished_at": None,
        "effective_config": effective_config,
        "effective_config_digest": canonical.digest(effective_config),
        "input_refs": study_refs,
        "code_environment": code_environment,
        "outcome_unknown": False,
        "retry_of": retry_of,
        # a Configuration whose digest the freeze record of the Study's first Exposure does not hold (hypotrail.core.exposure)
        **exposure.marks(study, [{"effective_config": effective_config}]),
    }
    contracts.validate(manifest)
    writes.replace(manifest_path, canonical.dumps(manifest))  # a hit here writes nothing and leaves no Attempt
    try:
        terminal = _record(study, writes, workload, examples, manifest, plan, api_key)
        writes.replace(manifest_path, canonical.dumps(terminal))
    except Exception as error:
        record_failure(study, manifest_path, manifest, error)
        # the scan of the Study is made whether or not the run failed (#74): what it finds travels with the error
        error.scan_warnings = _warnings_of(study, api_key)
        if isinstance(error, HypotrailError) and error.scan_warnings:
            error.details["warnings"] = error.scan_warnings
        raise
    return terminal, False, _warnings_of(study, api_key)


# --- The run, and the artifacts it leaves -----------------------------------------------------------------------------------------


def _usage(sample) -> dict | None:
    """What the log states for one Episode (latency, tokens, cost); a figure it does not give is None, never zero (CMP-06)."""
    from hypotrail.agentic import live as agentic_live

    if sample is None:
        return None
    figures = agentic_live.usage_of(sample)
    return {"latency_seconds": figures["latency_seconds"], "tokens": figures["total_tokens"], "cost": figures["cost"]}


def _sha256(path: Path) -> str:
    return data.sha256_file(path)


def _changed(before: str, after: str) -> IntegrityError:
    return IntegrityError(
        "DATABASE_CHANGED",
        "the Workload's database changed during the run",
        stage="run",
        details={"sha256_before": before, "sha256_after": after},
    )


def _record(study: Path, writes: _Writes, workload, examples: Path, manifest: dict, plan: dict, api_key) -> dict:
    """Run the Episodes, publish what they left and return the terminal manifest."""
    from hypotrail.agentic import imports, inspect_log, projection, runner
    from hypotrail.agentic import limits as limits_module
    from hypotrail.agentic import live as agentic_live

    mode = manifest["mode"]
    attempt_id = manifest["attempt_id"]
    folder = f"{layout.ATTEMPTS_DIR}/{attempt_id}"
    effective_config = manifest["effective_config"]
    declaration_ref = writes.publish(
        f"{folder}/workload.json", (workload.directory / "workload.json").read_bytes(), media_type="application/json", role="workload_declaration"
    )
    limits = limits_module.EpisodeLimits()
    before = _sha256(workload.database_path)
    with tempfile.TemporaryDirectory(prefix="hypotrail-run-") as scratch:  # Inspect's log stays outside the Study until it is scanned and read
        out = Path(scratch) / "run"
        if mode == LIVE:
            model = agentic_live.prepared_model(plan["model"], api_key)
            location = runner.run_episodes(
                workload.cases(plan["partition"], plan["cases"]),
                workload=workload,
                configuration=plan["configuration"]["id"],
                model=model,
                repeats=plan["repeats"],
                log_dir=out / LOG_NAME,
                limits=limits,
                reasoning_effort=agentic_live.REASONING_EFFORT,
            )
            after = _sha256(workload.database_path)
            if before != after:
                raise _changed(before, after)
            leaked = agentic_live.scan_for_secret(out, api_key)
            if leaked:
                raise leak(leaked)
            keys = [(case, repeat) for case in plan["cases"] for repeat in range(plan["repeats"])]
            agentic_live.record_execution(
                location=location, out_dir=out, limits=limits, database_sha256={"before": before, "after": after}
            )
            self_check = None
        else:
            from hypotrail.agentic import fixture

            summary = fixture.run_fixture(workload_dir=workload.directory, out_dir=out, configuration=plan["configuration"]["id"], limits=limits)
            location = str(out / summary["inspect_log"])
            scenarios = fixture.load_scenarios(workload)
            keys = [(scenario["case"]["case_id"], 0) for scenario in scenarios]
            self_check = {
                "mode": fixture.MODE,
                "banner": fixture.BANNER,
                "scenarios": summary["scenarios"],
                "counts": summary["counts"],
                "tool_errors": summary["tool_errors"],
                "business_case_outputs": summary["business_case_outputs"],
            }
        log = inspect_log.read(location)  # Inspect's public log API, never a parser of its storage format
        episodes = projection.project_episodes(log, expected=keys)
        samples = {(str(s.id), s.epoch - 1): s for s in log.samples or []}
        entries = imports.log_entries(episodes, {key: _usage(sample) for key, sample in samples.items()})
        population = canonical.dumps({"episodes": [{"case_id": c, "repeat": r} for c, r in sorted(keys)]})
        population_ref = writes.publish(f"{folder}/{POPULATION_NAME}", population, media_type="application/json", role="run_population")
        log_ref = writes.publish_file(Path(location), f"{folder}/{LOG_NAME}/{Path(location).name}", media_type="application/zip", role="inspect_log")
        run_ref = writes.publish_file(out / "run.json", f"{folder}/run.json", media_type="application/json", role="run_record")
        published = [log_ref, run_ref]
        if self_check is not None:
            published.append(writes.publish_record(f"{folder}/{SELF_CHECK_NAME}", self_check, role="self_check"))
        normalized_ref = writes.publish(f"{folder}/{OBSERVATIONS_NAME}", imports.normalized(entries), media_type="application/jsonl", role="observations")
        reported = agentic_live.served_models(log)  # what the provider says, as `run.json`'s `served_models`: never the requested name
        served_model = ", ".join(reported) if reported else None
        observation_set = {
            "kind": "observations",
            "schema_version": "observations/1",
            "observation_set_id": str(uuid.uuid4()),
            "attempt_id": attempt_id,
            "domain": DOMAIN,
            "origin": "generated",
            "mode": mode,
            "population_ref": population_ref,
            "raw_refs": [log_ref],
            "normalized_ref": normalized_ref,
            "provenance": {
                "produced_by": "hypotrail",
                "configuration": plan["configuration"]["id"],
                "partition": plan["partition"],
                "model": plan["model"],
                "served_model": served_model,
            },
            "unknown_fields": [],
        }
        contracts.validate(observation_set)
        observation_set_ref = writes.publish_record(f"{folder}/observation_set.json", observation_set, role="observation_set")
        effective = limits_module.effective_limits(log)
        effective_config = {
            **effective_config,
            "served_model": served_model,
            "tools": agentic_live.tool_names(log),
            "limits": effective,
            "limit_notes": agentic_live.limit_notes(effective),
            "effective_parameters": agentic_live.effective_parameters(log),
        }
    statuses = [entry["status"] for entry in entries.values()]
    terminal = {
        **manifest,
        "technical_status": "completed",
        "finished_at": now(),
        "effective_config": effective_config,
        "effective_config_digest": canonical.digest(effective_config),
        "input_refs": [*manifest["input_refs"], declaration_ref],
        "output_refs": [population_ref, *published, normalized_ref, observation_set_ref],
        "item_counts": {status: statuses.count(status) for status in ITEM_STATUSES},
    }
    contracts.validate(terminal)
    return terminal
