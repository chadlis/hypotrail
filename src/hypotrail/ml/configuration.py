"""Validation of a Configuration against its Workload's declarations.

Standard library only. What the Track code fixes is small: the Partition roles
(`hypotrail.ml.partitions`: `train`, `dev`, `public_check`) and the kinds of
Configuration it knows (`seasonal_baseline`, `ridge_pipeline`) with the keys each
takes. Everything else is declared by the Workload: `forbidden_features` (columns
that are not known at date t), `allowed_target_features` (the only transformations
of the target a Configuration may use), the Partition date ranges, and each
Configuration's own settings.

A Configuration declares its kind. The kind picks the keys it may carry; an unknown
kind, or a key that does not belong to the kind, is refused. The checks that apply to
every Configuration (forbidden features, target transformations that reach date t or
later, target transformations the Workload does not declare) run for every kind. A
Workload declaration must declare the `train` Partition whatever its Configurations (`hypotrail.ml.declaration`).
A Configuration that breaks a rule is refused with a coded error, before anything is
fitted or predicted. Nothing is dropped or included silently.

The model inputs of a `ridge_pipeline` are the lag feature names and `calendar_columns`.
The forbidden-feature check reads them and the `columns` of the encoder and of the
scaler; the encoder and the scaler must together take exactly the model inputs.
"""

from pathlib import Path

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.declaration import RIDGE, SEASONAL, kind_of, load_declaration


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="configuration", details=details)


def _declared(declaration: dict, key: str) -> list:
    if key not in declaration:
        raise _refuse("DECLARATION_INCOMPLETE", f"declaration lacks {key!r}", key=key)
    return declaration[key]


def declared_configuration(declaration: dict, config_id: str) -> dict:
    """The Configuration the Workload declares under `config_id`; its key is its id."""
    try:
        return declaration["configurations"][config_id]
    except KeyError:
        raise _refuse(
            "CONFIGURATION_NOT_DECLARED", f"no configuration {config_id!r} is declared", config_id=config_id
        ) from None


def _input_names(configuration: dict) -> list:
    names = [f["name"] for f in configuration["lag_features"]]
    names += configuration["calendar_columns"]
    names += configuration["encoder"]["columns"]
    names += configuration["scaler"]["columns"]
    return names


def is_past_period(period) -> bool:
    """A period that points strictly before date t: a whole number of at least 1."""
    return isinstance(period, int) and not isinstance(period, bool) and period >= 1


def _target_transformations(kind: str, configuration: dict) -> list:
    """The transformations of the target a Configuration uses: named lags, or the seasonal period."""
    if kind == SEASONAL:
        return [{"kind": "lag", "period": configuration["period_k"]}]
    return configuration["lag_features"]


def _model_input_names(kind: str, configuration: dict) -> list:
    """The columns and features a Configuration feeds to a model, wherever it lists them."""
    if kind == SEASONAL:
        return []
    return _input_names(configuration)


def _check_target_transformations(declaration: dict, config_id: str, transformations: list) -> None:
    allowed = _declared(declaration, "allowed_target_features")
    for feature in transformations:
        name, period = feature.get("name"), feature["period"]
        named = {"feature": name} if name is not None else {}
        if not is_past_period(period):
            raise _refuse(
                "TARGET_FEATURE_NOT_PAST",
                f"configuration {config_id!r} reaches date t or later (period {period!r})",
                config_id=config_id,
                period=period,
                **named,
            )
        declared = feature in allowed if name is not None else any(
            f["kind"] == feature["kind"] and f["period"] == period for f in allowed
        )
        if not declared:
            raise _refuse(
                "TARGET_TRANSFORMATION_NOT_ALLOWED",
                f"configuration {config_id!r} uses a transformation of the target ({feature!r}) that the Workload does not declare",
                config_id=config_id,
                period=period,
                **named,
            )


def _check_ridge_inputs(config_id: str, configuration: dict) -> None:
    # Every model input goes through the encoder or the scaler, and every column they take is a
    # model input: nothing is dropped by a remainder, nothing is invented.
    model_inputs = [f["name"] for f in configuration["lag_features"]] + list(configuration["calendar_columns"])
    transformed = set(configuration["encoder"]["columns"]) | set(configuration["scaler"]["columns"])
    for name in model_inputs:
        if name not in transformed:
            raise _refuse(
                "MODEL_INPUT_NOT_TRANSFORMED",
                f"input {name!r} of {config_id!r} is taken by neither the encoder nor the scaler",
                config_id=config_id,
                feature=name,
            )
    for transformer in ("encoder", "scaler"):
        for name in configuration[transformer]["columns"]:
            if name not in model_inputs:
                raise _refuse(
                    "TRANSFORMER_COLUMN_NOT_A_MODEL_INPUT",
                    f"the {transformer} of {config_id!r} takes {name!r}, which is not a model input",
                    config_id=config_id,
                    feature=name,
                    transformer=transformer,
                )


def validate_configuration(declaration: dict, config_id: str, configuration: dict) -> None:
    """Refuse a Configuration that breaks a declared rule. The kind it declares picks its keys only;
    the checks that apply to every Configuration run for every kind."""
    kind = kind_of(config_id, configuration)
    forbidden = _declared(declaration, "forbidden_features")
    for name in _model_input_names(kind, configuration):
        if name in forbidden:
            raise _refuse(
                "FORBIDDEN_FEATURE",
                f"configuration {config_id!r} uses {name!r}, which is forbidden at date t",
                config_id=config_id,
                feature=name,
            )
    _check_target_transformations(declaration, config_id, _target_transformations(kind, configuration))
    if kind == RIDGE:
        _check_ridge_inputs(config_id, configuration)


def load_configuration(workload_dir: Path, config_id: str) -> dict:
    """Read the Workload's declaration and the Configuration `config_id`, validated for its kind."""
    declaration = load_declaration(workload_dir)
    configuration = declared_configuration(declaration, config_id)
    validate_configuration(declaration, config_id, configuration)
    return {"declaration": declaration, "configuration": configuration}
