"""Preconditions of a live model execution, checked before anything is imported or sent.

Standard library only. A live execution is opt-in, bounded and never part of the test
suite or CI. The provider key is read from one variable and from no other.
"""

import re

from hypotrail.core.errors import (
    EXIT_CAPABILITY_UNAVAILABLE,
    HypotrailError,
    InvalidInputError,
)

KEY_VARIABLE = "HYPOTRAIL_ANTHROPIC_API_KEY"
# Inspect's Anthropic provider prefers this variable over an explicit API key.
TOKEN_VARIABLE_THAT_WOULD_OVERRIDE_THE_KEY = "ANTHROPIC_AUTH_TOKEN"
NOT_VALIDATED = "LIVE_NOT_VALIDATED"
MAX_EPISODES = 2

# One provider only: the key must never be sent to another one, nor through a
# cloud-platform variant of the same provider.
_MODEL_ID = re.compile(r"anthropic/[A-Za-z0-9][A-Za-z0-9._-]*")


def require_model(model) -> str:
    """The explicit model identifier. There is no default."""
    if not model or not _MODEL_ID.fullmatch(model):
        raise InvalidInputError(
            "MODEL_REQUIRED",
            "an explicit Anthropic model identifier is required, as anthropic/<model>",
            stage="live",
            details={"model": model},
        )
    return model


def check_bounds(case_ids: list[str], repeats: int, dev_case_ids: set[str]) -> None:
    """At most two Episodes, all on dev Cases."""
    outside = [c for c in case_ids if c not in dev_case_ids]
    if outside:
        raise InvalidInputError(
            "CASE_NOT_DEV",
            f"a live execution is limited to dev Cases, not: {', '.join(outside)}",
            stage="live",
            details={"cases": outside},
        )
    episodes = len(case_ids) * repeats
    if repeats < 1 or len(set(case_ids)) != len(case_ids) or not 1 <= episodes <= MAX_EPISODES:
        raise InvalidInputError(
            "EPISODES_OUT_OF_BOUNDS",
            f"a live execution is limited to {MAX_EPISODES} Episodes (distinct Cases x Repeats), "
            f"got {episodes}",
            stage="live",
            details={"episodes": episodes, "maximum": MAX_EPISODES},
        )


def read_api_key(environ) -> str:
    """The key from `HYPOTRAIL_ANTHROPIC_API_KEY`, or exit 5 with a named blocker."""
    if environ.get(TOKEN_VARIABLE_THAT_WOULD_OVERRIDE_THE_KEY):
        raise _unavailable(
            f"{TOKEN_VARIABLE_THAT_WOULD_OVERRIDE_THE_KEY} is set and would take "
            f"precedence over {KEY_VARIABLE}"
        )
    key = environ.get(KEY_VARIABLE)
    if not key:
        raise _unavailable(f"{KEY_VARIABLE} is not set")
    return key


def _unavailable(blocker: str) -> HypotrailError:
    return HypotrailError(
        "LIVE_UNAVAILABLE",
        f"{NOT_VALIDATED}: {blocker}; no network call was made",
        stage="capability",
        details={"status": NOT_VALIDATED, "blocker": blocker},
        exit_code=EXIT_CAPABILITY_UNAVAILABLE,
    )
