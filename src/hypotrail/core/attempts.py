"""The Attempt recorder: how `run ml`, `import ml`, `run agent` and `import agent` record an Attempt.

Each of the four writers checks its request in its own order and supplies what differs between them: its effective_config,
its input references, the outputs it publishes and its normalized Observations. The recorder does the rest, the same way for
the four:

- `replayed`: the request identity and its check against a recorded Attempt. The same `request_id` with the same request
  returns the recorded Attempt, every artifact its manifest references read back; with another request it is
  `REQUEST_CONFLICT`;
- `record`: the `running` manifest, `write.begin()` and `write.attempt()`, the Observation set record, the Item counts and
  the terminal manifest, written last. An error inside the live process leaves a `failed` Attempt.

A writer's files are written through one of two adapters: `Plain`, or `Scanned`, which refuses a file that holds the key
before it is written.
"""

import dataclasses
import datetime
import uuid
from pathlib import Path

from hypotrail.core import artifacts, canonical, contracts, requests
from hypotrail.core import study as layout
from hypotrail.core.errors import HypotrailError, coded_error

ITEM_STATUSES = ("produced", "failed", "missing")
SCENARIO_MODE = "scripted_fixture"
SCENARIO_BANNER = "test simulation, no LLM evaluated"
"""What a `scripted_fixture` Attempt carries wherever it is shown: it tests the harness and evaluates no model.

Held here, in the core, so that `hypotrail.agentic.fixture` (which imports Inspect) and `hypotrail.report` (which never does)
say the same words.
"""


def now() -> str:
    """The time, as an ISO string in UTC: every record that holds a timestamp takes it from here (an Attempt manifest, an Assessment,
    a freeze record, an Exposure entry, a recovered Attempt)."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def record_failure(study: Path, manifest_path: str, running: dict, error: Exception) -> None:
    """An error inside this live process: the Attempt is `failed`, with finished_at and a Reason.

    Its published artifacts stay. If even this write fails, the manifest stays `running`: no state
    is invented. The Reason is the code and message of the error `coded_error` names, so a foreign
    exception, an OS error included, is named by its type only.
    """
    coded = coded_error(error)
    reason = f"{coded.code}: {coded.message}"
    failed = {**running, "technical_status": "failed", "finished_at": now(), "reason": reason}
    try:
        contracts.validate(failed)
        artifacts.replace_bytes(study, manifest_path, canonical.dumps(failed))
    except Exception:
        pass


def observation_set_id(study: Path, manifest: dict) -> str | None:
    """The ID of the Observation set an Attempt manifest names in its `output_refs`, read from that record; None when it names none.

    A terminal manifest names the one the recorder published; a `running`, `failed` or `interrupted` manifest names none, even when the record
    was published before the Attempt stopped.
    """
    refs = layout.observation_set_refs(manifest)
    if not refs:
        return None
    return layout.read_record(study, refs[0]["path"])["observation_set_id"]


def observation_set_partition(study: Path, manifest: dict) -> str | None:
    """The Partition the Observation set an Attempt manifest names holds in its `provenance`, read from that record; None when the manifest
    names none or the record names no Partition."""
    refs = layout.observation_set_refs(manifest)
    if not refs:
        return None
    return layout.read_record(study, refs[0]["path"]).get("provenance", {}).get("partition")


def verify_recorded(study: Path, manifest: dict) -> None:
    for ref in [*manifest["input_refs"], *manifest.get("output_refs", [])]:
        artifacts.read_verified(study, ref)


# --- The two adapters through which an Attempt's files are written -------------------------------------------------------------------


class Plain:
    """An Attempt's writes, each made as it is given."""

    def __init__(self, study: Path):
        self.study = study

    def scan(self, relative: str, data: bytes) -> None:
        """Nothing is refused before the `running` manifest."""

    def replace(self, relative: str, data: bytes) -> None:
        artifacts.replace_bytes(self.study, relative, data)

    def publish(self, relative: str, data: bytes, *, media_type: str, role: str) -> dict:
        return artifacts.publish_bytes(self.study, relative, data, media_type=media_type, role=role)

    def publish_record(self, relative: str, record: dict, *, role: str) -> dict:
        return artifacts.publish_record(self.study, relative, record, role=role)

    def publish_file(self, source: Path, relative: str, *, media_type: str, role: str) -> dict:
        return artifacts.publish_file(self.study, source, relative, media_type=media_type, role=role)

    def coded(self, error: Exception, manifest_path: str) -> HypotrailError:
        """The error the `failed` manifest records and the writer raises: a foreign exception by its type only."""
        return coded_error(error)


