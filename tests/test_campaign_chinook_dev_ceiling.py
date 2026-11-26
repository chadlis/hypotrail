"""The Repeats, the Episode cost limit C and the ceiling of the Chinook `dev` Campaign, fixed before its first paid invocation (#235).

The ceiling file, `docs/handbook/traces/campaign-chinook-dev/ceiling.json`, is checked against what it is computed from:
the price list, the plan's C, B and the declared limits, through ticket 1b (#234)'s helper (`tests/_cost_ceiling.py`).
Its prices against the provider's page are read by the pre-run gate, not here: the suite has no network.
"""

import dataclasses
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from _cost_ceiling import FRAMING_ALLOWANCE_TOKENS, ceiling, episode_bound
from test_episode_cost_limit import B_BYTES

from hypotrail.agentic.limits import NOT_ENFORCEABLE, EpisodeLimits
from hypotrail.agentic.prices import PRICE_FIELDS, read_price_list
from hypotrail.agentic.sql_tool import QueryCaps

ROOT = Path(__file__).resolve().parent.parent
FOLDER = Path("docs/handbook/traces/campaign-chinook-dev")
PLAN = json.loads((ROOT / FOLDER / "plan.json").read_text(encoding="utf-8"))
CEILING = json.loads((ROOT / FOLDER / "ceiling.json").read_text(encoding="utf-8"))
PRICE_LIST = json.loads((ROOT / PLAN["price_list"]).read_text(encoding="utf-8"))
MODEL = PLAN["model"]
# D-131 on chadlis/hypotrail#75, "Budget": "USD 80 of live calls for this slice"
BUDGET_USD = 80
# D-145 on chadlis/hypotrail#75, point 6: "If the worst-case ceiling ... is at most USD 40, the campaign runs three Repeats"
THREE_REPEAT_BUDGET_USD = 40
CASES_PER_LINE = 100
LINES = 2
CENT = 0.01


def limits(c: float) -> EpisodeLimits:
    return EpisodeLimits(cost_limit_usd=c)


def bound(c: float) -> float:
    return episode_bound(PRICE_LIST, MODEL, limits(c), B_BYTES)


def paid_episodes(repeats: int) -> int:
    return LINES * CASES_PER_LINE * repeats


def is_round(value: float) -> bool:
    return abs(value / CENT - round(value / CENT)) < 1e-9


