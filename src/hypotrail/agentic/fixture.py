"""The `scripted_fixture` Mode: technical scenarios run by Inspect's mock model.

The scenarios are data (`fixtures/scenarios.json`, named by the Workload declaration). A script is
a list of model turns, each one of:

- `{"tool_call": {"function": ..., "arguments": {...}}}`: the model calls a real local tool; with
  `"repeat": true` as the last turn, it makes the same call on every later turn;
- `{"answer_from_last_result": {"unit": ..., ...}}`: a final answer built from the last tool result
  (its columns and rows, citing its own `tool_call_id`); `status`, `reason_code`, `columns`, `rows`
  and `evidence` may be given to override;
- `{"raw_answer": "text"}`: a final answer kept verbatim.

A scenario whose `script` is null is expected but never run, so it stays absent from the log.

The tools are the real ones, and the task, the projection and the Scorer are the code a live run
uses; only the model differs. Nothing here reads the network, a provider key or a Reference when it
answers. The scenario Cases are technical: none of them is one of the Workload's business Cases.
Everything written carries the Mode and the banner.
"""

import json
import platform
from importlib import metadata
from pathlib import Path

from inspect_ai.log import read_eval_log
from inspect_ai.model import ModelOutput

from hypotrail.agentic import counts, limits as limits_module, projection, rescore, runner
from hypotrail.agentic.declaration import SCENARIOS, check_document, load_workload, read_json
from hypotrail.core.data import sha256_file
from hypotrail.core.errors import IntegrityError, InvalidInputError

MODE = "scripted_fixture"
BANNER = "simulation, no LLM evaluated"
MODEL = "mockllm/model"


class ScenarioScript:
    """The callable for the mock model: plays the script of the scenario whose question it is sent."""

    def __init__(self, scenarios: list[dict]):
        self.script_by_question = {
            s["case"]["question"]: s["script"] for s in scenarios if s["script"] is not None
        }

    def _script(self, messages) -> list[dict]:
        user = next(m for m in messages if m.role == "user")
        return next(script for question, script in self.script_by_question.items() if question in user.text)

    @staticmethod
    def _turn(script: list[dict], index: int) -> dict:
        if index < len(script):
            return script[index]
        if script[-1].get("repeat"):
            return script[-1]
        raise IndexError("the scenario script ran out of turns")

    def __call__(self, input, tools, tool_choice, config):
        script = self._script(input)
        turn = self._turn(script, sum(m.role == "assistant" for m in input))
        if "tool_call" in turn:
            call = turn["tool_call"]
            return ModelOutput.for_tool_call(MODEL, call["function"], call["arguments"])
        if "raw_answer" in turn:
            return ModelOutput.from_content(MODEL, turn["raw_answer"])
        spec = turn["answer_from_last_result"]
        result = json.loads(next(m for m in reversed(input) if m.role == "tool").text)
        answer = {
            "status": spec.get("status", "answered"),
            "reason_code": spec.get("reason_code"),
            "columns": spec.get("columns", result["columns"]),
            "rows": spec.get("rows", result["rows"]),
            "unit": spec["unit"],
            "evidence": spec.get("evidence", [result["tool_call_id"]]),
        }
        return ModelOutput.from_content(MODEL, json.dumps(answer))


def load_scenarios(workload) -> list[dict]:
    path = workload.scenarios_path
    if path is None:
        raise InvalidInputError(
            "SCENARIOS_NOT_DECLARED",
            f"the Workload {workload.workload_id!r} declares no scenarios",
            stage="fixture",
            details={"path": "scenarios"},
        )
    document = read_json(path, stage="fixture", noun="scenarios file", key="scenarios")
    check_document(document, SCENARIOS)
    return document["scenarios"]


def _write(out_dir: Path, name: str, body: dict) -> None:
    document = {"mode": MODE, "banner": BANNER, **body}
    (out_dir / name).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def run_fixture(
    *, workload_dir: Path, out_dir: Path, configuration: str, limits: limits_module.EpisodeLimits | None = None
) -> dict:
    """Run every scenario once, under a declared Configuration, and write the projection, the verdicts and the run record."""
    workload = load_workload(workload_dir)
    workload.system_text(configuration)  # an undeclared Configuration is refused before anything is written
    schema = workload.answer_schema()  # the keys this entry point reads are refused before anything is written
    scenarios = load_scenarios(workload)
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise InvalidInputError(
            "OUTPUT_NOT_EMPTY", f"output directory is not empty: {out_dir}", stage="fixture", details={"out": str(out_dir)}
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    limits = limits or limits_module.EpisodeLimits()

    scenario_of = {s["case"]["case_id"]: s["scenario_id"] for s in scenarios}
    references = {s["case"]["case_id"]: s["reference"] for s in scenarios if "reference" in s}

    hash_before = sha256_file(workload.database_path)
    location = runner.run_episodes(
        [s["case"] for s in scenarios if s["script"] is not None],
        workload=workload,
        configuration=configuration,
        model=runner.mock_model(ScenarioScript(scenarios)),
        repeats=1,
        log_dir=out_dir / "inspect",
        limits=limits,
        metadata={"mode": MODE, "banner": BANNER},
    )
    hash_after = sha256_file(workload.database_path)

    episodes = projection.project_log(location, expected=[(s["case"]["case_id"], 0) for s in scenarios])
    verdicts = rescore.rescore_episodes(episodes, references, schema=schema, workload=workload)
    for verdict in verdicts:
        verdict["scenario_id"] = scenario_of[verdict["case_id"]]
    tally = counts.tally(verdicts, workload=workload)
    log = read_eval_log(location, header_only=True)
    effective = limits_module.read_back(location)

    record = {
        "configuration": configuration,
        "model": log.eval.model,
        "provider": log.eval.model.split("/", 1)[0],
        "engine": {"name": "inspect-ai", "version": metadata.version("inspect-ai")},
        "python": platform.python_version(),
        "inspect_log": str(Path(location).resolve().relative_to(out_dir.resolve())),
        "inspect_status": log.status,
        "scenarios": [
            {"scenario_id": v["scenario_id"], "case_id": v["case_id"], "status": v["status"], "reason": v["reason"]}
            for v in verdicts
        ],
        "business_case_outputs": 0,
        "counts": tally["criteria"],
        "tool_errors": tally["tool_errors"],
        "effective_limits": effective,
        "requested_limits": limits.as_dict(),
        "limits_not_enforceable": limits_module.NOT_ENFORCEABLE,
        "provider_calls_allowed": {
            "model_turns": effective["model_turns"],
            "provider_calls": effective["model_turns"] + 1,
            "note": f"a {effective['model_turns']}-turn limit allows {effective['model_turns'] + 1} provider calls: "
            "the generation that exceeds the limit is still made, then discarded",
        },
        "database": {
            "file": str(workload.database_path.relative_to(Path(workload_dir))),
            "sha256_before": hash_before,
            "sha256_after": hash_after,
            "unchanged": hash_before == hash_after,
        },
    }
    _write(out_dir, "projection.json", {"episodes": episodes})
    _write(out_dir, "verdicts.json", {"verdicts": verdicts})
    _write(out_dir, "run.json", record)
    if hash_before != hash_after:
        raise IntegrityError(
            "DATABASE_CHANGED",
            "the Chinook file changed during the run",
            stage="fixture",
            details={"sha256_before": hash_before, "sha256_after": hash_after},
        )
    return {"mode": MODE, "banner": BANNER, **record}
