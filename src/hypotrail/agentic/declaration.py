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
- `CONFIGURATION_CYCLE`: Configurations extend each other in a loop;
- `PARTITIONS_NOT_DISJOINT`: a Case ID is listed in two Partitions.

The last three relate values to each other, so they stay in Track code, next to their use.
`PARTITIONS_NOT_DISJOINT` is checked when a `Workload` is constructed, which reads each declared
Cases file once with `cases.load_cases`: an unreadable file or an unparsable line is refused there
too (`FILE_NOT_FOUND`, `FILE_NOT_JSON`), and so is a Case ID repeated inside one file
(`CASE_ID_NOT_UNIQUE`; a Case ID in two files is `PARTITIONS_NOT_DISJOINT`).

Whether a key is required is also Track code. The schema leaves `scenarios`, `answer_schema` and
each Partition under `cases` optional, and the entry point that reads one refuses its absence:
`run_fixture` (the `scripted_fixture` Mode) refuses `answer_schema` with
`ANSWER_SCHEMA_NOT_DECLARED` and `scenarios` with its own code, and the readers of a Partition
refuse it with `PARTITION_NOT_DECLARED`. `rescore_log` and `rescore_episodes` take the answer
schema as an argument and read none from the declaration.

The Partition roles (`dev`, `public_check`) are the Track's (`hypotrail.agentic.partitions`): the
schema closes `cases` to them. The answer schema is a file the declaration names (`answer_schema`).
The scenarios file of the `scripted_fixture` Mode is checked the same way against
`scenarios.schema.json`, with the codes `SCENARIOS_INCOMPLETE`, `SCENARIOS_KEY_UNKNOWN`,
`SCENARIOS_WRONG_TYPE` and `SCENARIOS_VALUE_NOT_ALLOWED`, stage `fixture`.

A Configuration is a full `system_text`, or `extends` another Configuration with an
`added_instruction`. Its resolved text is the extended text followed by the instruction and
nothing else, so `verify` differs from `plain` only by the instruction. The References are named
by the declaration but never read here: they are not an input of the task builder.
"""

import json
from dataclasses import dataclass, field
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
    "null": "null",
}
# The most specific refusal first when a declaration has several faults.
_KEY_UNKNOWN, _MISSING, _WRONG_TYPE, _NOT_ALLOWED = range(4)


@dataclass(frozen=True)
class Document:
    """A JSON document the Track checks against one JSON Schema, and how it refuses it."""

    schema_name: str
    code_prefix: str
    stage: str
    noun: str

    def code(self, kind: str) -> str:
        return f"{self.code_prefix}_{kind}"


DECLARATION = Document(SCHEMA_NAME, "DECLARATION", "declaration", "declaration")
SCENARIOS = Document("scenarios.schema.json", "SCENARIOS", "fixture", "scenarios file")


def _refuse(code, message, *, stage="declaration", **details):
    return InvalidInputError(code, message, stage=stage, details=details)


def _dotted(path) -> str:
    return ".".join(str(step) for step in path)


@cache
def _validator(schema_name: str) -> Draft202012Validator:
    schema = json.loads(resources.files(__package__).joinpath(schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def read_json(path: Path, *, stage: str, noun: str, key: str | None = None):
    """The JSON in a file, or a coded refusal: FILE_NOT_FOUND, FILE_NOT_JSON."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise _refuse("FILE_NOT_FOUND", f"{noun} not found: {path}", stage=stage, key=key, path="", file=str(path)) from None
    except ValueError:
        raise _refuse("FILE_NOT_JSON", f"{noun} is not valid JSON: {path}", stage=stage, key=key, path="", file=str(path)) from None


