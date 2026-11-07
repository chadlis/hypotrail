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
    shutil.copytree(CHINOOK / "cases", target / "cases")  # a Workload reads its Cases files when it is built
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


# --- R2-S1, R2-P3, R2-P5: requiredness belongs to the entry point that reads a key; Partitions are disjoint --


def chinook_copy(tmp_path, edit=lambda d: None, *, data=False):
    target = tmp_path / "chinook"
    shutil.copytree(CHINOOK, target, ignore=None if data else shutil.ignore_patterns("data"))
    declaration = json.loads((target / "workload.json").read_text())
    edit(declaration)
    (target / "workload.json").write_text(json.dumps(declaration))
    return target


def refused_by(call):
    with pytest.raises(InvalidInputError) as caught:
        call()
    return caught.value


def test_answer_schema_is_not_required_by_the_schema_but_its_reader_refuses_its_absence(tmp_path):
    workload = load_workload(chinook_copy(tmp_path, lambda d: d.pop("answer_schema")))
    assert refused_by(workload.answer_schema).code == "ANSWER_SCHEMA_NOT_DECLARED"
    assert refused_by(lambda: workload.answer_schema_path).code == "ANSWER_SCHEMA_NOT_DECLARED"
    assert workload.cases("dev") and workload.system_text("plain")  # what the live path reads still works


def test_a_present_answer_schema_key_is_still_checked(tmp_path):
    assert refusal(workload_with(tmp_path, lambda d: d.__setitem__("answer_schema", 3))).code == "DECLARATION_WRONG_TYPE"
    assert refusal(workload_with(tmp_path / "b", lambda d: d.__setitem__("answer_schema", ""))).code == "DECLARATION_VALUE_NOT_ALLOWED"


def test_the_fixture_refuses_a_missing_answer_schema_before_any_effect(tmp_path):
    from hypotrail.agentic import fixture

    out = tmp_path / "out"
    error = refused_by(
        lambda: fixture.run_fixture(workload_dir=chinook_copy(tmp_path, lambda d: d.pop("answer_schema")), out_dir=out, configuration="plain")
    )
    assert error.code == "ANSWER_SCHEMA_NOT_DECLARED"
    assert not out.exists()


def test_the_live_command_accepts_a_declaration_without_an_answer_schema(tmp_path, monkeypatch):
    from hypotrail import cli
    from hypotrail.agentic import live as agentic_live
    from hypotrail.core import data

    examples = tmp_path / "examples"
    examples.mkdir()
    chinook_copy(examples, lambda d: d.pop("answer_schema"), data=True)
    monkeypatch.setattr(data, "default_examples_dir", lambda: examples)
    seen = []
    monkeypatch.setattr(agentic_live, "run_live", lambda **kw: seen.append(kw) or {"model": "m", "tool_loop_observed": False, "episodes": []})
    for name in ("HYPOTRAIL_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HYPOTRAIL_ANTHROPIC_API_KEY", "sk-ant-FAKE-live-key-0123456789abcdef")
    code = cli.main(["spike", "live", "--config", "plain", "--model", "anthropic/claude-test-1", "--out", str(tmp_path / "o"), "--json"])
    assert code == 0 and len(seen) == 1


def no_dev(d):
    d["cases"].pop("dev")


def test_a_declaration_with_public_check_alone_loads_but_dev_readers_refuse_it(tmp_path):
    from hypotrail.agentic import runner

    workload = load_workload(chinook_copy(tmp_path, no_dev))
    assert set(workload.declaration["cases"]) == {"public_check"}
    assert refused_by(lambda: workload.cases_path("dev")).code == "PARTITION_NOT_DECLARED"
    assert refused_by(lambda: workload.cases("dev")).code == "PARTITION_NOT_DECLARED"
    assert refused_by(lambda: runner.build_task(workload, "plain")).code == "PARTITION_NOT_DECLARED"
    assert refused_by(lambda: runner.build_task(workload, "plain", partition="dev")).code == "PARTITION_NOT_DECLARED"


def test_a_declaration_with_dev_alone_builds_the_dev_task(tmp_path):
    from hypotrail.agentic import runner

    workload = load_workload(chinook_copy(tmp_path, lambda d: d["cases"].pop("public_check")))
    assert len(runner.build_task(workload, "plain").dataset) == len(workload.cases("dev"))


