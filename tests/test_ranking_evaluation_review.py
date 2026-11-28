"""The evaluator's aggregate verdict and its separate confirmation in an ordinary Study."""

import json
from pathlib import Path

import pytest

from _ranking_helpers import initialize, ranking_paths
from _study_helpers import init_study, run_json
from test_run_tool_end_to_end import the_tool

OWNER_WORDS = "  I accept this ranking verdict.\nI checked the aggregate report.  "
QUESTION = "Confirm the protected ranking verdict"
QUESTION_ID = "confirm_ranking_verdict"
RECEIPT = {
    "schema_version": "ranking-evaluation-review/1",
    "proxy_decision_id": "62c0329b-45a0-4c4b-b3c0-3cf219538112",
    "comparison_id": "d3f599ab-35ab-40a2-b802-5c0b180ff362",
    "frame_digest": "a" * 64,
    "option": "accepted",
    "rule": "mlkit-ranking-acceptance@1",
    "source": "https://github.com/chadlis/hypotrail/issues/75#issuecomment-7235501369 frame_digest=" + "a" * 64,
    "delta": 0.02,
    "interval": [0.001, 0.036],
    "usable_resamples": 1000,
    "omitted_dates": 3,
}


@pytest.fixture
def review_study(ranking_paths):
    code, reported, err = initialize(ranking_paths)
    assert code == 0, (reported, err)
    return ranking_paths[-1]


def write_receipt(root, **changes):
    path = root / "review.json"
    path.write_text(json.dumps({**RECEIPT, **changes}), encoding="utf-8")
    return path


def status(study, *flags):
    code, payload, err = run_json("status", "--study", study, *flags)
    assert code == 0, (payload, err)
    return payload


def import_receipt(study, receipt, seq):
    return run_json("review", "import", "--study", study, "--receipt", receipt, "--read-sequence", seq)


def decide(study, cited, seq, request, *, author="human", question=QUESTION, option="accepted",
           channel="panel", words=OWNER_WORDS, typed=False, option_id="accepted"):
    argv = ["decide", "--study", study, "--artifact", cited, "--read-sequence", seq, "--request-id", request,
            "--question", question, "--option", option, "--author", author]
    if channel is not None:
        argv += ["--channel", channel, "--words", words]
    if typed:
        argv += ["--question-id", QUESTION_ID, "--option-id", option_id]
    return run_json(*argv)


def test_proxy_receipt_is_citable_and_only_matching_applying_panel_words_confirm_it(review_study, tmp_path):
    study = review_study
    input_path = write_receipt(tmp_path)
    before = status(study)
    sequence = before["write_sequence"]
    code, imported, err = import_receipt(study, input_path, sequence)
    assert code == 0, (imported, err)
    assert "ranking_reviews" not in before
    input_path.unlink()  # no read can depend on the file copied from the job

    after = status(study, "--since", sequence)
    [review] = after["ranking_reviews"]
    artifact_id = review["artifact_id"]
    assert review == {
        **{key: value for key, value in RECEIPT.items() if key != "schema_version"},
        "artifact_id": artifact_id,
        "question": QUESTION,
        "question_id": QUESTION_ID,
        "option_id": RECEIPT["option"],
        "pending": True,
    }
    assert imported["review"] == review
    assert after["decisions"] == before["decisions"] == []
    assert after["pending_decisions"] == before["pending_decisions"] == []
    assert after["exposures"] == before["exposures"]
    assert after["write_sequence"] == sequence + 2
    assert after["writes_since"] == [
        {"command": "review import", "phase": "begin", "request_id": None},
        {"command": "review import", "phase": "end", "request_id": None, "outcome": "completed",
         "written": [{"kind": "ranking_review", "id": artifact_id}]},
    ]
    for external_id in (review["proxy_decision_id"], review["comparison_id"]):
        code, payload, _ = decide(study, external_id, sequence + 2, "outside")
        assert (code, payload["error"]["code"]) == (2, "CITED_ID_NOT_FOUND")

    retries = (
        {"author": "proxy", "channel": None},
        {"channel": "chat_relayed"},
        {"question": "Another question"},
        {"option": "keep_control"},
        {"words": "  "},
        {},  # even matching free-text words are a separate decision, without the held question and option IDs
    )
    for index, options in enumerate(retries, 1):
        fresh = status(study)
        code, record, err = decide(study, artifact_id, fresh["write_sequence"], f"unrelated-{index}", **options)
        assert code == 0, (record, err)
        assert status(study)["ranking_reviews"] == [review]

    fresh = status(study)
    code, confirmed, err = decide(study, artifact_id, fresh["write_sequence"], "panel-record", typed=True)
    assert code == 0, (confirmed, err)
    end = status(study)
    assert end["ranking_reviews"] == [{**review, "pending": False}]
    assert end["write_sequence"] == fresh["write_sequence"] + 2
    assert confirmed["decision"]["words"] == {
        "channel": "panel", "texts": [OWNER_WORDS], "by": None, "authenticated": False,
    }
    assert confirmed["decision"]["question_id"] == QUESTION_ID
    assert confirmed["decision"]["option_id"] == "accepted"
    assert end["decisions"][-1]["applies"] is True


