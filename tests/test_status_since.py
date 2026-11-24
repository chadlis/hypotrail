"""`status --since N` (chadlis/hypotrail#195): the whole object of `status --json`, plus `writes_since`, the write-journal entries after
position N, in the shape of the `writes_since` detail of `STUDY_CHANGED`. The read takes no lock and writes nothing.

No model is called: the Bike Study is made of `run ml` Attempts, the Chinook Study of imports of the kit's answers.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from _client_helpers import chinook_pending_study, compared_study, decide
from _review_helpers import files
from _study_helpers import run_cli, run_json
from test_run_ml import killed
from test_study_lock import held_by_another_process

from hypotrail.core import study as layout

ROOT = Path(__file__).resolve().parent.parent
KEPT = ROOT / "docs" / "handbook" / "traces" / "campaign-public-check" / "study"
VALUES_REFUSED = ("-1", "x", "1.5")
# The top-level keys of `status --json` before `--since` existed.
STATUS_KEYS = {"ok", "study", "writer_alive", "revisions", "attempts", "freeze_records", "exposures", "check_informed", "write_sequence", "decisions", "declared_deviations", "assessments", "comparisons", "pending_decisions"}
BEGIN_KEYS, END_KEYS = {"phase", "command", "request_id"}, {"phase", "command", "request_id", "outcome", "written"}


@pytest.fixture(scope="module")
def studies(tmp_path_factory):
    """{name: folder} of the four fixture Studies: Bike, Chinook, a `run ml` killed between its two entries, and a copy of the kept Study written before the journal."""
    kept = tmp_path_factory.mktemp("kept") / "study"
    shutil.copytree(KEPT, kept)
    return {
        "bike": compared_study(tmp_path_factory.mktemp("bike")),
        "chinook": chinook_pending_study(tmp_path_factory.mktemp("chinook")),
        "killed": killed(tmp_path_factory.mktemp("killed"), kill_at=4)[0],
        "kept": kept,
    }


@pytest.fixture(scope="module")
def bike(studies):
    return studies["bike"]


def plain(study) -> dict:
    """The object of `status --json`, without `--since`."""
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    return payload


def sequence(study) -> int:
    return plain(study)["write_sequence"]


def stored_entries(study) -> list:
    """The write-journal entries as the files under `write_journal/` hold them, in position order."""
    folder = Path(study) / "write_journal"
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))] if folder.is_dir() else []


def answered(study, value) -> dict:
    code, payload, err = since(study, value)
    assert code == 0 and payload["ok"] is True, (payload, err)
    return payload


def since(study, value):
    """The exit code, the one JSON object and stderr of `status --study DIR --since VALUE --json`."""
    return run_json("status", "--study", study, "--since", value)


# --- the option and its value ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", VALUES_REFUSED)
def test_a_since_value_that_is_not_a_non_negative_integer_is_refused_as_invalid_arguments_before_the_study_is_read(bike, tmp_path, value):
    for study in (tmp_path / "no-study-here", bike):  # a folder that holds no Study first: the value is judged before the Study is read
        code, payload, err = since(study, value)
        assert code == 2 and payload["ok"] is False, (study, payload, err)
        assert (payload["error"]["code"], payload["error"]["stage"]) == ("INVALID_ARGUMENTS", "config"), (study, payload)


# --- a value above the Study's ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["bike", "chinook", "killed", "kept"])
def test_a_since_value_above_the_studys_write_sequence_is_refused_as_write_sequence_ahead_and_writes_nothing(studies, name):
    study = studies[name]
    before, current = files(study), sequence(study)
    code, payload, err = since(study, current + 1)
    assert code == 2 and payload["ok"] is False, (payload, err)
    error = payload["error"]
    assert (error["code"], error["stage"]) == ("WRITE_SEQUENCE_AHEAD", "sequence"), error
    assert error["details"] == {"read_sequence": current + 1, "write_sequence": current}
    assert files(study) == before


# --- the key `writes_since` ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["bike", "chinook"])
def test_writes_since_holds_the_stored_journal_entries_after_n_in_journal_order_for_every_n_up_to_the_write_sequence(studies, name):
    study = studies[name]
    stored = stored_entries(study)
    assert len(stored) == sequence(study) == 12
    for n in range(len(stored) + 1):
        payload = answered(study, n)
        assert payload["writes_since"] == stored[n:], n
        for entry in payload["writes_since"]:  # the journal's entries only: kinds and ids of what was written, no content of an artifact
            assert set(entry) == (BEGIN_KEYS if entry["phase"] == "begin" else END_KEYS), entry
            assert all(set(item) == {"kind", "id"} for item in entry.get("written", [])), entry
    assert answered(study, 12)["writes_since"] == [] and answered(study, 0)["writes_since"] == stored


def test_writes_since_equals_the_writes_since_detail_of_the_study_changed_refusal_of_a_write_on_the_same_value(bike):
    [comparison] = [p.name for p in (Path(bike) / "comparisons").iterdir()]
    before = files(bike)
    for n in range(12):
        code, out, err = decide(bike, "Keep the Control", f"stale-{n}", n, comparison)
        error = json.loads(out)["error"]
        assert (code, error["code"]) == (6, "STUDY_CHANGED"), (n, error)
        assert answered(bike, n)["writes_since"] == error["details"]["writes_since"], n
    assert files(bike) == before


def test_a_killed_writer_leaves_its_begin_entry_in_writes_since_and_a_study_written_before_the_journal_answers_0_with_none(studies):
    writes = answered(studies["killed"], 2)["writes_since"]
    assert [(entry["phase"], entry["command"]) for entry in writes] == [("begin", "run ml")], writes
    kept = studies["kept"]
    before = files(kept)
    payload = answered(kept, 0)
    assert (payload["write_sequence"], payload["writes_since"]) == (0, [])
    code, payload, err = since(kept, 1)
    assert (code, payload["error"]["code"]) == (2, "WRITE_SEQUENCE_AHEAD"), (payload, err)
    assert files(kept) == before


def test_write_sequence_and_writes_since_of_one_answer_agree_while_a_writer_appends_between_two_listings_of_the_journal(bike, tmp_path, monkeypatch):
    study = tmp_path / "study"
    shutil.copytree(bike, study)
    listed = layout.record_names

    def listing_then_an_append(folder_of_study, folder):
        """Each listing of the journal is followed by one more entry, as a writer that appends between two reads would leave it."""
        names = listed(folder_of_study, folder)
        if folder == "write_journal" and names:
            journal = Path(folder_of_study) / folder
            (journal / f"{len(names) + 1:06d}.json").write_bytes((journal / names[-1]).read_bytes())
        return names

    monkeypatch.setattr(layout, "record_names", listing_then_an_append)
    for n in (0, 5, 12):
        payload = answered(study, n)
        assert len(payload["writes_since"]) == payload["write_sequence"] - n, n
        assert payload["writes_since"] == stored_entries(study)[n : payload["write_sequence"]], n


# --- additions only -------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["bike", "chinook", "killed", "kept"])
def test_the_object_with_since_holds_every_key_of_status_json_with_the_same_value_and_writes_since_and_without_since_none(studies, name):
    study = studies[name]
    without = plain(study)
    assert set(without) == STATUS_KEYS and "writes_since" not in without
    for n in sorted({0, without["write_sequence"]}):
        payload = answered(study, n)
        assert set(payload) == STATUS_KEYS | {"writes_since"}, n
        for key in without:
            assert payload[key] == without[key], (n, key)


# --- a read writes nothing ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["bike", "chinook"])
def test_the_read_with_since_writes_nothing_keeps_the_write_sequence_and_answers_while_another_writer_holds_the_lock(studies, name):
    study = studies[name]
    before, current = files(study), sequence(study)
    answered(study, 0)
    assert files(study) == before  # its `exposures/` and `write_journal/` included
    assert sequence(study) == current
    with held_by_another_process(study):
        payload = answered(study, 0)
    assert payload["writer_alive"] is True
    assert files(study) == before


# --- the human form -------------------------------------------------------------------------------------------------------------


def test_without_json_the_answer_is_the_lines_of_status_then_the_count_of_entries_after_n_and_each_ones_position_and_command(bike):
    code, lines, err = run_cli("status", "--study", bike)
    assert code == 0, err
    code, out, err = run_cli("status", "--study", bike, "--since", 10)
    assert code == 0, err
    head, tail = out.splitlines()[: len(lines.splitlines())], out.splitlines()[len(lines.splitlines()) :]
    assert head == lines.splitlines()
    assert re.fullmatch(r"\b2 write-journal entries after 10\b.*", (tail or [""])[0]), tail
    assert [re.match(r"\s*(\d+) \w+ (.+?)(?: \(\w+\))?$", line).groups() for line in tail[1:]] == [("11", "compare"), ("12", "compare")], tail


def test_without_json_a_refused_since_value_gets_the_refusals_human_form(bike):
    code, out, err = run_cli("status", "--study", bike, "--since", 13)
    assert (code, out) == (2, "")
    assert err.startswith("WRITE_SEQUENCE_AHEAD [sequence]: "), err


def test_chapter_04s_example_of_the_human_form_ends_with_the_lines_the_cli_prints_after_the_lines_of_status_on_the_bike_study(bike):
    chapter = (ROOT / "docs" / "handbook" / "chapters" / "04-study-and-attempts.html").read_text(encoding="utf-8")
    [example] = [block for block in re.findall(r"<pre[^>]*>(.*?)</pre>", chapter, re.S) if "--since 10" in block]
    code, out, err = run_cli("status", "--study", bike, "--since", 10)
    assert code == 0, err
    assert example.splitlines()[-3:] == out.splitlines()[-3:]
