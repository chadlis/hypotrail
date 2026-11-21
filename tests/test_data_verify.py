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
    """T01 (SPEC §10)."""
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
    """T01 (SPEC §10)."""
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
    """T01 (SPEC §10)."""
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


def test_verifying_no_workload_at_all_is_refused_rather_than_reported_as_success(tmp_path):
    (tmp_path / "examples").mkdir()
    code, out, _ = run_cli("data", "verify", "--examples-dir", str(tmp_path / "examples"), "--json")
    assert code == 2
    report = json.loads(out)
    assert report["ok"] is False
    assert report["error"]["code"] == "NO_WORKLOAD"
    assert report["error"]["stage"] == "config"


def test_verify_workloads_refuses_an_empty_selection(tmp_path):
    from hypotrail.core.errors import InvalidInputError

    with pytest.raises(InvalidInputError) as caught:
        data.verify_workloads(EXAMPLES, [])
    assert caught.value.code == "NO_WORKLOAD"


# --- Ticket #7 review: with --json, every failure is one JSON object on stdout -----------------------


def test_an_unexpected_exception_with_json_is_one_object_and_exit_4(monkeypatch):
    secret = "sk-ant-NOT-FOR-OUTPUT"

    def boom(*args, **kwargs):
        raise RuntimeError(f"upstream said: bad key {secret}")

    monkeypatch.setattr(data, "verify_workloads", boom)
    code, out, err = run_cli("data", "verify", "--json")
    assert code == 4
    report = json.loads(out)
    assert report["ok"] is False
    assert set(report["error"]) == {"code", "message", "stage", "details"}
    assert report["error"]["code"] == "UNEXPECTED_ERROR"
    assert report["error"]["details"] == {"type": "RuntimeError"}
    assert secret not in out + err


