"""The Episode cost limit, its price list and one tool call per turn on `run agent` (#234, after D-146 on chadlis/hypotrail#75).

Inspect's mock model is patched in through the one seam of `_run_agent_helpers`, and priced by the price list each test
writes (`_cost_limit_helpers.priceable`). No provider is called.
"""

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from inspect_ai.model import ModelCost, ModelOutput, ModelUsage
from inspect_ai.tool import ToolCall

from _agent_helpers import WORKLOAD
from _chinook_helpers import references_id
from _cost_ceiling import FRAMING_ALLOWANCE_TOKENS, ceiling, episode_bound, post_run_faults
from _cost_limit_helpers import MOCK, SOURCE, TEST_MODEL, price_list, priceable, write_price_list
from _run_agent_helpers import (
    ALL_CASES,
    FAKE_KEY,
    AnsweringModel,
    error_of,
    live,
    ok,
    patch_model,
    read,
    scripted,
    study_of,
    observation_set_id_of,
    observations_of,
    tree,
)
from _study_helpers import run_json

from hypotrail.agentic import live as agentic_live
from hypotrail.agentic import runner
from hypotrail.agentic.limits import EpisodeLimits
from hypotrail.core import live as core_live
from hypotrail.core import requests
from hypotrail.core.chinook_contract import CRITERIA
from hypotrail.core.errors import EXIT_INVALID_INPUT

ROOT = Path(__file__).resolve().parent.parent
LIMIT = 0.05
# USD 0.021 per model call at the helpers' prices (10,000 input tokens at 2, 100 output tokens at 10, per million):
# USD 0.05 is crossed on the third call, before the sixth model turn and before the output-token budget
COSTLY = ModelUsage(input_tokens=10_000, output_tokens=100, total_tokens=10_100)


@pytest.fixture(autouse=True)
def priced():
    with priceable():
        yield


def costly():
    """The helpers' scripted model, calling a tool on every turn at USD 0.021 a call."""
    inner = AnsweringModel(ALL_CASES, always_call_tool=True)

    def call(input, tools, tool_choice, config):
        output = inner(input, tools, tool_choice, config)
        output.usage = COSTLY
        return output

    call.calls = inner.calls
    return call


def cost_flags(path, limit=LIMIT):
    return ["--episode-cost-limit-usd", str(limit), "--price-list", path]


def assess(study, attempt):
    code, payload, err = run_json(
        "assess", "--study", study, "--observations", observation_set_id_of(study, attempt), "--scorer", "chinook_contract_v1", "--references", references_id(study)
    )
    assert code == 0, (payload, err)
    return payload["assessment"]


def criteria_rows(study, assessment):
    """{(case_id, repeat, criterion): (state, score, reason)} of an Assessment's per-item file."""
    rows = [line.split(",") for line in (Path(study) / assessment["per_item_ref"]["path"]).read_text().splitlines()[1:]]
    return {(r[0], int(r[1]), r[5]): (r[6], r[7], r[8]) for r in rows}


# --- an Episode stopped by the cost limit is failed / cost_limit, every Criterion scored false ---------------------


def test_a_mock_episode_stopped_at_the_cost_limit_is_failed_cost_limit_its_criteria_scored_false_and_the_comparison_has_a_delta(
    tmp_path, monkeypatch
):
    study = study_of(tmp_path)
    prices = write_price_list(tmp_path)
    patch_model(monkeypatch, costly())
    sides = {name: ok(live(study, name, name, *cost_flags(prices), cases=["D03"])) for name in ("plain", "verify")}
    for name, attempt in sides.items():
        (observation,) = observations_of(study, attempt)
        assert (observation["status"], observation["reason"]) == ("failed", "cost_limit"), name
        (episode,) = read(study, attempt, "run.json")["episodes"]
        assert episode["stopped_by_limit"] == {"type": "cost", "limit": LIMIT}, name
        assert episode["cost"] is not None and episode["cost"] >= LIMIT, name  # the Episode's cost is recorded
    assessments = {name: assess(study, attempt) for name, attempt in sides.items()}
    rows = criteria_rows(study, assessments["plain"])
    assert rows[("D03", 0, "format_valid")] == ("scored", "false", "cost_limit")
    assert rows[("D03", 0, "exact_table")] == ("scored", "false", "cost_limit")
    assert rows[("D03", 0, "evidence_link_valid")] == ("scored", "false", "cost_limit")
    assert rows[("D03", 0, "contract_success")] == ("scored", "false", "cost_limit")
    assert set(CRITERIA) == {"format_valid", "exact_table", "evidence_link_valid", "contract_success"}
    code, payload, err = run_json(
        "compare", "--study", study, "--control", assessments["plain"]["assessment_id"], "--candidate", assessments["verify"]["assessment_id"]
    )
    assert code == 0, (payload, err)
    assert payload["comparison"]["delta"]["value"] is not None


