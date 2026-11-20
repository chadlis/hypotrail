"""Ticket #74: two `llm_live` Attempts recorded by `run agent` (the mock model patched in by the test) are assessed and compared strictly, offline."""

import json
from pathlib import Path

import pytest
from _agent_compare_helpers import SCORER
from _agent_helpers import CHINOOK, REFERENCES, WORKLOAD, read_jsonl
from _assess_helpers import snapshot
from _run_agent_helpers import MODEL, ok, live, patch_model, refuse_provider, folder_of, observation_set_id_of, study_of
from _chinook_helpers import references_id
from _study_helpers import EXAMPLES, run_json

from hypotrail.agentic import rescore
from hypotrail.agentic import runner, sql_tool
from hypotrail.core.comparison import REFUSALS
from hypotrail.core.errors import EXIT_INTEGRITY_REFUSED


def assess(study, attempt):
    code, payload, err = run_json("assess", "--study", study, "--observations", observation_set_id_of(study, attempt), "--scorer", SCORER, "--references", references_id(study))
    assert code == 0, (payload, err)
    return payload["assessment"]


def compare(study, control, candidate, *more):
    return run_json("compare", "--study", study, "--control", control["assessment_id"], "--candidate", candidate["assessment_id"], *more)


@pytest.fixture(scope="module")
def sides(tmp_path_factory):
    """`plain` and `verify` run on the same dev Cases, Repeats, tools and limits, then assessed."""
    with pytest.MonkeyPatch.context() as patch:
        study = study_of(tmp_path_factory.mktemp("compare"))
        patch_model(patch)
        attempts = {"plain": ok(live(study, "plain", "plain", repeats=2)), "verify": ok(live(study, "verify", "verify", repeats=2))}
        yield study, attempts, {name: assess(study, attempt) for name, attempt in attempts.items()}


def test_two_recorded_llm_live_attempts_are_assessed_and_compared_strictly_with_the_model_the_tools_and_the_database_patched_to_fail(sides, monkeypatch, guard):
    study, attempts, assessments = sides
    # the model, the tools and the Chinook file all fail from here on: `assess` and `compare` use none of them
    refuse_provider(monkeypatch)

    def boom(*args, **kwargs):
        raise AssertionError("a tool was built")

    monkeypatch.setattr(sql_tool, "query_readonly", boom)
    monkeypatch.setattr(sql_tool, "describe_schema", boom)
    guard(EXAMPLES)
    again = {name: assess(study, attempt) for name, attempt in attempts.items()}  # an Assessment again, offline
    code, payload, err = compare(study, again["plain"], again["verify"])
    assert code == 0 and err == "", (payload, err)
    record = payload["comparison"]
    assert record["comparability"]["status"] == "compatible" and record["declared_factor"] == "configuration" and record["warnings"] == []
    assert [(c["check"], c["passed"], c["reason"]) for c in record["comparability"]["checks"]] == [
        (name, True, None) for name in ("population", "references", "scorer", "unit", "repeats", "tools", "model", "budgets", "mode")
    ]
    assert record["delta"]["value"] == 0 and record["coverage"]["complete"] is True
    # the verdicts of the Assessment are those `rescore_log` gives on the kept log
    schema = json.loads((CHINOOK / "schemas" / "table-answer.schema.json").read_text())
    references = {r["case_id"]: r for r in read_jsonl(REFERENCES)}
    for name, attempt in attempts.items():
        (log,) = (folder_of(study, attempt) / "inspect").glob("*.eval")
        expected = [(case, repeat) for case in ("D03", "D05") for repeat in (0, 1)]
        verdicts = rescore.rescore_log(str(log), references, schema=schema, expected=expected, workload=WORKLOAD)
        rows = [r.split(",") for r in (study / again[name]["per_item_ref"]["path"]).read_text().splitlines()[1:]]
        per_item = {(r[0], int(r[1]), r[5]): (r[6], r[7]) for r in rows}
        for verdict in verdicts:
            for criterion in verdict["criteria"]:
                score = "" if criterion["score"] is None else ("true" if criterion["score"] else "false")
                assert per_item[verdict["case_id"], verdict["repeat"], criterion["name"]] == (criterion["state"], score)
    # the patch has no flag, and no such log is a kept trace
    kept = Path(__file__).resolve().parent.parent / "docs" / "handbook" / "traces"
    assert not any(attempts[name]["attempt_id"] in str(p) for name in attempts for p in kept.rglob("*"))


def test_a_difference_in_repeats_or_in_the_requested_model_is_refused_between_recorded_attempts_and_a_declared_factor_lets_it_through(sides, monkeypatch):
    study, attempts, assessments = sides
    patch_model(monkeypatch)
    one = ok(live(study, "verify", "verify-one", repeats=1))
    other_model = ok(live(study, "verify", "verify-model", repeats=2, model="anthropic/claude-other"))
    for candidate, check, factor in ((assess(study, one), "repeats", "repeats"), (assess(study, other_model), "model", "model")):
        before = snapshot(study)
        code, payload, _ = compare(study, assessments["plain"], candidate)
        assert code == EXIT_INTEGRITY_REFUSED and payload["error"]["code"] == REFUSALS[check][0]
        assert snapshot(study) == before
        code, payload, _ = compare(study, assessments["plain"], candidate, "--factor", factor)
        assert code == 0, payload
        assert payload["comparison"]["declared_factor"] == factor
        assert next(c for c in payload["comparison"]["comparability"]["checks"] if c["check"] == check) == {"check": check, "passed": True, "reason": "declared_factor"}
