"""D-055 on chadlis/hypotrail#75, item 1: the PreToolUse hook on Agent, `.claude/skills/drive/fix_prompt_check.py`.

The hook only warns. Its sources are a directory of `.md` files named by `HYPOTRAIL_PROMPT_SOURCES`, so no test reads GitHub.
"""

import json
import os
import re
import stat

import pytest

from _drive_scripts import FIXTURES, ROOT, load, run

SETTINGS = ROOT / ".claude" / "settings.json"
TRIGGER = "This is a review fix"
SOURCE = "The check refuses a call. It also logs every refusal to the journal.\n"


@pytest.fixture
def sources(tmp_path):
    directory = tmp_path / "sources"
    directory.mkdir()
    (directory / "issue-1-body.md").write_text(SOURCE)
    return directory


def hook(prompt: str, sources, extra_env: dict | None = None, stdin: str | None = None):
    env = {**os.environ, "HYPOTRAIL_PROMPT_SOURCES": str(sources), "CLAUDE_PROJECT_DIR": str(ROOT), **(extra_env or {})}
    payload = stdin if stdin is not None else json.dumps({"tool_name": "Agent", "tool_input": {"prompt": prompt}})
    return run("fix_prompt_check", stdin=payload, env=env, cwd=ROOT)


def context_of(result) -> str:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]


def test_the_settings_register_the_script_as_a_pretooluse_command_hook_on_agent():
    entries = json.loads(SETTINGS.read_text())["hooks"]["PreToolUse"]
    registered = [
        (entry["matcher"], hook["type"], hook["command"])
        for entry in entries
        for hook in entry["hooks"]
        if "fix_prompt_check.py" in hook["command"]
    ]
    assert [(matcher, kind) for matcher, kind, _ in registered] == [("Agent", "command")]
    assert registered[0][2].endswith('/.claude/skills/drive/fix_prompt_check.py')


def test_a_prompt_that_is_not_a_review_fix_gets_no_output(sources):
    result = hook("Summarise the repository. Quote \"anything at all, nothing checked\" as #12 says.", sources)
    assert (result.returncode, result.stdout) == (0, "")


def test_a_review_fix_prompt_is_let_through_with_its_findings_in_additional_context_and_no_decision(sources):
    result = hook(f'{TRIGGER}. Tightened C says: "The check was never written." B1-P-01', sources)
    output = json.loads(result.stdout)
    assert result.returncode == 0
    assert list(output) == ["hookSpecificOutput"]
    assert list(output["hookSpecificOutput"]) == ["hookEventName", "additionalContext"]
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "not found word for word" in output["hookSpecificOutput"]["additionalContext"]


def test_a_quotation_that_is_a_whole_sentence_of_a_source_and_a_named_finding_id_give_no_warning(sources):
    context = context_of(hook(f'{TRIGGER}. B1-P-01, #1 Tightened C says: "The check refuses a call."', sources))
    assert context.startswith("Fix-prompt check (warns only, the call goes through): 0 warning(s). Finding IDs named: B1-P-01.")


def test_a_quotation_that_stops_inside_a_sentence_of_its_source_is_warned_as_partial(sources):
    context = context_of(hook(f'{TRIGGER}. B1-P-01, #1 Tightened C says: "refuses a call. It also logs"', sources))
    assert "1 warning(s)" in context and "not a whole sentence or item of its source" in context


def test_a_quotation_that_elides_words_is_warned_as_partial_by_declaration(sources):
    context = context_of(hook(f'{TRIGGER}. B1-P-01, #1 Tightened C says: "The check refuses … every refusal to the journal."', sources))
    assert 'elided with "…"' in context


def test_a_quotation_that_joins_two_items_of_a_source_is_warned_as_not_word_for_word(sources):
    (sources / "issue-1-body.md").write_text("- first item here.\n- second item here.\n")
    context = context_of(hook(f'{TRIGGER}. B1-P-01, #1 Tightened C says: "first item here. second item here."', sources))
    assert "not found word for word in a source" in context


def test_a_quotation_of_a_file_or_a_rule_only_has_to_be_word_for_word(sources):
    context = context_of(hook(f'{TRIGGER}. B1-P-01. `rules.md` says "refuses a call. It also logs".', sources))
    assert "0 warning(s)" in context
    context = context_of(hook(f'{TRIGGER}. B1-P-01. `rules.md` says "refuses every call. It also logs".', sources))
    assert "1 warning(s)" in context and "not found word for word in a source" in context


