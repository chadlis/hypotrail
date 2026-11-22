"""D-055 on chadlis/hypotrail#75, item 3: the record check before a merge, `.claude/skills/drive/check_record.py`.

The hook is run as a subprocess with a fake `gh` first on the PATH, which answers from a directory of JSON files, so no test reads GitHub.
"""

import json
import os
import stat
import sys

import pytest

from _drive_scripts import ROOT, load, run

SETTINGS = ROOT / ".claude" / "settings.json"
FAKE_GH = f"""#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
directory = os.environ["FAKE_GH_DIR"]
name = args[1].replace("/", "__")
path = os.path.join(directory, name)
if not os.path.exists(path):
    print("HTTP 404", file=sys.stderr)
    sys.exit(1)
data = json.load(open(path))
print(json.dumps([data] if "--slurp" in args else data))
"""

BODY = "Slice R9 (#50).\n\nB1-P-02 is carried: the PR body gives the red runs.\n"


def comment(first: str, rest: str = "", n: int = 0) -> dict:
    return {"id": n, "body": f"{first}\n\n{rest}"}


def routing(number: int, rows: str) -> dict:
    return comment(
        f"## R9, round {number}: routing (review of record)",
        "| ID | round | axis | requirement | row | status | evidence |\n|---|---|---|---|---|---|---|\n" + rows,
    )


ROW1 = f"| B1-P-02 | 1 | Spec | the PR body will give each red run | 1 | open | x |\n| B1-S-01 | 1 | Standards | a name | 1 | open | y |"
ROW5 = "| B5-S-01 | 5 | Standards | a docstring | 1 (documentation) | open | z |\n| B5-P-01 | 5 | Spec | a limit | 1 (documentation) | open | z |"


def complete_record() -> list:
    return [
        comment("## R9: state (updated in place)", "- **Review rounds used:** 2 of 5.\n"),
        comment("## R9, round 1: Standards axis (review of record, `x`)"),
        comment("## R9, round 1: Spec axis (review of record, `x`)"),
        routing(1, ROW1),
        comment("## R9, round 2: Standards axis (review of record, `x`)"),
        routing(2, "| B2-S-01 | 2 | Standards | another name | 1 | open | y |"),
        comment("## R9: closing register", "B1-P-02 carried. B1-S-01 fixed. B2-S-01 fixed.\n"),
    ]


def documentation_record() -> list:
    """Five reviewed rounds, the documentation path in round 5, both verifications and a register that lists every ID."""
    record = [comment("## R9: state (updated in place)", "- **Review rounds used:** 5 of 5.\n")]
    for number in range(1, 6):
        record.append(comment(f"## R9, round {number}: Standards axis (review of record, `x`)"))
        rows = ROW5 if number == 5 else f"| B{number}-S-01 | {number} | Standards | the name of round {number} | 1 | open | y |"
        record.append(routing(number, rows))
    record.append(comment("## R9, round 5: Standards verification of the documentation fixes"))
    record.append(comment("## R9, round 5: Spec verification of the documentation fixes"))
    record.append(comment("## R9: closing register", "B1-S-01 B2-S-01 B3-S-01 B4-S-01 B5-S-01 B5-P-01\n"))
    return record


def problems(comments, body=BODY):
    return load("check_record").problems(body, comments)


def test_a_complete_record_has_no_problem():
    assert problems(complete_record()) == []


def test_a_state_comment_whose_round_count_is_not_the_number_of_reviewed_rounds_is_refused():
    record = complete_record()
    record[0] = comment("## R9: state (updated in place)", "- **Review rounds used:** 0 of 5.\n")
    assert problems(record) == ["the state comment says 0 of 5 review rounds, and 2 have a review of record"]


def test_a_missing_state_comment_is_refused():
    assert problems(complete_record()[1:]) == ["the state comment has no line 'Review rounds used: N of 5'"]