# --- each flag without the other, and either flag with scripted_fixture, is refused with exit 2 ----------------------

DRIVER = """
import runpy, sys
sys.modules["inspect_ai"] = None  # an import of Inspect would fail
sys.argv = ["hypotrail"] + sys.argv[1:]
try:
    runpy.run_module("hypotrail", run_name="__main__", alter_sys=True)
finally:
    print("INSPECT_IMPORTED" if sys.modules.get("inspect_ai") is not None else "", file=sys.stderr)
"""


def run_process(*args):
    env = {k: v for k, v in os.environ.items() if k not in (core_live.KEY_VARIABLE, "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")}
    env["PYTHONPATH"] = str(ROOT / "src")
    done = subprocess.run([sys.executable, "-c", DRIVER, *map(str, args)], cwd=ROOT, env=env, capture_output=True, text=True)
    return done.returncode, json.loads(done.stdout), done.stderr


@pytest.mark.parametrize(
    ("label", "mode", "flags", "expected"),
    [
        ("the cost limit alone", "llm_live", ["--episode-cost-limit-usd", "0.05"], "PRICE_LIST_REQUIRED"),
        ("the price list alone", "llm_live", ["--price-list", "PRICES"], "COST_LIMIT_REQUIRED"),
        ("the cost limit with scripted_fixture", "scripted_fixture", ["--episode-cost-limit-usd", "0.05"], "UNSUPPORTED_CAPABILITY"),
        ("the price list with scripted_fixture", "scripted_fixture", ["--price-list", "PRICES"], "UNSUPPORTED_CAPABILITY"),
    ],
)
def test_each_cost_flag_without_the_other_and_either_with_scripted_fixture_is_refused_with_exit_2_by_the_cli_process(tmp_path, label, mode, flags, expected):
    study = study_of(tmp_path)
    prices = write_price_list(tmp_path)
    flags = [str(prices) if f == "PRICES" else f for f in flags]
    live_only = ["--partition", "dev", "--repeats", "1", "--model", TEST_MODEL, "--cases", "D03"] if mode == "llm_live" else []
    before = tree(study)
    code, payload, err = run_process("run", "agent", "--study", study, "--mode", mode, "--config", "plain", "--request-id", "r", *live_only, *flags, "--json")
    assert (code, payload["error"]["code"]) == (EXIT_INVALID_INPUT, expected), (label, payload, err)
    assert "INSPECT_IMPORTED" not in err, label
    assert tree(study) == before, label  # nothing written, not even the writer's lock file


# --- a model the price list does not price, and a price list with no source, are refused before any call ---------


@pytest.mark.parametrize(
    ("label", "content", "expected"),
    [
        ("a price list that omits the requested model", price_list([MOCK]), "MODEL_NOT_PRICED"),
        ("a price list with no source", price_list(source=None), "PRICE_LIST_INVALID"),
    ],
)
def test_a_price_list_that_omits_the_model_or_has_no_source_is_refused_with_exit_2_and_the_mock_is_never_called(tmp_path, monkeypatch, label, content, expected):
    study = study_of(tmp_path)
    script = patch_model(monkeypatch, scripted())
    code, error = error_of(live(study, "plain", "r", *cost_flags(write_price_list(tmp_path, content))))
    assert (code, error["code"]) == (EXIT_INVALID_INPUT, expected), label
    assert script.calls == [], label
    assert not (study / "attempts").exists() or not list((study / "attempts").iterdir()), label


