"""Ticket #86: `report` renders a Study of the tool-using agent Track (Chinook).

The tests of #85 that hold for both Tracks are in `tests/test_report.py`, parametrised over `TRACKS`. These are the
criteria and Tightened lines that only the agent Track has. One test per criterion; a criterion that states several
conditions is one test holding all of them.
"""

import csv
import glob
import json
import re
import shutil
from pathlib import Path
from urllib.parse import unquote

import pytest
from _agent_compare_helpers import answer_lines, imported, keys_of
from _agent_compare_helpers import assess as assess_agent
from _agent_compare_helpers import compare as compare_agent
from _agent_compare_helpers import observation_set_of
from _chinook_helpers import FIXTURE_CASES, chinook_examples, episodes_file, import_agent, init_chinook, write_lines
from _report_helpers import doc_of, edit_manifest, journal_of, lines_of, report, sha_of
from _report_tracks import TRACKS
from _run_agent_helpers import fixture, live, ok, patch_model, study_of
from _study_helpers import ROOT

from hypotrail.core.chinook_contract import CRITERIA

CHINOOK = TRACKS["chinook"]
KEPT = ROOT / "docs" / "handbook" / "traces" / "run-agent-live-plain"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """The Chinook world of `test_report.py`: two native Attempts, an Import, their Assessments and Comparisons, and the page."""
    base = tmp_path_factory.mktemp("agent-world")
    study, facts = CHINOOK.world(base)
    out = base / "elsewhere" / "report.html"
    out.parent.mkdir()
    code, payload, err = report(study, out)
    assert code == 0, (payload, err)
    return study, facts, out, doc_of(out)


def per_item_of(study, assessment_id) -> list:
    record = json.loads((Path(study) / "assessments" / assessment_id / "assessment.json").read_text())
    with (Path(study) / record["per_item_ref"]["path"]).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def entries_of(study, attempt) -> dict:
    """{(case_id, repeat): the Episode's normalized Observation} of an Attempt."""
    path = Path(study) / "attempts" / attempt["attempt_id"] / "observations.jsonl"
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {(e["case_id"], e["repeat"]): e for e in lines}


def assessment_of(study, assessment_id) -> dict:
    return json.loads((Path(study) / "assessments" / assessment_id / "assessment.json").read_text())


def attempt_of(study, assessment_id) -> dict:
    observation_set = assessment_of(study, assessment_id)["observation_set_id"]
    for path in (Path(study) / "attempts").glob("*/observation_set.json"):
        if json.loads(path.read_text())["observation_set_id"] == observation_set:
            return json.loads((path.parent / "attempt.json").read_text())
    raise AssertionError(observation_set)


def trace_ref_of(study, attempt):
    """(ref, label) of the one artifact an Episode's trace is read from: the Inspect log, else the import source."""
    folder = Path(study) / "attempts" / attempt["attempt_id"]
    record = json.loads((folder / "observation_set.json").read_text())
    for ref in record["raw_refs"]:
        if ref["path"].endswith(".eval"):
            return ref, "Trace"
    return record["raw_refs"][0], "Trace in the import source"


def expected_cell(study, attempt, row_set, case, repeat) -> list:
    """The lines a matrix cell holds, written from the records alone (the per-Item file, the Observations, the references)."""
    entry = entries_of(study, attempt).get((case, repeat))
    rows = [r for r in row_set if r["case_id"] == case and int(r["repeat"]) == repeat]
    status = rows[0]["execution_status"]
    lines = [f"Case {case}, Repeat {repeat}"]
    if status == "produced":
        lines.append("Execution: produced")
    else:
        lines.append(f"Execution: {status} (Reason: {(entry or {}).get('reason') or 'unknown'})")
    if status == "produced" and rows[0]["answer_given_as"]:
        read = rows[0]["answer_read_from"]
        lines.append("Answer read from: " + {"raw_answer": "raw_answer", "embedded_object": "embedded_object (Wrapped answer)", "": "nothing read"}[read])
    for name in CRITERIA:
        row = next(r for r in rows if r["criterion"] == name)
        if row["state"] == "scored":
            text = row["score"] + (f" (Reason: {row['reason']})" if row["reason"] else "")
        else:
            text = f"{row['state']} (Reason: {row['reason']}), Instrument failure"
        lines.append(f"{name}: {text}")
    if entry is not None and isinstance(entry.get("trace"), list):
        ref, label = trace_ref_of(study, attempt)
        lines.append(f"{label}: {ref['path']}, SHA-256 {ref['sha256']}")
    else:
        lines.append("Trace: trace absent")
    return lines


