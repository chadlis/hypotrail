"""Ticket #244: a Study that holds a `decision/1` record and `decision/2` records.

The kept `decision/1` record (`tests/fixtures/decision_1/`) was recorded by `decide` at `39fdc92`, on a Bike Study made by `init` there; it
cites that Study's References set. A record of `decision/1` still reads, still replays and is never rewritten. No model is called.
"""

import json
import shutil
from pathlib import Path

from _study_helpers import before_resampling_examples, init_study, run_json
from test_write_sequence import seq

KEPT = Path(__file__).resolve().parent / "fixtures" / "decision_1"
[KEPT_FILE] = sorted(KEPT.glob("*.json"))
RECORD = json.loads(KEPT_FILE.read_text(encoding="utf-8"))


def holding_both(tmp_path) -> Path:
    """A Bike Study whose StudySpec is the one the kept `decision/1` record names: made on the Workload of before `resampling`."""
    study, _ = init_study(tmp_path, examples=before_resampling_examples(tmp_path))
    (study / "decisions").mkdir()
    shutil.copyfile(KEPT_FILE, study / "decisions" / KEPT_FILE.name)
    return study


def kept_decide(study, *extra, request_id=RECORD["request_id"]):
    flags = ["--study", study, "--question", RECORD["question"], "--option", RECORD["option"], "--author", RECORD["author"], "--source", RECORD["source"]]
    flags += [part for cited in RECORD["cited_ids"] for part in ("--artifact", cited)]
    return run_json("decide", *flags, "--request-id", request_id, "--read-sequence", seq(study), *extra)


def test_a_decision_1_record_is_listed_as_stored_replays_conflicts_on_words_and_stays_byte_identical_beside_a_decision_2(tmp_path):
    study = holding_both(tmp_path)
    kept = KEPT_FILE.read_bytes()

    code, listing, err = run_json("status", "--study", study)
    assert code == 0, (listing, err)
    [row] = listing["decisions"]
    assert {key: value for key, value in row.items() if key not in ("applies", "reasons", "evidence_change")} == RECORD
    assert "words" not in row and RECORD["schema_version"] == "decision/1"

    code, payload, err = kept_decide(study)
    assert code == 0, (payload, err)
    assert (payload["replayed"], payload["decision"]) == (True, RECORD)

    words = tmp_path / "words.txt"
    words.write_text("Keep the candidate, please.", encoding="utf-8")
    code, payload, err = kept_decide(study, "--words-file", words)
    assert (code, payload["error"]["code"], payload["error"]["details"]["differs"]) == (6, "REQUEST_CONFLICT", ["words"]), payload

    code, payload, err = kept_decide(study, request_id="beside-it")
    assert code == 0, (payload, err)
    assert (payload["replayed"], payload["decision"]["schema_version"]) == (False, "decision/2")

    code, listing, err = run_json("status", "--study", study)
    assert [row["schema_version"] for row in listing["decisions"]] == ["decision/1", "decision/2"]
    assert (study / "decisions" / KEPT_FILE.name).read_bytes() == kept
