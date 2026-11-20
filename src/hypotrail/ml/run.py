"""`run ml`: one Configuration, one Partition, one Attempt recorded in a Study.

The order is fixed, and nothing is computed before the checks that precede it:

1. the Workload's data is verified against its lock (`DATA_INTEGRITY`, exit 3: no Attempt is written);
2. every Study artifact the run reads (dataset, population, References) is read back against its
   digest (`ARTIFACT_INTEGRITY`, exit 3);
3. the Configuration and the Partition are checked against the declaration (exit 2);
4. the request is identified (`hypotrail.core.requests`): the same `request_id` with the same
   request returns the recorded Attempt, with neither a fit nor a prediction; with another request
   it is `REQUEST_CONFLICT` (exit 6) and nothing is written;
5. for a new request, the Protocol of the Workload must still be the Study's (`PROTOCOL_CHANGED`,
   exit 3): a Configuration may change after `init`, the Protocol may not;
6. the manifest is written `running`; the scratch files of the Track's own writers are published
   atomically (predictions, parameters, normalized observations, the Observation set record); the
   manifest is replaced by the terminal one, last.

An Attempt stopped between the running manifest and the terminal one keeps what it published and
is never shown as completed.
"""

import csv
import datetime
import io
import json
import shutil
import uuid
from pathlib import Path

from hypotrail.core import artifacts, canonical, contracts, data, environment, lock, requests
from hypotrail.core.attempts import ITEM_STATUSES, now as _now, record_failure as _record_failure, verify_recorded as _verify_recorded
from hypotrail.core import study as layout
from hypotrail.core.errors import HypotrailError, IntegrityError, InvalidInputError
from hypotrail.ml.configuration import checked_configuration
from hypotrail.ml.declaration import RidgeConfiguration, SeasonalConfiguration, load_declaration, plain
from hypotrail.ml.metrics import declared_partition
from hypotrail.ml.partitions import TRAIN
from hypotrail.ml.predictions import PREDICTIONS_NAME
from hypotrail.ml.study import DOMAIN, MODE, protocol_content

COMMAND = "run ml"
OBSERVATIONS_COLUMNS = ["row_id", "status", "reason", "y_pred_raw", "y_pred"]
PARAMETERS_NAME = "sklearn_params.json"


def _rows(data_bytes: bytes) -> list:
    return list(csv.DictReader(io.StringIO(data_bytes.decode("utf-8"), newline="")))


def _normalized(items: list, predictions: list) -> bytes:
    """One line per Item of the Partition, `produced` when the library predicted it, `missing` otherwise."""
    by_id = {row["row_id"]: row for row in predictions}
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(OBSERVATIONS_COLUMNS)
    for row_id in sorted(items):
        row = by_id.get(row_id)
        if row is None:
            writer.writerow([row_id, "missing", "not_predicted", "", ""])
        else:
            writer.writerow([row_id, "produced", "", row["y_pred_raw"], row["y_pred"]])
    return out.getvalue().encode("utf-8")


def item_counts(normalized: bytes) -> dict:
    counts = dict.fromkeys(ITEM_STATUSES, 0)
    for row in _rows(normalized):
        counts[row["status"]] += 1
    return counts


def run_ml(
    study: Path,
    config_id: str,
    partition: str,
    request_id: str,
    *,
    retry_of: str | None = None,
    examples_dir: Path | None = None,
) -> tuple[dict, bool]:
    """Run (or replay) one request under the Study's writer lock; a second writer is refused at once."""
    study = Path(study)
    if not request_id:
        raise InvalidInputError("REQUEST_ID_EMPTY", "--request-id must not be empty", stage="request", details={})
    layout.require_domain(layout.read_spec(study), DOMAIN, COMMAND)  # a folder that is no Study is refused before a lock file is created in it
    with lock.writer_lock(study):
        return _run_locked(study, config_id, partition, request_id, retry_of=retry_of, examples_dir=examples_dir)


