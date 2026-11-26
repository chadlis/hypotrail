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
# The Protocol digest of `init --workload chinook` on the Chinook Workload as it is on main at 64b77d4, computed on that commit,
# without #264's change to `init`. (At 9d443aa, before main's Chinook Workload declared its resampling, it was d6d1d70b….)
CHINOOK_PROTOCOL_AT_MAIN = "eca303c62ef111f0e516278e53733ffb39fa973e503050b3654b3938e26a66c3"


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


def test_init_of_the_chinook_workload_keeps_the_protocol_digest_it_has_on_main(tmp_path):
    code, payload, err = run_json("init", "--workload", "chinook", "--study", tmp_path / "chinook")
    assert code == 0, (payload, err)
    assert payload["study"]["protocol_digest"] == CHINOOK_PROTOCOL_AT_MAIN


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


# --- a data manifest that does not match its schema ---------------------------------------------------------------------------


MALFORMED_MANIFESTS = {
    "no sources": (lambda manifest: manifest.pop("sources"), ""),
    "sources not a list": (lambda manifest: manifest.update(sources={}), "sources"),
    "a source without its notice": (lambda manifest: manifest["sources"][0].pop("notice"), "sources.0"),
}


def malformed_manifest(tmp_path, edit) -> Path:
    """A copy of `examples/` whose `chinook_prose` data manifest is changed by `edit`."""
    target = Path(tmp_path) / "malformed"
    shutil.copytree(EXAMPLES, target)
    path = target / "chinook_prose" / core_data.MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    edit(manifest)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return target


@pytest.mark.parametrize("fault", list(MALFORMED_MANIFESTS))
def test_data_verify_and_init_refuse_a_data_manifest_that_does_not_match_its_schema_with_data_manifest_invalid(tmp_path, fault):
    edit, path = MALFORMED_MANIFESTS[fault]
    examples = malformed_manifest(tmp_path, edit)
    code, payload, err = verify(examples, "chinook_prose")
    assert (code, payload.get("error", {}).get("code")) == (2, "DATA_MANIFEST_INVALID"), (payload, err)
    assert (payload["error"]["details"]["workload"], payload["error"]["details"]["path"]) == ("chinook_prose", path)
    study = tmp_path / "study"
    code, payload, err = init_prose(tmp_path, "--examples-dir", examples, name="study")
    assert (code, payload.get("error", {}).get("code")) == (2, "DATA_MANIFEST_INVALID"), (payload, err)
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


# --- the review record of the References (D-131 on chadlis/hypotrail#75, conditions 1 and 4) ----------------------------------


def jsonl(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_review_record_holds_one_agreed_line_per_case_whose_two_writers_sql_give_one_table_and_whose_reference_rule_is_writer_as():
    from hypotrail.core.data import open_sqlite_readonly

    header, *lines = jsonl(PROSE / "review" / "chinook-prose-references.review.jsonl")
    assert header["record"] == "header"
    cases = [case["case_id"] for name in ("chinook-prose-dev.jsonl", "chinook-prose-public-check.jsonl") for case in jsonl(PROSE / "cases" / name)]
    references = {r["case_id"]: r for r in jsonl(PROSE / "references" / "chinook-prose-references.jsonl")}
    assert [line["case_id"] for line in lines] == cases == list(references)
    connection = open_sqlite_readonly(EXAMPLES / "chinook" / "data" / "Chinook_Sqlite.sqlite")
    try:
        for line in lines:
            a, b = line["writer_a"], line["writer_b"]
            assert a["status"] == b["status"] == references[line["case_id"]]["expected_outcome"], line["case_id"]
            if a["status"] == "answered":
                assert connection.execute(a["sql"]).fetchall() == connection.execute(b["sql"]).fetchall(), line["case_id"]
                assert line["tables_equal"] is True, line["case_id"]
            assert {fact["rule"] for fact in references[line["case_id"]]["expected_facts"]} <= {a["sql"]}, line["case_id"]
            assert line["outcome"] == "agreed", line["case_id"]
    finally:
        connection.close()