@pytest.mark.parametrize("change", [
    {"per_item": ["SYNTHETIC-NO-DIAGNOSTICS"]},
    {"source": "SYNTHETIC-NO-DIAGNOSTICS"},
    {"option": "SYNTHETIC-NO-DIAGNOSTICS"},
    {"rule": "SYNTHETIC-NO-DIAGNOSTICS"},
    {"proxy_decision_id": "SYNTHETIC-NO-DIAGNOSTICS"},
    {"comparison_id": RECEIPT["comparison_id"].upper()},
    {"frame_digest": "b" * 64},
    {"delta": float("inf")},
    {"delta": 1.001},
    {"interval": [0.04, 0.01]},
    {"interval": [-1.001, 0]},
    {"interval": [True, 0.9]},
    {"usable_resamples": True},
    {"omitted_dates": -1},
])
def test_refuses_untrusted_shape_and_source_without_echo_or_writes(review_study, tmp_path, change):
    seq = status(review_study)["write_sequence"]
    code, refused, err = import_receipt(review_study, write_receipt(tmp_path, **change), seq)
    assert (code, refused["error"]["code"]) == (2, "RANKING_REVIEW_INVALID")
    assert "SYNTHETIC-NO-DIAGNOSTICS" not in repr((refused, err))
    assert status(review_study)["write_sequence"] == seq


@pytest.mark.parametrize("contradiction", [
    {"option": "keep_control"},
    {"delta": 0.009999},
    {"delta": None},
    {"interval": [0, 0.036]},
    {"interval": [-0.001, 0.036]},
    {"interval": None, "usable_resamples": 0},
    {"usable_resamples": 2001},
    {"usable_resamples": 0},
    {"option": "keep_control", "interval": None},
])
def test_refuses_receipts_inconsistent_with_the_declared_rule_or_usable_draws(review_study, tmp_path, contradiction):
    seq = status(review_study)["write_sequence"]
    receipt = write_receipt(tmp_path, **contradiction)
    code, refused, _ = import_receipt(review_study, receipt, seq)
    assert (code, refused["error"]["code"]) == (2, "RANKING_REVIEW_INVALID")
    end = status(review_study)
    assert "ranking_reviews" not in end
    assert end["write_sequence"] == seq


def test_accepts_the_exact_delta_threshold_and_all_draws_usable(review_study, tmp_path):
    seq = status(review_study)["write_sequence"]
    receipt = write_receipt(tmp_path, delta=0.01, usable_resamples=2000)
    code, imported, err = import_receipt(review_study, receipt, seq)
    assert code == 0, (imported, err)
    assert imported["review"]["option"] == "accepted"
    assert imported["review"]["usable_resamples"] == 2000