def _run_locked(
    study: Path,
    config_id: str,
    partition: str,
    request_id: str,
    *,
    retry_of: str | None = None,
    examples_dir: Path | None = None,
) -> tuple[dict, bool]:
    """Run (or replay) one request; return the Attempt manifest and whether it was recorded already."""
    spec = layout.read_spec(study)
    examples = Path(examples_dir) if examples_dir is not None else data.default_examples_dir()
    workload = spec["workload"]
    data.verify_workloads(examples, [workload])  # T01 at this entry point: before anything is computed
    study_refs = [*spec["dataset_refs"], *(entry["ref"] for entry in spec["artifacts"])]
    for ref in study_refs:
        artifacts.read_verified(study, ref)
    by_role = {entry["ref"]["role"]: entry["ref"] for entry in spec["artifacts"]}

    source = examples / workload
    declaration = load_declaration(source)
    declared_partition(declaration, partition)
    configuration = checked_configuration(declaration, config_id)
    if retry_of is not None and retry_of not in layout.attempt_ids(study):
        raise InvalidInputError(
            "RETRY_OF_UNKNOWN",
            f"retry_of names no Attempt of this Study: {retry_of!r}",
            stage="request",
            details={"retry_of": retry_of},
        )

    dataset_sha = data.sha256_file(source / declaration.data_file)
    effective_config = {
        "command": COMMAND,
        "workload": workload,
        "mode": MODE,
        "partition": partition,
        "configuration": {"id": config_id, "declared": plain(configuration)},
        "protocol": {"protocol_id": spec["protocol_id"], "protocol_digest": spec["protocol_digest"]},
        "input_digests": {
            "dataset": dataset_sha,
            "population": by_role["memberships"]["sha256"],
            "references": by_role["references"]["sha256"],
        },
        "effective_parameters": None,
        "bounds": {"clip_min": configuration.post_processing.clip_min, "fit_partition": TRAIN},
    }
    code_environment = environment.code_environment()
    requested = requests.identity(effective_config, code_environment)

    recorded = layout.find_by_request(study, request_id)
    if recorded is not None:
        differs = requests.differences(
            requests.identity(recorded["effective_config"], recorded["code_environment"]), requested
        )
        if differs:
            raise requests.conflict(request_id, recorded["attempt_id"], differs)
        _verify_recorded(study, recorded)
        return recorded, True

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

    attempt_id = str(uuid.uuid4())
    folder = f"{layout.ATTEMPTS_DIR}/{attempt_id}"
    manifest_path = layout.attempt_manifest_path(attempt_id)
    manifest = {
        "kind": "attempt",
        "schema_version": "attempt/1",
        "attempt_id": attempt_id,
        "request_id": request_id,
        "operation": "execute",
        "mode": MODE,
        "technical_status": "running",
        "started_at": _now(),
        "finished_at": None,
        "effective_config": effective_config,
        "effective_config_digest": canonical.digest(effective_config),
        "input_refs": study_refs,
        "code_environment": code_environment,
        "outcome_unknown": False,
        "retry_of": retry_of,
    }
    contracts.validate(manifest)
    artifacts.replace_bytes(study, manifest_path, canonical.dumps(manifest))

    try:
        declaration_ref = artifacts.publish_bytes(
            study,
            f"{folder}/workload.json",
            (source / "workload.json").read_bytes(),
            media_type="application/json",
            role="workload_declaration",
        )
        scratch = study / layout.SCRATCH_DIR / attempt_id
        try:
            if isinstance(configuration, SeasonalConfiguration):
                from hypotrail.ml import baselines

                baselines.write_seasonal_baseline(source, scratch, config_id, partition)
                parameters = {"fitted": False, "period_days": configuration.period_k.days}
                raw_files = [(PREDICTIONS_NAME, "predictions")]
            else:
                assert isinstance(configuration, RidgeConfiguration)
                from hypotrail.ml import ridge

                ridge.write_outputs(source, scratch, config_id, partition)
                parameters = json.loads((scratch / PARAMETERS_NAME).read_text(encoding="utf-8"))
                raw_files = [(PREDICTIONS_NAME, "predictions"), (PARAMETERS_NAME, "effective_parameters")]
            raw_refs = [
                artifacts.publish_file(
                    study, scratch / name, f"{folder}/{name}", media_type=layout.media_type_of(name), role=role
                )
                for name, role in raw_files
            ]
            predictions = _rows((scratch / PREDICTIONS_NAME).read_bytes())
        finally:
            shutil.rmtree(study / layout.SCRATCH_DIR / attempt_id, ignore_errors=True)

        items = [row["row_id"] for row in _rows(artifacts.read_verified(study, by_role["memberships"])) if row["partition"] == partition]
        normalized = _normalized(items, predictions)
        normalized_ref = artifacts.publish_bytes(
            study, f"{folder}/observations.csv", normalized, media_type="text/csv", role="observations"
        )
        observation_set = {
            "kind": "observations",
            "schema_version": "observations/1",
            "observation_set_id": str(uuid.uuid4()),
            "attempt_id": attempt_id,
            "domain": DOMAIN,
            "origin": "generated",
            "mode": MODE,
            "population_ref": by_role["memberships"],
            "raw_refs": raw_refs,
            "normalized_ref": normalized_ref,
            "provenance": {"produced_by": "hypotrail", "configuration": config_id, "partition": partition},
            "unknown_fields": [],
        }
        contracts.validate(observation_set)
        observation_set_ref = artifacts.publish_record(
            study, f"{folder}/observation_set.json", observation_set, role="observation_set"
        )

        effective_config = {**effective_config, "effective_parameters": parameters}
        terminal = {
            **manifest,
            "technical_status": "completed",
            "finished_at": _now(),
            "effective_config": effective_config,
            "effective_config_digest": canonical.digest(effective_config),
            "input_refs": [*study_refs, declaration_ref],
            "output_refs": [*raw_refs, normalized_ref, observation_set_ref],
            "item_counts": item_counts(normalized),
        }
        contracts.validate(terminal)
        artifacts.replace_bytes(study, manifest_path, canonical.dumps(terminal))
        return terminal, False
    except Exception as error:
        _record_failure(study, manifest_path, manifest, error)
        raise
