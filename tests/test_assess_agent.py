"""Ticket #68: `assess --scorer chinook_contract_v1` scores an imported Observation set and writes an agent Assessment."""

import csv
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from _assess_helpers import snapshot
from _chinook_helpers import (
    FIXTURE,
    FIXTURE_CASES,
    chinook_examples,
    episodes_file,
    fixture_lines,
    fixture_population,
    import_agent,
    init_chinook,
    references_id,
    spec_of,
    write_lines,
)
from _study_helpers import EXAMPLES, run_json, sha256

from hypotrail.core import canonical, contracts, scorers
from hypotrail.core.chinook_contract import CRITERIA, SCORER_VERSION
from hypotrail.core.errors import EXIT_INVALID_INPUT

SCORER = "chinook_contract_v1"


def assess(study, observations, references, scorer=SCORER, *more):
    return run_json("assess", "--study", study, "--observations", observations, "--scorer", scorer, "--references", references, *more)


def imported(tmp_path, lines=None, *, keys=None, name="study", request_id="imp"):
    """(study, Observation set ID) of a Chinook Study that imported `lines` (the kit's fixture by default)."""
    study = init_chinook(tmp_path, name=name)[0]
    source = FIXTURE if lines is None else write_lines(tmp_path / f"{name}-answers.jsonl", lines)
    population = fixture_population(tmp_path, f"{name}-population.json") if keys is None else episodes_file(tmp_path, keys, name=f"{name}-population.json")
    code, payload, err = import_agent(study, source, population, request_id)
    assert code == 0, (payload, err)
    folder = Path(study) / "attempts" / payload["attempt"]["attempt_id"]
    return study, json.loads((folder / "observation_set.json").read_text())["observation_set_id"]


def assessed(study, observation_set):
    code, payload, err = assess(study, observation_set, references_id(study))
    assert code == 0, (payload, err)
    return payload["assessment"]


def per_item(study, record):
    with (Path(study) / record["per_item_ref"]["path"]).open(newline="", encoding="utf-8") as handle:
        return {(r["case_id"], int(r["repeat"]), r["criterion"]): r for r in csv.DictReader(handle)}


def detailed(study, record):
    return json.loads((Path(study) / record["detailed_metrics_ref"]["path"]).read_text())


def error_of(payload):
    error = payload["error"]
    assert set(error) == {"code", "message", "stage", "details"}
    return error


def final(**fields):
    answer = {"columns": ["track_count"], "evidence": [], "reason_code": None, "rows": [[3503]], "status": "answered", "unit": "count"}
    return {**answer, **fields}


def line(case_id, answer=None, *, status="produced", **more):
    entry = {"case_id": case_id, "repeat": 0, "observation_status": status, **more}
    if answer is not None:
        entry["final_answer" if isinstance(answer, dict) else "raw_answer"] = answer
    return entry


@pytest.fixture
def fixture_assessment(tmp_path):
    study, observation_set = imported(tmp_path)
    return study, observation_set, assessed(study, observation_set)


# --- AC5: the Scorer's name and version, a state and a Reason for every Episode and Criterion ---------------------------


def test_the_scorer_is_registered_at_version_2_and_the_assessment_records_its_name_and_version(fixture_assessment):
    _, _, record = fixture_assessment
    contracts.validate(record)
    assert SCORER in scorers.REGISTRY and scorers.REGISTRY[SCORER].version == SCORER_VERSION == "2"
    assert record["scorer"] == {"id": SCORER, "version": "2", "config_digest": scorers.REGISTRY[SCORER].config_digest}
    assert record["kind"] == "assessment" and record["schema_version"] == "assessment/1"


def test_every_expected_episode_has_a_state_for_every_criterion_and_a_reason_for_every_non_score(fixture_assessment):
    study, _, record = fixture_assessment
    rows = per_item(study, record)
    assert set(rows) == {(case, 0, criterion) for case in FIXTURE_CASES for criterion in CRITERIA}
    for row in rows.values():
        assert row["state"] in ("scored", "unscored", "errored")
        assert (row["state"] == "scored") == (row["score"] != "")
        if row["state"] != "scored":
            assert row["reason"]
    # the kit's answers carry no trace: the evidence link is unscored with its Reason
    assert {(r["state"], r["reason"]) for (c, _, k), r in rows.items() if k == "evidence_link_valid"} == {("unscored", "trace_missing")}