class Scanned(Plain):
    """An Attempt's writes, with a `secret`: each file is scanned for it before it is written (`SECRET_IN_OUTPUT`, exit 4)."""

    def __init__(self, study: Path, secret: str | None):
        super().__init__(study)
        self.secret = secret

    def _scanned(self, data: bytes, where: str) -> None:
        if self.secret and self.secret.encode() in data:
            raise leak([where], scanned="attempt")

    def scan(self, relative: str, data: bytes) -> None:
        """Refuse a file that holds the key before anything is written: not even the journal's `begin` entry follows."""
        self._scanned(data, relative)

    def replace(self, relative: str, data: bytes) -> None:
        self._scanned(data, relative)
        artifacts.replace_bytes(self.study, relative, data)

    def publish(self, relative: str, data: bytes, *, media_type: str, role: str) -> dict:
        self._scanned(data, relative)
        return artifacts.publish_bytes(self.study, relative, data, media_type=media_type, role=role)

    def publish_record(self, relative: str, record: dict, *, role: str) -> dict:
        return self.publish(relative, canonical.dumps(record), media_type="application/json", role=role)

    def publish_file(self, source: Path, relative: str, *, media_type: str, role: str) -> dict:
        return self.publish(relative, Path(source).read_bytes(), media_type=media_type, role=role)

    def coded(self, error: Exception, manifest_path: str) -> HypotrailError:
        """The error the `failed` manifest records and the writer raises: a foreign exception by its type only, and the key never in the Reason."""
        coded = coded_error(error)  # a foreign exception by its type only: the failed manifest and the raised error say the same
        if self.secret and self.secret in f"{coded.code}: {coded.message}":  # the Reason is the failed manifest's one new text: scanned like every file
            coded = leak([manifest_path], scanned="attempt")  # a hit is the Reason, with no message text of the error
        return coded


# What a hit says, by what was scanned: an Attempt's file is refused before it is written; an execution's output (`spike live`)
# is already on disk when it is scanned.
LEAK_MESSAGES = {
    "attempt": "the API key was found in what this Attempt would write: {files}; nothing holding it was kept",
    "execution": "the API key was found in the execution output: {files}; do not keep or commit it",
}


def leak(files: list, *, scanned: str) -> HypotrailError:
    """`SECRET_IN_OUTPUT` (exit 4) for the `files` that hold the key, in the words of what was `scanned` (`attempt` or `execution`)."""
    return HypotrailError(
        "SECRET_IN_OUTPUT",
        LEAK_MESSAGES[scanned].format(files=", ".join(files)),
        stage="live",
        details={"files": files},
    )


# --- The lifecycle --------------------------------------------------------------------------------------------------------------------


def replayed(study: Path, write, request_id: str, effective_config: dict, code_environment: dict) -> dict | None:
    """The Attempt recorded for this request, every artifact it references read back, or None for a new request.

    The same `request_id` with another request is `REQUEST_CONFLICT` (exit 6), and nothing is written.
    """
    requested = requests.identity(effective_config, code_environment)

    def check_recorded(recorded: dict) -> None:
        differs = requests.differences(requests.identity(recorded["effective_config"], recorded["code_environment"]), requested)
        if differs:
            raise requests.conflict(request_id, recorded["attempt_id"], differs)
        verify_recorded(study, recorded)

    return write.replay_attempt(check_recorded)


@dataclasses.dataclass(frozen=True)
class Produced:
    """What a writer's produce step published beside its Observations.

    `inputs`: the references the terminal manifest adds to its `input_refs`; `outputs`: those its `output_refs` list before the
    normalized Observations and the Observation set record; `effective_config`: the one the terminal manifest records.
    """

    inputs: list
    outputs: list
    effective_config: dict


