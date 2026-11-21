"""Ticket #97: the offline rehearsal of the Campaign's commands (chapter 16), with the provider patched.

The commands are read from chapter 16's `data-campaign` lines, their placeholders are filled with the fixed values below
(the values the paid Campaign of #98 uses unchanged), and each line is run as a separate process in a fresh copy of the
checkout: the working directory is the copy's root, the code is the copy's, and `--study` is the same relative path in
every line. The one thing changed is the provider: a small driver (`DRIVER`) replaces `prepared_model` with Inspect's mock
model, then runs `hypotrail.__main__` with the line's own arguments. No model is called and the network is guarded in the
driver as it is in the suite.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from inspect_ai.log import read_eval_log

ROOT = Path(__file__).resolve().parent.parent
CHAPTER = Path("docs/handbook/chapters/16-acceptance-grid.html")

# The fixed values of the Campaign's placeholders. #98 runs the lines with these, unchanged.
STUDY_DIR = "campaign-study"
REQUEST_ID_PLAIN = "campaign-plain"
REQUEST_ID_VERIFY = "campaign-verify"
REPORT_FILE = "campaign-report.html"

FAKE_KEY = "sk-ant-FAKE-rehearsal-0123456789abcdef"
SERVED_MODEL = "claude-sonnet-5-5-rehearsal"  # what the patched provider reports: not the name the Campaign requests
PREFIX = "uv run python -m hypotrail "
CASES = [f"E{n:02d}" for n in range(1, 13)]
EXPECTED_RUN_ARGS = {
    "plain": "--mode llm_live --config plain --partition public_check --repeats 3 --model anthropic/claude-sonnet-5-5",
    "verify": "--mode llm_live --config verify --partition public_check --repeats 3 --model anthropic/claude-sonnet-5-5",
}

DRIVER = '''
"""Runs `python -m hypotrail ARGS` with the provider patched. Written by tests/test_campaign_rehearsal.py."""
import json, os, runpy, socket, sys

ATTEMPTS = []  # network attempts and provider constructions, written to the rehearsal log at exit
LOG = os.environ["REHEARSAL_LOG"]


def note(kind, detail):
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": kind, "detail": detail, "argv": sys.argv[1:]}) + "\\n")


def blocked(*args, **kwargs):
    note("network", repr(args[:2]))
    raise RuntimeError("network access attempted in the rehearsal")


for name in ("connect", "connect_ex"):
    real = getattr(socket.socket, name)

    def guarded(self, address, *args, _real=real, **kwargs):
        if self.family == socket.AF_UNIX or address[0] in ("127.0.0.1", "::1", "localhost"):
            return _real(self, address, *args, **kwargs)
        return blocked(address)

    setattr(socket.socket, name, guarded)
real_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda host, *a, **k: real_getaddrinfo(host, *a, **k) if host in ("127.0.0.1", "::1", "localhost") else blocked(host)

note("start", os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
from _run_agent_helpers import scripted
from hypotrail.agentic import live, runner

script = scripted()


def provider(input, tools, tool_choice, config):
    output = script(input, tools, tool_choice, config)
    output.model = os.environ["REHEARSAL_SERVED_MODEL"]
    return output


def prepared_model(model_id, api_key, *args, **kwargs):
    note("model", {"requested": model_id, "key_given": bool(api_key)})
    return runner.mock_model(provider)


live.prepared_model = prepared_model
sys.argv = ["hypotrail"] + sys.argv[1:]
runpy.run_module("hypotrail", run_name="__main__", alter_sys=True)
'''


def campaign_lines(checkout: Path) -> dict:
    """`data-campaign` name -> the line chapter 16 gives, read from the copy."""
    text = (checkout / CHAPTER).read_text(encoding="utf-8")
    lines = dict(re.findall(r'<code data-campaign="([a-z-]+)">(.*?)</code>', text))
    assert list(lines) == ["run-plain", "run-verify", "assess-plain", "assess-verify", "compare", "report"], list(lines)
    return lines


def fill(line: str, values: dict) -> str:
    for placeholder, value in values.items():
        line = line.replace(placeholder, value)
    return line


class Rehearsal:
    """A fresh copy of the checkout and the Campaign run in it, step by step."""

    def __init__(self, base: Path):
        self.base = base
        self.checkout = base / "checkout"
        self.log = base / "rehearsal.jsonl"
        self.driver = base / "driver.py"
        self.driver.write_text(DRIVER, encoding="utf-8")
        skip = {".venv", ".git", ".claude", "__pycache__", ".pytest_cache"}
        shutil.copytree(ROOT, self.checkout, ignore=lambda folder, names: [n for n in names if n in skip])
        self.lines = campaign_lines(self.checkout)
        # The README's install line, as the live Campaign's checkout had it: `uv run` then resolves the copy's own environment (93-R1-01).
        synced = subprocess.run(["uv", "sync", "--locked", "--all-extras"], cwd=self.checkout, capture_output=True, text=True)
        assert synced.returncode == 0, synced.stderr
        self.launched = []  # the argv each line was started with
        self.ran = []  # (argv text after the prefix, exit code, stdout, stderr)
        env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy") and k != "ANTHROPIC_AUTH_TOKEN"}
        env.update(
            HYPOTRAIL_ANTHROPIC_API_KEY=FAKE_KEY, PYTHONPATH=str(self.checkout / "src"), NO_PROXY="*", REHEARSAL_LOG=str(self.log),
            REHEARSAL_SERVED_MODEL=SERVED_MODEL,
        )
        self.env = env

    def command(self, text: str):
        """Run one line, as it reads after the prefix, in the copy's root."""
        assert text.startswith(PREFIX), text
        args = text[len(PREFIX):].split()
        launched = ["uv", "run", "python", str(self.driver), *args]  # the live line's launcher, `uv run python`, then the driver in place of `-m hypotrail`
        self.launched.append(launched)
        done = subprocess.run(launched, cwd=self.checkout, env=self.env, capture_output=True, text=True)
        self.ran.append((text, done.returncode, done.stdout, done.stderr))
        return done

    def campaign(self, name: str, values: dict):
        return self.command(fill(self.lines[name], {**values, "DIR": STUDY_DIR}))

    def status(self) -> dict:
        done = self.command(f"{PREFIX}status --study {STUDY_DIR} --json")
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    def attempt(self, request_id: str) -> dict:
        found = [a for a in self.status()["attempts"] if a["request_id"] == request_id]
        assert len(found) == 1, (request_id, found)
        return self.study / "attempts" / found[0]["attempt_id"]

    @property
    def study(self) -> Path:
        return self.checkout / STUDY_DIR

    def notes(self, kind: str) -> list:
        if not self.log.exists():
            return []
        return [n for n in map(json.loads, self.log.read_text(encoding="utf-8").splitlines()) if n["kind"] == kind]


