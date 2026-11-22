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

A Study has one request_id namespace, for its Attempts, its decisions (`hypotrail.core.decisions`, D-033 on chadlis/hypotrail#75) and
its Declared deviations (`hypotrail.core.deviations`, D-073 on chadlis/hypotrail#75). `REQUEST_CONFLICT`'s `details` carry `attempt_id`,
`decision_id` and `declared_deviation_id`, each set to null when it does not apply (D-034 on chadlis/hypotrail#75). A request_id that names
a record of another kind is a conflict whose `differs` is `["command"]`, the first element of `IDENTITY_KEYS` (D-037 on chadlis/hypotrail#75);
between two decisions, or two Declared deviations, `differs` names fields of the record.
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


def _refusal(message: str, request_id: str, differs: list, *, attempt_id=None, decision_id=None, declared_deviation_id=None) -> HypotrailError:
    """`REQUEST_CONFLICT`: `details` carry `attempt_id`, `decision_id` and `declared_deviation_id`, the ones that do not apply set to null."""
    return HypotrailError(
        "REQUEST_CONFLICT",
        message,
        stage="request",
        details={
            "request_id": request_id,
            "attempt_id": attempt_id,
            "decision_id": decision_id,
            "declared_deviation_id": declared_deviation_id,
            "differs": differs,
        },
        exit_code=EXIT_LOCK_OR_CONFLICT,
    )


def conflict(request_id: str, attempt_id: str, differs: list) -> HypotrailError:
    """A `run` or an `import` whose `request_id` names an Attempt of another request."""
    return _refusal(
        f"request_id {request_id!r} already names an Attempt of another request (differs: {', '.join(differs)}); "
        "use a new request_id, with retry_of to repeat it on purpose",
        request_id,
        differs,
        attempt_id=attempt_id,
    )


def conflict_with_a_decision(request_id: str, decision_id: str) -> HypotrailError:
    """A `run`, an `import` or a `deviation` whose `request_id` names a decision: the elements of a request differ from the record's by its command."""
    return _refusal(
        f"request_id {request_id!r} already names a decision (differs: command); use a new request_id",
        request_id,
        ["command"],
        decision_id=decision_id,
    )


def conflict_with_a_declared_deviation(request_id: str, declared_deviation_id: str) -> HypotrailError:
    """A `run`, an `import` or a `decide` whose `request_id` names a Declared deviation: the requests differ by their command."""
    return _refusal(
        f"request_id {request_id!r} already names a Declared deviation (differs: command); use a new request_id",
        request_id,
        ["command"],
        declared_deviation_id=declared_deviation_id,
    )


def conflict_between_decisions(request_id: str, decision_id: str, differs: list) -> HypotrailError:
    """A `decide` whose `request_id` names another decision: `differs` lists the fields of the decision record that differ."""
    return _refusal(
        f"request_id {request_id!r} already names another decision (differs: {', '.join(differs)}); use a new request_id",
        request_id,
        differs,
        decision_id=decision_id,
    )


def conflict_between_declared_deviations(request_id: str, declared_deviation_id: str, differs: list) -> HypotrailError:
    """A `deviation` whose `request_id` names another Declared deviation: `differs` lists the fields of the record that differ."""
    return _refusal(
        f"request_id {request_id!r} already names another Declared deviation (differs: {', '.join(differs)}); use a new request_id",
        request_id,
        differs,
        declared_deviation_id=declared_deviation_id,
    )


def conflict_with_an_attempt(request_id: str, attempt_id: str, command: str = "decide") -> HypotrailError:
    """A `decide` or a `deviation` whose `request_id` names an Attempt, which that command cannot repeat."""
    return _refusal(
        f"request_id {request_id!r} already names an Attempt, which `{command}` cannot repeat (differs: command); use a new request_id",
        request_id,
        ["command"],
        attempt_id=attempt_id,
    )
