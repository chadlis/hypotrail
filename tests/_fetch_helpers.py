"""Helpers of the `data fetch` tests (#22): a stand-in server on the loopback interface, test locks, and one provoker of every refusal.

No test here reaches a real host: every `download_url` of a test lock names the stand-in, the hosts the real locks name appear
only as `landing_url` (never opened), and the network guard of `conftest.py` stays on.
"""

import hashlib
import io
import json
import shutil
import stat
import threading
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from hypotrail import cli

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


def fetch(lock, dest, *flags):
    """Run `data fetch --json`; return (exit code, the one JSON object on stdout, stderr)."""
    code, out, err = run_cli("data", "fetch", "--lock", str(lock), "--dest", str(dest), "--json", *flags)
    return code, json.loads(out), err


class Stand:
    """A stand-in server: `routes` maps a path to a body (200), an int (that status), or a callable `(handler) -> None`."""

    def __init__(self):
        self.routes, self.requests = {}, []
        stand = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                stand.requests.append(self.path)
                route = stand.routes.get(self.path, 404)
                if callable(route):
                    return route(self)
                if isinstance(route, int):
                    self.send_response(route)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(route)))
                self.end_headers()
                self.wfile.write(route)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def url(self, path):
        return self.base + path

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def cut_after(body: bytes, sent: int):
    """A route that announces the whole body, sends `sent` bytes of it and closes the connection."""

    def route(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body[:sent])
        handler.wfile.flush()
        handler.close_connection = True

    return route


def cut_chunked(body: bytes, sent: int):
    """A route that answers in chunked encoding, sends `sent` bytes of `body` as one whole chunk and closes before the last chunk."""

    def route(handler):
        handler.send_response(200)
        handler.send_header("Transfer-Encoding", "chunked")
        handler.end_headers()
        handler.wfile.write(f"{sent:x}\r\n".encode() + body[:sent] + b"\r\n")
        handler.wfile.flush()
        handler.close_connection = True

    return route


def cut_without_length(body: bytes, sent: int):
    """A route that announces neither a length nor chunking, sends `sent` bytes of `body` and closes: HTTP cannot tell it from a complete body."""

    def route(handler):
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(body[:sent])
        handler.wfile.flush()
        handler.close_connection = True

    return route


def redirect_to(location: str):
    def route(handler):
        handler.send_response(302)
        handler.send_header("Location", location)
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    return route


