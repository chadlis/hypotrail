"""The single-feature check of a regression Assessment: each declared lag feature, used alone as the forecast, scored as the Assessment is.

D-062 change 2: "A regression candidate that a single one of its own allowed features, used alone as a forecast, beats on the same
rows is flagged." The check reads only what the Attempt and the Study keep: the Configuration recorded in the Attempt's manifest
(`effective_config.configuration.declared`), the copy of `workload.json` the Attempt keeps (its date and target columns and its
`allowed_target_features`), the Study's copy of the dataset that the Attempt's own `input_refs` name, and the population. Nothing is
fitted. The features computed are the declared lag features that the kept declaration allows and whose kind is in the target's unit
(`IN_TARGET_UNIT`). For each, the forecast of an Item is the feature's value at the Item's date (`lags.compute_lags`), and its Metric
is the Scorer's aggregate of the absolute errors over the Items the Assessment scored. A feature beats the Assessment when its Metric
is strictly lower.

The work is in two steps, so that `assess` can check every digest before an Exposure and read target values only after it:
`prepare` reads back the declaration, the population and the dataset copy against their digests and parses no target value;
`compute` parses the dataset copy into a series that keeps only the dates strictly before the last scored Item's.

The field it returns is `{"computed": [...], "beating": [...]}`, empty for a Configuration that declares no such feature; an Attempt
that records no declared Configuration (an Import) gets no field at all ("not checked"), and neither does an Assessment whose features
cannot all be computed for every scored Item (`LAG_SOURCE_MISSING`): `compute` then returns the line that names the cause instead.
"""

import csv
import datetime
import io
from dataclasses import dataclass

from hypotrail.core import artifacts
from hypotrail.core.errors import InvalidInputError
from hypotrail.ml import lags, series
from hypotrail.ml.declaration import Declaration, TargetFeature, declaration_of
from hypotrail.ml.periods import Period

FIELD = "single_feature_check"
# Every kind of `target_feature` in the Workload schema: the values of the target itself, so in the target's unit.
IN_TARGET_UNIT = frozenset({"lag", "mean_previous"})


@dataclass(frozen=True)
class Prepared:
    """What `prepare` read back against the digests: the features to compute and, when there are any, the bytes they need."""

    features: tuple
    declaration: Declaration | None = None
    dataset: bytes | None = None
    dates: dict | None = None


def _declared_features(configuration: dict) -> tuple:
    return tuple(
        TargetFeature(f["name"], f["kind"], Period(f["period"], "period", f"lag_features.{index}.period"))
        for index, f in enumerate(configuration["declared"].get("lag_features", []))
    )


def prepare(study, manifest: dict, population_ref: dict) -> Prepared | None:
    """None when the Attempt records no declared Configuration; otherwise the features to compute, with every input read back."""
    configuration = manifest["effective_config"].get("configuration")
    if not isinstance(configuration, dict):  # an Import declares no Configuration
        return None
    declared = _declared_features(configuration)
    if not declared:
        return Prepared(())
    refs = {ref["role"]: ref for ref in manifest["input_refs"]}
    kept = refs["workload_declaration"]
    declaration = declaration_of(artifacts.read_verified(study, kept), kept["path"])
    allowed = declaration.allowed_target_features or ()
    features = tuple(f for f in declared if f in allowed and f.kind in IN_TARGET_UNIT)
    if not features:
        return Prepared(())
    dataset = artifacts.read_verified(study, refs["dataset"])
    population = csv.DictReader(io.StringIO(artifacts.read_verified(study, population_ref).decode("utf-8"), newline=""))
    dates = {row["row_id"]: datetime.date.fromisoformat(row["date"]) for row in population}
    return Prepared(features, declaration, dataset, dates)


def compute(prepared: Prepared, scored: list, metric_of, assessment_metric: dict) -> tuple:
    """(the field, None), or (None, the line that says why the field is absent).

    `scored` lists (row_id, reference) for every Item the Assessment scored, in the Assessment's order; `metric_of` turns a list of
    absolute errors into a Metric as the Assessment's Scorer does.
    """
    if not prepared.features:
        return {"computed": [], "beating": []}, None
    days = [(prepared.dates[row_id], reference) for row_id, reference in scored]
    values = series.target_series(prepared.dataset, prepared.declaration)
    if days:
        last = max(day for day, _ in days)
        values = {day: value for day, value in values.items() if day < last}
    errors = {f.name: [] for f in prepared.features}
    for day, reference in days:
        try:
            forecasts = lags.compute_lags(values, day, prepared.features)
        except InvalidInputError as error:
            if error.code != "LAG_SOURCE_MISSING":
                raise
            return None, f"{error.code}: the single-feature check is not recorded, since {error.message}"
        for name, value in forecasts.items():
            errors[name].append(abs(value - reference))
    computed = [{"feature": f.name, "metric": metric_of(errors[f.name])} for f in prepared.features]
    bound = assessment_metric["value"]
    beating = sorted(
        (
            {"feature": entry["feature"], "value": entry["metric"]["value"]}
            for entry in computed
            if bound is not None and entry["metric"]["value"] is not None and entry["metric"]["value"] < bound
        ),
        key=lambda entry: (entry["value"], entry["feature"]),
    )
    return {"computed": computed, "beating": beating}, None
