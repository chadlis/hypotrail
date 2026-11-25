"""Ticket #74: `run agent`, the command, its refusals, the key, the output and the order of its checks.

Inspect's mock model only: the patch is the test's own (`_run_agent_helpers.patch_model`) and no flag reaches it.
"""

import sys

import pytest
from _chinook_helpers import chinook_examples, database_of
from _run_agent_helpers import (
    FAKE_KEY,
    MODEL,
    TWO,
    agent,
    answering_with,
    error_of,
    fixture,
    live,
    live_args,
    ok,
    patch_model,
    read,
    refuse_provider,
    scripted,
    study_of,
    tree,
    tree_without_lock,
)
from _study_helpers import ROOT, init_study, run_cli
from test_study_lock import held_by_another_process

from hypotrail import cli
from hypotrail.core import live as core_live
from hypotrail.core.errors import (
    EXIT_CAPABILITY_UNAVAILABLE,
    EXIT_INFRASTRUCTURE,
    EXIT_INTEGRITY_REFUSED,
    EXIT_INVALID_INPUT,
    EXIT_LOCK_OR_CONFLICT,
)


def agent_parser():
    parser = cli.build_parser()
    run = parser._subparsers._group_actions[0].choices["run"]
    return run._subparsers._group_actions[0].choices["agent"]


# --- The command ------------------------------------------------------------------------------------------------------------------


def test_run_agent_is_a_command_with_its_flags_and_refuses_the_other_track(tmp_path):
    parser = agent_parser()
    flags = {option for action in parser._actions for option in action.option_strings}
    assert flags == {
        "-h", "--help", "--study", "--mode", "--config", "--request-id", "--partition", "--repeats", "--model", "--cases", "--retry-of",
        "--examples-dir", "--read-sequence", "--json",
    }  # and no flag that patches the model
    required = {action.dest for action in parser._actions if action.required}
    assert required == {"study", "mode", "config", "request_id"}
    assert next(a for a in parser._actions if a.dest == "mode").choices == ["scripted_fixture", "llm_live"]
    assert next(a for a in parser._actions if a.dest == "cases").option_strings == ["--cases"] and next(a for a in parser._actions if a.dest == "cases").nargs is None
    study = study_of(tmp_path)
    before = tree(study)
    code, out, err = run_cli("run", "agent", "--study", study, "--mode", "scripted_fixture", "--config", "plain", "--json")
    assert code == EXIT_INVALID_INPUT and '"INVALID_ARGUMENTS"' in out  # --request-id is required
    code, out, _ = run_cli("run", "agent", "--study", study, "--mode", "other", "--config", "plain", "--request-id", "r", "--json")
    assert code == EXIT_INVALID_INPUT and '"INVALID_ARGUMENTS"' in out
    assert tree(study) == before
    bike, _ = init_study(tmp_path, name="bike-study")
    result = fixture(bike, "plain", "r")
    code, error = error_of(result)
    assert (code, error["code"]) == (EXIT_INVALID_INPUT, "UNSUPPORTED_CAPABILITY")
    assert error["details"]["study_domain"] == "regression"


@pytest.mark.parametrize("mode", ["scripted_fixture", "llm_live"])
def test_config_is_required_in_both_modes(tmp_path, mode):
    study = study_of(tmp_path)
    before = tree(study)
    code, out, _ = run_cli("run", "agent", "--study", study, "--mode", mode, "--request-id", "r", "--json")
    assert code == EXIT_INVALID_INPUT and '"INVALID_ARGUMENTS"' in out
    assert tree(study) == before


