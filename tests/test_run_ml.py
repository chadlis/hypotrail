"""Ticket #64: `run ml` records one Bike Attempt (manifest, Observation set, predictions) in a Study."""

import csv
import json
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest
from _ml_helpers import fit_probe
from _study_helpers import EXAMPLES, examples_copy, init_study, run_json, run_ml, sha256

from hypotrail.core import artifacts, canonical, contracts
from hypotrail.core.errors import (
    EXIT_INTEGRITY_REFUSED,
    EXIT_INVALID_INPUT,
    EXIT_LOCK_OR_CONFLICT,
)

BIKE = EXAMPLES / "bike_day"


def snapshot(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): sha256(p) for p in sorted(folder.rglob("*")) if p.is_file()}


def rows_of(path: Path) -> list:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    """One Study with `seasonal_7` and `ridge_v1` run on dev; read-only for the tests that use it."""
    tmp = tmp_path_factory.mktemp("ran")
    study, _ = init_study(tmp)
    attempts = {}
    for config in ("seasonal_7", "ridge_v1"):
        code, payload, err = run_ml(study, config, "dev", f"ml-dev-{config}")
        assert code == 0, (payload, err)
        attempts[config] = payload["attempt"]
    return study, attempts


# --- AC2: the Attempt manifest -----------------------------------------------------------------------


def test_the_manifest_holds_every_field_of_the_contract_and_is_valid(ran):
    study, attempts = ran
    for config, manifest in attempts.items():
        contracts.validate(manifest)
        stored = json.loads((study / "attempts" / manifest["attempt_id"] / "attempt.json").read_text())
        assert stored == manifest
        assert (study / "attempts" / manifest["attempt_id"] / "attempt.json").read_bytes() == canonical.dumps(manifest)
        assert manifest["request_id"] == f"ml-dev-{config}"
        assert manifest["operation"] == "execute" and manifest["mode"] == "native_ml"
        assert manifest["technical_status"] == "completed" and manifest["finished_at"] and manifest["started_at"]
        assert manifest["outcome_unknown"] is False and manifest["retry_of"] is None
        assert manifest["effective_config_digest"] == canonical.digest(manifest["effective_config"])


def test_attempt_id_is_a_uuid_and_two_requests_of_identical_inputs_are_two_attempts(tmp_path):
    study, _ = init_study(tmp_path)
    _, one, _ = run_ml(study, "seasonal_7", "dev", "r1")
    _, two, _ = run_ml(study, "seasonal_7", "dev", "r2")
    first, second = one["attempt"], two["attempt"]
    assert uuid.UUID(first["attempt_id"]).version == 4 and uuid.UUID(second["attempt_id"]).version == 4
    assert first["attempt_id"] != second["attempt_id"]
    assert first["effective_config_digest"] == second["effective_config_digest"]  # same inputs, still two Attempts


def test_effective_config_holds_the_mode_the_configuration_the_protocol_the_input_digests_the_parameters_and_the_bounds(ran):
    study, attempts = ran
    spec = json.loads((study / "study.json").read_text())
    declared = json.loads((BIKE / "workload.json").read_text())["configurations"]
    for config, manifest in attempts.items():
        effective = manifest["effective_config"]
        assert effective["mode"] == "native_ml"
        assert effective["configuration"]["id"] == config
        assert effective["configuration"]["declared"] == declared[config]  # the declared content, whatever the key order of the file
        assert effective["protocol"] == {"protocol_id": spec["protocol_id"], "protocol_digest": spec["protocol_digest"]}
        by_role = {entry["ref"]["role"]: entry["ref"]["sha256"] for entry in spec["artifacts"]}
        assert effective["input_digests"] == {
            "dataset": sha256(BIKE / "data" / "day.csv"),
            "population": by_role["memberships"],
            "references": by_role["references"],
        }
        assert effective["partition"] == "dev" and effective["workload"] == "bike_day" and effective["command"] == "run ml"
        assert effective["bounds"] == {"clip_min": 0, "fit_partition": "train"}
    ridge = attempts["ridge_v1"]["effective_config"]["effective_parameters"]
    assert ridge["ridge"]["params"]["alpha"] == 1.0 and ridge["ridge"]["params"]["solver"] == "svd"
    assert attempts["seasonal_7"]["effective_config"]["effective_parameters"] == {"fitted": False, "period_days": 7}