def test_the_live_command_refuses_a_workload_without_dev_before_the_key_and_any_run(tmp_path, monkeypatch):
    from hypotrail import cli
    from hypotrail.agentic import live as agentic_live
    from hypotrail.core import data

    examples = tmp_path / "examples"
    examples.mkdir()
    chinook_copy(examples, no_dev, data=True)
    monkeypatch.setattr(data, "default_examples_dir", lambda: examples)
    for name in ("HYPOTRAIL_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    started = []
    monkeypatch.setattr(agentic_live, "run_live", lambda **kw: started.append(kw))
    out = tmp_path / "o"
    code = cli.main(["spike", "live", "--config", "plain", "--model", "anthropic/claude-test-1", "--out", str(out), "--json"])
    assert code == 2 and started == [] and not out.exists()


def overlapping(tmp_path, extra_id):
    target = chinook_copy(tmp_path)
    path = target / "cases" / "chinook-public-check.jsonl"
    first = json.loads(path.read_text().splitlines()[0])
    path.write_text(path.read_text() + json.dumps({**first, "case_id": extra_id}) + "\n")
    return target


def test_a_case_id_listed_in_two_partitions_is_refused_when_the_declaration_is_loaded(tmp_path):
    error = refused_by(lambda: load_workload(overlapping(tmp_path, "D03")))
    assert (error.code, error.details["case_ids"]) == ("PARTITIONS_NOT_DISJOINT", ["D03"])


def test_two_partitions_pointing_at_one_file_are_not_disjoint(tmp_path):
    target = chinook_copy(tmp_path, lambda d: d["cases"].__setitem__("public_check", d["cases"]["dev"]))
    assert refused_by(lambda: load_workload(target)).code == "PARTITIONS_NOT_DISJOINT"


def test_distinct_case_ids_and_single_partitions_still_load(tmp_path):
    load_workload(overlapping(tmp_path / "a", "d03"))  # IDs are compared exactly
    load_workload(overlapping(tmp_path / "b", "E99"))
    load_workload(chinook_copy(tmp_path / "c", lambda d: d["cases"].pop("public_check")))
    load_workload(CHINOOK)


def test_a_declared_cases_file_that_is_absent_is_refused_when_the_declaration_is_loaded(tmp_path):
    target = chinook_copy(tmp_path)
    (target / "cases" / "chinook-public-check.jsonl").unlink()
    assert refused_by(lambda: load_workload(target)).code == "FILE_NOT_FOUND"


def test_a_cases_line_that_cannot_be_parsed_is_refused_when_the_declaration_is_loaded(tmp_path):
    target = chinook_copy(tmp_path)
    path = target / "cases" / "chinook-public-check.jsonl"
    path.write_text(path.read_text() + "{not json\n")
    assert refused_by(lambda: load_workload(target)).code == "FILE_NOT_JSON"
    path.write_text("[1, 2]\n")  # JSON, but not a Case
    assert refused_by(lambda: load_workload(target)).code == "FILE_NOT_JSON"


def with_repeated_first_case(tmp_path, partition):
    """A copy of the Chinook Workload whose `partition` file ends with a second copy of its first Case."""
    target = chinook_copy(tmp_path)
    path = target / "cases" / ("chinook-dev.jsonl" if partition == "dev" else "chinook-public-check.jsonl")
    first = path.read_text().splitlines()[0]
    path.write_text(path.read_text() + first + "\n")
    return target, path, json.loads(first)["case_id"]


@pytest.mark.parametrize("partition", ["dev", "public_check"])
def test_a_case_id_repeated_inside_one_cases_file_is_refused_when_the_declaration_is_loaded(tmp_path, partition):
    target, _, case_id = with_repeated_first_case(tmp_path, partition)
    error = refused_by(lambda: load_workload(target))
    assert (error.code, error.stage, error.details["case_id"]) == ("CASE_ID_NOT_UNIQUE", "declaration", case_id)


def test_a_case_id_in_both_partitions_is_still_not_disjoint_not_a_repeat(tmp_path):
    # once in each file: a repeat in no single file
    assert refused_by(lambda: load_workload(overlapping(tmp_path, "D03"))).code == "PARTITIONS_NOT_DISJOINT"


def test_an_unparsable_line_is_still_refused_before_a_repeat(tmp_path):
    target, path, _ = with_repeated_first_case(tmp_path, "dev")
    path.write_text(path.read_text() + "{not json\n")
    assert refused_by(lambda: load_workload(target)).code == "FILE_NOT_JSON"


def test_a_malformed_line_hides_no_overlap(tmp_path):
    target = overlapping(tmp_path, "D03")
    path = target / "cases" / "chinook-public-check.jsonl"
    path.write_text(path.read_text() + "{not json\n")
    assert refused_by(lambda: load_workload(target)).code == "FILE_NOT_JSON"


def test_a_workload_built_directly_is_checked_like_a_loaded_one(tmp_path):
    from hypotrail.agentic.declaration import Workload

    overlap = overlapping(tmp_path / "a", "D03")
    declaration = json.loads((overlap / "workload.json").read_text())
    assert refused_by(lambda: Workload(overlap, declaration)).code == "PARTITIONS_NOT_DISJOINT"

    missing = chinook_copy(tmp_path / "b")
    (missing / "cases" / "chinook-dev.jsonl").unlink()
    assert refused_by(lambda: Workload(missing, json.loads((missing / "workload.json").read_text()))).code == "FILE_NOT_FOUND"


def test_partition_of_answers_for_every_listed_case_of_the_real_declaration():
    workload = load_workload(CHINOOK)
    for partition in ("dev", "public_check"):
        for case in workload.cases(partition):
            assert workload.partition_of(case["case_id"]) == partition
    assert workload.partition_of("NOT-A-CASE") is None


def test_dev_only_workload_reads_only_its_declared_file(tmp_path):
    target = chinook_copy(tmp_path, lambda d: d["cases"].pop("public_check"))
    (target / "cases" / "chinook-public-check.jsonl").unlink()
    workload = load_workload(target)
    assert workload.partition_of(workload.cases("dev")[0]["case_id"]) == "dev"
