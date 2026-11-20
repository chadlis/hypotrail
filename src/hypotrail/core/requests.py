"""The identity of a request, and the `REQUEST_CONFLICT` of a request_id reused for another request.

A request is identified by its command, Workload, Configuration, Partition, Mode, the digests of
its input files and the code revision (chadlis/hypotrail#1 amendment); the agent Track adds the
model, the Repeats and the Cases (chadlis/hypotrail#74), which a native ML request does not hold. The code revision is the one of the
Attempt's `code_environment`: the commit, its dirty state and, for a dirty tree, the fingerprint
of the local code (#64 Tightened B2).

The identity is taken from the Attempt manifest itself, so the recorded request and the new one
are compared on the same fields. The Configuration is its id and its declared content in canonical
form, so a declaration whose keys are in another order is the same request; the effective
parameters, found only after a fit, and the Python version are not part of it. Input files are
compared by the sha256 of their bytes.

The same request_id with the same request returns the recorded Attempt; with any element
different it is `REQUEST_CONFLICT`, exit 6, naming the elements that differ.
"""

from hypotrail.core import canonical
from hypotrail.core.errors import EXIT_LOCK_OR_CONFLICT, HypotrailError

# `model`, `repeats` and `cases` belong to the agent Track (`model` and `repeats` also to imports, where they
# are `unknown` unless the file declares them); a native ML request does not hold them, so both sides read
# them as absent.
IDENTITY_KEYS = ("command", "workload", "configuration", "partition", "cases", "mode", "model", "repeats", "input_digests")
ELEMENTS = IDENTITY_KEYS + ("code_revision",)


def identity(effective_config: dict, code_environment: dict) -> dict:
    request = {key: effective_config.get(key) for key in IDENTITY_KEYS}
    request["code_revision"] = code_environment["code_revision"]
    return request


def differences(recorded: dict, requested: dict) -> list:
    """The elements of the two requests that differ, in the order of `ELEMENTS`."""
    return [key for key in ELEMENTS if canonical.dumps(recorded.get(key)) != canonical.dumps(requested.get(key))]


def conflict(request_id: str, attempt_id: str, differs: list) -> HypotrailError:
    return HypotrailError(
        "REQUEST_CONFLICT",
        f"request_id {request_id!r} already names an Attempt of another request (differs: {', '.join(differs)}); "
        "use a new request_id, with retry_of to repeat it on purpose",
        stage="request",
        details={"request_id": request_id, "attempt_id": attempt_id, "differs": differs},
        exit_code=EXIT_LOCK_OR_CONFLICT,
    )
