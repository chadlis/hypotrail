"""The first Comparison of the temporal regression Track: Control against Candidate on `dev`.

Each side is a predictions CSV; targets come from the References artifact.
Items are paired by `row_id`, never by position, and the two files must cover
exactly the same Items: there is no silent intersection (SPEC CMP-02). The
metrics are those of `metrics.compute_metrics`. `delta_mae` is
`MAE(Candidate) - MAE(Control)`: a positive value means the Candidate is worse,
and no sign is required. The strict comparability checks belong to a later
contract. A request on `public_check` is refused until the Exposure journal
exists (SPEC section 2).
"""

import json
import math
from pathlib import Path

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.metrics import (
    DIRECTION,
    PRIMARY,
    UNIT,
    _finite,
    _read,
    _unique_by_row_id,
    compute_metrics,
)

COMPARISON_NAME = "comparison.json"
MODE = "native_ml"


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="comparison", details=details)


def _config_id(predictions_path, rows):
    ids = {row["config_id"] for row in rows}
    if len(ids) != 1:
        raise _refuse("CONFIG_ID_NOT_UNIQUE", f"{predictions_path} must name exactly one config_id", config_ids=sorted(ids))
    return ids.pop()


def compare(
    control_predictions,
    candidate_predictions,
    references_path,
    memberships_path,
    out_dir,
    *,
    partition: str = "dev",
) -> dict:
    """Compare two predictions files on `dev` and write `comparison.json` into `out_dir`."""
    if partition == "public_check":
        raise _refuse(
            "PUBLIC_CHECK_COMPARISON_REFUSED",
            "a Comparison on public_check is refused: no Exposure journal exists yet",
            partition=partition,
        )
    if partition != "dev":
        raise _refuse("PARTITION_NOT_SUPPORTED", f"a Comparison is computed on dev only, not {partition}", partition=partition)

    control_rows = _read(control_predictions)
    candidate_rows = _read(candidate_predictions)
    control_by_id = _unique_by_row_id(control_rows, "Control predictions")
    candidate_by_id = _unique_by_row_id(candidate_rows, "Candidate predictions")
    if set(control_by_id) != set(candidate_by_id):
        raise _refuse(
            "COMPARISON_ITEMS_DIFFER",
            "Control and Candidate do not cover the same Items",
            only_control=len(set(control_by_id) - set(candidate_by_id)),
            only_candidate=len(set(candidate_by_id) - set(control_by_id)),
        )

    control = compute_metrics(control_predictions, references_path, memberships_path, partition=partition)
    candidate = compute_metrics(candidate_predictions, references_path, memberships_path, partition=partition)
    references = _unique_by_row_id(_read(references_path), "references")

    row_ids = sorted(control_by_id)  # the same Items on both sides, in a fixed order
    differences = []
    for row_id in row_ids:
        y_true = _finite(references[row_id]["y_true"], row_id, "y_true")
        control_error = abs(_finite(control_by_id[row_id]["y_pred"], row_id, "y_pred") - y_true)
        candidate_error = abs(_finite(candidate_by_id[row_id]["y_pred"], row_id, "y_pred") - y_true)
        differences.append(
            {
                "row_id": row_id,
                "control_abs_error": control_error,
                "candidate_abs_error": candidate_error,
                "delta_abs_error": candidate_error - control_error,
            }
        )
    delta_mae = math.fsum(d["delta_abs_error"] for d in differences) / len(differences)

    result = {
        "mode": MODE,
        "population": {"partition": partition, "count": len(row_ids), "row_ids": row_ids},
        "metric": {"name": PRIMARY, "unit": UNIT, "direction": DIRECTION},
        "control": {"config_id": _config_id(control_predictions, control_rows), **control},
        "candidate": {"config_id": _config_id(candidate_predictions, candidate_rows), **candidate},
        "delta_mae": {"value": delta_mae, "unit": UNIT, "definition": "MAE(Candidate) - MAE(Control); positive means the Candidate is worse"},
        "differences": differences,
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / COMPARISON_NAME).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
