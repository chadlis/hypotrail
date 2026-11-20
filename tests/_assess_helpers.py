"""Shared by the Assessment tests (#66): run `assess`, find ids, build constructed Observation sets and References."""

import csv
import json
import uuid
from pathlib import Path

from _study_helpers import init_study, run_json, run_ml, sha256

from hypotrail.core import artifacts, canonical


def rows_of(path: Path) -> list:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def assess(study, observations, scorer, references, *more):
    return run_json("assess", "--study", study, "--observations", observations, "--scorer", scorer, "--references", references, *more)


def references_id(study) -> str:
    spec = json.loads((Path(study) / "study.json").read_text())
    return next(e["artifact_id"] for e in spec["artifacts"] if e["ref"]["role"] == "references")


def observation_set_id(study, attempt) -> str:
    folder = Path(study) / "attempts" / attempt["attempt_id"]
    return json.loads((folder / "observation_set.json").read_text())["observation_set_id"]


def observations_of(study, attempt) -> list:
    return rows_of(Path(study) / "attempts" / attempt["attempt_id"] / "observations.csv")


def snapshot(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): sha256(p) for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def fresh_study(tmp_path, *configs, partition="dev"):
    study, _ = init_study(tmp_path)
    attempts = {}
    for config in configs:
        code, payload, err = run_ml(study, config, partition, f"ml-{partition}-{config}")
        assert code == 0, (payload, err)
        attempts[config] = payload["attempt"]
    return study, attempts


def construct(study, attempt, edit, *, provenance=None, domain=None, mode=None):
    """A new kept Observation set built from `attempt`'s, whose normalized rows `edit` may change.

    `edit` receives the rows (dicts of observations.csv) and returns the rows to keep. The new
    Attempt manifest references the new files by digest, as a completed Attempt does.
    """
    folder = Path(study) / "attempts" / attempt["attempt_id"]
    new_id = str(uuid.uuid4())
    new_folder = Path(study) / "attempts" / new_id
    new_folder.mkdir()
    rows = edit(rows_of(folder / "observations.csv"))
    with (new_folder / "observations.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["row_id", "status", "reason", "y_pred_raw", "y_pred"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    normalized = artifacts.ref_of_existing(study, f"attempts/{new_id}/observations.csv", media_type="text/csv", role="observations")
    record = json.loads((folder / "observation_set.json").read_text())
    record.update(observation_set_id=str(uuid.uuid4()), attempt_id=new_id, normalized_ref=normalized)
    if provenance:
        record["provenance"] = {**record["provenance"], **provenance}
    if domain:
        record["domain"] = domain
    if mode:
        record["mode"] = mode
    (new_folder / "observation_set.json").write_bytes(canonical.dumps(record))
    set_ref = artifacts.ref_of_existing(study, f"attempts/{new_id}/observation_set.json", media_type="application/json", role="observation_set")
    manifest = json.loads((folder / "attempt.json").read_text())
    manifest.update(attempt_id=new_id, request_id=f"constructed-{new_id}")
    manifest["output_refs"] = [r for r in manifest["output_refs"] if r["role"] not in ("observations", "observation_set")] + [normalized, set_ref]
    (new_folder / "attempt.json").write_bytes(canonical.dumps(manifest))
    return record["observation_set_id"]


def construct_references(study, edit):
    """Replace the Study's References set by `edit(rows)` and keep the StudySpec consistent with its bytes."""
    path = Path(study) / "artifacts" / "references.csv"
    rows = edit(rows_of(path))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["row_id", "y_true"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    spec = json.loads((Path(study) / "study.json").read_text())
    for entry in spec["artifacts"]:
        if entry["ref"]["role"] == "references":
            entry["ref"]["sha256"], entry["ref"]["size_bytes"] = sha256(path), path.stat().st_size
    (Path(study) / "study.json").write_bytes(canonical.dumps(spec))


def per_item(study, assessment) -> dict:
    return {r["row_id"]: r for r in rows_of(Path(study) / assessment["per_item_ref"]["path"])}