def make_zip(entries: dict[str, bytes], links: tuple[str, ...] = ()) -> bytes:
    """A zip archive of `entries`; the names in `links` are stored as symbolic links."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = ((stat.S_IFLNK if name in links else stat.S_IFREG) | 0o644) << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def source(stand, path, data, local_path, **extra):
    """One lock source for the content `data` served at `path`."""
    return {
        "dataset_id": "test-" + local_path.replace("/", "-"),
        "landing_url": "https://landing.invalid/never-opened",
        "download_url": stand.url(path),
        "local_path": local_path,
        "sha256": sha256(data),
        "size_bytes": len(data),
        **extra,
    }


def write_lock(directory: Path, *sources, schema="data-sources/1") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "data-sources.lock.json"
    lock.write_text(json.dumps({"schema_version": schema, "sources": list(sources)}), encoding="utf-8")
    return lock


def tree(root: Path) -> dict[str, bytes | None]:
    """Every path under `root` (files with their bytes, directories and links as None)."""
    return {
        p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() and not p.is_symlink() else None)
        for p in sorted(root.rglob("*"))
    }


def real_workload_stand(stand, workload_dir: Path) -> tuple[Path, dict[str, bytes]]:
    """Serve the real committed bytes of a Workload under a lock copy whose URLs name the stand-in.

    Returns the rewritten lock and the files it asks for (the Bike archive is built here, so its `archive_sha256` is the test archive's).
    """
    committed = EXAMPLES / workload_dir.name  # the bytes come from the committed Workload; the copy may have lost its data
    lock = json.loads((committed / "data-sources.lock.json").read_text(encoding="utf-8"))
    served = {}
    for entry in lock["sources"]:
        data = (committed / entry["local_path"]).read_bytes()
        if "member" in entry:
            archive = make_zip({entry["member"]: data, "readme.txt": b"not the member"})
            stand.routes["/archive.zip"], entry["download_url"], entry["archive_sha256"] = archive, stand.url("/archive.zip"), sha256(archive)
        else:
            stand.routes["/data"], entry["download_url"] = data, stand.url("/data")
        served[entry["local_path"]] = data
        if "notice_url" in entry:
            notice = (committed / entry["notice"]).read_bytes()
            stand.routes["/notice"], entry["notice_url"] = notice, stand.url("/notice")
            served[entry["notice"]] = notice
    path = workload_dir.parent / (workload_dir.name + "-stand.lock.json")
    path.write_text(json.dumps(lock), encoding="utf-8")
    return path, served


def workload_copy(tmp_path: Path, name: str, *, drop_data: bool = True) -> Path:
    """A copy of one committed Workload directory, under an `examples/`-shaped tree, without its data files."""
    target = tmp_path / "examples" / name
    shutil.copytree(EXAMPLES / name, target)
    if drop_data:
        shutil.rmtree(target / "data")
    return target


def fetch_refusals(tmp_path: Path) -> dict[str, list[tuple[int, dict]]]:
    """Provoke every coded refusal of `data fetch`: {code: [(exit code, error object), ...]}; each case in its own directory."""
    stand = Stand()
    try:
        return _provoke(tmp_path, stand)
    finally:
        stand.close()


def _provoke(tmp_path: Path, stand: Stand):
    found: dict[str, list] = {}
    counter = iter(range(1000))

    def case(code, *sources, schema="data-sources/1", prepare=None, raw=None, args=None):
        directory = tmp_path / f"case-{next(counter)}"
        lock = write_lock(directory / "lock", *sources, schema=schema)
        if raw is not None:
            lock.write_text(raw, encoding="utf-8")
        dest = directory / "dest"
        if prepare is not None:
            prepare(dest)
        flags = args(lock, dest) if args else ("--lock", str(lock), "--dest", str(dest))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = cli.main(["data", "fetch", *flags, "--json"])
        error = json.loads(out.getvalue())["error"]
        assert error["code"] == code, (code, error)
        found.setdefault(code, []).append((status, error))

    body = b"alpha,beta\n1,2\n"
    stand.routes["/ok"] = body
    good = source(stand, "/ok", body, "data/a.csv")
    archive = make_zip({"day.csv": body})
    stand.routes["/archive"] = archive

    def with_archive(**changes):
        entry = source(stand, "/archive", body, "data/day.csv", archive_sha256=sha256(archive), member="day.csv")
        entry.update(changes)
        return entry

    case("FILE_NOT_FOUND", good, args=lambda lock, dest: ("--lock", str(lock) + ".missing", "--dest", str(dest)))
    case("FILE_NOT_JSON", raw="{not json")
    case("LOCK_SCHEMA_UNKNOWN", good, schema="data-sources/9")
    case("LOCK_INVALID", {k: v for k, v in good.items() if k != "sha256"})
    case("LOCK_INVALID", {**good, "download_url": "file:///etc/passwd"})
    case("PATH_OUTSIDE_DEST", {**good, "local_path": "/tmp/escaped.csv"})
    case("PATH_OUTSIDE_DEST", {**good, "local_path": "../escaped.csv"})
    case("PATH_OUTSIDE_DEST", with_archive(member="../day.csv"))
    case("PATH_OUTSIDE_DEST", with_archive(member="/day.csv"))

    def link_outside(dest):
        outside = dest.parent / "outside"
        outside.mkdir(parents=True)
        dest.mkdir()
        (dest / "data").symlink_to(outside, target_is_directory=True)

    case("PATH_OUTSIDE_DEST", good, prepare=link_outside)

    def dest_is_file(dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("not a directory")

    case("DEST_NOT_A_DIRECTORY", good, prepare=dest_is_file)

    def other_bytes(dest):
        (dest / "data").mkdir(parents=True)
        (dest / "data" / "a.csv").write_bytes(b"other bytes\n")

    case("DEST_FILE_DIFFERS", good, prepare=other_bytes)
    stand.routes["/wrong"] = b"alpha,beta\n9,9\n"
    case("DOWNLOAD_INTEGRITY", source(stand, "/wrong", body, "data/a.csv", size_bytes=len(stand.routes["/wrong"])))
    case("DOWNLOAD_INTEGRITY", with_archive(archive_sha256="0" * 64))
    case("DOWNLOAD_INTEGRITY", with_archive(sha256="1" * 64))
    stand.routes["/long"] = body * 3
    case("DOWNLOAD_TOO_LARGE", source(stand, "/long", body, "data/a.csv"))
    case("DOWNLOAD_TOO_LARGE", with_archive(size_bytes=len(body) - 1))
    linked = make_zip({"day.csv": b"../outside"}, links=("day.csv",))
    stand.routes["/linked"] = linked
    case("ARCHIVE_MEMBER_REFUSED", with_archive(download_url=stand.url("/linked"), archive_sha256=sha256(linked)))
    case("ARCHIVE_MEMBER_REFUSED", with_archive(member="other.csv"))
    stand.routes["/gone"] = 404
    stand.routes["/cut"] = cut_after(body, 5)
    case("DOWNLOAD_FAILED", source(stand, "/gone", body, "data/a.csv"))
    case("DOWNLOAD_FAILED", source(stand, "/cut", body, "data/a.csv"))
    case("DOWNLOAD_FAILED", {**good, "download_url": "http://127.0.0.1:1/closed"})
    stand.routes["/redirect"] = redirect_to(stand.url("/ok"))
    case("DOWNLOAD_FAILED", source(stand, "/redirect", body, "data/a.csv"))
    return found
