"""The Workload declaration of the agentic Track (`workload.json`), checked against one JSON Schema.

`workload.schema.json` describes the whole shape (ADR 0002 and its clarification of 2026-11-04):
every key, its type and its allowed values. `jsonschema` checks it. A declaration that does not
match is refused with a coded `InvalidInputError`, stage `declaration`, before Inspect is imported:
this module imports none of it. The codes:

- `DECLARATION_INCOMPLETE`: a key is missing;
- `DECLARATION_KEY_UNKNOWN`: a key the Track does not know, in a closed object;
- `DECLARATION_WRONG_TYPE`: a value of the wrong JSON type;
- `DECLARATION_VALUE_NOT_ALLOWED`: a value of the right type the schema does not allow;
- `CONFIGURATION_NOT_DECLARED`: a Configuration extends, or is asked for as, one that is not declared;
- `CONFIGURATION_CYCLE`: Configurations extend each other in a loop.

The last two relate values to each other, so they stay in Track code, next to their use.

A Configuration is a full `system_text`, or `extends` another Configuration with an
`added_instruction`. Its resolved text is the extended text followed by the instruction and
nothing else, so `verify` differs from `plain` only by the instruction. The References are named
by the declaration but never read here: they are not an input of the task builder.
"""

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path

from jsonschema import Draft202012Validator

from hypotrail.agentic.cases import load_cases
from hypotrail.core.errors import InvalidInputError

DECLARATION_NAME = "workload.json"
SCHEMA_NAME = "workload.schema.json"

_ARTICLE = {
    "string": "a string",
    "integer": "an integer",
    "number": "a number",
    "boolean": "a boolean",
    "object": "an object",
    "array": "a list",
}
# The most specific refusal first when a declaration has several faults.
_KEY_UNKNOWN, _MISSING, _WRONG_TYPE, _NOT_ALLOWED = range(4)


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage="declaration", details=details)


def _dotted(path) -> str:
    return ".".join(str(step) for step in path)


@cache
def _validator() -> Draft202012Validator:
    schema = json.loads(resources.files(__package__).joinpath(SCHEMA_NAME).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _refusals(error):
    path = tuple(error.absolute_path)
    where = _dotted(path)
    if error.validator == "required":
        for key in error.validator_value:
            if key not in error.instance:
                yield _MISSING, path + (key,), _refuse(
                    "DECLARATION_INCOMPLETE", f"declaration lacks {_dotted(path + (key,))!r}", key=key, path=where
                )
    elif error.validator == "additionalProperties":
        known = error.schema.get("properties", {})
        for key in error.instance:
            if key not in known:
                yield _KEY_UNKNOWN, path + (key,), _refuse(
                    "DECLARATION_KEY_UNKNOWN",
                    f"declaration has a key the Track does not know: {_dotted(path + (key,))!r}",
                    key=key,
                    path=where,
                )
    elif error.validator == "type":
        expected = error.validator_value
        expected = _ARTICLE[expected] if isinstance(expected, str) else " or ".join(_ARTICLE[t] for t in expected)
        names = [s for s in path if isinstance(s, str)]
        yield _WRONG_TYPE, path, _refuse(
            "DECLARATION_WRONG_TYPE",
            f"{where or 'the declaration'} must be {expected}",
            key=names[-1] if names else None,
            path=where,
            expected=expected,
        )
    else:
        names = [s for s in path if isinstance(s, str)]
        yield _NOT_ALLOWED, path, _refuse(
            "DECLARATION_VALUE_NOT_ALLOWED",
            f"{where or 'the declaration'} is not allowed: {error.message}",
            key=names[-1] if names else None,
            path=where,
        )


def check_schema(declaration) -> None:
    """Refuse a declaration that does not match the schema, with the most specific fault first."""
    found = [item for error in _validator().iter_errors(declaration) for item in _refusals(error)]
    if found:
        found.sort(key=lambda item: (item[0], _dotted(item[1])))
        raise found[0][2]


def _not_declared(name, path, declared):
    return _refuse(
        "CONFIGURATION_NOT_DECLARED",
        f"configuration {name!r} is not declared; the Workload declares {sorted(declared)}",
        configuration=name,
        path=path,
    )


def check_configurations(declaration) -> None:
    configurations = declaration["configurations"]
    for config_id, configuration in configurations.items():
        seen = [config_id]
        while "extends" in configuration:
            base = configuration["extends"]
            if base not in configurations:
                raise _not_declared(base, f"configurations.{seen[-1]}.extends", configurations)
            if base in seen:
                raise _refuse(
                    "CONFIGURATION_CYCLE",
                    f"configurations extend each other in a loop: {' -> '.join(seen + [base])}",
                    configuration=config_id,
                    path=f"configurations.{seen[-1]}.extends",
                )
            seen.append(base)
            configuration = configurations[base]


@dataclass(frozen=True)
class Workload:
    """A validated declaration and the folder its relative paths are read from."""

    directory: Path
    declaration: dict

    @property
    def workload_id(self) -> str:
        return self.declaration["workload_id"]

    @property
    def database_path(self) -> Path:
        return self.directory / self.declaration["database"]["file"]

    @property
    def scenarios_path(self) -> Path | None:
        """The scenarios file of the `scripted_fixture` Mode, or None when the Workload declares none."""
        declared = self.declaration.get("scenarios")
        return None if declared is None else self.directory / declared

    def system_text(self, configuration: str) -> str:
        """The exact system text of a Configuration: the extended text, then its added instruction."""
        configurations = self.declaration["configurations"]
        if configuration not in configurations:
            raise _not_declared(configuration, "configurations", configurations)
        declared = configurations[configuration]
        if "system_text" in declared:
            return declared["system_text"]
        return self.system_text(declared["extends"]) + declared["added_instruction"]

    def cases_path(self, partition: str = "dev") -> Path:
        files = self.declaration["cases"]
        if partition not in files:
            raise _refuse(
                "PARTITION_NOT_DECLARED",
                f"the Workload declares no Cases for {partition!r}; it declares {sorted(files)}",
                partition=partition,
                path="cases",
            )
        return self.directory / files[partition]

    def cases(self, partition: str = "dev", case_ids: list[str] | None = None) -> list[dict]:
        """The Cases of a declared Partition. Nothing here reads the References."""
        return load_cases(self.cases_path(partition), case_ids)


def load_workload(workload_dir: Path) -> Workload:
    directory = Path(workload_dir)
    path = directory / DECLARATION_NAME
    try:
        declaration = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise _refuse("FILE_NOT_FOUND", f"declaration not found: {path}", key=DECLARATION_NAME, path="", file=str(path)) from None
    except ValueError:
        raise _refuse("FILE_NOT_JSON", f"declaration is not valid JSON: {path}", key=DECLARATION_NAME, path="", file=str(path)) from None
    check_schema(declaration)
    check_configurations(declaration)
    return Workload(directory, declaration)
