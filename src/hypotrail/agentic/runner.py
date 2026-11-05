"""Running the Workload task under Inspect, offline or live.

One code path serves the scripted runs and the live run: only the model differs.
"""

from collections.abc import Callable
from pathlib import Path

from inspect_ai import Task, eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageSystem, ChatMessageUser, Model, get_model
from inspect_ai.solver import generate, use_tools

from hypotrail.agentic.cases import user_message
from hypotrail.agentic.declaration import Workload
from hypotrail.agentic.limits import EpisodeLimits, eval_options
from hypotrail.agentic.sql_tool import QueryCaps, describe_schema, query_readonly


def build_task(
    workload: Workload,
    configuration: str,
    *,
    cases: list[dict] | None = None,
    partition: str = "dev",
    scorer=None,
    query_caps: QueryCaps | None = None,
    metadata: dict | None = None,
) -> Task:
    """The Inspect task of a Workload under one Configuration.

    Each Case is one sample whose input is the Configuration's system text and the user message
    rendered from the Case. The model gets `describe_schema` and `query_readonly` on the database
    the declaration fixes. The References are not an input: nothing here reads them.
    """
    system_text = workload.system_text(configuration)
    samples = [
        Sample(
            id=case["case_id"],
            input=[ChatMessageSystem(content=system_text), ChatMessageUser(content=user_message(case))],
        )
        for case in (cases if cases is not None else workload.cases(partition))
    ]
    database = workload.database_path
    query_caps = query_caps or QueryCaps()
    return Task(
        dataset=MemoryDataset(samples, name=workload.workload_id),
        solver=[use_tools(describe_schema(database), query_readonly(database, query_caps)), generate()],
        scorer=scorer,
        name=f"{workload.workload_id}_{configuration}",
        # the exact prompt text of the Configuration is kept in the log header
        metadata={
            "configuration": configuration,
            "system_text": system_text,
            "query_caps": query_caps.as_dict(),
            **(metadata or {}),
        },
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
    workload: Workload,
    configuration: str,
    model: Model,
    repeats: int,
    log_dir: Path,
    scorer=None,
    limits: EpisodeLimits | None = None,
    query_caps: QueryCaps | None = None,
    metadata: dict | None = None,
    **overrides,
) -> str:
    """Run every Case `repeats` times and return the location of the Inspect log."""
    logs = eval(
        build_task(workload, configuration, cases=cases, scorer=scorer, query_caps=query_caps, metadata=metadata),
        model=model,
        epochs=repeats,
        log_dir=str(log_dir),
        display="none",
        **{**eval_options(limits or EpisodeLimits()), **overrides},
    )
    return logs[0].location