def check_matrix(study, out, doc, assessment_id):
    """The matrix of `assessment_id`: one row per Case, one column per Repeat, each cell as the records say; returns the cells found."""
    rows = per_item_of(study, assessment_id)
    attempt = attempt_of(study, assessment_id)
    table = doc.tables[f"matrix-{assessment_id}"]
    cases = sorted({r["case_id"] for r in rows})
    repeats = sorted({int(r["repeat"]) for r in rows})
    assert [c["text"] for c in table[0]] == ["Case", *[f"Repeat {n}" for n in repeats]]
    assert [row[0]["text"] for row in table[1:]] == cases
    found = {}
    for row in table[1:]:
        for repeat, cell in zip(repeats, row[1:]):
            assert lines_of(cell) == expected_cell(study, attempt, rows, row[0]["text"], repeat), (row[0]["text"], repeat)
            for href in cell["links"]:
                target = (out.parent / unquote(href)).resolve()  # the link resolves, from the folder of --out, to the artifact the cell names
                assert target.is_file() and target.is_relative_to(Path(study).resolve()) and sha_of(target) in " ".join(lines_of(cell))
            found[(row[0]["text"], repeat)] = cell
    return found


# --- C2: the matrix ---------------------------------------------------------------------------------------------------


def test_each_assessment_shows_a_matrix_one_row_per_case_one_column_per_repeat_each_cell_with_its_statuses_and_a_link_to_its_trace(world):
    study, facts, out, doc = world
    cells = 0
    for assessment_id in [*facts["assessments"].values(), facts["import_assessment"]]:
        cells += len(check_matrix(study, out, doc, assessment_id))
    assert cells == 3 * len(FIXTURE_CASES) * CHINOOK.repeats
    native = check_matrix(study, out, doc, facts["assessments"]["plain"])
    log = Path(next(r["path"] for r in facts["attempts"]["plain"]["output_refs"] if r["role"] == "inspect_log"))
    assert all(cell["links"] and unquote(cell["links"][0]).endswith(log.name) for cell in native.values())  # a native Attempt links its Inspect log
    imported_cells = check_matrix(study, out, doc, facts["import_assessment"])
    source = next(r for r in facts["import"]["input_refs"] if r["role"] == "import_source")
    assert all(unquote(c["links"][0]).endswith(Path(source["path"]).name) for c in imported_cells.values())  # an Import's steps are in its source


def test_an_import_with_no_trace_says_trace_absent_and_an_instrument_failure_is_shown_apart_from_a_format_failure_of_the_system(tmp_path):
    """T17 (SPEC §10)."""
    study, _ = init_chinook(tmp_path)
    lines = answer_lines(repeats=1, traced=False, failed={("D07", 0)})
    by_case = {line["case_id"]: line for line in lines}
    by_case["D08"].pop("final_answer")  # a produced answer that is not a table at all: a format failure of the system
    by_case["D08"]["raw_answer"] = "I could not find out."
    by_case["D03"].clear()  # an Episode the producer never ran
    by_case["D03"].update(case_id="D03", repeat=0, origin="agent_output", observation_status="missing")
    code, payload, err = import_agent(study, write_lines(tmp_path / "answers.jsonl", lines), episodes_file(tmp_path, keys_of(1)), "no-trace")
    assert code == 0, (payload, err)
    assessment = assess_agent(study, observation_set_of(study, payload["attempt"]))
    out = tmp_path / "page.html"
    assert report(study, out)[0] == 0
    doc = doc_of(out)
    cells = check_matrix(study, out, doc, assessment["assessment_id"])
    rows = per_item_of(study, assessment["assessment_id"])
    assert all(lines_of(c)[-1] == "Trace: trace absent" and not c["links"] for c in cells.values())
    instrument = {r["reason"] for r in rows if r["state"] == "unscored"}
    assert instrument >= {"trace_missing", "execution_failed", "observation_missing"}
    system = {r["reason"] for r in rows if r["state"] == "scored" and r["score"] == "false" and r["reason"]}
    assert system == {"invalid_response_format"}
    line_of = lambda case, name: next(line for line in lines_of(cells[(case, 0)]) if line.startswith(f"{name}:"))  # noqa: E731
    assert line_of("D01", "evidence_link_valid") == "evidence_link_valid: unscored (Reason: trace_missing), Instrument failure"
    assert line_of("D08", "format_valid") == "format_valid: false (Reason: invalid_response_format)"
    assert "Execution: failed (Reason: unknown)" in lines_of(cells[("D07", 0)]) and "Execution: missing (Reason: unknown)" in lines_of(cells[("D03", 0)])
    counted = {row[0]: row for row in doc.body("attempts")}[payload["attempt"]["attempt_id"]]
    assert counted[5:8] == ["2", "1", "1"]  # produced, failed, missing: the Observation set's counts, as the manifest records them


