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
