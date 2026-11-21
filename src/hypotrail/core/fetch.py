"""Acquisition of a Workload's public sources against its lock (`data fetch`, SPEC DATA-02).

Standard library only. Each file is downloaded to a temporary file in the directory it will be published in, its size
is bounded while it arrives, its SHA-256 is checked against the lock, and only then is it published by an atomic
rename. The order of the command is fixed: the lock and every path are checked first (exit 2, nothing written, no
connection), then the destination files already there (a matching one is left, a differing one is refused), and only
then the network.

There is no mirror: a request starts only from the lock's `download_url` (or `notice_url`), and the command never chooses
another URL. The redirects that URL answers with are followed (D-019 on chadlis/hypotrail#75), at most `MAX_REDIRECTS` hops and https only: a
downgrade to http or one hop more is a failed transfer, with no fallback. No host is allowlisted in the code: the lock's
SHA-256 is the only acceptance gate, and the timeout and the size bound apply to the file that finally arrives. A failed
transfer is a coded error that names the already verified bundle and reports the final host, never a URL or its query.
"""

import hashlib
import http.client
import json
import os
import re
import secrets
import stat
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from hypotrail.core.errors import (
    EXIT_INFRASTRUCTURE,
    HypotrailError,
    IntegrityError,
    InvalidInputError,
)

SUPPORTED_SCHEMA = "data-sources/1"

# The one cap on any download whose lock gives no size (an archive, a notice). It names no Workload (ADR 0002).
GENERIC_CAP_BYTES = 64 * 1024 * 1024

CHUNK_BYTES = 64 * 1024
TIMEOUT_SECONDS = 30

_SHA256 = re.compile(r"[0-9a-f]{64}")


# D-019 on chadlis/hypotrail#75: redirects are followed up to this many hops, and only to these schemes.
MAX_REDIRECTS = 5
REDIRECT_SCHEMES = ("https",)


class _RedirectRefused(Exception):
    def __init__(self, reason: str, url: str):
        super().__init__(reason)
        self.reason, self.url = reason, url


def host_of(url: str) -> str:
    """The host (and port, if any) of a URL: all that an error reports of it; never a path, a query or credentials."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    return f"{host}:{parts.port}" if parts.port else host


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def __init__(self):
        self.current = None

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        hops = len(getattr(req, "redirect_dict", {}))  # the redirects already followed for this request
        if urllib.parse.urlsplit(newurl).scheme.lower() not in REDIRECT_SCHEMES:
            raise _RedirectRefused("redirect_downgrade", newurl)
        if hops >= MAX_REDIRECTS:
            raise _RedirectRefused("too_many_redirects", newurl)
        self.current = newurl
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url: str):
    """Open one URL, following redirects under D-019 on chadlis/hypotrail#75. Tests replace this function; nothing else in the module touches the network."""
    request = urllib.request.Request(url, headers={"User-Agent": "hypotrail-data-fetch"})
    redirects = _Redirects()
    try:
        return urllib.request.build_opener(redirects).open(request, timeout=TIMEOUT_SECONDS)
    except _RedirectRefused:
        raise
    except Exception as error:
        error.final_host = host_of(redirects.current or url)  # where the request was when it failed
        raise


# --- the lock -----------------------------------------------------------------------------------------------


def _invalid(key: str, lock_path: Path, what: str) -> InvalidInputError:
    return InvalidInputError(
        "LOCK_INVALID",
        f"the lock lacks a usable {key} ({what}): nothing was downloaded",
        stage="config",
        details={"file": str(lock_path), "key": key},
    )


