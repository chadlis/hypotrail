"""`.claude/skills/drive/post_fix_prompt.sh`: a fix prompt is posted on the slice issue only once `premises.py` and `fix_prompt_check.py --strict` accept it.

A fake `gh` first on the PATH writes each call it gets, and the body it would post, into a folder, so no test reads or writes GitHub.
"""

import os
import stat
import subprocess
import sys

import pytest

from _drive_scripts import DRIVE

TRIGGER = "This is a review fix"
SOURCE = "The check refuses a call. It also logs every refusal to the journal.\n"
FAKE_GH = f"""#!{sys.executable}
import os, sys
log = os.environ["FAKE_GH_LOG"]
calls = sorted(os.listdir(log))
with open(os.path.join(log, f"call-{{len(calls)}}.args"), "w") as out:
    out.write("\\n".join(sys.argv[1:]))
for word in sys.argv[1:]:
    if word.startswith("body=@"):
        with open(word[len("body=@"):]) as body, open(os.path.join(log, f"call-{{len(calls)}}.body"), "w") as out:
            out.write(body.read())
if "FAKE_GH_POSTED" in os.environ:
    with open(os.environ["FAKE_GH_POSTED"]) as posted:
        sys.stdout.write(posted.read())
else:
    print(7130000001)
"""


@pytest.fixture
def setting(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "issue-1-body.md").write_text(SOURCE)
    bin_dir, log = tmp_path / "bin", tmp_path / "log"
    bin_dir.mkdir()
    log.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_GH_LOG": str(log), "HYPOTRAIL_PROMPT_SOURCES": str(sources)}
    return tmp_path, project, log, env


def post(setting, prompt: str, *extra: str):
    tmp_path, project, log, env = setting
    path = tmp_path / "prompt.md"
    path.write_text(prompt)
    result = subprocess.run(
        ["bash", str(DRIVE / "post_fix_prompt.sh"), "176", "L2.5", "2", str(path), str(project), *extra],
        capture_output=True, text=True, env=env, cwd=project,
    )
    return result, sorted(log.iterdir())


def test_a_prompt_with_a_planted_partial_quotation_exits_1_and_posts_nothing(setting):
    result, calls = post(setting, f'{TRIGGER}. B1-P-01, #1 Tightened C says: "refuses a call. It also logs"\n')
    assert result.returncode == 1 and "not a whole sentence or item of its source" in result.stdout + result.stderr
    assert calls == []


def test_a_prompt_that_premises_refuses_posts_nothing(setting):
    result, calls = post(setting, f"{TRIGGER}. B1-P-01. `fault` is called from `cli.py` only.\n")
    assert result.returncode != 0 and "NO callers(...) LINE" in result.stdout + result.stderr
    assert calls == []


def test_an_accepted_prompt_is_posted_once_under_the_fixed_heading_in_a_four_backtick_fence_with_both_sheets_and_its_comment_id_printed(setting):
    prompt = f'{TRIGGER}. B1-P-01, #1 Tightened C says: "The check refuses a call."\n'
    result, calls = post(setting, prompt)
    assert result.returncode == 0, result.stdout + result.stderr
    assert [call.name for call in calls] == ["call-0.args", "call-0.body"]
    args = calls[0].read_text().splitlines()
    assert args[:2] == ["api", "repos/chadlis/hypotrail/issues/176/comments"]
    body = calls[1].read_text()
    assert body.startswith("## L2.5, round 2: fix prompt (to slice-builder), word for word\n")
    assert f"\n````\n{prompt}````\n" in body
    assert "premises.py" in body and "Fix-prompt check (strict): 0 warning(s). Finding IDs named: B1-P-01." in body
    assert result.stdout.strip().splitlines()[-1] == "7130000001"


def test_with_out_an_accepted_prompt_is_written_to_the_file_as_the_comment_it_would_post_its_path_printed_and_gh_never_called(setting):
    tmp_path = setting[0]
    prompt = f'{TRIGGER}. B1-P-01, #1 Tightened C says: "The check refuses a call."\n'
    built = tmp_path / "comment.md"
    result, calls = post(setting, prompt, "--out", str(built))
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == []
    assert result.stdout.strip().splitlines()[-1] == str(built)
    body = built.read_text()
    assert body.startswith("## L2.5, round 2: fix prompt (to slice-builder), word for word\n")
    assert f"\n````\n{prompt}````\n" in body and "Fix-prompt check (strict): 0 warning(s). Finding IDs named: B1-P-01." in body


def test_with_out_a_refused_prompt_writes_no_file(setting):
    tmp_path = setting[0]
    built = tmp_path / "comment.md"
    result, calls = post(setting, f'{TRIGGER}. B1-P-01, #1 Tightened C says: "refuses a call. It also logs"\n', "--out", str(built))
    assert result.returncode == 1 and calls == [] and not built.exists()


def compare(setting, posted: str, built: str):
    tmp_path, project, log, env = setting
    (tmp_path / "posted.md").write_text(posted)
    (tmp_path / "built.md").write_text(built)
    return subprocess.run(
        ["bash", str(DRIVE / "post_fix_prompt.sh"), "--compare", "7130000001", str(tmp_path / "built.md")],
        capture_output=True, text=True, env={**env, "FAKE_GH_POSTED": str(tmp_path / "posted.md")}, cwd=project,
    )


BUILT = "## L2.5, round 2: fix prompt (to slice-builder), word for word\n\n````\nkeep `re.compile(r\"[^!\\[]\")` and ![x](y)\n````\n"


def test_compare_reads_the_posted_comment_and_exits_0_when_it_is_the_built_file(setting):
    result = compare(setting, BUILT, BUILT)
    assert result.returncode == 0, result.stdout + result.stderr
    args = sorted(setting[2].iterdir())[0].read_text().splitlines()
    assert args == ["api", "repos/chadlis/hypotrail/issues/comments/7130000001", "--jq", ".body"]


def test_compare_exits_1_and_prints_the_difference_when_the_posted_comment_lost_a_character(setting):
    result = compare(setting, BUILT.replace("![x]", "[x]"), BUILT)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "![x](y)" in result.stdout and "differs from" in result.stderr
