"""The code environment of an Attempt: Python, the dependency lock and the code revision (SPEC §5, ID-03).

`code_environment()` returns `{python, dependency_lock, code_revision}`:

- `python`: the interpreter's version;
- `dependency_lock`: the path and sha256 of `uv.lock` (null when the repository is not around the code);
- `code_revision`: the commit, whether the code is dirty and, when it is (or when there is no
  commit to name), a fingerprint of the local code. "The code" is `src/`, `pyproject.toml` and
  `uv.lock` of the repository: a modified test or document does not make a result's code dirty.

It never reads the process environment, so no provider secret can reach a record.
"""

import platform
import subprocess
from pathlib import Path

from hypotrail.core import canonical

CODE_PATHS = ("src", "pyproject.toml", "uv.lock")
LOCK_NAME = "uv.lock"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _git(root: Path, *arguments: str):
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *arguments], capture_output=True, check=False, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _code_files(root: Path) -> list[str]:
    listed = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *CODE_PATHS)
    if listed is not None:
        return sorted(name for name in listed.decode("utf-8").split("\0") if name)
    return sorted(  # no git around the code: every file of the package and the lock files that exist
        p.relative_to(root).as_posix()
        for target in CODE_PATHS
        for p in ([root / target] if (root / target).is_file() else (root / target).rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    )


def local_code_fingerprint(root: Path | None = None) -> str:
    """The digest of the paths and bytes of the code, as it is on disk."""
    root = root or repository_root()
    files = [
        [name, canonical.sha256_hex((root / name).read_bytes())]
        for name in _code_files(root)
        if (root / name).is_file()
    ]
    return canonical.digest(files)


def code_revision(root: Path | None = None) -> dict:
    """`{commit, dirty, local_code_fingerprint}`; the fingerprint is null for a clean tree at a commit."""
    root = root or repository_root()
    head = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain", "--untracked-files=all", "--", *CODE_PATHS)
    commit = head.decode().strip() if head else None
    dirty = True if status is None else bool(status.strip())  # the state of unknown code is never "clean"
    return {
        "commit": commit,
        "dirty": dirty,
        "local_code_fingerprint": local_code_fingerprint(root) if (dirty or commit is None) else None,
    }


def code_environment(root: Path | None = None) -> dict:
    root = root or repository_root()
    lock = root / LOCK_NAME
    return {
        "python": platform.python_version(),
        "dependency_lock": {
            "path": LOCK_NAME,
            "sha256": canonical.sha256_hex(lock.read_bytes()) if lock.is_file() else None,
        },
        "code_revision": code_revision(root),
    }