def test_a_round_with_a_review_of_record_and_no_routing_comment_is_refused():
    record = [c for c in complete_record() if "round 2: routing" not in c["body"]]
    assert problems(record) == ["round 2 has a review of record and no 'round 2: routing' comment"]


def test_a_documentation_path_with_no_verification_of_an_axis_is_refused():
    record = [c for c in documentation_record() if "Spec verification" not in c["body"]]
    assert problems(record) == ["round 5, documentation path (B5-P-01): no 'round 5: Spec verification' comment"]


def test_a_documentation_path_with_both_verifications_posted_is_complete():
    assert problems(documentation_record()) == []


def test_a_slice_without_a_documentation_path_needs_no_verification():
    assert not any("verification" in p for p in problems(complete_record()))


def two_round_record(first: str, second_rows: str, round_1_text: str = "", round_2_text: str = "") -> list:
    """Two reviewed rounds of one Spec reader: round 1 routes B1-P-01 on `first` to row 1, round 2 routes `second_rows`."""
    return [
        comment("## R9: state (updated in place)", "- **Review rounds used:** 2 of 5.\n"),
        comment("## R9, round 1: Spec axis (review of record, `x`)"),
        {"id": 0, "body": routing(1, f"| B1-P-01 | 1 | Spec | {first} | 1 | open | x |")["body"] + round_1_text},
        comment("## R9, round 2: Spec axis (review of record, `x`)"),
        {"id": 0, "body": routing(2, second_rows)["body"] + round_2_text},
        comment("## R9: closing register", "B1-P-01 fixed. B2-P-01 fixed.\n"),
    ]


@pytest.mark.parametrize(
    ("first", "second", "key"),
    [
        ('#142 B: "a duplicate key is accepted"', '#142 Tightened B: "plus one accepted call"', "#142 B"),
        ('`slice-builder.md`: "a test name says what the test checks"', '`slice-builder.md:11`: "a test name says what the test checks"', "`slice-builder.md`"),
        ("`ml/imports.py:97-105`: a strict reader named loose", "`ml/imports.py:322`", "`ml/imports.py`"),
    ],
)
def test_a_requirement_with_row_1_findings_in_two_rounds_and_no_structural_option_or_gate_line_is_refused(first, second, key):
    record = two_round_record(first, f"| B2-P-01 | 2 | Spec | {second} | 1 | open | x |")
    assert problems(record) == [
        f"requirement {key!r} has row-1 findings in rounds 1, 2, and no routing comment of round 2 or later has a line "
        f"'Structural option for {key}: ...' or 'Gate for {key}: D-nnn'"
    ]


@pytest.mark.parametrize("line", ["Structural option for #142 Tightened B: read the input once.", "### Structural option for #142 B: read the input once.", "- **Gate for #142 B: D-099 on chadlis/hypotrail#75**"])
def test_a_structural_option_or_gate_line_in_the_routing_comment_of_the_second_round_clears_the_requirement(line):
    rows = '| B2-P-01 | 2 | Spec | #142 Tightened B: "plus one accepted call" | 1, documentation only | open | x |'
    assert problems(two_round_record('#142 B: "a duplicate key is accepted"', rows)) != []
    assert problems(two_round_record('#142 B: "a duplicate key is accepted"', rows, round_2_text=f"\n{line}\n")) == []


def test_a_structural_option_line_in_a_round_before_the_second_does_not_clear_the_requirement():
    rows = '| B2-P-01 | 2 | Spec | #142 Tightened B: "plus one accepted call" | 1 | open | x |'
    record = two_round_record('#142 B: "a duplicate key is accepted"', rows, round_1_text="\nStructural option for #142 B: read the input once.\n")
    assert len(problems(record)) == 1 and "requirement '#142 B'" in problems(record)[0]


