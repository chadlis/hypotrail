"""The declared CLI scope of a protected ranking evaluator (D-264)."""

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar

from hypotrail.core.errors import InvalidInputError

HELD_OUT = "held_out"
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_WORKFLOW = ".github/workflows/evaluator.yml@refs/heads/main"
_inside = ContextVar("inside_ranking_evaluator", default=False)


def refusal(stage):
    return InvalidInputError(
        "RANKING_HELD_OUT_REFUSED",
        "The held-out ranking Partition is available only to supported commands of the declared evaluator CLI",
        stage=stage,
        details={"partition": HELD_OUT},
    )


@contextmanager
def entry_point():
    """Activate the explicit CLI entry point in a declared job of evaluator.yml, as for Agentkit A8.

    The kit owns the protected job and its admission policy. These environment fields declare the workflow
    context to Hypotrail; they do not verify GitHub's environment or replace the kit's authorization.
    """
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if (
        os.environ.get("HYPOTRAIL_RUN_TOOL") == "1"
        or os.environ.get("GITHUB_ACTIONS") != "true"
        or _REPOSITORY.fullmatch(repository) is None
        or os.environ.get("GITHUB_WORKFLOW_REF") != f"{repository}/{_WORKFLOW}"
    ):
        raise refusal("config")
    token = _inside.set(True)
    try:
        yield
    finally:
        _inside.reset(token)


def inside() -> bool:
    return _inside.get()


def is_protected(spec) -> bool:
    return spec["domain"] == "ranking" and spec.get("partition") == HELD_OUT


def refuse_protected(spec, *, stage) -> None:
    """Always refuse a protected Study at an entry point outside the evaluator contract."""
    if is_protected(spec):
        raise refusal(stage)


def require_study(spec, *, stage, run_tool=False) -> None:
    """Bind a declared evaluator command to a protected Study under its lock."""
    protected = is_protected(spec)
    if protected != inside() or (run_tool and protected):
        raise refusal(stage)
