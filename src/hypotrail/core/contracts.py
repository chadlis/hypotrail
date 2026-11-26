"""The contract schema (`contracts.schema.json`) and the one validator of every persisted record.

The schema is derived from the kit's `schemas/contracts.schema.json` and owned here (chadlis/hypotrail#64,
Tightened A2): the kit's copy is not changed. It keeps every field and constraint of the kit's
envelopes, renames the Criterion states and counters of the #1 amendment (`unscored`, `errored`)
and adds the fields and the two record kinds (`freeze`, `exposure`) that the tickets of slice #9
name. `jsonschema` is the one validator (ENV-02). A record that does not match is refused with
`CONTRACT_VIOLATION` (exit 3), whose details give the `kind`, the `path` of the first fault and its
`message`; a record is validated before it is written and after it is read.
"""

import json
from functools import cache
from importlib import resources

from jsonschema import Draft202012Validator

from hypotrail.core.errors import IntegrityError

SCHEMA_NAME = "contracts.schema.json"


@cache
def schema() -> dict:
    document = json.loads(resources.files(__package__).joinpath(SCHEMA_NAME).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(document)
    return document


@cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(schema())


def validate(record) -> None:
    """Refuse a record that is not valid against the contract schema."""
    errors = sorted(_validator().iter_errors(record), key=lambda error: [str(step) for step in error.absolute_path])
    if not errors:
        return
    kind = record.get("kind") if isinstance(record, dict) else None
    # `oneOf` at the root hides the fault: report the fault in the definition the record's kind selects, the one of its own
    # `schema_version` when the kind has several, else the first of that kind.
    selected = [e for e in errors if e.validator != "oneOf"]
    if kind is not None and not selected:
        of_kind = [name for name, d in schema()["$defs"].items() if d.get("properties", {}).get("kind", {}).get("const") == kind]
        version = record.get("schema_version")
        definition = next(
            (name for name in of_kind if schema()["$defs"][name]["properties"].get("schema_version", {}).get("const") == version),
            of_kind[0] if of_kind else None,
        )
        if definition is not None:
            sub = Draft202012Validator({"$ref": f"#/$defs/{definition}", "$defs": schema()["$defs"]})
            selected = sorted(sub.iter_errors(record), key=lambda error: [str(step) for step in error.absolute_path])
    error = (selected or errors)[0]
    path = "/" + "/".join(str(step) for step in error.absolute_path)
    raise IntegrityError(
        "CONTRACT_VIOLATION",
        f"{kind or 'record'} does not match the contract schema at {path}: {error.message}",
        stage="contract",
        details={"kind": kind, "path": path, "message": error.message},
    )