def dearest_kept_log_episode(before_this_campaign: bool) -> tuple:
    """(USD, run.json, case, repeat) of the kept Episode that costs most with every input token at p_max, over every kept run.json.

    With `before_this_campaign`, the run.json files this Campaign's own Study keeps are left out: the floor was fixed before them.
    """
    prices = PRICE_LIST["models"][MODEL]
    p_max = max(prices["input"], prices["input_cache_write"])
    listed = subprocess.run(["git", "ls-files", "docs/handbook/traces"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    priced = []
    own = PLAN["study"] + "/"
    for path in (p for p in listed if p.endswith("/run.json") and not (before_this_campaign and p.startswith(own))):
        for episode in json.loads((ROOT / path).read_text(encoding="utf-8"))["episodes"]:
            sent = sum(episode.get(k) or 0 for k in ("input_tokens", "input_tokens_cache_read", "input_tokens_cache_write"))
            usd = (sent * p_max + (episode.get("output_tokens") or 0) * prices["output"]) / 1e6
            priced.append((usd, path, episode["case_id"], episode["repeat"]))
    assert priced
    return max(priced)


# --- one comparison per ceiling, over the two, and E and the rerun ceiling ------------------------------------------------------------


@pytest.mark.parametrize("name, repeats", [("three_repeats", 3), ("one_repeat", 1)])
def test_each_ceiling_of_the_file_equals_the_formula_applied_to_the_price_list_the_plans_c_b_and_the_declared_limits(name, repeats):
    c = PLAN["episode_cost_limit_usd"]
    assert CEILING["episodes"][name] == paid_episodes(repeats)
    assert CEILING["ceilings_usd"][name] == pytest.approx(ceiling(PRICE_LIST, MODEL, limits(c), B_BYTES, paid_episodes(repeats)), abs=1e-9)


def test_e_and_the_ceiling_of_one_rerun_of_one_line_equal_the_formula_at_the_plans_c_and_repeats():
    c = PLAN["episode_cost_limit_usd"]
    assert CEILING["episode_bound"]["cost_limit_usd"] == c
    assert CEILING["episode_bound"]["value_usd"] == pytest.approx(bound(c), abs=1e-12)
    assert CEILING["rerun_ceiling_usd"] == pytest.approx(CASES_PER_LINE * PLAN["repeats"] * bound(c), abs=1e-9)
    prices = PRICE_LIST["models"][MODEL]
    assert CEILING["p_max"] == max(prices["input"], prices["input_cache_write"])
    assert (CEILING["p_in"], CEILING["p_out"]) == (prices["input"], prices["output"])


# --- one comparison per limit, over the fields of `EpisodeLimits`, and the SQL tool's caps ---------------------------------------------


@pytest.mark.parametrize("field", [f.name for f in dataclasses.fields(EpisodeLimits)])
def test_each_declared_limit_of_the_ceiling_file_equals_episode_limits_with_the_plans_cost_limit(field):
    declared = CEILING["declared_limits"]["episode_limits"]
    assert set(declared) == {f.name for f in dataclasses.fields(EpisodeLimits)}
    assert declared[field] == getattr(limits(PLAN["episode_cost_limit_usd"]), field)


def test_the_ceiling_file_names_tool_calls_not_enforced_and_holds_the_sql_tools_caps():
    declared = CEILING["declared_limits"]
    assert declared["episode_limits"]["parallel_tool_calls"] is False
    assert declared["tool_calls"] == {"enforced": False, "replaced_by": "one call per turn requested from the provider", "why": NOT_ENFORCEABLE["tool_calls"]}
    assert declared["query_caps"] == dataclasses.asdict(QueryCaps())


# --- one comparison per price, over the four kinds, and the price list's identity ------------------------------------------------------


@pytest.mark.parametrize("kind", PRICE_FIELDS)
def test_each_price_of_the_ceiling_file_equals_the_price_list(kind):
    assert CEILING["price_list"]["prices_usd_per_million_tokens"][kind] == PRICE_LIST["models"][MODEL][kind]


def test_the_ceiling_file_names_the_price_list_by_path_sha256_url_and_date_and_the_plan_names_the_same_file():
    checked = read_price_list(ROOT / PLAN["price_list"])  # the check `run agent` makes of it
    recorded = CEILING["price_list"]
    assert recorded["path"] == PLAN["price_list"] == str(FOLDER / "price-list.json")
    assert recorded["sha256"] == checked["sha256"] == hashlib.sha256((ROOT / PLAN["price_list"]).read_bytes()).hexdigest()
    assert (recorded["url"], recorded["read_on"]) == (checked["url"], checked["read_on"])
    assert CEILING["date"] == checked["read_on"]
    assert set(PRICE_LIST["models"]) == {MODEL}


def test_b_and_the_framing_allowance_of_the_ceiling_file_are_ticket_1bs():
    assert CEILING["b_bytes"] == B_BYTES
    assert CEILING["framing_allowance_tokens"] == FRAMING_ALLOWANCE_TOKENS == 2_048


# --- one assertion per condition on C, over the two, and its roundness -----------------------------------------------------------------


def test_c_is_the_largest_multiple_of_usd_0_01_whose_ceiling_at_the_plans_repeats_is_at_or_under_usd_80():
    c = PLAN["episode_cost_limit_usd"]
    episodes = paid_episodes(PLAN["repeats"])
    assert is_round(c), c
    assert ceiling(PRICE_LIST, MODEL, limits(c), B_BYTES, episodes) <= BUDGET_USD
    assert ceiling(PRICE_LIST, MODEL, limits(round(c + CENT, 2)), B_BYTES, episodes) > BUDGET_USD


def test_c_is_at_least_twice_the_dearest_kept_log_episode_priced_with_every_input_token_at_p_max_and_the_file_names_it():
    usd, path, case_id, repeat = dearest_kept_log_episode(before_this_campaign=True)
    assert PLAN["episode_cost_limit_usd"] >= 2 * usd
    assert PLAN["episode_cost_limit_usd"] >= 2 * dearest_kept_log_episode(before_this_campaign=False)[0]  # the Campaign's own Episodes too
    named = CEILING["dearest_kept_log_episode"]
    assert (named["run_json"], named["case_id"], named["repeat"]) == (path, case_id, repeat)
    assert named["priced_usd"] == pytest.approx(usd, abs=1e-12)
    assert CEILING["conditions_on_c"]["floor_usd"] == pytest.approx(2 * usd, abs=1e-12)


# --- one assertion on the plan's Repeats ---------------------------------------------------------------------------------------------


def test_the_plans_repeats_are_what_d145_point_6_gives_for_the_ceiling_files_figures_and_its_ceiling_is_at_most_usd_80():
    rule = CEILING["repeats_rule"]
    floor = CEILING["conditions_on_c"]["floor_usd"]
    smallest = rule["smallest_round_c_at_or_above_floor"]
    assert is_round(smallest) and smallest >= floor and round(smallest - CENT, 2) < floor
    # the three-Repeat ceiling grows with C, so a C that meets the floor gives one at most USD 40 only if the smallest such C does
    assert rule["three_repeat_ceiling_at_that_c_usd"] == pytest.approx(ceiling(PRICE_LIST, MODEL, limits(smallest), B_BYTES, paid_episodes(3)), abs=1e-9)
    expected = 3 if rule["three_repeat_ceiling_at_that_c_usd"] <= THREE_REPEAT_BUDGET_USD else 1
    assert PLAN["repeats"] == rule["repeats"] == expected
    at_plan = CEILING["ceilings_usd"]["three_repeats" if PLAN["repeats"] == 3 else "one_repeat"]
    assert at_plan <= (THREE_REPEAT_BUDGET_USD if PLAN["repeats"] == 3 else BUDGET_USD)


def test_the_ceiling_file_holds_each_field_the_ticket_names():
    for key in ("date", "price_list", "declared_limits", "b_bytes", "framing_allowance_tokens", "p_max", "p_max_formula", "episode_bound", "episodes", "ceilings_usd", "rerun_ceiling_usd", "dearest_kept_log_episode"):
        assert key in CEILING, key
    words = CEILING["episode_bound"]
    assert words["formula"] == "E = C × (1 + p_max/p_in) + [p_max × (1,024 + B + framing allowance) + p_out × 1,024] / 1e6"
    assert words["premise"] and words["derivation"]
    assert CEILING["p_max_formula"] == "p_max = max(input, input_cache_write)"
    assert CEILING["ceilings_usd"]["formula"] == "paid Episodes × E"
