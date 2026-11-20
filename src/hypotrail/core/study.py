"""The layout of a Study on disk, and how a Track-neutral command opens one.

A Study is a folder named explicitly (`--study DIR`); it holds, all as artifacts referenced by digest:

```
DIR/
  study.json                         the StudySpec of the current revision (canonical JSON)
  datasets/<file>                    the dataset as it was at `init`
  artifacts/memberships.csv          the population, a Study artifact with an ID
  artifacts/references.csv           the References set, a Study artifact with an ID
  revisions/<n>/study.json           the StudySpec of revision n, once a later revision exists (core/revisions.py)
  attempts/<attempt_id>/attempt.json the Attempt manifest (running, then terminal)
  attempts/<attempt_id>/...          the Attempt's predictions, parameters, Observation set
  assessments/<assessment_id>/per_item.csv     an Assessment's Criterion state per Item
  assessments/<assessment_id>/assessment.json  the Assessment record (written last)
  comparisons/<comparison_id>/population.json     a Comparison's population identity
  comparisons/<comparison_id>/paired_deltas.csv   its absolute errors and their difference per row_id
  comparisons/<comparison_id>/comparison.json     the Comparison record (written last)
  .scratch/<attempt_id>/             scratch files of the library writers, before publication
```

The Workload itself (its declaration, its Configurations, its data and lock) stays where it is declared
(`examples/<name>`): a Configuration can change after the Study exists, and an Attempt records the
Configuration it ran. The Protocol is what the Study freezes of the Workload.
"""

import json
from pathlib import Path

from hypotrail.core import artifacts, canonical, contracts
from hypotrail.core.errors import InvalidInputError

STUDY_FILE = "study.json"
ARTIFACTS_DIR = "artifacts"
DATASETS_DIR = "datasets"
ATTEMPTS_DIR = "attempts"
SCRATCH_DIR = ".scratch"
ASSESSMENTS_DIR = "assessments"
COMPARISONS_DIR = "comparisons"
MANIFEST_NAME = "attempt.json"

_MEDIA_TYPES = {".csv": "text/csv", ".json": "application/json", ".md": "text/markdown", ".txt": "text/plain"}


def media_type_of(path) -> str:
    return _MEDIA_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


def declared_track(workload_dir: Path):
    """The `track` a Workload declares (None when absent), read before any Track loader runs."""
    path = Path(workload_dir) / "workload.json"
    try:
        declaration = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # the Track's own loader reports a missing or unreadable declaration
    return declaration.get("track") if isinstance(declaration, dict) else None


def require_domain(spec: dict, domain: str, command: str) -> None:
    """Refuse a command on a Study of another Track: a combination the code does not offer."""
    if spec["domain"] != domain:
        raise InvalidInputError(
            "UNSUPPORTED_CAPABILITY",
            f"`{command}` works on a Study of the {domain!r} domain; this Study is {spec['domain']!r}",
            stage="study",
            details={"command": command, "study_domain": spec["domain"], "command_domain": domain},
        )


def short_id(prefix: str, sha256: str) -> str:
    """The ID of a Study artifact: its kind and the first 16 hex digits of its digest."""
    return f"{prefix}-{sha256[:16]}"


def attempt_manifest_path(attempt_id: str) -> str:
    return f"{ATTEMPTS_DIR}/{attempt_id}/{MANIFEST_NAME}"


def read_spec(study) -> dict:
    """The StudySpec of `study`, validated against the contract schema."""
    path = Path(study) / STUDY_FILE
    if not path.is_file():
        raise InvalidInputError(
            "STUDY_NOT_FOUND",
            f"no Study here: {path} does not exist (create one with `init`)",
            stage="study",
            details={"study": str(study)},
        )
    spec = canonical.loads(path.read_bytes())
    contracts.validate(spec)
    return spec


def read_record(study, relative: str) -> dict:
    """A record kept in the Study, read back and validated."""
    path = artifacts.resolve(study, relative)
    record = canonical.loads(path.read_bytes())
    contracts.validate(record)
    return record


def read_manifest(study, attempt_id: str) -> dict:
    return read_record(study, attempt_manifest_path(attempt_id))


def attempt_ids(study) -> list:
    folder = Path(study) / ATTEMPTS_DIR
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if (p / MANIFEST_NAME).is_file())


def find_by_request(study, request_id: str):
    """The Attempt recorded under `request_id`, or None. A request_id names at most one Attempt."""
    for attempt_id in attempt_ids(study):
        manifest = read_manifest(study, attempt_id)
        if manifest["request_id"] == request_id:
            return manifest
    return None


def find_observation_set(study, observation_set_id: str):
    """The Observation set record of `observation_set_id` and the manifest of its Attempt, or None.

    The record is found through the Attempts' manifests, which reference it by digest, and read back
    against that digest once it is the one asked for.
    """
    for attempt_id in attempt_ids(study):
        manifest = read_manifest(study, attempt_id)
        for ref in manifest.get("output_refs", []):
            if ref["role"] != "observation_set":
                continue
            try:
                record = canonical.loads(artifacts.resolve(study, ref["path"]).read_bytes())
            except (OSError, ValueError, InvalidInputError):
                continue
            if isinstance(record, dict) and record.get("observation_set_id") == observation_set_id:
                artifacts.read_verified(study, ref)
                contracts.validate(record)
                return record, manifest
    return None


def find_assessment(study, assessment_id: str):
    """The Assessment record of `assessment_id`, or None; the ID is only compared, never made into a path."""
    folder = Path(study) / ASSESSMENTS_DIR
    if not folder.is_dir():
        return None
    for candidate in sorted(folder.iterdir()):
        if candidate.name == assessment_id and (candidate / "assessment.json").is_file():
            return read_record(study, f"{ASSESSMENTS_DIR}/{candidate.name}/assessment.json")
    return None