def test_the_kept_live_log_imported_and_assessed_renders_d03_and_d05_as_wrapped_answers_with_their_reasons(tmp_path):
    study, _ = init_chinook(tmp_path)
    log = glob.glob(str(KEPT / "inspect" / "*.eval"))[0]
    code, payload, err = import_agent(study, log, episodes_file(tmp_path, [("D03", 0), ("D05", 0)]), "kept")
    assert code == 0, (payload, err)
    assessment = assess_agent(study, observation_set_of(study, payload["attempt"]))
    out = tmp_path / "page.html"
    assert report(study, out)[0] == 0
    doc = doc_of(out)
    cells = check_matrix(study, out, doc, assessment["assessment_id"])
    assert sorted(cells) == [("D03", 0), ("D05", 0)]
    for cell in cells.values():
        lines = lines_of(cell)
        assert "Answer read from: embedded_object (Wrapped answer)" in lines
        assert "exact_table: true" in lines and "format_valid: false (Reason: invalid_response_format)" in lines
        assert "contract_success: false (Reason: invalid_response_format)" in lines
        source = next(r for r in payload["attempt"]["input_refs"] if r["role"] == "import_source")
        assert f"Trace: {source['path']}, SHA-256 {source['sha256']}" in lines  # the kept Inspect log is the trace, linked and never read


# --- C3: counters and the two named rates -----------------------------------------------------------------------------


RATES = ("Quality among the scored (N_correct / N_scored)", "Share of the planned Episodes with a confirmed success (N_correct / N_expected)")


def rate_text(metric) -> str:
    return f"{float(f'{metric['value']:.6g}'):g}" if metric["value"] is not None else f"null (Reason: {metric['reason']})"


def check_criteria(study, doc, assessment_id) -> dict:
    record = assessment_of(study, assessment_id)
    detailed = json.loads((Path(study) / record["detailed_metrics_ref"]["path"]).read_text())
    rows = per_item_of(study, assessment_id)
    table = doc.tables[f"criteria-{assessment_id}"]
    keys = ["expected", "attempted", "produced", "scored", "correct", "incorrect", "unscored", "errored"]
    assert [c["text"] for c in table[0]] == ["Criterion", *[f"N_{k}" for k in keys], *RATES, "Unknowns"]
    shown = {row[0]["text"]: [c["text"] for c in row[1:]] for row in table[1:]}
    assert list(shown) == list(CRITERIA)
    for name in CRITERIA:
        source = {"counts": record["counts"], "metrics": record["metrics"]} if name == record["primary_criterion"] else detailed["criteria"][name]
        counts, rates = source["counts"], {m["id"]: m for m in source["metrics"]}
        why = {}
        for r in rows:
            if r["criterion"] == name and r["state"] != "scored":
                why[r["reason"]] = why.get(r["reason"], 0) + 1
        unknowns = f"unscored {counts['unscored']}, errored {counts['errored']}" + ("; reasons: " + ", ".join(f"{k} {v}" for k, v in sorted(why.items())) if why else "")
        assert shown[name] == [*[str(counts[k]) for k in keys], rate_text(rates["quality_among_scored"]), rate_text(rates["confirmed_share_of_expected"]), unknowns], name
    return shown


