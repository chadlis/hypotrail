"""A Workload whose data lives outside the repository: a data manifest of digests in place of a database (#264).

`chinook_prose` declares the Chinook 1.4.5 bytes by their digest and size and never opens them: `data verify` reports the
source `declared`, `init` keeps a copy of the manifest in the Study, `run agent` is refused, and `import agent` records an
Import. No provider is called and no key is set.
"""

import json
import shutil
from pathlib import Path

import pytest
from _chinook_helpers import episodes_file, import_agent, spec_of, write_lines
from _run_agent_helpers import agent, live_args, refuse_provider
from _study_helpers import EXAMPLES, run_json, sha256

from hypotrail.core import canonical
from hypotrail.core import data as core_data

PROSE = EXAMPLES / "chinook_prose"
MANIFEST = PROSE / "data-manifest.json"
# The Protocol digest of `init --workload chinook` on the Chinook Workload as it is at 9d443aa, computed before #264 changed `init`.
CHINOOK_PROTOCOL_AT_9D443AA = "d6d1d70b197dc8720797f60a664dd5499c78358ad41d65631658cad5d94a7778"


def init_prose(tmp_path, *more, name="prose"):
    return run_json("init", "--workload", "chinook_prose", "--study", Path(tmp_path) / name, *more)


def prose_study(tmp_path, *more):
    code, payload, err = init_prose(tmp_path, *more)
    assert code == 0, (payload, err)
    return Path(tmp_path) / "prose", payload["study"]


def protocol_of(study: Path) -> dict:
    """The Protocol content `init` digested, recomputed from the Workload as `init` reads it."""
    from hypotrail.agentic.declaration import load_workload
    from hypotrail.agentic.study import dataset_sha256, protocol_content

    content = protocol_content(load_workload(PROSE), dataset_sha256=dataset_sha256(spec_of(study)))
    assert canonical.digest(content) == spec_of(study)["protocol_digest"]
    return content


def examples_without_chinook(tmp_path, *, edit_notice=None, remove_notice=False) -> Path:
    """A copy of `examples/` without the Chinook database file, its notice of `chinook_prose` changed or removed."""
    target = Path(tmp_path) / "examples"
    shutil.copytree(EXAMPLES, target)
    (target / "chinook" / "data" / "Chinook_Sqlite.sqlite").unlink()
    notice = target / "chinook_prose" / "licenses" / "Chinook-MIT.txt"
    if edit_notice is not None:
        notice.write_bytes(notice.read_bytes() + edit_notice)
    if remove_notice:
        notice.unlink()
    return target


def verify(examples, *workloads):
    args = ["data", "verify", "--examples-dir", examples]
    for workload in workloads:
        args += ["--workload", workload]
    return run_json(*args)


def twice_declared(tmp_path) -> Path:
    """A copy of `examples/` whose Chinook Workload, which declares a database and has a lock, also holds a data manifest."""
    target = Path(tmp_path) / "twice"
    shutil.copytree(EXAMPLES, target)
    shutil.copyfile(MANIFEST, target / "chinook" / core_data.MANIFEST_NAME)
    return target


def write_sequence(study) -> int:
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    return payload["write_sequence"]


# --- criterion 1: the Chinook and Bike digests -------------------------------------------------------------------------------


def test_init_of_the_chinook_workload_keeps_the_protocol_digest_it_had_at_9d443aa(tmp_path):
    code, payload, err = run_json("init", "--workload", "chinook", "--study", tmp_path / "chinook")
    assert code == 0, (payload, err)
    assert payload["study"]["protocol_digest"] == CHINOOK_PROTOCOL_AT_9D443AA


# --- criterion 2: `init` of a manifest Workload --------------------------------------------------------------------------------


def test_init_of_chinook_prose_keeps_the_manifest_as_role_data_manifest_and_no_dataset(tmp_path):
    study, spec = prose_study(tmp_path)
    roles = [ref["role"] for ref in spec["dataset_refs"]]
    assert "data_manifest" in roles
    assert "dataset" not in roles
    [ref] = spec["dataset_refs"]
    assert ref["sha256"] == sha256(MANIFEST)
    assert (study / ref["path"]).read_bytes() == MANIFEST.read_bytes()


def test_the_protocol_of_chinook_prose_holds_the_manifest_digest_and_no_dataset_or_answer_schema_digest(tmp_path):
    study, _ = prose_study(tmp_path)
    content = protocol_of(study)
    assert content["data_manifest_sha256"] == sha256(MANIFEST)
    assert "dataset_sha256" not in content
    assert "answer_schema_sha256" not in content


# --- criterion 3: `data verify` of a manifest Workload -----------------------------------------------------------------------


def test_data_verify_reports_chinook_prose_declared_with_the_chinook_database_file_absent(tmp_path):
    code, payload, err = verify(examples_without_chinook(tmp_path), "bike_day", "chinook_prose")
    assert code == 0, (payload, err)
    [declared] = [d for d in payload["datasets"] if d["workload"] == "chinook_prose"]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["sources"][0]
    assert declared["status"] == "declared"
    assert (declared["sha256"], declared["size_bytes"]) == (manifest["sha256"], manifest["size_bytes"])


