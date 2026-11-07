"""The opt-in, bounded live run: the spike task against a real Anthropic model.

It scores nothing against References. It only records that a real model calls
the tool and uses its result. The key is passed explicitly to the provider and is
never logged or persisted; the output is scanned for it before the run reports.
"""

import hashlib
import json
import platform
from importlib import metadata
from pathlib import Path

from inspect_ai.log import read_eval_log
from inspect_ai.model import GenerateConfig, Model, get_model

from hypotrail.agentic import limits as limits_module
from hypotrail.agentic import projection, runner
from hypotrail.agentic.declaration import load_workload
from hypotrail.core.answer_scoring import parse_answer
from hypotrail.core.errors import HypotrailError, InvalidInputError

ANTHROPIC_BASE_URL = "https://api.anthropic.com"
# Reasoning is disabled, for both Configurations (owner decision 1 on #8). A level would draw its
# thinking from the same 1,024-token output cap as the answer, so an answer could be cut by our own
# setting; disabled keeps the whole cap for the answer. Inspect's name for it is "none".
REASONING_EFFORT = "none"
REASONING_SETTING = "disabled"
# From Inspect's Anthropic provider (`completion_config` and `_supports_disabling_thinking`): for
# reasoning_effort="none" it sends thinking {"type": "disabled"}; Sonnet 5.5 rejects "disabled" and
# is sent {"type": "between_tools"} instead, which its source calls "no up-front thinking" and the
# model's lowest setting. Its source does not say whether thinking may still occur between tool calls.
REASONING_NOTE = (
    'reasoning_effort "none" is sent as thinking {"type": "disabled"}; for Sonnet 5.5, which rejects '
    '"disabled", Inspect sends {"type": "between_tools"}, described in its source as no up-front thinking '
    "and the model's lowest setting. Inspect's source does not say whether thinking may still happen "
    "between tool calls."
)


def live_model(model_id: str, api_key: str, base_url: str = ANTHROPIC_BASE_URL) -> Model:
    """The Anthropic model, with the key and endpoint given explicitly.

    `max_retries=0` is the Anthropic SDK's own retry count (its default is 2),
    set here so no transport retry happens below Inspect either.
    """
    return get_model(model_id, api_key=api_key, base_url=base_url, max_retries=0)


def scan_for_secret(directory: Path, secret: str) -> list[str]:
    """Files under `directory` that hold `secret`, in raw bytes or once decoded.

    An `.eval` log is compressed, so it is also read back through Inspect's log
    API and searched as text. The log's storage format is never opened by hand
    (ADR 0001). The scan goes on to the files after any log that cannot be read.

    A log that Inspect cannot read back is never reported clean: if no leak is
    found anywhere, the scan fails with LOG_NOT_FULLY_SCANNED. A leak that is
    found is returned first, since it is what must be acted on.
    """
    needle = secret.encode()
    found = []
    unscanned = []
    for path in sorted(p for p in Path(directory).rglob("*") if p.is_file()):
        relative = str(path.relative_to(directory))
        hit = needle in path.read_bytes()
        if not hit and path.suffix == ".eval":
            try:
                hit = secret in read_eval_log(str(path)).model_dump_json()
            except Exception:
                # The text of the error is not kept: it could quote the content.
                unscanned.append(relative)
        if hit:
            found.append(relative)
    if unscanned and not found:
        raise HypotrailError(
            "LOG_NOT_FULLY_SCANNED",
            f"the log could not be fully scanned for the API key: {', '.join(unscanned)}; "
            "it was not reported clean, do not keep or commit it",
            stage="live",
            details={"files": unscanned},
        )
    return found


def _raise_if_leaked(out_dir: Path, api_key: str) -> None:
    leaked = scan_for_secret(out_dir, api_key)
    if leaked:
        raise HypotrailError(
            "SECRET_IN_OUTPUT",
            f"the API key was found in the run output: {', '.join(leaked)}; do not keep or commit it",
            stage="live",
            details={"files": leaked},
        )


