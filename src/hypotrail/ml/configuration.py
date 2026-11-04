"""Validation of a Configuration against its Workload's declarations.

Standard library only. The Workload declares `forbidden_features` (columns that
are not known at date t) and `allowed_target_features` (the only transformations
of the target a Configuration may use). This module only checks a Configuration
against those declarations; it holds no list of its own. A Configuration that
breaks a rule is refused with a coded error, before anything is fitted or
predicted. Nothing is dropped or included silently.

The model inputs are the lag feature names and `calendar_columns`. The forbidden-feature check
reads them and the `columns` of the encoder and of the scaler; the encoder and the scaler must
together take exactly the model inputs.
"""

from hypotrail.core.errors import InvalidInputError


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


# Partitions that can never be fitted on: evaluation and exposure (SPEC §2, ML-05).
NEVER_FITTED = ("dev", "public_check")


def _check_fit_partition(declaration: dict, config_id: str, configuration: dict) -> None:
    """The Partition to fit on is the Workload's protocol; a Configuration cannot pick another."""
    if "fit_partition" in configuration:
        raise _refuse(
            "FIT_PARTITION_NOT_A_CONFIGURATION_CHOICE",
            f"configuration {config_id!r} declares a fit partition; only the Workload does",
            config_id=config_id,
        )
    partition = _declared(declaration, "fit_partition")
    if partition in NEVER_FITTED:
        raise _refuse(
            "FIT_PARTITION_NOT_ALLOWED",
            f"the Workload declares {partition!r} as its fit partition; it can never be fitted on",
            partition=partition,
        )
    if partition not in _declared(declaration, "partitions"):
        raise _refuse(
            "FIT_PARTITION_NOT_DECLARED",
            f"the Workload's fit partition {partition!r} is not one of its declared partitions",
            partition=partition,
        )


def _validate_seasonal(declaration: dict, config_id: str, configuration: dict) -> None:
    """`seasonal_k` uses the target k periods earlier: a lag the Workload must declare as allowed."""
    allowed = _declared(declaration, "allowed_target_features")
    k = configuration["period_k"]
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise _refuse(
            "TARGET_FEATURE_NOT_PAST",
            f"configuration {config_id!r} reaches date t or later (period {k!r})",
            config_id=config_id,
            period=k,
        )
    if not any(f["kind"] == "lag" and f["period"] == k for f in allowed):
        raise _refuse(
            "TARGET_TRANSFORMATION_NOT_ALLOWED",
            f"configuration {config_id!r} uses the target {k} periods earlier, which the Workload does not declare as allowed",
            config_id=config_id,
            period=k,
        )


def validate_configuration(declaration: dict, config_id: str, configuration: dict) -> None:
    _check_fit_partition(declaration, config_id, configuration)
    if "period_k" in configuration:
        _validate_seasonal(declaration, config_id, configuration)
        return
    forbidden = _declared(declaration, "forbidden_features")
    allowed = _declared(declaration, "allowed_target_features")

    for name in _input_names(configuration):
        if name in forbidden:
            raise _refuse(
                "FORBIDDEN_FEATURE",
                f"configuration {config_id!r} uses {name!r}, which is forbidden at date t",
                config_id=config_id,
                feature=name,
            )

    for feature in configuration["lag_features"]:
        name, period = feature["name"], feature["period"]
        if not isinstance(period, int) or isinstance(period, bool) or period < 1:
            raise _refuse(
                "TARGET_FEATURE_NOT_PAST",
                f"feature {name!r} of {config_id!r} reaches date t or later (period {period!r})",
                config_id=config_id,
                feature=name,
                period=period,
            )
        if feature not in allowed:
            raise _refuse(
                "TARGET_TRANSFORMATION_NOT_ALLOWED",
                f"feature {name!r} of {config_id!r} is not a declared transformation of the target",
                config_id=config_id,
                feature=name,
            )

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
