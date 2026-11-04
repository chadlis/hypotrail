"""The `seasonal_k` Configuration: predict each Item as the target k periods earlier.

Generic "value k periods ago" baseline. The Workload declares the target
column, the date column and k (`period_k`); nothing is fitted and no
estimator or preprocessing is involved (SPEC ML-01). The data is the daily
series, so a period is one day.
"""

import datetime
from pathlib import Path

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.memberships import derive_memberships, load_declaration
from hypotrail.ml.predictions import write_predictions
from hypotrail.ml.series import read_target_series


def write_seasonal_baseline(workload_dir: Path, out_dir: Path, *, partition: str = "dev") -> Path:
    """Write `predictions.csv` for the Items of one Partition (`dev` by default)."""
    declaration = load_declaration(workload_dir)
    k = declaration["period_k"]
    series = read_target_series(workload_dir, declaration)
    items = [m for m in derive_memberships(workload_dir) if m["partition"] == partition]
    row_ids, raw = [], []
    for item in items:
        date = datetime.date.fromisoformat(item["date"])
        earlier = date - datetime.timedelta(days=k)
        if earlier not in series:
            raise InvalidInputError(
                "NO_VALUE_K_PERIODS_EARLIER",
                f"no target {k} days before {item['date']}",
                stage="seasonal_baseline",
                details={"date": item["date"], "k": k},
            )
        row_ids.append(item["row_id"])
        raw.append(series[earlier])
    return write_predictions(out_dir, f"seasonal_{k}", row_ids, raw)
