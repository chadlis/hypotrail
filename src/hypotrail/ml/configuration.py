"""Validation of a Configuration against its Workload's declarations.

What the Track code fixes is small: the Partition roles
(`hypotrail.ml.partitions`: `train`, `dev`, `public_check`) and the kinds of
Configuration it knows (`seasonal_baseline`, `ridge_pipeline`) with the keys each
takes. Everything else is declared by the Workload: `forbidden_features` (columns
that are not known at date t), `allowed_target_features` (the only transformations
of the target a Configuration may use), the Partition date ranges, and each
Configuration's own settings.

A Configuration is a typed object of the declaration (`SeasonalConfiguration` or `RidgeConfiguration`);
what runs here takes the typed `Declaration` and refuses a raw dictionary with a `TypeError`.

A Configuration declares its kind. The JSON Schema of the declaration (`hypotrail.ml.declaration`)
has already refused an unknown kind, a key that does not belong to the kind, a missing key and
a wrongly typed or disallowed value when the declaration was loaded. What runs here are the
rules that relate values to each other or to the protocol. They apply to every Configuration
(forbidden features, target transformations that reach date t or later, target transformations
the Workload does not declare), and to the `ridge_pipeline` kind the cover of its model inputs
by the encoder and the scaler. A Configuration that breaks a rule is refused with a coded
error, before anything is fitted or predicted. Nothing is dropped or included silently.

The model inputs of a `ridge_pipeline` are the lag feature names and `calendar_columns`.
The forbidden-feature check reads them and the `columns` of the encoder and of the
scaler; the encoder and the scaler must together take exactly the model inputs.
"""

from pathlib import Path

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.declaration import (
    RIDGE,
    SEASONAL,
    Declaration,
    RidgeConfiguration,
    SeasonalConfiguration,
    TargetFeature,
    load_declaration,
    require_keys,
    typed,
)


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="configuration", details=details)


def declared_configuration(declaration: Declaration, config_id: str):
    """The Configuration the Workload declares under `config_id`; its key is its id."""
    typed(declaration, Declaration)
    require_keys(declaration, "configurations")
    try:
        return declaration.configurations[config_id]
    except KeyError:
        raise _refuse(
            "CONFIGURATION_NOT_DECLARED", f"no configuration {config_id!r} is declared", config_id=config_id
        ) from None


def _input_names(configuration: RidgeConfiguration) -> list:
    names = [f.name for f in configuration.lag_features]
    names += configuration.calendar_columns
    names += configuration.encoder.columns
    names += configuration.scaler.columns
    return names


def is_past_period(period: int) -> bool:
    """A period that points strictly before date t: at least 1 (the schema guarantees a whole number)."""
    return period >= 1


def _target_transformations(configuration) -> list:
    """The transformations of the target a Configuration uses: named lags, or the seasonal period."""
    if isinstance(configuration, SeasonalConfiguration):
        return [TargetFeature(None, "lag", configuration.period_k)]
    return list(configuration.lag_features)


def _model_input_names(configuration) -> list:
    """The columns and features a Configuration feeds to a model, wherever it lists them."""
    if isinstance(configuration, SeasonalConfiguration):
        return []
    return _input_names(configuration)


def _check_target_transformations(declaration: Declaration, config_id: str, transformations: list) -> None:
    allowed = declaration.allowed_target_features
    for feature in transformations:
        name, period = feature.name, feature.period.days
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
            f.kind == feature.kind and f.period == feature.period for f in allowed
        )
        if not declared:
            raise _refuse(
                "TARGET_TRANSFORMATION_NOT_ALLOWED",
                f"configuration {config_id!r} uses a transformation of the target ({feature!r}) that the Workload does not declare",
                config_id=config_id,
                period=period,
                **named,
            )


def _check_ridge_inputs(config_id: str, configuration: RidgeConfiguration) -> None:
    # Every model input goes through the encoder or the scaler, and every column they take is a
    # model input: nothing is dropped by a remainder, nothing is invented.
    model_inputs = [f.name for f in configuration.lag_features] + list(configuration.calendar_columns)
    transformed = set(configuration.encoder.columns) | set(configuration.scaler.columns)
    for name in model_inputs:
        if name not in transformed:
            raise _refuse(
                "MODEL_INPUT_NOT_TRANSFORMED",
                f"input {name!r} of {config_id!r} is taken by neither the encoder nor the scaler",
                config_id=config_id,
                feature=name,
            )
    for transformer in ("encoder", "scaler"):
        for name in getattr(configuration, transformer).columns:
            if name not in model_inputs:
                raise _refuse(
                    "TRANSFORMER_COLUMN_NOT_A_MODEL_INPUT",
                    f"the {transformer} of {config_id!r} takes {name!r}, which is not a model input",
                    config_id=config_id,
                    feature=name,
                    transformer=transformer,
                )


def validate_configuration(declaration: Declaration, config_id: str) -> None:
    """Refuse a Configuration that breaks a declared rule, once the schema has passed.
    The checks that apply to every Configuration run for every kind."""
    typed(declaration, Declaration)
    configuration = declared_configuration(declaration, config_id)
    require_keys(declaration, "forbidden_features", "allowed_target_features")
    forbidden = declaration.forbidden_features
    for name in _model_input_names(configuration):
        if name in forbidden:
            raise _refuse(
                "FORBIDDEN_FEATURE",
                f"configuration {config_id!r} uses {name!r}, which is forbidden at date t",
                config_id=config_id,
                feature=name,
            )
    _check_target_transformations(declaration, config_id, _target_transformations(configuration))
    if isinstance(configuration, RidgeConfiguration):
        _check_ridge_inputs(config_id, configuration)


def load_configuration(workload_dir: Path, config_id: str):
    """Read the Workload's declaration and the Configuration `config_id`, validated for its kind."""
    declaration = load_declaration(workload_dir)
    configuration = checked_configuration(declaration, config_id)
    return {"declaration": declaration, "configuration": configuration}


def checked_configuration(declaration: Declaration, config_id: str):
    """The Configuration `config_id` of a loaded declaration, once `validate_configuration` has passed."""
    typed(declaration, Declaration)
    require_keys(declaration, "target_column")
    configuration = declared_configuration(declaration, config_id)
    validate_configuration(declaration, config_id)
    return configuration
