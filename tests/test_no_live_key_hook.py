"""D-048 on chadlis/hypotrail#75: the PreToolUse hook `.claude/hooks/no-live-key.sh` unsets the provider key before every Bash command.

The script is run as a subprocess with the JSON Claude Code sends on stdin. Only a single simple
`capture.sh` command is exempt; everything else is rewritten, and any malformed input blocks the command.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".claude" / "hooks" / "no-live-key.sh"
SETTINGS = ROOT / ".claude" / "settings.json"
UNSET = "unset HYPOTRAIL_ANTHROPIC_API_KEY"
CAPTURE = ".claude/skills/drive/capture.sh"


def run_hook(stdin: str, env: dict | None = None, bash: str = "bash"):
    return subprocess.run([bash, str(HOOK)], input=stdin, capture_output=True, text=True, env=env)


def run_command(command: str, **extra):
    payload = {"tool_name": "Bash", "tool_input": {"command": command, **extra}}
    return run_hook(json.dumps(payload))


def rewritten(result) -> dict:
    assert result.returncode == 0
    return json.loads(result.stdout)["hookSpecificOutput"]


def test_the_settings_register_the_script_as_a_pretooluse_command_hook_on_bash():
    entries = json.loads(SETTINGS.read_text())["hooks"]["PreToolUse"]
    registered = [
        (entry["matcher"], hook["type"], hook["command"])
        for entry in entries
        for hook in entry["hooks"]
        if "no-live-key.sh" in hook["command"]
    ]
    assert len(registered) == 1
    matcher, kind, command = registered[0]
    assert (matcher, kind) == ("Bash", "command")
    assert command.endswith("/.claude/hooks/no-live-key.sh\"") or command.endswith("/.claude/hooks/no-live-key.sh")


def test_an_ordinary_command_is_prefixed_with_the_unset_and_other_fields_are_kept():
    result = run_command("ls -l", description="list", timeout=5000, run_in_background=False)
    assert result.returncode == 0
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    assert output["updatedInput"] == {
        "command": UNSET + "\nls -l",
        "description": "list",
        "timeout": 5000,
        "run_in_background": False,
    }


@pytest.mark.parametrize(
    "command",
    [
        CAPTURE,
        f"{CAPTURE} --out run1 --flag",
        f"/home/user/hypotrail/{CAPTURE}",
        f"/a/b/{CAPTURE} arg",
        f"{CAPTURE}\targ",
    ],
)
def test_a_single_simple_capture_command_is_exempt(command):
    result = run_command(command)
    assert (result.returncode, result.stdout) == (0, "")


@pytest.mark.parametrize(
    "suffix",
    [" ; echo x", " && echo x", " || echo x", " | cat", " & ", "\necho x", " $(echo x)", " `echo x`"],
    ids=["semicolon", "and", "or", "pipe", "background", "newline", "dollar-paren", "backtick"],
)
def test_a_capture_command_with_a_shell_operator_is_rewritten(suffix):
    command = CAPTURE + suffix
    assert rewritten(run_command(command))["updatedInput"]["command"] == UNSET + "\n" + command


@pytest.mark.parametrize(
    "command",
    ["capture.sh", "capture.sh arg", f"{CAPTURE}.bak", f"{CAPTURE}.bak arg", "x" + CAPTURE, f"drive/capture.sh"],
)
def test_a_path_that_only_resembles_capture_is_rewritten(command):
    assert rewritten(run_command(command))["updatedInput"]["command"] == UNSET + "\n" + command


@pytest.mark.parametrize(
    "stdin",
    [
        "not json",
        "",
        "{}",
        '{"tool_input": "ls"}',
        '{"tool_input": {}}',
        '{"tool_input": {"command": 5}}',
        '{"tool_input": {"command": null}}',
        '{"tool_input": {"command": ["ls"]}}',
    ],
    ids=["invalid-json", "empty", "no-tool-input", "tool-input-not-object", "no-command", "number", "null", "list"],
)
def test_malformed_input_blocks_the_command(stdin):
    result = run_hook(stdin)
    assert (result.returncode, result.stdout) == (2, "")


def test_a_path_without_jq_blocks_the_command(tmp_path):
    bash = shutil.which("bash")
    (tmp_path / "bash").symlink_to(bash)
    env = {"PATH": str(tmp_path)}
    assert shutil.which("jq", path=str(tmp_path)) is None
    result = run_hook(json.dumps({"tool_input": {"command": "ls"}}), env=env, bash=bash)
    assert (result.returncode, result.stdout) == (2, "")


def test_the_rewritten_command_runs_with_the_key_unset():
    dummy = "dummy-key-not-real"
    command = 'echo "key=[${HYPOTRAIL_ANTHROPIC_API_KEY-unset}]"'
    new_command = rewritten(run_command(command))["updatedInput"]["command"]
    env = {**os.environ, "HYPOTRAIL_ANTHROPIC_API_KEY": dummy}
    ran = subprocess.run(["bash", "-c", new_command], capture_output=True, text=True, env=env)
    assert ran.stdout == "key=[unset]\n"
    assert dummy not in ran.stdout + ran.stderr


@pytest.mark.parametrize(
    "command",
    [
        "uv run --locked --all-extras pytest",
        "pytest -q tests/test_x.py",
        "cd /x && uv run python -m pytest",
        "uv run pytest tests/ 2>&1 | tail -3",
    ],
)
def test_a_command_that_runs_pytest_gets_ten_minutes_in_the_foreground(command):
    result = run_command(command, description="suite", timeout=120000, run_in_background=True)
    updated = rewritten(result)["updatedInput"]
    assert (updated["timeout"], updated["run_in_background"]) == (600000, False)
    assert updated["command"] == UNSET + "\n" + command and updated["description"] == "suite"


def test_a_pytest_command_with_no_timeout_or_background_field_gets_both():
    updated = rewritten(run_command("uv run pytest"))["updatedInput"]
    assert (updated["timeout"], updated["run_in_background"]) == (600000, False)


@pytest.mark.parametrize("command", ["ls .pytest_cache", "cat tests/test_pytest_hook.py", "echo pytest-cov", "uv run python -m hypotrail --help"])
def test_a_command_that_does_not_run_pytest_keeps_its_timeout_and_background_fields(command):
    updated = rewritten(run_command(command, timeout=5000, run_in_background=True))["updatedInput"]
    assert (updated["timeout"], updated["run_in_background"]) == (5000, True)
