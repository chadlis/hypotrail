"""Ticket #44: generic Track code builds the Inspect task from the Workload declaration.

Seams: `load_workload(...).system_text` (the prompt texts), `runner.build_task` and
`runner.run_episodes` (the task and what its log records), `sql_tool.schema_description` (the
`describe_schema` result). Scripted models only: no network.
"""

import json
import re
import shutil
import sqlite3
from pathlib import Path

import pytest
from inspect_ai.log import read_eval_log

from _agent_helpers import CHINOOK, DATABASE, REFERENCES, ScriptedModel, read_jsonl

from hypotrail.agentic import cases as case_module
from hypotrail.agentic import limits as limits_module
from hypotrail.agentic import projection, runner, sql_tool
from hypotrail.agentic.declaration import load_workload

WORKLOAD = load_workload(CHINOOK)
CASE_IDS = ["D03", "D05"]
ELEVEN = [
    "Album", "Artist", "Customer", "Employee", "Genre", "Invoice",
    "InvoiceLine", "MediaType", "Playlist", "PlaylistTrack", "Track",
]


def cases(ids=CASE_IDS):
    return WORKLOAD.cases("dev", ids)


def run(configuration, tmp_path, *, workload=WORKLOAD, run_cases=None, script=None, repeats=1):
    run_cases = run_cases or cases()
    script = script or ScriptedModel(run_cases)
    location = runner.run_episodes(
        run_cases,
        workload=workload,
        configuration=configuration,
        model=runner.mock_model(script),
        repeats=repeats,
        log_dir=tmp_path / configuration,
    )
    return script, location


# --- the prompt texts ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "element",
    [
        "describe_schema",
        "query_readonly",
        "do not guess",
        "table-answer/1",
        "single JSON object",
        "no Markdown fence",
        "no extra prose",
        '"status"',
        '"reason_code"',
        '"columns"',
        '"rows"',
        '"unit"',
        '"evidence"',
        "answered",
        "needs_clarification",
        "not_answerable",
        "criterion_undefined",
        "field_not_available",
        "clarification",
        "not available",
    ],
)
def test_plain_states_the_instruction_and_the_common_format_rules(element):
    assert element in WORKLOAD.system_text("plain")


def test_verify_is_plain_followed_by_the_declared_instruction_and_nothing_else():
    declared = WORKLOAD.declaration["configurations"]["verify"]
    assert declared["extends"] == "plain"
    assert WORKLOAD.system_text("verify") == WORKLOAD.system_text("plain") + declared["added_instruction"]
    assert WORKLOAD.system_text("verify") != WORKLOAD.system_text("plain")


def test_the_added_instruction_asks_for_scope_joins_units_and_result_before_concluding():
    instruction = WORKLOAD.declaration["configurations"]["verify"]["added_instruction"].lower()
    for word in ("scope", "joins", "units", "result", "before you conclude"):
        assert word in instruction


def test_neither_prompt_text_contains_a_reference_value_of_any_case():
    references = read_jsonl(REFERENCES)
    values = {str(cell) for r in references for row in r["rows"] for cell in row if cell is not None}
    values |= {r["oracle_sql"] for r in references if r["oracle_sql"]}
    assert {"3503", "Iron Maiden", "283910.04"} <= values  # the scan has something to find
    for configuration in ("plain", "verify"):
        text = WORKLOAD.system_text(configuration)
        for value in values:
            assert not re.search(rf"(?<![\w.]){re.escape(value)}(?![\w])", text), (configuration, value)


def test_an_undeclared_configuration_is_refused_before_a_task_is_built():
    with pytest.raises(Exception) as caught:
        runner.build_task(WORKLOAD, "terse")
    assert caught.value.code == "CONFIGURATION_NOT_DECLARED"


# --- what the model is sent -----------------------------------------------------------------


@pytest.mark.parametrize("configuration", ["plain", "verify"])
def test_the_model_input_is_the_system_text_and_the_rendering_of_three_case_fields(configuration, tmp_path):
    script, location = run(configuration, tmp_path, repeats=2)
    by_id = {c["case_id"]: c for c in cases()}
    episodes = projection.project_log(location, expected=[(c, r) for c in CASE_IDS for r in (0, 1)])
    for episode in episodes:
        case = by_id[episode["case_id"]]
        assert episode["input"] == [
            {"role": "system", "content": WORKLOAD.system_text(configuration)},
            {"role": "user", "content": case_module.user_message(case)},
        ]
    first_calls = [c for c in script.calls if c[-1][0] == "user"]
    assert len(first_calls) == 4
    assert all([role for role, _ in call] == ["system", "user"] for call in first_calls)


