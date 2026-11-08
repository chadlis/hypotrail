"""The writer lock of a Study: one writer at a time, a second one is refused at once.

Every command that writes to a Study holds an exclusive, non-blocking `flock` on
`<study>/writer.lock` for the whole command. A second writer does not wait: it is refused with
`STUDY_LOCKED` (exit 6, stage `lock`) and writes nothing. The operating system releases the lock
when its holder exits, however it exits, so a killed writer never blocks the Study; and that the
lock is gone proves nothing about a remote call the dead writer may have made (SPEC §5): an
Attempt is `interrupted` only by the explicit `recover`, which keeps `outcome_unknown`.

The lock file stays empty: taking the lock never writes to the Study. `is_held` is the read-only
probe `status` uses: a non-blocking shared lock, taken and dropped at once. It fails only while a
writer holds the exclusive lock; for that instant a writer arriving at the same moment is refused
too, which is a refusal that writes nothing.

The mechanism (an exclusive `flock` released by the operating system when the process ends, and a
shared non-blocking `flock` as the read-only liveness probe) is adapted from `writer_lock` and
`lease_is_held` in `framework/mlkit/study/lock.py` of `hypotrail/hypotrail` at commit `4ef4925`,
copied and owned here (chadlis/hypotrail#65; #64 Tightened D). Not copied: waiting with a timeout,
the holder record, execution leases and the Windows backend; a platform without `fcntl` is refused
with `LOCKING_UNAVAILABLE`.
"""

import contextlib
import errno
import os
from pathlib import Path

from hypotrail.core import artifacts
from hypotrail.core.errors import EXIT_CAPABILITY_UNAVAILABLE, EXIT_LOCK_OR_CONFLICT, HypotrailError

LOCK_FILE = "writer.lock"
_BUSY = (errno.EAGAIN, errno.EACCES)


def _load_fcntl():
    import fcntl

    return fcntl


def _fcntl():
    try:
        return _load_fcntl()
    except ImportError:
        raise HypotrailError(
            "LOCKING_UNAVAILABLE",
            "this platform has no file locking (fcntl): a Study cannot admit a writer here",
            stage="lock",
            details={"platform": os.name},
            exit_code=EXIT_CAPABILITY_UNAVAILABLE,
        ) from None


def _locked(study) -> HypotrailError:
    return HypotrailError(
        "STUDY_LOCKED",
        f"another process is writing to the Study {study}; nothing was written (retry when it has finished)",
        stage="lock",
        details={"study": str(study)},
        exit_code=EXIT_LOCK_OR_CONFLICT,
    )


@contextlib.contextmanager
def writer_lock(study):
    """Hold the Study's writer lock for the block; refuse at once when another writer holds it."""
    fcntl = _fcntl()
    path = artifacts.resolve(study, LOCK_FILE)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in _BUSY:
                raise _locked(study) from None
            raise
        yield
    finally:
        os.close(descriptor)  # closing releases the lock


def is_held(study) -> bool:
    """True while a live writer holds the Study's lock. Read-only: it creates and writes nothing."""
    fcntl = _fcntl()
    path = Path(artifacts.resolve(study, LOCK_FILE))
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in _BUSY:
                return True
            raise
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    finally:
        os.close(descriptor)
