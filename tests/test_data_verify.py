"""Ticket #15: `python -m hypotrail data verify` on the copied Workload data."""

import hashlib
import io
import json
import shutil
import sqlite3
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from hypotrail import cli
from hypotrail.core import data

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def examples_copy(tmp_path):
    target = tmp_path / "examples"
    shutil.copytree(EXAMPLES, target)
    return target


def test_both_datasets_verify_with_no_workload_given():
    code, out, _ = run_cli("data", "verify", "--json")
    assert code == 0
    report = json.loads(out)
    assert report["ok"] is True
    verified = {d["workload"]: d for d in report["datasets"]}
    assert set(verified) == {"bike_day", "chinook"}
    assert all(d["status"] == "verified" for d in verified.values())


def test_a_single_workload_can_be_verified():
    code, out, _ = run_cli("data", "verify", "--workload", "bike_day", "--json")
    assert code == 0
    assert [d["workload"] for d in json.loads(out)["datasets"]] == ["bike_day"]


def test_plain_output_is_human_readable_and_stdout_is_not_json_without_the_flag():
    code, out, _ = run_cli("data", "verify")
    assert code == 0
    assert "bike_day" in out and "chinook" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_the_two_data_files_match_the_lock_bytes_and_size():
    for workload in ("bike_day", "chinook"):
        lock = json.loads((EXAMPLES / workload / "data-sources.lock.json").read_text())
        for source in lock["sources"]:
            path = EXAMPLES / workload / source["local_path"]
            assert sha256(path) == source["sha256"]
            assert path.stat().st_size == source["size_bytes"]


def test_unknown_workload_is_an_invalid_input():
    code, out, _ = run_cli("data", "verify", "--workload", "nope", "--json")
    assert code == 2
    error = json.loads(out)["error"]
    assert set(error) >= {"code", "message", "stage", "details"}


# --- tampering: bytes are refused first -----------------------------------