def test_a_comment_of_another_issue_that_quotes_a_source_in_part_does_not_make_the_partial_quotation_whole(sources):
    (sources / "issue-9-comment-5.md").write_text('The reader wrote: "refuses a call" in a table.\n')
    context = context_of(hook(f'{TRIGGER}. B1-P-01, #1 Tightened C says: "refuses a call. It also logs"', sources))
    assert "not a whole sentence or item of its source" in context
    (sources / "issue-1-body.md").unlink()
    context = context_of(hook(f'{TRIGGER}. B1-P-01, #9 Tightened C says: "refuses a call"', sources))
    assert "0 warning(s)" in context


def test_the_finding_ids_the_prompt_names_are_listed_and_a_prompt_that_names_none_is_warned(sources):
    assert "Finding IDs named: B1-P-01, R2-S-03." in context_of(hook(f"{TRIGGER}. Fix R2-S-03 and B1-P-01.", sources))
    context = context_of(hook(f"{TRIGGER}. Fix the tests.", sources))
    assert "Finding IDs named: none." in context and "finding IDs: the prompt names none" in context


def test_a_prompt_that_points_to_a_file_with_the_trigger_is_checked_on_that_file_and_one_without_it_is_not(sources, tmp_path):
    pointed = tmp_path / "task.md"
    pointed.write_text(f'{TRIGGER}. B1-P-01, #1 Tightened C says: "The check was never written."\n')
    context = context_of(hook(f"Read {pointed} and do exactly what it says.", sources))
    assert "not found word for word" in context
    pointed.write_text("Summarise the repository.\n")
    assert hook(f"Read {pointed} and do exactly what it says.", sources).stdout == ""


def test_a_sentence_of_the_form_called_from_only_is_reported_by_the_premise_sheet_through_the_hook(sources):
    context = context_of(hook(f"{TRIGGER}. B1-P-01. `fault` is called from `cli.py` only.", sources))
    assert "Premise sheet:" in context and "NO callers(...) LINE for the claim" in context


def test_the_hook_exits_0_whatever_it_finds(sources):
    prompt = f'{TRIGGER}. #1 Tightened C says: "The check was never written." `fault` is called from `cli.py` only.'
    result = hook(prompt, sources)
    assert result.returncode == 0
    assert set(json.loads(result.stdout)) == {"hookSpecificOutput"}  # no permissionDecision, no decision, no systemMessage


@pytest.mark.parametrize("stdin", ["not json", "", "{}", '{"tool_input": {"prompt": 5}}', '{"tool_input": []}'])
def test_an_error_of_the_hook_itself_is_a_warning_and_the_call_goes_through(sources, stdin):
    result = hook("", sources, stdin=stdin)
    assert result.returncode == 0
    if stdin == '{"tool_input": {"prompt": 5}}':
        assert result.stdout == ""
    else:
        assert "Fix-prompt check failed and did not check the prompt" in context_of(result)


