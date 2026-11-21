"""The write protocol that `run ml`, `run agent`, `import ml`, `import agent` and `decide` share (ADR 0004).

A writer calls `check_arguments` before anything else, does its own checks that come before the lock, then works inside `locked(...)`, which
takes the writer lock and opens the write journal. Inside it, the session it yields runs the steps in the order every one of these writers
keeps: the replay lookup under the `request_id`, the guard on the Study's one `request_id` namespace, then the stale check (`require_current`).
A writer supplies its command, what identifies its request, its own check of a record already recorded, its own checks and its writes;
it calls `begin()` just before its first write.
"""

import contextlib
from pathlib import Path

from hypotrail.core import decisions, lock, requests, write_journal  # `decisions` imports this module too: each uses the other only when called
from hypotrail.core import study as layout
from hypotrail.core.errors import InvalidInputError

RUN_ML = "run ml"
RUN_AGENT = "run agent"
IMPORT_ML = "import ml"
IMPORT_AGENT = "import agent"
DECIDE = "decide"
INIT = "init"
INIT_NEW_REVISION = "init --new-revision"

DECISION = "decision"
REVISION = "revision"


def invalid_arguments(message: str, command: str) -> InvalidInputError:
    """An `INVALID_ARGUMENTS` refusal whose `details` are `{"command": "hypotrail <command>"}`, the form the parser gives."""
    return InvalidInputError("INVALID_ARGUMENTS", message, stage="config", details={"command": f"hypotrail {command}"})


def check_read_sequence(command: str, read_sequence) -> None:
    """The first argument check of a writer, before any lock: the value of `--read-sequence`.

    `command` is the command's name as the command line shows it, which `init --new-revision` gives as `init`.
    """
    fault = write_journal.read_sequence_fault(read_sequence)
    if fault is not None:
        raise invalid_arguments(fault, command)


def check_arguments(command: str, read_sequence, request_id) -> None:
    """The first two argument checks of a writer that has a `request_id`, before any lock: the value of `--read-sequence`, then that `--request-id` is not empty."""
    check_read_sequence(command, read_sequence)
    if not request_id:
        raise InvalidInputError("REQUEST_ID_EMPTY", "--request-id must not be empty", stage="request", details={})


class Write:
    """What a writer holds while it works under the writer lock."""

    def __init__(self, study, request_id: str, read_sequence, journal):
        self.study, self.request_id, self.read_sequence, self._journal = Path(study), request_id, read_sequence, journal

    def begin(self) -> None:
        """Append the `begin` entry, once: call it just before the command's first write."""
        self._journal.begin()

    def require_current(self) -> None:
        """Refuse a write made on a write sequence that is not the Study's: the writer has no replay to run first."""
        write_journal.require_current(self.study, self.read_sequence)

    def attempt(self, attempt_id: str) -> None:
        """Name the Attempt the command writes: its `end` entry names the Attempt and, once it exists, its Observation set."""
        self._journal.attempt_id = attempt_id

    def wrote(self, kind: str, identifier: str) -> None:
        """Name an id the command wrote, for its `end` entry."""
        self._journal.wrote(kind, identifier)

    def replay_attempt(self, check_recorded):
        """The Attempt recorded under the `request_id`, after `check_recorded(recorded)`, or None for a new request.

        For a new request, a `request_id` that names a decision is refused, then the write sequence is checked.
        `check_recorded` is the writer's own check of a recorded Attempt: it raises, or returns.
        """
        recorded = layout.find_by_request(self.study, self.request_id)
        if recorded is not None:
            check_recorded(recorded)
            return recorded
        decision = decisions.find_by_request(self.study, self.request_id)
        if decision is not None:
            raise requests.conflict_with_a_decision(self.request_id, decision["decision_id"])
        write_journal.require_current(self.study, self.read_sequence)
        return None

    def replay_decision(self, check_recorded):
        """The decision recorded under the `request_id`, after `check_recorded(recorded)`, or None for a new request.

        For a new request, a `request_id` that names an Attempt is refused, then the write sequence is checked.
        """
        recorded = decisions.find_by_request(self.study, self.request_id)
        if recorded is not None:
            check_recorded(recorded)
            return recorded
        attempt = layout.find_by_request(self.study, self.request_id)
        if attempt is not None:
            raise requests.conflict_with_an_attempt(self.request_id, attempt["attempt_id"])
        write_journal.require_current(self.study, self.read_sequence)
        return None


@contextlib.contextmanager
def locked(study, command: str, request_id: str | None = None, *, read_sequence=None, has_attempt: bool = False):
    """Take the Study's writer lock and journal the command's writes; yield the `Write` of the command.

    `request_id` is None for a command that has none. `has_attempt` is true for a command that records an Attempt (`run`, `import`).
    """
    with lock.writer_lock(study), write_journal.writing(study, command, request_id, has_attempt=has_attempt) as journal:
        yield Write(study, request_id, read_sequence, journal)