def test_llm_live_refuses_what_the_workload_or_the_bound_does_not_allow_before_the_key_is_read_and_before_inspect_is_imported(tmp_path, monkeypatch):
    study = study_of(tmp_path)
    patch_model(monkeypatch, key=None)  # no key: reading it would be a refusal of exit 5, not of exit 2
    refuse_provider(monkeypatch)
    monkeypatch.setitem(sys.modules, "inspect_ai", None)  # Inspect cannot be imported
    before = tree(study)
    base = dict(config="plain", request_id="r", cases=TWO, repeats=1, partition="dev", model=MODEL)
    cases = [
        ("an undeclared Configuration", dict(base, config="nonesuch"), "CONFIGURATION_NOT_DECLARED"),
        ("a Partition the Track does not run", dict(base, partition="other"), "PARTITION_NOT_ALLOWED"),
        ("a Partition the Workload does not declare", dict(base, partition="train"), "PARTITION_NOT_ALLOWED"),
        ("no Repeat", dict(base, repeats=0), "REPEATS_OUT_OF_BOUNDS"),
        ("four Repeats", dict(base, repeats=4), "REPEATS_OUT_OF_BOUNDS"),
        ("a model that is not anthropic/<model>", dict(base, model="openai/gpt-x"), "MODEL_REQUIRED"),
        ("a bare model name", dict(base, model="claude-test-1"), "MODEL_REQUIRED"),
        ("a Case of the other Partition", dict(base, cases=["D03", "E01"]), "CASE_NOT_IN_PARTITION"),
        ("an unknown Case", dict(base, cases=["Z99"]), "CASE_NOT_IN_PARTITION"),
        ("a repeated Case", dict(base, cases=["D03", "D03"]), "CASE_REPEATED"),
    ]
    for label, options, expected in cases:
        code, error = error_of(agent(study, *live_args(**options)))
        assert (code, error["code"]) == (EXIT_INVALID_INPUT, expected), label
        assert FAKE_KEY not in str(error)
    for missing, expected in (("--partition", "PARTITION_REQUIRED"), ("--repeats", "REPEATS_REQUIRED"), ("--model", "MODEL_REQUIRED")):
        args = live_args("plain", "r")
        at = args.index(missing)
        del args[at : at + 2]
        code, error = error_of(agent(study, *args))
        assert (code, error["code"]) == (EXIT_INVALID_INPUT, expected), missing
    assert tree(study) == before  # nothing was written, not even the writer's lock file


# --- The key ----------------------------------------------------------------------------------------------------------------------


def test_without_the_key_or_with_a_variable_that_would_override_it_llm_live_exits_5_sends_nothing_and_writes_no_attempt_and_scripted_fixture_never_reads_it(
    tmp_path, monkeypatch, network_guard
):
    study = study_of(tmp_path)
    with pytest.MonkeyPatch.context() as sealed:
        patch_model(sealed, key=None)
        refuse_provider(sealed)  # a model, a provider call or an Episode would raise
        for label, token in (("no key", None), ("a bearer token that would override the key", "token")):
            if token:
                sealed.setenv("HYPOTRAIL_ANTHROPIC_API_KEY", FAKE_KEY)
                sealed.setenv("ANTHROPIC_AUTH_TOKEN", token)
            code, error = error_of(live(study, "plain", "r"))
            assert (code, error["code"], error["stage"]) == (EXIT_CAPABILITY_UNAVAILABLE, "LIVE_UNAVAILABLE", "capability"), label
            assert error["details"]["blocker"]
            assert not list((study / "attempts").glob("*")), label
    patch_model(monkeypatch, key=None)

    def read_key_is_never_called(environ):
        raise AssertionError("scripted_fixture read the key")

    monkeypatch.setattr(core_live, "read_api_key", read_key_is_never_called)
    attempt = ok(fixture(study, "plain", "fixture-no-key"))
    assert attempt["mode"] == "scripted_fixture" and attempt["technical_status"] == "completed"
    assert network_guard.attempts == []


# --- Output and exit codes --------------------------------------------------------------------------------------------------------


def test_with_json_stdout_holds_exactly_one_object_and_the_diagnostics_go_to_stderr(tmp_path, monkeypatch):
    import json

    study = study_of(tmp_path)
    patch_model(monkeypatch)
    code, out, err = run_cli("run", "agent", "--study", study, *live_args("plain", "j1"), "--json")
    assert code == 0
    payload = json.loads(out)  # the whole of stdout is one object
    assert set(payload) == {"ok", "replayed", "attempt", "warnings"}
    assert payload["ok"] is True and payload["replayed"] is False and payload["warnings"] == []
    assert payload["attempt"]["technical_status"] == "completed"
    code, out, err = run_cli("run", "agent", "--study", study, *live_args("plain", "j2", repeats=9), "--json")
    payload = json.loads(out)
    assert payload["ok"] is False and set(payload["error"]) == {"code", "message", "stage", "details"}
    assert payload["error"]["code"] == "REPEATS_OUT_OF_BOUNDS" and "REPEATS_OUT_OF_BOUNDS" in err  # the human line is on stderr
    assert FAKE_KEY not in out + err