def test_data_verify_of_chinook_prose_opens_no_data_file(tmp_path, monkeypatch):
    opened = []
    for name in ("sha256_file", "open_sqlite_readonly", "check_sqlite_tables", "check_daily_series"):
        original = getattr(core_data, name)

        def spy(path, *args, _original=original, **kwargs):
            opened.append(Path(path).name)
            return _original(path, *args, **kwargs)

        monkeypatch.setattr(core_data, name, spy)
    code, payload, err = verify(examples_without_chinook(tmp_path), "chinook_prose")
    assert code == 0, (payload, err)
    assert opened == ["Chinook-MIT.txt"]  # the notice is hashed; no data file is


@pytest.mark.parametrize(
    ("state", "expected"),
    [("changed", (3, "LICENCE_NOTICE_CHANGED")), ("missing", (3, "LICENCE_NOTICE_MISSING"))],
)
def test_data_verify_of_chinook_prose_refuses_a_changed_or_missing_notice(tmp_path, state, expected):
    examples = examples_without_chinook(tmp_path, edit_notice=b"x" if state == "changed" else None, remove_notice=state == "missing")
    code, payload, err = verify(examples, "bike_day", "chinook_prose")
    assert (code, payload.get("error", {}).get("code")) == expected, (payload, err)
    assert payload["error"]["details"]["workload"] == "chinook_prose"


def test_the_committed_data_manifests_match_their_schema():
    from importlib import resources

    from jsonschema import Draft202012Validator

    schema = json.loads(resources.files("hypotrail.core").joinpath("data-manifest.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    manifests = sorted(EXAMPLES.glob(f"*/{core_data.MANIFEST_NAME}"))
    assert manifests == [MANIFEST]
    for path in manifests:
        assert list(Draft202012Validator(schema).iter_errors(json.loads(path.read_text(encoding="utf-8")))) == []


def test_the_chinook_prose_manifest_declares_the_chinook_bytes_of_the_chinook_lock():
    lock = json.loads((EXAMPLES / "chinook" / core_data.LOCK_NAME).read_text(encoding="utf-8"))["sources"][0]
    [source] = json.loads(MANIFEST.read_text(encoding="utf-8"))["sources"]
    assert (source["dataset_id"], source["sha256"], source["size_bytes"]) == (lock["dataset_id"], lock["sha256"], lock["size_bytes"])
    assert "url" not in json.dumps(source) and "local_path" not in source


# --- criterion 4: DATA_DECLARED_TWICE ------------------------------------------------------------------------------------------


def test_data_verify_refuses_a_workload_that_declares_a_database_and_a_manifest(tmp_path):
    code, payload, err = verify(twice_declared(tmp_path), "chinook")
    assert (code, payload.get("error", {}).get("code")) == (2, "DATA_DECLARED_TWICE"), (payload, err)


def test_init_refuses_a_workload_that_declares_a_database_and_a_manifest_before_anything_is_written(tmp_path):
    study = tmp_path / "study"
    code, payload, err = run_json("init", "--workload", "chinook", "--study", study, "--examples-dir", twice_declared(tmp_path))
    assert (code, payload.get("error", {}).get("code")) == (2, "DATA_DECLARED_TWICE"), (payload, err)
    assert not study.exists()


# --- criterion 5: DATABASE_NOT_DECLARED -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode_args",
    [
        ["--mode", "scripted_fixture", "--config", "external", "--request-id", "r"],
        live_args("external", "r", cases=["D01"]),
    ],
    ids=["scripted_fixture", "llm_live"],
)
def test_run_agent_on_a_chinook_prose_study_is_refused_database_not_declared_and_writes_nothing(tmp_path, monkeypatch, mode_args):
    monkeypatch.delenv("HYPOTRAIL_ANTHROPIC_API_KEY", raising=False)
    refuse_provider(monkeypatch)
    study, _ = prose_study(tmp_path)
    before = write_sequence(study)
    files = sorted(p.relative_to(study) for p in study.rglob("*"))
    code, payload, err = agent(study, *mode_args)
    assert (code, payload.get("error", {}).get("code")) == (2, "DATABASE_NOT_DECLARED"), (payload, err)
    assert write_sequence(study) == before
    assert sorted(p.relative_to(study) for p in study.rglob("*")) == files


# --- criterion 6: `import agent` onto a manifest Study ---------------------------------------------------------------------------


def test_import_agent_onto_a_chinook_prose_study_records_an_import_whose_dataset_digest_is_the_manifest_copys(tmp_path):
    study, spec = prose_study(tmp_path)
    line = {"case_id": "D01", "repeat": 0, "observation_status": "produced", "raw_answer": "Customer 12 has seven invoices."}
    source = write_lines(tmp_path / "answers.jsonl", [line])
    code, payload, err = import_agent(study, source, episodes_file(tmp_path, [("D01", 0)]), "import-a")
    assert code == 0, (payload, err)
    attempt = payload["attempt"]
    assert attempt["technical_status"] == "completed"
    [manifest_copy] = spec["dataset_refs"]
    assert attempt["effective_config"]["input_digests"]["dataset"] == manifest_copy["sha256"] == sha256(study / manifest_copy["path"])