def test_an_answer_without_a_trace_has_its_content_scored_and_its_evidence_link_unscored(fixture_assessment):
    study, _, record = fixture_assessment
    rows = per_item(study, record)
    for case in ("D01", "D03"):
        assert (rows[case, 0, "exact_table"]["score"], rows[case, 0, "format_valid"]["score"]) == ("true", "true")
        assert (rows[case, 0, "evidence_link_valid"]["state"], rows[case, 0, "evidence_link_valid"]["reason"]) == ("unscored", "trace_missing")
        # the Scorer's existing rule: no dependency is false, so the primary Criterion is unscored too
        assert (rows[case, 0, "contract_success"]["state"], rows[case, 0, "contract_success"]["reason"]) == ("unscored", "trace_missing")
    for case in ("D07", "D08"):  # needs_clarification / not_answerable: no tool call is required
        assert rows[case, 0, "contract_success"]["score"] == "true"


def test_no_trace_is_generated_from_a_correct_result(tmp_path, fixture_assessment):
    study, observation_set, _ = fixture_assessment
    attempt = next((Path(study) / "attempts").iterdir())
    kept = [json.loads(text) for text in (attempt / "observations.jsonl").read_text().splitlines()]
    assert all(entry["trace"] is None for entry in kept)
    assert "tool_call" not in (attempt / "observations.jsonl").read_text()


# --- Tightened K2 (AC6): the primary Criterion, the counters and the two rates -----------------------------------------------


def test_the_envelope_names_contract_success_as_primary_and_holds_its_counters_and_its_two_rates(fixture_assessment):
    _, _, record = fixture_assessment
    assert record["primary_criterion"] == "contract_success"
    assert record["counts"] == {
        "expected": 4, "attempted": 4, "produced": 4, "scored": 2, "correct": 2, "incorrect": 0, "unscored": 2, "errored": 0,
    }
    quality, share = record["metrics"]
    assert (quality["id"], quality["value"], quality["denominator"], quality["status"]) == ("quality_among_scored", 1.0, 2, "scored")
    assert (share["id"], share["value"], share["denominator"], share["status"]) == ("confirmed_share_of_expected", 0.5, 4, "scored")
    assert {m["direction"] for m in record["metrics"]} == {"higher_is_better"}


def test_the_unknowns_are_shown_beside_the_rates_and_the_second_rate_does_not_call_them_incorrect(fixture_assessment):
    _, _, record = fixture_assessment
    assert record["unknowns"] == {"unscored": 2, "errored": 0, "reasons": {"trace_missing": 2}}
    assert record["counts"]["incorrect"] == 0  # D01 and D03 are unscored, not incorrect


def test_the_secondary_criteria_are_kept_apart_each_with_its_counters_and_its_two_rates(fixture_assessment):
    study, _, record = fixture_assessment
    metrics = detailed(study, record)
    assert set(metrics["criteria"]) == {"exact_table", "format_valid", "evidence_link_valid"}
    assert "contract_success" not in metrics["criteria"]
    exact = metrics["criteria"]["exact_table"]
    assert exact["counts"] == {"expected": 4, "attempted": 4, "produced": 4, "scored": 4, "correct": 4, "incorrect": 0, "unscored": 0, "errored": 0}
    assert [(m["id"], m["value"]) for m in exact["metrics"]] == [("quality_among_scored", 1.0), ("confirmed_share_of_expected", 1.0)]
    evidence = metrics["criteria"]["evidence_link_valid"]
    assert evidence["counts"]["unscored"] == 4 and evidence["counts"]["scored"] == 0
    assert [(m["value"], m["status"], m["reason"]) for m in evidence["metrics"]] == [
        (None, "unscored", "no_scored_episode"), (0.0, "scored", None),
    ]
    ref = record["detailed_metrics_ref"]
    assert ref["sha256"] == sha256(Path(study) / ref["path"]) and ref["role"] == "detailed_metrics"