def test_inspect_is_given_the_models_only_and_run_json_records_the_content_its_sha256_the_url_and_the_date(tmp_path, monkeypatch):
    study = study_of(tmp_path)
    prices = write_price_list(tmp_path)
    patch_model(monkeypatch)
    given = []
    real_eval = runner.eval

    def spying_eval(*args, **kwargs):
        given.append(kwargs.get("model_cost_config"))
        return real_eval(*args, **kwargs)

    monkeypatch.setattr(runner, "eval", spying_eval)
    attempt = ok(live(study, "plain", "priced", *cost_flags(prices), cases=["D03"]))
    content = json.loads(prices.read_bytes())
    assert given == [{name: ModelCost(**entry) for name, entry in content["models"].items()}]
    recorded = read(study, attempt, "run.json")["price_list"]
    assert recorded["content"] == content
    assert recorded["sha256"] == hashlib.sha256(prices.read_bytes()).hexdigest()
    assert recorded["url"] == SOURCE["url"]
    assert recorded["read_on"] == SOURCE["read_on"]


# --- the two new limits read back from the log equal the request --------------------------------------------------


def test_the_cost_limit_and_parallel_tool_calls_read_back_from_the_log_equal_the_request_with_the_flags_and_without(tmp_path, monkeypatch):
    study = study_of(tmp_path)
    prices = write_price_list(tmp_path)
    patch_model(monkeypatch)
    records = {
        "with the flags": read(study, ok(live(study, "plain", "with", *cost_flags(prices), cases=["D03"])), "run.json"),
        "without": read(study, ok(live(study, "plain", "without", cases=["D03"])), "run.json"),
    }
    assert records["with the flags"]["requested_limits"]["cost_limit_usd"] == LIMIT
    assert records["with the flags"]["effective_limits"]["cost_limit_usd"] == LIMIT
    assert records["with the flags"]["effective_limits"]["parallel_tool_calls"] == records["with the flags"]["requested_limits"]["parallel_tool_calls"] is False
    assert records["without"]["effective_limits"]["cost_limit_usd"] == records["without"]["requested_limits"]["cost_limit_usd"] is None
    assert records["without"]["effective_limits"]["parallel_tool_calls"] == records["without"]["requested_limits"]["parallel_tool_calls"] is False


# --- a kept log re-summarises with the new keys null, and an earlier request still replays -----------------------

KEPT_LOGS = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "docs" / "handbook" / "traces").rglob("*.eval"))


@pytest.mark.parametrize("kept", KEPT_LOGS)
def test_a_kept_log_re_summarises_with_the_cost_limit_parallel_tool_calls_and_price_list_null(tmp_path, kept):
    out = tmp_path / "out"
    (out / "inspect").mkdir(parents=True)
    location = shutil.copy(ROOT / kept, out / "inspect")
    record = agentic_live.summarize(location=str(location), out_dir=out, api_key=FAKE_KEY)
    for side in ("requested_limits", "effective_limits"):
        assert (record[side]["cost_limit_usd"], record[side]["parallel_tool_calls"]) == (None, None), side
    assert record["price_list"] is None


def test_a_request_id_recorded_without_the_two_identity_elements_still_replays(tmp_path, monkeypatch):
    study = study_of(tmp_path)
    patch_model(monkeypatch)
    first = ok(live(study, "plain", "earlier", cases=["D03"]))
    assert not {"cost_limit_usd", "price_list_sha256"} & set(first["effective_config"])
    assert {"cost_limit_usd", "price_list_sha256"} <= set(requests.IDENTITY_KEYS)
    code, payload, err = live(study, "plain", "earlier", cases=["D03"])
    assert code == 0 and payload["replayed"] is True and payload["attempt"] == first, (payload, err)


