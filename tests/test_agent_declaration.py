"""Ticket #44: the Chinook Workload is declared as data and checked against one JSON Schema.

Seam: `load_workload` (the load). A refusal carries a code and comes before Inspect is imported.
"""

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hypotrail.agentic.declaration import load_workload
from hypotrail.core.errors import InvalidInputError

CHINOOK = Path(__file__).resolve().parent.parent / "examples" / "chinook"
DECLARATION = json.loads((CHINOOK / "workload.json").read_text(encoding="utf-8"))


def workload_with(tmp_path, edit):
    target = tmp_path / "chinook"
    target.mkdir(parents=True)
    declaration = copy.deepcopy(DECLARATION)
    edit(declaration)
    (target / "workload.json").write_text(json.dumps(declaration), encoding="utf-8")
    return target


def refusal(workload):
    with pytest.raises(InvalidInputError) as caught:
        load_workload(workload)
    return caught.value


def test_the_real_declaration_is_accepted_and_names_what_the_ticket_lists():
    workload = load_workload(CHINOOK)
    declaration = workload.declaration
    assert declaration["database"]["file"] == "data/Chinook_Sqlite.sqlite"
    assert declaration["licence_notice"] == "licenses/Chinook-MIT.txt"
    assert (CHINOOK / declaration["licence_notice"]).is_file()
    assert declaration["references"] == "references/chinook-references.jsonl"
    assert set(declaration["cases"]) == {"dev", "public_check"}
    assert set(declaration["configurations"]) == {"plain", "verify"}
    assert workload.database_path == CHINOOK / "data" / "Chinook_Sqlite.sqlite"


def test_the_declaration_holds_no_python():
    assert not list(CHINOOK.glob("*.py"))
    assert json.loads((CHINOOK / "workload.json").read_text()) == DECLARATION


@pytest.mark.parametrize("key", ["track", "database", "licence_notice", "cases", "references", "configurations"])
def test_a_missing_required_key_is_refused_with_a_code(tmp_path, key):
    error = refusal(workload_with(tmp_path, lambda d: d.pop(key)))
    assert error.code == "DECLARATION_INCOMPLETE"
    assert error.details["key"] == key


def test_a_missing_key_in_a_nested_object_is_refused_with_its_path(tmp_path):
    error = refusal(workload_with(tmp_path, lambda d: d["database"].pop("file")))
    assert (error.code, error.details["key"], error.details["path"]) == ("DECLARATION_INCOMPLETE", "file", "database")


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d.__setitem__("licence_notice", 3),
        lambda d: d.__setitem__("cases", ["cases/chinook-dev.jsonl"]),
        lambda d: d["database"].__setitem__("file", None),
        lambda d: d["configurations"]["plain"].__setitem__("system_text", ["a", "b"]),
    ],
)
def test_a_wrong_type_is_refused_with_a_code(tmp_path, edit):
    assert refusal(workload_with(tmp_path, edit)).code == "DECLARATION_WRONG_TYPE"


@pytest.mark.parametrize(
    "edit, key",
    [
        (lambda d: d.__setitem__("surprise", 1), "surprise"),
        (lambda d: d["database"].__setitem__("password", "x"), "password"),
        (lambda d: d["configurations"]["plain"].__setitem__("temperature", 0), "temperature"),
        (lambda d: d["configurations"]["verify"].__setitem__("system_text", "x"), "system_text"),
    ],
)
def test_an_unknown_key_in_a_closed_object_is_refused_with_a_code(tmp_path, edit, key):
    error = refusal(workload_with(tmp_path, edit))
    assert error.code in {"DECLARATION_KEY_UNKNOWN", "DECLARATION_VALUE_NOT_ALLOWED"}
    if error.code == "DECLARATION_KEY_UNKNOWN":
        assert error.details["key"] == key


def test_an_unknown_key_at_the_root_is_refused_as_unknown(tmp_path):
    error = refusal(workload_with(tmp_path, lambda d: d.__setitem__("surprise", 1)))
    assert (error.code, error.details["key"]) == ("DECLARATION_KEY_UNKNOWN", "surprise")


def test_a_reference_to_a_configuration_that_is_not_declared_is_refused(tmp_path):
    error = refusal(workload_with(tmp_path, lambda d: d["configurations"]["verify"].__setitem__("extends", "plan")))
    assert error.code == "CONFIGURATION_NOT_DECLARED"
    assert error.details["configuration"] == "plan"
    assert error.details["path"] == "configurations.verify.extends"


def test_a_configuration_cannot_extend_itself_or_loop(tmp_path):
    def loop(d):
        d["configurations"]["plain"] = {"extends": "verify", "added_instruction": "x"}

    assert refusal(workload_with(tmp_path, loop)).code == "CONFIGURATION_CYCLE"


def test_a_declaration_that_is_not_json_or_absent_is_refused(tmp_path):
    (tmp_path / "workload.json").write_text("{not json")
    assert refusal(tmp_path).code == "FILE_NOT_JSON"
    assert refusal(tmp_path / "nowhere").code == "FILE_NOT_FOUND"