def test_an_unexpected_exception_without_json_exits_4_and_leaks_nothing(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("sk-ant-NOT-FOR-OUTPUT")

    monkeypatch.setattr(data, "verify_workloads", boom)
    code, out, err = run_cli("data", "verify")
    assert code == 4
    assert out == ""
    assert "UNEXPECTED_ERROR" in err and "sk-ant-NOT-FOR-OUTPUT" not in err


def test_an_os_error_with_json_is_still_one_object_and_exit_4(monkeypatch):
    def boom(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(data, "verify_workloads", boom)
    code, out, _ = run_cli("data", "verify", "--json")
    assert code == 4
    error = json.loads(out)["error"]
    assert error["code"] == "INFRASTRUCTURE_FAILURE"
    assert set(error) == {"code", "message", "stage", "details"}


# --- Review of ticket #7: short rows, a missing directory, argument errors -------------------------


@pytest.mark.parametrize("cut_before", ["cnt", "casual"])
def test_a_short_row_is_a_content_failure_naming_the_date_and_column(tmp_path, cut_before):
    lines = bike_lines()
    columns = lines[0].split(",")
    cells = lines[10].split(",")
    lines[10] = ",".join(cells[: columns.index(cut_before)])  # the row stops before `cut_before`
    # the total is checked before the parts, so it is the column named in both cases
    column = BIKE_SPEC["total_column"]
    with pytest.raises(data.DataCheckError) as caught:
        data.check_daily_series(write_csv(tmp_path, lines), BIKE_SOURCE, BIKE_SPEC)
    date = cells[columns.index(BIKE_SOURCE["native_key"])]
    assert caught.value.code == "DATA_CHECK_FAILED" and caught.value.exit_code == 3
    assert caught.value.stage == "values"
    assert caught.value.details["column"] == column
    assert caught.value.details["date"] == date
    assert column in str(caught.value) and date in str(caught.value)


def test_a_row_without_its_date_cell_is_a_calendar_failure_not_a_type_error(tmp_path):
    lines = bike_lines()
    lines[10] = lines[10].split(",")[0]  # only the first cell: the date is missing
    assert BIKE_SOURCE["native_key"] != lines[0].split(",")[0]
    with pytest.raises(data.DataCheckError) as caught:
        data.check_daily_series(write_csv(tmp_path, lines), BIKE_SOURCE, BIKE_SPEC)
    assert caught.value.code == "DATA_CHECK_FAILED"
    assert caught.value.stage == "calendar"
    assert caught.value.details["column"] == BIKE_SOURCE["native_key"]


def test_a_short_row_through_the_command_exits_3(examples_copy):
    day = examples_copy / "bike_day" / "data" / "day.csv"
    lines = day.read_text().splitlines()
    lines[10] = ",".join(lines[10].split(",")[:-1])
    day.write_text("\n".join(lines) + "\n")
    # the lock would refuse the changed bytes first: lock the changed file
    lock_path = examples_copy / "bike_day" / "data-sources.lock.json"
    lock = json.loads(lock_path.read_text())
    lock["sources"][0]["sha256"] = sha256(day)
    lock["sources"][0]["size_bytes"] = day.stat().st_size
    lock_path.write_text(json.dumps(lock))
    code, out, _ = run_cli(
        "data", "verify", "--workload", "bike_day", "--examples-dir", str(examples_copy), "--json"
    )
    assert code == 3
    error = json.loads(out)["error"]
    assert error["code"] == "DATA_CHECK_FAILED"
    assert error["details"]["column"] and error["details"]["date"]


def test_a_missing_examples_directory_is_an_invalid_input_not_an_infrastructure_failure(tmp_path):
    code, out, _ = run_cli("data", "verify", "--examples-dir", str(tmp_path / "nope"), "--json")
    assert code == 2
    error = json.loads(out)["error"]
    assert set(error) == {"code", "message", "stage", "details"}
    assert error["code"] == "EXAMPLES_DIR_NOT_FOUND"
    assert error["stage"] == "config"
    assert error["details"] == {"examples_dir": str(tmp_path / "nope")}


@pytest.mark.parametrize(
    ("state", "said"),
    [
        ("missing", "does not exist"),
        ("dangling_link", "is a link whose target does not exist"),
        ("file", "exists but is not a directory"),
        ("empty_directory", "exists but holds no Workload lock"),
        ("directory_without_lock", "exists but holds no Workload lock"),
        ("valid", None),
    ],
)
def test_the_resolver_states_only_what_it_observed_of_the_default_examples_and_never_calls_it_a_checkout(tmp_path, monkeypatch, state, said):
    # 10-R2-02 (rounds 2 and 3, #23 B): the four facts, each naming --examples-dir; code, exit 2 and details are those of every refusal.
    from hypotrail.core import data

    default = tmp_path / "somewhere" / "examples"
    default.parent.mkdir()
    if state == "dangling_link":
        default.symlink_to(tmp_path / "no-such-target", target_is_directory=True)
    elif state == "file":
        default.write_text("not a directory")
    elif state in ("empty_directory", "directory_without_lock"):
        default.mkdir()
        if state == "directory_without_lock":
            (default / "a_workload").mkdir()
    elif state == "valid":
        (default / "a_workload").mkdir(parents=True)
        (default / "a_workload" / data.LOCK_NAME).write_text("{}")
    monkeypatch.setattr(data, "default_examples_dir", lambda: default)
    if said is None:
        assert data.resolve_examples_dir(None) == default
        return
    code, out, _ = run_cli("data", "verify", "--json")
    assert code == 2
    error = json.loads(out)["error"]
    assert (error["code"], error["stage"], error["details"]) == ("EXAMPLES_DIR_NOT_FOUND", "config", {"examples_dir": str(default)})
    assert said in error["message"] and "--examples-dir" in error["message"]
    assert "source checkout" not in error["message"]
    others = {"does not exist", "is a link whose target does not exist", "exists but is not a directory", "exists but holds no Workload lock"}
    assert not any(other in error["message"] for other in others if other not in said)  # one fact, the observed one


@pytest.mark.parametrize(
    "argv",
    [
        ["data", "verify", "--bogus", "--json"],
        ["--json", "data", "verify", "--examples-dir"],
        ["spike", "live", "--json"],  # --out is required
        ["spike", "live", "--out", "x", "--repeats", "many", "--json"],
        ["--json", "nonsense"],
    ],
)
def test_an_argument_error_with_json_is_one_object_on_stdout_and_exit_2(argv):
    code, out, err = run_cli(*argv)
    assert code == 2
    report = json.loads(out)
    assert report["ok"] is False
    assert set(report["error"]) == {"code", "message", "stage", "details"}
    assert report["error"]["code"] == "INVALID_ARGUMENTS"
    assert report["error"]["message"]
    assert err  # the human diagnostic stays on stderr


def test_an_argument_error_without_json_keeps_stdout_empty_and_exits_2():
    code, out, err = run_cli("data", "verify", "--bogus")
    assert code == 2
    assert out == ""
    assert "usage:" in err and "--bogus" in err