@pytest.fixture(scope="module")
def rehearsal(tmp_path_factory):
    """The whole Campaign, run once. The fixture asserts nothing: each test below asserts its own criterion on what was recorded."""
    r = Rehearsal(tmp_path_factory.mktemp("rehearsal"))
    r.init = r.command(f"{PREFIX}init --workload chinook --study {STUDY_DIR}")
    r.run_plain = r.campaign("run-plain", {"REQUEST_ID_PLAIN": REQUEST_ID_PLAIN})
    r.run_verify = r.campaign("run-verify", {"REQUEST_ID_VERIFY": REQUEST_ID_VERIFY})
    r.folders = {}
    r.ids = {}
    for side, request_id in (("plain", REQUEST_ID_PLAIN), ("verify", REQUEST_ID_VERIFY)):
        try:
            folder = r.attempt(request_id)
        except AssertionError:
            continue
        r.folders[side] = folder
        if (folder / "observation_set.json").exists():  # an Attempt that did not complete has none: the tests say so
            r.ids[side] = json.loads((folder / "observation_set.json").read_text(encoding="utf-8"))["observation_set_id"]
    status = r.status() if r.folders else {"revisions": [{"artifacts": []}]}
    r.references_id = next((a["artifact_id"] for a in status["revisions"][-1]["artifacts"] if a["role"] == "references"), None)
    r.assessments = {}
    if len(r.ids) == 2:
        for side in ("plain", "verify"):
            name = f"assess-{side}"
            values = {"OBSERVATION_SET_ID_PLAIN": r.ids["plain"], "OBSERVATION_SET_ID_VERIFY": r.ids["verify"], "REFERENCES_ID": r.references_id}
            done = r.campaign(name, values)
            found = re.search(r"Assessment ([0-9a-f-]{36})", done.stdout)
            r.assessments[side] = found.group(1) if found else None
    r.compare = None
    if len(r.assessments) == 2 and all(r.assessments.values()):
        r.compare = r.campaign("compare", {"ASSESSMENT_ID_PLAIN": r.assessments["plain"], "ASSESSMENT_ID_VERIFY": r.assessments["verify"]})
        r.report = r.campaign("report", {"FILE": REPORT_FILE})
    return r