def test_a_refusal_comes_before_inspect_is_imported(tmp_path):
    bad = workload_with(tmp_path, lambda d: d.pop("database"))
    program = (
        "import sys\n"
        "from hypotrail.agentic.declaration import load_workload\n"
        "from hypotrail.core.errors import InvalidInputError\n"
        f"try:\n    load_workload({str(bad)!r})\nexcept InvalidInputError as e:\n    print(e.code)\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] == 'inspect_ai'))\n"
    )
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, check=True)
    assert result.stdout.split("\n")[:2] == ["DECLARATION_INCOMPLETE", "[]"]


# --- R1-S1: the agentic Track fixes its own Partition roles; the Workload cannot add one -----------------


def test_the_schema_closes_cases_to_the_roles_the_track_defines():
    from hypotrail.agentic import partitions, declaration
    from importlib import resources

    schema = json.loads(resources.files("hypotrail.agentic").joinpath(declaration.SCHEMA_NAME).read_text(encoding="utf-8"))
    assert set(schema["properties"]["cases"]["properties"]) == set(partitions.ROLES) == {"dev", "public_check"}
    assert schema["properties"]["cases"]["additionalProperties"] is False


@pytest.mark.parametrize("role", ["train", "test", "holdout", "Dev", ""])
def test_a_workload_cannot_name_a_partition_the_track_does_not_define(tmp_path, role):
    error = refusal(workload_with(tmp_path, lambda d: d["cases"].__setitem__(role, "cases/chinook-dev.jsonl")))
    assert (error.code, error.details["key"], error.details["path"]) == ("DECLARATION_KEY_UNKNOWN", role, "cases")


def test_a_workload_may_declare_dev_alone_or_both_roles(tmp_path):
    load_workload(workload_with(tmp_path, lambda d: d["cases"].pop("public_check")))
    assert set(load_workload(CHINOOK).declaration["cases"]) == {"dev", "public_check"}


def test_a_partition_file_must_be_a_string_and_cases_must_not_be_empty(tmp_path):
    assert refusal(workload_with(tmp_path, lambda d: d["cases"].__setitem__("dev", 3))).code == "DECLARATION_WRONG_TYPE"
    assert refusal(workload_with(tmp_path / "b", lambda d: d.__setitem__("cases", {}))).code == "DECLARATION_VALUE_NOT_ALLOWED"


# --- R1-S2: the answer schema is declared, and the Track names no Configuration -------------------------


def test_the_declaration_names_the_answer_schema_and_the_workload_reads_it_from_there():
    workload = load_workload(CHINOOK)
    assert workload.declaration["answer_schema"] == "schemas/table-answer.schema.json"
    assert workload.answer_schema_path == CHINOOK / "schemas" / "table-answer.schema.json"
    assert workload.answer_schema() == json.loads(workload.answer_schema_path.read_text(encoding="utf-8"))


def test_the_answer_schema_is_read_from_the_declared_path_not_a_fixed_one(tmp_path):
    target = tmp_path / "chinook"
    shutil.copytree(CHINOOK, target, ignore=shutil.ignore_patterns("data"))
    (target / "schemas" / "table-answer.schema.json").rename(target / "schemas" / "renamed.json")
    declaration = json.loads((target / "workload.json").read_text())
    declaration["answer_schema"] = "schemas/renamed.json"
    (target / "workload.json").write_text(json.dumps(declaration))
    assert load_workload(target).answer_schema()["type"] == "object"


def test_a_missing_or_mistyped_answer_schema_key_is_refused_with_a_code(tmp_path):
    error = refusal(workload_with(tmp_path, lambda d: d.pop("answer_schema")))
    assert (error.code, error.details["key"]) == ("DECLARATION_INCOMPLETE", "answer_schema")
    assert refusal(workload_with(tmp_path / "b", lambda d: d.__setitem__("answer_schema", 3))).code == "DECLARATION_WRONG_TYPE"


def test_an_answer_schema_file_that_is_absent_or_not_json_is_refused_with_a_code(tmp_path):
    def point_to(name):
        return lambda d: d.__setitem__("answer_schema", name)

    absent = load_workload(workload_with(tmp_path / "a", point_to("schemas/nowhere.json")))
    with pytest.raises(InvalidInputError) as caught:
        absent.answer_schema()
    assert caught.value.code == "FILE_NOT_FOUND"
    broken = load_workload(workload_with(tmp_path / "b", point_to("workload.json")))
    (broken.directory / "workload.json").write_text("{not json")
    with pytest.raises(InvalidInputError) as caught:
        broken.answer_schema()
    assert caught.value.code == "FILE_NOT_JSON"


def test_no_configuration_name_is_a_default_of_the_track():
    import inspect

    from hypotrail.agentic import fixture, live

    for function in (live.run_live, fixture.run_fixture):
        parameter = inspect.signature(function).parameters["configuration"]
        assert parameter.default is inspect.Parameter.empty, function.__name__
    assert not hasattr(fixture, "CONFIGURATION")