def test_a_carried_row_counts_for_a_round_only_while_that_round_lists_it_in_row_1_and_unsettled():
    carried = '| B1-P-01 | 1 | Spec | #142 B: "a duplicate key is accepted" | 1 | {status} | x |'
    assert len(problems(two_round_record('#142 B: "a duplicate key is accepted"', carried.format(status="open")))) == 1
    assert problems(two_round_record('#142 B: "a duplicate key is accepted"', carried.format(status="fixed in 1a2b3c4"))) == []
    assert problems(two_round_record('#142 B: "a duplicate key is accepted"', carried.format(status="open").replace("| 1 | open", "| 4 | open"))) == []


def test_requirements_with_different_keys_are_counted_apart():
    rows = '| B2-P-01 | 2 | Spec | #143 B: "The order is defined once" | 1 | open | x |'
    assert problems(two_round_record('#142 B: "a duplicate key is accepted"', rows)) == []


def test_a_missing_closing_register_is_refused():
    record = [c for c in complete_record() if "closing register" not in c["body"]]
    assert problems(record) == ["no closing register comment"]


def test_a_closing_register_that_leaves_out_an_assigned_finding_id_is_refused():
    record = complete_record()
    record[-1] = comment("## R9: closing register", "B1-P-02 carried. B2-S-01 fixed.\n")
    assert problems(record) == ["the closing register does not list: B1-S-01"]


def test_a_promised_line_that_the_pr_body_does_not_name_is_refused_unless_the_finding_is_settled():
    assert problems(complete_record(), body="Slice R9 (#50).\n") == ["B1-P-02 promises a line in the PR body, and the PR body does not name it"]
    record = complete_record()
    record[-1] = comment("## R9: closing register", "B1-P-02 refuted. B1-S-01 fixed. B2-S-01 fixed.\n")
    assert problems(record, body="Slice R9 (#50).\n") == []


def test_a_row_the_closing_register_settles_is_no_longer_promised_to_the_pr_body():
    record = complete_record()
    assert record[3]["body"].count("| open |") == 2
    record[-1] = comment("## R9: closing register", "B1-P-02 fixed. B1-S-01 fixed. B2-S-01 fixed.\n")
    assert problems(record, body="Slice R9 (#50).\n") == []


def test_a_row_the_closing_register_leaves_open_is_still_promised_to_the_pr_body_even_if_the_routing_row_said_fixed():
    record = complete_record()
    record[3] = routing(1, ROW1.replace("| open | x |", "| fixed | x |"))
    assert problems(record, body="Slice R9 (#50).\n") == ["B1-P-02 promises a line in the PR body, and the PR body does not name it"]


def test_the_skill_names_the_comment_forms_the_check_reads():
    skill = (ROOT / ".claude" / "skills" / "drive" / "SKILL.md").read_text()
    forms = ["## <slice>, round <r>: routing", "## <slice>, round <r>: <axis> verification"]
    assert all(form in skill for form in forms)
    assert "one verification comment per reader" in skill


def test_a_slice_with_no_review_of_record_is_refused():
    assert len(problems([comment("## R9: state (updated in place)")])) == 1


@pytest.mark.parametrize(
    ("body", "subject", "expected"),
    [
        ("Slice R1b (#138), split.", None, {138}),
        ("Part of #7.", None, {7}),
        ("nothing", "feat: a slice (#9)", {9}),
        ("Part of #7.", "feat: a slice (#9)", {7, 9}),
        ("Closes #132", None, set()),
    ],
)
def test_the_slice_issue_comes_from_the_squash_subject_or_the_pr_body(body, subject, expected):
    assert load("check_record").slice_numbers(body, subject) == expected


