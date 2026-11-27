"""The guide's tool list and rules, and its demonstration Bike path on the real CLI."""

import json
import re

import pytest
from test_run_tool_end_to_end import CLIENT, after, ok, the_tool

AGENT = CLIENT / "hypotrail-guide.agent.md"
BUILT_INS = {"read", "search"}
GUIDE_TOOL_IDS = {"hypotrail_read_study", "hypotrail_run"}
RULES = (
    "Read the Study with `hypotrail_read_study` at the start of every turn.",
    "Explain a step with the exact `lesson` card returned for it.",
    "If there is no card for the step, say so and do not write an explanation of your own.",
    "For a number from a Study record, say where to find it in the panel without copying the value into chat.",
    "Only the person records their choice, with Record in the panel.",
    "You may draft their wording, but always identify a draft or relay as such and never present it as the person's act.",
    "Never read or run anything on `public_check`.",
    "Never start a paid live run.",
    "For concepts, link to the corresponding pages of the learning booklet at the pinned commit below.",
    "When a kit is in the workspace, read its commands from its C6 `kit-status/1` output.",
)


def front_matter(source):
    opening, header, instructions = source.split("---\n", 2)
    assert opening == ""
    # The tools field uses a JSON array, which is also a YAML flow sequence.
    [tool_list] = [line.removeprefix("tools: ") for line in header.splitlines() if line.startswith("tools: ")]
    tools = json.loads(tool_list)
    assert isinstance(tools, list) and all(isinstance(tool, str) for tool in tools)
    assert len(tools) == len(set(tools))
    return set(tools), instructions


def contributed_tool_ids():
    manifest = json.loads((CLIENT / "package.json").read_text(encoding="utf-8"))
    return {tool["toolReferenceName"]: tool["name"] for tool in manifest["contributes"]["languageModelTools"]}


def allowed_tools(source):
    tools, _ = front_matter(source)
    references = contributed_tool_ids()
    assert tools == BUILT_INS | {alias for alias, tool_id in references.items() if tool_id in GUIDE_TOOL_IDS}


def test_the_guide_agent_reaches_no_act_writer():
    source = AGENT.read_text(encoding="utf-8")
    allowed_tools(source)
    for planted in ("hypotrail_decide", "hypotrailDecide", "execute", "execute/runInTerminal", "edit", "edit/editFiles"):
        mutated, count = re.subn(r"(?m)^(tools: \[.*)\]$", rf'\1, "{planted}"]', source)
        assert count == 1
        with pytest.raises(AssertionError):
            allowed_tools(mutated)


def test_every_tool_named_exists():
    tools, _ = front_matter(AGENT.read_text(encoding="utf-8"))
    assert tools <= BUILT_INS | contributed_tool_ids().keys()


def test_the_instructions_hold_each_rule():
    _, instructions = front_matter(AGENT.read_text(encoding="utf-8"))
    for rule in RULES:
        assert rule in instructions
    text = re.sub(r"https://[^)\s]+", "", instructions).replace("C6 `kit-status/1`", "")
    assert not re.search(r"\d", text)
    assert not re.search(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", text, re.IGNORECASE)


def test_booklet_links_are_pinned():
    _, instructions = front_matter(AGENT.read_text(encoding="utf-8"))
    # The guide only links outside the workspace for the booklet.
    urls = re.findall(r"https?://[^)\s]+", instructions)
    assert len(urls) >= 2
    assert all(re.fullmatch(r"https://github\.com/chadlis/hypotrail-learning/blob/[0-9a-f]{40}/\S+", url) for url in urls)


def test_the_guide_agent_tools_drive_bike_to_its_pending_decision(tmp_path):
    study = tmp_path / "l1-bike"
    references = ok("init", "--workload", "bike_day", "--study", study, "--json")["references_id"]
    words = "Synthetic panel fixture from the guide test."

    def read(expected_cards):
        answer = the_tool(tmp_path, {"study": str(study)}, tool="hypotrail_read_study")
        text, cards_text = answer["text"].split("\nThe lesson cards of the Study, ", 1)
        status = after(text, "as the CLI's read printed it:\n")
        lesson = after(cards_text, "each explains a kind of step the Study shows:\n")
        assert answer["calls"] == [["status", f"--study={study}", "--json"], ["lesson", f"--study={study}", "--json"]]
        assert lesson["write_sequence"] == status["write_sequence"]
        assert [card["kind"] for card in lesson["cards"]] == expected_cards
        assert all(card["text"] and card["key_paths"] for card in lesson["cards"])
        assert status["ok"] and lesson["ok"]
        return status

    def run(command, *arguments):
        status = read([])
        assert status["pending_decisions"] == []
        assert status["decisions"] == []
        answer = the_tool(tmp_path, {"study": str(study), "command": command, "arguments": list(arguments), "read_sequence": status["write_sequence"]})
        assert all(call[0] in {command, "status"} for call in answer["calls"])
        [write] = [call for call in answer["calls"] if call[0] == command]
        assert f"--read-sequence={status['write_sequence']}" in write
        payload = after(answer["text"], "It printed:\n")
        assert payload["ok"]
        return payload

    # The ML Track provides cards for Comparisons and Decisions. The earlier reads carry an empty list.
    observed = {
        config: run("run", "ml", f"--config={config}", "--partition=dev", f"--request-id=guide-{config}")["observation_set_id"]
        for config in ("seasonal_7", "ridge_v1")
    }
    assessments = {
        config: run("assess", f"--observations={observation}", "--scorer=regression_mae_v1", f"--references={references}")["assessment"]["assessment_id"]
        for config, observation in observed.items()
    }
    comparison = run("compare", f"--control={assessments['seasonal_7']}", f"--candidate={assessments['ridge_v1']}")["comparison"]["comparison_id"]
    pending = read(["comparisons"])
    assert pending["decisions"] == []
    [question] = pending["pending_decisions"]
    assert question["comparison_id"] == comparison

    # Simulate the panel's Record control in a temporary Study, with synthetic words.
    panel = the_tool(tmp_path, {"words": words}, panel_record=True)
    [record] = [call for call in panel["calls"] if call[0] == "decide"]
    assert set(record[1:]) >= {
        f"--study={study}",
        f"--question-id={question['question']['id']}",
        f"--option-id={question['options'][0]['id']}",
        f"--artifact={comparison}",
        f"--read-sequence={pending['write_sequence']}",
        f"--words={words}",
        "--author=human",
        "--channel=panel",
        "--json",
    }
    assert re.fullmatch(r'<a href="[^"]+" data-recorded>', panel["text"])
    decided = read(["comparisons", "decisions"])
    assert decided["pending_decisions"] == []
    assert decided["write_sequence"] == pending["write_sequence"] + 2  # begin and wrote entries for one Decision
    [decision] = decided["decisions"]
    assert decision["question_id"] == question["question"]["id"]
    assert decision["option_id"] == question["options"][0]["id"]