def _refusals(error, document):
    path = tuple(error.absolute_path)
    where = _dotted(path)
    noun = document.noun

    def refuse(kind, message, **details):
        return _refuse(document.code(kind), message, stage=document.stage, **details)

    if error.validator == "required":
        for key in error.validator_value:
            if key not in error.instance:
                yield _MISSING, path + (key,), refuse(
                    "INCOMPLETE", f"{noun} lacks {_dotted(path + (key,))!r}", key=key, path=where
                )
    elif error.validator == "additionalProperties":
        known = error.schema.get("properties", {})
        for key in error.instance:
            if key not in known:
                yield _KEY_UNKNOWN, path + (key,), refuse(
                    "KEY_UNKNOWN",
                    f"{noun} has a key the Track does not know: {_dotted(path + (key,))!r}",
                    key=key,
                    path=where,
                )
    elif error.validator == "type":
        expected = error.validator_value
        expected = _ARTICLE[expected] if isinstance(expected, str) else " or ".join(_ARTICLE[t] for t in expected)
        names = [s for s in path if isinstance(s, str)]
        yield _WRONG_TYPE, path, refuse(
            "WRONG_TYPE",
            f"{where or 'the ' + noun} must be {expected}",
            key=names[-1] if names else None,
            path=where,
            expected=expected,
        )
    else:
        names = [s for s in path if isinstance(s, str)]
        yield _NOT_ALLOWED, path, refuse(
            "VALUE_NOT_ALLOWED",
            f"{where or 'the ' + noun} is not allowed: {error.message}",
            key=names[-1] if names else None,
            path=where,
        )


def check_document(document_value, document: Document) -> None:
    """Refuse a document that does not match its schema, with the most specific fault first."""
    found = [
        item for error in _validator(document.schema_name).iter_errors(document_value) for item in _refusals(error, document)
    ]
    if found:
        found.sort(key=lambda item: (item[0], _dotted(item[1])))
        raise found[0][2]


def check_schema(declaration) -> None:
    """Refuse a declaration that does not match the schema, with the most specific fault first."""
    check_document(declaration, DECLARATION)


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
    _owner: dict = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        """Read each declared Cases file once; refuse an unreadable file, an unparsable line, a shared Case ID.

        No Workload exists with overlapping or unreadable Partitions (GLOSSARY: a Partition is a
        named, disjoint subset), so `partition_of` has no precondition.
        """
        owner: dict[str, str] = {}
        shared: dict[str, set[str]] = {}
        for partition, file in self.declaration["cases"].items():
            for case_id in {case["case_id"] for case in load_cases(self.directory / file)}:
                if case_id in owner:
                    shared.setdefault(case_id, {owner[case_id]}).add(partition)
                else:
                    owner[case_id] = partition
        if shared:
            raise _refuse(
                "PARTITIONS_NOT_DISJOINT",
                f"a Case is listed in two Partitions: {sorted(shared)}",
                path="cases",
                case_ids=sorted(shared),
                partitions=sorted({role for roles in shared.values() for role in roles}),
            )
        object.__setattr__(self, "_owner", owner)

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

    @property
    def answer_schema_path(self) -> Path:
        """The answer schema file. Optional in the declaration: its readers refuse its absence (ANSWER_SCHEMA_NOT_DECLARED)."""
        declared = self.declaration.get("answer_schema")
        if declared is None:
            raise _refuse(
                "ANSWER_SCHEMA_NOT_DECLARED",
                f"the Workload {self.workload_id!r} declares no answer schema",
                path="answer_schema",
            )
        return self.directory / declared

    def answer_schema(self) -> dict:
        """The Workload's answer schema, read from the path its declaration gives."""
        return read_json(self.answer_schema_path, stage="declaration", noun="answer schema", key="answer_schema")

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

    def partition_of(self, case_id: str) -> str | None:
        """The Partition role the declaration gives a Case, or None for a Case it does not list."""
        return self._owner.get(case_id)

    def cases(self, partition: str = "dev", case_ids: list[str] | None = None) -> list[dict]:
        """The Cases of a declared Partition. Nothing here reads the References."""
        return load_cases(self.cases_path(partition), case_ids)


def load_workload(workload_dir: Path) -> Workload:
    directory = Path(workload_dir)
    declaration = read_json(directory / DECLARATION_NAME, stage="declaration", noun="declaration", key=DECLARATION_NAME)
    check_schema(declaration)
    check_configurations(declaration)
    return Workload(directory, declaration)