@pytest.mark.parametrize(
    ("title", "files", "apparatus"),
    [
        ("drive: tighten the hooks", [".claude/skills/drive/SKILL.md", "AGENTS.md", "tests/test_x.py", "README.md"], True),
        ("drive: tighten the hooks", [], True),
        ("drive: tighten the hooks", [".claude/settings.json", "src/hypotrail/cli.py"], False),
        ("drive: tighten the hooks", ["examples/chinook/task.json"], False),
        ("feat: a slice (#50)", [".claude/settings.json", "AGENTS.md"], False),
        ("Drive: tighten the hooks", ["AGENTS.md"], False),
        ("", ["AGENTS.md"], False),
    ],
)
def test_a_pull_request_titled_drive_that_changes_nothing_under_src_or_examples_and_names_no_slice_issue_is_an_apparatus_pull_request(title, files, apparatus):
    assert load("check_record").is_apparatus(title, files, "no slice here", None) is apparatus


@pytest.fixture
def gh_dir(tmp_path):
    directory = tmp_path / "gh"
    directory.mkdir()
    (tmp_path / "bin").mkdir()
    gh = tmp_path / "bin" / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    put(directory, "repos/chadlis/hypotrail/pulls/7", {"body": BODY})
    put(directory, "repos/chadlis/hypotrail/pulls/7/files", [{"filename": "src/hypotrail/cli.py"}])
    put(directory, "repos/chadlis/hypotrail/issues/50/comments", complete_record())
    return directory


def put(directory, path, data):
    (directory / path.replace("/", "__")).write_text(json.dumps(data))


def hook(gh_dir, payload):
    env = {**os.environ, "PATH": f"{gh_dir.parent / 'bin'}:{os.environ['PATH']}", "FAKE_GH_DIR": str(gh_dir)}
    return run("check_record", stdin=payload if isinstance(payload, str) else json.dumps(payload), env=env)


def merge_tool(number=7, **extra):
    return {"tool_name": "mcp__github__merge_pull_request", "tool_input": {"owner": "chadlis", "repo": "hypotrail", "pullNumber": number, **extra}}


def bash(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def test_the_settings_register_the_script_on_the_merge_tool_and_on_bash():
    entries = json.loads(SETTINGS.read_text())["hooks"]["PreToolUse"]
    registered = sorted(
        (entry["matcher"], hook["type"]) for entry in entries for hook in entry["hooks"] if "check_record.py" in hook["command"]
    )
    assert registered == [("Bash", "command"), ("mcp__github__merge_pull_request", "command")]


def test_a_complete_record_lets_the_merge_tool_through(gh_dir):
    result = hook(gh_dir, merge_tool())
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_an_incomplete_record_blocks_the_merge_tool_with_the_reasons_on_stderr(gh_dir):
    put(gh_dir, "repos/chadlis/hypotrail/issues/50/comments", complete_record()[:-1])
    result = hook(gh_dir, merge_tool())
    assert result.returncode == 2 and "no closing register comment" in result.stderr and "slice #50" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "gh pr merge 7 --squash",
        "cd /x && gh pr merge 7 --squash --subject 'feat: a slice (#50)'",
        "gh pr merge https://github.com/chadlis/hypotrail/pull/7 --squash",
        "gh pr merge --squash --repo chadlis/hypotrail",
        "gh api -X PUT repos/chadlis/hypotrail/pulls/7/merge -f merge_method=squash",
    ],
)
def test_a_bash_command_that_merges_is_checked_like_the_merge_tool(gh_dir, command):
    put(gh_dir, "repos/chadlis/hypotrail/issues/50/comments", complete_record()[:-1])
    assert hook(gh_dir, bash(command)).returncode == 2


@pytest.mark.parametrize("command", ["gh pr view 7", "gh pr list; ls", "echo gh pr merge 7", "ls"])
def test_a_bash_command_that_does_not_merge_is_let_through(gh_dir, command):
    put(gh_dir, "repos/chadlis/hypotrail/issues/50/comments", [])
    result = hook(gh_dir, bash(command))
    assert (result.returncode, result.stdout) == (0, "")


def test_a_merge_in_another_repository_is_not_checked(gh_dir):
    assert hook(gh_dir, bash("gh pr merge 7 --repo someone/else")).returncode == 0


