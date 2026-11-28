"""M2b: the protected ranking CLI, using only synthetic Items and References."""

import json

import pytest
from _ranking_helpers import CONTRACT, WORKLOAD, command, metadata, write_build

from hypotrail.core import artifacts, lock
from hypotrail.ml import ranking_study

PRIVATE_IDS = ("synthetic-private-a@2011-02-01", "synthetic-private-b@2011-02-01")
PRIVATE_SCORE = "0.71234567890123456"
REFUSAL = "RANKING_HELD_OUT_REFUSED"


@pytest.fixture
def synthetic(tmp_path):
    items = (
        "item_id,entity_id,as_of,partition,mature\npublic-dev@2011-01-01,public-dev,2011-01-01,dev,true\n"
        + "".join(f"{item},{item.split('@')[0]},2011-02-01,held_out,true\n" for item in PRIVATE_IDS)
    )
    references = "item_id,label\n" + "".join(f"{item},{label}\n" for label, item in enumerate(PRIVATE_IDS))
    examples, build = write_build(
        tmp_path, items=items.encode(), references=b"item_id,label\npublic-dev@2011-01-01,1\n", held_out_references=references.encode()
    )
    return examples, build, tmp_path / "study"


@pytest.fixture
def evaluator_job(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/kit")
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", "example/kit/.github/workflows/evaluator.yml@refs/heads/main")
    monkeypatch.delenv("HYPOTRAIL_RUN_TOOL", raising=False)


def _init(paths):
    examples, build, study = paths
    return "init", "--partition", "held_out", "--examples-dir", examples, "--build-dir", build, "--workload", WORKLOAD, "--study", study


def _import(paths, role):
    _, build, study = paths
    mapping = json.loads((CONTRACT / "mapping.json").read_bytes())
    mapping["dataset_sha256"] = metadata((build / "items.csv").read_bytes())["sha256"]
    mapping_path = build / f"{role}-mapping.json"
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
    population = build / f"{role}-population.json"
    population.write_text(json.dumps({"item_ids": PRIVATE_IDS}), encoding="utf-8")
    scores = build / f"{role}-scores.csv"
    ordered = PRIVATE_IDS if role == "control" else PRIVATE_IDS[::-1]
    scores.write_text(f"item_id,score\n{ordered[0]},{PRIVATE_SCORE}\n{ordered[1]},0\n", encoding="utf-8")
    return "import", "ml", "--study", study, "--source", scores, "--population", population, "--mapping", mapping_path, "--request-id", role


def _assess(study, observations, references):
    return "assess", "--study", study, "--observations", observations, "--references", references, "--scorer", "ranking_recall_at_top_v1"


def _safe(text):
    for item in PRIVATE_IDS:
        assert item.split("@")[0] not in text
    for private in (PRIVATE_SCORE, "per_item.csv", "references-held_out.csv", "item_ids"):
        assert private not in text


def _evaluate(*args):
    code, payload, err = command("--evaluator", *args)
    assert code == 0, (payload, err)
    _safe(json.dumps(payload) + err)
    return payload


@pytest.mark.parametrize("declaration", ["plain_cli", "job_marker_only", "missing_job", "different_workflow", "different_repository", "different_branch", "run_tool"])
def test_init_refuses_before_opening_a_protected_build(synthetic, evaluator_job, monkeypatch, declaration):
    if declaration in {"plain_cli", "missing_job"}:
        monkeypatch.delenv("GITHUB_ACTIONS")
    if declaration == "different_workflow":
        monkeypatch.setenv("GITHUB_WORKFLOW_REF", "example/kit/.github/workflows/ci.yml@refs/heads/main")
    if declaration == "different_repository":
        monkeypatch.setenv("GITHUB_REPOSITORY", "example/another-kit")
    if declaration == "different_branch":
        monkeypatch.setenv("GITHUB_WORKFLOW_REF", "example/kit/.github/workflows/evaluator.yml@refs/heads/test")
    if declaration == "run_tool":
        monkeypatch.setenv("HYPOTRAIL_RUN_TOOL", "1")
    prefix = () if declaration in {"plain_cli", "job_marker_only"} else ("--evaluator",)
    monkeypatch.setattr(ranking_study, "_read_source", lambda *_: pytest.fail("opened a protected build"))
    code, payload, err = command(*prefix, *_init(synthetic))
    assert (code, payload["error"]["code"]) == (2, REFUSAL)
    _safe(json.dumps(payload) + err)
    assert not synthetic[2].exists()


@pytest.fixture
def made(synthetic, evaluator_job):
    return _evaluate(*_init(synthetic))


@pytest.mark.parametrize("operation", ["import", "assess", "compare", "report", "revision"])
def test_plain_cli_refuses_an_existing_protected_study_before_row_reads(synthetic, made, monkeypatch, operation):
    _, _, study = synthetic
    out = study.parent / "aggregate.json"
    args = {
        "import": _import(synthetic, "control"),
        "assess": _assess(study, "unknown", made["references_id"]),
        "compare": ("compare", "--study", study, "--control", "unknown", "--candidate", "unknown"),
        "report": ("report", "--study", study, "--out", out),
        "revision": ("init", "--study", study, "--new-revision"),
    }
    monkeypatch.setattr(artifacts, "read_verified", lambda *_: pytest.fail("opened a protected record payload"))
    code, payload, err = command(*args[operation])
    assert (code, payload["error"]["code"]) == (2, REFUSAL)
    _safe(json.dumps(payload) + err)
    assert not out.exists()


def test_evaluator_cli_keeps_protected_rows_under_the_lock_and_publishes_aggregates(synthetic, evaluator_job, monkeypatch):
    _, _, study = synthetic
    read_source, read_verified = ranking_study._read_source, artifacts.read_verified

    def locked_source(folder, source):
        assert lock.is_held(study), "Build source was read before the Study was locked"
        assert source["dataset_id"] != "references-dev.csv"
        return read_source(folder, source)

    def locked_record(folder, ref):
        assert lock.is_held(study), "Study payload was read outside the Study lock"
        return read_verified(folder, ref)

    monkeypatch.setattr(ranking_study, "_read_source", locked_source)
    monkeypatch.setattr(artifacts, "read_verified", locked_record)
    made = _evaluate(*_init(synthetic))
    assessments = []
    for role, recall in (("control", 0), ("candidate", 1)):
        imported = _evaluate(*_import(synthetic, role))
        record = _evaluate(*_assess(study, imported["observation_set_id"], made["references_id"]))["assessment"]
        assert record["metrics"][0]["value"] == recall
        assessments.append(record)
    control, candidate = (a["assessment_id"] for a in assessments)
    comparison = _evaluate("compare", "--study", study, "--control", control, "--candidate", candidate)["comparison"]
    assert comparison["delta"]["value"] == 1
    interval = comparison["interval"]
    assert interval["unit"] == "entity" and interval["resamples"] == 2000
    assert 0 < interval["usable_resamples"] < 2000
    assert interval["omitted_dates"] == 2000 - interval["usable_resamples"]

    monkeypatch.setattr(artifacts, "read_verified", lambda *_: pytest.fail("aggregate report opened a protected payload"))
    out = study.parent / "aggregate.json"
    report = _evaluate("report", "--study", study, "--out", out)["report"]
    assert report["partition"] == "held_out"
    assert report["comparisons"] == [comparison]
    assert {a["assessment_id"] for a in report["assessments"]} == {control, candidate}
    assert report["write_sequence"] > 0
    text = out.read_text(encoding="utf-8")
    assert json.loads(text) == report
    _safe(text)


def test_protected_command_diagnostics_carry_no_arguments_or_payload_text(synthetic, made):
    _, _, study = synthetic
    code, payload, err = command("--evaluator", *_assess(study, PRIVATE_IDS[0], made["references_id"]))
    assert (code, payload["error"]["code"]) == (2, "OBSERVATION_SET_NOT_FOUND")
    _safe(json.dumps(payload) + err)


def test_evaluator_process_refuses_human_decisions_before_reading_words(synthetic, made):
    _, build, study = synthetic
    code, payload, err = command(
        "--evaluator", "decide", "--study", study, "--question", "Rule", "--option", "accepted", "--author", "human",
        "--words-file", build / PRIVATE_IDS[0], "--artifact", "test", "--request-id", "refused", "--read-sequence", 0,
    )
    assert (code, payload["error"]["code"]) == (2, REFUSAL)
    _safe(json.dumps(payload) + err)


def test_evaluator_context_does_not_enable_other_commands(synthetic, made):
    _, _, study = synthetic
    code, payload, err = command("--evaluator", "status", "--study", study)
    assert (code, payload["error"]["code"]) == (2, REFUSAL)
    _safe(json.dumps(payload) + err)


def test_evaluator_cannot_create_a_protected_study_in_a_git_checkout(synthetic, evaluator_job, monkeypatch):
    examples, build, study = synthetic
    checkout = study.parent / "checkout"
    checkout.mkdir()
    (checkout / ".git").write_text("gitdir: synthetic-checkout\n", encoding="utf-8")
    monkeypatch.setattr(ranking_study, "_read_source", lambda *_: pytest.fail("opened a protected build"))
    code, payload, err = command("--evaluator", *_init((examples, build, checkout / "study")))
    assert (code, payload["error"]["code"]) == (2, REFUSAL)
    _safe(json.dumps(payload) + err)
    assert not (checkout / "study").exists()


def test_comparison_binds_both_sides_before_opening_either_protected_payload(synthetic, made, monkeypatch):
    from hypotrail.core import study as layout

    _, _, study = synthetic
    control = _evaluate(*_import(synthetic, "control"))["observation_set_id"]
    candidate = _evaluate(*_import(synthetic, "candidate"))["observation_set_id"]
    assessments = [
        _evaluate(*_assess(study, observations, made["references_id"]))["assessment"]["assessment_id"]
        for observations in (control, candidate)
    ]
    find = layout.find_observation_set
    read_verified = artifacts.read_verified

    def mismatched(folder, observations):
        observed, manifest = find(folder, observations)
        if observations == candidate:
            observed["provenance"]["partition"] = "dev"
        return observed, manifest

    def no_payload(folder, ref):
        assert ref["role"] == "observation_set", "Comparison opened a per-Item payload before checking both sides"
        return read_verified(folder, ref)

    monkeypatch.setattr(layout, "find_observation_set", mismatched)
    monkeypatch.setattr(artifacts, "read_verified", no_payload)
    code, payload, err = command("--evaluator", "compare", "--study", study, "--control", assessments[0], "--candidate", assessments[1])
    assert (code, payload["error"]["code"]) == (2, REFUSAL)
    _safe(json.dumps(payload) + err)


@pytest.mark.parametrize("operation", ["init", "init_agent", "recover", "deviation", "assess_agent"])
def test_other_writers_refuse_protected_studies_before_accessing_records(synthetic, made, monkeypatch, operation):
    from hypotrail.core import evaluator, write_journal
    from hypotrail.core import study as layout

    examples, build, study = synthetic
    imported = _evaluate(*_import(synthetic, "control"))
    attempt_id, = layout.attempt_ids(study)
    sequence = write_journal.write_sequence(study)
    agent = examples / "agent-fixture"
    agent.mkdir()
    (agent / "workload.json").write_text('{"track":"tool_using_agent"}', encoding="utf-8")
    args = {
        "init": ("init", "--study", study, "--examples-dir", examples, "--workload", WORKLOAD, "--build-dir", build),
        "init_agent": ("init", "--study", study, "--examples-dir", examples, "--workload", agent.name),
        "recover": ("recover", "--study", study, "--attempt", attempt_id, "--read-sequence", sequence),
        "deviation": (
            "deviation", "--study", study, "--text", "A synthetic deviation", "--author", "proxy",
            "--artifact", attempt_id, "--request-id", "deviation", "--read-sequence", sequence,
        ),
        "assess_agent": (
            "assess", "--study", study, "--observations", imported["observation_set_id"],
            "--references", made["references_id"], "--scorer", "text_facts_v1",
        ),
    }

    def unread(*_):
        pytest.fail("Writer opened a protected record before refusing the Study")

    refuse_protected = evaluator.refuse_protected

    def refusal_under_lock(spec, *, stage):
        assert lock.is_held(study), "Writer refused the protected Study outside the writer lock"
        refuse_protected(spec, stage=stage)

    monkeypatch.setattr(evaluator, "refuse_protected", refusal_under_lock)
    monkeypatch.setattr(layout, "read_manifest", unread)
    monkeypatch.setattr(layout, "find_observation_set", unread)
    monkeypatch.setattr(artifacts, "read_verified", unread)
    code, payload, err = command(*args[operation])
    assert (code, payload["error"]["code"]) == (2, REFUSAL)
    assert write_journal.write_sequence(study) == sequence
    _safe(json.dumps(payload) + err)


def test_evaluator_requires_exact_prefix_and_keeps_ordinary_global_help(synthetic, evaluator_job, capsys):
    from hypotrail import cli

    with pytest.raises(SystemExit) as help_exit:
        cli.main(["--he"])
    assert help_exit.value.code == 0
    assert "usage: hypotrail" in capsys.readouterr().out
    code, payload, err = command("--eval", *_init(synthetic))
    assert (code, payload["error"]["code"]) == (2, REFUSAL)
    _safe(json.dumps(payload) + err)
    assert not synthetic[2].exists()


@pytest.fixture
def compared(synthetic, made):
    _, _, study = synthetic
    assessments = []
    for role in ("control", "candidate"):
        observation_id = _evaluate(*_import(synthetic, role))["observation_set_id"]
        assessment_id = _evaluate(*_assess(study, observation_id, made["references_id"]))["assessment"]["assessment_id"]
        assessments.append(assessment_id)
    comparison_id = _evaluate("compare", "--study", study, "--control", assessments[0], "--candidate", assessments[1])["comparison"]["comparison_id"]
    return study, assessments[0], comparison_id


def _change_record(path, change):
    from hypotrail.core import canonical, contracts

    record = canonical.loads(path.read_bytes())
    change(record)
    contracts.validate(record)
    path.write_bytes(canonical.dumps(record))


def test_protected_report_projects_only_known_coverage_fields_and_metric_labels(compared):
    study, assessment_id, comparison_id = compared

    def extra_assessment_labels(record):
        record["metrics"][0].update(id=PRIVATE_IDS[0], unit=PRIVATE_IDS[1], reason=PRIVATE_IDS[0])

    def extra_comparison_fields(record):
        record["coverage"][PRIVATE_IDS[1]] = {"score": PRIVATE_SCORE}
        record["delta"].update(metric=PRIVATE_IDS[0], unit=PRIVATE_IDS[1], definition=PRIVATE_IDS[0], reason=PRIVATE_IDS[1])

    _change_record(study / "assessments" / assessment_id / "assessment.json", extra_assessment_labels)
    _change_record(study / "comparisons" / comparison_id / "comparison.json", extra_comparison_fields)
    out = study.parent / "aggregate.json"
    report = _evaluate("report", "--study", study, "--out", out)["report"]
    comparison = report["comparisons"][0]
    assert comparison["coverage"] == {"expected": 2, "control_scored": 2, "candidate_scored": 2, "paired": 2}
    assert comparison["delta"]["value"] == 1
    assert comparison["delta"]["metric"] == "recall_at_top_fraction"
    assert all(a["metrics"][0]["id"] == "recall_at_top_fraction" for a in report["assessments"])
    _safe(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize("field", ["identifier", "coverage"])
def test_protected_report_refuses_nonaggregate_values_in_selected_fields(compared, field):
    study, _, comparison_id = compared

    def change(record):
        if field == "identifier":
            record["comparison_id"] = PRIVATE_IDS[1]
        else:
            record["coverage"]["paired"] = PRIVATE_IDS[1]

    _change_record(study / "comparisons" / comparison_id / "comparison.json", change)
    out = study.parent / "aggregate.json"
    code, payload, err = command("--evaluator", "report", "--study", study, "--out", out)
    assert (code, payload["error"]["code"]) == (3, "CONTRACT_VIOLATION")
    _safe(json.dumps(payload) + err)
    assert not out.exists()


@pytest.mark.parametrize("operation", ["assess", "assess_agent", "assess_unknown", "compare", "compare_factor", "report", "recover", "revision"])
def test_ordinary_cli_refuses_protected_scope_before_journal_and_operation_checks(synthetic, made, monkeypatch, operation):
    from hypotrail.core import evaluator, write_journal

    _, _, study = synthetic
    stale = ("--read-sequence", 0)
    assessment = ("assess", "--study", study, "--observations", "unknown", "--references", made["references_id"], "--scorer")
    comparison = ("compare", "--study", study, "--control", "unknown", "--candidate", "unknown")
    out = study.parent / "aggregate.json"
    args = {
        "assess": (*assessment, "ranking_recall_at_top_v1", *stale),
        "assess_agent": (*assessment, "text_facts_v1", *stale),
        "assess_unknown": (*assessment, "unregistered"),
        "compare": (*comparison, *stale),
        "compare_factor": (*comparison, "--factor", "configuration"),
        "report": ("report", "--study", study, "--out", out, *stale),
        "recover": ("recover", "--study", study, "--attempt", "unknown", *stale),
        "revision": ("init", "--study", study, "--new-revision", *stale),
    }
    original_refusal = evaluator.refusal

    def refusal_under_lock(stage):
        assert lock.is_held(study), "The Partition was refused outside the Study lock"
        return original_refusal(stage)

    def unread(*_):
        pytest.fail("The journal was accessed before the protected Study was refused")

    monkeypatch.setattr(evaluator, "refusal", refusal_under_lock)
    monkeypatch.setattr(write_journal, "write_sequence", unread)
    monkeypatch.setattr(write_journal, "entries", unread)
    code, payload, err = command(*args[operation])
    assert (code, payload["error"]["code"]) == (2, REFUSAL)
    _safe(json.dumps(payload) + err)
    assert not out.exists()


def test_ordinary_decide_refuses_the_protected_study_before_reading_a_words_file(synthetic, made, monkeypatch):
    from hypotrail.core import decisions

    _, build, study = synthetic

    def unread(*_):
        pytest.fail("The words file was opened before the protected Study was refused")

    monkeypatch.setattr(decisions, "_read_words_file", unread)
    code, payload, err = command(
        "decide", "--study", study, "--question", "Rule", "--option", "accepted", "--author", "proxy", "--source", "synthetic",
        "--words-file", build / "references-held_out.csv", "--artifact", made["references_id"], "--request-id", "refused", "--read-sequence", 0,
    )
    assert (code, payload["error"]["code"]) == (2, REFUSAL)
    _safe(json.dumps(payload) + err)


def test_declared_evaluator_still_checks_stale_write_sequences_without_printing_the_journal(synthetic, made):
    _, _, study = synthetic
    _evaluate(*_import(synthetic, "private-request"))
    code, payload, err = command(
        "--evaluator", "compare", "--study", study, "--control", "unknown", "--candidate", "unknown", "--read-sequence", 0,
    )
    assert (code, payload["error"]["code"]) == (6, "STUDY_CHANGED")
    assert payload["error"]["details"] == {}
    assert "private-request" not in err
    _safe(json.dumps(payload) + err)