def _read_lock(lock_path: Path) -> list[dict]:
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InvalidInputError("FILE_NOT_FOUND", f"lock not found: {lock_path}", stage="config", details={"file": str(lock_path)}) from None
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise InvalidInputError(
            "FILE_NOT_JSON",
            f"lock is not valid JSON: {lock_path}",
            stage="config",
            details={"file": str(lock_path), "line": getattr(error, "lineno", None)},
        ) from None
    if not isinstance(lock, dict):
        raise _invalid("schema_version", lock_path, "the lock is not a JSON object")
    version = lock.get("schema_version")
    if not isinstance(version, str):
        raise _invalid("schema_version", lock_path, "missing")
    if version != SUPPORTED_SCHEMA:
        raise InvalidInputError(
            "LOCK_SCHEMA_UNKNOWN",
            f"the lock's schema_version is {version!r}; this command reads {SUPPORTED_SCHEMA!r}: nothing was downloaded",
            stage="config",
            details={"file": str(lock_path), "schema_version": version, "supported": SUPPORTED_SCHEMA},
        )
    sources = lock.get("sources")
    if not isinstance(sources, list) or not sources:
        raise _invalid("sources", lock_path, "a non-empty list")
    return [_source(position, entry, lock_path) for position, entry in enumerate(sources)]