def test_an_apparatus_pull_request_is_let_through_with_a_note(gh_dir):
    put(gh_dir, "repos/chadlis/hypotrail/pulls/7/files", [{"filename": ".claude/settings.json"}, {"filename": "tests/test_x.py"}])
    put(gh_dir, "repos/chadlis/hypotrail/pulls/7", {"title": "drive: the hooks", "body": "no slice here"})
    result = hook(gh_dir, merge_tool())
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert result.returncode == 0 and "apparatus pull request" in context


def test_a_pull_request_that_names_no_slice_issue_is_blocked(gh_dir):
    put(gh_dir, "repos/chadlis/hypotrail/pulls/7", {"body": "no slice here"})
    result = hook(gh_dir, merge_tool())
    assert result.returncode == 2 and "cannot tell the slice issue" in result.stderr


def test_the_squash_subject_names_the_slice_when_the_body_does_not(gh_dir):
    put(gh_dir, "repos/chadlis/hypotrail/pulls/7", {"body": "B1-P-02: the red runs"})
    assert hook(gh_dir, merge_tool(commit_title="feat: a slice (#50)")).returncode == 0


@pytest.mark.parametrize("payload", ["not json", "", "{}", '{"tool_name": "Bash", "tool_input": {}}', json.dumps({"tool_name": "mcp__github__merge_pull_request", "tool_input": {}})])
def test_malformed_input_blocks_the_merge(gh_dir, payload):
    assert hook(gh_dir, payload).returncode == 2


def test_a_github_error_blocks_the_merge(gh_dir):
    (gh_dir / "repos__chadlis__hypotrail__issues__50__comments").unlink()
    result = hook(gh_dir, merge_tool())
    assert result.returncode == 2 and "failed" in result.stderr


def test_the_drive_skill_runs_the_record_check_in_the_merge_step():
    row = next(line for line in (ROOT / ".claude/skills/drive/SKILL.md").read_text().splitlines() if line.startswith("| 12 |"))
    assert "check_record.py" in row


@pytest.mark.parametrize(
    "command",
    [
        'gh api -X PUT "repos/{owner}/{repo}/pulls/7/merge"',
        "gh api -XPUT repos/chadlis/hypotrail/pulls/7/merge",
        "gh api --method PUT /repos/chadlis/hypotrail/pulls/7/merge -f merge_method=squash",
        "gh api --method=put repos/chadlis/hypotrail/pulls/7/merge",
        "gh -R chadlis/hypotrail pr merge 7 --squash",
        "gh pr -R chadlis/hypotrail merge 7",
        "gh pr merge --squash -Rchadlis/hypotrail 7",
        "GH_REPO=chadlis/hypotrail gh pr merge 7",
        "env GH_TOKEN=x gh pr merge 7 --squash",
        "timeout 60 gh pr merge 7 --squash",
        "timeout -s KILL 60 gh pr merge 7",
        'bash -c "gh pr merge 7 --squash"',
        "echo start; bash -lc 'cd /x && gh pr merge 7'",
        'eval "gh pr merge 7"',
        'echo "$(gh pr merge 7)"',
        "(gh pr merge 7)",
        "/usr/bin/gh pr merge 7 2>&1",
    ],
)
def test_a_merge_is_found_wherever_the_flags_and_prefixes_sit(gh_dir, command):
    put(gh_dir, "repos/chadlis/hypotrail/issues/50/comments", complete_record()[:-1])
    result = hook(gh_dir, bash(command))
    assert result.returncode == 2 and "no closing register comment" in result.stderr


def test_a_quoted_semicolon_or_ampersand_in_the_subject_does_not_hide_the_merge_or_its_subject(gh_dir):
    put(gh_dir, "repos/chadlis/hypotrail/pulls/7", {"body": "B1-P-02: the red runs"})
    command = "gh pr merge 7 --squash --subject 'feat: a; b & c | d (#50)'"
    assert hook(gh_dir, bash(command)).returncode == 0
    put(gh_dir, "repos/chadlis/hypotrail/issues/50/comments", complete_record()[:-1])
    assert hook(gh_dir, bash(command)).returncode == 2


