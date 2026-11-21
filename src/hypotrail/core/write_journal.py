"""The write journal of a Study, and the write sequence it gives (chadlis/hypotrail#107, slice #104).

A Study keeps a write sequence: a value that every write to the Study advances and that nothing else changes. It is the number of
entries of an append-only journal, `write_journal/<n>.json` (`n` is the entry's position, from 1, `%06d`). An entry is never
rewritten. `status --json` shows the value as the top-level key `write_sequence` (it takes no lock and writes nothing).

Every command that writes appends two entries (D-033 on chadlis/hypotrail#75, amended by D-034 on chadlis/hypotrail#75):

- a `begin` entry just before its first write: `phase`, `command` and `request_id` (null for a command without one);
- an `end` entry after its last write: `phase`, `command`, `request_id`, `outcome` and `written`, the ids written as
  `[{"kind", "id"}]`. `outcome` is `completed` (the command wrote what it set out to write), `refused` (a coded refusal stopped
  it after its first write) or `failed` (D-035 on chadlis/hypotrail#75, amended by D-036 on chadlis/hypotrail#75 and D-037 on chadlis/hypotrail#75). A reader does not treat that list as closed.

A command refused before its first write appends nothing: a replay, `STUDY_LOCKED`, `REQUEST_CONFLICT`, `PROTOCOL_CHANGED`, a
refusal of its arguments or of the ids a `decide` cites, and a `report` whose page shows `dev` Items only. A writer killed between its two entries leaves the
`begin` entry only: a killed writer has still written. A Study written before this slice holds no journal and shows 0.

A command that is given the write sequence its author read (`--read-sequence`, chadlis/hypotrail#108, D-033 on chadlis/hypotrail#75,
amended by D-034 on chadlis/hypotrail#75) compares it with the Study's under the writer lock, by `require_current(...)`: a value below the Study's is
`STUDY_CHANGED` (exit 6, stage `sequence`, `details` `read_sequence`, `write_sequence` and `writes_since`, the journal entries after
the value read), a value above it `WRITE_SEQUENCE_AHEAD` (exit 2, stage `sequence`, `details` `read_sequence` and `write_sequence`).
Either refusal comes before the command's first write, so it appends nothing.

One rule in one place: every writer wraps its locked work in `writing(...)`, calls `begin()` just before its first write, and
names what it wrote with `wrote(...)` (or `attempt(...)` for an Attempt and its Observation set). `writing` appends the `end`
entry once the block ends, however it ends. The caller holds the Study's writer lock, so the position of an entry is the count
of entries plus one.
"""

import contextlib
import contextvars
from pathlib import Path

from hypotrail.core import artifacts, contracts
from hypotrail.core import study as layout
from hypotrail.core.errors import EXIT_INFRASTRUCTURE, EXIT_LOCK_OR_CONFLICT, HypotrailError, InvalidInputError, coded_error

JOURNAL_DIR = "write_journal"
BEGIN, END = "begin", "end"
COMPLETED, REFUSED, FAILED = "completed", "refused", "failed"
SEQUENCE_STAGE = "sequence"

_active = contextvars.ContextVar("write_journal_session", default=None)


def write_sequence(study) -> int:
    """The write sequence of the Study: the number of entries of its journal (0 for a Study written before the journal)."""
    return len(layout.record_names(study, JOURNAL_DIR))


def entries(study) -> list:
    """The journal's entries, in the order they were appended."""
    return layout.read_records(study, JOURNAL_DIR)


def read_sequence_fault(read_sequence) -> str | None:
    """Why `read_sequence` is not a value of `--read-sequence`, or None: the one rule, and its one message, of the command line and of the library.

    A value is a non-negative integer (a boolean is not one). `None` (not given) is not a fault.
    """
    if read_sequence is None:
        return None
    if isinstance(read_sequence, bool) or not isinstance(read_sequence, int) or read_sequence < 0:
        return f"--read-sequence takes a non-negative integer, not {read_sequence!r}"
    return None


def invalid_arguments(message: str, command: str) -> InvalidInputError:
    """An `INVALID_ARGUMENTS` refusal as the command line gives it: `details` `{"command"}` is the parser's `prog`, `hypotrail <command>`. The one place the core builds it."""
    return InvalidInputError("INVALID_ARGUMENTS", message, stage="config", details={"command": f"hypotrail {command}"})


def require_valid_read_sequence(read_sequence, command: str) -> None:
    """Refuse a `read_sequence` that `read_sequence_fault` names, as the command line does (`INVALID_ARGUMENTS`, exit 2): the first argument check of a writer, before any lock.

    `command` is the command's name as the command line shows it (`details` `{"command"}` is then the one the parser gives).
    """
    fault = read_sequence_fault(read_sequence)
    if fault is not None:
        raise invalid_arguments(fault, command)


