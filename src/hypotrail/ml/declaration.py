"""The Workload declaration (`workload.json`): checked as a whole against one JSON Schema.

`workload.schema.json` describes the whole shape of the declaration: every key, at every level,
each kind of Configuration with the keys it takes, and the type and the allowed values of every
leaf. `jsonschema` checks it (ENV-02: one schema validator). A declaration that does not match is
refused with a coded `InvalidInputError`, stage `declaration`, whose details give `key` and
`path`, before anything is read, fitted, predicted or written. Nothing is dropped or defaulted
silently. The schema is the only description of the shape: no key, object, list or type is
checked by hand elsewhere.

The codes:

- `DECLARATION_INCOMPLETE`: a key is missing;
- `DECLARATION_KEY_UNKNOWN`: a key the Track does not know, in a closed object;
- `DECLARATION_WRONG_TYPE`: a value of the wrong JSON type, leaf or container;
- `DECLARATION_VALUE_NOT_ALLOWED`: a value of the right type that the schema does not allow
  (below a minimum, outside the allowed values, an empty string, an invalid date);
- `CONFIGURATION_KIND_UNKNOWN`: a Configuration with no kind or an unknown kind;
- `CONFIGURATION_KEY_NOT_FOR_KIND`: a key that does not belong to the kind of its Configuration.

Only `partitions` is required by the schema, because it is the one key every public entry point
reads. Every other key is read by some entry points only; each of them refuses its absence with
`DECLARATION_INCOMPLETE` through `require_keys`, before it writes anything. Three root keys are
descriptive and no Track code reads them (`schema_version`, `track`, `licence_notice`). The keys
of `partitions` and of `configurations` are names the Workload chooses.

The rules that relate values to each other or to the protocol stay in Track code and run after
the schema: the `train` Partition being declared (here), and in `configuration.py` and
`memberships.py` the forbidden features, the target transformations, the encoder and the
scaler covering the model inputs, and the Partition ranges.
"""

import json
import math
from functools import cache
from importlib import resources
from pathlib import Path

from jsonschema import Draft202012Validator, validators

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.partitions import TRAIN

DECLARATION_NAME = "workload.json"
SCHEMA_NAME = "workload.schema.json"

SEASONAL = "seasonal_baseline"
RIDGE = "ridge_pipeline"

# The most specific refusal first when a declaration has several faults.
_KIND_UNKNOWN, _KEY_UNKNOWN, _MISSING, _WRONG_TYPE, _NOT_ALLOWED = range(5)

_ARTICLE = {
    "string": "a string",
    "integer": "an integer",
    "number": "a number",
    "boolean": "a boolean",
    "object": "an object",
    "array": "a list",
}


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="declaration", details=details)


def _dotted(path) -> str:
    return ".".join(str(step) for step in path)


def _key_of(path, default=None):
    """The key a value sits under: the last name on its path (list positions are not keys)."""
    names = [step for step in path if isinstance(step, str)]
    return names[-1] if names else default