@pytest.mark.parametrize(
    "workload,relative",
    [("bike_day", "data/day.csv"), ("chinook", "data/Chinook_Sqlite.sqlite")],
)
def test_a_flipped_byte_is_refused_with_the_integrity_code_naming_the_file(
    examples_copy, workload, relative
):
    path = examples_copy / workload / relative
    raw = bytearray(path.read_bytes())
    raw[len(raw) // 2] ^= 0x01
    path.write_bytes(bytes(raw))

    code, out, _ = run_cli(
        "data", "verify", "--examples-dir", str(examples_copy), "--json"
    )

    assert code == 3
    error = json.loads(out)["error"]
    assert error["stage"] == "integrity"
    assert error["details"]["file"] == relative
    assert relative in error["message"]


def test_the_content_checks_never_run_on_tampered_bytes(examples_copy, monkeypatch):
    def must_not_run(*args, **kwargs):
        raise AssertionError("a content check ran before the bytes were verified")

    monkeypatch.setattr(data, "check_daily_series", must_not_run)
    monkeypatch.setattr(data, "check_sqlite_tables", must_not_run)
    path = examples_copy / "chinook" / "data" / "Chinook_Sqlite.sqlite"
    raw = bytearray(path.read_bytes())
    raw[0] ^= 0xFF
    path.write_bytes(bytes(raw))

    code, _, _ = run_cli("data", "verify", "--examples-dir", str(examples_copy))

    assert code == 3


def test_tampered_chinook_bytes_stop_the_bike_check_too(examples_copy, monkeypatch):
    # Bytes of every selected dataset are verified before any content check.
    monkeypatch.setattr(
        data,
        "check_daily_series",
        lambda *a, **k: pytest.fail("content check ran before all bytes were verified"),
    )
    path = examples_copy / "chinook" / "data" / "Chinook_Sqlite.sqlite"
    raw = bytearray(path.read_bytes())
    raw[10] ^= 0x01
    path.write_bytes(bytes(raw))
    code, _, _ = run_cli("data", "verify", "--examples-dir", str(examples_copy))
    assert code == 3


# --- licences ---------------------------------------------------------------


def test_the_notices_sit_next_to_their_data():
    assert (EXAMPLES / "bike_day/licenses/Bike-Sharing-attribution.md").is_file()
    assert (EXAMPLES / "chinook/licenses/Chinook-MIT.txt").is_file()


def test_the_chinook_notice_must_match_the_lock_hash(examples_copy):
    notice = examples_copy / "chinook" / "licenses" / "Chinook-MIT.txt"
    notice.write_text(notice.read_text() + "\nedited")
    code, out, _ = run_cli(
        "data", "verify", "--examples-dir", str(examples_copy), "--json"
    )
    assert code == 3
    error = json.loads(out)["error"]
    assert error["stage"] == "licence"
    assert error["details"]["file"] == "licenses/Chinook-MIT.txt"


def test_a_missing_notice_is_refused(examples_copy):
    (examples_copy / "bike_day/licenses/Bike-Sharing-attribution.md").unlink()
    code, out, _ = run_cli(
        "data", "verify", "--examples-dir", str(examples_copy), "--json"
    )
    assert code == 3
    assert json.loads(out)["error"]["stage"] == "licence"


# --- Bike calendar ------------------------------------------------------------

BIKE_SPEC = json.loads((EXAMPLES / "bike_day/data-checks.json").read_text())
BIKE_SOURCE = json.loads((EXAMPLES / "bike_day/data-sources.lock.json").read_text())[
    "sources"
][0]


def bike_lines():
    return (EXAMPLES / "bike_day/data/day.csv").read_text().splitlines()


def write_csv(tmp_path, lines):
    path = tmp_path / "day.csv"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_bike_has_one_row_per_date_from_2011_01_01_to_2012_12_31():
    result = data.check_daily_series(
        EXAMPLES / "bike_day/data/day.csv", BIKE_SOURCE, BIKE_SPEC
    )
    assert result["rows"] == 731
    assert result["date_min"] == "2011-01-01" and result["date_max"] == "2012-12-31"


def test_a_missing_day_is_a_calendar_failure(tmp_path):
    lines = bike_lines()
    del lines[100]
    with pytest.raises(data.DataCheckError) as caught:
        data.check_daily_series(write_csv(tmp_path, lines), BIKE_SOURCE, BIKE_SPEC)
    assert caught.value.stage == "calendar"


def test_a_duplicate_date_is_a_calendar_failure(tmp_path):
    lines = bike_lines()
    lines[50] = lines[49]
    with pytest.raises(data.DataCheckError) as caught:
        data.check_daily_series(write_csv(tmp_path, lines), BIKE_SOURCE, BIKE_SPEC)
    assert caught.value.stage == "calendar"


def test_a_negative_or_non_integer_count_is_refused(tmp_path):
    for bad in ("-5", "12.5", "abc"):
        lines = bike_lines()
        cells = lines[10].split(",")
        cells[-1] = bad
        lines[10] = ",".join(cells)
        with pytest.raises(data.DataCheckError):
            data.check_daily_series(write_csv(tmp_path, lines), BIKE_SOURCE, BIKE_SPEC)


def test_cnt_must_equal_casual_plus_registered(tmp_path):
    lines = bike_lines()
    cells = lines[10].split(",")
    cells[-1] = str(int(cells[-1]) + 1)
    lines[10] = ",".join(cells)
    with pytest.raises(data.DataCheckError) as caught:
        data.check_daily_series(write_csv(tmp_path, lines), BIKE_SOURCE, BIKE_SPEC)
    assert "casual" in str(caught.value)


# --- Chinook ------------------------------------------------------------------

CHINOOK_DB = EXAMPLES / "chinook/data/Chinook_Sqlite.sqlite"
CHINOOK_SPEC = json.loads((EXAMPLES / "chinook/data-checks.json").read_text())


def test_chinook_integrity_is_ok_and_the_eleven_tables_have_their_counts():
    result = data.check_sqlite_tables(CHINOOK_DB, {}, CHINOOK_SPEC)
    assert result["integrity_check"] == "ok"
    assert result["table_row_counts"] == CHINOOK_SPEC["table_row_counts"]
    assert len(result["table_row_counts"]) == 11


def test_a_wrong_table_count_is_refused():
    spec = json.loads(json.dumps(CHINOOK_SPEC))
    spec["table_row_counts"]["Track"] = 3504
    with pytest.raises(data.DataCheckError) as caught:
        data.check_sqlite_tables(CHINOOK_DB, {}, spec)
    assert caught.value.stage == "tables"


def test_chinook_is_opened_read_only_and_a_write_fails_with_the_readonly_error():
    before = sha256(CHINOOK_DB)
    connection = data.open_sqlite_readonly(CHINOOK_DB)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("CREATE TABLE x (a)")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM Track")
    finally:
        connection.close()
    assert sha256(CHINOOK_DB) == before


def test_verification_leaves_the_chinook_file_unchanged(examples_copy):
    path = examples_copy / "chinook/data/Chinook_Sqlite.sqlite"
    before = sha256(path)
    code, _, _ = run_cli("data", "verify", "--examples-dir", str(examples_copy))
    assert code == 0
    assert sha256(path) == before
    assert sorted(p.name for p in path.parent.iterdir()) == [
        "Chinook_Sqlite.sqlite"
    ]