def _scanned(out_dir: Path, api_key: str, work):
    """Run `work`, then scan `out_dir` for the key, whether or not `work` failed.

    Nothing may keep a key in its output (#20), so a failing step must not skip
    the scan. If both fail, the leak is raised and the first failure stays
    attached to it as its context.
    """
    try:
        return work()
    finally:
        _raise_if_leaked(out_dir, api_key)


def _succeeded(step: dict) -> bool:
    body = step["result"]
    return step["tool_error"] is None and not (isinstance(body, dict) and body.get("error") is not None)


def _has_tool_loop(episode: dict) -> bool:
    """A produced Episode: a successful `query_readonly` call, then a model turn, then the final answer."""
    steps = episode["steps"]
    if episode["status"] != "produced" or not steps or steps[-1]["kind"] != "final_answer":
        return False
    queries = {s["native_tool_call_id"] for s in steps if s["kind"] == "tool_call" and s["function"] == "query_readonly"}
    answered_after = next((i for i in range(len(steps) - 1, -1, -1) if steps[i]["kind"] == "model_turn"), None)
    return answered_after is not None and any(
        s["kind"] == "tool_result" and s["native_tool_call_id"] in queries and _succeeded(s)
        for s in steps[:answered_after]
    )


def tool_loop_observed(episodes: list[dict]) -> bool:
    """AG-10: at least one Episode shows model, a successful `query_readonly`, model, final answer.

    `describe_schema` calls and further queries may come anywhere in the loop.
    """
    return any(_has_tool_loop(e) for e in episodes)


# The Reasons of a null `uses_tool_result` (GLOSSARY: Reason).
NO_FINAL_ANSWER = "no_final_answer"
NO_TOOL_RESULT = "no_tool_result"
ANSWER_UNREADABLE = "answer_unreadable"


def _uses_result_with_reason(episode: dict) -> tuple[bool | None, str | None]:
    """Whether every row of the final answer is a row the tool returned, and why not when unknown.

    The value is `True` or `False` only for a readable answer (exactly one JSON object, as
    `parse_answer` decides). Otherwise it is `None` with a Reason: NO_FINAL_ANSWER,
    NO_TOOL_RESULT or ANSWER_UNREADABLE. The model may fetch more rows than it reports
    (for example to check ties).
    """
    results = [s for s in episode["steps"] if s["kind"] == "tool_result"]
    if episode["final_answer"] is None:
        return None, NO_FINAL_ANSWER
    if not results:
        return None, NO_TOOL_RESULT
    answer = parse_answer(episode["final_answer"])
    if answer is None:
        return None, ANSWER_UNREADABLE
    rows = answer.get("rows")
    # A tool message that is not JSON has no result (None); it returned no row.
    returned = [
        row
        for result in results
        if isinstance(result["result"], dict) and isinstance(result["result"].get("rows"), list)
        for row in result["result"]["rows"]
    ]
    return isinstance(rows, list) and bool(rows) and all(row in returned for row in rows), None


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


def reasoning_in_request(model: Model) -> dict | None:
    """The `thinking` field Inspect's own request building gives this model, with no network.

    It asks the provider's `completion_config` for the parameters it would send for the run's
    generation settings. None means the request would not state the reasoning setting.
    """
    config = GenerateConfig(
        max_tokens=limits_module.EpisodeLimits().max_output_tokens, reasoning_effort=REASONING_EFFORT
    )
    return model.api.completion_config(config)[0].get("thinking")


TOKEN_FIELDS = ("input_tokens", "output_tokens", "input_tokens_cache_write", "input_tokens_cache_read", "total_tokens")


def budget_of(sample) -> dict | None:
    """The Episode token budget as Inspect recorded it on the sample, and what it metered.

    The budget is stated as the run record states it (`limits.token_budget_fields`: its key names its
    metering); `metered_usage` is what the limit counted, to be read next to the Episode's
    `output_tokens`. A sample absent from the log has no figures (None).
    """
    if sample is None:
        return None
    return {
        **limits_module.token_budget_fields(sample.token_limit, sample.token_limit_type),
        "metered_usage": sample.token_limit_usage,
    }