def test_the_exit_codes_of_run_agent_are_those_of_section_8(tmp_path, monkeypatch):
    # 0: a recorded Attempt, whatever its Episodes' outcomes (here one Episode failed)
    study = study_of(tmp_path, name="s0")
    patch_model(monkeypatch, scripted(error_on=("D03", 1)))
    code, payload, _ = live(study, "plain", "e0")
    assert code == 0 and payload["attempt"]["item_counts"] == {"produced": 1, "failed": 1, "missing": 0}
    # 2: invalid input
    code, error = error_of(live(study, "plain", "e2", repeats=9))
    assert code == EXIT_INVALID_INPUT
    # 3: integrity or Protocol refused (the data no longer matches its lock)
    examples = chinook_examples(tmp_path)
    changed = study_of(tmp_path, examples=examples, name="s3")
    database_of(examples).write_bytes(database_of(examples).read_bytes() + b"x")
    code, error = error_of(live(changed, "plain", "e3", "--examples-dir", examples))
    assert (code, error["code"]) == (EXIT_INTEGRITY_REFUSED, "DATA_INTEGRITY")
    # 4: infrastructure (the key found in the execution's output)
    leaky = study_of(tmp_path, name="s4")
    patch_model(monkeypatch, answering_with(FAKE_KEY))
    code, error = error_of(live(leaky, "plain", "e4"))
    assert (code, error["code"]) == (EXIT_INFRASTRUCTURE, "SECRET_IN_OUTPUT")
    # 5: a capability that is not available (no key)
    patch_model(monkeypatch, key=None)
    code, error = error_of(live(study, "plain", "e5"))
    assert (code, error["code"]) == (EXIT_CAPABILITY_UNAVAILABLE, "LIVE_UNAVAILABLE")
    # 6: a lock held, and a request_id that names another request
    patch_model(monkeypatch)
    with held_by_another_process(study):
        code, error = error_of(live(study, "plain", "e6"))
        assert (code, error["code"]) == (EXIT_LOCK_OR_CONFLICT, "STUDY_LOCKED")
    code, error = error_of(live(study, "plain", "e0", cases=["D03"]))
    assert (code, error["code"]) == (EXIT_LOCK_OR_CONFLICT, "REQUEST_CONFLICT")


# --- The other Mode's flags (D-012 on chadlis/hypotrail#75 item 13) ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("flag, value", [("--partition", "dev"), ("--repeats", "1"), ("--model", MODEL), ("--cases", "D03")])
def test_a_flag_of_the_other_mode_is_refused_with_unsupported_capability(tmp_path, monkeypatch, flag, value):
    study = study_of(tmp_path)
    refuse_provider(monkeypatch)
    before = tree(study)
    code, error = error_of(fixture(study, "plain", "r", flag, value))
    assert (code, error["code"]) == (EXIT_INVALID_INPUT, "UNSUPPORTED_CAPABILITY")
    assert error["details"]["flag"] == flag and error["details"]["mode"] == "scripted_fixture"
    assert tree(study) == before


# --- The order of the checks (Tightened K, D-012 on chadlis/hypotrail#75 item 10) -------------------------------------------------------------------------


