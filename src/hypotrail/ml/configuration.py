"""Validation of a Configuration against its Workload's declarations.

Standard library only. The Workload declares `forbidden_features` (columns that
are not known at date t) and `allowed_target_features` (the only transformations
of the target a Configuration may use). This module only checks a Configuration
against those declarations; it holds no list of its own. A Configuration that
breaks a rule is refused with a coded error, before anything is fitted or
predicted. Nothing is dropped or included silently.

The model inputs checked are the lag feature names, `calendar_columns`, and the
`columns` of the encoder and of the scaler.
"""

from hypotrail.core.errors import InvalidInputError


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="configuration", details=details)


def _declared(declaration: dict, key: str) -> list:
    if key not in declaration:
        raise _refuse("DECLARATION_INCOMPLETE", f"declaration lacks {key!r}", key=key)
    return declaration[key]


def _input_names(configuration: dict) -> list:
    names = [f["name"] for f in configuration["lag_features"]]
    names += configuration["calendar_columns"]
    names += configuration["encoder"]["columns"]
    names += configuration["scaler"]["columns"]
    return names


def validate_configuration(declaration: dict, config_id: str, configuration: dict) -> None:
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
