"""Running the spike task under Inspect, offline or live.

One code path serves the scripted runs and the live run: only the model differs.
"""

from collections.abc import Callable
from pathlib import Path

from inspect_ai import Task, eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageSystem, ChatMessageUser, Model, get_model
from inspect_ai.solver import generate, use_tools

from hypotrail.agentic.cases import model_input
from hypotrail.agentic.limits import EpisodeLimits, eval_options
from hypotrail.agentic.sql_tool import QueryCaps, query_readonly


def build_task(cases: list[dict], database: Path, scorer=None, query_caps: QueryCaps | None = None) -> Task:
    """The spike task: the model may call `query_readonly`, then answers."""
    samples = []
    for case in cases:
        system_text, user_text = model_input(case)
        samples.append(
            Sample(
                id=case["case_id"],
                input=[ChatMessageSystem(content=system_text), ChatMessageUser(content=user_text)],
            )
        )
    query_caps = query_caps or QueryCaps()
    return Task(
        dataset=MemoryDataset(samples, name="chinook-spike"),
        solver=[use_tools(query_readonly(database, query_caps)), generate()],
        scorer=scorer,
        name="chinook_spike",
        metadata={"query_caps": query_caps.as_dict()},
        fail_on_error=False,
    )


async def _estimate_text_tokens(text: str) -> int:
    """Offline token estimate: about four characters per token, never zero."""
    return max(1, len(text) // 4)


def mock_model(script: Callable) -> Model:
    """Inspect's built-in mock model driven by a scripted callable.

    The mock provider fills in token usage by counting with tiktoken, which
    downloads its vocabulary on first use. A scripted run must work with the
    network off after installation (SPEC DATA-03), so the count is replaced by
    a local estimate and nothing is fetched.
    """
    model = get_model("mockllm/model", custom_outputs=script)
    model.api.count_text_tokens = _estimate_text_tokens
    return model


def run_episodes(
    cases: list[dict],
    *,
    database: Path,
    model: Model,
    repeats: int,
    log_dir: Path,
    scorer=None,
    limits: EpisodeLimits | None = None,
    query_caps: QueryCaps | None = None,
    **overrides,
) -> str:
    """Run every Case `repeats` times and return the location of the Inspect log."""
    logs = eval(
        build_task(cases, database, scorer, query_caps),
        model=model,
        epochs=repeats,
        log_dir=str(log_dir),
        display="none",
        **{**eval_options(limits or EpisodeLimits()), **overrides},
    )
    return logs[0].location