def require_current(study, read_sequence) -> None:
    """Refuse a write made on a write sequence that is not the Study's: the caller holds the writer lock. `None` (not given) is never refused."""
    if read_sequence is None:
        return
    current = write_sequence(study)
    if read_sequence > current:
        raise InvalidInputError(
            "WRITE_SEQUENCE_AHEAD",
            f"the write sequence read ({read_sequence}) is above the Study's ({current}); nothing was written",
            stage=SEQUENCE_STAGE,
            details={"read_sequence": read_sequence, "write_sequence": current},
        )
    if read_sequence < current:
        raise HypotrailError(
            "STUDY_CHANGED",
            f"the Study was written to after the write sequence read ({read_sequence}): it is at {current}; nothing was written (read it again)",
            stage=SEQUENCE_STAGE,
            details={"read_sequence": read_sequence, "write_sequence": current, "writes_since": entries(study)[read_sequence:]},
            exit_code=EXIT_LOCK_OR_CONFLICT,
        )


def _append(study, entry: dict) -> None:
    contracts.validate(entry)
    position = write_sequence(study) + 1
    artifacts.publish_record(study, f"{JOURNAL_DIR}/{position:06d}.json", entry, role="write_journal")


class _Session:
    """What one writing command has done so far, for its `end` entry."""

    def __init__(self, study, command: str, request_id):
        self.study, self.command, self.request_id = Path(study), command, request_id
        self.begun = False
        self.written: list = []
        self.attempt_id = None

    def begin(self) -> None:
        """Append the `begin` entry, once: call it just before the command's first write."""
        if not self.begun:
            _append(self.study, {"phase": BEGIN, "command": self.command, "request_id": self.request_id})
            self.begun = True

    def wrote(self, kind: str, identifier: str) -> None:
        item = {"kind": kind, "id": identifier}
        if item not in self.written:
            self.written.append(item)

    def _written(self) -> list:
        """The ids written: an Attempt, and its Observation set once the Attempt published one."""
        found = list(self.written)
        if self.attempt_id is not None:
            try:
                manifest = layout.read_manifest(self.study, self.attempt_id)
            except Exception:
                return found  # the Attempt's manifest was never written: nothing is named
            found.insert(0, {"kind": "attempt", "id": self.attempt_id})
            for ref in manifest.get("output_refs", []):
                if ref["role"] == "observation_set":
                    found.append({"kind": "observation_set", "id": layout.read_record(self.study, ref["path"])["observation_set_id"]})
        return found

    def end(self, outcome: str) -> None:
        _append(
            self.study,
            {"phase": END, "command": self.command, "request_id": self.request_id, "outcome": outcome, "written": self._written()},
        )


def _session() -> _Session:
    session = _active.get()
    if session is None:
        raise RuntimeError("a write to a Study is made inside write_journal.writing(...)")
    return session


def begin() -> None:
    """Append the `begin` entry of the command that is writing, once: call it just before its first write."""
    _session().begin()


def wrote(kind: str, identifier: str) -> None:
    """Name an id the command wrote, for its `end` entry."""
    _session().wrote(kind, identifier)


def attempt(attempt_id: str) -> None:
    """Name the Attempt the command writes: its `end` entry names the Attempt and, once it exists, its Observation set."""
    _session().attempt_id = attempt_id


def _outcome_of(error: Exception, has_attempt: bool) -> str:
    """`failed` for any error of a command that leaves an Attempt, and for a technical error (exit 4); else `refused` (D-037 on chadlis/hypotrail#75)."""
    if has_attempt or coded_error(error).exit_code == EXIT_INFRASTRUCTURE:
        return FAILED
    return REFUSED


@contextlib.contextmanager
def writing(study, command: str, request_id=None, *, has_attempt: bool = False):
    """Journal the command's writes: the caller holds the writer lock. Nothing is appended unless `begin()` is called.

    `has_attempt` is true for a command that records an Attempt (`run`, `import`): any error after its `begin` leaves a `failed`
    Attempt, so its outcome is `failed` whatever the exit code.
    """
    session = _Session(study, command, request_id)
    token = _active.set(session)
    try:
        yield session
    except Exception as error:
        if session.begun:
            with contextlib.suppress(Exception):  # the error that stopped the command is the one that is raised
                session.end(_outcome_of(error, has_attempt))
        raise
    else:
        if session.begun:
            session.end(COMPLETED)
    finally:
        _active.reset(token)
