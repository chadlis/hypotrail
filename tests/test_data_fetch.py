"""Ticket #22: `python -m hypotrail data fetch` acquires a Workload's sources against its lock.

Every download is served by the stand-in on the loopback interface (or by a replaced opener); the network guard stays on.
"""

import json
import os
import shutil
import urllib.request
import zipfile
from urllib.parse import urlsplit

import pytest
from _fetch_helpers import (
    Stand,
    cut_after,
    fetch,
    fetch_refusals,
    make_zip,
    real_workload_stand,
    redirect_to,
    run_cli,
    sha256,
    source,
    tree,
    workload_copy,
    write_lock,
)

from hypotrail.core import fetch as core_fetch

BODY = b"alpha,beta\n1,2\n"


@pytest.fixture
def stand():
    stand = Stand()
    yield stand
    stand.close()


# --- C1: the command, --json, the lock refused before any download ---------------------------------------------------


def test_c1_the_command_prints_one_json_object_on_stdout_and_diagnostics_on_stderr(stand, tmp_path):
    stand.routes["/a"] = BODY
    lock = write_lock(tmp_path / "lock", source(stand, "/a", BODY, "data/a.csv"))
    code, out, err = run_cli("data", "fetch", "--lock", str(lock), "--dest", str(tmp_path / "dest"), "--json")
    assert code == 0 and err == ""
    assert json.loads(out)["ok"] is True  # stdout is exactly one JSON document

    code, out, err = run_cli("data", "fetch", "--lock", str(tmp_path / "nothing.json"), "--dest", str(tmp_path / "dest"), "--json")
    error = json.loads(out)["error"]  # still exactly one object, with the four members
    assert code == 2 and set(error) == {"code", "message", "stage", "details"}
    assert error["code"] in err and error["message"] in err  # the human diagnostic is on stderr

    code, out, err = run_cli("data", "fetch", "--lock", str(lock), "--dest", str(tmp_path / "dest"))
    assert code == 0
    with pytest.raises(json.JSONDecodeError):  # without the flag stdout is for humans
        json.loads(out)


def test_c1_a_lock_that_is_not_json_or_has_an_unknown_schema_or_lacks_a_key_is_refused_before_any_download(stand, tmp_path):
    stand.routes["/a"] = BODY
    good = source(stand, "/a", BODY, "data/a.csv")
    (tmp_path / "not-json.json").write_text("{nope")
    cases = {
        "FILE_NOT_JSON": (tmp_path / "not-json.json"),
        "LOCK_SCHEMA_UNKNOWN": write_lock(tmp_path / "v9", good, schema="data-sources/9"),
        "LOCK_INVALID": write_lock(tmp_path / "nokey", {k: v for k, v in good.items() if k != "download_url"}),
    }
    for code, lock in cases.items():
        status, payload, _ = fetch(lock, tmp_path / "dest")
        assert (status, payload["error"]["code"]) == (2, code), code
    assert stand.requests == [] and not (tmp_path / "dest").exists()
    status, payload, _ = fetch(write_lock(tmp_path / "ok", good), tmp_path / "dest")  # a refusal of everything would fail here
    assert status == 0 and stand.requests == ["/a"]


def test_c1_a_source_that_names_an_archive_without_its_member_lacks_a_key(stand, tmp_path):
    lock = write_lock(tmp_path / "l", source(stand, "/a", BODY, "data/a.csv", archive_sha256=sha256(BODY)))
    status, payload, _ = fetch(lock, tmp_path / "dest")
    assert (status, payload["error"]["code"], payload["error"]["details"]["key"]) == (2, "LOCK_INVALID", "sources[0].member")
    assert stand.requests == []


# --- C2: only the lock's download_url, a temporary file beside the target, the hash, then an atomic rename ------------


def test_c2_each_source_comes_only_from_its_download_url_through_a_temporary_file_and_a_rename(stand, tmp_path, monkeypatch):
    stand.routes["/a"] = BODY
    dest = tmp_path / "dest"
    during = {}

    def serve(handler):  # what the destination looks like while the body is in flight
        handler.send_response(200)
        handler.send_header("Content-Length", str(len(BODY)))
        handler.end_headers()
        handler.wfile.write(BODY[:4])
        handler.wfile.flush()
        during["names"] = sorted(p.name for p in (dest / "data").iterdir()) if (dest / "data").exists() else None
        handler.wfile.write(BODY[4:])

    stand.routes["/a"] = serve
    renames = []
    real_replace = os.replace

    def spy(src, dst):
        renames.append((os.fspath(src), os.fspath(dst), sha256(open(src, "rb").read())))
        return real_replace(src, dst)

    monkeypatch.setattr(core_fetch.os, "replace", spy)
    lock = write_lock(tmp_path / "lock", source(stand, "/a", BODY, "data/a.csv"))
    status, payload, _ = fetch(lock, dest)
    assert status == 0 and stand.requests == ["/a"]  # the landing_url (a host that is not loopback) is never tried
    assert len(during["names"]) == 1 and during["names"][0] != "a.csv"  # a temporary file, in the target's directory, and no a.csv yet
    ((src, dst, digest),) = renames
    assert os.path.dirname(src) == os.path.dirname(dst) == str(dest / "data")  # renamed within one directory
    assert dst == str(dest / "data" / "a.csv") and digest == sha256(BODY)  # the hash was already the lock's at the rename
    assert [p.name for p in (dest / "data").iterdir()] == ["a.csv"] and (dest / "data" / "a.csv").read_bytes() == BODY


# --- C3: the bound stops the download as soon as it is passed -------------------------------------------------------


class Endless:
    """A response of `total` bytes that counts what was asked of it."""

    def __init__(self, total):
        self.total, self.read_bytes, self.headers = total, 0, {}

    def read(self, amount=-1):
        amount = min(amount, self.total - self.read_bytes)
        self.read_bytes += amount
        return b"x" * amount

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_c3_a_download_that_grows_past_its_bound_is_stopped_at_once_and_leaves_nothing(tmp_path, monkeypatch):
    big = Endless(50 * 1024 * 1024)
    monkeypatch.setattr(core_fetch, "open_url", lambda url: big)
    entry = {
        "dataset_id": "t", "download_url": "http://127.0.0.1:9/x", "local_path": "data/a.csv",
        "sha256": sha256(BODY), "size_bytes": 1000,
    }
    dest = tmp_path / "dest"
    status, payload, _ = fetch(write_lock(tmp_path / "l", entry), dest)
    assert (status, payload["error"]["code"]) == (3, "DOWNLOAD_TOO_LARGE")
    assert big.read_bytes <= 1000 + core_fetch.CHUNK_BYTES  # stopped as it passed the bound, not at the end of 50 MB
    assert list(dest.rglob("*")) == [dest / "data"]  # no file of any kind is left


def test_c3_the_one_generic_cap_bounds_an_archive_and_a_notice_whatever_their_data_size(stand, tmp_path, monkeypatch):
    monkeypatch.setattr(core_fetch, "GENERIC_CAP_BYTES", 100)
    archive = make_zip({"day.csv": BODY, "padding.bin": bytes(range(256)) * 4})
    stand.routes["/archive"] = archive
    entry = source(stand, "/archive", BODY, "data/day.csv", archive_sha256=sha256(archive), member="day.csv")
    status, payload, _ = fetch(write_lock(tmp_path / "a", entry), tmp_path / "d1")
    assert (status, payload["error"]["code"], payload["error"]["details"]["what"]) == (3, "DOWNLOAD_TOO_LARGE", "archive")
    notice = b"licence text " * 20
    stand.routes["/notice"] = notice
    entry = source(stand, "/ok", BODY, "data/a.csv", notice="licenses/N.txt", notice_url=stand.url("/notice"), notice_sha256=sha256(notice))
    stand.routes["/ok"] = BODY
    status, payload, _ = fetch(write_lock(tmp_path / "n", entry), tmp_path / "d2")
    assert (status, payload["error"]["code"], payload["error"]["details"]["what"]) == (3, "DOWNLOAD_TOO_LARGE", "notice")
    assert not (tmp_path / "d1" / "data" / "day.csv").exists() and not (tmp_path / "d2" / "licenses" / "N.txt").exists()


# --- C4: a hash that differs is refused, exit 3, nothing published -------------------------------------------------


def test_c4_a_download_whose_sha256_differs_from_the_lock_is_refused_and_a_file_beside_it_is_untouched(stand, tmp_path):
    wrong = b"alpha,beta\n9,9\n"  # same size as BODY, other bytes
    stand.routes["/wrong"] = wrong
    stand.routes["/notice"] = b"licence\n"
    entry = source(
        stand, "/wrong", BODY, "data/a.csv",
        notice="licenses/N.txt", notice_url=stand.url("/notice"), notice_sha256=sha256(b"licence\n"),
    )
    dest = tmp_path / "dest"
    (dest / "licenses").mkdir(parents=True)
    (dest / "licenses" / "N.txt").write_bytes(b"licence\n")  # matches the lock: it stays as it is
    before = tree(dest)
    mtime = (dest / "licenses" / "N.txt").stat().st_mtime_ns
    status, payload, _ = fetch(write_lock(tmp_path / "l", entry), dest)
    error = payload["error"]
    assert (status, error["code"], error["stage"]) == (3, "DOWNLOAD_INTEGRITY", "integrity")
    assert error["details"]["expected_sha256"] == sha256(BODY) and error["details"]["actual_sha256"] == sha256(wrong)
    assert {k: v for k, v in tree(dest).items() if k != "data"} == before and not (dest / "data" / "a.csv").exists()
    assert (dest / "licenses" / "N.txt").stat().st_mtime_ns == mtime
    assert [p for p in (dest / "data").iterdir()] == []  # the temporary file is gone


# --- C5 and B: the archive, its member and the guard ------------------------------------------------------------------


def archive_lock(stand, tmp_path, archive, data=BODY, **changes):
    stand.routes["/archive"] = archive
    entry = source(stand, "/archive", data, "data/day.csv", archive_sha256=sha256(archive), member="day.csv")
    entry.update(changes)
    return write_lock(tmp_path / "lock", entry)


def test_b_a_valid_archive_publishes_day_csv_and_nothing_else(stand, tmp_path):
    lock = archive_lock(stand, tmp_path, make_zip({"day.csv": BODY, "readme.txt": b"other", "hour.csv": b"other"}))
    dest = tmp_path / "dest"
    status, payload, _ = fetch(lock, dest)
    assert status == 0 and payload["sources"][0]["status"] == "fetched"
    assert tree(dest) == {"data": None, "data/day.csv": BODY}


def test_b_an_entry_named_day_csv_that_is_a_link_is_refused_after_the_archive_check_and_nothing_is_written(stand, tmp_path):
    lock = archive_lock(stand, tmp_path, make_zip({"day.csv": b"../../outside"}, links=("day.csv",)))
    dest = tmp_path / "dest"
    status, payload, _ = fetch(lock, dest)
    error = payload["error"]
    assert (status, error["code"], error["details"]["reason"]) == (3, "ARCHIVE_MEMBER_REFUSED", "link")
    assert stand.requests == ["/archive"]  # the archive was downloaded and checked before the refusal
    assert not (dest / "data" / "day.csv").exists() and list((dest / "data").iterdir()) == []
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize("member, reason", [("../day.csv", "parent_reference"), ("/day.csv", "absolute")])
def test_b_a_member_that_leaves_the_target_directory_is_refused_before_any_download(stand, tmp_path, member, reason):
    archive = make_zip({"day.csv": BODY})
    lock = archive_lock(stand, tmp_path, archive, member=member)
    status, payload, _ = fetch(lock, tmp_path / "dest")
    assert (status, payload["error"]["code"], payload["error"]["details"]["reason"]) == (2, "PATH_OUTSIDE_DEST", reason)
    assert stand.requests == [] and not (tmp_path / "dest").exists()


def test_c5_the_archive_is_checked_against_archive_sha256_before_it_is_opened(stand, tmp_path, monkeypatch):
    archive = make_zip({"day.csv": BODY})
    lock = archive_lock(stand, tmp_path, archive, archive_sha256="0" * 64)
    opened = []
    real = zipfile.ZipFile
    monkeypatch.setattr(core_fetch.zipfile, "ZipFile", lambda *a, **k: opened.append(a) or real(*a, **k))
    status, payload, _ = fetch(lock, tmp_path / "dest")
    assert (status, payload["error"]["code"], payload["error"]["details"]["what"]) == (3, "DOWNLOAD_INTEGRITY", "archive")
    assert opened == [] and not (tmp_path / "dest" / "data" / "day.csv").exists()


