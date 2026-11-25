"""The Protocol check: is the Workload's Protocol, as it is declared now, still the one of the Study's current revision?

It is made on five paths: `run ml`, `import ml`, `run agent` and `import agent` for a new request (stage `request`), and
`hypotrail.core.exposure.checked_basis` when an Exposure is recorded (stage `exposure`). The core knows no Track, so each
path computes the Protocol digest itself and gives it here, with the message and the stage it refuses with.
"""

from hypotrail.core.errors import IntegrityError


def require_unchanged(spec: dict, protocol_digest: str, *, message: str, stage: str) -> None:
    """Refuse with `PROTOCOL_CHANGED` (exit 3) when `protocol_digest` is not the `protocol_digest` of `spec`."""
    if protocol_digest != spec["protocol_digest"]:
        raise IntegrityError(
            "PROTOCOL_CHANGED",
            message,
            stage=stage,
            details={"expected_protocol_digest": spec["protocol_digest"], "actual_protocol_digest": protocol_digest},
        )
