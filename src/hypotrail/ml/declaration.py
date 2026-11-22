"""The Workload declaration (`workload.json`): checked as a whole against one JSON Schema, then read once into typed objects.

`workload.schema.json` describes the whole shape of the declaration: every key, at every level,
each kind of Configuration with the keys it takes, and the type and the allowed values of every
leaf. `jsonschema` checks it (ENV-02: one schema validator). A declaration that does not match is
refused with a coded `InvalidInputError`, stage `declaration`, whose details give `key` and
`path`, before anything is read, fitted, predicted or written. Nothing is dropped or defaulted
silently. The schema is the only description of the shape: no key, object, list or type is
checked by hand elsewhere, apart from the two checks named below.

The codes:

- `DECLARATION_INCOMPLETE`: a key is missing;
- `DECLARATION_KEY_UNKNOWN`: a key the Track does not know, in a closed object;
- `DECLARATION_WRONG_TYPE`: a value of the wrong JSON type, leaf or container;
- `DECLARATION_VALUE_NOT_ALLOWED`: a value of the right type that the schema does not allow
  (below a minimum, outside the allowed values, an empty string, an invalid date);
- `CONFIGURATION_KIND_UNKNOWN`: a Configuration with no kind or an unknown kind;
- `CONFIGURATION_KEY_NOT_FOR_KIND`: a key that does not belong to the kind of its Configuration.

Two kinds of check stay in Track code, next to their use (ADR 0002, clarification of 2026-11-04):

- whether a key is required: only `partitions` is required by the schema, because it is the one
  key every public entry point reads. Every other key is read by some entry points only; each of
  them refuses its absence with `DECLARATION_INCOMPLETE` through `require_keys`, before it
  writes anything;
- whether a period can be applied to actual dates: a `Period` (`periods.py`) refuses, with
  `DECLARATION_VALUE_NOT_ALLOWED` naming the period's key and path, a shift that leaves the
  calendar. Its stage is `periods`, not `declaration`, so it is told from a refusal at load.

`load_declaration` is the one loader: it reads the file, checks it against the schema and returns
a `Declaration` (`declaration_of` does the same from bytes, such as the copy of the file an Attempt keeps), a tree of frozen dataclasses (tuples and read-only mappings, no `dict` or `list`
of the file). Every computation of the Track starts from it and refuses anything else with a
`TypeError`; no other module indexes the raw dictionary. A root key that the schema leaves
optional is `None` on the `Declaration` when the file lacks it. The three descriptive root keys are
not kept.

Three root keys are descriptive and no Track code reads them (`schema_version`, `track`,
`licence_notice`). The keys of `partitions` and of `configurations` are names the Workload
chooses.

The rules that relate values to each other or to the protocol also stay in Track code and run
after the schema: the `train` Partition being declared (here), and in `configuration.py` and
`memberships.py` the forbidden features, the target transformations, the encoder and the
scaler covering the model inputs, and the Partition ranges.
"""

import datetime
import json
import math
from dataclasses import dataclass, fields, is_dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, Mapping, Optional

from jsonschema import Draft202012Validator, validators

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.partitions import TRAIN
from hypotrail.ml.periods import Period

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
    elif "propertyNames" in error.schema_path:
        # An empty name of a Partition or of a Configuration: the key is the name, the path the object that holds it.
        yield _NOT_ALLOWED, path + (error.instance,), _refuse(
            "DECLARATION_VALUE_NOT_ALLOWED",
            f"{where} has a name that is not allowed: {error.instance!r} ({error.message})",
            key=error.instance,
            path=where,
        )
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


# --- the typed declaration ------------------------------------------------------------------


@dataclass(frozen=True)
class PartitionRange:
    name: str
    first: datetime.date
    last: datetime.date


@dataclass(frozen=True)
class TargetFeature:
    name: str
    kind: str
    period: Period


@dataclass(frozen=True)
class PostProcessing:
    clip_min: float


@dataclass(frozen=True)
class Encoder:
    columns: tuple
    handle_unknown: str
    sparse_output: bool


@dataclass(frozen=True)
class Scaler:
    columns: tuple


@dataclass(frozen=True)
class RidgeSettings:
    alpha: float
    fit_intercept: bool
    solver: str


@dataclass(frozen=True)
class SeasonalConfiguration:
    kind: ClassVar[str] = SEASONAL
    period_k: Period
    post_processing: PostProcessing


@dataclass(frozen=True)
class RidgeConfiguration:
    kind: ClassVar[str] = RIDGE
    lag_features: tuple
    calendar_columns: tuple
    encoder: Encoder
    scaler: Scaler
    ridge: RidgeSettings
    post_processing: PostProcessing


@dataclass(frozen=True)
class Declaration:
    """A Workload declaration; an optional root key the file lacks is `None`."""

    partitions: tuple
    data_file: Optional[str] = None
    id_prefix: Optional[str] = None
    date_column: Optional[str] = None
    target_column: Optional[str] = None
    target_unit: Optional[str] = None
    question: Optional[str] = None
    objective: Optional[str] = None
    limitations: Optional[tuple] = None
    period_k: Optional[Period] = None
    forbidden_features: Optional[tuple] = None
    allowed_target_features: Optional[tuple] = None
    configurations: Optional[Mapping] = None


