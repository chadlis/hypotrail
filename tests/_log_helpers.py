"""Shared by the Inspect log import tests (#69): logs written offline by Inspect's mock model, population files, `import agent`."""

import shutil
from pathlib import Path

from _agent_helpers import WORKLOAD, ScriptedModel

from hypotrail.agentic import runner

KEPT = Path(__file__).resolve().parent.parent / "docs" / "handbook" / "traces"
KEPT_LOGS = sorted(KEPT.glob("live-*/inspect/*.eval"))
SCRIPTED = {"mode": "scripted_fixture", "banner": "simulation, no LLM evaluated"}


def scripted_log(tmp_path, case_ids=("D01", "D03"), *, partition="dev", repeats=1, name="logs", metadata=SCRIPTED, script=None, limits=None, configuration="plain"):
    """The location of an Inspect log of `case_ids`, run by the mock model on the real local tools."""
    cases = WORKLOAD.cases(partition, list(case_ids))
    return runner.run_episodes(
        cases,
        workload=WORKLOAD,
        configuration=configuration,
        model=runner.mock_model(script or ScriptedModel(cases)),
        repeats=repeats,
        log_dir=Path(tmp_path) / name,
        metadata=metadata,
        limits=limits,
    )


def agent_log_import_refusals(tmp_path, monkeypatch):
    """Provoke each refusal that only a log import has; return {code: (exit code, stage, set of details keys)}."""
    import sys

    from _chinook_helpers import episodes_file, import_agent, init_chinook
    from inspect_ai.log import read_eval_log

    from hypotrail.agentic import inspect_log
    from hypotrail.core.errors import InvalidInputError

    found = {}

    def record(result):
        code, payload, _ = result
        error = payload["error"]
        found[error["code"]] = (code, error["stage"], set(error["details"]))

    study = init_chinook(tmp_path, name="log-refusals")[0]
    log = scripted_log(tmp_path, ("D01", "D03"))
    record(import_agent(study, log, episodes_file(tmp_path, [("D01", 0)]), "r"))  # D03 is in the log, not in the population
    junk = Path(tmp_path) / "junk.eval"
    junk.write_bytes(b"not a log")
    record(import_agent(study, junk, episodes_file(tmp_path, [("D01", 0)]), "r"))
    from inspect_ai.log import write_eval_log

    other_version = read_eval_log(str(log))
    other_version.eval.packages = {"inspect_ai": "0.3.1"}
    write_eval_log(other_version, str(Path(tmp_path) / "other-version.eval"))
    record(import_agent(study, Path(tmp_path) / "other-version.eval", episodes_file(tmp_path, [("D01", 0)]), "r"))
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "inspect_ai", None)
        record(import_agent(study, log, episodes_file(tmp_path, [("D01", 0)]), "r"))
    loaded = read_eval_log(str(log))
    loaded.samples.append(loaded.samples[0].model_copy())  # Inspect's own writer drops a repeated sample
    try:
        inspect_log.checked_episodes(loaded, [("D01", 0), ("D03", 0)], "dev", {"D01": "dev", "D03": "dev"})
    except InvalidInputError as error:
        found[error.code] = (error.exit_code, error.stage, set(error.details))
    return found


def kept_log(tmp_path, index=0):
    """A copy of one of the kept live logs (the kept trace itself is never touched)."""
    target = Path(tmp_path) / f"kept-{index}.eval"
    shutil.copyfile(KEPT_LOGS[index], target)
    return target
