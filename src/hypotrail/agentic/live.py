"""The opt-in, bounded live run: the spike task against a real Anthropic model.

It scores nothing against References. It only records that a real model calls
the tool and uses its result. The key is passed explicitly to the provider and is
never logged or persisted; the output is scanned for it before the run reports.
"""

import json
import platform
from importlib import metadata
from pathlib import Path

from inspect_ai.log import read_eval_log
from inspect_ai.model import Model, get_model

from hypotrail.agentic import cases as case_module
from hypotrail.agentic import limits as limits_module
from hypotrail.agentic import projection, runner
from hypotrail.core.errors import HypotrailError, InvalidInputError

ANTHROPIC_BASE_URL = "https://api.anthropic.com"
EXPECTED_SEQUENCE = ["model_turn", "tool_call", "tool_result", "model_turn", "final_answer"]


def live_model(model_id: str, api_key: str, base_url: str = ANTHROPIC_BASE_URL) -> Model:
    """The Anthropic model, with the key and endpoint given explicitly.

    `max_retries=0` is the Anthropic SDK's own retry count (its default is 2),
    set here so no transport retry happens below Inspect either.
    """
    return get_model(model_id, api_key=api_key, base_url=base_url, max_retries=0)


def scan_for_secret(directory: Path, secret: str) -> list[str]:
    """Files under `directory` that hold `secret`, in raw bytes or once decoded.

    An `.eval` log is compressed, so it is also read back through Inspect's log
    API and searched as text.
    """
    needle = secret.encode()
    found = []
    for path in sorted(p for p in Path(directory).rglob("*") if p.is_file()):
        hit = needle in path.read_bytes()
        if not hit and path.suffix == ".eval":
            hit = secret in read_eval_log(str(path)).model_dump_json()
        if hit:
            found.append(str(path.relative_to(directory)))
    return found


def _tool_loop_observed(episodes: list[dict]) -> bool:
    return any(
        e["status"] == "produced" and [s["kind"] for s in e["steps"]] == EXPECTED_SEQUENCE
        for e in episodes
    )


def _uses_result(episode: dict) -> bool | None:
    """True when the final answer's rows are the rows the tool returned."""
    results = [s for s in episode["steps"] if s["kind"] == "tool_result"]
    if episode["final_answer"] is None or not results:
        return None
    try:
        answer = json.loads(episode["final_answer"])
    except json.JSONDecodeError:
        return False
    return isinstance(answer, dict) and answer.get("rows") == results[-1]["result"]["rows"]


def request_parameters(log) -> dict | None:
    """The parameters of the first model request, as the log recorded them.

    Messages, system prompt and tool definitions are left out: they are already
    in the projection. The key is never part of a request body.
    """
    for sample in log.samples or []:
        for event in sample.events or []:
            if event.event == "model" and event.call is not None:
                request = dict(event.call.request)
                return {k: v for k, v in request.items() if k not in ("messages", "system", "tools")}
    return None


def run_live(
    *,
    model_id: str,
    api_key: str,
    cases_path: Path,
    database: Path,
    case_ids: list[str],
    repeats: int,
    out_dir: Path,
    base_url: str = ANTHROPIC_BASE_URL,
) -> dict:
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise InvalidInputError(
            "OUTPUT_NOT_EMPTY",
            f"output directory is not empty: {out_dir}",
            stage="live",
            details={"out": str(out_dir)},
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = case_module.load_cases(cases_path, case_ids)
    limits = limits_module.EpisodeLimits()
    location = runner.run_episodes(
        cases,
        database=database,
        model=live_model(model_id, api_key, base_url),
        repeats=repeats,
        log_dir=out_dir / "inspect",
        limits=limits,
    )
    expected = [(c, r) for c in case_ids for r in range(repeats)]
    episodes = projection.project_log(location, expected=expected)
    log = read_eval_log(location)

    record = {
        "mode": "llm_live",
        "provider": "anthropic",
        "model": model_id,
        "served_models": sorted(
            {s.output.model for s in (log.samples or []) if s.output and s.output.model}
        ),
        "request_parameters": request_parameters(log),
        "engine": {"name": "inspect-ai", "version": metadata.version("inspect-ai")},
        "python": platform.python_version(),
        "hardware": platform.platform(),
        "machine": platform.machine(),
        "effective_limits": limits_module.read_back(location),
        "requested_limits": limits.as_dict(),
        "inspect_log": str(Path(location).relative_to(out_dir)),
        "inspect_status": log.status,
        "episodes": [
            {
                "case_id": e["case_id"],
                "repeat": e["repeat"],
                "status": e["status"],
                "stopped_by_limit": e["stopped_by_limit"],
                "uses_tool_result": _uses_result(e),
            }
            for e in episodes
        ],
        "tool_loop_observed": _tool_loop_observed(episodes),
    }
    (out_dir / "projection.json").write_text(json.dumps(episodes, indent=2, sort_keys=True) + "\n")
    (out_dir / "run.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")

    leaked = scan_for_secret(out_dir, api_key)
    if leaked:
        raise HypotrailError(
            "SECRET_IN_OUTPUT",
            f"the API key was found in the run output: {', '.join(leaked)}; do not keep or commit it",
            stage="live",
            details={"files": leaked},
        )
    return record