def test_the_user_message_renders_the_question_the_columns_and_the_unit():
    case = cases(["D05"])[0]
    assert case_module.user_message(case) == (
        f"Question: {case['question']}\n"
        f"Requested columns: artist_name, album_count\n"
        f"Unit: {case['unit']}"
    )


def test_no_other_case_field_can_reach_the_model():
    case = cases(["D03"])[0]
    clean = case_module.user_message(case)
    poison = {k: f"POISON-{k}" for k in case if k not in ("question", "answer_columns", "unit")}
    poison["oracle_sql"] = "POISON-oracle_sql"
    poison["numeric_absolute_tolerance"] = "POISON-tolerance"
    assert poison.keys() >= {"case_id", "split", "family", "dataset_id", "ordering", "answer_format"}
    assert case_module.user_message({**case, **poison}) == clean
    assert "POISON" not in clean


def test_the_logged_model_input_holds_no_routing_field_reference_sql_status_or_tolerance(tmp_path):
    _, location = run("verify", tmp_path)
    references = {r["case_id"]: r for r in read_jsonl(REFERENCES)}
    by_id = {c["case_id"]: c for c in cases()}
    for episode in projection.project_log(location, expected=[(c, 0) for c in CASE_IDS]):
        text = "\n".join(m["content"] for m in episode["input"])
        reference, case = references[episode["case_id"]], by_id[episode["case_id"]]
        for forbidden in (reference["oracle_sql"] or "-no-oracle-", case["case_id"], case["split"], case["family"],
                          "numeric_absolute_tolerance", reference["reference_version"]):
            assert forbidden not in text, forbidden
        # the statuses are the common format rules of the system text; a Case's own status is not in its message
        assert reference["status"] not in episode["input"][1]["content"]
        for row in reference["rows"]:
            assert json.dumps(row) not in text


def test_a_case_with_no_unit_gets_the_same_system_text_and_the_same_rendering(tmp_path):
    base, other = cases(["D03", "D05"])
    no_unit = {**other, "unit": None}
    _, location = run("plain", tmp_path, run_cases=[base, no_unit])
    inputs = {e["case_id"]: e["input"] for e in projection.project_log(location, expected=[("D03", 0), ("D05", 0)])}
    assert inputs["D03"][0] == inputs["D05"][0] == {"role": "system", "content": WORKLOAD.system_text("plain")}
    assert inputs["D05"][1]["content"].endswith("Unit: none")
    assert inputs["D05"][1]["content"] == case_module.user_message(no_unit)


# --- same tools, same limits, same settings ----------------------------------------------------


def logged_setup(location):
    log = read_eval_log(location)
    model_events = [e for s in log.samples for e in s.events if e.event == "model"]
    return {
        "tools": [[t.model_dump() for t in e.tools] for e in model_events],
        "limits": limits_module.read_back(location),
        "generation": log.eval.model_generate_config.model_dump(exclude_none=True),
        "plan_config": log.plan.config.model_dump(exclude_none=True),
        "eval_config": log.eval.config.model_dump(exclude_none=True),
    }


def test_plain_and_verify_runs_record_identical_tools_limits_and_generation_settings(tmp_path):
    plain = logged_setup(run("plain", tmp_path)[1])
    verify = logged_setup(run("verify", tmp_path)[1])
    assert plain["tools"] and plain == verify


def test_the_task_offers_exactly_describe_schema_and_query_readonly(tmp_path):
    _, location = run("plain", tmp_path)
    names = {t["name"] for turn in logged_setup(location)["tools"] for t in turn}
    assert names == {"describe_schema", "query_readonly"}


def test_both_tools_work_on_the_database_path_the_declaration_fixes(tmp_path):
    other = tmp_path / "other"
    shutil.copytree(CHINOOK, other, ignore=shutil.ignore_patterns("data"))
    (other / "data").mkdir()
    with sqlite3.connect(other / "data" / "Chinook_Sqlite.sqlite") as connection:
        connection.execute("CREATE TABLE Marker (Id INTEGER PRIMARY KEY, Note TEXT)")
        connection.execute("INSERT INTO Marker VALUES (1, 'only in the declared file')")
    workload = load_workload(other)
    assert workload.database_path == other / "data" / "Chinook_Sqlite.sqlite"

    from inspect_ai.model import ModelOutput

    class UsesBoth(ScriptedModel):
        def __call__(self, input, tools, tool_choice, config):
            tool_turns = sum(m.role == "tool" for m in input)
            if tool_turns == 0:
                return ModelOutput.for_tool_call("mockllm/model", "describe_schema", {})
            if tool_turns == 1:
                return ModelOutput.for_tool_call("mockllm/model", "query_readonly", {"sql": "SELECT Note FROM Marker"})
            return ModelOutput.from_content("mockllm/model", "done")

    one = cases(["D03"])
    _, location = run("plain", tmp_path, workload=workload, run_cases=one, script=UsesBoth(one))
    events = [e for s in read_eval_log(location).samples for e in s.events if e.event == "tool"]
    assert [e.function for e in events] == ["describe_schema", "query_readonly"]
    assert [t["name"] for t in json.loads(events[0].result)["tables"]] == ["Marker"]
    assert json.loads(events[1].result)["rows"] == [["only in the declared file"]]


