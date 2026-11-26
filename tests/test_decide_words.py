"""Ticket #244: `decide` records the ids of the pending decision and the person's words, in a `decision/2` record.

D-149 on chadlis/hypotrail#75 settles what is tested here: `--question-id` and `--option-id` are checked against the core's ids and texts;
`--words` and `--words-file` are stored whole, with a `channel` that defaults to `chat_relayed` and `authenticated` false; words need
`--author human`. No model is called.
"""

from pathlib import Path

import pytest
from _study_helpers import run_cli, run_json
from test_decide import (  # noqa: F401 (`exposed` and `study` are fixtures)
    decide,
    decision_files,
    error_of,
    exposed,
    held,
    made,
    read,
    study,
)
from test_write_sequence import entries, seq, tree

from hypotrail.core.decisions import PENDING_OPTIONS, PENDING_QUESTION

QUESTION = PENDING_QUESTION["text"]
CANDIDATE = next(option["text"] for option in PENDING_OPTIONS if option["id"] == "keep_candidate")
CONTROL = next(option["text"] for option in PENDING_OPTIONS if option["id"] == "keep_control")
# The French quotation marks are written as escapes: no file under `tests/` holds them as characters.
FIRST = 'We keep the candidate, as Zo\u00eb said \u00ab on garde le candidat \u00bb\u202f: it\'s "better" on dev.\nThat is all.'
SECOND = "  And the control stays for the record.  \n"


def words_file(folder: Path, name: str, text: str) -> Path:
    path = Path(folder) / name
    path.write_bytes(text.encode("utf-8"))
    return path


def with_words(study, *extra, request_id="w-1", read_sequence=None, question=QUESTION, option=CANDIDATE, author="human", cited=None):
    """`decide` on the command line with the core's texts, a cited Comparison and the flags of `extra`."""
    flags = [
        "--study", study, "--question", question, "--option", option, "--author", author, "--request-id", request_id,
        "--read-sequence", seq(study) if read_sequence is None else read_sequence,
    ]
    for cited_id in cited or [held(study)["comparison"]]:
        flags += ["--artifact", cited_id]
    return run_json("decide", *flags, *extra)


IDS = ("--question-id", "keep_after_comparison", "--option-id", "keep_candidate")


def test_decide_with_the_ids_two_words_files_and_by_records_the_texts_byte_for_byte_in_order_as_chat_relayed(study, tmp_path):
    first, second = words_file(tmp_path, "first.txt", FIRST), words_file(tmp_path, "second.txt", SECOND)
    code, payload, err = with_words(study, *IDS, "--words-file", first, "--words-file", second, "--by", "the owner")
    assert code == 0, (payload, err)
    [file] = decision_files(study)
    record = read(file)
    assert record["schema_version"] == "decision/2"
    assert (record["question_id"], record["option_id"]) == ("keep_after_comparison", "keep_candidate")
    assert record["words"] == {"texts": [FIRST, SECOND], "channel": "chat_relayed", "by": "the owner", "authenticated": False}
    assert [text.encode("utf-8") for text in record["words"]["texts"]] == [first.read_bytes(), second.read_bytes()]
    assert {key: record[key] for key in ("question", "option", "author", "source", "cited_ids")} == {
        "question": QUESTION, "option": CANDIDATE, "author": "human", "source": None, "cited_ids": [held(study)["comparison"]],
    }
    assert payload["decision"] == record


def test_channel_choice_records_the_text_of_the_option_and_channel_panel_records_the_text_given(study):
    code, payload, err = with_words(study, *IDS, "--channel", "choice")
    assert code == 0, (payload, err)
    assert payload["decision"]["words"] == {"texts": [CANDIDATE], "channel": "choice", "by": None, "authenticated": False}
    code, payload, err = with_words(study, "--words", "keep it", "--channel", "panel", request_id="w-2")
    assert code == 0, (payload, err)
    assert payload["decision"]["words"] == {"texts": ["keep it"], "channel": "panel", "by": None, "authenticated": False}