def test_the_checks_run_in_the_order_of_the_ticket_and_each_pair_of_adjacent_refusals_ends_at_the_earlier(tmp_path, monkeypatch):
    from _chinook_helpers import init_chinook
    from _exposure_helpers import edit_chinook_references

    examples = chinook_examples(tmp_path)
    study, _ = init_chinook(tmp_path, examples=examples)
    more = ["--examples-dir", examples]
    patch_model(monkeypatch)
    first = ok(live(study, "plain", "r", *more))

    def refusal(result):
        code, error = error_of(result)
        return code, error["code"]

    # flag checks (2) come before the writer lock (6)
    with held_by_another_process(study):
        assert refusal(live(study, "plain", "x", *more, repeats=9)) == (EXIT_INVALID_INPUT, "REPEATS_OUT_OF_BOUNDS")
        # the writer lock comes before the request identity (a conflict is 6, too, but its own code)
        assert refusal(live(study, "plain", "r", *more, cases=["D03"])) == (EXIT_LOCK_OR_CONFLICT, "STUDY_LOCKED")
    # the request identity comes before the data verification
    database = database_of(examples)
    database.write_bytes(database.read_bytes() + b"x")  # the data no longer matches its lock
    assert refusal(live(study, "plain", "r", *more, cases=["D03"])) == (EXIT_LOCK_OR_CONFLICT, "REQUEST_CONFLICT")
    # the data verification comes before the read-back of the Study's artifacts
    memberships = study / "artifacts" / "memberships.csv"
    original = memberships.read_bytes()
    memberships.write_bytes(b"case_id,partition\n")
    assert refusal(live(study, "plain", "new", *more)) == (EXIT_INTEGRITY_REFUSED, "DATA_INTEGRITY")
    database.write_bytes(database.read_bytes()[:-1])  # the data is the locked one again
    # the read-back of the Study's artifacts comes before the Protocol check (the References changed since init)
    corrected = edit_chinook_references(tmp_path, lambda records: records["D01"].update(rows=[[0]]), name="corrected")
    assert refusal(live(study, "plain", "new", "--examples-dir", corrected)) == (EXIT_INTEGRITY_REFUSED, "ARTIFACT_INTEGRITY")
    memberships.write_bytes(original)
    # the Protocol check comes before Inspect being available, which comes before the key
    inspect_ai = sys.modules["inspect_ai"]
    monkeypatch.setitem(sys.modules, "inspect_ai", None)
    assert refusal(live(study, "plain", "new", "--examples-dir", corrected)) == (EXIT_INTEGRITY_REFUSED, "PROTOCOL_CHANGED")
    patch_model(monkeypatch, key=None)
    assert refusal(live(study, "plain", "new", *more)) == (EXIT_CAPABILITY_UNAVAILABLE, "INSPECT_UNAVAILABLE")
    sys.modules["inspect_ai"] = inspect_ai
    assert refusal(live(study, "plain", "new", *more)) == (EXIT_CAPABILITY_UNAVAILABLE, "LIVE_UNAVAILABLE")
    # a replay is answered at the request identity: with no key and with Inspect that cannot be imported
    monkeypatch.setitem(sys.modules, "inspect_ai", None)
    refuse_provider(monkeypatch)
    before = tree(study)
    code, payload, err = live(study, "plain", "r", *more)
    assert code == 0 and payload["replayed"] is True and payload["attempt"] == first
    assert tree(study) == before



def test_the_generic_run_agent_code_names_no_workload_in_its_message_or_its_help():
    """R1-06, ADR 0002: the Track's code stays generic; a Workload's name is declared data, never a literal of the Track."""
    from hypotrail.agentic.declaration import database_changed

    assert "chinook" not in database_changed("a", "b", stage="run").message.lower()
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if getattr(a, "choices", None) and "run" in a.choices)
    run_parser = sub.choices["run"]
    agent = next(a for a in run_parser._actions if getattr(a, "choices", None) and "agent" in a.choices).choices["agent"]
    config = next(a for a in agent._actions if "--config" in a.option_strings)
    assert "chinook" not in config.help.lower()


def test_the_generic_run_agent_module_docstring_names_no_workload():
    """R2-05, ADR 0002: the module that documents the order of `run agent` for any Workload does not name Chinook either."""
    from hypotrail.agentic import run

    assert "chinook" not in run.__doc__.lower()


# --- The first paid live call of #80 ----------------------------------------------------------------------------------------------


def test_the_exact_live_command_of_slice_80_from_the_repository_root_with_the_provider_patched_exits_0_with_a_completed_attempt_of_2_episodes(
    tmp_path, monkeypatch
):
    """The command of the first paid live call (#80), argument for argument, from the repository root: nothing reaches a provider."""
    import json

    monkeypatch.chdir(ROOT)
    study = study_of(tmp_path, name="live-check")
    patch_model(monkeypatch)  # the fake key in HYPOTRAIL_ANTHROPIC_API_KEY, and `prepared_model` patched
    code, out, err = run_cli(
        *("run", "agent", "--study", study, "--mode", "llm_live", "--config", "plain", "--partition", "dev"),
        *("--cases", "D03", "--cases", "D05", "--repeats", "1", "--model", "anthropic/claude-sonnet-5-5"),
        *("--request-id", "live-check-1", "--json"),
    )
    assert code == 0, (out, err)
    payload = json.loads(out)
    attempt = payload["attempt"]
    assert payload["ok"] is True and attempt["mode"] == "llm_live" and attempt["technical_status"] == "completed"
    record = read(study, attempt, "run.json")
    assert [(e["case_id"], e["repeat"]) for e in record["episodes"]] == [("D03", 0), ("D05", 0)]
    assert FAKE_KEY not in out + err