def test_scored_is_correct_plus_incorrect_for_every_criterion(tmp_path):
    lines = [line("D01", final(rows=[[1]])), line("D03", final(rows=[[1297]]), trace=None), line("D07", status="failed"), line("D08", status="missing")]
    study, observation_set = imported(tmp_path, lines)
    record = assessed(study, observation_set)
    every = [record["counts"], *(c["counts"] for c in detailed(study, record)["criteria"].values())]
    for counts in every:
        assert counts["scored"] == counts["correct"] + counts["incorrect"]
        assert counts["expected"] == 4 and counts["produced"] == 2 and counts["attempted"] == 3


def test_a_zero_denominator_gives_a_null_rate_with_a_reason_never_zero(tmp_path):
    lines = [line(case, status="missing") for case in FIXTURE_CASES]
    study, observation_set = imported(tmp_path, lines)
    record = assessed(study, observation_set)
    quality, share = record["metrics"]
    assert (quality["value"], quality["status"], quality["reason"], quality["denominator"]) == (None, "unscored", "no_scored_episode", 0)
    assert (share["value"], share["status"]) == (0.0, "scored")  # four Episodes were planned: this denominator is not zero
    assert record["counts"]["scored"] == 0 and record["counts"]["unscored"] == 4


def test_a_wrong_table_without_a_trace_is_incorrect_not_unscored_and_a_malformed_answer_too(tmp_path):
    lines = [
        line("D01", final(rows=[[1]])),
        line("D03", '```json\n{"status": "answered"}\n```'),
        line("D07", final(columns=[], rows=[], reason_code="field_not_available", status="not_answerable", unit=None)),
        line("D08", final(columns=[], rows=[], reason_code="field_not_available", status="not_answerable", unit=None)),
    ]
    study, observation_set = imported(tmp_path, lines)
    record = assessed(study, observation_set)
    rows = per_item(study, record)
    assert rows["D01", 0, "contract_success"]["score"] == "false" and rows["D01", 0, "exact_table"]["score"] == "false"
    assert rows["D03", 0, "contract_success"]["score"] == "false" and rows["D03", 0, "format_valid"]["score"] == "false"
    assert rows["D08", 0, "contract_success"]["score"] == "false"  # the wrong status for a question that needs clarification
    assert record["counts"]["incorrect"] == 3 and record["counts"]["correct"] == 1
    assert record["metrics"][0]["value"] == 0.25


def test_an_answer_with_a_valid_trace_is_scored_for_its_evidence_link_too(tmp_path):
    trace = [
        {"kind": "model_turn", "turn": 1, "stop_reason": "tool_calls"},
        {"kind": "tool_call", "native_tool_call_id": "n1", "function": "query_readonly", "arguments": {"sql": "SELECT COUNT(*) FROM Track"}},
        {"kind": "tool_result", "native_tool_call_id": "n1", "app_tool_call_id": "c1", "result": {"tool_call_id": "c1", "rows": [[3503]]}, "tool_error": None},
        {"kind": "model_turn", "turn": 2, "stop_reason": "stop"},
        {"kind": "final_answer", "text": "..."},
    ]
    lines = fixture_lines()
    lines[0] = line("D01", final(evidence=["c1"]), trace=trace)
    lines[1] = line("D03", final(rows=[[1297]], columns=["track_count"], evidence=["unknown-id"]), trace=trace)
    study, observation_set = imported(tmp_path, lines)
    rows = per_item(study, assessed(study, observation_set))
    assert (rows["D01", 0, "evidence_link_valid"]["score"], rows["D01", 0, "contract_success"]["score"]) == ("true", "true")
    assert (rows["D03", 0, "evidence_link_valid"]["reason"], rows["D03", 0, "contract_success"]["score"]) == ("evidence_unknown_id", "false")


