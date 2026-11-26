"""The two checks of a capped live Campaign, which ticket 2 (#235) applies to its plan and to its kept log.

`episode_bound` and `ceiling` are D-146's formula on chadlis/hypotrail#75: "Per Episode: `E = C × (1 + p_max/p_in) +
[p_max × (1,024 + B + framing allowance) + p_out × 1,024] / 1e6`." and "Ceiling = paid Episodes × E.", with "`p_max =
max(input, input_cache_write)`". The 1,024 is the output cap of one model call (`EpisodeLimits.max_output_tokens`); B is
counted at one token per byte.

`post_run_faults` is its post-run witness: "no assistant message holds two tool calls, and no Episode cost exceeds E".
It reads the log through Inspect's public log API, and an Episode's cost as the run record states it (`usage_of`).
"""

from inspect_ai.log import read_eval_log

from hypotrail.agentic.limits import EpisodeLimits
from hypotrail.agentic.live import usage_of

# The drive's answer C4 on chadlis/hypotrail#232: "The framing allowance is 2,048 tokens"
FRAMING_ALLOWANCE_TOKENS = 2_048


def episode_bound(price_list: dict, model: str, limits: EpisodeLimits, b_bytes: int) -> float:
    """E in USD, for `model` priced by `price_list` (the file's content) under the declared `limits`."""
    prices = price_list["models"][model]
    p_in, p_out = prices["input"], prices["output"]
    p_max = max(prices["input"], prices["input_cache_write"])
    cap = limits.max_output_tokens
    return limits.cost_limit_usd * (1 + p_max / p_in) + (p_max * (cap + b_bytes + FRAMING_ALLOWANCE_TOKENS) + p_out * cap) / 1e6


def ceiling(price_list: dict, model: str, limits: EpisodeLimits, b_bytes: int, paid_episodes: int) -> float:
    """The Campaign's ceiling in USD: the paid Episodes times E."""
    return paid_episodes * episode_bound(price_list, model, limits, b_bytes)


def post_run_faults(location: str, bound: float) -> list[str]:
    """Each fault of a kept log: an assistant message with two tool calls or more, an Episode whose cost exceeds `bound` or is not recorded."""
    faults = []
    for sample in read_eval_log(location).samples or []:
        episode = f"{sample.id} repeat {sample.epoch - 1}"
        for index, message in enumerate(sample.messages):
            if message.role == "assistant" and len(message.tool_calls or []) > 1:
                faults.append(f"{episode}: assistant message {index} holds {len(message.tool_calls)} tool calls")
        cost = usage_of(sample)["cost"]
        if cost is None:
            faults.append(f"{episode}: no cost is recorded")
        elif cost > bound:
            faults.append(f"{episode}: cost {cost} exceeds E = {bound}")
    return faults
