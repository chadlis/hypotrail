"""Ticket #20: the opt-in, bounded live run. Nothing here reaches a real provider.

The live path is exercised against a fake Anthropic endpoint on loopback, which
speaks the Messages API well enough to carry a tool call, so the provider
client, the key header, the logs and the key scan are all the real ones.
"""

import io
import json
import threading
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from _agent_helpers import CASES, CHINOOK, REFERENCES, WORKLOAD, oracle_sql, read_jsonl

from hypotrail import cli
from hypotrail.agentic import cases as case_module
from hypotrail.agentic import live as agentic_live
from hypotrail.agentic import projection, runner
from hypotrail.core import live as core_live

ROOT = Path(__file__).resolve().parent.parent
FAKE_KEY = "sk-ant-FAKE-live-key-0123456789abcdef"
MODEL_ID = "anthropic/claude-test-1"
PROXY_VARIABLES = ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("HYPOTRAIL_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("INSPECT_EVAL_MODEL", "anthropic/should-never-be-used")
    return monkeypatch


@pytest.fixture
def never_runs(monkeypatch):
    calls = []

    def fail(**kwargs):
        calls.append(kwargs)
        raise AssertionError("the live run was started")

    monkeypatch.setattr(agentic_live, "run_live", fail)
    return calls


def live_args(tmp_path, *extra):
    return ["spike", "live", "--config", "plain", "--out", str(tmp_path / "out"), "--json", *extra]


# --- the key ------------------------------------------------------------------------------------


def test_without_the_key_the_live_path_exits_5_names_the_blocker_and_sends_nothing(
    tmp_path, clean_env, never_runs, network_guard
):
    code, out, err = run_cli(*live_args(tmp_path, "--model", MODEL_ID))

    assert code == 5
    assert "LIVE_NOT_VALIDATED" in out + err
    error = json.loads(out)["error"]
    assert error["details"]["blocker"] == "HYPOTRAIL_ANTHROPIC_API_KEY is not set"
    assert error["details"]["status"] == "LIVE_NOT_VALIDATED"
    assert never_runs == []
    assert network_guard.attempts == []
    assert not (tmp_path / "out").exists()


def test_the_old_variable_name_is_not_read(tmp_path, clean_env, never_runs, network_guard):
    clean_env.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    code, out, _ = run_cli(*live_args(tmp_path, "--model", MODEL_ID))
    assert code == 5
    assert "HYPOTRAIL_ANTHROPIC_API_KEY is not set" in out
    assert network_guard.attempts == []


def test_a_bearer_token_in_the_environment_would_override_the_key_so_the_run_refuses(
    tmp_path, clean_env, never_runs
):
    clean_env.setenv("HYPOTRAIL_ANTHROPIC_API_KEY", FAKE_KEY)
    clean_env.setenv("ANTHROPIC_AUTH_TOKEN", "bearer-token")
    code, out, _ = run_cli(*live_args(tmp_path, "--model", MODEL_ID))
    assert code == 5
    assert "ANTHROPIC_AUTH_TOKEN" in out
    assert "bearer-token" not in out and FAKE_KEY not in out


def test_the_key_is_never_echoed(tmp_path, clean_env, monkeypatch):
    clean_env.setenv("HYPOTRAIL_ANTHROPIC_API_KEY", FAKE_KEY)
    monkeypatch.setattr(agentic_live, "run_live", lambda **kw: {
        "model": kw["model_id"], "tool_loop_observed": False, "episodes": []
    })
    code, out, err = run_cli(*live_args(tmp_path, "--model", MODEL_ID))
    assert code == 0
    assert FAKE_KEY not in out + err


# --- the model identifier ----------------------------------------------------------------------------


def test_without_a_model_the_run_exits_before_inspect_starts(tmp_path, clean_env, never_runs):
    clean_env.setenv("HYPOTRAIL_ANTHROPIC_API_KEY", FAKE_KEY)
    code, out, _ = run_cli(*live_args(tmp_path))
    assert code == 2
    assert json.loads(out)["error"]["code"] == "MODEL_REQUIRED"
    assert never_runs == []


@pytest.mark.parametrize(
    "model", ["claude-sonnet-5-5", "openai/gpt-x", "anthropic/bedrock/claude", "anthropic/", "anthropic/a b"]
)
def test_only_a_plain_anthropic_model_identifier_is_accepted(tmp_path, clean_env, never_runs, model):
    clean_env.setenv("HYPOTRAIL_ANTHROPIC_API_KEY", FAKE_KEY)
    code, out, _ = run_cli(*live_args(tmp_path, "--model", model))
    assert code == 2
    assert never_runs == []


def test_the_code_holds_no_default_model():
    source = (ROOT / "src" / "hypotrail").rglob("*.py")
    for path in source:
        text = path.read_text()
        assert "claude-sonnet" not in text and "claude-opus" not in text and "claude-haiku" not in text, path.name


# --- bounds ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        ["--case", "E01"],  # public_check
        ["--case", "D03", "--case", "E01"],
        ["--case", "D01", "--case", "D02", "--case", "D03"],  # 3 Episodes
        ["--case", "D03", "--case", "D05", "--repeats", "2"],  # 4 Episodes
        ["--case", "D03", "--repeats", "3"],
        ["--case", "D03", "--repeats", "0"],
        ["--case", "D03", "--case", "D03"],
        ["--case", "NOPE"],
    ],
)
def test_the_run_refuses_non_dev_cases_and_more_than_two_episodes(tmp_path, clean_env, never_runs, extra):
    clean_env.setenv("HYPOTRAIL_ANTHROPIC_API_KEY", FAKE_KEY)
    code, _, _ = run_cli(*live_args(tmp_path, "--model", MODEL_ID, *extra))
    assert code == 2
    assert never_runs == []


