"""D-055 on chadlis/hypotrail#75, items 4 and 5b: sentences of the drive skill and of the builder's instructions that the decision words exactly."""

import re

from _drive_scripts import ROOT

SKILL = (ROOT / ".claude/skills/drive/SKILL.md").read_text()
BUILDER = (ROOT / ".claude/agents/slice-builder.md").read_text()
STOP_RULE = (
    "**Stop rule.** A later escape that code under `src/` actually uses is a blocker. "
    "An escape that is only planted is a stated limit, written down in the test's docstring and in the PR body."
)
REFUSAL = "When unsure whether a refusal targets the hook's rewrite or the change, treat it as refusing the change."


def test_the_line_on_a_criterion_that_quantifies_over_code_adds_one_sentence_that_quotes_the_stop_rule_of_d_054_word_for_word():
    line = next(line for line in SKILL.splitlines() if line.startswith("A criterion that quantifies over code"))
    sentence = f' When the quantifier ranges over uses of a name (calls through any alias, receiver or import), no static listing is complete: the Tightened line names the conventions that bound it and quotes D-054 on chadlis/hypotrail#75 word for word: "{STOP_RULE}"'
    assert line.endswith(sentence)
    assert SKILL.count("Stop rule.") == 1


def test_the_builder_treats_a_refusal_it_cannot_attribute_as_refusing_the_change_then_stops_and_hands_back():
    assert REFUSAL in BUILDER
    after = BUILDER.split(REFUSAL, 1)[1].split("\n", 1)[0]
    assert "stop and hand back with the refusal text" in after and "make the change with no other tool" in after


# The ceiling is the count of the skill when step 10 first stated it; raising it is a change of that row too.
WORD_CEILING = 14_802


def c_locale_word_count(text: str) -> int:
    """What `LC_ALL=C wc -w` counts: runs of bytes between ASCII whitespace that hold at least one printable ASCII character."""
    return sum(1 for word in text.encode("utf-8").split() if re.search(rb"[\x21-\x7e]", word))


def test_the_skill_states_its_word_ceiling_in_step_10_and_stays_at_or_under_it():
    row = next(line for line in SKILL.splitlines() if line.startswith("| 10 |"))
    stated = re.search(r"keeps `SKILL.md` at or under ([\d,]+) words \(`LC_ALL=C wc -w`\)", row)
    assert stated and int(stated.group(1).replace(",", "")) == WORD_CEILING
    assert c_locale_word_count(SKILL) <= WORD_CEILING
