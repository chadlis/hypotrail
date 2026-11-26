"""The kept Chinook `dev` Campaign (#235): its captures, its Study and its spend, read back from what is committed.

The captures under `docs/handbook/traces/campaign-chinook-dev/commands/` are the commands' own output, written by
`.claude/skills/drive/capture.sh`; each step's `.argv` is its `printf '%q '` line. The Study is read on a copy, so nothing
here writes in the kept folder. The post-run witness of ticket 1b (#234), `_cost_ceiling.post_run_faults`, is applied to
each kept Inspect log with the ceiling file's E.
"""

import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from inspect_ai.log import read_eval_log

from _campaign_plan import LAUNCHER, SIDES, Filler, read_plan, rule_option, technical_failures, unscored_episodes
from _cost_ceiling import post_run_faults

from hypotrail.core import artifacts
from hypotrail.core.errors import IntegrityError

ROOT = Path(__file__).resolve().parent.parent
PLAN = read_plan(ROOT)
CEILING = json.loads((ROOT / PLAN["ceiling_file"]).read_text(encoding="utf-8"))
PRICES = json.loads((ROOT / PLAN["price_list"]).read_text(encoding="utf-8"))["models"][PLAN["model"]]
CAPTURES = ROOT / PLAN["captures"]
STUDY = ROOT / PLAN["study"]
FOLDER = ROOT / Path(PLAN["ceiling_file"]).parent
SPEND = json.loads((FOLDER / "spend.json").read_text(encoding="utf-8"))
E = CEILING["episode_bound"]["value_usd"]
BUDGET_USD = 80
CAPTURE_KINDS = (".argv", ".start", ".out", ".err", ".exit", ".end")
STEPS = sorted(p.stem for p in CAPTURES.glob("*.argv"))
# the paid invocations made, in the plan's order
PAID = [step for step in PLAN["paid_steps"] if step in STEPS]
# what `uv` itself prints on this machine before the command runs; any other line of `.err` is the command's own
UV_NOTICE = "warning: The `UV_NATIVE_TLS` environment variable is deprecated and will be removed in a future release. Use `UV_SYSTEM_CERTS` instead."
TOKEN_KINDS = {"input": "input_tokens", "input_cache_read": "input_tokens_cache_read", "input_cache_write": "input_tokens_cache_write", "output": "output_tokens"}
# the prefix of an Anthropic API key: no file of the kept folder holds one
KEY_PREFIX = b"sk-ant-"


def captured(step: str, kind: str) -> str:
    return (CAPTURES / f"{step}{kind}").read_text(encoding="utf-8")


def attempt_of(step: str) -> str:
    return re.match(r"Attempt (\S+) ", captured(step, ".out")).group(1)


def attempt_folder(attempt_id: str, study: Path = STUDY) -> Path:
    return study / "attempts" / attempt_id


def filler() -> Filler:
    f = Filler(PLAN, ROOT)
    for step in STEPS:
        f.ran(step, captured(step, ".out"))
    return f


def selected_steps() -> list:
    """The steps the plan's rules select, given what the captures recorded: a rerun only after a technical failure, one Decision line."""
    steps = ["init"]
    for side in SIDES:
        steps.append(f"run-{side}")
        if technical_failures(attempt_folder(attempt_of(f"run-{side}")) / "observations.jsonl"):
            steps.append(f"rerun-{side}")
    steps += ["assess-plain", "assess-verify", "compare", "status", "decide-neither" if filler().delta_is_null() else "decide-rule", "report"]
    return steps


def paid_steps() -> list:
    return [step for step in STEPS if step in PLAN["paid_steps"]]


def last_attempt(side: str) -> str:
    return attempt_of(f"rerun-{side}" if f"rerun-{side}" in STEPS else f"run-{side}")


# --- T2-4: one comparison per step, over the steps captured --------------------------------------------------------------------------


def test_the_steps_captured_are_the_ones_the_plans_rules_select_each_with_its_six_capture_files():
    assert sorted(selected_steps()) == STEPS
    for step in STEPS:
        for kind in CAPTURE_KINDS:
            assert (CAPTURES / f"{step}{kind}").is_file(), (step, kind)
    starts = [captured(step, ".start").strip() for step in selected_steps()]
    assert starts == sorted(starts)  # in the plan's order


@pytest.mark.parametrize("step", STEPS)
def test_each_steps_argv_parsed_with_shlex_equals_the_plans_line_filled_and_its_exit_is_0(step):
    argv = shlex.split(captured(step, ".argv"))
    assert argv[: len(LAUNCHER)] == LAUNCHER
    assert argv == filler().fill(step)
    assert captured(step, ".exit").strip() == "0"


def test_at_most_four_run_agent_invocations_and_at_most_one_rerun_per_line():
    invocations = [step for step in STEPS if shlex.split(captured(step, ".argv"))[len(LAUNCHER) : len(LAUNCHER) + 2] == ["run", "agent"]]
    assert sorted(invocations) == paid_steps() and len(invocations) <= 4
    for side in SIDES:
        assert [s for s in invocations if s.endswith(f"-{side}")] in ([f"run-{side}"], [f"rerun-{side}", f"run-{side}"])


