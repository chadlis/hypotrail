"""The shape of a Workload declaration (`workload.json`), checked as a whole, standard library only.

The declaration is read once and refused before anything is computed when it does not have
the shape the Track reads: a required key is missing, a key the Track does not know is
present, or an object or a list is something else. Each refusal is a coded
`InvalidInputError` that names the key (`path` gives where, when it is not at the root).
Nothing is dropped or defaulted silently.

Only containers are typed here. The values inside them (a period, a bound, a column name)
keep the checks that already govern them, in `configuration.py` and the readers.

The schema below is the only list of keys. Three root keys are descriptive and no Track
code reads them (`schema_version`, `track`, `licence_notice`): they are accepted and may be
absent. The keys of `partitions` and of `configurations` are names the Workload chooses;
the one Partition the Track requires is `train` (SPEC section 2: it fits the preprocessing
and the model), whatever the Configurations are.
"""

import json
from pathlib import Path

from hypotrail.core.errors import InvalidInputError
from hypotrail.ml.partitions import TRAIN

DECLARATION_NAME = "workload.json"


def _refuse(code, message, stage="declaration", **details):
    return InvalidInputError(code, message, stage=stage, details=details)


class Obj:
    """An object with the keys it requires, the keys it may carry, and optionally a node for any other key."""

    def __init__(self, required=(), optional=(), *, open=None):
        self.required = dict(required)
        self.optional = dict(optional)
        self.open = open


class ListOf:
    def __init__(self, item=None):
        self.item = item


def _dotted(path) -> str:
    return ".".join(str(step) for step in path)


def _wrong_type(path, expected):
    return _refuse(
        "DECLARATION_WRONG_TYPE",
        f"{_dotted(path) or 'the declaration'} must be {expected}",
        key=path[-1] if path else None,
        path=_dotted(path),
        expected=expected,
    )


def _missing(path, key):
    details = {"key": key}
    if path:
        details["path"] = _dotted(path)
    return _refuse("DECLARATION_INCOMPLETE", f"declaration lacks {_dotted(path + (key,))!r}", **details)


def _unknown(path, key):
    details = {"key": key}
    if path:
        details["path"] = _dotted(path)
    return _refuse(
        "DECLARATION_KEY_UNKNOWN", f"declaration has a key the Track does not know: {_dotted(path + (key,))!r}", **details
    )


def _check(value, node, path):
    if node is None:
        return
    if callable(node):
        node(value, path)
    elif isinstance(node, ListOf):
        if not isinstance(value, list):
            raise _wrong_type(path, "a list")
        for index, item in enumerate(value):
            _check(item, node.item, path + (index,))
    else:
        if not isinstance(value, dict):
            raise _wrong_type(path, "an object")
        known = node.required.keys() | node.optional.keys()
        for key in value:
            if key not in known and node.open is None:
                raise _unknown(path, key)
        for key in node.required:
            if key not in value:
                raise _missing(path, key)
        for key, item in value.items():
            _check(item, node.required.get(key, node.optional.get(key, node.open)), path + (key,))


SEASONAL = "seasonal_baseline"
RIDGE = "ridge_pipeline"

_LAG = Obj({"name": None, "kind": None, "period": None})
_CLIP = Obj({"clip_min": None})
# The kinds of Configuration the Track knows, with what each one takes (`kind` included).
KIND_NODES = {
    SEASONAL: Obj({"kind": None, "period_k": None, "post_processing": _CLIP}),
    RIDGE: Obj({
        "kind": None,
        "lag_features": ListOf(_LAG),
        "calendar_columns": ListOf(),
        "encoder": Obj({"columns": ListOf(), "handle_unknown": None, "sparse_output": None}),
        "scaler": Obj({"columns": ListOf()}),
        "ridge": Obj({"alpha": None, "fit_intercept": None, "solver": None}),
        "post_processing": _CLIP,
    }),
}
KINDS = {kind: set(node.required) for kind, node in KIND_NODES.items()}


def kind_of(config_id: str, configuration: dict) -> str:
    """The kind a Configuration declares; an unknown kind, or a key not of its kind, is refused."""
    kind = configuration.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        details = {"config_id": config_id}
        if "kind" not in configuration:
            details["key"] = "kind"
        # The value is shown as JSON scalars only, so the details stay printable.
        details["kind"] = kind if isinstance(kind, (str, int, float, bool, type(None))) else repr(kind)
        raise _refuse(
            "CONFIGURATION_KIND_UNKNOWN",
            f"configuration {config_id!r} declares the kind {kind!r}; the Track knows {sorted(KINDS)}",
            stage="configuration",
            **details,
        )
    for key in configuration:
        if key not in KINDS[kind]:
            raise _refuse(
                "CONFIGURATION_KEY_NOT_FOR_KIND",
                f"configuration {config_id!r} is of kind {kind!r}, which takes no key {key!r}",
                stage="configuration",
                config_id=config_id,
                kind=kind,
                key=key,
            )
    return kind


def _configuration(value, path):
    if not isinstance(value, dict):
        raise _wrong_type(path, "an object")
    kind = kind_of(path[-1], value)
    _check(value, KIND_NODES[kind], path)


_ROOT = Obj(
    required={
        "data_file": None,
        "id_prefix": None,
        "date_column": None,
        "target_column": None,
        "target_unit": None,
        "period_k": None,
        "forbidden_features": ListOf(),
        "allowed_target_features": ListOf(_LAG),
        "partitions": Obj(open=ListOf()),
        "configurations": Obj(open=_configuration),
    },
    optional={"schema_version": None, "track": None, "licence_notice": None},
)


def validate_declaration(declaration) -> None:
    """Refuse a declaration that lacks a required key, has an unknown key or a wrongly typed container."""
    _check(declaration, _ROOT, ())
    if TRAIN not in declaration["partitions"]:
        raise _refuse(
            "TRAIN_PARTITION_NOT_DECLARED",
            f"the Workload does not declare the {TRAIN!r} Partition, on which every Configuration is fitted",
            stage="configuration",
            key=TRAIN,
            path="partitions",
            partition=TRAIN,
        )


def load_declaration(workload_dir: Path) -> dict:
    path = Path(workload_dir) / DECLARATION_NAME
    try:
        declaration = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise _refuse("FILE_NOT_FOUND", f"declaration not found: {path}", file=str(path)) from None
    except json.JSONDecodeError:
        raise _refuse("FILE_NOT_JSON", f"declaration is not valid JSON: {path}", file=str(path)) from None
    validate_declaration(declaration)
    return declaration
