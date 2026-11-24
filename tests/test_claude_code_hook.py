"""chadlis/hypotrail#196: the Claude Code `UserPromptSubmit` hook template under `clients/claude-code/`.

The script is started as Claude Code starts it, with `python3 -I`, `CLAUDE_PROJECT_DIR` set and the hook's JSON on stdin. A test either
gives it a stub `uv`, first on `PATH`, that records each start and answers a prepared object, or lets it start the real CLI of this
checkout, which needs `uv` on `PATH` and the checkout's `.venv` synced, as CI has them. No model is called and no Claude Code binary is
started: Claude Code's delivery of the text to the model is the owner's check.
"""

import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

import pytest
from _client_helpers import chinook_decided_study, chinook_pending_study, compared_study, decide, decided_study, rescored_study, several_pending_study
from _study_helpers import run_cli

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "clients" / "claude-code"
SCRIPT = TEMPLATE / "hypotrail_study_hook.py"
FRAGMENT = TEMPLATE / "settings-fragment.json"
RECORDER = Path(__file__).resolve().parent / "_hook_recorder.py"
CHAPTER = ROOT / "docs" / "handbook" / "chapters" / "18-vscode-client.html"
HOOK_TABLE = "claude-code-hook"
# Claude Code's timeout of a `UserPromptSubmit` command hook whose entry gives none (code.claude.com/docs/en/hooks, read 2026-11-24).
DEFAULT_HOOK_TIMEOUT_SECONDS = 30
# The `python3` a user's `PATH` gives, found before a test changes `PATH`, outside this checkout's environment, where `hypotrail` is
# not importable: the script needs the standard library only.
PYTHON3 = shutil.which(
    "python3", path=os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep) if not Path(p).resolve().is_relative_to(Path(sys.prefix).resolve()))
)
CONTRACT = json.loads((ROOT / "clients" / "vscode" / "contract.json").read_text(encoding="utf-8"))
STUB_UV = f"""#!{sys.executable} -I
import json, os, subprocess, sys, time
sleep = float(os.environ.get("STUB_SLEEP", "0"))
# A stub that does not answer starts a child of its own too, as `uv` starts the CLI's Python.
child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(600)"]).pid if sleep else None
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({{"arguments": sys.argv[1:], "cwd": os.getcwd(), "pids": [os.getpid(), child]}}) + "\\n")
time.sleep(sleep)
sys.stdout.write(open(os.environ["STUB_ANSWER"], encoding="utf-8").read())
"""