def test_both_flags_enter_the_request_identity(tmp_path, monkeypatch):
    study = study_of(tmp_path)
    prices = write_price_list(tmp_path)
    patch_model(monkeypatch)
    attempt = ok(live(study, "plain", "r", *cost_flags(prices), cases=["D03"]))
    config = attempt["effective_config"]
    assert (config["cost_limit_usd"], config["price_list_sha256"]) == (LIMIT, hashlib.sha256(prices.read_bytes()).hexdigest())
    for label, flags, differs in (
        ("another cost limit", cost_flags(prices, 0.07), ["cost_limit_usd"]),
        ("another price list", cost_flags(write_price_list(tmp_path, price_list(prices={**price_list()["models"][MOCK], "output": 11.0}), name="other.json")), ["price_list_sha256"]),
        ("no flags", [], ["cost_limit_usd", "price_list_sha256"]),
    ):
        code, error = error_of(live(study, "plain", "r", *flags, cases=["D03"]))
        assert (error["code"], error["details"]["differs"]) == ("REQUEST_CONFLICT", differs), label


# --- the ceiling is D-146's formula on the price file and the declared limits ------------------------------------


def test_the_ceiling_helper_gives_the_formula_on_a_fixture_price_list():
    """Prices 2 / 10 with a cache write of 2.5 (p_max 2.5), C = 0.08, the output cap 1,024, B = 10,000, 200 Episodes.

    E = 0.08 x (1 + 2.5 / 2) + [2.5 x (1,024 + 10,000 + 2,048) + 10 x 1,024] / 1e6
      = 0.18 + (32,680 + 10,240) / 1e6 = 0.18 + 0.04292 = 0.22292;
    ceiling = 200 x 0.22292 = 44.584.
    """
    prices = price_list([TEST_MODEL])
    limits = EpisodeLimits(cost_limit_usd=0.08)
    assert FRAMING_ALLOWANCE_TOKENS == 2_048
    assert math.isclose(episode_bound(prices, TEST_MODEL, limits, 10_000), 0.22292)
    assert math.isclose(ceiling(prices, TEST_MODEL, limits, 10_000, 200), 44.584)
    # the part of E that depends on C, in D-146's illustration
    no_fixed_part = episode_bound(prices, TEST_MODEL, limits, 0) - episode_bound(prices, TEST_MODEL, EpisodeLimits(cost_limit_usd=0.0), 0)
    assert math.isclose(no_fixed_part, 0.18)


# --- the post-run witness ------------------------------------------------------------------------------------------


def two_tool_calls_at_once():
    """A model whose first reply holds two tool calls in one assistant message, and whose answer then costs USD 0.4."""

    def call(input, tools, tool_choice, config):
        if not any(m.role == "tool" for m in input):
            return _two_calls()
        output = ModelOutput.from_content(MOCK, "done")
        output.usage = ModelUsage(input_tokens=200_000, output_tokens=100, total_tokens=200_100)
        return output

    return call


def _two_calls():
    output = ModelOutput.for_tool_call(MOCK, "describe_schema", {})
    output.choices[0].message.tool_calls = [
        ToolCall(id="a", function="describe_schema", arguments={}),
        ToolCall(id="b", function="describe_schema", arguments={}),
    ]
    output.usage = ModelUsage(input_tokens=1_000, output_tokens=100, total_tokens=1_100)
    return output


def capped_log(tmp_path, script):
    return runner.run_episodes(
        WORKLOAD.cases("dev", ["D03"]), workload=WORKLOAD, configuration="plain", model=runner.mock_model(script), repeats=1,
        log_dir=tmp_path, limits=EpisodeLimits(cost_limit_usd=LIMIT), model_costs=price_list([MOCK])["models"],
    )


def test_the_post_run_witness_passes_a_log_made_under_the_cost_limit_and_reports_two_tool_calls_and_a_cost_above_e(tmp_path):
    bound = episode_bound(price_list([MOCK]), MOCK, EpisodeLimits(cost_limit_usd=LIMIT), 10_000)
    clean = capped_log(tmp_path / "clean", costly())
    assert post_run_faults(clean, bound) == []
    planted = post_run_faults(capped_log(tmp_path / "planted", two_tool_calls_at_once()), bound)
    assert any("holds 2 tool calls" in fault for fault in planted), planted
    assert any("exceeds E" in fault for fault in planted), planted