def test_a_source_that_cannot_be_read_makes_a_missing_quotation_unchecked_not_missing(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    gh = fake / "gh"
    gh.write_text("#!/bin/sh\necho offline >&2\nexit 1\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "CLAUDE_PROJECT_DIR": str(ROOT)}
    env.pop("HYPOTRAIL_PROMPT_SOURCES", None)
    payload = json.dumps({"tool_input": {"prompt": f'{TRIGGER}. B1-P-01, #1 Tightened C says: "The check was never written."'}})
    context = context_of(run("fix_prompt_check", stdin=payload, env=env, cwd=ROOT))
    assert "source not read: GitHub issues" in context
    assert "unchecked: a source could not be read" in context and "not found word for word" not in context


def test_the_drive_skill_says_the_drive_posts_the_hook_output_beside_the_fix_prompt():
    paragraph = next(
        line for line in (ROOT / ".claude/skills/drive/SKILL.md").read_text().splitlines() if line.startswith("**Quote a decision whole, with its verbs.**")
    )
    assert "/fix_prompt_check.py` on the Agent tool" in paragraph and "post them beside the prompt" in paragraph


# The 17 quotation warnings that the checker gives on the eight accepted fix prompts of the first two slices, each read against its source by hand
# when the fixtures were added. A warning that a prompt does not earn is a false warning: it would have been a false refusal had the hook blocked.
# The kinds: partial (the quotation stops inside a sentence or item of its source), joined (two items run into one quotation, not word for word), elided (it says so with an ellipsis).
TRUE_WARNINGS = {
    "r1-round-1": [
        ("The product handbook follows current behaviour", "partial"),
        ("each Study writer is called once with each check", "partial"),
        ("The order paragraph names the two checks by command", "joined"),
        ("The table `checks-before-the-lock`, and the probe's lock-held part", "joined"),
        ("`init`'s check rows are called without `--read-sequence`", "joined"),
        ("a test compares the table's rows with the probe's calls", "partial"),
    ],
    "r1-round-2": [
        ("A probe calls every Study writer with the Study's writer lock held", "elided"),
        ("once with the first check after the stale check provoked", "partial"),
        ("The rows are the checks before the lock beyond the general order", "partial"),
    ],
    "r1-round-3": [
        ("A probe calls every Study writer", "elided"),
        ("the first refusal that the arguments, the examples directory", "partial"),
    ],
    "r1-round-4": [("A probe calls every Study writer with the Study's writer lock held", "elided")],
    "r1b-round-1": [
        ("`require_valid_read_sequence` is called from the Study-write module only", "partial"),
        ("the refusal at `cli.py:406`", "partial"),
        ("No call into the Study-write module passes a command name", "partial"),
        ("say what the code does after the move", "partial"),
    ],
    "r1b-round-2": [("No call into the Study-write module passes a command name", "partial")],
    "r1b-round-3": [],
    "r1b-round-4": [],
}
KINDS = {
    "partial": "not a whole sentence or item of its source",
    "joined": "not found word for word in a source",
    "elided": 'elided with "…"',
}


def fixture_warnings():
    module = load("fix_prompt_check")
    corpus = [(path.stem, path.read_text()) for path in sorted((FIXTURES / "sources").glob("*.md"))]
    return {path.stem: module.check_quotations(path.read_text(), corpus) for path in sorted((FIXTURES / "fix-prompts").glob("*.md"))}


def test_the_checker_gives_no_false_warning_on_the_accepted_fix_prompts_of_the_first_two_slices(record_property):
    found = fixture_warnings()
    assert sorted(found) == sorted(TRUE_WARNINGS)
    false_warnings = []
    for name, warnings in found.items():
        true = [(quote, KINDS[kind]) for quote, kind in TRUE_WARNINGS[name]]
        false_warnings += [
            f"{name}: {warning}"
            for warning in warnings
            if not any(quote in warning and why in warning for quote, why in true)
        ]
        missed = [quote for quote, why in true if not any(quote in warning and why in warning for warning in warnings)]
        assert missed == [], f"{name}: a warning judged true is no longer given"
    total = sum(len(warnings) for warnings in found.values())
    report = f"quotation warnings on {len(found)} accepted fix prompts: {total}; false warnings: {len(false_warnings)}"
    record_property("false_warnings", len(false_warnings))
    print(report)
    assert false_warnings == [], report


def test_no_fixture_prompt_names_a_finding_id_so_each_one_is_warned_by_the_finding_id_check():
    module = load("fix_prompt_check")
    named = {path.stem: module.check_finding_ids(path.read_text())[0] for path in sorted((FIXTURES / "fix-prompts").glob("*.md"))}
    assert len(named) == 8 and all(ids == [] for ids in named.values())


def test_the_hook_runs_on_all_fixture_prompts_but_the_first_of_the_first_slice_which_says_only_as_a_review_fix():
    without = [path.stem for path in sorted((FIXTURES / "fix-prompts").glob("*.md")) if TRIGGER not in path.read_text()]
    assert without == ["r1-round-1"]


def test_every_source_fixture_is_named_after_its_issue_and_comment_or_after_the_repository_file_it_copies():
    assert all(re.fullmatch(r"issue-\d+-(body|comment-\d+)|repo-[\w-]+", path.stem) for path in (FIXTURES / "sources").glob("*.md"))
