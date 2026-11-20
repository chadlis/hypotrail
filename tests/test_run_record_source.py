"""#62: a `run.json` says what the execution's own Inspect log says wherever the log holds it.

Each test builds its log offline with Inspect's mock model and edits it through the public log API (ADR 0001);
nothing reaches a model or the network.
"""

import platform
import types

import pytest
from inspect_ai.log import read_eval_log
from inspect_ai.model import ModelCall

from _record_helpers import FAKE_KEY, live_record, make_log, resummary

from hypotrail.agentic import fixture
from hypotrail.agentic import live as agentic_live
from hypotrail.agentic import limits as limits_module
from hypotrail.core.errors import HypotrailError
from _agent_helpers import CHINOOK


def _installed_inspect_is(monkeypatch, version):
    stub = types.SimpleNamespace(version=lambda name: version)
    for module in (agentic_live, fixture):
        monkeypatch.setattr(module, "metadata", stub, raising=False)


def test_engine_version_is_the_one_the_log_records_in_a_live_record_a_re_summary_and_the_scripted_record(tmp_path, monkeypatch):
    """AC1 (Tightened A): the installed Inspect differs from the log's, in the three kinds of record."""
    _installed_inspect_is(monkeypatch, "9.9.9")
    out, location = make_log(tmp_path, "kept", edit=lambda log: log.eval.packages.update({"inspect_ai": "0.3.100"}))
    live = live_record(tmp_path, monkeypatch, location)
    again = resummary(out, location)
    scripted = fixture.run_fixture(workload_dir=CHINOOK, out_dir=tmp_path / "scripted", configuration="plain")
    scripted_log = read_eval_log(str(tmp_path / "scripted" / scripted["inspect_log"]), header_only=True)
    assert scripted_log.eval.packages["inspect_ai"] != "9.9.9"
    assert live["engine"] == {"name": "inspect-ai", "version": "0.3.100"}
    assert again["engine"] == {"name": "inspect-ai", "version": "0.3.100"}
    assert scripted["engine"] == {"name": "inspect-ai", "version": scripted_log.eval.packages["inspect_ai"]}


def test_model_provider_and_expected_episodes_are_the_logs_whatever_the_caller_says(tmp_path, monkeypatch):
    """AC2 (Tightened B): another model, other Cases, another number of Repeats change nothing; a named Episode the log lacks is missing."""

    def plan(log):
        log.eval.model = "anthropic/claude-log-1"
        log.eval.dataset.sample_ids = ["D03", "D05"]
        log.eval.config.epochs = 2

    out, location = make_log(tmp_path, "kept", edit=plan)
    expected_cases = [{"case_id": c, "repeat": r} for c in ("D03", "D05") for r in (0, 1)]
    disagreeing = {"model_id": "anthropic/other-model", "case_ids": ("D07",), "repeats": 5}
    live = live_record(tmp_path, monkeypatch, location, **disagreeing)
    again = resummary(out, location, **disagreeing)
    for record in (live, again):
        assert (record["model"], record["provider"]) == ("anthropic/claude-log-1", "anthropic")
        assert record["cases"] == expected_cases
        assert [(e["case_id"], e["repeat"], e["status"]) for e in record["episodes"]] == [
            ("D03", 0, "produced"), ("D03", 1, "missing"), ("D05", 0, "missing"), ("D05", 1, "missing"),
        ]


def test_the_provider_call_note_is_built_from_the_effective_turn_limit_of_the_log(tmp_path, monkeypatch):
    """AC3 (Tightened C): a log made under a turn limit other than today's default."""
    assert limits_module.EpisodeLimits().model_turns != 3
    out, location = make_log(tmp_path, "kept", limits=limits_module.EpisodeLimits(model_turns=3))
    again = resummary(out, location)
    live = live_record(tmp_path, monkeypatch, location)
    for record in (again, live):
        assert record["effective_limits"]["model_turns"] == 3
        assert record["limit_notes"]["provider_calls"] == "3 model turns allow 4 provider calls"
        assert record["limit_notes"]["tool_calls"] == limits_module.NOT_ENFORCEABLE["tool_calls"]  # D-012 item 8: top-level
        assert "tool_calls" not in (record["summarised_by"] or {})