class Recording:
    """What a writer's produce step is handed: the new Attempt's ID, its folder, its `running` manifest and the adapter its files are written through."""

    def __init__(self, attempt_id: str, manifest: dict, writes: Plain):
        self.attempt_id = attempt_id
        self.folder = f"{layout.ATTEMPTS_DIR}/{attempt_id}"
        self.manifest = manifest
        self.writes = writes
        self.observations_refs = None
        self.statuses = None

    def observations(
        self, name: str, normalized: bytes, statuses: list, *, media_type: str, domain: str, origin: str, population_ref: dict, raw_refs: list,
        provenance: dict, unknown_fields: list,
    ) -> None:
        """Publish the normalized Observations, one `status` in `statuses` for each, then the Observation set record."""
        normalized_ref = self.writes.publish(f"{self.folder}/{name}", normalized, media_type=media_type, role="observations")
        observation_set = {
            "kind": "observations",
            "schema_version": "observations/1",
            "observation_set_id": str(uuid.uuid4()),
            "attempt_id": self.attempt_id,
            "domain": domain,
            "origin": origin,
            "mode": self.manifest["mode"],
            "population_ref": population_ref,
            "raw_refs": raw_refs,
            "normalized_ref": normalized_ref,
            "provenance": provenance,
            "unknown_fields": unknown_fields,
        }
        contracts.validate(observation_set)
        observation_set_ref = self.writes.publish_record(f"{self.folder}/observation_set.json", observation_set, role="observation_set")
        self.observations_refs, self.statuses = [normalized_ref, observation_set_ref], list(statuses)


def record(
    study: Path,
    write,
    *,
    request_id: str,
    operation: str,
    mode: str,
    effective_config: dict,
    code_environment: dict,
    input_refs: list,
    produce,
    started_at: str | None = None,
    retry_of: str | None = None,
    outside_config: dict | None = None,
    marks: dict | None = None,
    writes: Plain | None = None,
    failed=None,
) -> dict:
    """Record a new Attempt and return its terminal manifest.

    The `running` manifest is validated, scanned by the adapter `writes` (`Plain` when none is given) and written first, after
    `write.begin()` and `write.attempt()`. `produce` is then called with the `Recording`: it publishes the writer's outputs, calls
    `Recording.observations` once, and returns what it `Produced`. The terminal manifest is written last.

    The writer gives what differs: `started_at` (an Import's is its import_time; otherwise the time the manifest is made),
    `outside_config` (keys the manifest holds outside `effective_config`, after `input_refs`) and `marks` (what
    `hypotrail.core.exposure.marks` gives, last).

    An error inside the live process leaves a `failed` Attempt: the error the adapter codes is recorded and raised, after `failed`,
    when given, is called with it.
    """
    writes = writes or Plain(study)
    attempt_id = str(uuid.uuid4())
    manifest_path = layout.attempt_manifest_path(attempt_id)
    manifest = {
        "kind": "attempt",
        "schema_version": "attempt/1",
        "attempt_id": attempt_id,
        "request_id": request_id,
        "operation": operation,
        "mode": mode,
        "technical_status": "running",
        "started_at": now() if started_at is None else started_at,
        "finished_at": None,
        "effective_config": effective_config,
        "effective_config_digest": canonical.digest(effective_config),
        "input_refs": input_refs,
        **(outside_config or {}),
        "code_environment": code_environment,
        "outcome_unknown": False,
        "retry_of": retry_of,
        **(marks or {}),
    }
    contracts.validate(manifest)
    running = canonical.dumps(manifest)
    writes.scan(manifest_path, running)  # a hit here writes nothing, not even the journal's `begin` entry, and leaves no Attempt
    write.begin()  # the running manifest is the first write
    write.attempt(attempt_id)
    writes.replace(manifest_path, running)
    try:
        recording = Recording(attempt_id, manifest, writes)
        produced = produce(recording)
        terminal = {
            **manifest,
            "technical_status": "completed",
            "finished_at": now(),
            "effective_config": produced.effective_config,
            "effective_config_digest": canonical.digest(produced.effective_config),
            "input_refs": [*input_refs, *produced.inputs],
            "output_refs": [*produced.outputs, *recording.observations_refs],
            "item_counts": {status: recording.statuses.count(status) for status in ITEM_STATUSES},
        }
        contracts.validate(terminal)
        writes.replace(manifest_path, canonical.dumps(terminal))
        return terminal
    except Exception as error:
        coded = writes.coded(error, manifest_path)
        record_failure(study, manifest_path, manifest, coded)
        if failed is not None:
            failed(coded)
        raise coded from error
