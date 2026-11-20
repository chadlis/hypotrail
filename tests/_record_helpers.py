"""Shared by the tests of what a `run.json` says and where each field comes from (#62): logs written offline, edited through Inspect's public log API, and the two ways a record is written."""

import shutil
from pathlib import Path

from inspect_ai.log import read_eval_log, write_eval_log

from _agent_helpers import CHINOOK, WORKLOAD, ScriptedModel

from hypotrail.agentic import live as agentic_live
from hypotrail.agentic import runner

FAKE_KEY = "sk-ant-FAKE-record-key-0123456789abcdef"
LOG_MODEL = "mockllm/model"


def make_log(tmp_path, name, *, case_ids=("D03",), repeats=1, edit=None, limits=None, **overrides):
    """An out directory `tmp_path/name` holding an Inspect log run by the mock model, edited by `edit(log)` if given.

    Returns (out_dir, location). The log is edited and written back only through `read_eval_log` and
    `write_eval_log`, never by opening the file.
    """
    out = Path(tmp_path) / name
    cases = WORKLOAD.cases("dev", list(case_ids))
    location = runner.run_episodes(
        cases, workload=WORKLOAD, configuration="plain", model=runner.mock_model(ScriptedModel(cases)),
        repeats=repeats, log_dir=out / "inspect", limits=limits, **overrides,
    )
    if edit is not None:
        log = read_eval_log(location)
        edit(log)
        write_eval_log(log, location)
    return out, location


def resummary(out, location, *, model_id=LOG_MODEL, case_ids=("D03",), repeats=1, **kwargs):
    """`live.summarize` of a kept log; the caller arguments default to what the log holds."""
    return agentic_live.summarize(
        location=location, out_dir=out, model_id=model_id, api_key=FAKE_KEY, case_ids=list(case_ids), repeats=repeats, **kwargs
    )


def live_record(tmp_path, monkeypatch, location, *, model_id=LOG_MODEL, case_ids=("D03",), repeats=1, name="live-out"):
    """The record `run_live` writes right after a run whose Inspect log is `location` (a copy of it): no model, no network."""

    def run_the_copy(cases, *, log_dir, **kwargs):
        Path(log_dir).mkdir(parents=True)
        return str(shutil.copy(location, log_dir))

    monkeypatch.setattr(agentic_live, "live_model", lambda *a, **k: object())
    monkeypatch.setattr(agentic_live, "reasoning_in_request", lambda model: {"type": "disabled"})
    monkeypatch.setattr(agentic_live.runner, "run_episodes", run_the_copy)
    return agentic_live.run_live(
        model_id=model_id, api_key=FAKE_KEY, workload_dir=CHINOOK, case_ids=list(case_ids), repeats=repeats,
        out_dir=Path(tmp_path) / name, configuration="plain",
    )
