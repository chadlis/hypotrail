"""Ticket #276: the `file_relayed` channel, and the level of a Decision derived when the Study is read.

ADR 0006, point 2: "`words.channel` keeps `panel`, `choice` and `chat_relayed`, and gains `file_relayed`: the caller read the words from a
file and relays them." D-172 on chadlis/hypotrail#75, as the ticket's amendment states it: a `file_relayed` Decision without `source` is
refused (`INVALID_ARGUMENTS`, exit 2, nothing written). The levels of ADR 0006, point 4, strongest first: `pr`, `panel`, `relayed`,
`undeclared`; a `proxy` Decision is off the scale. No model is called.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from _study_helpers import before_resampling_examples, init_study, run_cli, run_json
from test_write_sequence import entries, seq, tree

from hypotrail.core.decisions import PENDING_OPTIONS, PENDING_QUESTION

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = json.loads((ROOT / "clients" / "vscode" / "contract.json").read_text(encoding="utf-8"))
QUESTION = PENDING_QUESTION["text"]
CANDIDATE = next(option["text"] for option in PENDING_OPTIONS if option["id"] == "keep_candidate")
IDS = ("--question-id", "keep_after_comparison", "--option-id", "keep_candidate")
# The French quotation marks are written as escapes: no file under `tests/` holds them as characters.
WORDS = 'Keep the candidate, as Zoë wrote « on garde le candidat » : it is "better".\nThat is all.\n'
JOB = "job:https://github.com/example/kit/actions/runs/123456789;actor=evaluator-bot"
PULL = "https://github.com/example/kit/pull/12@" + "0123456789abcdef" * 2 + "01234567"
# A `decision/2` record that `decide` wrote at `3109b8c`, before `file_relayed` existed, on a Bike Study made by `init` there on the Workload
# of before `resampling`; it cites that Study's References set.
BEFORE = Path(__file__).resolve().parent / "fixtures" / "decision_2_before_file_relayed"
[BEFORE_FILE] = sorted(BEFORE.glob("*.json"))
BEFORE_RECORD = json.loads(BEFORE_FILE.read_text(encoding="utf-8"))


@pytest.fixture
def fresh(tmp_path):
    """A Bike Study just made by `init`, and the id of its References set, which a Decision may cite."""
    study, payload = init_study(tmp_path)
    return study, payload["references_id"]


def decide(study, cited, *extra, request_id="f-1", author="human"):
    flags = ["--study", study, "--question", QUESTION, "--option", CANDIDATE, "--author", author, "--artifact", cited]
    return run_json("decide", *flags, "--request-id", request_id, "--read-sequence", seq(study), *extra)


def words_file(folder: Path) -> Path:
    path = Path(folder) / "words.txt"
    path.write_bytes(WORDS.encode("utf-8"))
    return path


def test_decide_with_channel_file_relayed_a_words_file_and_a_source_records_the_words_whole_and_the_source_as_given(fresh, tmp_path):
    study, cited = fresh
    path = words_file(tmp_path)
    code, payload, err = decide(study, cited, *IDS, "--words-file", path, "--channel", "file_relayed", "--source", JOB)
    assert code == 0, (payload, err)
    [file] = sorted((study / "decisions").glob("*.json"))
    record = json.loads(file.read_text(encoding="utf-8"))
    assert record["words"] == {"texts": [WORDS], "channel": "file_relayed", "by": None, "authenticated": False}
    assert record["words"]["texts"][0].encode("utf-8") == path.read_bytes()
    assert (record["source"], record["author"], record["schema_version"]) == (JOB, "human", "decision/2")
    assert payload["decision"] == record


@pytest.mark.parametrize("source", [None, ""], ids=["no --source", "an empty --source"])
@pytest.mark.parametrize("words", ["file", "text"])
def test_decide_with_channel_file_relayed_and_no_source_is_refused_with_invalid_arguments_and_writes_nothing(source, words, fresh, tmp_path):
    study, cited = fresh
    given = ("--words-file", words_file(tmp_path)) if words == "file" else ("--words", WORDS)
    journal, files = entries(study), tree(study)
    extra = (*given, "--channel", "file_relayed") + (() if source is None else ("--source", source))
    code, payload, err = decide(study, cited, *extra)
    assert payload["ok"] is False, payload
    error = payload["error"]
    assert (code, error["code"], error["details"]) == (2, "INVALID_ARGUMENTS", {"command": "hypotrail decide"}), payload
    assert "--source" in error["message"] and "file_relayed" in error["message"], error["message"]
    assert entries(study) == journal and tree(study) == files


# (the flags of the Decision, its author) and the level `status --json` derives for it.
LEVELS = {
    "channel panel": ((*IDS, "--words", "keep it", "--channel", "panel"), "human", "panel"),
    "channel choice": ((*IDS, "--channel", "choice"), "human", "panel"),
    "channel chat_relayed": (("--words", "keep it"), "human", "relayed"),
    "channel file_relayed with the job's run": (("--words", "keep it", "--channel", "file_relayed", "--source", JOB), "human", "relayed"),
    "channel file_relayed with a pull request": (("--words", "keep it", "--channel", "file_relayed", "--source", PULL), "human", "pr"),
    "channel panel with a pull request": (("--words", "keep it", "--channel", "panel", "--source", PULL), "human", "pr"),
    "no words": ((), "human", "undeclared"),
    "no words with a pull request": (("--source", PULL), "human", "pr"),
    "no words with a source that is no citation": (("--source", "the owner, in chat"), "human", "undeclared"),
    "a merge commit of 39 hex digits": (("--words", "keep it", "--source", PULL[:-1]), "human", "relayed"),
    "a merge commit in capitals": (("--words", "keep it", "--source", PULL.upper().replace("HTTPS://GITHUB.COM", "https://github.com").replace("/PULL/", "/pull/")), "human", "relayed"),
    "text after the merge commit": (("--words", "keep it", "--source", PULL + " merged"), "human", "relayed"),
    "a pull request with no merge commit": (("--words", "keep it", "--source", PULL.split("@")[0]), "human", "relayed"),
    "a proxy": (("--source", "rule: the lower MAE"), "proxy", None),
    "a proxy that cites a pull request": (("--source", PULL), "proxy", None),
}


@pytest.mark.parametrize("case", list(LEVELS))
def test_status_derives_the_level_of_each_decision_from_its_channel_and_a_pull_request_cited_in_its_source(case, fresh):
    study, cited = fresh
    extra, author, level = LEVELS[case]
    code, payload, err = decide(study, cited, *extra, author=author)
    assert code == 0, (payload, err)
    [file] = sorted((study / "decisions").glob("*.json"))
    stored = file.read_bytes()
    code, listing, err = run_json("status", "--study", study)
    assert code == 0, (listing, err)
    [row] = listing["decisions"]
    assert "level" in row and row["level"] == level, row.get("level")
    assert "level" not in json.loads(stored) and file.read_bytes() == stored  # derived when read, never stored


def test_a_file_relayed_decision_read_back_through_status_and_the_panels_read_holds_its_words_channel_source_and_level(fresh, tmp_path):
    study, cited = fresh
    path = words_file(tmp_path)
    code, payload, err = decide(study, cited, *IDS, "--words-file", path, "--channel", "file_relayed", "--source", JOB)
    assert code == 0, (payload, err)
    decision_id = payload["decision"]["decision_id"]

    code, listing, err = run_json("status", "--study", study)
    assert code == 0, (listing, err)
    panel = [argument.replace("{path}", str(study)).replace("{n}", "0") for argument in CONTRACT["read_arguments"]]
    code, out, err = run_cli(*panel)
    assert code == 0, (out, err)
    for read in (listing, json.loads(out)):
        [row] = [row for row in read["decisions"] if row["decision_id"] == decision_id]
        assert row["words"] == {"texts": [WORDS], "channel": "file_relayed", "by": None, "authenticated": False}
        assert row["words"]["texts"][0].encode("utf-8") == path.read_bytes()
        assert (row["source"], row["author"], row["applies"]) == (JOB, "human", True)
        assert row.get("level") == "relayed", row.get("level")


def test_a_decision_2_record_written_before_file_relayed_is_listed_as_stored_replays_and_keeps_its_digest(tmp_path):
    study, _ = init_study(tmp_path, examples=before_resampling_examples(tmp_path))
    (study / "decisions").mkdir()
    shutil.copyfile(BEFORE_FILE, study / "decisions" / BEFORE_FILE.name)
    kept = BEFORE_FILE.read_bytes()
    digest = hashlib.sha256(kept).hexdigest()

    code, listing, err = run_json("status", "--study", study)
    assert code == 0, (listing, err)
    [row] = listing["decisions"]
    assert {key: value for key, value in row.items() if key not in ("applies", "reasons", "evidence_change", "level")} == BEFORE_RECORD
    assert row.get("level") == "relayed", row.get("level")

    flags = ["--study", study, "--question", BEFORE_RECORD["question"], "--option", BEFORE_RECORD["option"], "--author", "human"]
    flags += ["--source", BEFORE_RECORD["source"], "--artifact", *BEFORE_RECORD["cited_ids"], "--words", *BEFORE_RECORD["words"]["texts"]]
    flags += ["--by", BEFORE_RECORD["words"]["by"], "--request-id", BEFORE_RECORD["request_id"], "--read-sequence", seq(study)]
    code, payload, err = run_json("decide", *flags)
    assert code == 0, (payload, err)
    assert (payload["replayed"], payload["decision"]) == (True, BEFORE_RECORD)

    code, listing, err = run_json("status", "--study", study)
    assert code == 0, (listing, err)
    [entry] = [entry for entry in listing["record_files"] if entry.get("id") == BEFORE_RECORD["decision_id"]]
    assert hashlib.sha256((study / entry["path"]).read_bytes()).hexdigest() == digest
