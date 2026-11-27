"""The ranking Track's contract page, `docs/contracts/ranking-track.md`, against the files it describes.

The page states six points, each with its sources; its table of refused cases and its list of the keys `ranking-build/1` requires are the
ones the contract directory holds. No model is called.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "contracts" / "ranking-track.md"
CONTRACT = ROOT / "src" / "hypotrail" / "ml" / "contracts" / "ml-scores-1"
ADR = ROOT / "docs" / "adr" / "0008-the-ranking-track.md"
# A source the page cites: a Decision on the decision log, or an issue or pull request of one of the three repositories.
CITATION = re.compile(r"D-\d{3} on chadlis/hypotrail#75|chadlis/(hypotrail|mlkit|agentkit)#\d+|ADR \d{4}")


def page_text():
    return PAGE.read_text(encoding="utf-8")


def sections(text, level):
    """{heading: body} for each heading of `level` hashes, the body running to the next heading of that level or higher."""
    found = {}
    parts = re.split(rf"^(#{{1,{level}}} .*)$", text, flags=re.M)
    for heading, body in zip(parts[1::2], parts[2::2]):
        if heading.startswith("#" * level + " "):
            found[heading[level + 1:].strip()] = body
    return found


def cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def test_the_page_states_points_one_to_six_in_order_each_with_a_sources_line_that_cites_a_source():
    numbered = [(heading, body) for heading, body in sections(page_text(), 2).items() if re.match(r"\d+\. ", heading)]
    assert [heading.split(".")[0] for heading, _ in numbered] == ["1", "2", "3", "4", "5", "6"]
    for heading, body in numbered:
        sources = [line for line in body.splitlines() if line.startswith("Sources:")]
        assert len(sources) == 1 and CITATION.search(sources[0]), f"{heading} has no Sources line that cites a source"


def test_the_pages_table_of_refused_cases_is_the_contracts_expected_files_and_names_an_m1_test_for_each():
    [table] = [body for heading, body in sections(page_text(), 3).items() if heading == "The refused cases"]
    rows = [cells(line) for line in table.splitlines() if line.startswith("| `")]
    listed = {row[0].strip("`"): (row[1].strip("`"), row[2].strip("`"), int(row[3]), row[4].strip("`")) for row in rows}
    expected = {}
    for path in sorted((CONTRACT / "examples" / "refused").glob("*/expected.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        expected[path.parent.name] = (record["contract"], record["code"], record["exit"], record["caught_by"])
    assert listed == expected
    assert all(row[5].startswith("`tests/") for row in rows), "each refused case names the M1 test that runs it through the command"


def test_the_pages_list_of_required_build_keys_is_the_one_ranking_build_requires():
    loaded = json.loads((CONTRACT / "ranking-build.schema.json").read_text(encoding="utf-8"))
    required = set(loaded["required"]) - {"source"} | {f"source.{key}" for key in loaded["properties"]["source"]["required"]}
    entry = set(loaded["properties"]["files"]["additionalProperties"]["required"])
    lines = page_text().splitlines()
    [keys] = [line for line in lines if line.startswith("Required keys:")]
    [entry_keys] = [line for line in lines if line.startswith("Each entry of `files` requires:")]
    assert set(re.findall(r"`([^`]+)`", keys)) == required
    assert set(re.findall(r"`([^`]+)`", entry_keys.split(":", 1)[1])) == entry


def test_the_page_says_ml_scores_leaves_y_pred_raw_out_and_names_the_m1_test_that_refuses_it():
    [body] = [body for heading, body in sections(page_text(), 3).items() if heading == "`y_pred_raw`"]
    assert "leaves it out" in body and "`MAPPING_KEY_UNKNOWN`" in body
    assert re.search(r"^M1 test: `tests/[^`]+`", body, re.M)


def test_the_contract_readme_no_longer_says_draft_and_the_changelog_and_the_readme_record_the_acceptance():
    readme = (CONTRACT / "README.md").read_text(encoding="utf-8")
    assert not re.search(r"\bdraft\b", readme, re.I)
    assert "chadlis/hypotrail#277" not in readme
    rows = [cells(line) for line in (ROOT / "docs" / "contracts" / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if line.startswith("| 20")]
    accepted = [row for row in rows if "`ranking-build/1`" in row[1] and "M0" in row[3]]
    assert len(accepted) == 1 and all(name in accepted[0][1] for name in ("`ml-scores/1`", "`ranking-items/1`", "`ranking-reference/1`"))
    assert accepted[0][2] == "1"
    assert "is a draft until" not in (ROOT / "README.md").read_text(encoding="utf-8")


def test_adr_0008_is_accepted_and_links_the_page_which_links_it_back():
    adr = ADR.read_text(encoding="utf-8")
    assert "Status: accepted" in adr and "(../contracts/ranking-track.md)" in adr
    assert "(../adr/0008-the-ranking-track.md)" in page_text()