def test_code_environment_holds_python_the_dependency_lock_and_the_code_revision(ran):
    _, attempts = ran
    environment = attempts["ridge_v1"]["code_environment"]
    assert environment["python"].startswith("3.13")
    assert environment["dependency_lock"] == {"path": "uv.lock", "sha256": sha256(Path(__file__).resolve().parents[1] / "uv.lock")}
    revision = environment["code_revision"]
    assert set(revision) == {"commit", "dirty", "local_code_fingerprint"}
    assert revision["commit"] is None or len(revision["commit"]) == 40
    if revision["dirty"]:  # a dirty tree (a pull request in progress) carries the fingerprint of the local code
        assert len(revision["local_code_fingerprint"]) == 64
    else:
        assert revision["local_code_fingerprint"] is None


def git(root, *arguments):
    subprocess.run(
        ["git", "-c", "user.email=t@example.org", "-c", "user.name=t", "-C", str(root), *arguments],
        check=True, capture_output=True,
    )


def test_the_code_revision_names_the_commit_the_dirty_state_and_a_fingerprint_of_the_local_code(tmp_path):
    from hypotrail.core import environment

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("x = 1\n")
    (tmp_path / "uv.lock").write_text("lock\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "first")
    clean = environment.code_revision(tmp_path)
    assert clean["dirty"] is False and clean["local_code_fingerprint"] is None and len(clean["commit"]) == 40
    (tmp_path / "src" / "module.py").write_text("x = 2\n")
    dirty = environment.code_revision(tmp_path)
    assert dirty["commit"] == clean["commit"] and dirty["dirty"] is True and len(dirty["local_code_fingerprint"]) == 64
    (tmp_path / "src" / "module.py").write_text("x = 3\n")
    assert environment.code_revision(tmp_path)["local_code_fingerprint"] != dirty["local_code_fingerprint"]
    (tmp_path / "README.md").write_text("a document is not the code\n")
    git(tmp_path, "checkout", "--", "src/module.py")
    assert environment.code_revision(tmp_path)["dirty"] is False


def test_no_provider_secret_is_written_anywhere_in_the_study_or_printed(tmp_path, monkeypatch):
    secret = "sk-ant-SENTINEL-0123456789"
    for name in ("HYPOTRAIL_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.setenv(name, secret)
    study, _ = init_study(tmp_path)
    code, payload, err = run_ml(study, "ridge_v1", "dev", "secret-check")
    assert code == 0
    blob = b"".join(p.read_bytes() for p in study.rglob("*") if p.is_file()) + json.dumps(payload).encode() + err.encode()
    assert secret.encode() not in blob


# --- AC3: the Observation set --------------------------------------------------------------------------


@pytest.mark.parametrize("config", ["seasonal_7", "ridge_v1"])
def test_the_attempt_yields_exactly_one_observation_set_whose_items_are_the_partitions_items(ran, config):
    study, attempts = ran
    manifest = attempts[config]
    folder = study / "attempts" / manifest["attempt_id"]
    sets = sorted(folder.glob("observation_set*.json"))
    assert len(sets) == 1
    observation_set = json.loads(sets[0].read_text())
    contracts.validate(observation_set)
    assert observation_set["attempt_id"] == manifest["attempt_id"]
    assert (observation_set["domain"], observation_set["origin"], observation_set["mode"]) == ("regression", "generated", "native_ml")
    assert observation_set["unknown_fields"] == []
    spec = json.loads((study / "study.json").read_text())
    memberships = next(e["ref"] for e in spec["artifacts"] if e["ref"]["role"] == "memberships")
    assert observation_set["population_ref"] == memberships
    normalized = rows_of(study / observation_set["normalized_ref"]["path"])
    items = [r["row_id"] for r in rows_of(study / memberships["path"]) if r["partition"] == "dev"]
    assert sorted(r["row_id"] for r in normalized) == sorted(items) and len(items) == 182
    assert {r["status"] for r in normalized} == {"produced"}
    assert sorted(r["path"] for r in observation_set["raw_refs"]) == sorted(
        f"attempts/{manifest['attempt_id']}/{name}" for name in (["predictions.csv"] if config == "seasonal_7" else ["predictions.csv", "sklearn_params.json"])
    )
    assert observation_set["observation_set_id"] and observation_set["provenance"]["configuration"] == config
    assert observation_set["observation_set_id"] != manifest["attempt_id"]
    assert manifest["item_counts"] == {"produced": 182, "failed": 0, "missing": 0}
    assert sum(1 for ref in manifest["output_refs"] if ref["role"] == "observation_set") == 1
    for ref in manifest["output_refs"] + manifest["input_refs"]:
        artifacts.read_verified(study, ref)  # every reference matches its bytes


@pytest.mark.parametrize("config, writer", [("seasonal_7", "seasonal"), ("ridge_v1", "ridge")])
@pytest.mark.parametrize("partition, count", [("dev", 182), ("train", 358), ("public_check", 184)])
def test_the_predictions_are_those_the_library_writes_for_the_same_configuration_and_partition(tmp_path, config, writer, partition, count):
    study, _ = init_study(tmp_path)
    _, payload, _ = run_ml(study, config, partition, "r")
    folder = study / "attempts" / payload["attempt"]["attempt_id"]
    reference = tmp_path / "library"
    if writer == "seasonal":
        from hypotrail.ml.baselines import write_seasonal_baseline

        write_seasonal_baseline(BIKE, reference, config, partition)
    else:
        from hypotrail.ml.ridge import write_outputs

        write_outputs(BIKE, reference, config, partition)
    assert (folder / "predictions.csv").read_bytes() == (reference / "predictions.csv").read_bytes()
    assert len(rows_of(folder / "predictions.csv")) == count
    if writer == "ridge":
        assert (folder / "sklearn_params.json").read_bytes() == (reference / "sklearn_params.json").read_bytes()


def test_a_partition_the_workload_does_not_declare_and_an_undeclared_configuration_are_refused_before_anything_is_written(tmp_path):
    study, _ = init_study(tmp_path)
    before = snapshot(study)
    code, payload, _ = run_ml(study, "seasonal_7", "nope", "r")
    assert code == EXIT_INVALID_INPUT and payload["error"]["code"] == "PARTITION_NOT_DECLARED"
    code, payload, _ = run_ml(study, "nope", "dev", "r")
    assert code == EXIT_INVALID_INPUT and payload["error"]["code"] == "CONFIGURATION_NOT_DECLARED"
    assert snapshot(study) == before


# --- AC7: the data lock ---------------------------------------------------------------------------------


def test_one_altered_byte_of_the_data_is_refused_with_the_verification_code_and_no_attempt_is_written(tmp_path):
    """T01 (SPEC §10)."""
    examples = examples_copy(tmp_path)
    study, _ = init_study(tmp_path, examples=examples)
    data = examples / "bike_day" / "data" / "day.csv"
    content = bytearray(data.read_bytes())
    content[len(content) // 2] ^= 0x01  # one byte, one bit
    data.write_bytes(bytes(content))
    before = snapshot(study)
    with fit_probe(strict=True) as probe:
        code, payload, _ = run_ml(study, "ridge_v1", "dev", "r", "--examples-dir", examples)
    assert code == EXIT_INTEGRITY_REFUSED
    assert payload["error"]["code"] == "DATA_INTEGRITY" and payload["error"]["stage"] == "integrity"
    assert probe.calls == []
    assert snapshot(study) == before and not (study / "attempts").exists()


def test_a_study_artifact_whose_bytes_changed_is_an_integrity_refusal_before_any_computation(tmp_path):
    for relative in ("artifacts/memberships.csv", "artifacts/references.csv", "datasets/day.csv"):
        study, _ = init_study(tmp_path, name="s-" + relative.replace("/", "-"))
        path = study / relative
        path.write_bytes(path.read_bytes() + b"\n")
        with fit_probe(strict=True) as probe:
            code, payload, _ = run_ml(study, "ridge_v1", "dev", "r")
        assert code == EXIT_INTEGRITY_REFUSED, relative
        assert payload["error"]["code"] == "ARTIFACT_INTEGRITY" and payload["error"]["details"]["path"] == relative
        assert probe.calls == [] and not (study / "attempts").exists()


# --- AC8: --json and exit codes --------------------------------------------------------------------------


def test_the_request_id_is_required_for_run(tmp_path):
    study, _ = init_study(tmp_path)
    code, payload, err = run_json("run", "ml", "--study", study, "--config", "seasonal_7", "--partition", "dev")
    assert code == EXIT_INVALID_INPUT and payload["error"]["code"] == "INVALID_ARGUMENTS"
    assert "--request-id" in payload["error"]["message"] and err
    code, payload, _ = run_ml(study, "seasonal_7", "dev", "")
    assert code == EXIT_INVALID_INPUT and payload["error"]["code"] == "REQUEST_ID_EMPTY"
    assert not (study / "attempts").exists()


def test_every_error_has_code_message_stage_and_details_and_diagnostics_go_to_stderr(tmp_path):
    study, _ = init_study(tmp_path)
    for args in (["--config", "nope"], ["--partition", "nope"]):
        base = {"--config": "seasonal_7", "--partition": "dev"}
        base[args[0]] = args[1]
        code, payload, err = run_json("run", "ml", "--study", study, "--request-id", "r", *[x for kv in base.items() for x in kv])
        assert code == EXIT_INVALID_INPUT and payload["ok"] is False
        assert set(payload["error"]) == {"code", "message", "stage", "details"}
        assert payload["error"]["code"] in err  # the human diagnostic is on stderr
    code, payload, _ = run_json("run", "ml", "--study", tmp_path / "none", "--config", "seasonal_7", "--partition", "dev", "--request-id", "r")
    assert code == EXIT_INVALID_INPUT and payload["error"]["code"] == "STUDY_NOT_FOUND"


def test_a_successful_run_ml_prints_exactly_one_json_object_on_stdout(tmp_path, capsys):
    from hypotrail import cli

    study, _ = init_study(tmp_path)
    capsys.readouterr()
    code = cli.main(["run", "ml", "--study", str(study), "--config", "seasonal_7", "--partition", "dev", "--request-id", "r", "--json"])
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)  # the whole of stdout is one object
    assert set(payload) == {"ok", "replayed", "attempt", "observation_set_id"} and payload["replayed"] is False and payload["ok"] is True


# --- AC: request identity -----------------------------------------------------------------------------------------


class Instruments:
    """Fit and prediction replaced by functions that fail when called."""

    def __init__(self, monkeypatch):
        self.calls = []

        def boom(label):
            def fail(*args, **kwargs):
                self.calls.append(label)
                raise AssertionError(f"{label} called")

            return fail

        import hypotrail.ml.baselines
        import hypotrail.ml.ridge

        for module, name in (
            (hypotrail.ml.ridge, "fit_configuration"),
            (hypotrail.ml.ridge, "predict_partition"),
            (hypotrail.ml.ridge, "write_outputs"),
            (hypotrail.ml.baselines, "write_seasonal_baseline"),
            (hypotrail.ml.baselines, "write_predictions"),
            (hypotrail.ml.ridge, "write_predictions"),
        ):
            monkeypatch.setattr(module, name, boom(f"{module.__name__}.{name}"))


@pytest.mark.parametrize("config", ["seasonal_7", "ridge_v1"])
def test_the_same_request_returns_the_recorded_attempt_with_neither_a_fit_nor_a_prediction(tmp_path, monkeypatch, config):
    """T18 (SPEC §10)."""
    study, _ = init_study(tmp_path)
    _, first, _ = run_ml(study, config, "dev", "same")
    before = snapshot(study)
    instruments = Instruments(monkeypatch)
    with fit_probe(strict=True) as probe:
        code, second, _ = run_ml(study, config, "dev", "same")
    assert code == 0 and second["replayed"] is True and first["replayed"] is False
    assert second["attempt"] == first["attempt"]
    assert instruments.calls == [] and probe.calls == []
    assert snapshot(study) == before  # nothing written


def test_a_replay_reads_the_recorded_attempt_back_and_a_changed_output_is_an_integrity_refusal(tmp_path):
    study, _ = init_study(tmp_path)
    _, first, _ = run_ml(study, "seasonal_7", "dev", "same")
    predictions = study / "attempts" / first["attempt"]["attempt_id"] / "predictions.csv"
    predictions.write_bytes(predictions.read_bytes().replace(b"bike-day", b"bike-dax", 1))
    code, payload, _ = run_ml(study, "seasonal_7", "dev", "same")
    assert code == EXIT_INTEGRITY_REFUSED and payload["error"]["code"] == "ARTIFACT_INTEGRITY"


def test_a_recorded_reference_that_leaves_the_study_is_refused_when_the_attempt_is_read_back(tmp_path):
    study, _ = init_study(tmp_path)
    _, first, _ = run_ml(study, "seasonal_7", "dev", "same")
    manifest_path = study / "attempts" / first["attempt"]["attempt_id"] / "attempt.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["output_refs"][0]["path"] = "../elsewhere.csv"
    manifest_path.write_bytes(canonical.dumps(manifest))
    code, payload, _ = run_ml(study, "seasonal_7", "dev", "same")
    assert code == EXIT_INTEGRITY_REFUSED and payload["error"]["code"] == "ARTIFACT_PATH_OUTSIDE_STUDY"


def conflict(study, *args, **more):
    before = snapshot(study)
    code, payload, _ = run_ml(study, *args, *more.get("extra", []))
    assert code == EXIT_LOCK_OR_CONFLICT, payload
    assert payload["error"]["code"] == "REQUEST_CONFLICT" and payload["error"]["stage"] == "request"
    assert snapshot(study) == before  # nothing written
    assert payload["error"]["details"]["decision_id"] is None and payload["error"]["details"]["attempt_id"]  # #109 Tightened K: it names an Attempt, no decision
    return payload["error"]["details"]


def test_the_same_request_id_with_another_configuration_or_partition_is_a_conflict_that_writes_nothing(tmp_path):
    """T18 (SPEC §10)."""
    study, _ = init_study(tmp_path)
    _, first, _ = run_ml(study, "seasonal_7", "dev", "same")
    details = conflict(study, "ridge_v1", "dev", "same")
    assert details["differs"] == ["configuration"] and details["attempt_id"] == first["attempt"]["attempt_id"]
    assert conflict(study, "seasonal_7", "train", "same")["differs"] == ["partition"]


def test_ridge_alpha_changed_from_1_to_10_under_the_same_name_is_a_conflict(tmp_path):
    examples = examples_copy(tmp_path)
    study, _ = init_study(tmp_path, examples=examples)
    run_ml(study, "ridge_v1", "dev", "same", "--examples-dir", examples)
    declaration = json.loads((examples / "bike_day" / "workload.json").read_text())
    declaration["configurations"]["ridge_v1"]["ridge"]["alpha"] = 10.0
    (examples / "bike_day" / "workload.json").write_text(json.dumps(declaration))
    details = conflict(study, "ridge_v1", "dev", "same", extra=["--examples-dir", examples])
    assert details["differs"] == ["configuration"]
    # the same name with another alpha is a new request under a new request_id, and is not a Protocol change
    code, payload, _ = run_ml(study, "ridge_v1", "dev", "other", "--examples-dir", examples)
    assert code == 0
    assert payload["attempt"]["effective_config"]["configuration"]["declared"]["ridge"]["alpha"] == 10.0


def test_a_changed_input_file_digest_under_the_same_request_id_is_a_conflict(tmp_path):
    examples = examples_copy(tmp_path)
    study, _ = init_study(tmp_path, examples=examples)
    run_ml(study, "seasonal_7", "dev", "same", "--examples-dir", examples)

    def correct(table):  # a changed data file whose lock is rewritten: it verifies, and its digest is another
        row = next(r for r in table if r["dteday"] == "2012-03-15")
        row["cnt"], row["registered"] = str(int(row["cnt"]) + 1), str(int(row["registered"]) + 1)

    changed = examples_copy(tmp_path, rows=correct, name="examples-changed")
    details = conflict(study, "seasonal_7", "dev", "same", extra=["--examples-dir", changed])
    assert details["differs"] == ["input_digests"]


def test_a_changed_code_revision_under_the_same_request_id_is_a_conflict(tmp_path, monkeypatch):
    from hypotrail.core import environment

    study, _ = init_study(tmp_path)
    real = environment.code_revision
    monkeypatch.setattr(environment, "code_revision", lambda root=None: {"commit": "a" * 40, "dirty": False, "local_code_fingerprint": None})
    run_ml(study, "seasonal_7", "dev", "same")
    run_ml(study, "seasonal_7", "dev", "same")  # unchanged revision: replay
    monkeypatch.setattr(environment, "code_revision", lambda root=None: {"commit": "b" * 40, "dirty": False, "local_code_fingerprint": None})
    assert conflict(study, "seasonal_7", "dev", "same")["differs"] == ["code_revision"]
    # the same commit, but a dirty tree, or another fingerprint of the local code, is a conflict too
    monkeypatch.setattr(environment, "code_revision", lambda root=None: {"commit": "a" * 40, "dirty": True, "local_code_fingerprint": "c" * 64})
    assert conflict(study, "seasonal_7", "dev", "same")["differs"] == ["code_revision"]
    monkeypatch.setattr(environment, "code_revision", real)


def test_the_request_identity_names_each_element_that_differs():
    from hypotrail.core import requests

    effective = {
        "command": "run ml", "workload": "bike_day", "configuration": {"id": "a", "declared": {"k": 1}},
        "partition": "dev", "mode": "native_ml", "input_digests": {"dataset": "d"}, "effective_parameters": None,
    }
    environment = {"code_revision": {"commit": "a", "dirty": False, "local_code_fingerprint": None}, "python": "3.13"}
    base = requests.identity(effective, environment)
    assert requests.differences(base, requests.identity({**effective, "effective_parameters": {"x": 1}}, {**environment, "python": "3.14"})) == []
    for key, value in (
        ("command", "run agent"), ("workload", "other"), ("configuration", {"id": "a", "declared": {"k": 2}}),
        ("partition", "train"), ("mode", "scripted_fixture"), ("input_digests", {"dataset": "e"}),
        ("cases", ["D03"]), ("model", "anthropic/other"), ("repeats", 2),
    ):
        assert requests.differences(base, requests.identity({**effective, key: value}, environment)) == [key]
    other = {**environment, "code_revision": {"commit": "b", "dirty": False, "local_code_fingerprint": None}}
    assert requests.differences(base, requests.identity(effective, other)) == ["code_revision"]


def test_a_wanted_rerun_uses_a_new_request_id_with_retry_of_and_the_earlier_attempt_is_unchanged(tmp_path):
    study, _ = init_study(tmp_path)
    _, first, _ = run_ml(study, "seasonal_7", "dev", "same")
    earlier = snapshot(study / "attempts" / first["attempt"]["attempt_id"])
    code, second, _ = run_ml(study, "seasonal_7", "dev", "again", "--retry-of", first["attempt"]["attempt_id"])
    assert code == 0 and second["replayed"] is False
    assert second["attempt"]["retry_of"] == first["attempt"]["attempt_id"]
    assert second["attempt"]["attempt_id"] != first["attempt"]["attempt_id"]
    assert snapshot(study / "attempts" / first["attempt"]["attempt_id"]) == earlier  # same digests
    code, payload, _ = run_ml(study, "seasonal_7", "dev", "third", "--retry-of", "no-such-attempt")
    assert code == EXIT_INVALID_INPUT and payload["error"]["code"] == "RETRY_OF_UNKNOWN"


def test_a_protocol_changed_since_init_is_refused_for_a_new_request(tmp_path):
    study, _ = init_study(tmp_path)

    def shift(declaration):
        declaration["partitions"]["dev"][1] = "2012-06-29"
        declaration["partitions"]["public_check"][0] = "2012-06-30"

    changed = examples_copy(tmp_path, edit=shift)
    before = snapshot(study)
    code, payload, _ = run_ml(study, "seasonal_7", "dev", "r", "--examples-dir", changed)
    assert code == EXIT_INTEGRITY_REFUSED and payload["error"]["code"] == "PROTOCOL_CHANGED"
    assert snapshot(study) == before


def test_the_key_order_of_a_declaration_changes_neither_the_effective_config_digest_nor_the_request(tmp_path):
    def reorder(declaration):
        ridge = declaration["configurations"]["ridge_v1"]
        declaration["configurations"]["ridge_v1"] = dict(reversed(list(ridge.items())))
        declaration["configurations"]["ridge_v1"]["ridge"] = dict(reversed(list(ridge["ridge"].items())))

    reordered = examples_copy(tmp_path, edit=reorder)
    assert sha256(reordered / "bike_day" / "workload.json") != sha256(BIKE / "workload.json")
    study, _ = init_study(tmp_path)
    _, plain, _ = run_ml(study, "ridge_v1", "dev", "same")
    code, again, _ = run_ml(study, "ridge_v1", "dev", "same", "--examples-dir", reordered)
    assert code == 0 and again["replayed"] is True  # no false conflict from the key order
    code, other, _ = run_ml(study, "ridge_v1", "dev", "other", "--examples-dir", reordered)
    assert code == 0
    assert other["attempt"]["effective_config_digest"] == plain["attempt"]["effective_config_digest"]
    declaration_refs = lambda m: [r for r in m["input_refs"] if r["role"] == "workload_declaration"]
    assert declaration_refs(other["attempt"])[0]["sha256"] != declaration_refs(plain["attempt"])[0]["sha256"]  # source files: bytes, separately


# --- AC6: an interrupted write ---------------------------------------------------------------------------------------

KILL = textwrap.dedent(
    """
    import os, sys
    from hypotrail import cli

    kill_at, replaced = int(sys.argv[1]), [0]
    real = os.replace

    def counting_replace(source, target, *args, **kwargs):
        if "write_journal" in str(target):  # the write journal's entries are not publications of the Attempt
            return real(source, target, *args, **kwargs)
        replaced[0] += 1
        if replaced[0] == kill_at:
            os._exit(9)  # the writing process dies at this publication
        return real(source, target, *args, **kwargs)

    os.replace = counting_replace
    sys.exit(cli.main(["run", "ml", "--study", sys.argv[2], "--config", sys.argv[3], "--partition", "dev", "--request-id", "killed", "--json"]))
    """
)


def killed(tmp_path, kill_at, config="seasonal_7"):
    study, _ = init_study(tmp_path)
    result = subprocess.run([sys.executable, "-c", KILL, str(kill_at), str(study), config], capture_output=True, text=True)
    assert result.returncode == 9, result.stderr
    folders = list((study / "attempts").iterdir())
    assert len(folders) == 1
    return study, folders[0]


def test_a_write_stopped_before_publication_finds_no_artifact_under_its_final_path_and_no_terminal_manifest(tmp_path):
    study, folder = killed(tmp_path, kill_at=3)  # the first output is about to be published
    assert not (folder / "predictions.csv").exists()
    manifest = json.loads((folder / "attempt.json").read_text())
    assert manifest["technical_status"] == "running" and manifest["finished_at"] is None
    contracts.validate(manifest)


def test_a_write_stopped_before_the_terminal_manifest_keeps_the_published_artifacts_and_invents_no_completed_state(tmp_path):
    study, folder = killed(tmp_path, kill_at=6)  # everything is published, the terminal manifest is not
    assert (folder / "predictions.csv").is_file() and (folder / "observation_set.json").is_file()
    manifest = json.loads((folder / "attempt.json").read_text())
    assert manifest["technical_status"] == "running" and manifest["finished_at"] is None
    assert "item_counts" not in manifest


def test_the_same_request_id_after_an_interruption_returns_the_recorded_attempt_without_recomputing(tmp_path, monkeypatch):
    study, folder = killed(tmp_path, kill_at=6)
    before = snapshot(study)
    instruments = Instruments(monkeypatch)
    code, payload, _ = run_json("run", "ml", "--study", study, "--config", "seasonal_7", "--partition", "dev", "--request-id", "killed")
    assert code == 0 and payload["replayed"] is True and payload["attempt"]["technical_status"] == "running"
    assert instruments.calls == [] and snapshot(study) == before


def test_run_ml_reads_the_declaration_through_the_one_loader_and_refuses_what_the_schema_refuses(tmp_path):
    study, _ = init_study(tmp_path)
    examples = examples_copy(tmp_path, edit=lambda declaration: declaration.update(period_k=0))
    before = snapshot(study)
    code, payload, _ = run_ml(study, "seasonal_7", "dev", "r", "--examples-dir", examples)
    assert code == EXIT_INVALID_INPUT
    assert (payload["error"]["code"], payload["error"]["stage"]) == ("DECLARATION_VALUE_NOT_ALLOWED", "declaration")
    assert payload["error"]["details"]["key"] == "period_k"
    assert snapshot(study) == before