def test_a_final_answer_object_is_scored_as_its_canonical_text_and_each_record_says_where_it_was_read_from(tmp_path):
    wrapped = "Here it is:\n" + json.dumps(final())
    lines = [line("D01", json.dumps(final(), sort_keys=True)), line("D03", wrapped), line("D07", status="failed"), line("D08", final(columns=[], rows=[], reason_code="criterion_undefined", status="needs_clarification", unit=None))]
    study, observation_set = imported(tmp_path, lines)
    record = assessed(study, observation_set)
    rows = per_item(study, record)
    assert rows["D01", 0, "exact_table"]["answer_given_as"] == "raw_answer" and rows["D01", 0, "exact_table"]["answer_read_from"] == "raw_answer"
    assert rows["D03", 0, "exact_table"]["answer_read_from"] == "embedded_object"
    assert rows["D03", 0, "format_valid"]["score"] == "false"  # the Scorer's existing rule: a wrapped answer is not a valid format
    assert rows["D08", 0, "exact_table"]["answer_given_as"] == "final_answer" and rows["D08", 0, "exact_table"]["answer_read_from"] == "raw_answer"
    assert rows["D07", 0, "exact_table"]["answer_read_from"] == ""  # no answer: nothing was read


# --- failed and missing Episodes, counted apart (Tightened G) ----------------------------------------------------------------


def test_a_failed_or_missing_episode_is_unscored_with_a_reason_and_counted_apart_from_the_criteria(tmp_path):
    lines = [line("D01", status="failed"), line("D03", status="missing"), *fixture_lines()[2:]]
    study, observation_set = imported(tmp_path, lines)
    record = assessed(study, observation_set)
    rows = per_item(study, record)
    assert {(rows["D01", 0, k]["state"], rows["D01", 0, k]["reason"]) for k in CRITERIA} == {("unscored", "execution_failed")}
    assert {(rows["D03", 0, k]["state"], rows["D03", 0, k]["reason"]) for k in CRITERIA} == {("unscored", "observation_missing")}
    assert record["operational_errors"] == {"failed": 1, "missing": 1}
    assert record["counts"]["attempted"] == 3 and record["counts"]["produced"] == 2
    # an Episode that failed and is unscored appears in both: the operational counts do not replace the Criterion counts
    assert record["counts"]["unscored"] == 2
    assert record["unknowns"]["reasons"] == {"execution_failed": 1, "observation_missing": 1}


def test_a_scoring_crash_is_errored_for_that_episode_only(tmp_path, monkeypatch):
    from hypotrail.agentic import assess as agent_assess
    from hypotrail.core import chinook_contract

    real = chinook_contract.score_episode

    def crash(raw_answer, reference, schema, steps=None):
        if "3503" in raw_answer:
            raise RuntimeError("boom with a secret sk-123")
        return real(raw_answer, reference, schema, steps)

    study, observation_set = imported(tmp_path)
    monkeypatch.setattr(agent_assess, "score_episode", crash)
    record = assessed(study, observation_set)
    rows = per_item(study, record)
    assert {(rows["D01", 0, k]["state"], rows["D01", 0, k]["reason"]) for k in CRITERIA} == {("errored", "scoring_failed")}
    assert rows["D07", 0, "contract_success"]["score"] == "true"
    assert record["counts"]["errored"] == 1
    assert "sk-123" not in json.dumps(record) + (Path(study) / record["per_item_ref"]["path"]).read_text()


def test_a_missing_reference_makes_exact_table_unscored_not_false(tmp_path):
    study, observation_set = imported(tmp_path)
    spec = spec_of(study)
    entry = next(e for e in spec["artifacts"] if e["ref"]["role"] == "references")
    path = Path(study) / entry["ref"]["path"]
    path.write_text("".join(text for text in path.read_text().splitlines(keepends=True) if '"case_id": "D01"' not in text))
    entry["ref"]["sha256"], entry["ref"]["size_bytes"] = sha256(path), path.stat().st_size
    (Path(study) / "study.json").write_bytes(canonical.dumps(spec))
    rows = per_item(study, assessed(study, observation_set))
    assert (rows["D01", 0, "exact_table"]["state"], rows["D01", 0, "exact_table"]["reason"]) == ("unscored", "reference_missing")


# --- the records a second Assessment leaves alone ------------------------------------------------------------------------------


def test_another_assessment_of_the_same_observations_never_changes_an_earlier_one(fixture_assessment):
    study, observation_set, first = fixture_assessment
    before = snapshot(Path(study) / "assessments" / first["assessment_id"])
    second = assessed(study, observation_set)
    assert second["assessment_id"] != first["assessment_id"] and second["observation_set_id"] == first["observation_set_id"]
    assert snapshot(Path(study) / "assessments" / first["assessment_id"]) == before


def test_the_assessment_layout_is_the_three_files_and_assessment_json_is_written_last(fixture_assessment):
    study, _, record = fixture_assessment
    folder = Path(study) / "assessments" / record["assessment_id"]
    assert sorted(p.name for p in folder.iterdir()) == ["assessment.json", "metrics.json", "per_item.csv"]
    assert canonical.loads((folder / "assessment.json").read_bytes()) == record


# --- AC7: public_check ---------------------------------------------------------------------------------------------------------


def test_an_assessment_of_public_check_items_is_an_exposure_and_writes_its_journal_entry(tmp_path):
    # #73 lifted the refusal inside a Study; tests/test_exposure.py holds the rest of the rules
    keys = [("E01", 0), ("E11", 0)]
    study, observation_set = imported(tmp_path, [line(c, status="missing") for c, _ in keys], keys=keys)
    code, payload, err = assess(study, observation_set, references_id(study))
    assert code == 0, (payload, err)
    (entry,) = [json.loads(p.read_text()) for p in (Path(study) / "exposures").glob("*.json")]
    assert entry["assessment_ids"] == [payload["assessment"]["assessment_id"]]


# --- refusals of the registry and of the Study ----------------------------------------------------------------------------------


def test_a_regression_scorer_on_agent_answers_and_the_agent_scorer_on_predictions_are_unsupported(tmp_path, fixture_assessment):
    from _assess_helpers import fresh_study, observation_set_id
    from _assess_helpers import references_id as bike_references

    study, observation_set, _ = fixture_assessment
    code, payload, _ = assess(study, observation_set, references_id(study), "regression_mae_v1")
    assert (code, error_of(payload)["code"]) == (EXIT_INVALID_INPUT, "UNSUPPORTED_CAPABILITY")
    bike, attempts = fresh_study(tmp_path / "bike", "seasonal_7")
    code, payload, _ = assess(bike, observation_set_id(bike, attempts["seasonal_7"]), bike_references(bike))
    assert (code, error_of(payload)["code"]) == (EXIT_INVALID_INPUT, "UNSUPPORTED_CAPABILITY")


def test_an_unknown_observation_set_or_references_id_is_refused(fixture_assessment):
    study, observation_set, _ = fixture_assessment
    code, payload, _ = assess(study, "nope", references_id(study))
    assert (code, error_of(payload)["code"]) == (2, "OBSERVATION_SET_NOT_FOUND")
    code, payload, _ = assess(study, observation_set, "nope")
    assert (code, error_of(payload)["code"]) == (2, "REFERENCES_NOT_FOUND")


def test_a_kept_artifact_that_changed_is_an_integrity_refusal(fixture_assessment):
    study, observation_set, _ = fixture_assessment
    attempt = next((Path(study) / "attempts").iterdir())
    kept = attempt / "source" / FIXTURE.name
    kept.write_bytes(kept.read_bytes() + b"\n")
    before = snapshot(study)
    code, payload, _ = assess(study, observation_set, references_id(study))
    assert (code, error_of(payload)["code"]) == (3, "ARTIFACT_INTEGRITY")
    assert snapshot(study) == before


# --- Tightened J and AC8: --json, and nothing outside the Study is used --------------------------------------------------------


def test_the_human_line_names_the_primary_criterion_and_its_counters(tmp_path):
    from _study_helpers import run_cli

    study, observation_set = imported(tmp_path)
    code, out, err = run_cli("assess", "--study", study, "--observations", observation_set, "--scorer", SCORER, "--references", references_id(study))
    assert code == 0 and "contract_success" in out and "2 correct of 4 expected Episodes" in out and err == ""