def test_two_episodes_on_dev_cases_are_accepted(tmp_path, clean_env, monkeypatch):
    clean_env.setenv("HYPOTRAIL_ANTHROPIC_API_KEY", FAKE_KEY)
    seen = []
    monkeypatch.setattr(agentic_live, "run_live", lambda **kw: seen.append(kw) or {
        "model": kw["model_id"], "tool_loop_observed": False, "episodes": []
    })
    code, _, _ = run_cli(*live_args(tmp_path, "--model", MODEL_ID))
    assert code == 0
    assert seen[0]["case_ids"] == ["D03", "D05"] and seen[0]["repeats"] == 1
    assert seen[0]["api_key"] == FAKE_KEY


# --- the provider client ------------------------------------------------------------------------------------


def test_the_key_reaches_the_provider_explicitly_and_no_environment_key_is_used(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "some-other-key")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    model = agentic_live.live_model(MODEL_ID, FAKE_KEY)
    client = model.api.client
    assert client.api_key == FAKE_KEY
    assert client.max_retries == 0
    assert str(client.base_url).rstrip("/") == "https://api.anthropic.com"


# --- a rehearsal against a fake endpoint -------------------------------------------------------------------------


class FakeAnthropic:
    """Speaks just enough of the Messages API to carry model -> tool -> model."""

    def __init__(self):
        cases = case_module.load_cases(CASES)
        self.sql = {c["question"]: oracle_sql(c["case_id"]) for c in cases if c["case_id"] in ("D03", "D05")}
        self.units = {c["question"]: c["unit"] for c in cases}
        self.requests = []
        self.cut_answers = False  # reply to the second call with a text cut by the output cap
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                reply = json.dumps(outer.reply(body)).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    @staticmethod
    def _text_of(blocks):
        if isinstance(blocks, str):
            return blocks
        return "".join(b.get("text", "") for b in blocks)

    def reply(self, body):
        first_user = next(m for m in body["messages"] if m["role"] == "user")
        question = next(q for q in self.sql if q in self._text_of(first_user["content"]))
        message = {
            "id": "msg_fake", "type": "message", "role": "assistant", "model": "claude-test-1-20261101",
            "stop_sequence": None, "usage": {"input_tokens": 120, "output_tokens": 30},
        }
        last = body["messages"][-1]
        results = [b for b in last["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]
        if not results:
            return {**message, "stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": "toolu_fake01", "name": "query_readonly", "input": {"sql": self.sql[question]}}
            ]}
        result = json.loads(self._text_of(results[0]["content"]))
        answer = {"status": "answered", "reason_code": None, "columns": result["columns"],
                  "rows": result["rows"], "unit": self.units[question], "evidence": [result["tool_call_id"]]}
        if self.cut_answers:
            return {**message, "stop_reason": "max_tokens", "content": [{"type": "text", "text": json.dumps(answer)[:40]}]}
        return {**message, "stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(answer)}]}


@pytest.fixture
def rehearsal(tmp_path, clean_env):
    for name in PROXY_VARIABLES:
        clean_env.delenv(name, raising=False)
    clean_env.setenv("NO_PROXY", "127.0.0.1,localhost")
    with FakeAnthropic() as fake:
        record = agentic_live.run_live(
            model_id=MODEL_ID,
            api_key=FAKE_KEY,
            workload_dir=CHINOOK,
            case_ids=["D03", "D05"],
            repeats=1,
            out_dir=tmp_path / "out",
            base_url=fake.url,
        )
        yield fake, record, tmp_path / "out"


def test_a_rehearsal_shows_a_real_client_carrying_model_tool_model_answer(rehearsal):
    fake, record, out = rehearsal
    assert record["tool_loop_observed"] is True
    assert [e["status"] for e in record["episodes"]] == ["produced", "produced"]
    assert [e["uses_tool_result"] for e in record["episodes"]] == [True, True]
    assert len(fake.requests) == 4  # two generations per Episode
    episodes = json.loads((out / "projection.json").read_text())
    assert all([s["kind"] for s in e["steps"]] == agentic_live.EXPECTED_SEQUENCE for e in episodes)


def test_the_key_is_sent_only_in_the_authorization_header(rehearsal):
    fake, _, _ = rehearsal
    for request in fake.requests:
        headers = {k.lower(): v for k, v in request["headers"].items()}
        assert headers["authorization"] == f"Bearer {FAKE_KEY}"
        assert "x-api-key" not in headers
        others = {k: v for k, v in headers.items() if k != "authorization"}
        assert FAKE_KEY not in json.dumps(others)
        assert FAKE_KEY not in json.dumps(request["body"])
        assert request["path"].endswith("/v1/messages")
        assert request["body"]["max_tokens"] == 1024
        assert request["body"]["model"] == "claude-test-1"


def test_the_record_holds_provider_model_revision_engine_parameters_and_hardware(rehearsal):
    _, record, out = rehearsal
    assert record["provider"] == "anthropic" and record["model"] == MODEL_ID
    assert record["served_models"] == ["claude-test-1-20261101"]
    assert record["engine"]["name"] == "inspect-ai" and record["engine"]["version"]
    assert record["hardware"] and record["machine"]
    assert record["effective_limits"]["model_turns"] == 6
    assert record["effective_limits"]["transport_retries"] == 0
    # the request parameters that took effect, as the log recorded them
    assert record["request_parameters"]["max_tokens"] == 1024
    assert record["request_parameters"]["model"] == "claude-test-1"
    assert "messages" not in record["request_parameters"]
    assert (out / "run.json").is_file() and (out / "projection.json").is_file()


def test_the_key_appears_in_no_file_the_run_produced(rehearsal):
    _, _, out = rehearsal
    files = [p for p in out.rglob("*") if p.is_file()]
    assert files
    assert agentic_live.scan_for_secret(out, FAKE_KEY) == []
    for path in files:
        assert FAKE_KEY.encode() not in path.read_bytes()


def test_the_scan_finds_a_key_in_a_plain_file_and_inside_a_compressed_log(tmp_path):
    (tmp_path / "plain.txt").write_text(f"x {FAKE_KEY} y")
    assert agentic_live.scan_for_secret(tmp_path, FAKE_KEY) == ["plain.txt"]

    # a log whose system prompt holds the key: invisible in the compressed bytes
    from _agent_helpers import ScriptedModel

    cases = case_module.load_cases(CASES, ["D03"])
    leaky = [{**cases[0], "question": cases[0]["question"] + " " + FAKE_KEY}]
    script = ScriptedModel(leaky)
    script.sql_by_question = {leaky[0]["question"]: oracle_sql("D03")}
    script.unit_by_question = {leaky[0]["question"]: "count"}
    script.case_by_question = {leaky[0]["question"]: "D03"}
    location = runner.run_episodes(
        leaky, workload=WORKLOAD, configuration="plain", model=runner.mock_model(script), repeats=1, log_dir=tmp_path / "logs"
    )
    assert FAKE_KEY.encode() not in Path(location).read_bytes()
    assert agentic_live.scan_for_secret(tmp_path / "logs", FAKE_KEY) == [Path(location).name]


def test_an_unreadable_log_does_not_stop_the_scan_of_the_other_files(tmp_path):
    # "a.eval" sorts first and is not a readable log; the key sits in a later file
    (tmp_path / "a.eval").write_bytes(b"PK\x03\x04 truncated, not a zip")
    (tmp_path / "z.txt").write_text(f"x {FAKE_KEY} y")
    assert agentic_live.scan_for_secret(tmp_path, FAKE_KEY) == ["z.txt"]


def test_an_unreadable_log_is_still_searched_as_raw_bytes(tmp_path):
    (tmp_path / "a.eval").write_bytes(b"PK\x03\x04 truncated " + FAKE_KEY.encode())
    assert agentic_live.scan_for_secret(tmp_path, FAKE_KEY) == ["a.eval"]


def test_an_unreadable_log_next_to_a_leak_still_ends_in_secret_in_output(tmp_path):
    from hypotrail.core.errors import HypotrailError

    (tmp_path / "a.eval").write_bytes(b"")
    (tmp_path / "z.txt").write_text(FAKE_KEY)
    with pytest.raises(HypotrailError) as caught:
        agentic_live._raise_if_leaked(tmp_path, FAKE_KEY)
    assert caught.value.code == "SECRET_IN_OUTPUT"
    assert caught.value.details == {"files": ["z.txt"]}
    assert FAKE_KEY not in str(caught.value)


@pytest.mark.parametrize(
    "content",
    [b"not a log", b"", b"PK\x03\x04 truncated, not a zip"],
    ids=["not-a-zip", "empty", "truncated-zip"],
)
def test_a_log_that_cannot_be_read_back_and_is_clean_in_raw_bytes_is_not_reported_clean(
    tmp_path, content
):
    from hypotrail.core.errors import HypotrailError

    (tmp_path / "a.eval").write_bytes(content)
    with pytest.raises(HypotrailError) as caught:
        agentic_live.scan_for_secret(tmp_path, FAKE_KEY)
    assert caught.value.code == "LOG_NOT_FULLY_SCANNED"
    assert caught.value.stage == "live"
    assert caught.value.details == {"files": ["a.eval"]}
    assert "could not be fully scanned" in caught.value.message
    assert FAKE_KEY not in str(caught.value)


def test_a_zip_that_read_eval_log_refuses_is_not_opened_by_hand(tmp_path):
    import zipfile

    # the key is compressed, so invisible in raw bytes; the zip is not a valid log
    with zipfile.ZipFile(tmp_path / "a.eval", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("samples/1.json", f"x {FAKE_KEY} y" * 50)
    assert FAKE_KEY.encode() not in (tmp_path / "a.eval").read_bytes()
    from hypotrail.core.errors import HypotrailError

    with pytest.raises(HypotrailError) as caught:
        agentic_live.scan_for_secret(tmp_path, FAKE_KEY)
    assert caught.value.code == "LOG_NOT_FULLY_SCANNED"
    assert caught.value.details == {"files": ["a.eval"]}


def test_the_live_module_does_not_import_zipfile():
    import ast

    tree = ast.parse(Path(agentic_live.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "zipfile" not in imported
    assert not hasattr(agentic_live, "zipfile")


def test_a_log_that_cannot_be_fully_scanned_fails_the_run_report(tmp_path):
    from hypotrail.core.errors import HypotrailError

    (tmp_path / "a.eval").write_bytes(b"not a log")
    with pytest.raises(HypotrailError) as caught:
        agentic_live._raise_if_leaked(tmp_path, FAKE_KEY)
    assert caught.value.code == "LOG_NOT_FULLY_SCANNED"


def test_a_run_that_leaks_the_key_is_reported_as_an_error(tmp_path, clean_env, monkeypatch):
    for name in PROXY_VARIABLES:
        clean_env.delenv(name, raising=False)
    clean_env.setenv("NO_PROXY", "127.0.0.1,localhost")
    real = projection.project_log

    def leaky(location, expected):
        episodes = real(location, expected=expected)
        episodes[0]["steps"].append({"kind": "note", "text": FAKE_KEY})
        return episodes

    monkeypatch.setattr(agentic_live.projection, "project_log", leaky)
    from hypotrail.core.errors import HypotrailError

    with FakeAnthropic() as fake, pytest.raises(HypotrailError) as caught:
        agentic_live.run_live(
            model_id=MODEL_ID, api_key=FAKE_KEY, workload_dir=CHINOOK,
            case_ids=["D03"], repeats=1, out_dir=tmp_path / "out", base_url=fake.url,
        )
    assert caught.value.code == "SECRET_IN_OUTPUT"
    assert FAKE_KEY not in str(caught.value)


def test_a_non_empty_output_directory_is_refused(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "earlier.txt").write_text("x")
    with pytest.raises(Exception, match="not empty"):
        agentic_live.run_live(
            model_id=MODEL_ID, api_key=FAKE_KEY, workload_dir=CHINOOK,
            case_ids=["D03"], repeats=1, out_dir=tmp_path / "out",
        )


def test_the_command_reads_the_cases_through_the_cases_module_and_validates_before_the_key(
    tmp_path, clean_env, never_runs, monkeypatch
):
    seen = []

    def fake_load_cases(path, case_ids=None):
        seen.append(Path(path).name)
        return [{"case_id": "D03"}, {"case_id": "D05"}]

    monkeypatch.setattr(case_module, "load_cases", fake_load_cases)
    # no key: the bounds are checked first, so an out-of-bounds request exits 2, not 5
    code, out, _ = run_cli(*live_args(tmp_path, "--model", MODEL_ID, "--case", "E01"))
    assert code == 2 and json.loads(out)["error"]["code"] == "CASE_NOT_DEV"
    assert seen == ["chinook-dev.jsonl"]
    code, out, _ = run_cli(*live_args(tmp_path, "--model", MODEL_ID))
    assert code == 5


def test_the_command_reaches_the_missing_key_without_importing_inspect(tmp_path):
    import subprocess
    import sys

    probe = (
        "import sys, json\n"
        "from hypotrail import cli\n"
        "code = cli.main(sys.argv[1:])\n"
        "print(json.dumps({'code': code, 'inspect': 'inspect_ai' in sys.modules}))\n"
    )
    env = {k: v for k, v in __import__("os").environ.items() if "ANTHROPIC" not in k}
    result = subprocess.run(
        [sys.executable, "-c", probe, "spike", "live", "--config", "plain", "--model", MODEL_ID, "--out", str(tmp_path / "o"), "--json"],
        capture_output=True, text=True, env=env, check=True,
    )
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report == {"code": 5, "inspect": False}


# --- opt-in --------------------------------------------------------------------------------------------------------


def test_nothing_in_the_suite_starts_a_live_run_against_the_real_endpoint():
    # The only run_live calls in tests pass a loopback base_url or are patched.
    for path in (ROOT / "tests").glob("test_*.py"):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if "run_live(" in line and "def " not in line:
                assert path.name == "test_live.py", (path.name, number)
    assert agentic_live.ANTHROPIC_BASE_URL == "https://api.anthropic.com"
    assert core_live.MAX_EPISODES == 2


# --- regression: a relative output directory, and summarising a kept log ----------------------------------------


def test_a_relative_output_directory_works(tmp_path, clean_env):
    for name in PROXY_VARIABLES:
        clean_env.delenv(name, raising=False)
    clean_env.setenv("NO_PROXY", "127.0.0.1,localhost")
    clean_env.chdir(tmp_path)
    with FakeAnthropic() as fake:
        record = agentic_live.run_live(
            model_id=MODEL_ID, api_key=FAKE_KEY, workload_dir=CHINOOK,
            case_ids=["D03"], repeats=1, out_dir=Path("relative-out"), base_url=fake.url,
        )
    assert record["inspect_log"].startswith("inspect/")
    assert (tmp_path / "relative-out" / "run.json").is_file()


def test_a_kept_log_can_be_summarised_again_without_any_model_call(rehearsal, tmp_path, network_guard):
    _, record, out = rehearsal
    (out / "run.json").unlink()
    (out / "projection.json").unlink()
    again = agentic_live.summarize(
        location=str(next((out / "inspect").glob("*.eval"))),
        out_dir=out,
        model_id=MODEL_ID,
        api_key=FAKE_KEY,
        case_ids=["D03", "D05"],
        repeats=1,
    )
    assert again == {**record, "database_sha256": None}
    assert (out / "run.json").is_file()


def _episode(answer, tool_rows):
    return {
        "final_answer": None if answer is None else json.dumps(answer),
        "steps": [{"kind": "tool_result", "result": {"rows": tool_rows}}],
    }


def test_uses_result_means_every_answer_row_is_a_row_the_tool_returned():
    tool_rows = [["Iron Maiden", 21], ["Led Zeppelin", 14], ["Deep Purple", 11], ["Metallica", 10]]
    # the model may fetch more rows than it reports (for example to check ties)
    assert agentic_live._uses_result(_episode({"rows": tool_rows[:3]}, tool_rows)) is True
    assert agentic_live._uses_result(_episode({"rows": tool_rows}, tool_rows)) is True
    # a value the tool never returned is not "using its result"
    assert agentic_live._uses_result(_episode({"rows": [["Iron Maiden", 22]]}, tool_rows)) is False
    assert agentic_live._uses_result(_episode({"rows": []}, tool_rows)) is False
    assert agentic_live._uses_result(_episode(None, tool_rows)) is None
    assert agentic_live._uses_result({"final_answer": "not json", "steps": [{"kind": "tool_result", "result": {"rows": []}}]}) is False


# --- review findings: a non-JSON tool message, and the key scan on a failing run ------------------------------


def test_a_tool_result_that_is_not_json_does_not_count_as_a_returned_row():
    episode = {
        "final_answer": json.dumps({"rows": [["Iron Maiden", 21]]}),
        "steps": [{"kind": "tool_result", "result": None}],
    }
    assert agentic_live._uses_result(episode) is False
    odd = {"final_answer": json.dumps({"rows": [["x", 1]]}), "steps": [
        {"kind": "tool_result", "result": {"rows": "not a list"}},
        {"kind": "tool_result", "result": {"columns": []}},
        {"kind": "tool_result", "result": ["a", "list"]},
    ]}
    assert agentic_live._uses_result(odd) is False


def test_a_non_json_tool_message_still_gives_a_summary_and_both_files(rehearsal, monkeypatch):
    _, _, out = rehearsal
    (out / "run.json").unlink()
    (out / "projection.json").unlink()
    real = projection.project_log

    def with_a_text_tool_message(location, expected):
        episodes = real(location, expected=expected)
        for step in episodes[0]["steps"]:
            if step["kind"] == "tool_result":
                step["result"] = None
        return episodes

    monkeypatch.setattr(agentic_live.projection, "project_log", with_a_text_tool_message)
    again = agentic_live.summarize(
        location=str(next((out / "inspect").glob("*.eval"))), out_dir=out, model_id=MODEL_ID,
        api_key=FAKE_KEY, case_ids=["D03", "D05"], repeats=1,
    )
    assert again["episodes"][0]["uses_tool_result"] is False
    assert again["episodes"][1]["uses_tool_result"] is True
    assert (out / "run.json").is_file() and (out / "projection.json").is_file()


def test_the_key_scan_runs_even_when_summarising_fails(rehearsal, monkeypatch):
    _, _, out = rehearsal
    (out / "stray.txt").write_text(FAKE_KEY)

    def broken(location, expected):
        raise RuntimeError("projection failed")

    monkeypatch.setattr(agentic_live.projection, "project_log", broken)
    from hypotrail.core.errors import HypotrailError

    with pytest.raises(HypotrailError) as caught:
        agentic_live.summarize(
            location=str(next((out / "inspect").glob("*.eval"))), out_dir=out, model_id=MODEL_ID,
            api_key=FAKE_KEY, case_ids=["D03", "D05"], repeats=1,
        )
    assert caught.value.code == "SECRET_IN_OUTPUT"
    assert caught.value.details["files"] == ["stray.txt"]
    assert FAKE_KEY not in str(caught.value)


def test_the_key_scan_runs_even_when_the_episodes_fail(tmp_path, clean_env, monkeypatch):
    out = tmp_path / "out"

    def fails_after_writing_the_key(cases, **kwargs):
        (kwargs["log_dir"].parent / "stray.txt").write_text(FAKE_KEY)
        raise RuntimeError("the run stopped")

    monkeypatch.setattr(agentic_live.runner, "run_episodes", fails_after_writing_the_key)
    from hypotrail.core.errors import HypotrailError

    with pytest.raises(HypotrailError) as caught:
        agentic_live.run_live(
            model_id=MODEL_ID, api_key=FAKE_KEY, workload_dir=CHINOOK,
            case_ids=["D03"], repeats=1, out_dir=out,
        )
    assert caught.value.code == "SECRET_IN_OUTPUT"


def test_a_failing_run_without_a_leak_keeps_its_own_error(tmp_path, clean_env, monkeypatch):
    def fails(cases, **kwargs):
        raise RuntimeError("the run stopped")

    monkeypatch.setattr(agentic_live.runner, "run_episodes", fails)
    with pytest.raises(RuntimeError, match="the run stopped"):
        agentic_live.run_live(
            model_id=MODEL_ID, api_key=FAKE_KEY, workload_dir=CHINOOK,
            case_ids=["D03"], repeats=1, out_dir=tmp_path / "out",
        )


def test_the_run_record_keeps_the_exact_prompt_text_of_its_configuration(rehearsal):
    _, record, out = rehearsal
    assert record["configuration"] == "plain"
    assert record["system_text"] == WORKLOAD.system_text("plain")
    assert json.loads((out / "run.json").read_text())["system_text"] == WORKLOAD.system_text("plain")


# --- ticket #49: one named Configuration, an explicit reasoning setting, a fuller record ------------------------------


def test_the_command_names_a_declared_configuration(tmp_path, clean_env, monkeypatch):
    clean_env.setenv("HYPOTRAIL_ANTHROPIC_API_KEY", FAKE_KEY)
    seen = []
    monkeypatch.setattr(agentic_live, "run_live", lambda **kw: seen.append(kw) or {
        "model": kw["model_id"], "tool_loop_observed": False, "episodes": []
    })
    args = ["spike", "live", "--config", "verify", "--model", MODEL_ID, "--out", str(tmp_path / "o"), "--json"]
    assert run_cli(*args)[0] == 0
    assert seen[0]["configuration"] == "verify"


def test_without_config_the_command_is_refused_before_anything_starts(tmp_path, clean_env, never_runs):
    clean_env.setenv("HYPOTRAIL_ANTHROPIC_API_KEY", FAKE_KEY)
    code, out, _ = run_cli("spike", "live", "--model", MODEL_ID, "--out", str(tmp_path / "o"), "--json")
    assert code == 2 and json.loads(out)["error"]["code"] == "INVALID_ARGUMENTS"
    assert never_runs == []


def test_an_unknown_configuration_is_refused_with_a_code_before_the_key_is_read_and_before_inspect_is_imported(
    tmp_path,
):
    import subprocess
    import sys

    probe = (
        "import sys, json, io\n"
        "from contextlib import redirect_stdout\n"
        "from hypotrail import cli\n"
        "out = io.StringIO()\n"
        "with redirect_stdout(out):\n"
        "    code = cli.main(sys.argv[1:])\n"
        "print(json.dumps({'code': code, 'inspect': 'inspect_ai' in sys.modules, 'out': out.getvalue()}))\n"
    )
    env = {k: v for k, v in __import__("os").environ.items() if "ANTHROPIC" not in k}
    env["HYPOTRAIL_ANTHROPIC_API_KEY"] = FAKE_KEY
    result = subprocess.run(
        [sys.executable, "-c", probe, "spike", "live", "--config", "nope", "--model", MODEL_ID,
         "--out", str(tmp_path / "o"), "--json"],
        capture_output=True, text=True, env=env, check=True,
    )
    report = json.loads(result.stdout)
    assert report["code"] == 2 and report["inspect"] is False
    assert json.loads(report["out"])["error"]["code"] == "CONFIGURATION_NOT_DECLARED"
    assert FAKE_KEY not in result.stdout + result.stderr


def test_an_unknown_configuration_is_refused_before_the_missing_key_is_reported(tmp_path, clean_env, never_runs):
    code, out, _ = run_cli("spike", "live", "--config", "nope", "--model", MODEL_ID,
                           "--out", str(tmp_path / "o"), "--json")
    assert code == 2 and json.loads(out)["error"]["code"] == "CONFIGURATION_NOT_DECLARED"


@pytest.fixture
def both_rehearsals(tmp_path, clean_env):
    for name in PROXY_VARIABLES:
        clean_env.delenv(name, raising=False)
    clean_env.setenv("NO_PROXY", "127.0.0.1,localhost")
    runs = {}
    with FakeAnthropic() as fake:
        for configuration in ("plain", "verify"):
            first = len(fake.requests)
            record = agentic_live.run_live(
                model_id=MODEL_ID, api_key=FAKE_KEY, workload_dir=CHINOOK, case_ids=["D03", "D05"],
                repeats=1, out_dir=tmp_path / configuration, base_url=fake.url, configuration=configuration,
            )
            runs[configuration] = (fake.requests[first:], record, tmp_path / configuration)
        yield runs


def _system_text(body):
    system = body["system"]
    return system if isinstance(system, str) else "".join(b["text"] for b in system)


def test_both_configurations_send_the_same_explicit_reasoning_setting_and_the_1024_token_cap(both_rehearsals):
    sent = {}
    for configuration, (requests, _, _) in both_rehearsals.items():
        assert len(requests) == 4
        for request in requests:
            assert request["body"]["max_tokens"] == 1024
            assert request["body"]["thinking"] == {"type": "disabled"}
        sent[configuration] = {(r["body"]["max_tokens"], json.dumps(r["body"]["thinking"])) for r in requests}
    assert sent["plain"] == sent["verify"] and len(sent["plain"]) == 1
    # the Configurations differ by their prompt only
    plain, verify = (_system_text(both_rehearsals[c][0][0]["body"]) for c in ("plain", "verify"))
    assert plain == WORKLOAD.system_text("plain") and verify == WORKLOAD.system_text("verify")


def test_the_record_holds_the_reasoning_setting_and_the_output_cap_as_sent(both_rehearsals):
    for configuration, (_, record, out) in both_rehearsals.items():
        assert {k: v for k, v in record["reasoning"].items() if k != "note"} == {
            "setting": "disabled", "requested": "none", "sent": {"type": "disabled"}
        }
        assert record["output_cap"] == {"requested": 1024, "sent": 1024}
        assert record["configuration"] == configuration
        assert record["system_text"] == WORKLOAD.system_text(configuration)
        assert record["mode"] == "llm_live" and record["provider"] == "anthropic"
        assert record["model"] == MODEL_ID and record["served_models"] == ["claude-test-1-20261101"]
        assert json.loads((out / "run.json").read_text())["reasoning"] == record["reasoning"]


def test_the_record_names_the_cases_it_ran_and_the_chinook_hash_before_and_after(both_rehearsals):
    import hashlib

    expected = hashlib.sha256((CHINOOK / "data" / "Chinook_Sqlite.sqlite").read_bytes()).hexdigest()
    for _, record, _ in both_rehearsals.values():
        assert record["cases"] == [{"case_id": "D03", "repeat": 0}, {"case_id": "D05", "repeat": 0}]
        assert record["database_sha256"] == {"before": expected, "after": expected}


def test_the_record_reads_back_the_limits_and_names_what_cannot_be_enforced(both_rehearsals):
    for _, record, _ in both_rehearsals.values():
        limits = record["effective_limits"]
        assert limits["model_turns"] == 6 and limits["max_output_tokens"] == 1024
        assert set(limits["query_caps"]) == {"max_rows", "max_bytes", "max_seconds", "max_instructions"} or limits["query_caps"]
        notes = record["limit_notes"]
        assert "no limit on the number of tool calls" in notes["tool_calls"]
        assert notes["provider_calls"] == "6 model turns allow 7 provider calls"


def test_for_each_configuration_the_join_case_shows_model_tool_model_answer_and_the_record_reports_it(both_rehearsals):
    for _, record, out in both_rehearsals.values():
        assert record["tool_loop_observed"] is True
        episodes = json.loads((out / "projection.json").read_text())
        d03 = next(e for e in episodes if e["case_id"] == "D03")
        assert [s["kind"] for s in d03["steps"]] == agentic_live.EXPECTED_SEQUENCE


def test_every_model_call_records_why_it_stopped(both_rehearsals):
    for _, _, out in both_rehearsals.values():
        for episode in json.loads((out / "projection.json").read_text()):
            turns = [s for s in episode["steps"] if s["kind"] == "model_turn"]
            assert [t["stop_reason"] for t in turns] == ["tool_calls", "stop"]


def test_an_answer_cut_by_the_output_cap_is_told_apart_from_a_complete_one(tmp_path, clean_env):
    for name in PROXY_VARIABLES:
        clean_env.delenv(name, raising=False)
    clean_env.setenv("NO_PROXY", "127.0.0.1,localhost")
    with FakeAnthropic() as fake:
        fake.cut_answers = True
        agentic_live.run_live(
            model_id=MODEL_ID, api_key=FAKE_KEY, workload_dir=CHINOOK, case_ids=["D03"],
            repeats=1, out_dir=tmp_path / "out", base_url=fake.url,
        )
    (episode,) = json.loads((tmp_path / "out" / "projection.json").read_text())
    assert [s["stop_reason"] for s in episode["steps"] if s["kind"] == "model_turn"] == ["tool_calls", "max_tokens"]


def test_tokens_and_cost_the_log_does_not_give_are_null_never_zero_and_calls_and_latency_are_descriptive(both_rehearsals):
    for _, record, _ in both_rehearsals.values():
        for episode in record["episodes"]:
            assert episode["model_calls"] == 2
            assert isinstance(episode["latency_seconds"], float) and episode["latency_seconds"] >= 0
            assert episode["input_tokens"] == 240 and episode["output_tokens"] == 60  # as the endpoint reported
            assert episode["cost"] is None


def test_an_episode_with_no_usage_in_the_log_has_null_tokens_not_zero():
    class Sample:
        model_usage = {}
        total_time = 1.5
        events = []

    usage = agentic_live.usage_of(Sample())
    assert usage == {"model_calls": 0, "latency_seconds": 1.5, "input_tokens": None, "output_tokens": None, "cost": None}


# --- the reasoning setting must be stated by the request, or nothing is sent ---------------------------------------------


@pytest.mark.parametrize(
    ("model", "thinking"),
    [("anthropic/claude-sonnet-5", {"type": "disabled"}), ("anthropic/claude-sonnet-5-5", {"type": "between_tools"})],
)
def test_the_request_inspect_would_build_states_the_reasoning_setting(model, thinking):
    assert agentic_live.reasoning_in_request(agentic_live.live_model(model, FAKE_KEY)) == thinking


@pytest.mark.parametrize("model", ["anthropic/claude-sonnet-4-5", "anthropic/claude-opus-5-5"])
def test_a_model_whose_request_would_not_state_reasoning_is_refused_and_nothing_is_sent(
    tmp_path, clean_env, model
):
    from hypotrail.core.errors import HypotrailError

    for name in PROXY_VARIABLES:
        clean_env.delenv(name, raising=False)
    clean_env.setenv("NO_PROXY", "127.0.0.1,localhost")
    with FakeAnthropic() as fake, pytest.raises(HypotrailError) as caught:
        agentic_live.run_live(
            model_id=model, api_key=FAKE_KEY, workload_dir=CHINOOK, case_ids=["D03"],
            repeats=1, out_dir=tmp_path / "out", base_url=fake.url,
        )
    assert caught.value.code == "REASONING_NOT_EXPLICIT" and caught.value.exit_code == 2
    assert fake.requests == []
    assert not (tmp_path / "out").exists()
    assert FAKE_KEY not in str(caught.value)


def test_the_record_explains_between_tools_for_disabled_reasoning(both_rehearsals):
    for _, record, _ in both_rehearsals.values():
        assert "between_tools" in record["reasoning"]["note"]
        assert "no up-front thinking" in record["reasoning"]["note"]