def test_what_no_log_holds_describes_the_execution_itself_and_in_a_re_summary_sits_under_summarised_by(tmp_path, monkeypatch):
    """AC4 + D-012 items 4 and 7: python, hardware, machine; the database hashes the caller gives."""
    monkeypatch.setattr(platform, "python_version", lambda: "3.99.1")
    monkeypatch.setattr(platform, "platform", lambda *a, **k: "SummariserOS-1")
    monkeypatch.setattr(platform, "machine", lambda: "summ64")
    _installed_inspect_is(monkeypatch, "9.9.9")
    out, location = make_log(tmp_path, "kept")
    hashes = {"before": "a" * 64, "after": "a" * 64}
    again = resummary(out, location, database_sha256=hashes)
    live = live_record(tmp_path, monkeypatch, location)
    assert again["request_source"] == "kept_log"
    assert (again["python"], again["hardware"], again["machine"], again["database_sha256"]) == (None, None, None, None)
    assert (live["request_source"], live["python"], live["hardware"], live["machine"]) == ("this_attempt", "3.99.1", "SummariserOS-1", "summ64")
    assert live["summarised_by"] is None and live["database_sha256"] is not None
    assert again["summarised_by"] == {
        "python": "3.99.1", "hardware": "SummariserOS-1", "machine": "summ64", "inspect_version": "9.9.9",
        "reasoning_note": agentic_live.REASONING_NOTE, "database_sha256_given_by_caller": hashes,
    }


def test_reasoning_setting_is_the_logs_and_the_note_moves_under_summarised_by_in_a_re_summary(tmp_path, monkeypatch):
    """AC5 + D-012 item 5: requested and sent are read from the log; setting is the log's value verbatim, null when it has none."""

    def effort_and_thinking(log):
        log.plan.config.reasoning_effort = "low"
        log.eval.model_generate_config.reasoning_effort = None
        event = next(e for s in log.samples for e in s.events if e.event == "model")
        event.call = ModelCall(request={"max_tokens": 5, "thinking": {"type": "enabled"}}, response={})

    none_out, none_location = make_log(tmp_path, "none")
    out, location = make_log(tmp_path, "low", edit=effort_and_thinking)
    again = resummary(out, location)
    live = live_record(tmp_path, monkeypatch, location)
    for record in (again, live):
        assert (record["reasoning"]["setting"], record["reasoning"]["requested"]) == ("low", "low")
        assert record["reasoning"]["sent"] == {"type": "enabled"}
    assert live["reasoning"]["note"] == agentic_live.REASONING_NOTE
    assert again["reasoning"]["note"] is None and again["summarised_by"]["reasoning_note"] == agentic_live.REASONING_NOTE
    assert resummary(none_out, none_location)["reasoning"]["setting"] is None


def test_a_re_summary_of_a_kept_log_gives_the_logs_values_whatever_the_caller_and_the_installed_inspect_say(tmp_path, kept_all_token_log, monkeypatch):
    """AC6 (Tightened E2): the kept live-l12-plain log, caller arguments that disagree with it, another installed Inspect."""
    _installed_inspect_is(monkeypatch, "9.9.9")
    out = tmp_path
    record = resummary(
        out, kept_all_token_log, model_id="anthropic/other-model", case_ids=("D07", "D08", "E11"), repeats=3,
    )
    assert record["model"] == "anthropic/claude-sonnet-5-5"
    assert record["engine"]["version"] == "0.3.287"
    assert record["cases"] == [{"case_id": "D03", "repeat": 0}, {"case_id": "D05", "repeat": 0}]
    assert record["limit_notes"]["provider_calls"] == "6 model turns allow 7 provider calls"
    assert record["summarised_by"]["inspect_version"] == "9.9.9"


def test_a_re_summary_calls_no_model_and_no_tool_and_still_scans_its_output_for_the_key(tmp_path, monkeypatch, network_guard):
    """AC7: the log is read, nothing is run; the output directory is scanned for the key."""
    out, location = make_log(tmp_path, "kept")

    def refuse(*args, **kwargs):
        raise AssertionError("a re-summary ran a model or a tool")

    monkeypatch.setattr(agentic_live.runner, "run_episodes", refuse)
    monkeypatch.setattr(agentic_live, "live_model", refuse)
    monkeypatch.setattr(agentic_live, "get_model", refuse)
    monkeypatch.setattr(agentic_live, "reasoning_in_request", refuse)
    assert resummary(out, location)["mode"] == "llm_live"
    assert network_guard.attempts == []
    (out / "stray.txt").write_text(FAKE_KEY)
    with pytest.raises(HypotrailError) as caught:
        resummary(out, location)
    assert caught.value.code == "SECRET_IN_OUTPUT" and caught.value.details["files"] == ["stray.txt"]


@pytest.mark.parametrize("absent", ["sample_ids", "epochs", "both"])
def test_a_plan_the_log_does_not_hold_gives_null_cases_never_the_callers(tmp_path, absent):
    """D-012 item 6: sample_ids or epochs absent from the log, the field is null."""

    def drop(log):
        if absent in ("sample_ids", "both"):
            log.eval.dataset.sample_ids = None
        if absent in ("epochs", "both"):
            log.eval.config.epochs = None

    out, location = make_log(tmp_path, "kept", edit=drop)
    record = resummary(out, location, case_ids=("D03", "D05"), repeats=2)
    assert record["cases"] is None