_AC7_CHILD = textwrap.dedent(
    r"""
    import builtins, io, json, os, pathlib, socket, sqlite3, sys
    BLOCKED = ("inspect_ai", "sklearn", "numpy", "scipy", "pandas", "anthropic", "openai")
    for name in BLOCKED:
        sys.modules[name] = None
    a = sys.argv[1:]
    mode = a[4]
    targets = {(pathlib.Path(a[3]) / "chinook/data/Chinook_Sqlite.sqlite").resolve(), pathlib.Path(a[5]).resolve()}
    assert all(t.exists() for t in targets), targets
    used, net = [], []
    def is_target(f):
        if isinstance(f, int): return False
        try: return pathlib.Path(os.fsdecode(f).removeprefix("file:").split("?")[0]).resolve() in targets
        except (TypeError, ValueError): return False
    class Used(BaseException): pass
    def guarded(name, real):
        def w(f, *x, **k):
            if is_target(f):
                used.append(name); raise Used(name)
            return real(f, *x, **k)
        return w
    io.open = guarded("io.open", io.open); builtins.open = guarded("open", builtins.open)
    os.open = guarded("os.open", os.open); sqlite3.connect = guarded("sqlite3.connect", sqlite3.connect)
    def blocked(name):
        def b(*x, **k):
            net.append(name); raise OSError("network " + name)
        return b
    socket.socket.connect = blocked("connect"); socket.socket.connect_ex = blocked("connect_ex"); socket.getaddrinfo = blocked("getaddrinfo")
    from hypotrail import cli
    assert cli.main(["import", "agent", "--study", a[0], "--source", a[1], "--population", a[2], "--request-id", "x", "--examples-dir", a[3], "--json"]) == 0
    folder = next((pathlib.Path(a[0]) / "attempts").iterdir())
    osid = json.loads((folder / "observation_set.json").read_text())["observation_set_id"]
    spec = json.loads((pathlib.Path(a[0]) / "study.json").read_text())
    ref = next(e["artifact_id"] for e in spec["artifacts"] if e["ref"]["role"] == "references")
    extra = [] if mode == "default-examples" else ["--examples-dir", a[3]]
    assert cli.main(["assess", "--study", a[0], "--observations", osid, "--scorer", "chinook_contract_v1", "--references", ref, "--json", *extra]) == 0
    loaded = sorted(m for m in sys.modules if sys.modules[m] is not None and m.split(".")[0] in BLOCKED)
    agentic = sorted(m for m in sys.modules if m in ("hypotrail.agentic.sql_tool", "hypotrail.agentic.runner", "hypotrail.agentic.projection", "hypotrail.agentic.live"))
    print("LOADED", loaded, agentic, used, net)
    """
)


@pytest.mark.parametrize("mode", ["with-examples", "default-examples"])
def test_ac7_import_agent_and_assess_succeed_with_every_condition_at_once(tmp_path, mode):
    """#68 AC7 (R4-02, R5-01): in a fresh interpreter Inspect and the providers are not importable, the network is patched
    (a child does not inherit the conftest guard) and every use (`open`, `io.open`, `os.open`, `sqlite3.connect`) of the
    Study-side and of the repository's Chinook file raises, both files being present through `import agent` and `assess`.
    Both succeed, load no blocked module and none of the model or tool modules, and record zero uses and zero network attempts."""
    examples = chinook_examples(tmp_path)
    study = init_chinook(tmp_path, examples=examples)[0]
    population = fixture_population(tmp_path)
    repository_file = EXAMPLES / "chinook" / "data" / "Chinook_Sqlite.sqlite"
    args = [str(study), str(FIXTURE), str(population), str(examples), mode, str(repository_file)]
    done = subprocess.run([sys.executable, "-c", _AC7_CHILD, *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "LOADED [] [] [] []" in done.stdout


def test_assess_writes_nothing_outside_the_study_and_reads_no_network(tmp_path, fixture_assessment, network_guard):
    study, observation_set, _ = fixture_assessment
    before = {p for p in tmp_path.rglob("*") if p.is_file() and Path(study) not in p.parents}
    assessed(study, observation_set)
    assert {p for p in tmp_path.rglob("*") if p.is_file() and Path(study) not in p.parents} == before
    assert network_guard.attempts == []