def _source(position: int, entry, lock_path: Path) -> dict:
    where = f"sources[{position}]"

    def text(key):
        value = entry.get(key) if isinstance(entry, dict) else None
        if not isinstance(value, str) or not value:
            raise _invalid(f"{where}.{key}", lock_path, "a non-empty string")
        return value

    def digest(key):
        value = text(key)
        if not _SHA256.fullmatch(value):
            raise _invalid(f"{where}.{key}", lock_path, "a lowercase SHA-256 in hexadecimal")
        return value

    if not isinstance(entry, dict):
        raise _invalid(where, lock_path, "an object")
    source = {"where": where, "dataset_id": text("dataset_id"), "local_path": text("local_path"), "sha256": digest("sha256")}
    source["download_url"] = _http_url(text("download_url"), f"{where}.download_url", lock_path)
    size = entry.get("size_bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise _invalid(f"{where}.size_bytes", lock_path, "a positive integer")
    source["size_bytes"] = size
    source["archive_sha256"] = source["member"] = None
    if "archive_sha256" in entry or "member" in entry:  # one without the other is not an archive
        source["archive_sha256"], source["member"] = digest("archive_sha256"), text("member")
    named = entry.get("notice")  # reported when there is no URL to fetch it from; never written then
    source["notice"] = named if isinstance(named, str) else None
    source["notice_url"] = source["notice_sha256"] = None
    if "notice_url" in entry:
        source["notice_url"] = _http_url(text("notice_url"), f"{where}.notice_url", lock_path)
        source["notice"], source["notice_sha256"] = text("notice"), digest("notice_sha256")
    return source


def _http_url(url: str, key: str, lock_path: Path) -> str:
    if not re.match(r"https?://[^/\s]+", url):
        raise _invalid(key, lock_path, "an http or https URL")
    return url


# --- the paths ----------------------------------------------------------------------------------------------


def _outside(key: str, path: str, reason: str) -> InvalidInputError:
    return InvalidInputError(
        "PATH_OUTSIDE_DEST",
        f"{key} {path!r} would leave the destination ({reason}): nothing was downloaded or written",
        stage="config",
        details={"key": key, "path": path, "reason": reason},
    )


def _guard_relative(key: str, path: str) -> None:
    """A path of the lock that is written under `--dest` is relative and has no `..`; a member is a name only inside an archive, held to the same rule."""
    if "\x00" in path or PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute():
        raise _outside(key, path, "absolute")
    if ".." in PurePosixPath(path.replace("\\", "/")).parts:
        raise _outside(key, path, "parent_reference")


def _guard_destination(dest: Path, key: str, path: str) -> Path:
    """The path the file is published at; refused when it passes through a link that leads outside `--dest`."""
    root = Path(os.path.realpath(dest))
    target = dest / path
    if not Path(os.path.realpath(target)).is_relative_to(root):
        raise _outside(key, path, "link_outside")
    return target


def _plan(sources: list[dict], dest: Path) -> list[dict]:
    if dest.exists() and not dest.is_dir():
        raise InvalidInputError(
            "DEST_NOT_A_DIRECTORY", f"--dest is not a directory: {dest}", stage="config", details={"dest": str(dest)}
        )
    for source in sources:
        where = source["where"]
        _guard_relative(f"{where}.local_path", source["local_path"])
        if source["member"] is not None:
            _guard_relative(f"{where}.member", source["member"])
        if source["notice_url"] is not None:
            _guard_relative(f"{where}.notice", source["notice"])
    for source in sources:
        where = source["where"]
        source["target"] = _guard_destination(dest, f"{where}.local_path", source["local_path"])
        if source["notice_url"] is not None:
            source["notice_target"] = _guard_destination(dest, f"{where}.notice", source["notice"])
    return sources


# --- what is already there ----------------------------------------------------------------------------------


def _present(path: Path, expected_sha256: str, expected_size: int | None, file: str) -> bool:
    """True when the file at `path` matches the lock, False when there is none; a file that differs is refused, never replaced."""
    if not os.path.lexists(path):
        return False
    actual_sha256 = actual_size = None
    if path.is_file():
        actual_size = path.stat().st_size
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        actual_sha256 = digest.hexdigest()
        if actual_sha256 == expected_sha256 and (expected_size is None or actual_size == expected_size):
            return True
    raise IntegrityError(
        "DEST_FILE_DIFFERS",
        f"{file} already exists and does not match the lock: it is left as it is and never replaced "
        "(to acquire it again, remove it first); nothing was downloaded",
        stage="integrity",
        details={"file": file, "expected_sha256": expected_sha256, "actual_sha256": actual_sha256},
    )


# --- one download -------------------------------------------------------------------------------------------


class _Temporary:
    """A temporary file in the directory its content will be published in; gone unless it was renamed away."""

    def __init__(self, target: Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        self.path = target.parent / f".{target.name}.{secrets.token_hex(6)}.part"
        self.handle = os.fdopen(os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666), "wb")

    def publish(self, target: Path) -> None:
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.handle.close()
        os.replace(self.path, target)
        self.path = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if not self.handle.closed:
            self.handle.close()
        if self.path is not None:
            self.path.unlink(missing_ok=True)


# The explicit alternative every refusal of a download names (#22 C6): the one place its words are written.
VERIFIED_BUNDLE = "the already verified bundle is the explicit alternative: run `data verify` on the committed data"


def _failed(file: str, host: str, reason: str, status: int | None = None) -> HypotrailError:
    return HypotrailError(
        "DOWNLOAD_FAILED",
        f"could not download {file} (host {host}: {reason}); nothing was published and no other source is tried; {VERIFIED_BUNDLE}",
        stage="download",
        details={"file": file, "host": host, "reason": reason, "status": status},
        exit_code=EXIT_INFRASTRUCTURE,
    )


def _too_large(file: str, what: str, bound: int) -> IntegrityError:
    return IntegrityError(
        "DOWNLOAD_TOO_LARGE",
        f"the {what} of {file} grew past its bound of {bound} bytes: it was stopped and nothing was published",
        stage="integrity",
        details={"file": file, "what": what, "bound_bytes": bound},
    )


@dataclass(frozen=True)
class _Outcome:
    """What one transfer (or one extraction) came to, computed once; `_check` decides from it and from the lock's expected SHA-256."""

    file: str
    what: str  # "file", "archive", "notice" or "member"
    host: str | None  # the final host of a transfer
    framing: str | None  # as `http.client` computed it: "chunked", "length" (it set a length), "unframed" (neither); None for a member
    announced: int | None  # the length `http.client` set, when it set one
    received: int  # bytes that arrived
    lock_size: int | None  # the lock's size_bytes for this body, or None where the lock gives none (the archive, a notice)
    sha256: str  # of the bytes that arrived


def _check(outcome: _Outcome, expected_sha256: str) -> None:
    """The one table from an outcome to its refusal; return when the body is whole and equal to the lock.

    Exits are those of #22 C4, C6, H, J and K. In order:
    - a body framed by a length (the one `http.client` set) that delivered fewer bytes is a cut transfer (`DOWNLOAD_FAILED`,
      `interrupted`, exit 4);
    - an unframed body (`http.client` set no length and the body is not chunked, so the close delimits it) shorter than the lock's `size_bytes` is a cut transfer too (D-020 on
      chadlis/hypotrail#75, #22 Tightened K); only `received < size_bytes` triggers it;
    - a different SHA-256 is `DOWNLOAD_INTEGRITY`, exit 3, and so is the same SHA-256 with a different size;
    - the hint that a server may have cut the body short is given only where HTTP cannot tell that from a differing body: an
      unframed transfer whose lock gives no size.
    """
    o = outcome
    if o.framing == "length" and o.received != o.announced:
        raise _failed(o.file, o.host, "interrupted")
    if o.framing == "unframed" and o.lock_size is not None and o.received < o.lock_size:
        raise _failed(o.file, o.host, "interrupted")
    hash_differs = o.sha256 != expected_sha256
    if not hash_differs and (o.lock_size is None or o.received == o.lock_size):
        return
    if hash_differs:
        differs = f"does not match the lock (expected sha256 {expected_sha256}, got {o.sha256})"
    else:
        differs = f"does not match the lock: its size is {o.received} bytes and the lock says {o.lock_size} bytes (the sha256 matches)"
    hint = "; a body that a server cut short without announcing a length cannot be told from a differing one here" if o.framing == "unframed" and o.lock_size is None else ""
    raise IntegrityError(
        "DOWNLOAD_INTEGRITY",
        f"the {o.what} of {o.file} {differs}: nothing was published{hint}; {VERIFIED_BUNDLE}",
        stage="integrity",
        details={
            "file": o.file,
            "what": o.what,
            "expected_sha256": expected_sha256,
            "actual_sha256": o.sha256,
            "size_bytes": o.lock_size,  # the lock's, or None
            "actual_size_bytes": o.received,
        },
    )


def _transfer(url: str, file: str, what: str, bound: int, temporary: _Temporary, lock_size: int | None = None) -> _Outcome:
    """Write the body of `url` to the temporary file, stopping as soon as it passes `bound`; return what arrived.

    A read that fails (a reset, a timeout, a chunked body that ends before its last chunk) is a cut transfer at once; every other
    judgement is `_check`'s, made on the returned outcome.
    """
    try:
        response = open_url(url)
    except _RedirectRefused as error:
        raise _failed(file, host_of(error.url), error.reason) from None
    except urllib.error.HTTPError as error:
        raise _failed(file, getattr(error, "final_host", host_of(url)), "http_status", error.code) from None
    except (OSError, ValueError) as error:  # unreachable host, refused or timed-out connection, malformed URL
        raise _failed(file, getattr(error, "final_host", host_of(url)), "unreachable") from None
    digest, total = hashlib.sha256(), 0
    host = host_of(response.geturl()) if hasattr(response, "geturl") else host_of(url)  # the final host, after any redirect
    with response:
        # The framing is the one `http.client` computed (#22 L), read before the first read because `length` counts down as the body
        # arrives. It reads a chunked body as chunked and ignores a Content-Length on it, one it cannot parse as an integer, or a
        # negative one. No header is parsed here.
        chunked, announced = response.chunked, response.length
        if announced is not None and announced > bound:
            raise _too_large(file, what, bound)
        while True:
            try:
                block = response.read(CHUNK_BYTES)
            except (OSError, http.client.HTTPException):  # a connection reset, a timeout, an incomplete read
                raise _failed(file, host, "interrupted") from None
            if not block:
                break
            total += len(block)
            if total > bound:
                raise _too_large(file, what, bound)
            digest.update(block)
            temporary.handle.write(block)
    framing = "chunked" if chunked else "length" if announced is not None else "unframed"
    return _Outcome(file, what, host, framing, announced, total, lock_size, digest.hexdigest())


def _fetch_file(url: str, target: Path, file: str, sha256: str, size: int | None, what: str) -> None:
    """Download `url` and publish it at `target`: temporary file, bound, hash (and size), atomic rename."""
    bound = GENERIC_CAP_BYTES if size is None else size
    with _Temporary(target) as temporary:
        _check(_transfer(url, file, what, bound, temporary, size), sha256)
        temporary.publish(target)


def _member_refused(file: str, member: str, reason: str) -> IntegrityError:
    return IntegrityError(
        "ARCHIVE_MEMBER_REFUSED",
        f"the archive's {member!r} cannot be extracted ({reason}): nothing was published",
        stage="integrity",
        details={"file": file, "member": member, "reason": reason},
    )


def _fetch_member(source: dict, target: Path, file: str) -> None:
    """Download the archive, check it against `archive_sha256`, and only then open it to extract the one `member`."""
    member = source["member"]
    with _Temporary(target) as archive:
        _check(_transfer(source["download_url"], file, "archive", GENERIC_CAP_BYTES, archive), source["archive_sha256"])
        archive.handle.flush()
        try:
            with zipfile.ZipFile(archive.path) as zipped:
                try:
                    info = zipped.getinfo(member)
                except KeyError:
                    raise _member_refused(file, member, "missing") from None
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise _member_refused(file, member, "link")
                if info.is_dir() or (mode and not stat.S_ISREG(mode)):
                    raise _member_refused(file, member, "not_a_file")
                bound = source["size_bytes"]
                with _Temporary(target) as extracted, zipped.open(info) as stream:
                    digest, total = hashlib.sha256(), 0
                    for block in iter(lambda: stream.read(CHUNK_BYTES), b""):
                        total += len(block)
                        if total > bound:  # the member is bounded by the lock whatever its header says
                            raise _too_large(file, "member", bound)
                        digest.update(block)
                        extracted.handle.write(block)
                    _check(_Outcome(file, "member", None, None, None, total, bound, digest.hexdigest()), source["sha256"])
                    extracted.publish(target)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError):
            raise _member_refused(file, member, "unreadable") from None