def plain(value):
    """The JSON content of a typed declaration object: what a record keeps of a Configuration or a Partition.

    A `Period` is its number of days, a date its ISO text, a tuple a list and a read-only mapping a dict; a
    dataclass is a dict of its fields, with the `kind` of a Configuration. The result is built from the
    typed objects only, never from the file, so the order of the keys in the file does not reach it.
    """
    if isinstance(value, Period):
        return value.days
    if isinstance(value, datetime.date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        content = {field.name: plain(getattr(value, field.name)) for field in fields(value)}
        if isinstance(getattr(type(value), "kind", None), str):
            content["kind"] = type(value).kind
        return content
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


def typed(value, kind):
    """`value`, if it is a `kind`; a raw dictionary (or anything else) is a `TypeError`."""
    if not isinstance(value, kind):
        raise TypeError(f"expected a {kind.__name__} read by load_declaration, got {type(value).__name__}")
    return value


def _features(raw, where) -> tuple:
    return tuple(
        TargetFeature(f["name"], f["kind"], Period(f["period"], "period", f"{where}.{index}.period"))
        for index, f in enumerate(raw)
    )


def _configuration(config_id, raw):
    post = PostProcessing(raw["post_processing"]["clip_min"])
    where = f"configurations.{config_id}"
    if raw["kind"] == SEASONAL:
        return SeasonalConfiguration(Period(raw["period_k"], "period_k", f"{where}.period_k"), post)
    return RidgeConfiguration(
        _features(raw["lag_features"], f"{where}.lag_features"),
        tuple(raw["calendar_columns"]),
        Encoder(tuple(raw["encoder"]["columns"]), raw["encoder"]["handle_unknown"], raw["encoder"]["sparse_output"]),
        Scaler(tuple(raw["scaler"]["columns"])),
        RidgeSettings(raw["ridge"]["alpha"], raw["ridge"]["fit_intercept"], raw["ridge"]["solver"]),
        post,
    )


def _declaration(raw: dict) -> Declaration:
    """The typed objects of a declaration the schema has accepted."""
    partitions = tuple(
        PartitionRange(name, *(datetime.date.fromisoformat(bound) for bound in bounds))  # dates: guaranteed by the schema
        for name, bounds in raw["partitions"].items()
    )
    optional = {key: raw[key] for key in ("data_file", "id_prefix", "date_column", "target_column", "target_unit") if key in raw}
    optional.update({key: raw[key] for key in ("question", "objective") if key in raw})
    if "limitations" in raw:
        optional["limitations"] = tuple(raw["limitations"])
    if "period_k" in raw:
        optional["period_k"] = Period(raw["period_k"])
    if "forbidden_features" in raw:
        optional["forbidden_features"] = tuple(raw["forbidden_features"])
    if "allowed_target_features" in raw:
        optional["allowed_target_features"] = _features(raw["allowed_target_features"], "allowed_target_features")
    if "configurations" in raw:
        optional["configurations"] = MappingProxyType(
            {config_id: _configuration(config_id, config) for config_id, config in raw["configurations"].items()}
        )
    return Declaration(partitions, **optional)


def check_schema(declaration) -> None:
    """Refuse a declaration that does not match the schema, with the most specific fault first."""
    found = []
    for error in _validator().iter_errors(declaration):
        found.extend(_refusals(error))
    if found:
        found.sort(key=lambda item: (item[0], _dotted(item[1])))
        raise found[0][2]


def require_keys(declaration: Declaration, *keys: str) -> None:
    """Refuse the absence of a key the calling entry point reads and the schema leaves optional."""
    typed(declaration, Declaration)
    for key in keys:
        if getattr(declaration, key) is None:
            raise _refuse("DECLARATION_INCOMPLETE", f"declaration lacks {key!r}", key=key, path="")


def _finite(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(text)
    return value


def _not_json(constant):
    raise ValueError(constant)


def load_declaration(workload_dir: Path) -> Declaration:
    """The one loader: read `workload.json`, check it against the schema, return the typed declaration."""
    path = Path(workload_dir) / DECLARATION_NAME
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise _refuse("FILE_NOT_FOUND", f"declaration not found: {path}", key=DECLARATION_NAME, path="", file=str(path)) from None
    except ValueError:  # bytes that are not UTF-8
        raise _not_valid(str(path)) from None
    return _checked(text, str(path))


def declaration_of(data: bytes, file: str) -> Declaration:
    """The typed declaration of the bytes of a `workload.json`, checked as `load_declaration` checks it; `file` names where they come from."""
    try:
        text = data.decode("utf-8")
    except ValueError:
        raise _not_valid(file) from None
    return _checked(text, file)


def _not_valid(file: str) -> InvalidInputError:
    return _refuse("FILE_NOT_JSON", f"declaration is not valid JSON: {file}", key=DECLARATION_NAME, path="", file=file)


def _checked(text: str, file: str) -> Declaration:
    try:
        declaration = json.loads(text, parse_float=_finite, parse_constant=_not_json)
    except ValueError:  # json.JSONDecodeError, a constant such as NaN, a float beyond the double range
        raise _not_valid(file) from None
    check_schema(declaration)
    if TRAIN not in declaration["partitions"]:
        raise _refuse(
            "TRAIN_PARTITION_NOT_DECLARED",
            f"the Workload does not declare the {TRAIN!r} Partition, which the Track fits on",
            key=TRAIN,
            path="partitions",
            partition=TRAIN,
        )
    return _declaration(declaration)