def refused_cases(folder: Path) -> dict:
    latin = Path(folder) / "latin-1.txt"  # the test writes it before it gives it
    return {
        "a question id the core does not supply": dict(extra=("--question-id", "keep_forever", "--option-id", "keep_candidate")),
        "an option id the core does not supply": dict(extra=("--question-id", "keep_after_comparison", "--option-id", "keep_both")),
        "a question id without an option id": dict(extra=("--question-id", "keep_after_comparison")),
        "an option id without a question id": dict(extra=("--option-id", "keep_candidate")),
        "a question text that is not the core's for the id": dict(extra=IDS, question="Which one?"),
        "an option text that is not the core's for the id": dict(extra=IDS, option=CONTROL),
        "words with a proxy author": dict(extra=("--words", "keep it"), author="proxy"),
        "by without words": dict(extra=("--by", "the owner",)),
        "a channel without words": dict(extra=("--channel", "panel")),
        "channel choice without an option id": dict(extra=("--channel", "choice")),
        "channel choice with a text": dict(extra=(*IDS, "--channel", "choice", "--words", "keep it")),
        "an empty text": dict(extra=("--words", "")),
        "a words file that does not exist": dict(extra=("--words-file", Path(folder) / "none.txt")),
        "a words file that is not UTF-8": dict(extra=("--words-file", latin)),
    }


@pytest.mark.parametrize("case", list(refused_cases(Path("."))))
def test_each_wrong_use_of_the_new_options_is_refused_with_invalid_arguments_and_writes_nothing(case, study, tmp_path):
    (tmp_path / "latin-1.txt").write_bytes("Zo\u00eb".encode("latin-1"))
    given = refused_cases(tmp_path)[case]
    journal, files = entries(study), tree(study)
    code, payload, err = with_words(study, *given["extra"], **{key: value for key, value in given.items() if key != "extra"})
    error = error_of(payload)
    assert (code, error["code"], error["details"]) == (2, "INVALID_ARGUMENTS", {"command": "hypotrail decide"}), payload
    assert entries(study) == journal and tree(study) == files


def test_the_same_request_with_the_same_decision_and_words_is_a_replay_also_after_the_sequence_moved_on(study, tmp_path):
    words = words_file(tmp_path, "first.txt", FIRST)
    code, payload, err = with_words(study, *IDS, "--words-file", words, "--by", "the owner")
    assert code == 0, (payload, err)
    first, stale = payload["decision"], payload["decision"]["read_sequence"]
    made(study, request_id="bump")  # another write moves the sequence on
    files = tree(study)
    code, payload, err = with_words(study, *IDS, "--words", FIRST, "--by", "the owner", read_sequence=stale)
    assert code == 0, (payload, err)
    assert payload["replayed"] is True and payload["decision"] == first
    assert tree(study) == files


RECORDED = (*IDS, "--words", "the first", "--words", "the second", "--by", "the owner")


@pytest.mark.parametrize(
    "again, option, differs",
    [
        ((*IDS, "--words", "Other words.", "--by", "the owner"), CANDIDATE, ["words"]),
        ((*IDS, "--words", "the second", "--words", "the first", "--by", "the owner"), CANDIDATE, ["words"]),
        ((*RECORDED, "--channel", "panel"), CANDIDATE, ["words"]),
        ((*IDS, "--words", "the first", "--words", "the second", "--by", "someone else"), CANDIDATE, ["words"]),
        (("--question-id", "keep_after_comparison", "--option-id", "keep_control", *RECORDED[4:]), CONTROL, ["option", "option_id"]),
    ],
    ids=["other words", "the same texts in another order", "another channel", "another by", "another option id and its text"],
)
def test_the_same_request_with_other_words_a_channel_a_by_or_an_option_id_is_a_request_conflict_that_names_them(again, option, differs, study):
    code, payload, err = with_words(study, *RECORDED)
    assert code == 0, (payload, err)
    files = tree(study)
    code, payload, err = with_words(study, *again, option=option)
    error = error_of(payload)
    assert (code, error["code"]) == (6, "REQUEST_CONFLICT"), payload
    assert error["details"]["differs"] == differs
    assert tree(study) == files


def test_the_line_of_decide_names_the_count_of_texts_and_the_channel_and_no_character_of_a_text(study, tmp_path):
    first, second = words_file(tmp_path, "first.txt", "\u00e9\u00e9\u00e9"), words_file(tmp_path, "second.txt", "\u00e8\u00e8\u00e8")
    sequence = seq(study)
    code, out, err = run_cli(
        "decide", "--study", study, "--question", QUESTION, "--option", CANDIDATE, "--author", "human", "--artifact", held(study)["comparison"],
        "--request-id", "w-line", "--read-sequence", sequence, *IDS, "--words-file", first, "--words-file", second,
    )
    assert code == 0, (out, err)
    assert "(words: 2 texts, channel chat_relayed)" in out
    assert not {"\u00e9", "\u00e8"} & set(out)