def test_refuses_duplicate_json_key_without_echo(review_study, tmp_path):
    seq = status(review_study)["write_sequence"]
    path = tmp_path / "bad.json"
    path.write_text('{"SYNTHETIC-NO-DIAGNOSTICS":1,"SYNTHETIC-NO-DIAGNOSTICS":2}', encoding="utf-8")
    code, refused, err = import_receipt(review_study, path, seq)
    assert (code, refused["error"]["code"]) == (2, "RANKING_REVIEW_INVALID")
    assert "SYNTHETIC-NO-DIAGNOSTICS" not in repr((refused, err))
    assert status(review_study)["write_sequence"] == seq


def test_typed_ranking_confirmation_requires_a_matching_receipt_and_panel_words(review_study, tmp_path):
    seq = status(review_study)["write_sequence"]
    code, initial, err = import_receipt(review_study, write_receipt(tmp_path), seq)
    assert code == 0, (initial, err)
    review = initial["review"]
    for index, options in enumerate((
        {"author": "proxy", "channel": None},
        {"channel": "chat_relayed"},
        {"words": "  "},
        {"channel": None},
        {"question": "Another question"},
        {"option": "keep_control"},
        {"option": "keep_control", "option_id": "keep_control"},
    ), 1):
        code, refused, _ = decide(review_study, review["artifact_id"], seq + 2, f"bad-{index}", typed=True, **options)
        assert (code, refused["error"]["code"]) == (2, "INVALID_ARGUMENTS")
    code, refused, _ = decide(review_study, review["proxy_decision_id"], seq + 2, "external", typed=True)
    assert (code, refused["error"]["code"]) == (2, "CITED_ID_NOT_FOUND")
    end = status(review_study)
    assert end["ranking_reviews"] == [review]
    assert end["decisions"] == []
    assert end["write_sequence"] == seq + 2


def test_exact_reimport_is_a_noop_and_stale_import_is_refused(review_study, tmp_path):
    receipt = write_receipt(tmp_path, option="keep_control", delta=None, interval=None, usable_resamples=0)
    seq = status(review_study)["write_sequence"]
    code, initial, err = import_receipt(review_study, receipt, seq)
    assert code == 0, (initial, err)
    assert status(review_study)["write_sequence"] == seq + 2
    code, refused, _ = import_receipt(review_study, receipt, seq)
    assert (code, refused["error"]["code"]) == (6, "STUDY_CHANGED")
    code, existing, err = import_receipt(review_study, receipt, seq + 2)
    assert code == 0, (existing, err)
    assert existing["review"] == initial["review"]
    ending = status(review_study)
    assert ending["ranking_reviews"] == [initial["review"]]
    assert ending["write_sequence"] == seq + 2


def test_an_edited_stored_receipt_cannot_supply_evidence(review_study, tmp_path):
    seq = status(review_study)["write_sequence"]
    code, initial, err = import_receipt(review_study, write_receipt(tmp_path), seq)
    assert code == 0, (initial, err)
    artifact_id = initial["review"]["artifact_id"]
    [stored] = list((review_study / "artifacts" / "ranking-reviews").glob("*.json"))
    stored.write_bytes(stored.read_bytes() + b"\n")
    code, refused, _ = run_json("status", "--study", review_study)
    assert (code, refused["error"]["code"]) == (3, "RANKING_REVIEW_INTEGRITY")
    code, refused, _ = decide(review_study, artifact_id, seq + 2, "edited-artifact")
    assert (code, refused["error"]["code"]) == (3, "RANKING_REVIEW_INTEGRITY")