@pytest.mark.parametrize(
    "command",
    [
        "git commit -F - <<'EOF'\nfeat: x\n\nThen run gh pr merge 7 --squash\nEOF",
        "cat <<EOF > notes.md\ngh api -X PUT repos/chadlis/hypotrail/pulls/7/merge\nEOF\nls",
        "cat <<-EOF\n\tgh pr merge 7\n\tEOF",
        'git commit -m "docs: explain gh pr merge 7"',
        "git commit -m 'gh pr merge 7; gh pr merge 8'",
        "echo 'gh api -X PUT repos/chadlis/hypotrail/pulls/7/merge'",
        "gh issue comment 5 --body 'gh pr merge 7'",
    ],
)
def test_the_text_gh_pr_merge_inside_a_heredoc_body_or_a_quoted_message_is_not_a_merge(gh_dir, command):
    put(gh_dir, "repos/chadlis/hypotrail/issues/50/comments", [])
    result = hook(gh_dir, bash(command))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_a_command_after_a_heredoc_is_still_read(gh_dir):
    put(gh_dir, "repos/chadlis/hypotrail/issues/50/comments", complete_record()[:-1])
    assert hook(gh_dir, bash("cat <<'EOF'\nnotes\nEOF\ngh pr merge 7")).returncode == 2


@pytest.mark.parametrize(
    "command",
    [
        "gh api repos/chadlis/hypotrail/pulls/7/merge",
        "gh api -X GET repos/chadlis/hypotrail/pulls/7/merge",
        "gh api --method GET repos/chadlis/hypotrail/pulls/7/merge --jq .merged",
        "gh api repos/chadlis/hypotrail/pulls/7/files",
    ],
)
def test_a_read_only_call_of_the_merge_path_is_not_a_merge(gh_dir, command):
    put(gh_dir, "repos/chadlis/hypotrail/issues/50/comments", [])
    result = hook(gh_dir, bash(command))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


@pytest.mark.parametrize(
    "command",
    [
        "gh pr merge",
        "gh pr merge --squash --delete-branch",
        "gh pr merge my-branch --squash",
        "gh api -X PUT repos/chadlis/hypotrail/pulls/$PR/merge",
        "gh api -X PUT repos/chadlis/hypotrail/pulls/{number}/merge",
    ],
)
def test_a_merge_whose_pull_request_number_cannot_be_read_is_refused(gh_dir, command):
    result = hook(gh_dir, bash(command))
    assert result.returncode == 2 and "name the pull request number" in result.stderr


def test_a_merge_without_a_number_in_another_repository_is_not_checked(gh_dir):
    assert hook(gh_dir, bash("gh pr merge -R someone/else --squash")).returncode == 0


def test_every_merge_of_a_command_is_checked(gh_dir):
    put(gh_dir, "repos/chadlis/hypotrail/pulls/8", {"body": "Part of #51."})
    put(gh_dir, "repos/chadlis/hypotrail/pulls/8/files", [{"filename": "src/hypotrail/cli.py"}])
    put(gh_dir, "repos/chadlis/hypotrail/issues/51/comments", [])
    result = hook(gh_dir, bash("gh pr merge 7 --squash && gh pr merge 8 --squash"))
    assert result.returncode == 2 and "slice #51" in result.stderr


def check_record_entries():
    entries = json.loads(SETTINGS.read_text())["hooks"]["PreToolUse"]
    return [hook for entry in entries for hook in entry["hooks"] if "check_record.py" in hook["command"]]


def test_a_timeout_or_a_failure_of_the_record_check_blocks_the_merge():
    entries = check_record_entries()
    assert len(entries) == 2
    assert [entry.get("onFailure") for entry in entries] == ["block", "block"]