def test_each_agent_assessment_shows_per_criterion_its_counters_the_two_named_rates_and_the_unknowns_and_a_zero_denominator_is_null_with_its_reason(world, tmp_path):
    study, facts, _, doc = world
    for assessment_id in [*facts["assessments"].values(), facts["import_assessment"]]:
        check_criteria(study, doc, assessment_id)
    # a Study where nothing was scored: every Episode failed, so the quality among the scored has a zero denominator
    alone, _ = init_chinook(tmp_path)
    failed = answer_lines(repeats=1, failed={(c, 0) for c in FIXTURE_CASES}, traced=False)
    _, assessment = imported(tmp_path, alone, "failed", failed, repeats=1)
    out = tmp_path / "page.html"
    assert report(alone, out)[0] == 0
    shown = check_criteria(alone, doc_of(out), assessment["assessment_id"])
    primary = shown["contract_success"]
    assert primary[3] == "0" and primary[4] == "0" and primary[8] == "null (Reason: no_scored_episode)" and primary[9] == "0"
    assert "execution_failed" in primary[10]
    assert "unknown" not in primary[8] and not re.search(r"\bnan\b", doc_of(out).text, re.I)


# --- C4: Comparisons --------------------------------------------------------------------------------------------------


def comparison_tables(doc, count):
    return [{r[0]: r[1] for r in doc.body(f"comparison-{i}")} for i in range(count)]


def test_an_agent_comparison_shows_its_deltas_coverage_and_comparability_as_recorded_aggregated_by_case_first(world):
    study, facts, out, doc = world
    tables = comparison_tables(doc, 2)
    native = next(t for t in tables if t["Candidate Assessment"] == facts["assessments"]["verify"])
    descriptive = next(t for t in tables if t["Candidate Assessment"] == facts["import_assessment"])
    record = facts["comparison"]
    assert native["Control Assessment"] == facts["assessments"]["plain"] and native["Comparability"] == "compatible, with warning COMPARISON_ORDER_NOT_ALTERNATED"
    coverage = record["coverage"]
    assert native["Coverage"] == f"expected {coverage['expected']}, Control scored {coverage['control_scored']}, Candidate scored {coverage['candidate_scored']}, paired {coverage['paired']}"
    assert native["Coverage rates"] == f"Control {coverage['control_rate']:.6g}, Candidate {coverage['candidate_rate']:.6g}"
    delta = record["delta"]
    assert native["Delta"] == f"{delta['metric']} {float(f'{delta['value']:.6g}'):g} {delta['unit']}"
    assert native["Delta definition"] == delta["definition"] and "positive means the Candidate is better" in native["Delta definition"]
    assert "A positive delta means the Candidate is worse" not in doc.text  # the Bike sentence is for a loss; this Criterion is higher-is-better
    index = tables.index(native)
    # aggregated by Case first, as the record holds it: one row per Case, from the paired-deltas file
    shown = doc.body(f"comparison-cases-{index}")
    with (study / record["paired_deltas_ref"]["path"]).open(newline="", encoding="utf-8") as handle:
        recorded = list(csv.DictReader(handle))
    assert [r[0] for r in shown] == [r["case_id"] for r in recorded] and len(shown) == len(FIXTURE_CASES)
    for row, r in zip(shown, recorded):
        assert row[1:] == [r["repeats"], *[f"{float(r[k]):.6g}" for k in ("control_share", "candidate_share", "delta_share")]]
    secondary = {r[0]: r[1] for r in doc.body(f"comparison-secondary-{index}")}
    assert set(secondary) == {d["metric"] for d in record["secondary_deltas"]}
    assert descriptive["Comparability"] == "descriptive_only (descriptive)"
    warning = facts["descriptive"]["warnings"][0]
    assert f"Warning {warning['code']}." in doc.text and warning["message"] in doc.text
    # the numbers are those the record holds, not recomputed: an edited record is shown as edited
    path = study / "comparisons" / record["comparison_id"] / "comparison.json"
    original = path.read_bytes()
    from hypotrail.core import canonical

    path.write_bytes(canonical.dumps({**record, "coverage": {**coverage, "paired": 3, "control_rate": 0.25}, "delta": {**delta, "value": 0.125}}))
    try:
        edited = out.parent / "edited.html"
        assert report(study, edited)[0] == 0
        shown_tables = comparison_tables(doc_of(edited), 2)
        changed = next(t for t in shown_tables if t["Candidate Assessment"] == facts["assessments"]["verify"])
        assert "paired 3" in changed["Coverage"] and changed["Delta"].split()[1] == "0.125" and "Control 0.25" in changed["Coverage rates"]
    finally:
        path.write_bytes(original)


def test_the_comparability_cell_of_a_comparison_that_holds_the_order_warning_names_its_code_beside_the_status(world):
    study, facts, out, doc = world
    record = facts["comparison"]  # `plain` then `verify`, two native Attempts run one after the other
    assert record["comparability"]["status"] == "compatible" and "COMPARISON_ORDER_NOT_ALTERNATED" in [w["code"] for w in record["warnings"]]
    native = next(t for t in comparison_tables(doc, 2) if t["Candidate Assessment"] == facts["assessments"]["verify"])
    cell = native["Comparability"]
    assert cell.startswith("compatible") and "COMPARISON_ORDER_NOT_ALTERNATED" in cell, cell


def test_the_comparability_cell_of_a_comparison_that_holds_the_declared_deviation_warning_names_its_code_beside_the_status(world, tmp_path):
    from _deviation_helpers import CODE, comparability_cells, compare_ids, declare, rendered

    source, facts, _, _ = world
    study = tmp_path / "copy"
    shutil.copytree(source, study)  # the module's Study stays without a Declared deviation
    declare(study, [facts["attempts"]["plain"]["attempt_id"]])
    record = compare_ids(study, facts["assessments"]["plain"], facts["assessments"]["verify"])
    assert record["comparability"]["status"] == "compatible" and CODE in [w["code"] for w in record["warnings"]]
    rendered(study, tmp_path / "page.html")
    cell = comparability_cells(tmp_path / "page.html")[record["comparison_id"]]
    assert cell.startswith("compatible") and CODE in cell, cell


def test_the_page_shows_the_warning_a_comparison_recorded_and_nothing_computed_from_a_declaration_or_its_withdrawal(tmp_path):
    from _deviation_helpers import chinook_world, the_report_shows_what_each_comparison_recorded_and_computes_nothing_from_the_declared_deviations

    world = chinook_world(tmp_path, count=2)
    (tmp_path / "out").mkdir()
    the_report_shows_what_each_comparison_recorded_and_computes_nothing_from_the_declared_deviations(world, tmp_path / "out")


def test_C_when_the_record_withholds_the_main_delta_the_page_shows_only_withheld_with_the_coverage_rates_and_no_bounds(tmp_path):
    study, _ = init_chinook(tmp_path)
    with pytest.MonkeyPatch.context() as mp:
        patch_model(mp)
        native = ok(live(study, "plain", "native", cases=FIXTURE_CASES, repeats=1))
    control = assess_agent(study, observation_set_of(study, native))
    broken = answer_lines(repeats=1, model=None, tool_use=None, mode=None, failed={("D01", 0), ("D03", 0)})
    _, candidate = imported(tmp_path, study, "broken", broken, repeats=1)
    code, payload, err = compare_agent(study, control, candidate)
    assert code == 0, (payload, err)
    record = payload["comparison"]
    assert record["delta"]["value"] is None and record["paired_deltas_ref"] is None  # the record withholds the main delta
    out = tmp_path / "page.html"
    assert report(study, out)[0] == 0
    doc = doc_of(out)
    table = comparison_tables(doc, 1)[0]
    assert table["Delta"] == "withheld"
    assert table["Coverage rates"] == f"Control {record['coverage']['control_rate']:.6g}, Candidate {record['coverage']['candidate_rate']:.6g}"
    assert {r[1] for r in doc.body("comparison-secondary-0")} == {"withheld"}
    assert "comparison-cases-0" not in doc.tables
    card = " ".join(" ".join(c["text"] for c in row) for row in doc.tables["comparison-0"])
    assert not re.search(r"bound|interval|confidence|coverage_incomplete", card, re.I)


