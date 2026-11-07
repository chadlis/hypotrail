"""Episode limits, set through Inspect's own options and read back from the log.

AG-11 proposes the values below; the Episode token budget was revised by owner decision on #50 (2026-11-07):
4,000 output tokens, metered by Inspect's own `TokenLimit(type="output")`, not 12,000 tokens in total.
Nothing here re-implements a limit: each field maps to an Inspect option, or is reported as having no
native control.
"""

from dataclasses import asdict, dataclass

from inspect_ai.log import read_eval_log
from inspect_ai.util import TokenLimit

from hypotrail.core.errors import InvalidInputError

# which tokens the Episode token budget meters: Inspect's "output" (reasoning tokens included), never "all"
TOKEN_BUDGET_METERING = "output"


@dataclass(frozen=True)
class EpisodeLimits:
    model_turns: int = 6
    tool_calls: int = 8
    time_seconds: int = 60
    output_token_budget: int = 4_000
    max_output_tokens: int = 1_024
    concurrency: int = 1
    response_cache: bool = False
    sample_retries: int = 0
    transport_retries: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def requested_limits(limits: EpisodeLimits) -> dict:
    """The limits asked for, with the metering of the token budget beside it (the metering is not a limit)."""
    return {**limits.as_dict(), "token_budget_metering": TOKEN_BUDGET_METERING}


def token_budget_fields(limit: int | None, limit_type: str | None) -> dict:
    """The token budget as the record states it: its key names its metering, and the metering stands beside it.

    Inspect records "output" for the budget in force and None for "all" tokens (a log made before
    metering types existed). The key is `output_token_budget` for "output" and `total_tokens` for "all".
    With no limit there is nothing to state: the dict is empty. Another type (an Inspect formula) is refused.
    """
    if limit is None:
        return {}
    metering = limit_type or "all"
    if metering not in ("output", "all"):
        raise InvalidInputError(
            "TOKEN_METERING_UNSUPPORTED",
            f"the token limit type {limit_type!r} is neither 'output' nor 'all'",
            stage="limits",
            details={"token_limit_type": limit_type},
        )
    key = "output_token_budget" if metering == "output" else "total_tokens"
    return {key: limit, "token_budget_metering": metering}


# Limits for which Inspect 0.3.287 offers no control of its own.
NOT_ENFORCEABLE = {
    "tool_calls": (
        "Inspect has no limit on the number of tool calls (its limits are message, "
        "turn, token, time, working time and cost). It is bounded only indirectly: "
        "at most one call per model turn if the model makes no parallel tool calls."
    ),
}


def eval_options(limits: EpisodeLimits) -> dict:
    """Keyword arguments for `inspect_ai.eval` that apply the limits."""
    return {
        "turn_limit": limits.model_turns,
        "time_limit": limits.time_seconds,
        "token_limit": TokenLimit(tokens=limits.output_token_budget, type=TOKEN_BUDGET_METERING),
        "max_samples": limits.concurrency,
        "max_tasks": 1,
        "retry_on_error": limits.sample_retries,
        "task_retry_attempts": 0,
        # generation settings
        "max_tokens": limits.max_output_tokens,
        "max_connections": limits.concurrency,
        "max_retries": limits.transport_retries,
        "cache": limits.response_cache,
    }


def read_back(location: str) -> dict:
    """The values that took effect, as the log records them (public log API).

    `query_caps` holds the four per-query caps of the SQL tool (None for a log made before they existed).
    """
    log = read_eval_log(location, header_only=True)
    config = log.eval.config
    # Generation settings passed to `eval` are recorded in the plan; those set on
    # the model are recorded with the model. Either one may hold a value.
    generate = log.eval.model_generate_config.model_copy(
        update=log.plan.config.model_dump(exclude_none=True)
    )
    return {
        "model_turns": config.turn_limit,
        "tool_calls": None,
        "time_seconds": config.time_limit,
        **token_budget_fields(config.token_limit, config.token_limit_type),
        "max_output_tokens": generate.max_tokens,
        "concurrency": config.max_samples,
        "max_connections": generate.max_connections,
        "response_cache": generate.cache,
        "sample_retries": config.retry_on_error,
        "transport_retries": generate.max_retries,
        # the per-query caps of `query_readonly`, recorded in the task metadata
        "query_caps": (log.eval.metadata or {}).get("query_caps"),
    }


# How each limit stands, and the test that witnesses it (spike check 3).
# Labels: "shown enforced", "configured, not witnessed", "not enforceable".
ENFORCEMENT = {
    "model_turns": ("shown enforced", "test_the_turn_limit_stops_the_episode_at_the_configured_count"),
    "tool_calls": ("not enforceable", "test_inspect_has_no_tool_call_limit"),
    "time_seconds": ("configured, not witnessed", "test_the_time_limit_stops_a_slow_episode"),
    "output_token_budget": ("shown enforced", "test_the_output_token_budget_stops_the_episode"),
    "max_output_tokens": ("configured, not witnessed", "test_the_output_token_cap_reaches_every_model_call"),
    "concurrency": ("shown enforced", "test_one_episode_runs_at_a_time"),
    "response_cache": ("shown enforced", "test_the_response_cache_is_off"),
    "sample_retries": ("shown enforced", "test_an_errored_episode_is_not_retried"),
    "transport_retries": ("shown enforced", "test_a_transient_model_error_is_not_retried"),
}