@pytest.mark.parametrize("side", [s for s in SIDES if f"rerun-{s}" in STEPS])
def test_each_rerun_follows_a_first_attempt_with_a_technical_failure_names_it_and_fits_the_budget(side):
    first = attempt_of(f"run-{side}")
    assert technical_failures(attempt_folder(first) / "observations.jsonl")
    argv = shlex.split(captured(f"rerun-{side}", ".argv"))
    assert argv[argv.index("--retry-of") + 1] == first
    rows = [row["step"] for row in SPEND["invocations"]]
    before = sum(row["cost_usd"] for row in SPEND["invocations"][: rows.index(f"rerun-{side}")])
    assert before + CEILING["rerun_ceiling_usd"] <= BUDGET_USD


# --- T2-5: the kept Study, read on a copy -------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def copy(tmp_path_factory):
    target = tmp_path_factory.mktemp("kept") / "study"
    shutil.copytree(STUDY, target)
    return target


@pytest.fixture(scope="module")
def status(copy):
    done = subprocess.run([sys.executable, "-m", "hypotrail", "status", "--study", str(copy), "--json"], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def artifact_refs(value) -> list:
    """Every ArtifactRef a record of the Study holds."""
    if isinstance(value, dict):
        if {"path", "sha256", "size_bytes", "media_type", "role"} <= set(value):
            return [value]
        return [ref for item in value.values() for ref in artifact_refs(item)]
    if isinstance(value, list):
        return [ref for item in value for ref in artifact_refs(item)]
    return []


def study_refs(study: Path) -> list:
    refs = []
    for record in sorted(study.rglob("*.json")):
        refs += artifact_refs(json.loads(record.read_text(encoding="utf-8")))
    return refs


def test_the_attempts_are_two_to_four_llm_live_on_dev_each_of_100_by_r_episodes_with_the_counts_the_captures_show(copy, status):
    attempts = status["attempts"]
    assert 2 <= len(attempts) <= 4 and len(attempts) == len(paid_steps())
    by_id = {a["attempt_id"]: a for a in attempts}
    for step in paid_steps():
        attempt = by_id[attempt_of(step)]
        manifest = json.loads((attempt_folder(attempt["attempt_id"], copy) / "attempt.json").read_text(encoding="utf-8"))
        assert attempt["mode"] == "llm_live" and manifest["effective_config"]["partition"] == "dev"
        assert manifest["effective_config"]["configuration"]["id"] == step.split("-")[-1]
        counts = attempt["item_counts"]
        assert sum(counts.values()) == 100 * PLAN["repeats"]
        shown = re.search(r"\((\d+) Episodes produced, (\d+) failed, (\d+) missing\)", captured(step, ".out")).groups()
        assert tuple(map(int, shown)) == (counts["produced"], counts["failed"], counts["missing"])
        episodes = [json.loads(line) for line in (attempt_folder(attempt["attempt_id"], copy) / "observations.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        assert all(e["status"] == "produced" or (e["status"] == "failed" and e["reason"]) or e["status"] == "missing" for e in episodes)
        assert attempt["retry_of"] == (attempt_of(f"run-{step.split('-')[-1]}") if step.startswith("rerun-") else None)


def test_the_assessments_are_two_one_per_configuration_each_of_its_lines_last_observation_set(copy, status):
    assessed = {a["observation_set_id"] for a in status["assessments"]}
    expected = set()
    for side in SIDES:
        expected.add(json.loads((attempt_folder(last_attempt(side), copy) / "observation_set.json").read_text(encoding="utf-8"))["observation_set_id"])
    assert len(status["assessments"]) == 2 and assessed == expected


def test_the_comparison_is_one_of_the_two_assessments_with_plain_as_control(status):
    (comparison,) = status["comparisons"]
    ids = {a["observation_set_id"]: a["assessment_id"] for a in status["assessments"]}
    plain = ids[filler().value("<OBSERVATION_SET_ID_PLAIN>")]
    verify = ids[filler().value("<OBSERVATION_SET_ID_VERIFY>")]
    assert comparison["roles"] == {"control_assessment_id": plain, "candidate_assessment_id": verify}


def test_the_decision_is_one_that_cites_the_comparison_applies_and_has_the_option_the_plans_rule_gives(copy, status):
    (comparison,) = status["comparisons"]
    (decision,) = status["decisions"]
    assert decision["cited_ids"] == [comparison["comparison_id"]] and decision["applies"] is True
    assert status["pending_decisions"] == []
    record = json.loads(next((copy / "decisions").glob("*.json")).read_text(encoding="utf-8"))
    assert (record["author"], record["question"]) == ("proxy", PLAN["decision"]["question"])
    delta = comparison["delta"]
    if delta["value"] is None:
        matrix = json.loads((copy / comparison["matrix_ref"]["path"]).read_text(encoding="utf-8"))
        assert record["option"] == "Choose neither yet"
        assert record["source"] == PLAN["decision"]["source"] + "; unscored Episodes: " + unscored_episodes(matrix)
    else:
        assert record["option"] == rule_option(delta["value"]) and record["source"] == PLAN["decision"]["source"]


def test_there_is_no_exposure(status):
    assert status["exposures"]["recorded_in_this_study"] == 0 and status["exposures"]["entries"] == []
    assert status["freeze_records"] == []


@pytest.mark.parametrize("index", range(len(study_refs(STUDY))))
def test_each_artifact_reference_of_the_study_reads_back_against_its_digest(copy, index):
    artifacts.read_verified(copy, study_refs(copy)[index])


def test_a_changed_byte_of_an_assessments_per_item_csv_is_reported_as_artifact_integrity(tmp_path):
    target = tmp_path / "study"
    shutil.copytree(STUDY, target)
    per_item = next(target.glob("assessments/*/per_item.csv"))
    data = bytearray(per_item.read_bytes())
    data[-2] = ord("0") if data[-2] != ord("0") else ord("1")
    per_item.write_bytes(bytes(data))
    failed = []
    for ref in study_refs(target):
        try:
            artifacts.read_verified(target, ref)
        except IntegrityError as error:
            failed.append((ref["path"], error.code))
    assert failed == [(per_item.relative_to(target).as_posix(), "ARTIFACT_INTEGRITY")]


@pytest.mark.parametrize("step", PAID)
def test_on_each_kept_log_no_assistant_message_holds_two_tool_calls_and_no_episode_cost_exceeds_e(step):
    (log,) = (attempt_folder(attempt_of(step)) / "inspect").glob("*.eval")
    assert post_run_faults(str(log), E) == []


@pytest.mark.parametrize("step", PAID)
def test_each_attempt_states_the_served_model_beside_the_requested_one_and_the_scan_showed_no_warning(step):
    config = json.loads((attempt_folder(attempt_of(step)) / "attempt.json").read_text(encoding="utf-8"))["effective_config"]
    assert config["model"] == PLAN["model"] and config["served_model"]
    assert f"(model {config['model']}, served_model {config['served_model']})" in captured(step, ".out")
    assert captured(step, ".out").count("\n") == 1  # the Attempt line, and no warning line
    assert [line for line in captured(step, ".err").splitlines() if line != UV_NOTICE] == []


def test_no_file_of_the_kept_folder_holds_a_key():
    blob = b"".join(p.read_bytes() for p in FOLDER.rglob("*") if p.is_file())
    for log in FOLDER.rglob("*.eval"):
        blob += read_eval_log(str(log)).model_dump_json().encode()  # decoded through Inspect's log API
    assert KEY_PREFIX not in blob


# --- T2-6: the spend, recomputed ---------------------------------------------------------------------------------------------------------


def run_record(step: str) -> dict:
    return json.loads((attempt_folder(attempt_of(step)) / "run.json").read_text(encoding="utf-8"))


def test_spend_json_lists_each_paid_invocation_and_says_it_is_an_estimate():
    assert [row["step"] for row in SPEND["invocations"]] == [s for s in PLAN["paid_steps"] if s in STEPS]
    assert [row["attempt_id"] for row in SPEND["invocations"]] == [attempt_of(s) for s in PLAN["paid_steps"] if s in STEPS]
    assert SPEND["estimate"].startswith("An estimate") and "can differ from what is billed" in SPEND["estimate"]


@pytest.mark.parametrize("kind", TOKEN_KINDS)
@pytest.mark.parametrize("step", PAID)
def test_each_token_kind_of_each_invocation_is_the_sum_over_its_run_json(step, kind):
    (row,) = [r for r in SPEND["invocations"] if r["step"] == step]
    assert row["tokens"][kind] == sum(e.get(TOKEN_KINDS[kind]) or 0 for e in run_record(step)["episodes"])


@pytest.mark.parametrize("step", PAID)
def test_each_invocations_cost_is_its_logs_cost_equal_to_its_tokens_priced_at_the_price_list_and_within_its_ceiling(step):
    (row,) = [r for r in SPEND["invocations"] if r["step"] == step]
    episodes = run_record(step)["episodes"]
    unknown = any(e.get("cost") is None for e in episodes)
    assert row["cost_unknown"] is unknown
    assert row["cost_usd"] == pytest.approx(len(episodes) * E if unknown else sum(e["cost"] for e in episodes), abs=1e-9)
    if not unknown:
        priced = sum(row["tokens"][kind] * PRICES[kind] for kind in TOKEN_KINDS) / 1e6
        assert row["cost_usd"] == pytest.approx(priced, abs=1e-6)
    assert row["ceiling_usd"] == pytest.approx(len(episodes) * E, abs=1e-9)
    assert row["cost_usd"] <= row["ceiling_usd"]


def test_the_total_over_every_paid_invocation_is_at_most_usd_80_and_the_rest_is_stated():
    total = sum(row["cost_usd"] for row in SPEND["invocations"])
    assert SPEND["total_usd"] == pytest.approx(total, abs=1e-9) and total <= BUDGET_USD
    assert SPEND["budget_usd"] == BUDGET_USD and SPEND["remaining_usd"] == pytest.approx(BUDGET_USD - total, abs=1e-9)
