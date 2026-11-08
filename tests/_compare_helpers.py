"""Shared by the Comparison tests (#71): a Study with two assessed Attempts, `compare`, and Assessments built by hand."""

import csv
import json
import uuid
from pathlib import Path

from _assess_helpers import assess, fresh_study, observation_set_id, references_id, rows_of
from _study_helpers import run_json

from hypotrail.core import artifacts, canonical


def compare(study, control, candidate, *more):
    return run_json("compare", "--study", study, "--control", control, "--candidate", candidate, *more)


def assessed(tmp_path, *configs, scorer="regression_mae_v1"):
    """(Study, {config: Attempt}, {config: Assessment}) once each Configuration ran on dev and was assessed."""
    study, attempts = fresh_study(tmp_path, *configs)
    out = {}
    for config, attempt in attempts.items():
        code, payload, err = assess(study, observation_set_id(study, attempt), scorer, references_id(study))
        assert code == 0, (payload, err)
        out[config] = payload["assessment"]
    return study, attempts, out


def forged(study, assessment, edit=None, *, per_item=None):
    """A new Assessment record derived from `assessment`: `edit` changes the record, `per_item` the rows of its per-Item file.

    The new record is published beside the real ones and references its own per-Item file by digest.
    """
    new_id = str(uuid.uuid4())
    folder = Path(study) / "assessments" / new_id
    folder.mkdir()
    rows = rows_of(Path(study) / assessment["per_item_ref"]["path"])
    if per_item is not None:
        rows = per_item(rows)
    path = folder / "per_item.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["row_id", "execution_status", "criterion", "state", "value", "reason"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    record = json.loads(json.dumps(assessment))
    record["assessment_id"] = new_id
    record["per_item_ref"] = artifacts.ref_of_existing(study, f"assessments/{new_id}/per_item.csv", media_type="text/csv", role="per_item")
    if edit is not None:
        edit(record)
    (folder / "assessment.json").write_bytes(canonical.dumps(record))
    return record


def comparisons(study) -> list:
    folder = Path(study) / "comparisons"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []
