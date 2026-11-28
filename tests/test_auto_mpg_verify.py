import json

import pytest

from _study_helpers import EXAMPLES, run_json, sha256
from hypotrail.core import data, fetch


LOCK = "uci-data-sources.lock.json"
NOTICE = "licenses/Auto-MPG-attribution.md"
SOURCE = "data/auto-mpg.data"


@pytest.fixture
def bundle(tmp_path):
    examples = tmp_path / "examples"
    workload = examples / "auto_mpg"
    notice = workload / NOTICE
    notice.parent.mkdir(parents=True)
    notice.write_text("Synthetic dataset attribution.\n", encoding="utf-8")
    external = tmp_path / "external.dat"
    # This is not valid CSV or even UTF-8. Verification treats it as opaque bytes.
    external.write_bytes(b"opaque\x00\xff\n")
    lock = {
        "schema_version": "data-sources/1",
        "sources": [{
            "dataset_id": "uci-auto-mpg-v1",
            "download_url": "https://example.invalid/auto-mpg.data",
            "local_path": SOURCE,
            "sha256": sha256(external),
            "size_bytes": external.stat().st_size,
            "license": "CC-BY-4.0",
            "notice": NOTICE,
            "notice_sha256": sha256(notice),
        }],
    }
    (workload / LOCK).write_text(json.dumps(lock), encoding="utf-8")
    return examples, external, notice, lock


def verify(examples, external):
    return run_json("data", "verify", "--examples-dir", examples, "--workload", "auto_mpg", "--data-file", external)


def test_auto_mpg_verifies_only_the_explicit_external_file_and_notice(bundle):
    examples, external, notice, lock = bundle
    source, = lock["sources"]

    code, payload, err = verify(examples, external)

    assert (code, err) == (0, "")
    assert payload == {"ok": True, "datasets": [{
        "workload": "auto_mpg", "dataset_id": source["dataset_id"], "status": "verified",
        "file": SOURCE, "sha256": source["sha256"], "size_bytes": source["size_bytes"],
        "license": source["license"], "notice": NOTICE, "checks": [],
    }]}
    assert external.stat().st_size == source["size_bytes"]
    assert sha256(notice) == source["notice_sha256"]
    assert data.discover_workloads(examples) == []


@pytest.mark.parametrize(
    ("fault", "exit_code", "error_code"),
    [
        ("same_size_bytes", 3, "DATA_INTEGRITY"),
        ("pinned_size", 3, "DATA_INTEGRITY"),
        ("missing_data", 3, "DATA_MISSING"),
        ("empty_notice", 3, "LICENCE_NOTICE_MISSING"),
        ("missing_notice", 3, "LICENCE_NOTICE_MISSING"),
        ("changed_notice", 3, "LICENCE_NOTICE_CHANGED"),
        ("missing_lock", 2, "FILE_NOT_FOUND"),
        ("invalid_json", 2, "FILE_NOT_JSON"),
        ("invalid_encoding", 2, "FILE_NOT_JSON"),
        ("invalid_source", 2, "LOCK_INVALID"),
    ],
)
def test_auto_mpg_refuses_missing_or_tampered_inputs(bundle, fault, exit_code, error_code):
    examples, external, notice, lock = bundle
    lock_file = examples / "auto_mpg" / LOCK
    if fault == "same_size_bytes":
        external.write_bytes(b"opaque\x00\xfe\n")
    elif fault == "pinned_size":
        lock["sources"][0]["size_bytes"] += 1
        lock_file.write_text(json.dumps(lock), encoding="utf-8")
    elif fault == "missing_data":
        external.unlink()
    elif fault == "empty_notice":
        notice.write_bytes(b"")
    elif fault == "missing_notice":
        notice.unlink()
    elif fault == "changed_notice":
        notice.write_text("This notice changed.\n", encoding="utf-8")
    elif fault == "missing_lock":
        lock_file.unlink()
    elif fault == "invalid_json":
        lock_file.write_text("{", encoding="utf-8")
    elif fault == "invalid_encoding":
        lock_file.write_bytes(b"\xff")
    else:
        lock["sources"][0]["notice_sha256"] = "not a SHA-256"
        lock_file.write_text(json.dumps(lock), encoding="utf-8")

    code, payload, err = verify(examples, external)

    assert code == exit_code
    assert payload["ok"] is False
    assert payload["error"]["code"] == error_code
    assert str(external) not in err
    assert str(external) not in json.dumps(payload)
    if fault == "invalid_encoding":
        assert payload["error"]["stage"] == "config"
        assert payload["error"]["details"]["line"] is None
    if fault == "pinned_size":
        details = payload["error"]["details"]
        assert details["actual_sha256"] == details["expected_sha256"]
        assert details["actual_size_bytes"] + 1 == details["expected_size_bytes"]


@pytest.mark.parametrize(
    ("flags", "error"),
    [
        ((), "DATA_FILE_NEEDS_AUTO_MPG"),
        (("--workload", "bike_day"), "DATA_FILE_NEEDS_AUTO_MPG"),
        (("--workload", "auto_mpg", "--workload", "bike_day"), "DATA_FILE_NEEDS_AUTO_MPG"),
        (("--workload", "auto_mpg", "--workload", "auto_mpg"), "DATA_FILE_NEEDS_AUTO_MPG"),
        (("--workload", "auto_mpg", "--build-dir", "not-read"), "INVALID_ARGUMENTS"),
    ],
)
def test_data_file_rejects_ambiguous_arguments_before_opening_a_source(bundle, monkeypatch, flags, error):
    examples, external, _, _ = bundle

    def unexpected_source(*args, **kwargs):
        pytest.fail("An invalid argument combination must not reach data verification.")

    monkeypatch.setattr(data, "sha256_file", unexpected_source)

    code, payload, err = run_json("data", "verify", "--examples-dir", examples, "--data-file", external, *flags)
    assert code == 2
    assert payload["error"]["code"] == error
    if "--build-dir" in flags:
        assert "--build-dir: not allowed with argument --data-file" in err


def test_committed_auto_mpg_lock_is_fetch_compatible_without_fetching_any_bytes():
    directory = EXAMPLES / "auto_mpg"
    source, = fetch._read_lock(directory / LOCK)
    assert source["download_url"] == "https://archive.ics.uci.edu/ml/machine-learning-databases/auto-mpg/auto-mpg.data"
    assert source["size_bytes"] == 30286
    assert source["sha256"] == "48b830e11feee5572525f8f1691ddb9d38d3d7b7063edcd8fca672c2a5e17d8d"
    recorded = json.loads((directory / LOCK).read_text(encoding="utf-8"))["sources"][0]
    assert recorded["notice_sha256"] == sha256(directory / NOTICE)
