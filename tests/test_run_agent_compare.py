"""Ticket #74: two `llm_live` Attempts recorded by `run agent` (the mock model patched in by the test) are assessed and compared strictly, offline."""

import json
from pathlib import Path

import pytest
from _agent_compare_helpers import SCORER
from _agent_helpers import CHINOOK, REFERENCES, WORKLOAD, read_jsonl
from _assess_helpers import snapshot
from _run_agent_helpers import MODEL, ok, live, patch_model, refuse_provider, folder_of, observation_set_id_of, study_of
from _chinook_helpers import chinook_examples, references_id
from _study_helpers import EXAMPLES, run_cli, run_json
from test_write_sequence import seq

from hypotrail.agentic import rescore
from hypotrail.agentic import runner, sql_tool
from hypotrail.core.comparison import REFUSALS
from hypotrail.core.errors import EXIT_INTEGRITY_REFUSED


ORDER = "COMPARISON_ORDER_NOT_ALTERNATED"


def codes_of(record):
    return [warning["code"] for warning in record["warnings"]]


def assess(study, attempt, *more):
    code, payload, err = run_json("assess", "--study", study, "--observations", observation_set_id_of(study, attempt), "--scorer", SCORER, "--references", references_id(study), *more)
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
    assert code == 0, (payload, err)
    record = payload["comparison"]
    # strict: every check passed and both sides are native. `plain` then `verify` ran in two time blocks, so the record holds
    # the order warning, and stderr holds it and nothing else; the warning leaves the status as the checks compute it.
    assert codes_of(record) == [ORDER]
    assert err.splitlines() == [f"{ORDER}: {record['warnings'][0]['message']}"]
    assert record["comparability"]["status"] == "compatible" and record["declared_factor"] == "configuration"
    assert [(c["check"], c["passed"], c["reason"]) for c in record["comparability"]["checks"]] == [
        (name, True, None) for name in ("population", "cases", "references", "scorer", "unit", "repeats", "tools", "model", "budgets", "mode")
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


def test_two_attempts_run_one_after_the_other_hold_one_order_warning_naming_the_side_that_ran_first_in_both_role_orders_and_stay_compatible(sides):
    study, attempts, assessments = sides
    assert attempts["plain"]["finished_at"] < attempts["verify"]["started_at"]  # `plain` ran, then `verify`
    for control, candidate, first, second in (("plain", "verify", "control", "candidate"), ("verify", "plain", "candidate", "control")):
        code, payload, err = compare(study, assessments[control], assessments[candidate])
        assert code == 0, (payload, err)
        record = payload["comparison"]
        assert codes_of(record) == [ORDER], control
        (message,) = [warning["message"] for warning in record["warnings"]]
        assert f"The {first} ran before the {second}" in message, message
        assert "time block" in message and "time effect" in message, message
        assert message in record["limitations"]
        # the status is computed as without the warning: every check passed, so it is compatible
        assert record["comparability"]["status"] == "compatible"
        assert all(c["passed"] and c["reason"] is None for c in record["comparability"]["checks"])


def test_two_attempts_of_one_configuration_that_differ_by_their_model_compared_with_factor_model_hold_the_order_warning_too(sides, monkeypatch):
    study, attempts, assessments = sides
    patch_model(monkeypatch)
    other = ok(live(study, "plain", "plain-other-model", repeats=2, model="anthropic/claude-other"))
    assert other["effective_config"]["configuration"]["id"] == attempts["plain"]["effective_config"]["configuration"]["id"] == "plain"
    assert attempts["plain"]["finished_at"] < other["started_at"]
    code, payload, err = compare(study, assessments["plain"], assess(study, other), "--factor", "model")
    assert code == 0, (payload, err)
    assert payload["comparison"]["declared_factor"] == "model"
    assert codes_of(payload["comparison"]) == [ORDER]


def test_without_json_the_status_line_on_stdout_names_the_order_code_beside_compatible_and_stderr_holds_the_order_warning(sides):
    study, _, assessments = sides
    code, out, err = run_cli("compare", "--study", study, "--control", assessments["plain"]["assessment_id"], "--candidate", assessments["verify"]["assessment_id"])
    assert code == 0, (out, err)
    (line,) = [line for line in out.splitlines() if "compatible" in line]
    comparison_id = line.split()[1]
    record = json.loads((study / "comparisons" / comparison_id / "comparison.json").read_text(encoding="utf-8"))
    assert record["comparability"]["status"] == "compatible" and codes_of(record) == [ORDER]
    assert line.startswith(f"Comparison {comparison_id} (compatible") and ORDER in line.split("):")[0], line
    assert f"{ORDER}: {record['warnings'][0]['message']}" in err.splitlines()


def test_without_json_the_status_line_on_stdout_names_the_declared_deviation_code_beside_the_status_and_stderr_holds_its_warning(sides, tmp_path):
    import shutil

    from _deviation_helpers import CODE, declare

    source, attempts, assessments = sides
    study = tmp_path / "copy"
    shutil.copytree(source, study)  # the module's Study stays without a Declared deviation
    declare(study, [attempts["plain"]["attempt_id"]])
    code, out, err = run_cli("compare", "--study", study, "--control", assessments["plain"]["assessment_id"], "--candidate", assessments["verify"]["assessment_id"])
    assert code == 0, (out, err)
    (line,) = [line for line in out.splitlines() if line.startswith("Comparison ")]
    record = json.loads((study / "comparisons" / line.split()[1] / "comparison.json").read_text(encoding="utf-8"))
    assert record["comparability"]["status"] == "compatible" and CODE in codes_of(record)
    assert line.startswith(f"Comparison {record['comparison_id']} (compatible") and CODE in line.split("):")[0], line
    (warning,) = [w for w in record["warnings"] if w["code"] == CODE]
    assert f"{CODE}: {warning['message']}" in err.splitlines()


def test_the_order_warning_goes_when_nothing_but_the_four_times_of_the_two_manifests_change_from_disjoint_to_overlapping(sides, tmp_path):
    import shutil

    from hypotrail.core import canonical

    source, attempts, assessments = sides
    study = tmp_path / "copy"
    shutil.copytree(source, study)
    records = []
    for times in (None, "overlapping"):
        if times:
            start, end = attempts["plain"]["started_at"], attempts["verify"]["finished_at"]
            for name in ("plain", "verify"):  # both intervals become [plain's start, verify's end]
                path = folder_of(study, attempts[name]) / "attempt.json"
                manifest = json.loads(path.read_text(encoding="utf-8"))
                path.write_bytes(canonical.dumps({**manifest, "started_at": start, "finished_at": end}))
        code, payload, err = compare(study, assessments["plain"], assessments["verify"])
        assert code == 0, (payload, err)
        records.append(payload["comparison"])
    disjoint, overlapping = records
    assert codes_of(disjoint) == [ORDER] and codes_of(overlapping) == []
    order = disjoint["warnings"][0]["message"]
    assert [m for m in disjoint["limitations"] if m != order] == overlapping["limitations"]
    for key in ("comparability", "coverage", "delta", "secondary_deltas", "declared_factor", "code_environment"):
        assert disjoint[key] == overlapping[key], key


def test_two_attempts_whose_case_digests_are_equal_for_every_case_record_the_cases_check_passed(sides):
    study, attempts, assessments = sides
    assert attempts["plain"]["case_digests"] == attempts["verify"]["case_digests"]
    code, payload, err = compare(study, assessments["plain"], assessments["verify"])
    assert code == 0, (payload, err)
    checks = payload["comparison"]["comparability"]["checks"]
    assert {c["check"]: c for c in checks}.get("cases") == {"check": "cases", "passed": True, "reason": None}


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


def sides_across_a_case_change(tmp_path, partition):
    """`plain` run twice on the same two Cases of `partition`, on either side of `init --new-revision` made after the text of the
    first Case changed in a copy of the Workload (the References file unchanged), both assessed against the one References set."""
    examples = chinook_examples(tmp_path)
    given = ("--examples-dir", str(examples))
    study = study_of(tmp_path, examples=examples)
    cases = [case["case_id"] for case in WORKLOAD.cases(partition)][:2]
    before = ok(live(study, "plain", "before", *given, cases=cases, partition=partition))
    path = examples / "chinook" / WORKLOAD.cases_path(partition).relative_to(CHINOOK)
    references = (examples / "chinook" / "references" / "chinook-references.jsonl").read_bytes()
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    lines[0]["question"] += " (variante)"
    path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8")
    code, payload, err = run_json("init", "--study", study, "--new-revision", *given)
    assert code == 0, (payload, err)
    after = ok(live(study, "plain", "after", *given, cases=cases, partition=partition))
    assert (examples / "chinook" / "references" / "chinook-references.jsonl").read_bytes() == references
    assessments = [assess(study, attempt, *given) for attempt in (before, after)]
    assert assessments[0]["references_ref"]["sha256"] == assessments[1]["references_ref"]["sha256"]
    return study, examples, cases, (before, after), assessments


@pytest.mark.parametrize("partition", ["dev", "public_check"])
def test_two_attempts_whose_content_differs_for_one_case_are_refused_on_cases_which_cannot_be_declared_and_nothing_is_written(tmp_path, monkeypatch, partition):
    patch_model(monkeypatch)
    study, examples, cases, (before, after), (control, candidate) = sides_across_a_case_change(tmp_path, partition)
    given = ("--examples-dir", str(examples))
    exposures = sorted(p.name for p in (study / "exposures").glob("*")) if (study / "exposures").is_dir() else []
    sequence = seq(study)
    code, payload, err = compare(study, control, candidate, *given)
    assert code == EXIT_INTEGRITY_REFUSED, (payload, err)
    error = payload["error"]
    assert (error["code"], error["stage"]) == ("COMPARISON_CASES_DIFFER", "compare")
    assert set(error["details"]) == {"check", "reason", "control", "candidate", "checks"}
    assert (error["details"]["check"], error["details"]["reason"]) == ("cases", "cases_differ")
    changed = cases[0]  # the same Case IDs on both sides; only the first Case's content changed
    assert error["details"]["control"] == {"cases": {changed: before["case_digests"][changed]}}
    assert error["details"]["candidate"] == {"cases": {changed: after["case_digests"][changed]}}
    assert before["case_digests"][changed] != after["case_digests"][changed]
    assert [c["check"] for c in error["details"]["checks"]] == ["population", "cases"]
    assert error["details"]["checks"][-1] == {"check": "cases", "passed": False, "reason": "cases_differ"}
    assert "cases" in error["message"] and "cannot be declared" in error["message"]
    # no Comparison, no new Exposure, no write
    assert not (study / "comparisons").exists() or not any((study / "comparisons").iterdir())
    assert (sorted(p.name for p in (study / "exposures").glob("*")) if (study / "exposures").is_dir() else []) == exposures
    assert seq(study) == sequence
    # `cases` is no factor a request can declare
    code, out, err = run_cli("compare", "--study", study, "--control", control["assessment_id"], "--candidate", candidate["assessment_id"], "--factor", "cases", *given, "--json")
    assert code == 2 and "invalid choice" in err


def test_two_sides_that_differ_in_case_content_and_in_references_are_refused_on_cases_first(tmp_path, monkeypatch):
    from test_compare_agent import rewritten

    patch_model(monkeypatch)
    study, examples, _, _, (control, candidate) = sides_across_a_case_change(tmp_path, "dev")
    other_references = rewritten(study, candidate, lambda record: record["references_ref"].update(sha256="b" * 64))
    code, payload, _ = compare(study, control, other_references, "--examples-dir", str(examples))
    assert code == EXIT_INTEGRITY_REFUSED and payload["error"]["code"] == "COMPARISON_CASES_DIFFER"


def without_case_digests(study, attempt, *, file_digest=True):
    """The Attempt's manifest rewritten as one recorded before `case_digests` existed; without `file_digest`, its Cases file digest goes too."""
    from hypotrail.core import canonical

    path = folder_of(study, attempt) / "attempt.json"
    manifest = {key: value for key, value in json.loads(path.read_text(encoding="utf-8")).items() if key != "case_digests"}
    if not file_digest:
        config = manifest["effective_config"]
        config = {**config, "input_digests": {key: value for key, value in config["input_digests"].items() if key != "cases"}}
        manifest.update(effective_config=config, effective_config_digest=canonical.digest(config))
    path.write_bytes(canonical.dumps(manifest))
    return manifest


def missing_one_case(study, attempt):
    """The Attempt's manifest rewritten with `case_digests` that leaves out the first Case it evaluated."""
    from hypotrail.core import canonical

    path = folder_of(study, attempt) / "attempt.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    first = attempt["effective_config"]["cases"][0]
    manifest["case_digests"] = {case_id: digest for case_id, digest in manifest["case_digests"].items() if case_id != first}
    path.write_bytes(canonical.dumps(manifest))
    return manifest


@pytest.fixture(scope="module")
def content_records(tmp_path_factory):
    """Native sides on the same dev Cases with and without per-Case digests, before and after a change of one Case's text."""
    tmp_path = tmp_path_factory.mktemp("content")
    with pytest.MonkeyPatch.context() as patch:
        patch_model(patch)
        examples = chinook_examples(tmp_path)
        given = ("--examples-dir", str(examples))
        study = study_of(tmp_path, examples=examples)
        attempts = {
            name: ok(live(study, config, name, *given))
            for name, config in (("a-old", "plain"), ("b-old", "verify"), ("b-new", "verify"), ("none", "verify"), ("partial", "verify"))
        }
        path = examples / "chinook" / WORKLOAD.cases_path("dev").relative_to(CHINOOK)
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        lines[0]["question"] += " (variante)"
        path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8")
        code, payload, err = run_json("init", "--study", study, "--new-revision", *given)
        assert code == 0, (payload, err)
        attempts.update({name: ok(live(study, "verify", name, *given)) for name in ("c-old", "c-new")})
        assessments = {name: assess(study, attempt, *given) for name, attempt in attempts.items()}
        for name in ("a-old", "b-old", "c-old"):
            without_case_digests(study, attempts[name])
        without_case_digests(study, attempts["none"], file_digest=False)
        missing_one_case(study, attempts["partial"])
        yield study, examples, assessments


@pytest.mark.parametrize(
    "control,candidate,passed",
    [
        ("a-old", "b-old", True),  # both recorded before, the same Cases file
        ("a-old", "c-old", False),  # both recorded before, another Cases file
        ("a-old", "b-new", True),  # one recorded before, the same Cases file
        ("a-old", "c-new", False),  # one recorded before, another Cases file
        ("none", "b-new", False),  # a native side with neither record
        ("partial", "b-new", False),  # `case_digests` that leaves out a Case: no fallback to the same Cases file
    ],
)
def test_without_per_case_digests_the_same_cases_file_passes_and_anything_else_is_not_established_never_compatible(content_records, control, candidate, passed):
    study, examples, assessments = content_records
    code, payload, err = compare(study, assessments[control], assessments[candidate], "--examples-dir", str(examples))
    assert code == 0, (payload, err)
    record = payload["comparison"]
    entry = {c["check"]: c for c in record["comparability"]["checks"]}.get("cases")
    codes = [warning["code"] for warning in record["warnings"]]
    # every side here is a native Attempt recorded after the other one finished, so each record also holds the order warning
    if passed:
        assert entry == {"check": "cases", "passed": True, "reason": None}
        assert record["comparability"]["status"] == "compatible" and codes == [ORDER]
    else:
        assert entry == {"check": "cases", "passed": False, "reason": "not_established"}
        assert record["comparability"]["status"] == "descriptive_only"
        assert codes == ["COMPARISON_CASES_NOT_ESTABLISHED", ORDER]  # its own code: `cases` is no factor
        assert record["warnings"][0]["message"] in record["limitations"]
        assert "COMPARISON_FACTOR_NOT_ESTABLISHED" not in codes


def test_the_check_of_case_content_passes_on_the_two_kept_attempts_of_the_public_check_campaign():
    from hypotrail.core import agent_comparison

    kept = Path(__file__).resolve().parent.parent / "docs" / "handbook" / "traces" / "campaign-public-check" / "study" / "attempts"
    control, candidate = (json.loads(path.read_text(encoding="utf-8")) for path in sorted(kept.glob("*/attempt.json")))
    cases = control["effective_config"]["cases"]
    assert cases == candidate["effective_config"]["cases"]
    assert agent_comparison.check_cases(control, candidate, cases) == {"check": "cases", "passed": True, "reason": None}


def test_a_native_manifest_built_by_the_test_helper_holds_the_case_digests_run_agent_records_for_the_same_cases(tmp_path, monkeypatch):
    from _agent_compare_helpers import answer_lines, imported, native
    from _chinook_helpers import FIXTURE_CASES

    patch_model(monkeypatch)
    study = study_of(tmp_path)
    recorded = ok(live(study, "plain", "recorded", cases=FIXTURE_CASES))
    seed, _ = imported(tmp_path, study, "seed", answer_lines())
    built, _ = native(study, seed)
    assert set(recorded["case_digests"]) == set(FIXTURE_CASES)
    assert built.get("case_digests") == recorded["case_digests"]