# --- C5: the banner, scenarios ----------------------------------------------------------------------------------------


def scenario_study(tmp_path, *, examples=None, with_import=True):
    study, _ = init_chinook(tmp_path, examples=examples)
    with pytest.MonkeyPatch.context() as mp:
        patch_model(mp)
        more = ["--examples-dir", examples] if examples is not None else []
        scenario = ok(fixture(study, "plain", "scenarios", *more))
    imported_attempt = None
    if with_import:
        imported_attempt, _ = imported(tmp_path, study, "other", answer_lines(repeats=1, model=None, tool_use=None, mode=None), repeats=1)
    return study, scenario, imported_attempt


HITS = re.compile(r"LLM|llm_live|model answer", re.I)


def scenario_hits(text) -> list:
    """What names an LLM in the text of the scenario Attempt's part of the page, the banner and the recorded model removed."""
    from hypotrail.agentic import fixture as library

    return HITS.findall(text.replace(library.BANNER, " ").replace("mockllm/model", " "))


def test_E_the_banner_is_first_names_the_scenario_attempts_by_id_and_not_an_import_and_B_nothing_of_the_scenarios_part_names_an_llm(tmp_path):
    from hypotrail.agentic import fixture as library

    study, scenario, other = scenario_study(tmp_path)
    out = tmp_path / "page.html"
    code, payload, err = report(study, out)
    assert code == 0, (payload, err)
    raw, doc = out.read_text(encoding="utf-8"), doc_of(out)
    head = raw[: raw.index("<section")]  # the banner is at the top, before the first section
    assert library.BANNER in head and scenario["attempt_id"] in head and other["attempt_id"] not in head
    # B: the scenario Attempt's part, element by element, holds no LLM, no llm_live and no model answer
    part = doc.scope_text(scenario["attempt_id"])
    assert scenario["attempt_id"] in part and "scripted_fixture" in part and "not an Assessment" in part
    assert scenario_hits(part) == []
    assert doc.body(f"selfcheck-{scenario['attempt_id']}") and doc.body(f"selfcheck-counts-{scenario['attempt_id']}") and doc.body(f"answers-{scenario['attempt_id']}")
    marked = {attrs["data-attempt-id"] for _, attrs in doc.elements if attrs.get("data-attempt-id")}
    assert marked == {scenario["attempt_id"]}  # nothing else on the page is marked as the scenario's, nor is the Import
    # the scan has teeth: a heading "Model answers" over the self-check is found, and a page without a scenario has no banner
    assert scenario_hits(part + " Model answers") == ["Model answer"]
    plain, _ = init_chinook(tmp_path, name="no-scenario")
    imported(tmp_path, plain, "x", answer_lines(repeats=1, model=None, tool_use=None, mode=None), repeats=1)
    assert report(plain, tmp_path / "p.html")[0] == 0 and library.BANNER not in (tmp_path / "p.html").read_text(encoding="utf-8")


def test_F_no_page_the_suite_renders_states_a_milestone_status(world):
    from _report_helpers import assert_no_milestone_status

    _, _, out, _ = world
    assert_no_milestone_status(out.read_text(encoding="utf-8"))
    for stated in ("<p>LIVE_ACCEPTED</p>", "<p>The live acceptance is pending.</p>"):
        with pytest.raises(AssertionError):
            assert_no_milestone_status(out.read_text(encoding="utf-8") + stated)  # the guard `report()` applies to every page has teeth


# --- C6: markup in an agent answer ------------------------------------------------------------------------------------


SCENARIO_MARKUP = '</td><script>alert(1)</script><img src=x onerror=alert(1)> "><xx-marker>m</xx-marker> & done'