def test_c5_the_extracted_member_is_checked_against_the_lock_sha256_and_size_before_it_is_published(stand, tmp_path):
    archive = make_zip({"day.csv": BODY})
    for changes in ({"sha256": "1" * 64}, {"size_bytes": len(BODY) + 1}):
        lock = archive_lock(stand, tmp_path, archive, **changes)
        status, payload, _ = fetch(lock, tmp_path / "dest")
        assert (status, payload["error"]["code"], payload["error"]["details"]["what"]) == (3, "DOWNLOAD_INTEGRITY", "member"), changes
    status, payload, _ = fetch(archive_lock(stand, tmp_path, archive, size_bytes=len(BODY) - 1), tmp_path / "dest")
    assert (status, payload["error"]["code"]) == (3, "DOWNLOAD_TOO_LARGE")  # a member longer than the lock says is stopped, not read whole
    assert not (tmp_path / "dest" / "data" / "day.csv").exists() and list((tmp_path / "dest" / "data").iterdir()) == []


# --- C6: a failed transfer is exit 4 and names the verified bundle --------------------------------------------------


@pytest.mark.parametrize("kind", ["unreachable", "http_status", "interrupted"])
def test_c6_a_failed_transfer_is_exit_4_publishes_nothing_and_names_the_verified_bundle(stand, tmp_path, kind):
    stand.routes["/ok"] = BODY  # a mirror that is never to be tried
    url = {
        "unreachable": "http://127.0.0.1:1/closed",
        "http_status": stand.url("/gone"),
        "interrupted": stand.url("/cut"),
    }[kind]
    stand.routes["/gone"] = 503
    stand.routes["/cut"] = cut_after(BODY, 5)
    entry = source(stand, "/ok", BODY, "data/a.csv", download_url=url)
    dest = tmp_path / "dest"
    status, payload, err = fetch(write_lock(tmp_path / "l", entry), dest)
    error = payload["error"]
    assert (status, error["code"], error["stage"]) == (4, "DOWNLOAD_FAILED", "download")
    assert "data verify" in error["message"] and "verified bundle" in error["message"] and "data verify" in err
    assert error["details"]["reason"] == kind and error["details"]["host"] == urlsplit(url).netloc
    assert not (dest / "data" / "a.csv").exists() and list((dest / "data").iterdir()) == []
    assert "/ok" not in stand.requests and stand.requests.count(urlpath(url)) <= 1  # no other source, no second try


def urlpath(url):
    return "/" + url.split("/", 3)[3]


# --- J (D-019): redirects are followed, at most 5 hops, https only --------------------------------------------------
# The stand-in speaks http, so the https-only rule is witnessed twice without TLS: end to end, where the default rule refuses a
# redirect to the stand-in (an http address), and on the redirect handler itself, which is given https and http targets directly.
# The tests that need a followed hop on the loopback widen the allowed schemes for their own duration.


def chain(stand, hops, final=BODY, start="/r0"):
    """Routes /r0 -> /r1 -> ... -> /r<hops>, which answers `final`."""
    for n in range(hops):
        stand.routes[f"/r{n}"] = redirect_to(stand.url(f"/r{n + 1}"))
    stand.routes[f"/r{hops}"] = final
    return start


def test_j_a_followed_redirect_publishes_the_file_the_lock_names_and_up_to_five_hops_are_followed(stand, tmp_path, monkeypatch):
    monkeypatch.setattr(core_fetch, "REDIRECT_SCHEMES", ("http", "https"))
    for hops in (1, 5):
        start = chain(stand, hops)
        dest = tmp_path / f"dest{hops}"
        status, payload, _ = fetch(write_lock(tmp_path / f"l{hops}", source(stand, start, BODY, "data/a.csv")), dest)
        assert status == 0 and (dest / "data" / "a.csv").read_bytes() == BODY, hops
        assert stand.requests[-(hops + 1):] == [f"/r{n}" for n in range(hops + 1)]  # the lock's URL first, then each hop
        assert [p.name for p in (dest / "data").iterdir()] == ["a.csv"]


def test_j_the_lock_sha256_stays_the_only_gate_after_a_redirect(stand, tmp_path, monkeypatch):
    monkeypatch.setattr(core_fetch, "REDIRECT_SCHEMES", ("http", "https"))
    chain(stand, 1, final=b"alpha,beta\n9,9\n")
    status, payload, _ = fetch(write_lock(tmp_path / "l", source(stand, "/r0", BODY, "data/a.csv")), tmp_path / "dest")
    assert (status, payload["error"]["code"]) == (3, "DOWNLOAD_INTEGRITY")
    assert list((tmp_path / "dest" / "data").iterdir()) == []


def test_j_a_sixth_hop_is_refused_with_exit_4_and_no_fallback(stand, tmp_path, monkeypatch):
    monkeypatch.setattr(core_fetch, "REDIRECT_SCHEMES", ("http", "https"))
    start = chain(stand, 6)
    dest = tmp_path / "dest"
    status, payload, err = fetch(write_lock(tmp_path / "l", source(stand, start, BODY, "data/a.csv")), dest)
    error = payload["error"]
    assert (status, error["code"], error["details"]["reason"]) == (4, "DOWNLOAD_FAILED", "too_many_redirects")
    assert "data verify" in error["message"]
    assert stand.requests == [f"/r{n}" for n in range(6)]  # the lock's URL and five hops; the sixth redirect was not followed
    assert list((dest / "data").iterdir()) == []


def test_j_a_redirect_to_http_is_a_downgrade_refused_with_exit_4_and_the_target_is_never_requested(stand, tmp_path):
    stand.routes["/start"] = redirect_to(stand.url("/target"))  # the stand-in is http: under the default rule this is a downgrade
    stand.routes["/target"] = BODY
    dest = tmp_path / "dest"
    status, payload, _ = fetch(write_lock(tmp_path / "l", source(stand, "/start", BODY, "data/a.csv")), dest)
    assert (status, payload["error"]["code"], payload["error"]["details"]["reason"]) == (4, "DOWNLOAD_FAILED", "redirect_downgrade")
    assert stand.requests == ["/start"] and list((dest / "data").iterdir()) == []


def test_j_the_redirect_handler_follows_https_refuses_http_and_refuses_the_sixth_hop():
    request = urllib.request.Request("https://origin.invalid/file")
    handler = core_fetch._Redirects()
    followed = handler.redirect_request(request, None, 302, "Found", {}, "https://cdn.invalid/file?sig=abc")
    assert followed.full_url == "https://cdn.invalid/file?sig=abc"  # built, never opened
    with pytest.raises(core_fetch._RedirectRefused) as refused:
        handler.redirect_request(request, None, 302, "Found", {}, "http://cdn.invalid/file")
    assert refused.value.reason == "redirect_downgrade"
    request.redirect_dict = {f"https://hop{n}.invalid/": 1 for n in range(5)}  # five hops already followed
    with pytest.raises(core_fetch._RedirectRefused) as refused:
        handler.redirect_request(request, None, 302, "Found", {}, "https://hop5.invalid/")
    assert refused.value.reason == "too_many_redirects"
    request.redirect_dict = {f"https://hop{n}.invalid/": 1 for n in range(4)}
    assert handler.redirect_request(request, None, 302, "Found", {}, "https://hop4.invalid/").full_url == "https://hop4.invalid/"


def test_j_details_and_messages_report_the_final_host_and_never_the_signed_url_or_its_query(stand, tmp_path, monkeypatch):
    monkeypatch.setattr(core_fetch, "REDIRECT_SCHEMES", ("http", "https"))
    other = Stand()  # a second host (another port), where the redirect leads
    try:
        signed = "/signed?X-Signature=TOPSECRET&Expires=1"
        stand.routes["/start"] = redirect_to(other.url(signed))
        other.routes[signed] = 503
        status, out, err = run_cli(
            "data", "fetch", "--lock", str(write_lock(tmp_path / "l", source(stand, "/start", BODY, "data/a.csv"))), "--dest", str(tmp_path / "dest"), "--json"
        )
        error = json.loads(out)["error"]
        assert (status, error["code"], error["details"]["reason"], error["details"]["status"]) == (4, "DOWNLOAD_FAILED", "http_status", 503)
        assert error["details"]["host"] == urlsplit(other.base).netloc != urlsplit(stand.base).netloc  # the final host, not the lock's
        for text in (out, err):
            assert "TOPSECRET" not in text and "X-Signature" not in text and "/signed" not in text
    finally:
        other.close()


# --- C7 and D: the fetched files pass `data verify` like the committed bundle --------------------------------------------


@pytest.mark.parametrize("name", ["bike_day", "chinook"])
def test_c7_fetched_files_pass_data_verify_and_are_refused_after_one_byte_is_altered(stand, tmp_path, name):
    workload = workload_copy(tmp_path, name)
    lock, served = real_workload_stand(stand, workload)
    status, payload, _ = fetch(lock, workload)  # --dest is the Workload directory
    assert status == 0, payload
    entry = payload["sources"][0]
    assert entry["status"] == "fetched"
    local = json.loads((workload / "data-sources.lock.json").read_text())["sources"][0]["local_path"]
    assert (workload / local).read_bytes() == served[local]
    code, out, _ = run_cli("data", "verify", "--examples-dir", str(workload.parent), "--workload", name, "--json")
    assert code == 0 and json.loads(out)["datasets"][0]["status"] == "verified"
    data = (workload / local).read_bytes()
    (workload / local).write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    code, out, _ = run_cli("data", "verify", "--examples-dir", str(workload.parent), "--workload", name, "--json")
    assert code == 3 and json.loads(out)["error"]["code"] == "DATA_INTEGRITY"


# --- A: every path stays inside --dest ---------------------------------------------------------------------------------------


def _absolute(tmp_path):
    return str(tmp_path / "elsewhere" / "a.csv")


@pytest.mark.parametrize(
    "case",
    ["valid", "absolute_local_path", "parent_local_path", "absolute_notice", "parent_notice", "link_to_outside", "link_file_to_outside"],
)
def test_a_every_path_the_fetch_writes_stays_inside_dest(stand, tmp_path, case):
    stand.routes["/a"] = BODY
    stand.routes["/notice"] = b"licence\n"
    lock_dir, dest, outside = tmp_path / "lock", tmp_path / "dest", tmp_path / "elsewhere"
    outside.mkdir()
    entry = source(stand, "/a", BODY, "data/a.csv", notice="licenses/N.txt", notice_url=stand.url("/notice"), notice_sha256=sha256(b"licence\n"))
    if case == "absolute_local_path":
        entry["local_path"] = _absolute(tmp_path)
    if case == "parent_local_path":
        entry["local_path"] = "../elsewhere/a.csv"
    if case == "absolute_notice":
        entry["notice"] = _absolute(tmp_path)
    if case == "parent_notice":
        entry["notice"] = "../elsewhere/N.txt"
    if case == "link_to_outside":
        dest.mkdir()
        (dest / "licenses").symlink_to(outside, target_is_directory=True)
    if case == "link_file_to_outside":
        (dest / "data").mkdir(parents=True)
        (dest / "data" / "a.csv").symlink_to(outside / "a.csv")  # a dangling link to a file outside
    status, payload, _ = fetch(write_lock(lock_dir, entry), dest)
    assert tree(outside) == {}  # nothing exists outside --dest afterwards
    if case == "valid":
        assert status == 0 and (dest / "data" / "a.csv").read_bytes() == BODY and (dest / "licenses" / "N.txt").read_bytes() == b"licence\n"
        return
    assert (status, payload["error"]["code"]) == (2, "PATH_OUTSIDE_DEST")
    assert stand.requests == []  # before any download
    if case.startswith(("absolute", "parent")):
        assert not dest.exists()


# --- F, I: present, differing, missing ---------------------------------------------------------------------------------------


def test_f_a_matching_file_is_not_downloaded_again_and_is_reported_present(stand, tmp_path):
    stand.routes["/a"] = BODY
    lock = write_lock(tmp_path / "l", source(stand, "/a", BODY, "data/a.csv"))
    dest = tmp_path / "dest"
    assert fetch(lock, dest)[0] == 0 and stand.requests == ["/a"]
    mtime = (dest / "data" / "a.csv").stat().st_mtime_ns
    status, payload, _ = fetch(lock, dest)
    assert status == 0 and payload["sources"][0]["status"] == "present"
    assert stand.requests == ["/a"] and (dest / "data" / "a.csv").stat().st_mtime_ns == mtime


def test_f_a_file_that_differs_is_refused_unchanged_byte_for_byte_before_any_download(stand, tmp_path):
    stand.routes["/a"] = BODY
    stand.routes["/b"] = BODY
    lock = write_lock(tmp_path / "l", source(stand, "/b", BODY, "data/b.csv"), source(stand, "/a", BODY, "data/a.csv"))
    dest = tmp_path / "dest"
    (dest / "data").mkdir(parents=True)
    (dest / "data" / "a.csv").write_bytes(BODY + b"extra\n")
    before = tree(dest)
    status, payload, _ = fetch(lock, dest)
    error = payload["error"]
    assert (status, error["code"], error["stage"]) == (3, "DEST_FILE_DIFFERS", "integrity")
    assert error["details"]["file"] == "data/a.csv" and "remove it first" in error["message"]
    assert tree(dest) == before and stand.requests == []  # the other source was not fetched either