def usage_of(sample) -> dict:
    """Descriptive numbers of one Episode: calls and latency, and the tokens and cost the log gives.

    The five token figures are Inspect's `ModelUsage` fields of the sample, summed over its models
    the way `ModelUsage.__add__` sums them (a field is None when every model leaves it None);
    `model_usage` keeps each model's entry as the log gives it. `total_tokens` includes the cached
    input tokens. A figure the log does not give is None, never zero (CMP-06); `sample` None is an
    expected Episode absent from the log.
    """
    if sample is None:
        return {
            "model_calls": None, "latency_seconds": None, "cost": None, "model_usage": None,
            **{field: None for field in TOKEN_FIELDS},
        }
    per_model = sample.model_usage or {}
    usage = list(per_model.values())

    def total(field):
        values = [getattr(u, field) for u in usage if getattr(u, field, None) is not None]
        return sum(values) if values else None

    return {
        "model_calls": sum(1 for e in sample.events or [] if e.event == "model"),
        "latency_seconds": None if sample.total_time is None else float(sample.total_time),
        **{field: total(field) for field in TOKEN_FIELDS},
        "cost": total("total_cost"),
        "model_usage": {name: u.model_dump(mode="json") for name, u in per_model.items()} or None,
    }


def _read_back_reasoning(location: str) -> str | None:
    """The reasoning effort that took effect, as the log header records it (public log API)."""
    log = read_eval_log(location, header_only=True)
    generate = log.eval.model_generate_config.model_copy(update=log.plan.config.model_dump(exclude_none=True))
    return generate.reasoning_effort


# where a record's `requested_limits` came from: the Attempt that made the request, or a kept log read again
THIS_ATTEMPT = "this_attempt"
KEPT_LOG = "kept_log"


_BUILT_BY_A_CONSTRUCTOR = object()


class Request:
    """The limits a record's `requested_limits` holds, with where they came from (`THIS_ATTEMPT` or `KEPT_LOG`).

    The only ways to build one are `Request.this_attempt(limits)` and `Request.from_log(location)`: each ties the
    source to how the limits were obtained, so a source cannot be paired with the other one's limits.
    """

    __slots__ = ("limits", "source")

    def __init__(self, limits: dict, source: str, *, _key: object = None):
        if _key is not _BUILT_BY_A_CONSTRUCTOR:
            raise TypeError("build a Request with Request.this_attempt or Request.from_log")
        self.limits = limits
        self.source = source

    @classmethod
    def this_attempt(cls, limits: limits_module.EpisodeLimits) -> "Request":
        return cls(limits_module.requested_limits(limits), THIS_ATTEMPT, _key=_BUILT_BY_A_CONSTRUCTOR)

    @classmethod
    def from_log(cls, location) -> "Request":
        return cls(limits_module.requested_from_log(location), KEPT_LOG, _key=_BUILT_BY_A_CONSTRUCTOR)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_live(
    *,
    model_id: str,
    api_key: str,
    workload_dir: Path,
    case_ids: list[str],
    repeats: int,
    out_dir: Path,
    base_url: str = ANTHROPIC_BASE_URL,
    configuration: str,
) -> dict:
    out_dir = Path(out_dir)
    model = live_model(model_id, api_key, base_url)
    if reasoning_in_request(model) is None:
        raise InvalidInputError(
            "REASONING_NOT_EXPLICIT",
            f"the request for {model_id} would not state the reasoning setting; "
            "a live run needs it explicit, so nothing was sent",
            stage="live",
            details={"model": model_id},
        )
    load_workload(workload_dir).cases_path("dev")  # a Workload without `dev` is refused before anything is written
    if out_dir.exists() and any(out_dir.iterdir()):
        raise InvalidInputError(
            "OUTPUT_NOT_EMPTY",
            f"output directory is not empty: {out_dir}",
            stage="live",
            details={"out": str(out_dir)},
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    def work() -> dict:
        workload = load_workload(workload_dir)
        before = _sha256(workload.database_path)
        limits = limits_module.EpisodeLimits()
        location = runner.run_episodes(
            workload.cases("dev", case_ids),
            workload=workload,
            configuration=configuration,
            model=model,
            repeats=repeats,
            log_dir=out_dir / "inspect",
            limits=limits,
            reasoning_effort=REASONING_EFFORT,
        )
        return _record(
            request=Request.this_attempt(limits),
            limits=limits,
            location=location,
            out_dir=out_dir,
            model_id=model_id,
            case_ids=case_ids,
            repeats=repeats,
            database_sha256={"before": before, "after": _sha256(workload.database_path)},
        )

    return _scanned(out_dir, api_key, work)


def summarize(
    *,
    location: str,
    out_dir: Path,
    model_id: str,
    api_key: str,
    case_ids: list[str],
    repeats: int,
    database_sha256: dict | None = None,
) -> dict:
    """Project a kept log, write the run record, and scan the output for the key.

    It reads the log only; it calls neither the model nor any tool, so it can be
    run again on a kept log. The scan runs even if a step fails. The database hashes
    belong to the run, so they are recorded only if given (None otherwise).
    """
    out_dir = Path(out_dir).resolve()
    return _scanned(
        out_dir,
        api_key,
        lambda: _record(
            request=Request.from_log(location),
            limits=limits_module.EpisodeLimits(),
            location=location,
            out_dir=out_dir,
            model_id=model_id,
            case_ids=case_ids,
            repeats=repeats,
            database_sha256=database_sha256,
        ),
    )


def _episode_entry(episode: dict, sample) -> dict:
    uses_tool_result, uses_tool_result_reason = _uses_result_with_reason(episode)
    return {
        "case_id": episode["case_id"],
        "repeat": episode["repeat"],
        "status": episode["status"],
        "stopped_by_limit": episode["stopped_by_limit"],
        "uses_tool_result": uses_tool_result,
        "uses_tool_result_reason": uses_tool_result_reason,
        "token_budget": budget_of(sample),
        **usage_of(sample),
    }


def _record(
    *,
    request: Request,
    limits: limits_module.EpisodeLimits,
    location: str,
    out_dir: Path,
    model_id: str,
    case_ids: list[str],
    repeats: int,
    database_sha256: dict | None,
) -> dict:
    out_dir = Path(out_dir).resolve()
    expected = [(c, r) for c in case_ids for r in range(repeats)]
    episodes = projection.project_log(location, expected=expected)
    log = read_eval_log(location)
    parameters = request_parameters(log)
    effective = limits_module.read_back(location)
    # `request` is what its caller names: this Attempt's, or the kept log's, never today's code (#57)
    samples = {(str(s.id), s.epoch - 1): s for s in log.samples or []}

    record = {
        "mode": "llm_live",
        "provider": "anthropic",
        # the exact prompt text of the Configuration, as the log header kept it
        "configuration": (log.eval.metadata or {}).get("configuration"),
        "system_text": (log.eval.metadata or {}).get("system_text"),
        "model": model_id,
        "served_models": sorted(
            {s.output.model for s in (log.samples or []) if s.output and s.output.model}
        ),
        "request_parameters": parameters,
        # reasoning and the output cap: what was asked, and what the request carried
        "reasoning": {
            "setting": REASONING_SETTING,
            "requested": _read_back_reasoning(location),
            "sent": (parameters or {}).get("thinking"),
            "note": REASONING_NOTE,
        },
        "output_cap": {"requested": request.limits["max_output_tokens"], "sent": (parameters or {}).get("max_tokens")},
        "engine": {"name": "inspect-ai", "version": metadata.version("inspect-ai")},
        "python": platform.python_version(),
        "hardware": platform.platform(),
        "machine": platform.machine(),
        "effective_limits": effective,
        "requested_limits": request.limits,
        "request_source": request.source,
        "limit_notes": {
            "tool_calls": limits_module.NOT_ENFORCEABLE["tool_calls"],
            "provider_calls": f"{limits.model_turns} model turns allow {limits.model_turns + 1} provider calls",
        },
        "cases": [{"case_id": c, "repeat": r} for c, r in expected],
        "database_sha256": database_sha256,
        "inspect_log": str(Path(location).resolve().relative_to(out_dir)),
        "inspect_status": log.status,
        "episodes": [_episode_entry(e, samples.get((e["case_id"], e["repeat"]))) for e in episodes],
        "tool_loop_observed": tool_loop_observed(episodes),
    }
    (out_dir / "projection.json").write_text(json.dumps(episodes, indent=2, sort_keys=True) + "\n")
    (out_dir / "run.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record