# --- the command --------------------------------------------------------------------------------------------


def fetch(lock_path: Path | str, dest: Path | str) -> list[dict]:
    """Acquire every source of the lock under `dest`; return one report per source."""
    lock_path, dest = Path(lock_path), Path(dest)
    sources = _plan(_read_lock(lock_path), dest)
    # what is already there, before any connection: a differing file refuses the whole command
    for source in sources:
        source["data_present"] = _present(source["target"], source["sha256"], source["size_bytes"], source["local_path"])
        source["notice_present"] = (
            _present(source["notice_target"], source["notice_sha256"], None, source["notice"]) if source["notice_url"] else None
        )
    reports = []
    for source in sources:
        if not source["data_present"]:
            if source["member"] is None:
                _fetch_file(source["download_url"], source["target"], source["local_path"], source["sha256"], source["size_bytes"], "file")
            else:
                _fetch_member(source, source["target"], source["local_path"])
        notice = {"file": source["notice"], "status": "absent"}
        if source["notice_url"] is not None:
            if not source["notice_present"]:
                _fetch_file(source["notice_url"], source["notice_target"], source["notice"], source["notice_sha256"], None, "notice")
            notice = {"file": source["notice"], "status": "present" if source["notice_present"] else "fetched"}
        reports.append(
            {
                "dataset_id": source["dataset_id"],
                "file": source["local_path"],
                "status": "present" if source["data_present"] else "fetched",
                "sha256": source["sha256"],
                "size_bytes": source["size_bytes"],
                "notice": notice,
            }
        )
    return reports