def test_i_a_missing_data_file_is_acquired_in_place_and_a_present_one_is_left(stand, tmp_path):
    workload = workload_copy(tmp_path, "chinook")
    lock, served = real_workload_stand(stand, workload)
    status, payload, _ = fetch(lock, workload)
    assert status == 0 and payload["sources"][0]["status"] == "fetched" and payload["sources"][0]["notice"]["status"] == "present"
    assert stand.requests == ["/data"]  # the committed notice matched, so only the data file came over the wire
    status, payload, _ = fetch(lock, workload)
    assert status == 0 and payload["sources"][0]["status"] == "present" and stand.requests == ["/data"]


# --- G, H: the notices ------------------------------------------------------------------------------------------------------


def test_g_the_chinook_notice_is_fetched_and_the_bike_notice_is_reported_absent(stand, tmp_path):
    chinook = workload_copy(tmp_path, "chinook")
    shutil.rmtree(chinook / "licenses")
    lock, served = real_workload_stand(stand, chinook)
    status, payload, _ = fetch(lock, chinook)
    assert status == 0 and payload["sources"][0]["notice"] == {"file": "licenses/Chinook-MIT.txt", "status": "fetched"}
    assert (chinook / "licenses" / "Chinook-MIT.txt").read_bytes() == served["licenses/Chinook-MIT.txt"]
    assert "/notice" in stand.requests

    bike = workload_copy(tmp_path, "bike_day")
    lock, _ = real_workload_stand(stand, bike)
    before = list(stand.requests)
    status, payload, _ = fetch(lock, bike)
    assert status == 0 and payload["sources"][0]["notice"] == {"file": "licenses/Bike-Sharing-attribution.md", "status": "absent"}
    assert stand.requests[len(before):] == ["/archive.zip"]  # no URL for the Bike notice: none is requested


def test_h_a_notice_is_checked_against_notice_sha256_and_bounded_by_the_cap_not_by_the_data_size(stand, tmp_path):
    notice = b"a licence text that is much longer than the five bytes of data\n" * 4
    stand.routes["/a"], stand.routes["/notice"] = b"abcde", notice
    entry = source(stand, "/a", b"abcde", "data/a.bin", notice="licenses/N.txt", notice_url=stand.url("/notice"), notice_sha256=sha256(notice))
    dest = tmp_path / "dest"
    status, _, _ = fetch(write_lock(tmp_path / "ok", entry), dest)
    assert status == 0 and (dest / "licenses" / "N.txt").read_bytes() == notice  # longer than size_bytes, still accepted

    stand.routes["/notice"] = notice[:-1] + b"?"
    other = tmp_path / "other"
    status, payload, _ = fetch(write_lock(tmp_path / "bad", entry), other)
    assert (status, payload["error"]["code"], payload["error"]["details"]["what"]) == (3, "DOWNLOAD_INTEGRITY", "notice")
    assert not (other / "licenses" / "N.txt").exists() and list((other / "licenses").iterdir()) == []

    differing = tmp_path / "differing"
    (differing / "licenses").mkdir(parents=True)
    (differing / "licenses" / "N.txt").write_bytes(b"edited by hand\n")
    status, payload, _ = fetch(write_lock(tmp_path / "bad", entry), differing)
    assert (status, payload["error"]["code"]) == (3, "DEST_FILE_DIFFERS")
    assert (differing / "licenses" / "N.txt").read_bytes() == b"edited by hand\n"


# --- C10: every refusal is covered, and the stand-in is the only host ------------------------------------------------------


def test_c10_every_refusal_has_a_case_and_each_is_coded_with_its_exit(tmp_path):
    found = fetch_refusals(tmp_path)
    assert {code: {status for status, _ in cases} for code, cases in found.items()} == {
        "FILE_NOT_FOUND": {2}, "FILE_NOT_JSON": {2}, "LOCK_SCHEMA_UNKNOWN": {2}, "LOCK_INVALID": {2}, "PATH_OUTSIDE_DEST": {2},
        "DEST_NOT_A_DIRECTORY": {2}, "DEST_FILE_DIFFERS": {3}, "DOWNLOAD_INTEGRITY": {3}, "DOWNLOAD_TOO_LARGE": {3},
        "ARCHIVE_MEMBER_REFUSED": {3}, "DOWNLOAD_FAILED": {4},
    }
    for cases in found.values():
        for _, error in cases:
            assert set(error) == {"code", "message", "stage", "details"}
