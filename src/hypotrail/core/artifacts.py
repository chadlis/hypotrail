"""Artifacts of a Study: ArtifactRef, safe paths, atomic publication, integrity on read-back.

An ArtifactRef is `{path, sha256, size_bytes, media_type, role}`: the path is relative to the
Study, the digest is of the bytes (SPEC §5, ID-02). A path that leaves the Study (`..`, an absolute
path) or that goes through a symlink pointing outside it is refused (`ARTIFACT_PATH_OUTSIDE_STUDY`),
for writing and for reading. A referenced artifact whose bytes no longer match its digest is an
integrity refusal, `ARTIFACT_INTEGRITY` (exit 3), raised before the bytes are used.

Publication is atomic: the bytes are written to a temporary file in the destination's directory
(so inside the Study and on the same filesystem), flushed and fsynced, then renamed onto the final
path with `os.replace`; the directory is fsynced. Nothing appears under the final path before the
rename. A published artifact is immutable: publishing other bytes under the same path is refused
(`ARTIFACT_IMMUTABLE`); the same bytes are accepted as already published.

An Attempt's folder (`attempts/<attempt_id>/`) is closed once its manifest is no longer `running`
(completed, failed or interrupted): a write that would change a file there, or add one, is refused
with `ATTEMPT_TERMINAL` (exit 3); republishing the same bytes changes nothing and is accepted.
While it runs, its manifest is replaced atomically (chadlis/hypotrail#65, SPEC §5).

The write helpers (`_fsync_dir`, the temporary-file-then-replace sequence of `publish_bytes`) are
adapted from `atomic_write` in `framework/mlkit/study/store.py` of `hypotrail/hypotrail` at commit
`4ef4925`, copied and owned here (chadlis/hypotrail#64, Tightened D); the Windows retry of that
source is not copied.
"""

import json
import os
import uuid
from pathlib import Path, PurePosixPath

from hypotrail.core import canonical
from hypotrail.core.errors import IntegrityError

TEMP_SUFFIX = ".tmp"


def _outside(path, study, reason):
    return IntegrityError(
        "ARTIFACT_PATH_OUTSIDE_STUDY",
        f"artifact path {path!r} {reason}",
        stage="artifact",
        details={"path": str(path), "study": str(study), "reason": reason},
    )


def resolve(study, relative) -> Path:
    """The absolute location of `relative` inside `study`; a path that escapes the Study is refused."""
    study = Path(study)
    text = str(relative)
    posix = PurePosixPath(text)
    if text == "" or posix.is_absolute() or "\\" in text or ".." in posix.parts or posix.parts in ((), (".",)):
        raise _outside(text, study, "is empty, absolute or leaves the Study")
    root = study.resolve()
    target = (root / posix).resolve()  # follows every symlink on the way
    if not target.is_relative_to(root):
        raise _outside(text, study, "goes through a symlink pointing outside the Study")
    return root / posix


def terminal_attempt(attempt_id, status, path) -> IntegrityError:
    return IntegrityError(
        "ATTEMPT_TERMINAL",
        f"Attempt {attempt_id} is {status}: its manifest and outputs can no longer change",
        stage="attempt",
        details={"attempt_id": attempt_id, "technical_status": status, "path": str(path)},
    )


def _refuse_if_terminal(study, relative) -> None:
    """Refuse a write into the folder of an Attempt whose manifest is not `running`."""
    parts = PurePosixPath(str(relative)).parts
    if len(parts) < 3 or parts[0] != "attempts":
        return
    manifest = resolve(study, "/".join(parts[:2]) + "/attempt.json")
    if not manifest.is_file():
        return
    status = json.loads(manifest.read_text(encoding="utf-8")).get("technical_status")
    if status != "running":
        raise terminal_attempt(parts[1], status, relative)


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _ref(relative, data: bytes, media_type, role) -> dict:
    return {
        "path": PurePosixPath(str(relative)).as_posix(),
        "sha256": canonical.sha256_hex(data),
        "size_bytes": len(data),
        "media_type": media_type,
        "role": role,
    }


def _immutable(target: Path, relative, data: bytes) -> bool:
    """True when `target` already holds exactly `data`; other existing bytes are refused."""
    if not target.exists():
        return False
    if target.read_bytes() == data:
        return True
    raise IntegrityError(
        "ARTIFACT_IMMUTABLE",
        f"{relative} is published and cannot be replaced with other bytes",
        stage="artifact",
        details={"path": str(relative)},
    )


def _write_atomically(target: Path, data: bytes) -> None:
    """Temporary file beside `target` (inside the Study), flushed, fsynced, then renamed onto it."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}{TEMP_SUFFIX}")
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    _fsync_dir(target.parent)


def publish_bytes(study, relative, data: bytes, *, media_type: str, role: str) -> dict:
    """Publish `data` at `relative` atomically; return its ArtifactRef."""
    target = resolve(study, relative)
    if not (target.exists() and target.read_bytes() == data):
        _refuse_if_terminal(study, relative)
    if not _immutable(target, relative, data):
        target.parent.mkdir(parents=True, exist_ok=True)
        resolve(study, relative)  # the directories just created are checked again
        _write_atomically(target, data)
    return _ref(relative, data, media_type, role)


def replace_bytes(study, relative, data: bytes) -> None:
    """Replace a file that is allowed to change (a running manifest) atomically; no ArtifactRef."""
    _refuse_if_terminal(study, relative)
    _write_atomically(resolve(study, relative), data)


def publish_file(study, source: Path, relative, *, media_type: str, role: str) -> dict:
    """Publish a file already written inside the Study (a scratch file of a library writer)."""
    return publish_bytes(study, relative, Path(source).read_bytes(), media_type=media_type, role=role)


def publish_record(study, relative, record, *, role: str) -> dict:
    """Publish `record` as canonical JSON; a value that is not canonical writes nothing."""
    return publish_bytes(study, relative, canonical.dumps(record), media_type="application/json", role=role)


def read_verified(study, ref: dict) -> bytes:
    """The bytes of a referenced artifact, once their digest and size match the reference."""
    path = resolve(study, ref["path"])
    details = {"path": ref["path"], "expected_sha256": ref["sha256"]}
    if not path.is_file():
        raise IntegrityError(
            "ARTIFACT_MISSING", f"referenced artifact missing: {ref['path']}", stage="artifact", details=details
        )
    data = path.read_bytes()
    actual = canonical.sha256_hex(data)
    if actual != ref["sha256"] or len(data) != ref["size_bytes"]:
        raise IntegrityError(
            "ARTIFACT_INTEGRITY",
            f"{ref['path']} does not match its reference",
            stage="artifact",
            details={**details, "actual_sha256": actual, "expected_size_bytes": ref["size_bytes"], "actual_size_bytes": len(data)},
        )
    return data


def ref_of_existing(study, relative, *, media_type: str, role: str) -> dict:
    """The ArtifactRef of a file already inside the Study, from its bytes."""
    return _ref(relative, resolve(study, relative).read_bytes(), media_type, role)