def test_a_different_receipt_cannot_replace_the_same_proxy_decision(review_study, tmp_path):
    seq = status(review_study)["write_sequence"]
    code, first, err = import_receipt(review_study, write_receipt(tmp_path), seq)
    assert code == 0, (first, err)
    other = write_receipt(tmp_path, option="keep_control", delta=-0.01, interval=[-0.02, 0])
    code, refused, _ = import_receipt(review_study, other, seq + 2)
    assert (code, refused["error"]["code"]) == (2, "RANKING_REVIEW_INVALID")
    end = status(review_study)
    assert end["ranking_reviews"] == [first["review"]]
    assert end["write_sequence"] == seq + 2


def test_protected_destination_is_refused_before_opening_receipt(review_study, tmp_path, monkeypatch):
    seq = status(review_study)["write_sequence"]
    receipt = write_receipt(tmp_path)
    header_path = review_study / "study.json"
    original_header = header_path.read_bytes()
    header_path.write_text(json.dumps({**json.loads(original_header), "partition": "held_out"}), encoding="utf-8")
    open_path = Path.open

    def guard(path, *args, **kwargs):
        if path == receipt:
            pytest.fail("a receipt must not be opened for a protected destination")
        return open_path(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", guard)
        code, refused, _ = import_receipt(review_study, receipt, seq)
        assert (code, refused["error"]["code"]) == (2, "RANKING_HELD_OUT_REFUSED")
        patch.setenv("GITHUB_ACTIONS", "true")
        patch.setenv("GITHUB_WORKFLOW_REF", "example/kit/.github/workflows/evaluator.yml@refs/heads/main")
        code, refused, _ = run_json(
            "--evaluator", "review", "import", "--study", review_study, "--receipt", receipt, "--read-sequence", seq,
        )
        assert (code, refused["error"]["code"]) == (2, "RANKING_HELD_OUT_REFUSED")
    header_path.write_bytes(original_header)
    assert status(review_study)["write_sequence"] == seq


def test_non_ranking_study_cannot_import_a_ranking_review(tmp_path):
    study, _ = init_study(tmp_path)
    before = status(study)
    assert "ranking_reviews" not in before
    code, refused, _ = import_receipt(study, write_receipt(tmp_path), before["write_sequence"])
    assert (code, refused["error"]["code"]) == (2, "UNSUPPORTED_CAPABILITY")
    assert status(study) == before


def test_panel_record_confirms_the_imported_receipt_in_the_real_study(review_study, tmp_path):
    receipt = write_receipt(tmp_path)
    before = status(review_study)
    code, imported, err = import_receipt(review_study, receipt, before["write_sequence"])
    assert code == 0, (imported, err)
    review = imported["review"]
    assert review["pending"] is True
    receipt.unlink()
    sequence = status(review_study)["write_sequence"]

    panel = the_tool(review_study.parent, {"words": OWNER_WORDS}, panel_record="ranking_review")
    assert "data-recorded" in panel["text"], panel
    assert panel["calls"][0][0] == "status"
    assert sum(call[0] == "decide" for call in panel["calls"]) == 1

    final = status(review_study, "--since", sequence)
    assert final["ranking_reviews"] == [{**review, "pending": False}]
    assert final["write_sequence"] == sequence + 2
    [decision] = final["decisions"]
    assert decision["applies"] is True
    assert decision["author"] == "human"
    assert decision["words"] == {"channel": "panel", "texts": [OWNER_WORDS], "by": None, "authenticated": False}
    for field in ("question", "question_id", "option", "option_id"):
        assert decision[field] == review[field]
    assert decision["cited_ids"] == [review["artifact_id"]]
    assert decision["read_sequence"] == sequence
    request_id = decision["request_id"]
    assert request_id
    assert final["writes_since"] == [
        {"command": "decide", "phase": "begin", "request_id": request_id},
        {
            "command": "decide", "phase": "end", "request_id": request_id, "outcome": "completed",
            "written": [{"kind": "decision", "id": decision["decision_id"]}],
        },
    ]