def manifest_of(folder: Path) -> dict:
    return json.loads((folder / "attempt.json").read_text(encoding="utf-8"))


def observations_of(folder: Path) -> list:
    return [json.loads(line) for line in (folder / "observations.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def comparison_of(r: Rehearsal) -> dict:
    (path,) = (r.study / "comparisons").glob("*/comparison.json")
    return json.loads(path.read_text(encoding="utf-8"))


# --- C1 and Tightened A: the exact `run agent` lines, in a fresh copy, from the same directory, the provider patched --------------------


def test_each_of_the_two_run_agent_lines_runs_in_a_fresh_copy_from_its_root_with_the_same_relative_study_and_exits_0_with_a_completed_attempt(rehearsal):
    r = rehearsal
    assert r.init.returncode == 0, r.init.stderr
    assert (r.checkout / ".git").exists() is False and (r.checkout / "src" / "hypotrail").is_dir()  # a copy, not the working tree
    assert r.checkout != ROOT and not str(STUDY_DIR).startswith("/")  # the relative path the Campaign uses
    for name, done in (("plain", r.run_plain), ("verify", r.run_verify)):
        assert done.returncode == 0, (name, done.stdout[-1500:], done.stderr[-1500:])
        manifest = manifest_of(r.attempt(REQUEST_ID_PLAIN if name == "plain" else REQUEST_ID_VERIFY))
        assert manifest["technical_status"] == "completed", name
        assert manifest["mode"] == "llm_live" and manifest["effective_config"]["configuration"]["id"] == name
    # every line ran in the copy's root, with the code of the copy: its own `src` and no other
    starts = r.notes("start")
    assert starts and {n["detail"] for n in starts} == {str(r.checkout)}


# --- C2: 36 Episodes each, with their statuses, the limits and the key ---------------------------------------------------------------------


def test_each_attempt_holds_36_episodes_e01_to_e12_by_three_repeats_with_a_status_the_same_model_and_limits_and_no_key_anywhere(rehearsal):
    r = rehearsal
    assert set(r.folders) == {"plain", "verify"}
    manifests = {side: manifest_of(folder) for side, folder in r.folders.items()}
    for side, folder in r.folders.items():
        episodes = observations_of(folder)
        assert sorted((e["case_id"], e["repeat"]) for e in episodes) == sorted((c, n) for c in CASES for n in range(3)), side
        assert len(episodes) == 36
        assert all(e["status"] in {"produced", "failed", "missing"} for e in episodes), side
        limits = manifests[side]["effective_config"]["limits"]
        assert (limits["response_cache"], limits["sample_retries"], limits["transport_retries"], limits["concurrency"]) == (False, 0, 0, 1), side
    plain, verify = (manifests[s]["effective_config"] for s in ("plain", "verify"))
    assert plain["model"] == verify["model"] == "anthropic/claude-sonnet-5-5"
    assert plain["limits"] == verify["limits"]
    # the fake key is in no output of any step and in no file of the Study; the Inspect logs are searched decoded too
    shown = "".join(out + err for _, _, out, err in r.ran).encode()
    blob = shown + b"".join(p.read_bytes() for p in r.study.rglob("*") if p.is_file())
    for log in r.study.rglob("*.eval"):
        blob += read_eval_log(str(log)).model_dump_json().encode()  # decoded through Inspect's log API
    assert FAKE_KEY.encode() not in blob
    assert (r.checkout / REPORT_FILE).exists() and FAKE_KEY.encode() not in (r.checkout / REPORT_FILE).read_bytes()


# --- C3: the rehearsed lines are chapter 16's lines, placeholders filled -----------------------------------------------------------------


def test_the_lines_that_ran_are_chapter_16s_data_campaign_lines_with_their_placeholders_filled_and_the_campaigns_flags(rehearsal):
    r = rehearsal
    assert (ROOT / CHAPTER).read_bytes() == (r.checkout / CHAPTER).read_bytes()  # the copy's chapter is the checkout's
    prefix_len = len(PREFIX)
    ran = [text for text, *_ in r.ran if " --json" not in text and "init --workload" not in text]
    expected = [
        fill(r.lines["run-plain"], {"DIR": STUDY_DIR, "REQUEST_ID_PLAIN": REQUEST_ID_PLAIN}),
        fill(r.lines["run-verify"], {"DIR": STUDY_DIR, "REQUEST_ID_VERIFY": REQUEST_ID_VERIFY}),
        fill(r.lines["assess-plain"], {"DIR": STUDY_DIR, "OBSERVATION_SET_ID_PLAIN": r.ids["plain"], "REFERENCES_ID": r.references_id}),
        fill(r.lines["assess-verify"], {"DIR": STUDY_DIR, "OBSERVATION_SET_ID_VERIFY": r.ids["verify"], "REFERENCES_ID": r.references_id}),
        fill(r.lines["compare"], {"DIR": STUDY_DIR, "ASSESSMENT_ID_PLAIN": r.assessments["plain"], "ASSESSMENT_ID_VERIFY": r.assessments["verify"]}),
        fill(r.lines["report"], {"DIR": STUDY_DIR, "FILE": REPORT_FILE}),
    ]
    assert ran == expected
    for text in ran:
        assert not re.search(r"\b[A-Z][A-Z_]{2,}\b", text[prefix_len:]), text  # no placeholder is left
    # #98's arguments, as the ticket states them, for each of the two invocations
    for side, request_id in (("plain", REQUEST_ID_PLAIN), ("verify", REQUEST_ID_VERIFY)):
        assert ran[0 if side == "plain" else 1] == f"{PREFIX}run agent --study {STUDY_DIR} {EXPECTED_RUN_ARGS[side]} --request-id {request_id}"


def test_each_line_is_started_with_the_live_launcher_uv_run_python_and_not_the_test_interpreter(rehearsal):
    # 93-R1-01, #97 Tightened A: `uv`'s environment resolution is rehearsed; only the provider patch (the driver) differs from the live line.
    r = rehearsal
    assert len(r.launched) == len(r.ran) and r.launched
    for argv in r.launched:
        assert argv[:3] == ["uv", "run", "python"] and argv[3] == str(r.driver), argv
        assert sys.executable not in argv


# --- C4 and Tightened B: assess twice, compare, report, offline ------------------------------------------------------------------------


def test_assess_twice_compare_with_plain_as_control_and_report_exit_0_and_the_comparison_is_compatible_and_strict(rehearsal):
    r = rehearsal
    assert set(r.assessments) == {"plain", "verify"} and all(r.assessments.values()), r.assessments
    assert r.compare is not None and r.compare.returncode == 0, r.compare and (r.compare.stdout, r.compare.stderr)
    assert r.report.returncode == 0, (r.report.stdout, r.report.stderr)
    assert (r.checkout / REPORT_FILE).stat().st_size > 0
    record = comparison_of(r)
    assert record["roles"] == {"control_assessment_id": r.assessments["plain"], "candidate_assessment_id": r.assessments["verify"]}
    assert record["comparability"]["status"] == "compatible" and all(c["passed"] for c in record["comparability"]["checks"])
    assert record["declared_factor"] == "configuration"
    assert record["warnings"] == []  # compatible with no warning is what strict means here


# --- D-028 condition 2: start and end times and the model the provider reported, for each invocation ------------------------------------


def test_each_invocation_records_its_start_and_end_times_and_the_model_the_provider_reported_and_plain_ran_before_verify(rehearsal):
    r = rehearsal
    stamps = {}
    for side, folder in r.folders.items():
        manifest = manifest_of(folder)
        assert manifest["started_at"] and manifest["finished_at"] and manifest["started_at"] < manifest["finished_at"], side
        assert manifest["effective_config"]["served_model"] == SERVED_MODEL, side  # reported, never the requested name
        assert manifest["effective_config"]["model"] == "anthropic/claude-sonnet-5-5"
        run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        assert run["served_models"] == [SERVED_MODEL], side
        provenance = json.loads((folder / "observation_set.json").read_text(encoding="utf-8"))["provenance"]
        assert provenance["served_model"] == SERVED_MODEL, side
        stamps[side] = (manifest["started_at"], manifest["finished_at"])
    assert stamps["plain"][1] <= stamps["verify"][0]  # two invocations back to back, plain then verify (D-028)


# --- C5: no model, no key that is real, no network -------------------------------------------------------------------------------------


def test_the_rehearsal_calls_no_model_and_makes_no_network_attempt_and_the_real_key_variable_is_not_read(rehearsal):
    r = rehearsal
    assert r.notes("network") == []
    models = r.notes("model")  # the patched provider, once per `run agent`, given the fake key
    assert [m["detail"]["requested"] for m in models] == ["anthropic/claude-sonnet-5-5"] * 2
    assert all(m["detail"]["key_given"] for m in models)
    assert r.env["HYPOTRAIL_ANTHROPIC_API_KEY"] == FAKE_KEY