def test_every_gh_call_of_the_record_check_is_capped_at_twenty_seconds_and_the_hook_timeout_holds_the_calls_of_a_merge(monkeypatch):
    module = load("check_record")
    seen = []

    def fake_run(command, **options):
        seen.append(options.get("timeout"))
        return type("Done", (), {"returncode": 0, "stdout": "[[]]" if "--slurp" in command else "{}", "stderr": ""})()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    module.gh(["repos/chadlis/hypotrail/pulls/7"])
    module.gh_pages("repos/chadlis/hypotrail/pulls/7/files")
    assert seen == [20, 20]
    calls_of_a_merge = 3
    assert all(entry["timeout"] >= calls_of_a_merge * 20 for entry in check_record_entries()) and {e["timeout"] for e in check_record_entries()} == {180}


@pytest.mark.parametrize(
    "command",
    [
        "gh pr merge 7 --squash -R Chadlis/Hypotrail",
        "gh pr merge https://github.com/CHADLIS/Hypotrail/pull/7 --squash",
        "gh api -X PUT repos/Chadlis/HYPOTRAIL/pulls/7/merge",
    ],
)
def test_a_merge_names_the_repository_whatever_the_case_of_its_name(gh_dir, command):
    put(gh_dir, "repos/chadlis/hypotrail/issues/50/comments", complete_record()[:-1])
    result = hook(gh_dir, bash(command))
    assert result.returncode == 2 and "no closing register comment" in result.stderr


def test_a_later_comment_that_is_neither_a_routing_nor_the_closing_register_settles_no_row():
    record = complete_record() + [
        comment("## R9, round 2: fix prompt", "B1-P-02 fixed. B1-S-01 fixed.\n"),
        comment("## R9, round 2: Spec axis report", "| B1-P-02 | 1 | Spec | x | 1 | fixed | y |\n"),
    ]
    assert problems(record, body="Slice R9 (#50).\n") == ["B1-P-02 promises a line in the PR body, and the PR body does not name it"]


def test_a_drive_titled_pull_request_with_tests_and_docs_only_and_a_part_of_line_is_checked_against_its_slice_issue(gh_dir):
    files = [{"filename": "tests/test_x.py"}, {"filename": "docs/agents/x.md"}]
    put(gh_dir, "repos/chadlis/hypotrail/pulls/7", {"title": "drive: tests and docs", "body": "Part of #120.\n"})
    put(gh_dir, "repos/chadlis/hypotrail/pulls/7/files", files)
    put(gh_dir, "repos/chadlis/hypotrail/issues/120/comments", [])
    result = hook(gh_dir, merge_tool())
    assert result.returncode == 2 and "slice #120" in result.stderr
    assert not load("check_record").is_apparatus("drive: tests and docs", ["tests/test_x.py"], "Part of #120.\n", None)


def test_a_drive_titled_pull_request_whose_squash_subject_ends_with_a_slice_number_is_checked(gh_dir):
    put(gh_dir, "repos/chadlis/hypotrail/pulls/7", {"title": "drive: docs", "body": "no slice here"})
    put(gh_dir, "repos/chadlis/hypotrail/pulls/7/files", [{"filename": "AGENTS.md"}])
    put(gh_dir, "repos/chadlis/hypotrail/issues/50/comments", [])
    result = hook(gh_dir, merge_tool(commit_title="drive: docs (#50)"))
    assert result.returncode == 2 and "slice #50" in result.stderr


def test_the_skill_places_the_routing_table_in_the_comment_the_check_reads():
    skill = (ROOT / ".claude" / "skills" / "drive" / "SKILL.md").read_text()
    bullet = next(line for line in skill.splitlines() if line.startswith("- **Where it lives.**"))
    assert "`## <slice>, round <r>: routing`" in bullet and "Review of record" not in bullet


def test_the_module_docstring_states_what_the_merge_detection_does_not_see():
    doc = load("check_record").__doc__
    assert "Stated limits" in doc and "xargs" in doc and "variable" in doc
    assert "planting" in doc and "defect" in doc
