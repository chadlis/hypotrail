"""Shared by the `run agent` tests (#74): a Chinook Study, the command, and the one seam through which a test patches the model.

The patch is a test's own: `hypotrail.agentic.live.prepared_model` is replaced by a function that returns Inspect's mock
model. No flag of the command reaches it, and nothing here calls a provider.
"""

import json
from pathlib import Path

from _agent_helpers import REFERENCES, WORKLOAD, ScriptedModel, read_jsonl
from _chinook_helpers import init_chinook
from _study_helpers import run_cli, run_json

from hypotrail.agentic import live as agentic_live
from hypotrail.agentic import runner
from hypotrail.core import live as core_live

FAKE_KEY = "sk-ant-FAKE-run-agent-0123456789abcdef"
MODEL = "anthropic/claude-test-1"
DEV = [case["case_id"] for case in WORKLOAD.cases("dev")]
PUBLIC = [case["case_id"] for case in WORKLOAD.cases("public_check")]
ALL_CASES = WORKLOAD.cases("dev") + WORKLOAD.cases("public_check")
TWO = ["D03", "D05"]


class AnsweringModel(ScriptedModel):
    """The spike tests' scripted model, which also answers a Case whose Reference has no SQL (not answerable, needs clarification) directly."""

    def __call__(self, input, tools, tool_choice, config):
        from inspect_ai.model import ModelOutput

        question = self._question(input)
        if self.sql_by_question[question] is not None:
            return super().__call__(input, tools, tool_choice, config)
        self.calls.append([(m.role, m.text) for m in input])
        reference = next(r for r in read_jsonl(REFERENCES) if r["case_id"] == self.case_by_question[question])
        answer = {"status": reference["status"], "reason_code": reference["reason_code"], "columns": [], "rows": [], "unit": None, "evidence": []}
        return ModelOutput.from_content("mockllm/model", json.dumps(answer))


def scripted(**options):
    """The scripted model of the spike tests, over every Case of the Workload."""
    return AnsweringModel(ALL_CASES, **options)


def patch_model(monkeypatch, script=None, *, key=FAKE_KEY):
    """The key in the environment and the model patched through Inspect's mock model; returns the script."""
    script = script if script is not None else scripted()
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    if key is None:
        monkeypatch.delenv(core_live.KEY_VARIABLE, raising=False)
    else:
        monkeypatch.setenv(core_live.KEY_VARIABLE, key)
    monkeypatch.setattr(agentic_live, "prepared_model", lambda model_id, api_key, *a, **k: runner.mock_model(script))
    return script


def refuse_provider(monkeypatch):
    """Anything that would reach a model or run an Episode raises."""

    def boom(*args, **kwargs):
        raise AssertionError("the provider or Inspect was used")

    monkeypatch.setattr(agentic_live, "prepared_model", boom)
    monkeypatch.setattr(agentic_live, "live_model", boom)
    monkeypatch.setattr(runner, "run_episodes", boom)


def study_of(tmp_path, *, examples=None, name="study"):
    study, _ = init_chinook(tmp_path, name=name, examples=examples)
    return study


def agent(study, *args):
    return run_json("run", "agent", "--study", study, *args)


def live_args(config, request_id, *, cases=TWO, repeats=1, partition="dev", model=MODEL):
    args = ["--mode", "llm_live", "--config", config, "--request-id", request_id, "--partition", partition, "--repeats", str(repeats), "--model", model]
    for case in cases or ():
        args += ["--cases", case]
    return args


def live(study, config, request_id, *more, **options):
    return agent(study, *live_args(config, request_id, **options), *more)


def fixture(study, config, request_id, *more):
    return agent(study, "--mode", "scripted_fixture", "--config", config, "--request-id", request_id, *more)


def ok(result):
    code, payload, err = result
    assert code == 0, (payload, err)
    return payload["attempt"]


def folder_of(study, attempt) -> Path:
    return Path(study) / "attempts" / attempt["attempt_id"]


def read(study, attempt, name):
    return json.loads((folder_of(study, attempt) / name).read_text(encoding="utf-8"))


def observations_of(study, attempt) -> list:
    text = (folder_of(study, attempt) / "observations.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def observation_set_id_of(study, attempt) -> str:
    return read(study, attempt, "observation_set.json")["observation_set_id"]


def tree(folder) -> dict:
    """{relative path: bytes} of every file under `folder`: a snapshot to show that nothing was written."""
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def tree_without_lock(folder) -> dict:
    return {k: v for k, v in tree(folder).items() if k != "writer.lock"}


def error_of(result):
    code, payload, err = result
    assert payload["ok"] is False, payload
    return code, payload["error"]


def answering_with(text):
    """A scripted model whose final answer holds `text`: a value planted in the execution's output."""
    from inspect_ai.model import ModelOutput

    inner = scripted()

    def script(input, tools, tool_choice, config):
        output = inner(input, tools, tool_choice, config)
        if input[-1].role == "tool":
            return ModelOutput.from_content("mockllm/model", json.dumps({"note": text}))
        return output

    return script