@cache
def _validator() -> Draft202012Validator:
    schema = json.loads(resources.files(__package__).joinpath(SCHEMA_NAME).read_text(encoding="utf-8"))
    # JSON has one number type, but a period is a whole number: 7.0 and true are not integers here.
    types = Draft202012Validator.TYPE_CHECKER.redefine(
        "integer", lambda _, value: isinstance(value, int) and not isinstance(value, bool)
    )
    checking = validators.extend(Draft202012Validator, type_checker=types)
    checking.check_schema(schema)
    return checking(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _is_kind(path) -> bool:
    return len(path) == 3 and path[0] == "configurations" and path[2] == "kind"


def _refusals(error):
    """The refusals one schema error stands for, each with its precedence."""
    path = tuple(error.absolute_path)
    where = _dotted(path)
    if error.validator == "required":
        for key in error.validator_value:
            if key in error.instance:
                continue
            child = path + (key,)
            if len(path) == 2 and path[0] == "configurations" and key == "kind":
                yield _KIND_UNKNOWN, child, _kind_unknown(path, error.instance.get("kind"), missing=True)
            else:
                yield _MISSING, child, _refuse(
                    "DECLARATION_INCOMPLETE", f"declaration lacks {_dotted(child)!r}", key=key, path=where
                )
    elif error.validator == "additionalProperties":
        known = error.schema.get("properties", {})
        for key in error.instance:
            if key in known:
                continue
            child = path + (key,)
            if len(path) == 2 and path[0] == "configurations":
                kind = error.instance["kind"]
                yield _KEY_UNKNOWN, child, _refuse(
                    "CONFIGURATION_KEY_NOT_FOR_KIND",
                    f"configuration {path[1]!r} is of kind {kind!r}, which takes no key {key!r}",
                    config_id=path[1],
                    kind=kind,
                    key=key,
                    path=where,
                )
            else:
                yield _KEY_UNKNOWN, child, _refuse(
                    "DECLARATION_KEY_UNKNOWN",
                    f"declaration has a key the Track does not know: {_dotted(child)!r}",
                    key=key,
                    path=where,
                )
    elif error.validator == "type":
        expected = error.validator_value
        expected = _ARTICLE[expected] if isinstance(expected, str) else " or ".join(_ARTICLE[t] for t in expected)
        yield _WRONG_TYPE, path, _refuse(
            "DECLARATION_WRONG_TYPE",
            f"{where or 'the declaration'} must be {expected}",
            key=_key_of(path),
            path=where,
            expected=expected,
        )
    elif error.validator == "enum" and _is_kind(path):
        yield _KIND_UNKNOWN, path, _kind_unknown(path[:-1], error.instance)
    else:
        yield _NOT_ALLOWED, path, _refuse(
            "DECLARATION_VALUE_NOT_ALLOWED",
            f"{where} is not allowed: {error.message}",
            key=_key_of(path),
            path=where,
        )


def _kind_unknown(config_path, kind, missing=False):
    config_id = config_path[1]
    details = {"config_id": config_id, "key": "kind", "path": _dotted(config_path + ("kind",))}
    if not missing:
        # The value is shown as JSON scalars only, so the details stay printable.
        details["kind"] = kind if isinstance(kind, (str, int, float, bool, type(None))) else repr(kind)
    return _refuse(
        "CONFIGURATION_KIND_UNKNOWN",
        f"configuration {config_id!r} declares the kind {kind!r}; the Track knows {[SEASONAL, RIDGE]}"
        if not missing
        else f"configuration {config_id!r} declares no kind; the Track knows {[SEASONAL, RIDGE]}",
        **details,
    )


def check_schema(declaration) -> None:
    """Refuse a declaration that does not match the schema, with the most specific fault first."""
    found = []
    for error in _validator().iter_errors(declaration):
        found.extend(_refusals(error))
    if found:
        found.sort(key=lambda item: (item[0], _dotted(item[1])))
        raise found[0][2]


def validate_declaration(declaration) -> None:
    """The schema, then the rule of the declaration itself: `train` is declared."""
    check_schema(declaration)
    if TRAIN not in declaration["partitions"]:
        raise _refuse(
            "TRAIN_PARTITION_NOT_DECLARED",
            f"the Workload does not declare the {TRAIN!r} Partition, which the Track fits on",
            key=TRAIN,
            path="partitions",
            partition=TRAIN,
        )


def require_keys(declaration: dict, *keys: str) -> None:
    """Refuse the absence of a key the calling entry point reads and the schema leaves optional."""
    for key in keys:
        if key not in declaration:
            raise _refuse("DECLARATION_INCOMPLETE", f"declaration lacks {key!r}", key=key, path="")


def _finite(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(text)
    return value


def _not_json(constant):
    raise ValueError(constant)


def load_declaration(workload_dir: Path) -> dict:
    path = Path(workload_dir) / DECLARATION_NAME
    try:
        declaration = json.loads(
            path.read_text(encoding="utf-8"), parse_float=_finite, parse_constant=_not_json
        )
    except FileNotFoundError:
        raise _refuse("FILE_NOT_FOUND", f"declaration not found: {path}", file=str(path)) from None
    except ValueError:  # json.JSONDecodeError, a constant such as NaN, a float beyond the double range
        raise _refuse("FILE_NOT_JSON", f"declaration is not valid JSON: {path}", file=str(path)) from None
    validate_declaration(declaration)
    return declaration
