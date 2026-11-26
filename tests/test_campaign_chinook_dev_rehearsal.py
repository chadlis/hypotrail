"""The offline rehearsal of the Chinook `dev` Campaign (#235): the plan's lines, through `decide`, on the 100 `dev` Cases.

The lines are read from `docs/handbook/traces/campaign-chinook-dev/plan.json` (`_campaign_plan`), their placeholders filled from
the earlier output the plan names, and each line is run as a process of its own in a fresh copy of the checkout, from the copy's
root, with the same relative Study path. The copy leaves out what the paid run itself writes beside the plan (its Study, captures,
report page and spend), so the rehearsal starts from the commit the run is made from. Two things differ from the live line: the
provider, patched (`DRIVER` replaces `prepared_model` with Inspect's mock model, priced as the price list prices the requested model,
then runs `hypotrail.__main__` with the line's own arguments), and the launcher (the live line starts with `uv run python -m
hypotrail`; the driver runs under the test interpreter, so `uv run` was not rehearsed, as D-029 on chadlis/hypotrail#75 records).
No model is called and the network is guarded in the driver.

Three Campaigns are rehearsed: one with no technical failure; one where an Episode of `plain`'s first Attempt is a technical failure,
which runs the rerun line; one where the failure recurs in the rerun, so the Comparison's delta is null and the Decision line is
"Choose neither yet".
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _campaign_plan import LAUNCHER, PLACEHOLDER, SIDES, Filler, line_of, read_plan, rule_option, spend_of, technical_failures

ROOT = Path(__file__).resolve().parent.parent
PLAN = read_plan(ROOT)
CEILING = json.loads((ROOT / PLAN["ceiling_file"]).read_text(encoding="utf-8"))
FOLDER = Path(PLAN["ceiling_file"]).parent
# what the paid run writes beside the plan, absent from the commit the run is made from
RUN_OUTPUTS = {FOLDER / name for name in ("study", "commands", "report.html", "spend.json", "commit.txt")}
FAKE_KEY = "sk-ant-FAKE-rehearsal-0123456789abcdef"
KEY_VARIABLE = "HYPOTRAIL_ANTHROPIC_API_KEY"
SERVED_MODEL = "claude-sonnet-5-5-rehearsal"
CASES = [f"D{n:02d}" for n in range(1, 101)]
FAILING_CASE = "D03"  # an answered Case: the patched provider raises on its first model call
BUDGET_USD = 80

DRIVER = '''
"""Runs `python -m hypotrail ARGS` with the provider patched. Written by tests/test_campaign_chinook_dev_rehearsal.py."""
import json, os, runpy, socket, sys

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
from _run_agent_helpers import ALL_CASES, AnsweringModel
from hypotrail.agentic import live, runner

args = sys.argv[1:]
request_id = args[args.index("--request-id") + 1] if "--request-id" in args else None
failing = json.loads(os.environ.get("REHEARSAL_FAIL", "{}")).get(request_id)
script = AnsweringModel(ALL_CASES, error_on=None if failing is None else (failing, 1))


def provider(input, tools, tool_choice, config):
    output = script(input, tools, tool_choice, config)
    output.model = os.environ["REHEARSAL_SERVED_MODEL"]
    return output


def prepared_model(model_id, api_key, *args, **kwargs):
    note("model", {"requested": model_id, "key_given": bool(api_key), "key_is_fake": api_key == os.environ["REHEARSAL_FAKE_KEY"]})
    if "--price-list" in sys.argv:  # the mock model is priced as the price list prices the requested model
        from inspect_ai.model import ModelCost, ModelInfo, set_model_cost, set_model_info

        prices = json.load(open(sys.argv[sys.argv.index("--price-list") + 1], encoding="utf-8"))["models"][model_id]
        set_model_info("mockllm/model", ModelInfo(organization="rehearsal", model="mockllm/model"))
        set_model_cost("mockllm/model", ModelCost(**prices))
    return runner.mock_model(provider)


live.prepared_model = prepared_model
sys.argv = ["hypotrail"] + args
runpy.run_module("hypotrail", run_name="__main__", alter_sys=True)
'''


class Rehearsal:
    """A fresh copy of the checkout and the plan's lines run in it, each filled from the outputs before it."""

    def __init__(self, base: Path, fail: dict):
        self.checkout = base / "checkout"
        self.log = base / "rehearsal.jsonl"
        self.driver = base / "driver.py"
        self.driver.write_text(DRIVER, encoding="utf-8")
        skip = {".venv", ".git", ".claude", "__pycache__", ".pytest_cache", "node_modules"}

        def ignored(folder, names):
            relative = Path(folder).resolve().relative_to(ROOT)
            return [n for n in names if n in skip or relative / n in RUN_OUTPUTS]

        shutil.copytree(ROOT, self.checkout, ignore=ignored)
        self.plan = read_plan(self.checkout)
        self.filler = Filler(self.plan, self.checkout)
        self.ran = []  # (step, filled argv, exit code, stdout, stderr)
        env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy") and k not in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", KEY_VARIABLE)}
        env.update(
            {KEY_VARIABLE: FAKE_KEY}, PYTHONPATH=str(self.checkout / "src"), NO_PROXY="*", REHEARSAL_LOG=str(self.log),
            REHEARSAL_SERVED_MODEL=SERVED_MODEL, REHEARSAL_FAKE_KEY=FAKE_KEY, REHEARSAL_FAIL=json.dumps(fail),
        )
        self.env = env
        self.spent = 0.0
        self.spend_before_rerun = {}

    def step(self, step: str):
        argv = self.filler.fill(step)
        assert argv[: len(LAUNCHER)] == LAUNCHER, argv
        done = subprocess.run([sys.executable, str(self.driver), *argv[len(LAUNCHER):]], cwd=self.checkout, env=self.env, capture_output=True, text=True)
        self.ran.append((step, argv, done.returncode, done.stdout, done.stderr))
        self.filler.ran(step, done.stdout)
        return done

    def attempt_folder(self, attempt_id: str) -> Path:
        return self.checkout / self.plan["study"] / "attempts" / attempt_id

    def paid(self, step: str):
        done = self.step(step)
        attempt_id = done.stdout.split()[1] if done.stdout.startswith("Attempt ") else None
        if attempt_id is not None:
            record = json.loads((self.attempt_folder(attempt_id) / "run.json").read_text(encoding="utf-8"))
            self.spent += spend_of(record, CEILING["episode_bound"]["value_usd"])
        return attempt_id

    def campaign(self):
        """The plan's lines in order: a rerun only after a technical failure and within the budget, one Decision line by the delta."""
        self.step("init")
        for side in SIDES:
            first = self.paid(f"run-{side}")
            if first is not None and technical_failures(self.attempt_folder(first) / "observations.jsonl"):
                self.spend_before_rerun[side] = self.spent
                if self.spent + CEILING["rerun_ceiling_usd"] <= BUDGET_USD:
                    self.paid(f"rerun-{side}")
        for step in ("assess-plain", "assess-verify", "compare", "status"):
            self.step(step)
        self.step("decide-neither" if self.filler.delta_is_null() else "decide-rule")
        self.step("report")
        return self

    @property
    def study(self) -> Path:
        return self.checkout / self.plan["study"]

    def status(self) -> dict:
        done = subprocess.run(
            [sys.executable, str(self.driver), "status", "--study", self.plan["study"], "--json"], cwd=self.checkout, env=self.env, capture_output=True, text=True
        )
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    def attempt(self, request_id: str) -> Path:
        (found,) = [a for a in self.status()["attempts"] if a["request_id"] == request_id]
        return self.study / "attempts" / found["attempt_id"]

    def notes(self, kind: str) -> list:
        if not self.log.exists():
            return []
        return [n for n in map(json.loads, self.log.read_text(encoding="utf-8").splitlines()) if n["kind"] == kind]

    def steps(self) -> list:
        return [step for step, *_ in self.ran]

    def comparison(self) -> dict:
        (path,) = (self.study / "comparisons").glob("*/comparison.json")
        return json.loads(path.read_text(encoding="utf-8"))

    def decision(self) -> dict:
        (path,) = (self.study / "decisions").glob("*.json")
        return json.loads(path.read_text(encoding="utf-8"))

    def assessment(self, assessment_id: str) -> dict:
        return json.loads((self.study / "assessments" / assessment_id / "assessment.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def clean(tmp_path_factory):
    """The Campaign with no technical failure, run once; the tests below assert what it recorded."""
    return Rehearsal(tmp_path_factory.mktemp("clean"), {}).campaign()


@pytest.fixture(scope="module")
def rerun(tmp_path_factory):
    """An Episode of `plain`'s first Attempt fails in execution; the rerun has none."""
    return Rehearsal(tmp_path_factory.mktemp("rerun"), {PLAN["request_ids"]["plain"]: FAILING_CASE}).campaign()


@pytest.fixture(scope="module")
def unscored(tmp_path_factory):
    """The failure of `plain`'s first Attempt recurs in its rerun: an Episode stays unscored after the allowed rerun."""
    fail = {PLAN["request_ids"]["plain"]: FAILING_CASE, PLAN["rerun_request_ids"]["plain"]: FAILING_CASE}
    return Rehearsal(tmp_path_factory.mktemp("unscored"), fail).campaign()


def manifest_of(folder: Path) -> dict:
    return json.loads((folder / "attempt.json").read_text(encoding="utf-8"))


def observations_of(folder: Path) -> list:
    return [json.loads(line) for line in (folder / "observations.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


# --- one process per line, over the lines of the plan ----------------------------------------------------------------------------------

CLEAN_STEPS = ["init", "run-plain", "run-verify", "assess-plain", "assess-verify", "compare", "status", "decide-rule", "report"]


@pytest.mark.parametrize("step", CLEAN_STEPS)
def test_each_line_of_the_plan_exits_0_as_a_process_of_its_own_from_the_copys_root_with_the_same_relative_study(clean, step):
    assert clean.steps() == CLEAN_STEPS
    ((_, argv, code, out, err),) = [entry for entry in clean.ran if entry[0] == step]
    assert code == 0, (step, out[-1500:], err[-1500:])
    assert argv[argv.index("--study") + 1] == PLAN["study"] and not PLAN["study"].startswith("/")
    assert {n["detail"] for n in clean.notes("start")} == {str(clean.checkout)}  # every line ran in the copy's root
    assert not (clean.checkout / ".git").exists() and clean.checkout != ROOT


def test_the_lines_run_are_the_plans_each_placeholder_filled_from_the_earlier_output_the_plan_names(clean):
    for step, argv, *_ in clean.ran:
        template = line_of(PLAN, step)
        assert len(argv) == len(template), step
        for word, filled in zip(template, argv):
            if not PLACEHOLDER.search(word):
                assert filled == word, (step, word)
            else:
                assert not PLACEHOLDER.search(filled), (step, filled)
    outputs = clean.filler.outputs
    fills = dict(zip(line_of(PLAN, "assess-plain"), next(a for s, a, *_ in clean.ran if s == "assess-plain")))
    assert fills["<OBSERVATION_SET_ID_PLAIN>"] in outputs["run-plain"] and fills["<REFERENCES_ID>"] in outputs["init"]
    decide = dict(zip(line_of(PLAN, "decide-rule"), next(a for s, a, *_ in clean.ran if s == "decide-rule")))
    assert decide["<COMPARISON_ID>"] in outputs["compare"]
    assert decide["<READ_SEQUENCE>"] == str(json.loads(outputs["status"])["write_sequence"])


# --- one assertion per Attempt, over the two --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("side", SIDES)
def test_each_run_agent_line_records_one_completed_attempt_of_100_by_r_episodes_with_the_same_model_and_limits(clean, side):
    folder = clean.attempt(PLAN["request_ids"][side])
    manifest = manifest_of(folder)
    repeats = PLAN["repeats"]
    episodes = observations_of(folder)
    other = manifest_of(clean.attempt(PLAN["request_ids"]["verify" if side == "plain" else "plain"]))["effective_config"]
    assert manifest["technical_status"] == "completed" and manifest["mode"] == "llm_live"
    assert manifest["effective_config"]["configuration"]["id"] == side
    assert sorted((e["case_id"], e["repeat"]) for e in episodes) == sorted((c, n) for c in CASES for n in range(repeats))
    assert len(episodes) == 100 * repeats
    config = manifest["effective_config"]
    assert config["model"] == other["model"] == PLAN["model"] and config["limits"] == other["limits"]
    assert config["limits"]["cost_limit_usd"] == PLAN["episode_cost_limit_usd"] and config["limits"]["parallel_tool_calls"] is False


@pytest.mark.parametrize("side", SIDES)
def test_each_assessment_scores_every_episode(clean, side):
    out = clean.filler.outputs[f"assess-{side}"]
    record = clean.assessment(out.split()[1].rstrip(":"))
    counts = record["counts"]
    assert counts["expected"] == counts["scored"] == 100 * PLAN["repeats"] and counts["unscored"] == counts["errored"] == 0


# --- one assertion per clause on the Comparison ------------------------------------------------------------------------------------------


def test_the_comparison_has_plain_as_control_and_verify_as_candidate(clean):
    ids = {side: clean.filler.outputs[f"assess-{side}"].split()[1].rstrip(":") for side in SIDES}
    assert clean.comparison()["roles"] == {"control_assessment_id": ids["plain"], "candidate_assessment_id": ids["verify"]}


def test_the_comparison_is_compatible(clean):
    record = clean.comparison()
    assert record["comparability"]["status"] == "compatible" and all(c["passed"] for c in record["comparability"]["checks"])


def test_the_comparison_covers_every_paired_episode(clean):
    coverage = clean.comparison()["coverage"]
    assert coverage["complete"] is True and coverage["paired"] == coverage["expected"] == 100 * PLAN["repeats"]


def test_the_comparison_carries_comparison_order_not_alternated(clean):
    assert [w["code"] for w in clean.comparison()["warnings"]] == ["COMPARISON_ORDER_NOT_ALTERNATED"]


# --- one assertion per clause on the Decision --------------------------------------------------------------------------------------------


def test_the_decision_is_recorded_with_author_proxy(clean):
    assert clean.decision()["author"] == PLAN["decision"]["author"] == "proxy"


def test_the_decision_answers_the_plans_question(clean):
    assert clean.decision()["question"] == PLAN["decision"]["question"] == "Which Configuration is kept on dev?"


def test_the_decisions_option_is_the_one_the_plans_rule_gives_for_the_rehearsed_shares(clean):
    delta = clean.comparison()["delta"]
    shares = {"plain": delta["control"], "verify": delta["candidate"]}
    kept = "verify" if shares["verify"] > shares["plain"] else "plain"  # "on a tie, keep `plain`"
    assert clean.decision()["option"] == {"plain": "Keep the Control", "verify": "Keep the Candidate"}[kept] == rule_option(delta["value"])


def test_the_decision_has_the_plans_source(clean):
    assert clean.decision()["source"] == PLAN["decision"]["source"]
    assert "D-145" in PLAN["decision"]["source"] and "#235" in PLAN["decision"]["source"]


def test_the_decision_cites_the_comparison_which_is_no_longer_a_pending_decision(clean):
    comparison_id = clean.comparison()["comparison_id"]
    status = clean.status()
    assert clean.decision()["cited_ids"] == [comparison_id]
    assert [row["applies"] for row in status["decisions"]] == [True]
    assert status["pending_decisions"] == []


# --- one assertion on the rehearsal log ----------------------------------------------------------------------------------------------------


def test_no_model_is_called_no_network_attempt_is_made_and_the_key_variable_holds_a_fake_value_and_the_real_key_is_absent(clean):
    assert clean.notes("network") == []
    models = clean.notes("model")
    assert [m["detail"]["requested"] for m in models] == [PLAN["model"]] * 2
    assert all(m["detail"]["key_given"] and m["detail"]["key_is_fake"] for m in models)
    assert clean.env[KEY_VARIABLE] == FAKE_KEY
    real = os.environ.get(KEY_VARIABLE)
    assert "ANTHROPIC_API_KEY" not in clean.env and (not real or real == FAKE_KEY or real not in clean.env.values())
    shown = "".join(out + err for *_, out, err in clean.ran)
    assert FAKE_KEY not in shown and all(FAKE_KEY.encode() not in p.read_bytes() for p in clean.study.rglob("*") if p.is_file())


# --- one run of the rerun line ---------------------------------------------------------------------------------------------------------------


def test_a_technical_failure_of_plain_runs_the_rerun_line_in_its_form_and_its_observation_set_is_the_one_assessed(rerun):
    assert rerun.steps() == ["init", "run-plain", "rerun-plain", "run-verify", "assess-plain", "assess-verify", "compare", "status", "decide-rule", "report"]
    assert all(code == 0 for _, _, code, *_ in rerun.ran), [(s, err[-800:]) for s, _, code, _, err in rerun.ran if code]
    first = rerun.attempt(PLAN["request_ids"]["plain"])
    assert [(c, s) for c, _, s, _ in technical_failures(first / "observations.jsonl")] == [(FAILING_CASE, "failed")]
    second = rerun.attempt(PLAN["rerun_request_ids"]["plain"])
    argv = next(a for s, a, *_ in rerun.ran if s == "rerun-plain")
    assert argv[-4:] == ["--request-id", PLAN["rerun_request_ids"]["plain"], "--retry-of", first.name]
    assert manifest_of(second)["retry_of"] == first.name and technical_failures(second / "observations.jsonl") == []
    assert len(observations_of(second)) == 100 * PLAN["repeats"]  # whole: every Case again
    rerun_set = json.loads((second / "observation_set.json").read_text(encoding="utf-8"))["observation_set_id"]
    assessed = next(a for s, a, *_ in rerun.ran if s == "assess-plain")
    assert assessed[assessed.index("--observations") + 1] == rerun_set
    assert rerun.spend_before_rerun["plain"] + CEILING["rerun_ceiling_usd"] <= BUDGET_USD
    assert first.is_dir()  # the first Attempt stays in the Study


# --- one run of each Decision line, over the two ---------------------------------------------------------------------------------------------


def test_the_rule_decision_line_runs_when_the_delta_has_a_value(clean):
    assert "decide-rule" in clean.steps() and "decide-neither" not in clean.steps()
    assert clean.comparison()["delta"]["value"] is not None


def test_an_episode_unscored_after_the_rerun_gives_a_null_delta_and_the_decision_line_choose_neither_yet(unscored):
    assert unscored.steps() == ["init", "run-plain", "rerun-plain", "run-verify", "assess-plain", "assess-verify", "compare", "status", "decide-neither", "report"]
    assert all(code == 0 for _, _, code, *_ in unscored.ran), [(s, err[-800:]) for s, _, code, _, err in unscored.ran if code]
    comparison = unscored.comparison()
    assert comparison["delta"]["value"] is None and comparison["delta"]["reason"] == "coverage_incomplete"
    decision = unscored.decision()
    assert decision["option"] == "Choose neither yet" and decision["cited_ids"] == [comparison["comparison_id"]]
    assert decision["source"] == PLAN["decision"]["source"] + f"; unscored Episodes: plain {FAILING_CASE} repeat 0 (execution_failed)"
    assert unscored.status()["pending_decisions"] == []


def test_the_module_docstring_says_what_differs_from_the_live_line_the_provider_and_the_launcher():
    doc = " ".join(__doc__.split())
    for part in ("Two things differ from the live line", "the provider, patched", "the launcher", "`uv run` was not rehearsed", "D-029 on chadlis/hypotrail#75"):
        assert part in doc, part
