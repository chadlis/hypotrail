"""The panel's Record with the person's words, through the real CLI: the kept writes `panel-words` and `panel-no-words` under
`clients/vscode/test/cli/`, whose argument lists `clients/vscode/test/panel-write.test.ts` checks the panel gives the bridge.

The CLI is run in process on scratch Studies, offline.
"""

import json

import pytest
from _client_helpers import KEPT, PANEL_WORDS, PANEL_WRITES, first_difference, panel_write_outputs


@pytest.fixture(scope="module")
def written(tmp_path_factory):
    return panel_write_outputs(tmp_path_factory.mktemp("panel-writes"))


def test_each_kept_write_of_the_panels_record_is_the_clis_own_once_its_values_are_replaced(written):
    made, _ = written
    assert sorted(made) == sorted(PANEL_WRITES)
    for name, parts in made.items():
        for part, text in parts.items():
            kept = (KEPT / f"{name}.{part}").read_text(encoding="utf-8")
            if part in ("args", "out"):
                assert first_difference(json.loads(kept), json.loads(text)) is None, (name, part)
            else:
                assert kept == text, (name, part)


def test_the_record_of_the_panels_record_with_words_holds_the_box_text_byte_for_byte_the_channel_panel_no_by_and_the_two_ids(written):
    made, records = written
    record = records["panel-words"]
    assert record["schema_version"] == "decision/2"
    assert record["words"] == {"texts": [PANEL_WORDS], "channel": "panel", "by": None, "authenticated": False}
    assert record["words"]["texts"][0].encode("utf-8") == PANEL_WORDS.encode("utf-8")
    assert (record["question_id"], record["option_id"]) == ("keep_after_comparison", "keep_control")
    arguments = json.loads(made["panel-words"]["args"])["arguments"]
    assert not [argument for argument in arguments if argument.startswith("--by")]


def test_the_record_of_the_panels_record_with_the_box_empty_holds_no_words_and_the_two_ids_and_its_arguments_no_words_and_no_channel(written):
    made, records = written
    record = records["panel-no-words"]
    assert record["words"] is None
    assert (record["question_id"], record["option_id"]) == ("keep_after_comparison", "keep_control")
    arguments = json.loads(made["panel-no-words"]["args"])["arguments"]
    assert not [argument for argument in arguments if argument.startswith(("--words", "--channel", "--by"))]