def test_T22_markup_in_a_scenarios_final_answer_is_shown_as_the_same_characters_and_the_rest_of_the_page_is_intact(tmp_path):
    examples = chinook_examples(tmp_path)
    path = examples / "chinook" / "fixtures" / "scenarios.json"
    scenarios = json.loads(path.read_text(encoding="utf-8"))
    target = next(s for s in scenarios["scenarios"] if s["scenario_id"] == "invalid_format")
    target["script"] = [target["script"][0], {"raw_answer": SCENARIO_MARKUP}]
    path.write_text(json.dumps(scenarios, indent=2), encoding="utf-8")
    study, scenario, _ = scenario_study(tmp_path, examples=examples, with_import=False)
    out = tmp_path / "page.html"
    code, payload, err = report(study, out)
    assert code == 0, (payload, err)
    raw, doc = out.read_text(encoding="utf-8"), doc_of(out)
    answers = " ".join(c["text"] for row in doc.tables[f"answers-{scenario['attempt_id']}"] for c in row)
    assert " ".join(SCENARIO_MARKUP.split()) in " ".join(answers.split())
    assert not [t for t, _ in doc.elements if t in ("script", "img", "xx-marker")] and "<xx-marker" not in raw
    assert [s["id"] for s in doc.sections][-1] == "exposure" and len(doc.sections) == 10
    for _, attrs in doc.elements:
        assert not [n for n in attrs if n.startswith("on") or n == "src"]


# --- C7: an llm_live Attempt ------------------------------------------------------------------------------------------


def test_a_live_attempt_shows_model_and_served_model_its_limits_notes_parameters_database_hashes_tokens_cost_and_latency_a_null_is_unknown(world, tmp_path):
    study, facts, out, doc = world
    attempt = facts["attempts"]["plain"]
    config = attempt["effective_config"]
    rows = {r[0]: r[1] for r in doc.body(f"live-{attempt['attempt_id']}")}
    assert rows["Model (requested)"] == config["model"]
    assert rows["Served model (reported)"] == (config["served_model"] or "unknown")
    assert json.loads(rows["Effective limits"]) == config["limits"]
    assert json.loads(rows["Effective parameters"]) == config["effective_parameters"]
    for key, note in config["limit_notes"].items():
        assert rows[f"Limit note, {key}"] == note
    assert "Inspect has no limit" in rows["Limit note, tool_calls"]
    run = json.loads((study / "attempts" / attempt["attempt_id"] / "run.json").read_text())
    assert rows["Chinook file SHA-256 before"] == run["database_sha256"]["before"] and rows["Chinook file SHA-256 after"] == run["database_sha256"]["after"]
    usage = doc.body(f"usage-{attempt['attempt_id']}")
    entries = entries_of(study, attempt)
    assert len(usage) == len(entries)
    for case, repeat, latency, tokens, cost in usage:
        recorded = entries[(case, int(repeat))]["usage"]
        shown = lambda value: "unknown" if value is None else f"{float(f'{value:.6g}'):g}"  # noqa: E731
        assert [latency, tokens, cost] == [shown(recorded["latency_seconds"]), shown(recorded["tokens"]), shown(recorded["cost"])]
    assert {row[4] for row in usage} == {"unknown"}  # the mock model has no cost: shown unknown, never 0
    # a served model the provider did not report is unknown, never the requested name
    copy = tmp_path / "copy"
    shutil.copytree(study, copy)
    edit_manifest(copy, attempt["attempt_id"], lambda m: m["effective_config"].update(served_model=None))
    again = tmp_path / "again.html"
    assert report(copy, again)[0] == 0
    assert {r[0]: r[1] for r in doc_of(again).body(f"live-{attempt['attempt_id']}")}["Served model (reported)"] == "unknown"


# --- D: Configurations ------------------------------------------------------------------------------------------------


