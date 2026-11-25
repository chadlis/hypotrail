"""`run ml`: one Configuration, one Partition, one Attempt recorded in a Study.

The order is fixed, and nothing is computed before the checks that precede it:

1. the Workload's data is verified against its lock (`DATA_INTEGRITY`, exit 3: no Attempt is written);
2. every Study artifact the Attempt reads (dataset, population, References) is read back against its
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

After the Study's first Exposure, an Attempt whose Configuration the freeze record does not hold is marked
`check_informed`; it is not refused (`hypotrail.core.exposure`).
"""

import csv
import datetime
import io
import json
import shutil
from pathlib import Path

from hypotrail.core import artifacts, attempts, canonical, data, environment, exposure, protocol_check, study_write
from hypotrail.core import study as layout
from hypotrail.core.errors import HypotrailError, InvalidInputError
from hypotrail.ml.configuration import checked_configuration
from hypotrail.ml.declaration import RidgeConfiguration, SeasonalConfiguration, load_declaration, plain
from hypotrail.ml.metrics import declared_partition
from hypotrail.ml.partitions import TRAIN
from hypotrail.ml.predictions import PARAMETERS_NAME, PREDICTIONS_NAME
from hypotrail.ml.study import DOMAIN, MODE, PROTOCOL_CHANGED_MESSAGE, protocol_content

COMMAND = study_write.RUN_ML
OBSERVATIONS_COLUMNS = ["row_id", "status", "reason", "y_pred_raw", "y_pred"]


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


def run_ml(
    study: Path,
    config_id: str,
    partition: str,
    request_id: str,
    *,
    retry_of: str | None = None,
    examples_dir: Path | None = None,
    read_sequence: int | None = None,
) -> tuple[dict, bool]:
    """Run (or replay) one request under the Study's writer lock; a second writer is refused at once."""
    study = Path(study)
    study_write.check_arguments(COMMAND, read_sequence, request_id)
    layout.read_spec(study)  # a folder that is no Study is refused before a lock file is created in it
    with study_write.locked(study, COMMAND, request_id, read_sequence=read_sequence, has_attempt=True) as write:
        return _run_locked(study, write, config_id, partition, request_id, retry_of=retry_of, examples_dir=examples_dir)


def _run_locked(
    study: Path,
    write: study_write.Write,
    config_id: str,
    partition: str,
    request_id: str,
    *,
    retry_of: str | None = None,
    examples_dir: Path | None = None,
) -> tuple[dict, bool]:
    """Run (or replay) one request; return the Attempt manifest and whether it was recorded already."""
    spec = layout.read_spec(study)
    layout.require_domain(spec, DOMAIN, COMMAND)
    examples = data.resolve_examples_dir(examples_dir)
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
    recorded = attempts.replayed(study, write, request_id, effective_config, code_environment)
    if recorded is not None:
        return recorded, True

    protocol = protocol_content(
        declaration,
        dataset_sha256=dataset_sha,
        memberships_sha256=by_role["memberships"]["sha256"],
        references_sha256=by_role["references"]["sha256"],
    )
    protocol_check.require_unchanged(spec, canonical.digest(protocol), message=PROTOCOL_CHANGED_MESSAGE, stage="request")

    def produce(recording: attempts.Recording) -> attempts.Produced:
        folder, writes = recording.folder, recording.writes
        declaration_ref = writes.publish(
            f"{folder}/workload.json", (source / "workload.json").read_bytes(), media_type="application/json", role="workload_declaration"
        )
        scratch = study / layout.SCRATCH_DIR / recording.attempt_id
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
            raw_refs = [writes.publish_file(scratch / name, f"{folder}/{name}", media_type=layout.media_type_of(name), role=role) for name, role in raw_files]
            predictions = _rows((scratch / PREDICTIONS_NAME).read_bytes())
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        items = [row["row_id"] for row in _rows(artifacts.read_verified(study, by_role["memberships"])) if row["partition"] == partition]
        normalized = _normalized(items, predictions)
        recording.observations(
            "observations.csv",
            normalized,
            [row["status"] for row in _rows(normalized)],
            media_type="text/csv",
            domain=DOMAIN,
            origin="generated",
            population_ref=by_role["memberships"],
            raw_refs=raw_refs,
            provenance={"produced_by": "hypotrail", "configuration": config_id, "partition": partition},
            unknown_fields=[],
        )
        return attempts.Produced(
            inputs=[declaration_ref], outputs=raw_refs, effective_config={**effective_config, "effective_parameters": parameters}
        )

    terminal = attempts.record(
        study,
        write,
        request_id=request_id,
        operation="execute",
        mode=MODE,
        effective_config=effective_config,
        code_environment=code_environment,
        input_refs=study_refs,
        produce=produce,
        retry_of=retry_of,
        # a Configuration whose digest the freeze record of the Study's first Exposure does not hold (hypotrail.core.exposure)
        marks=exposure.marks(study, [{"effective_config": effective_config}]),
    )
    return terminal, False
