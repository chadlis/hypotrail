"""The `seasonal_k` Configuration: predict each Item as the target k periods earlier.

Generic "value k periods ago" baseline. The Workload declares the Configuration
(`configurations.<id>` in `workload.json`: its k and its clipping bound), the target
column and the date column; nothing is fitted and no estimator or preprocessing is
involved (SPEC ML-01). The data is the daily series, so a period is one day.
"""

import datetime
from pathlib import Path

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.configuration import declared_configuration
from hypotrail.ml.memberships import derive_memberships, load_declaration
from hypotrail.ml.predictions import write_predictions
from hypotrail.ml.series import read_target_series


def write_seasonal_baseline(workload_dir: Path, out_dir: Path, config_id: str, partition: str) -> Path:
    """Write `predictions.csv` for the Items of `partition`, as the declared Configuration `config_id`."""
    declaration = load_declaration(workload_dir)
    configuration = declared_configuration(declaration, config_id)
    k = configuration["period_k"]
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise InvalidInputError(
            "TARGET_FEATURE_NOT_PAST",
            f"configuration {config_id!r} reaches date t or later (period {k!r})",
            stage="seasonal_baseline",
            details={"config_id": config_id, "period": k},
        )
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
    return write_predictions(
        out_dir, config_id, row_ids, raw, clip_min=configuration["post_processing"]["clip_min"]
    )
