"""The first Comparison of the temporal regression Track: Control against Candidate on `dev`.

Each side is a predictions CSV; targets come from the References artifact.
Items are paired by `row_id`, never by position, and the two files must cover
exactly the same Items: there is no silent intersection (SPEC CMP-02). The
metrics are those of `metrics.summarise`, over the same scored Items as the
differences. `delta_mae` is `MAE(Candidate) - MAE(Control)` from the two reported
MAEs: a positive value means the Candidate is worse, and no sign is required. The strict comparability checks belong to a later
contract. This file-based function takes no Study: it computes on `dev` only, and a request on `public_check` is refused. Inside a
Study, `compare` accepts `public_check` and journals the Exposure (SPEC section 2).
"""

import json
from pathlib import Path

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.memberships import load_declaration
from hypotrail.ml.partitions import DEV, require_dev
from hypotrail.ml.metrics import (
    DIRECTION,
    PRIMARY,
    declared_partition,
    declared_unit,
    read_by_row_id,
    score_items,
    summarise,
)

COMPARISON_NAME = "comparison.json"
MODE = "native_ml"


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="comparison", details=details)


def _config_id(predictions_path, by_id):
    ids = {row["config_id"] for row in by_id.values()}
    if len(ids) != 1:
        raise _refuse("CONFIG_ID_NOT_UNIQUE", f"{predictions_path} must name exactly one config_id", config_ids=sorted(ids))
    return ids.pop()


def compare(
    control_predictions,
    candidate_predictions,
    references_path,
    memberships_path,
    out_dir,
    workload_dir,
    *,
    partition: str = DEV,
) -> dict:
    """Compare two predictions files on a Partition and write `comparison.json` into `out_dir`."""
    require_dev(
        partition,
        public_check_code="PUBLIC_CHECK_COMPARISON_REFUSED",
        not_dev_code="COMPARISON_PARTITION_NOT_DEV",
        what="a Comparison",
        stage="comparison",
    )
    declaration = load_declaration(workload_dir)
    declared_partition(declaration, partition)
    unit = declared_unit(declaration)

    control_by_id = read_by_row_id(control_predictions, "Control predictions")
    candidate_by_id = read_by_row_id(candidate_predictions, "Candidate predictions")
    if set(control_by_id) != set(candidate_by_id):
        raise _refuse(
            "COMPARISON_ITEMS_DIFFER",
            "Control and Candidate do not cover the same Items",
            only_control=len(set(control_by_id) - set(candidate_by_id)),
            only_candidate=len(set(candidate_by_id) - set(control_by_id)),
        )

    references = read_by_row_id(references_path, "references")
    memberships = read_by_row_id(memberships_path, "memberships")
    control_items = score_items(control_by_id, references, memberships, partition)
    candidate_items = score_items(candidate_by_id, references, memberships, partition)
    control = summarise(control_items, partition, unit)
    candidate = summarise(candidate_items, partition, unit)

    row_ids = [item["row_id"] for item in control_items]  # the same Items on both sides, in a fixed order
    differences = [
        {
            "row_id": ctl["row_id"],
            "control_abs_error": ctl["abs_error"],
            "candidate_abs_error": cand["abs_error"],
            "delta_abs_error": cand["abs_error"] - ctl["abs_error"],
        }
        for ctl, cand in zip(control_items, candidate_items)
    ]
    delta_mae = candidate["metrics"][PRIMARY]["value"] - control["metrics"][PRIMARY]["value"]

    result = {
        "mode": MODE,
        "population": {"partition": partition, "count": len(row_ids), "row_ids": row_ids},
        "metric": {"name": PRIMARY, "unit": unit, "direction": DIRECTION},
        "control": {"config_id": _config_id(control_predictions, control_by_id), **control},
        "candidate": {"config_id": _config_id(candidate_predictions, candidate_by_id), **candidate},
        "delta_mae": {"value": delta_mae, "unit": unit, "definition": "MAE(Candidate) - MAE(Control); positive means the Candidate is worse"},
        "differences": differences,
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / COMPARISON_NAME).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