def test_D_the_configurations_section_shows_each_configurations_id_declared_content_and_system_text_escaped(tmp_path):
    markup = '<script>alert(1)</script> "><img src=x onerror=alert(1)>'
    examples = chinook_examples(tmp_path, edit=lambda d: d["configurations"]["verify"].update(added_instruction=f"\n{markup}\n"))
    study, _ = init_chinook(tmp_path, examples=examples)
    with pytest.MonkeyPatch.context() as mp:
        patch_model(mp)
        attempt = ok(live(study, "verify", "v", "--examples-dir", examples))
    out = tmp_path / "page.html"
    assert report(study, out)[0] == 0
    doc = doc_of(out)
    shown = {r[0]: r[1] for r in doc.body(f"configuration-{attempt['attempt_id']}")}
    configuration = attempt["effective_config"]["configuration"]
    assert shown["Configuration id"] == "verify"
    assert json.loads(shown["Declared content"]) == configuration["declared"]
    assert " ".join(shown["System text"].split()) == " ".join(configuration["system_text"].split()) and markup.split()[0] in shown["System text"]
    assert not [t for t, _ in doc.elements if t in ("script", "img")]
    section = next(s for s in doc.sections if s["id"] == "configurations")
    assert section["headings"] == ["Configurations compared"]


# --- the revision, the statuses ---------------------------------------------------------------------------------------


def test_an_agent_assessment_under_a_corrected_references_set_is_shown_with_its_revision_and_the_earlier_assessment_and_cause(tmp_path):
    from _exposure_helpers import edit_chinook_references
    from _revision_helpers import new_revision

    study, _ = init_chinook(tmp_path)
    with pytest.MonkeyPatch.context() as mp:
        patch_model(mp)
        attempt = ok(live(study, "plain", "first", cases=["D03", "D05"], repeats=1))
    observation_set = observation_set_of(study, attempt)
    first = assess_agent(study, observation_set)
    corrected = edit_chinook_references(tmp_path, lambda r: r["D03"].update(rows=[[r["D03"]["rows"][0][0] + 1]]))
    code, payload, err = new_revision(study, "--examples-dir", corrected)
    assert code == 0, (payload, err)
    second = assess_agent(study, observation_set)
    assert second["rescoring"]["earlier_assessment_id"] == first["assessment_id"] and second["study_revision"]["number"] == 2
    out = tmp_path / "page.html"
    assert report(study, out)[0] == 0
    doc = doc_of(out)
    shown = {a["assessment_id"]: {r[0]: r[1] for r in doc.body(f"assessment-{i}")} for i, a in enumerate(sorted([first, second], key=lambda a: (a["recorded_at"], a["assessment_id"])))}
    assert shown[first["assessment_id"]]["Revision"] == "1" and shown[second["assessment_id"]]["Revision"] == "2"
    assert shown[first["assessment_id"]]["References set"] != shown[second["assessment_id"]]["References set"]
    assert f"This Assessment follows Assessment {first['assessment_id']}" in doc.text and "Recorded cause: references_version" in doc.text
    assert {first["assessment_id"], second["assessment_id"]} <= {row[0] for row in doc.body("assessments")}
    check_criteria(study, doc, first["assessment_id"])  # the earlier Assessment stays shown, unchanged


def test_the_attempts_of_the_agent_track_show_their_mode_status_request_id_and_item_counts_a_null_is_unknown_and_no_nan(world, tmp_path):
    from _report_helpers import constructed_attempt

    study, facts, _, doc = world
    rows = {row[0]: row for row in doc.body("attempts")}
    plain = facts["attempts"]["plain"]
    assert rows[plain["attempt_id"]][1:5] == ["llm_live", "completed", "live-plain", "no"]
    counts = plain["item_counts"]
    assert rows[plain["attempt_id"]][5:8] == [str(counts["produced"]), str(counts["failed"]), str(counts["missing"])]
    assert rows[facts["import"]["attempt_id"]][1:5] == ["external_unknown", "completed", facts["import_request"], "no"]
    assert journal_of(study) == []  # a Study of dev Items records no Exposure
    assert not re.search(r"\b(nan|inf|infinity)\b", doc.text, re.I)
    # an Attempt that stopped has no counts: unknown, never 0, and never shown as completed
    copy = tmp_path / "copy"
    shutil.copytree(study, copy)
    running = constructed_attempt(copy, "running", request_id="still-going", mode="llm_live")
    out = tmp_path / "page.html"
    assert report(copy, out)[0] == 0
    shown = {row[0]: row for row in doc_of(out).body("attempts")}
    assert shown[running][1:] == ["llm_live", "running", "still-going", "no", "unknown", "unknown", "unknown", "none"]
