"""The layout of a Study on disk, and the readers every command shares to open one.

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
  revisions/<n>/freeze.json          the freeze record of revision n, written before its first public_check use (core/exposure.py)
  exposures/<seq>-<entry_id>.json    one Exposure journal entry each, appended and never rewritten (core/exposure.py)
  write_journal/<n>.json             one write journal entry each, appended and never rewritten (core/write_journal.py)
  decisions/<seq>-<decision_id>.json one decision each, appended and never rewritten (core/decisions.py)
  .scratch/<attempt_id>/             scratch files of the library writers, before publication
```

Everything here is Track-neutral except `expected_row_ids`, which reads the population of the regression Track
(`row_id`, and the `item_ids` file of `import ml`): `core/comparison.py` needs it for a regression Comparison and
the core imports no Track, so it stays here and says so.

The Workload itself (its declaration, its Configurations, its data and lock) stays where it is declared
(`examples/<name>`): a Configuration can change after the Study exists, and an Attempt records the
Configuration it ran. The Protocol is what the Study freezes of the Workload.
"""

import csv
import io
import json
from pathlib import Path

from hypotrail.core import artifacts, canonical, contracts, evaluator
from hypotrail.core.errors import HypotrailError, InvalidInputError

STUDY_FILE = "study.json"
ARTIFACTS_DIR = "artifacts"
DATASETS_DIR = "datasets"
ATTEMPTS_DIR = "attempts"
SCRATCH_DIR = ".scratch"
ASSESSMENTS_DIR = "assessments"
COMPARISONS_DIR = "comparisons"
MANIFEST_NAME = "attempt.json"
OBSERVATION_SET_ROLE = "observation_set"  # the role of the ref that an Attempt's manifest keeps to its Observation set record

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
    """Require an ordinary Study whose Track the command supports."""
    evaluator.refuse_protected(spec, stage="study")
    if spec["domain"] != domain:
        raise InvalidInputError(
            "UNSUPPORTED_CAPABILITY",
            f"`{command}` works on a Study of the {domain!r} domain; this Study is {spec['domain']!r}",
            stage="study",
            details={"command": command, "study_domain": spec["domain"], "command_domain": domain},
        )


def partition_of(memberships: bytes, key: str) -> dict:
    """{item ID: Partition} read from a Study's memberships CSV, whose first column is `key` (`row_id` or `case_id`).

    One reader for both Tracks: a quoted ID is read as CSV, and an Item with an empty Partition is left out.
    """
    rows = csv.DictReader(io.StringIO(memberships.decode("utf-8"), newline=""))
    return {row[key]: row["partition"] for row in rows if row["partition"]}


IMPORT_POPULATION_KEY = "item_ids"  # the one key of the population file `import ml` is given


def expected_row_ids(study, population_ref: dict, partition: str) -> list:
    """The sorted `row_id`s an Observation set of the regression Track is expected to answer (regression Track only).

    A native Attempt's population is the Study's memberships, whose Items of `partition` are all expected. An
    Import's population is the file it was given (`--population`), which may list fewer Items of that Partition.
    """
    raw = artifacts.read_verified(study, population_ref)
    if population_ref["role"] == "import_population":
        return sorted(canonical.loads(raw)[IMPORT_POPULATION_KEY])
    return sorted(row_id for row_id, found in partition_of(raw, "row_id").items() if found == partition)


def dataset_ref(spec: dict) -> dict:
    """The reference of the Study's own copy of the Workload's dataset: found by its role, never by its position."""
    return next(ref for ref in spec["dataset_refs"] if ref["role"] == "dataset")


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


def available_spec(study) -> dict | None:
    """A validated StudySpec when available, for callers with their own missing or unreadable Study error order."""
    try:
        return read_spec(study)
    except (OSError, HypotrailError):
        return None


def refuse_existing(study) -> None:
    """Refuse creation in an existing Study under the caller's writer lock."""
    spec = available_spec(study)
    if spec is not None:
        evaluator.refuse_protected(spec, stage="study")
    raise InvalidInputError("STUDY_EXISTS", f"a Study already exists in {study}", stage="study", details={"study": str(study)})


def record_names(study, folder: str) -> list:
    """The names of the JSON records in `<study>/<folder>`, sorted (position order, as the names start with it); none when the folder is absent."""
    path = Path(study) / folder
    return sorted(p.name for p in path.iterdir() if p.name.endswith(".json") and not p.name.startswith(".")) if path.is_dir() else []


def next_position(study, folder: str) -> int:
    """The position, from 1, of the next record of `<study>/<folder>`: the count of its records + 1."""
    return len(record_names(study, folder)) + 1


def read_record(study, relative: str) -> dict:
    """A record kept in the Study, read back and validated."""
    path = artifacts.resolve(study, relative)
    record = canonical.loads(path.read_bytes())
    contracts.validate(record)
    return record


def read_records(study, folder: str) -> list:
    """Every record of `<study>/<folder>`, in position order, each validated after it is read."""
    return [read_record(study, f"{folder}/{name}") for name in record_names(study, folder)]


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


def observation_set_refs(manifest: dict) -> list:
    """The refs of the manifest's `output_refs` whose role is that of an Observation set record, in the order the manifest lists them (usually one).

    The one walk from an Attempt's manifest to its Observation set: each caller reads the record it finds in its own way.
    """
    return [ref for ref in manifest.get("output_refs", []) if ref["role"] == OBSERVATION_SET_ROLE]


def find_observation_set(study, observation_set_id: str):
    """The Observation set record of `observation_set_id` and the manifest of its Attempt, or None.

    The record is found through the Attempts' manifests, which reference it by digest, and read back
    against that digest once it is the one asked for.
    """
    for attempt_id in attempt_ids(study):
        manifest = read_manifest(study, attempt_id)
        for ref in observation_set_refs(manifest):
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


def assessment_records(study) -> list:
    """Every Assessment record the Study keeps, in the order of their folder names."""
    folder = Path(study) / ASSESSMENTS_DIR
    if not folder.is_dir():
        return []
    return [
        read_record(study, f"{ASSESSMENTS_DIR}/{candidate.name}/assessment.json")
        for candidate in sorted(folder.iterdir())
        if (candidate / "assessment.json").is_file()
    ]


def comparison_records(study) -> list:
    """Every Comparison record the Study keeps, in the order of their folder names."""
    folder = Path(study) / COMPARISONS_DIR
    if not folder.is_dir():
        return []
    return [
        read_record(study, f"{COMPARISONS_DIR}/{candidate.name}/comparison.json")
        for candidate in sorted(folder.iterdir())
        if (candidate / "comparison.json").is_file()
    ]
