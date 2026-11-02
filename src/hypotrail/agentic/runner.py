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
from hypotrail.agentic.sql_tool import query_readonly


def build_task(cases: list[dict], database: Path, scorer=None) -> Task:
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
    return Task(
        dataset=MemoryDataset(samples, name="chinook-spike"),
        solver=[use_tools(query_readonly(database)), generate()],
        scorer=scorer,
        name="chinook_spike",
        fail_on_error=False,
    )


def mock_model(script: Callable) -> Model:
    """Inspect's built-in mock model driven by a scripted callable."""
    return get_model("mockllm/model", custom_outputs=script)


def run_episodes(
    cases: list[dict],
    *,
    database: Path,
    model: Model,
    repeats: int,
    log_dir: Path,
    scorer=None,
) -> str:
    """Run every Case `repeats` times and return the location of the Inspect log."""
    logs = eval(
        build_task(cases, database, scorer),
        model=model,
        epochs=repeats,
        log_dir=str(log_dir),
        display="none",
        max_samples=1,
    )
    return logs[0].location
