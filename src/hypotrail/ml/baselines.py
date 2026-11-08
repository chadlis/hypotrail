"""The `seasonal_k` Configuration: predict each Item as the target k periods earlier.

Generic "value k periods ago" baseline. The Workload declares the Configuration
(`configurations.<id>` in `workload.json`: its k and its clipping bound), the target
column and the date column; nothing is fitted and no estimator or preprocessing is
involved (SPEC ML-01). The data is the daily series, so a period is one day.
"""

import datetime
from pathlib import Path

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.configuration import load_configuration
from hypotrail.ml.memberships import memberships_of
from hypotrail.ml.predictions import write_predictions
from hypotrail.ml.series import read_target_series


def write_seasonal_baseline(workload_dir: Path, out_dir: Path, config_id: str, partition: str) -> Path:
    """Write `predictions.csv` for the Items of `partition`, as the declared Configuration `config_id`."""
    loaded = load_configuration(workload_dir, config_id)
    declaration, configuration = loaded["declaration"], loaded["configuration"]
    period = configuration.period_k
    series = read_target_series(workload_dir, declaration)
    items = [m for m in memberships_of(workload_dir, declaration) if m["partition"] == partition]
    row_ids, raw = [], []
    for item in items:
        date = datetime.date.fromisoformat(item["date"])
        earlier = period.earlier(date)
        if earlier not in series:
            raise InvalidInputError(
                "NO_VALUE_K_PERIODS_EARLIER",
                f"no target {period.days} days before {item['date']}",
                stage="seasonal_baseline",
                details={"date": item["date"], "k": period.days},
            )
        row_ids.append(item["row_id"])
        raw.append(series[earlier])
    return write_predictions(
        out_dir, config_id, row_ids, raw, clip_min=configuration.post_processing.clip_min
    )
