"""Shared helpers for the agentic spike tests: a scripted model for Inspect's mock provider."""

import json
from pathlib import Path

from inspect_ai.model import ModelOutput

ROOT = Path(__file__).resolve().parent.parent
CHINOOK = ROOT / "examples" / "chinook"
DATABASE = CHINOOK / "data" / "Chinook_Sqlite.sqlite"
CASES = CHINOOK / "cases" / "chinook-dev.jsonl"
REFERENCES = CHINOOK / "references" / "chinook-references.jsonl"
MODEL = "mockllm/model"


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


def oracle_sql(case_id):
    return next(r["oracle_sql"] for r in read_jsonl(REFERENCES) if r["case_id"] == case_id)


class ScriptedModel:
    """Callable for `mockllm` `custom_outputs`.

    Every Episode follows model -> tool call -> tool result -> model -> final
    answer. The SQL is the reference SQL of the Case (read by the test, never by
    the evaluated side), and the final answer repeats the rows the tool
    returned and cites the tool's own `tool_call_id`.

    `calls` keeps the full input of every generate call, so a test can inspect
    exactly what the model was sent.
    """

    def __init__(
        self, cases, *, error_on=None, always_call_tool=False, error_message="scripted model failure"
    ):
        self.sql_by_question = {c["question"]: oracle_sql(c["case_id"]) for c in cases}
        self.unit_by_question = {c["question"]: c["unit"] for c in cases}
        self.case_by_question = {c["question"]: c["case_id"] for c in cases}
        self.error_on = error_on  # (case_id, nth first-generate of that case)
        self.error_message = error_message
        self.always_call_tool = always_call_tool
        self.calls = []
        self._first_generates = {}

    def _question(self, messages):
        user = next(m for m in messages if m.role == "user")
        return next(q for q in self.sql_by_question if q in user.text)

    def __call__(self, input, tools, tool_choice, config):
        self.calls.append([(m.role, m.text) for m in input])
        question = self._question(input)
        last = input[-1]
        if last.role != "tool" or self.always_call_tool:
            if last.role != "tool":
                case_id = self.case_by_question[question]
                n = self._first_generates[case_id] = self._first_generates.get(case_id, 0) + 1
                if self.error_on == (case_id, n):
                    raise RuntimeError(self.error_message)
            return ModelOutput.for_tool_call(
                MODEL, "query_readonly", {"sql": self.sql_by_question[question]}
            )
        result = json.loads(last.text)
        answer = {
            "status": "answered",
            "reason_code": None,
            "columns": result["columns"],
            "rows": result["rows"],
            "unit": self.unit_by_question[question],
            "evidence": [result["tool_call_id"]],
        }
        return ModelOutput.from_content(MODEL, json.dumps(answer))