# --- the exact prompt text is kept ----------------------------------------------------------------


@pytest.mark.parametrize("configuration", ["plain", "verify"])
def test_a_run_keeps_the_exact_prompt_text_of_its_configuration_in_its_log(configuration, tmp_path):
    _, location = run(configuration, tmp_path)
    metadata = read_eval_log(location, header_only=True).eval.metadata
    assert metadata["configuration"] == configuration
    assert metadata["system_text"] == WORKLOAD.system_text(configuration)


# --- the References are not an input of the task builder --------------------------------------------


def test_a_task_built_from_the_declaration_works_when_the_references_are_absent(tmp_path):
    copy = tmp_path / "chinook"
    shutil.copytree(CHINOOK, copy, ignore=shutil.ignore_patterns("references", "fixtures"))
    assert not (copy / "references").exists()
    workload = load_workload(copy)
    _, location = run("verify", tmp_path, workload=workload, run_cases=workload.cases("dev", CASE_IDS))
    episodes = projection.project_log(location, expected=[(c, 0) for c in CASE_IDS])
    assert [e["status"] for e in episodes] == ["produced", "produced"]


# --- describe_schema ---------------------------------------------------------------------------


def sqlite_own_reading(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        names = [r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {
            name: {
                "columns": [(c[1], c[2]) for c in connection.execute(f'PRAGMA table_info("{name}")')],
                "foreign_keys": sorted(
                    (f[3], f[2], f[4]) for f in connection.execute(f'PRAGMA foreign_key_list("{name}")')),
            }
            for name in names
        }


def test_describe_schema_returns_the_eleven_tables_with_columns_types_and_foreign_keys():
    result = json.loads(json.dumps(sql_tool.schema_description(DATABASE)))
    expected = sqlite_own_reading(DATABASE)
    assert sorted(expected) == ELEVEN
    assert [t["name"] for t in result["tables"]] == ELEVEN
    for table in result["tables"]:
        reading = expected[table["name"]]
        assert [(c["name"], c["type"]) for c in table["columns"]] == reading["columns"]
        assert sorted((f["from"], f["table"], f["to"]) for f in table["foreign_keys"]) == reading["foreign_keys"]
    by_name = {t["name"]: t for t in result["tables"]}
    assert ("TrackId", "Track", "TrackId") in {(f["from"], f["table"], f["to"]) for f in by_name["InvoiceLine"]["foreign_keys"]}
    assert len(by_name["Track"]["columns"]) == 9


def test_describe_schema_holds_no_reference_value_and_no_oracle_sql():
    text = json.dumps(sql_tool.schema_description(DATABASE))
    for reference in read_jsonl(REFERENCES):
        assert not reference["oracle_sql"] or reference["oracle_sql"] not in text
        assert reference["reference_version"] not in text
        for row in reference["rows"]:
            assert json.dumps(row) not in text
    assert "oracle" not in text.lower() and "reference" not in text.lower()


def test_the_model_can_call_describe_schema_through_the_task(tmp_path):
    from inspect_ai.model import ModelOutput

    class Describer(ScriptedModel):
        def __call__(self, input, tools, tool_choice, config):
            if input[-1].role != "tool":
                return ModelOutput.for_tool_call("mockllm/model", "describe_schema", {})
            return ModelOutput.from_content("mockllm/model", "done")

    _, location = run("plain", tmp_path, script=Describer(cases()), run_cases=cases(["D03"]))
    log = read_eval_log(location)
    tool_events = [e for s in log.samples for e in s.events if e.event == "tool"]
    assert [e.function for e in tool_events] == ["describe_schema"]
    assert [t["name"] for t in json.loads(tool_events[0].result)["tables"]] == ELEVEN


def test_plain_and_verify_runs_both_carry_the_4000_output_token_budget(tmp_path):
    # T2 (AG-12: same budgets): both Configurations' runs record Inspect's native output-metered limit
    for configuration in ("plain", "verify"):
        _, location = run(configuration, tmp_path)
        config = read_eval_log(location, header_only=True).eval.config
        assert (config.token_limit, config.token_limit_type) == (4000, "output"), configuration
        assert limits_module.read_back(location)["output_token_budget"] == 4000