class TableRows(HTMLParser):
    """{data-item: data-value} of the rows of one table of a chapter source."""

    def __init__(self, table_id):
        super().__init__()
        self.table_id, self.inside, self.items = table_id, False, {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self.inside = attrs.get("id") == self.table_id
        elif tag == "tr" and self.inside and "data-item" in attrs:
            self.items[attrs["data-item"]] = attrs["data-value"]

    def handle_endtag(self, tag):
        if tag == "table":
            self.inside = False


def script():
    """The script as a module, to read the values it defines; importing it starts nothing."""
    spec = importlib.util.spec_from_file_location("hypotrail_study_hook", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def the_rule() -> str:
    return getattr(script(), "RULE", "")


def hook_table() -> dict:
    rows = TableRows(HOOK_TABLE)
    rows.feed(CHAPTER.read_text(encoding="utf-8"))
    return rows.items


# --- the fragment registers the script -------------------------------------------------------------------------------


def test_the_fragment_registers_the_script_once_under_user_prompt_submit_with_one_study_and_a_timeout_above_the_scripts_bound():
    fragment = json.loads(FRAGMENT.read_text(encoding="utf-8"))
    assert isinstance(fragment, dict) and set(fragment) == {"hooks"}
    assert set(fragment["hooks"]) == {"UserPromptSubmit"}
    [entry] = fragment["hooks"]["UserPromptSubmit"]
    [hook] = entry["hooks"]
    assert hook["type"] == "command"
    words = shlex.split(hook["command"])
    assert words[:2] == ["python3", "-I"]
    assert words[2].startswith("$CLAUDE_PROJECT_DIR/") and '"$CLAUDE_PROJECT_DIR"/' in hook["command"]
    assert (ROOT / words[2].removeprefix("$CLAUDE_PROJECT_DIR/")).resolve() == SCRIPT.resolve() and SCRIPT.is_file()
    assert words[3:4] == ["--study"] and len(words) == 5 and not words[4].startswith("-")
    assert hook.get("onFailure") != "block"
    bound = hook_table().get("read-timeout-seconds")
    assert bound is not None, "chapter 18's hook table gives no bound on the CLI call"
    assert hook.get("timeout", DEFAULT_HOOK_TIMEOUT_SECONDS) > float(bound)


# --- how a test starts the script ----------------------------------------------------------------------------------------


def started(arguments, *, session="session-1", env=None, path=None, script=SCRIPT, project=ROOT, cwd=None, wait=120):
    """The script started as Claude Code starts it: `python3 -I`, the hook's JSON on stdin, `CLAUDE_PROJECT_DIR` set unless `project` is None."""
    environment = {**os.environ, **(env or {})}
    environment.pop("CLAUDE_PROJECT_DIR", None)
    if project is not None:
        environment["CLAUDE_PROJECT_DIR"] = str(project)
    if path is not None:
        environment["PATH"] = path
    prompt = {"session_id": session, "hook_event_name": "UserPromptSubmit", "prompt": "What is pending?", "cwd": str(project or ROOT)}
    try:
        result = subprocess.run(
            [PYTHON3, "-I", str(script), *arguments], input=json.dumps(prompt), capture_output=True, text=True, env=environment,
            cwd=cwd or ROOT, timeout=wait,
        )
    except subprocess.TimeoutExpired:
        result = None
    assert result is not None, f"the script did not end within {wait} s"
    assert_never_blocks(result)
    return result


def assert_never_blocks(result):
    """exit 0, and a stdout that is plain text: not a JSON object, and not a text that Claude Code would try to parse as one."""
    assert result.returncode == 0, (result.stdout, result.stderr)
    text = result.stdout.strip()
    assert not (text.startswith("{") and text.endswith("}")), text[:200]
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    assert not isinstance(parsed, dict), text[:200]


class Stub:
    """A stub `uv` first on `PATH`: it records each start (its arguments and folder) and answers the text it was given."""

    def __init__(self, folder: Path, answer: str, sleep: float = 0):
        self.bin = folder / "stub-bin"
        self.bin.mkdir()
        (self.bin / "uv").write_text(STUB_UV, encoding="utf-8")
        (self.bin / "uv").chmod(0o755)
        self.log, answer_file = folder / "starts.jsonl", folder / "answer.txt"
        answer_file.write_text(answer, encoding="utf-8")
        self.env = {"STUB_LOG": str(self.log), "STUB_ANSWER": str(answer_file), "STUB_SLEEP": str(sleep)}
        self.path = f"{self.bin}{os.pathsep}{os.environ['PATH']}"

    def starts(self) -> list:
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []


def since_zero(study) -> str:
    code, out, err = run_cli("status", "--study", study, "--since", "0", "--json")
    assert code == 0, (out, err)
    return out


# --- what a start of the script starts and reads ---------------------------------------------------------------------


def test_the_script_starts_one_process_the_status_since_0_read_in_the_project_folder_and_prints_from_its_answer(tmp_path):
    study = compared_study(tmp_path / "bike")
    answer = since_zero(study)
    stub = Stub(tmp_path, answer)
    missing = tmp_path / "no-such-study"
    result = started(["--study", str(missing)], env=stub.env, path=stub.path, cwd=tmp_path)
    starts = stub.starts()
    assert len(starts) == 1, starts
    [start] = starts
    assert start["arguments"] == [*CONTRACT["first_arguments"], "status", "--study", str(missing), "--since", "0", "--json"]
    assert Path(start["cwd"]).resolve() == ROOT.resolve()
    payload = json.loads(answer)
    assert payload["study"]["study_id"] in result.stdout
    assert f"Write sequence: {payload['write_sequence']}" in result.stdout
    assert not missing.exists()


# --- what the text holds ---------------------------------------------------------------------------------------------


def quoted(value) -> str:
    """A text of the Study as the script prints it: a JSON string, so that a quote or a line break in it stays on its line."""
    return json.dumps(value, ensure_ascii=False)


def lines_of(text: str, start: str) -> list:
    return [line for line in text.splitlines() if line.startswith(start)]


def pending_lines(text: str) -> list:
    return lines_of(text, "- Comparison ")


def decision_lines(text: str) -> list:
    return lines_of(text, "- Decision ")


def assert_holds_the_study(text: str, study, payload):
    """Each value of `payload` (the CLI's `status --json` object of `study`) that the text names, on the line that names it."""
    assert quoted(str(study)) in text.splitlines()[0] and payload["study"]["study_id"] in text.splitlines()[0]
    assert f"Write sequence: {payload['write_sequence']}" in text.splitlines()
    pending = pending_lines(text)
    assert len(pending) == len(payload["pending_decisions"])
    for entry in payload["pending_decisions"]:
        [line] = [line for line in pending if entry["comparison_id"] in line]
        assert quoted(entry["question"]["text"]) in line, line
        for option in entry["options"]:
            assert f"{option['id']} {quoted(option['text'])}" in line, (option, line)
    decided = decision_lines(text)
    assert len(decided) == len(payload["decisions"])
    for decision in payload["decisions"]:
        [line] = [line for line in decided if decision["decision_id"] in line]
        assert f"question {quoted(decision['question'])}" in line, line
        assert f"option {quoted(decision['option'])}" in line, line
        assert f"author {decision['author']}" in line, line
        assert ("source none" if decision["source"] is None else f"source {quoted(decision['source'])}") in line, line
        assert f"cited {', '.join(decision['cited_ids']) or 'none'};" in line, line
        assert f"applies {'true' if decision['applies'] else 'false'}" in line, line
        change = decision["evidence_change"]
        assert f"evidence_change {'none' if change is None else change['state']}" in line, line


def status_json(study) -> dict:
    code, out, err = run_cli("status", "--study", study, "--json")
    assert code == 0, (out, err)
    return json.loads(out)


@pytest.mark.parametrize("make", [decided_study, chinook_decided_study, rescored_study, several_pending_study], ids=lambda make: make.__name__)
def test_the_text_names_the_study_its_write_sequence_each_pending_decision_and_each_decision_status_json_lists(tmp_path, make):
    study = make(tmp_path)
    result = started(["--study", str(study)])
    payload = status_json(study)
    assert payload["decisions"] or payload["pending_decisions"]
    assert_holds_the_study(result.stdout, study, payload)
    assert_ends_with_the_rule(result.stdout)


# --- the rule --------------------------------------------------------------------------------------------------------


def assert_ends_with_the_rule(stdout: str):
    """The rule, whole, on the last line, after the Study's values."""
    rule = the_rule()
    assert rule and "\n" not in rule
    assert stdout.rstrip("\n").splitlines()[-1] == rule


def test_the_rule_names_the_read_the_read_sequence_decide_and_a_proxy_decision_with_its_source():
    rule = the_rule()
    for named in ("status --json", "--read-sequence", "decide", "--author proxy", "--source", "write_sequence"):
        assert named in rule, named


# --- when the script cannot read --------------------------------------------------------------------------------------


def failure_line() -> str:
    return getattr(script(), "FAILURE_LINE", "")


def assert_is_the_failure_line(result):
    line = failure_line()
    assert line and "\n" not in line and the_rule() and the_rule() in line
    assert result.stdout == line + "\n", result.stdout[:300]


def gone(pid) -> bool:
    """True when no process has this id, or when it is a zombie that nothing has reaped yet."""
    status = Path(f"/proc/{pid}/status")
    try:
        return "\nState:\tZ" in status.read_text(encoding="utf-8")
    except FileNotFoundError:
        return True


def shortened(tmp_path, seconds: float) -> Path:
    """A copy of the script whose bound on the CLI call is `seconds`: the one means a test has to wait less than the bound itself."""
    source = SCRIPT.read_text(encoding="utf-8")
    line = f"READ_TIMEOUT_SECONDS = {script().READ_TIMEOUT_SECONDS}\n"
    assert source.count(line) == 1
    copy = tmp_path / "copy" / SCRIPT.name
    copy.parent.mkdir()
    copy.write_text(source.replace(line, f"READ_TIMEOUT_SECONDS = {seconds}\n"), encoding="utf-8")
    return copy


def test_given_no_study_the_script_prints_the_failure_line():
    assert_is_the_failure_line(started([]))


def test_a_study_the_cli_refuses_as_not_found_gives_the_failure_line(tmp_path):
    missing = tmp_path / "no-such-study"
    code, out, _ = run_cli("status", "--study", missing, "--json")
    assert code != 0 and json.loads(out)["error"]["code"] == "STUDY_NOT_FOUND"
    assert_is_the_failure_line(started(["--study", str(missing)]))


def test_a_cli_that_cannot_be_started_because_no_uv_is_on_path_gives_the_failure_line(tmp_path):
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    assert_is_the_failure_line(started(["--study", "runs/bike"], path=str(empty)))


def test_a_cli_that_does_not_answer_within_the_bound_gives_the_failure_line_and_is_stopped_with_its_child(tmp_path):
    stub = Stub(tmp_path, "", sleep=600)
    began = time.monotonic()
    result = started(["--study", "runs/bike"], env=stub.env, path=stub.path, script=shortened(tmp_path, 2), wait=30)
    assert time.monotonic() - began < 60
    assert_is_the_failure_line(result)
    [start] = stub.starts()
    deadline = time.monotonic() + 10
    while not all(gone(pid) for pid in start["pids"]) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert all(gone(pid) for pid in start["pids"]), start["pids"]


@pytest.mark.parametrize(
    "answer",
    ["not JSON at all\n", "[]\n", '{"ok": false}\n', '{"ok": true}\n{"ok": true}\n', '{"ok": true}\n'],
    ids=["not-json", "not-an-object", "ok-false", "two-objects", "ok-true-without-the-keys-the-text-names"],
)
def test_an_answer_that_is_not_one_json_object_with_ok_true_and_the_keys_the_text_names_gives_the_failure_line(tmp_path, answer):
    stub = Stub(tmp_path, answer)
    assert_is_the_failure_line(started(["--study", "runs/bike"], env=stub.env, path=stub.path))
    assert len(stub.starts()) == 1


def test_without_claude_project_dir_the_script_starts_nothing_and_prints_the_failure_line(tmp_path):
    stub = Stub(tmp_path, since_zero(compared_study(tmp_path / "bike")))
    assert_is_the_failure_line(started(["--study", "runs/bike"], env=stub.env, path=stub.path, project=None))
    assert stub.starts() == []


# --- the next prompt knows a Decision recorded since ---------------------------------------------------------------

QUOTED = r'"(?:[^"\\]|\\.)*"'


def write_sequence_of(text: str) -> int:
    [line] = lines_of(text, "Write sequence: ")
    return int(line.removeprefix("Write sequence: "))


def pending_of(text: str) -> list:
    """(comparison id, question, {option id: option text}) of each pending line of the text, read as an agent reads it."""
    found = []
    for line in pending_lines(text):
        match = re.fullmatch(rf"- Comparison (\S+): question ({QUOTED}); options (.*)\.", line)
        assert match, line
        options = {name: json.loads(value) for name, value in re.findall(rf"(\w+) ({QUOTED})", match[3])}
        found.append((match[1], json.loads(match[2]), options))
    return found


@pytest.mark.parametrize("make", [compared_study, chinook_pending_study], ids=["bike", "chinook"])
def test_after_a_decision_recorded_as_the_panel_records_it_the_next_prompt_of_a_new_session_names_it_and_no_longer_its_pending_decision(tmp_path, make):
    study = make(tmp_path)
    before = started(["--study", str(study)], session="session-before").stdout
    [(comparison, _, options)] = pending_of(before)
    option = options["keep_candidate"]
    code, out, err = decide(study, option, "panel-1", write_sequence_of(before), comparison)
    assert code == 0, (out, err)
    after = started(["--study", str(study)], session="session-after").stdout
    assert write_sequence_of(after) == write_sequence_of(before) + 2
    assert [entry for entry in pending_of(after) if entry[0] == comparison] == []
    [line] = decision_lines(after)
    assert f"option {quoted(option)}" in line and "author human;" in line and f"cited {comparison};" in line


RULE_SOURCE = "rule: keep the Candidate when its mean absolute error is lower than the Control's"


def test_a_proxy_decision_recorded_as_the_rule_says_is_listed_with_its_source_and_named_by_the_next_prompt(tmp_path):
    study = compared_study(tmp_path)
    before = started(["--study", str(study)]).stdout
    [(comparison, question, options)] = pending_of(before)
    code, out, err = run_cli(
        "decide", "--study", study, "--question", question, "--option", options["keep_candidate"], "--author", "proxy",
        "--source", RULE_SOURCE, "--artifact", comparison, "--request-id", "proxy-1", "--read-sequence", str(write_sequence_of(before)), "--json",
    )
    assert code == 0, (out, err)
    [decision] = status_json(study)["decisions"]
    assert (decision["author"], decision["source"], decision["cited_ids"]) == ("proxy", RULE_SOURCE, [comparison])
    [line] = decision_lines(started(["--study", str(study)], session="session-2").stdout)
    assert decision["decision_id"] in line and "author proxy;" in line and f"source {quoted(RULE_SOURCE)};" in line


# --- the cut ---------------------------------------------------------------------------------------------------------

# Claude Code's cap on a hook's plain stdout, past which it gives the model a file path and a preview instead (code.claude.com/docs/en/hooks,
# read 2026-11-24).
CLAUDE_CODE_CAP = 10_000


def test_past_the_limit_the_oldest_decisions_are_left_out_with_a_count_line_and_the_study_its_pending_decisions_and_the_rule_stay(tmp_path):
    study = several_pending_study(tmp_path)
    payload = status_json(study)
    [assessment, *_] = payload["assessments"]
    for number in range(40):
        code, out, err = run_cli(
            "decide", "--study", study, "--question", f"Is Assessment {number} worth a second look?", "--option", "Not yet", "--author", "proxy",
            "--source", f"rule {number}: an Assessment is looked at again once a week", "--artifact", assessment["assessment_id"],
            "--request-id", f"rule-{number}", "--read-sequence", str(payload["write_sequence"] + 2 * number), "--json",
        )
        assert code == 0, (out, err)
    payload = status_json(study)
    assert len(payload["pending_decisions"]) == 2 and len(payload["decisions"]) == 40
    whole = sum(len(line) + 1 for line in decision_lines(started(["--study", str(study)], script=unbounded(tmp_path)).stdout))
    result = started(["--study", str(study)])
    module = script()
    limit = getattr(module, "TEXT_LIMIT", None)
    assert limit is not None and whole > limit
    assert len(result.stdout) <= limit < CLAUDE_CODE_CAP
    count_line = getattr(module, "LEFT_OUT_LINE", "{count}")
    [count] = [int(m[1]) for line in result.stdout.splitlines() if (m := re.fullmatch(re.escape(count_line).replace(re.escape("{count}"), r"(\d+)"), line))]
    ids = [decision["decision_id"] for decision in payload["decisions"]]
    shown = [line.split()[2].rstrip(":") for line in decision_lines(result.stdout)]
    assert count > 0 and shown == ids[count:]
    assert ids[-1] in shown
    assert len(pending_of(result.stdout)) == 2 and write_sequence_of(result.stdout) == payload["write_sequence"]
    assert_ends_with_the_rule(result.stdout)


def unbounded(tmp_path) -> Path:
    """A copy of the script with no limit on its text: what it would print whole."""
    source = SCRIPT.read_text(encoding="utf-8")
    line = f"TEXT_LIMIT = {getattr(script(), 'TEXT_LIMIT', None)}\n"
    copy = tmp_path / "unbounded" / SCRIPT.name
    copy.parent.mkdir()
    copy.write_text(source.replace(line, "TEXT_LIMIT = 10 ** 9\n"), encoding="utf-8")
    return copy


# --- the script writes nothing and keeps nothing -----------------------------------------------------------------------


def recorded(result) -> dict:
    """The record `_hook_recorder.py` printed as the last line of stderr."""
    line = result.stderr.rstrip("\n").splitlines()[-1]
    assert line.startswith("RECORD "), result.stderr[-500:]
    return json.loads(line.removeprefix("RECORD "))


def files_of(folder) -> dict:
    return {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(Path(folder).rglob("*")) if path.is_file()}


def porcelain() -> str:
    return subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def writes_of(record) -> list:
    """What the script's own process wrote, made, moved or removed; `subprocess` opens the null device read-write for a child's stdin."""
    opened = [entry for entry in record["opened"] if entry["writes"] and entry["path"] != os.devnull]
    return opened + record["changed"]


@pytest.mark.parametrize("make", [compared_study, chinook_pending_study], ids=["bike", "chinook"])
def test_two_prompts_in_two_sessions_get_the_same_text_and_the_scripts_process_writes_nothing_and_opens_no_file_of_the_study(tmp_path, make):
    study = make(tmp_path)
    before, sequence, status_before = files_of(study), status_json(study)["write_sequence"], porcelain()
    texts = []
    for session in ("session-1", "session-2"):
        result = started([str(SCRIPT), "--study", str(study)], session=session, script=RECORDER)
        record = recorded(result)
        assert writes_of(record) == []
        assert [entry for entry in record["opened"] if entry["path"] and Path(entry["path"]).is_relative_to(Path(study).resolve())] == []
        assert [entry["call"] for entry in record["started"]] == ["subprocess"]
        texts.append(result.stdout)
    assert texts[0] == texts[1] and pending_of(texts[0])
    assert files_of(study) == before and status_json(study)["write_sequence"] == sequence
    assert porcelain() == status_before


@pytest.mark.parametrize("make", [compared_study, chinook_pending_study], ids=["bike", "chinook"])
def test_with_a_stub_uv_the_home_and_temporary_folders_given_to_the_script_stay_empty(tmp_path, make):
    study = make(tmp_path / "study")
    stub = Stub(tmp_path, since_zero(study))
    home, temporary = tmp_path / "home", tmp_path / "tmp"
    home.mkdir(), temporary.mkdir()
    env = {**stub.env, "HOME": str(home), "TMPDIR": str(temporary)}
    texts = [started(["--study", str(study)], session=session, env=env, path=stub.path).stdout for session in ("session-1", "session-2")]
    assert texts[0] == texts[1] and write_sequence_of(texts[0]) == status_json(study)["write_sequence"]
    assert list(home.iterdir()) == [] and list(temporary.iterdir()) == []
