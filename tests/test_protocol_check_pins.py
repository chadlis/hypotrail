"""Pins of the Protocol check, written before the Attempt writers and the Protocol check move, and kept unchanged by the changes that move them.

Each pin goes through the command line, as a user does: what `PROTOCOL_CHANGED` says on each of its five paths (`run ml`, `import ml`, `run agent`,
`import agent`, and the Exposure path that `assess` reaches), where the check comes in each writer's order, and which database digest each agent path takes.
No provider is called: `run agent` runs in `scripted_fixture` mode, and every refusal here comes before an Episode would run.
The Chinook digests pinned here are those of the kit's Workload, so the Chinook pins run on the frozen revision-1 Workload (`--examples-dir`).
"""

import json
import sys
from pathlib import Path

from _chinook_helpers import FIXTURE, database_of, episodes_file, fixture_population, import_agent, init_chinook, revision_one_examples, spec_of, write_lines
from _exposure_helpers import PUBLIC_CASES, REPEATS, assess_agent, correct_e01, edit_chinook_references, freezes, public_lines
from _import_helpers import import_ml, ready
from _run_agent_helpers import fixture
from _study_helpers import EXAMPLES, before_resampling_examples, examples_copy, init_study, run_ml, sha256

BIKE_PROTOCOL = "8c814f87519549fd33f1ccbbe342530d11e207e2ac5493c5a8b2f09f3fe13243"
BIKE_PROTOCOL_SHIFTED = "f3a2abbb9b3a1c44ccbfe1d47189d28aa767fc8c38c5e67604520a3c036e45d4"
# The digest of the Bike Workload before it declared `resampling` (`tests/fixtures/bike-before-resampling/`): every Study made on it keeps it.
BIKE_PROTOCOL_UNDECLARED = "d4a1c2cbeb43025f6d3de1be6cc4375b83b0307d928cbb7fadf26f58fd78a6f0"
CHINOOK_PROTOCOL = "aaea8fd070708b5952c408228467b5bfcb3ed77f3eef582d15cd88a9223c3f61"
CHINOOK_PROTOCOL_E01_CORRECTED = "f5915c74b47e2e21dfbfbc469cc4e14a6b1b6f12c3c9e664a370c2d33301227d"

ML_MESSAGE = "the Workload's Protocol is no longer the one of this Study (Partitions, population, References or rules)"
AGENT_MESSAGE = "the Workload's Protocol is no longer the one of this Study (Cases, References, answer schema, database or primary Criterion)"
EXPOSURE_MESSAGE = (
    "the Workload's Protocol is no longer the one of this Study's current revision: a Protocol change is made with `init --new-revision`"
)


def shift(declaration):
    """The Bike Partitions moved by one day: a changed Protocol."""
    declaration["partitions"]["dev"][1] = "2012-06-29"
    declaration["partitions"]["public_check"][0] = "2012-06-30"


def refusal(result) -> dict:
    code, payload, err = result
    assert (code, payload["ok"]) == (3, False), (payload, err)
    return payload["error"]


def code_of(result) -> str:
    _, payload, err = result
    assert payload["ok"] is False, (payload, err)
    return payload["error"]["code"]


def not_json(tmp_path, name) -> Path:
    path = Path(tmp_path) / name
    path.write_bytes(b"not json")
    return path


def bike_details() -> dict:
    return {"expected_protocol_digest": BIKE_PROTOCOL, "actual_protocol_digest": BIKE_PROTOCOL_SHIFTED}


def chinook_details() -> dict:
    return {"expected_protocol_digest": CHINOOK_PROTOCOL, "actual_protocol_digest": CHINOOK_PROTOCOL_E01_CORRECTED}


# --- what `PROTOCOL_CHANGED` says on each of its five paths ---------------------------------------------------------------------


def test_run_ml_refuses_a_changed_protocol_with_its_code_message_stage_and_details(tmp_path):
    study, _ = init_study(tmp_path)
    error = refusal(run_ml(study, "seasonal_7", "dev", "r", "--examples-dir", examples_copy(tmp_path, edit=shift)))
    assert error["code"] == "PROTOCOL_CHANGED"
    assert error["message"] == ML_MESSAGE
    assert error["stage"] == "request"
    assert error["details"] == bike_details()


def test_import_ml_refuses_a_changed_protocol_with_its_code_message_stage_and_details(tmp_path):
    study, _ = init_study(tmp_path)
    source, mapping, population, _ = ready(tmp_path)
    error = refusal(import_ml(study, source, mapping, population, "i", "--examples-dir", examples_copy(tmp_path, edit=shift)))
    assert error["code"] == "PROTOCOL_CHANGED"
    assert error["message"] == ML_MESSAGE
    assert error["stage"] == "request"
    assert error["details"] == bike_details()


def kit_study(tmp_path):
    """A Chinook Study made by `init` on the frozen revision-1 Workload, and that Workload's folder."""
    examples = revision_one_examples(tmp_path)
    study, _ = init_chinook(tmp_path, examples=examples)
    return study, examples


def kit_corrected(tmp_path, examples):
    return edit_chinook_references(tmp_path, correct_e01, base=examples)


def test_run_agent_refuses_a_changed_protocol_with_its_code_message_stage_and_details(tmp_path):
    study, examples = kit_study(tmp_path)
    error = refusal(fixture(study, "plain", "r", "--examples-dir", kit_corrected(tmp_path, examples)))
    assert error["code"] == "PROTOCOL_CHANGED"
    assert error["message"] == AGENT_MESSAGE
    assert error["stage"] == "request"
    assert error["details"] == chinook_details()


def test_import_agent_refuses_a_changed_protocol_with_its_code_message_stage_and_details(tmp_path):
    study, examples = kit_study(tmp_path)
    corrected = kit_corrected(tmp_path, examples)
    error = refusal(import_agent(study, FIXTURE, fixture_population(tmp_path), "i", "--examples-dir", corrected))
    assert error["code"] == "PROTOCOL_CHANGED"
    assert error["message"] == AGENT_MESSAGE
    assert error["stage"] == "request"
    assert error["details"] == chinook_details()


def import_public(tmp_path, study, name, *more) -> dict:
    """The Attempt of an Import of the 12 public_check Cases x 3 Repeats, with `more` given to `import agent`."""
    source = write_lines(Path(tmp_path) / f"{name}.jsonl", public_lines())
    keys = [(case_id, repeat) for case_id in PUBLIC_CASES for repeat in range(REPEATS)]
    code, payload, err = import_agent(study, source, episodes_file(tmp_path, keys, name=f"{name}-population.json"), name, *more)
    assert code == 0, (payload, err)
    return payload["attempt"]


def test_the_exposure_path_refuses_a_changed_protocol_with_its_code_message_stage_and_details(tmp_path):
    study, examples = kit_study(tmp_path)
    attempt = import_public(tmp_path, study, "imp", "--examples-dir", examples)
    error = refusal(assess_agent(study, attempt, "--examples-dir", kit_corrected(tmp_path, examples)))
    assert error["code"] == "PROTOCOL_CHANGED"
    assert error["message"] == EXPOSURE_MESSAGE
    assert error["stage"] == "exposure"
    assert error["details"] == chinook_details()


# --- where the Protocol check comes in each writer's order ------------------------------------------------------------------------


def test_import_ml_checks_the_protocol_before_the_mapping(tmp_path):
    study, _ = init_study(tmp_path)
    source, _, population, _ = ready(tmp_path)
    mapping = not_json(tmp_path, "mapping.json")
    assert code_of(import_ml(study, source, mapping, population, "both", "--examples-dir", examples_copy(tmp_path, edit=shift))) == "PROTOCOL_CHANGED"
    assert code_of(import_ml(study, source, mapping, population, "mapping")) == "MAPPING_INVALID"


def test_import_agent_checks_the_protocol_before_the_population(tmp_path):
    study, _ = init_chinook(tmp_path)
    population = not_json(tmp_path, "population.json")
    corrected = edit_chinook_references(tmp_path, correct_e01)
    assert code_of(import_agent(study, FIXTURE, population, "both", "--examples-dir", corrected)) == "PROTOCOL_CHANGED"
    assert code_of(import_agent(study, FIXTURE, population, "population")) == "POPULATION_INVALID"


def test_run_agent_checks_the_protocol_before_inspect_being_available(tmp_path, monkeypatch):
    study, _ = init_chinook(tmp_path)
    corrected = edit_chinook_references(tmp_path, correct_e01)
    monkeypatch.setitem(sys.modules, "inspect_ai", None)
    assert code_of(fixture(study, "plain", "both", "--examples-dir", corrected)) == "PROTOCOL_CHANGED"
    assert code_of(fixture(study, "plain", "inspect")) == "INSPECT_UNAVAILABLE"


def test_run_ml_refused_for_a_changed_protocol_writes_no_running_manifest_and_no_journal_entry(tmp_path):
    study, _ = init_study(tmp_path)
    journal = sorted(path.name for path in (study / "write_journal").iterdir())
    assert code_of(run_ml(study, "seasonal_7", "dev", "r", "--examples-dir", examples_copy(tmp_path, edit=shift))) == "PROTOCOL_CHANGED"
    assert sorted((study / "attempts").glob("*/attempt.json")) == []
    assert sorted(path.name for path in (study / "write_journal").iterdir()) == journal


# --- the database digest each agent path takes ----------------------------------------------------------------------------------


def with_changed_database(tmp_path) -> Path:
    """A copy of the frozen revision-1 Workload whose Chinook database has one more byte, with its lock entry rewritten so that the data
    verification passes."""
    examples = revision_one_examples(tmp_path, name="changed-database")
    database = database_of(examples)
    database.write_bytes(database.read_bytes() + b"x")
    lock_path = examples / "chinook" / "data-sources.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    for source in lock["sources"]:
        if source["local_path"] == "data/Chinook_Sqlite.sqlite":
            source["sha256"], source["size_bytes"] = sha256(database), database.stat().st_size
    lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
    return examples


def test_run_agent_hashes_the_live_database_and_refuses_a_changed_one_with_protocol_changed(tmp_path):
    study, _ = kit_study(tmp_path)
    assert code_of(fixture(study, "plain", "r", "--examples-dir", with_changed_database(tmp_path))) == "PROTOCOL_CHANGED"


def test_import_agent_takes_the_studys_copy_of_the_database_and_is_not_refused_for_a_changed_live_one(tmp_path):
    study, _ = kit_study(tmp_path)
    code, payload, err = import_agent(study, FIXTURE, fixture_population(tmp_path), "i", "--examples-dir", with_changed_database(tmp_path))
    assert (code, payload["ok"]) == (0, True), (payload, err)


def test_the_freeze_basis_records_the_protocol_digest_of_the_studys_copy_of_the_database_with_dataset_source_study_copy(tmp_path):
    study, _ = kit_study(tmp_path)
    changed = with_changed_database(tmp_path)
    attempt = import_public(tmp_path, study, "imp", "--examples-dir", changed)
    code, payload, err = assess_agent(study, attempt, "--examples-dir", changed)
    assert code == 0, (payload, err)
    [freeze] = freezes(study)
    assert (freeze["protocol_digest"], freeze["dataset_source"]) == (CHINOOK_PROTOCOL, "study_copy")
    assert spec_of(study)["protocol_digest"] == CHINOOK_PROTOCOL


# --- the declared resampling and the Protocol digest ---------------------------------------------------------------------------


def test_a_chinook_workload_that_declares_no_resampling_keeps_its_earlier_protocol_digest_and_the_live_one_gives_another(tmp_path):
    from hypotrail.agentic.declaration import load_workload
    from hypotrail.agentic.study import protocol_content

    study, examples = kit_study(tmp_path)  # the frozen revision-1 Workload, which declares no `resampling`
    assert spec_of(study)["protocol_digest"] == CHINOOK_PROTOCOL and "resampling" not in spec_of(study)
    assert "resampling" not in protocol_content(load_workload(examples / "chinook"), dataset_sha256=sha256(database_of(examples)))
    live, _ = init_chinook(tmp_path, name="live-study")
    assert spec_of(live)["protocol_digest"] != CHINOOK_PROTOCOL
    assert spec_of(live)["resampling"] == load_workload(EXAMPLES / "chinook").declaration["resampling"]


def test_the_bike_workload_of_before_resampling_keeps_its_earlier_protocol_digest_and_the_live_one_gives_another(tmp_path):
    from hypotrail.ml.declaration import load_declaration
    from hypotrail.ml.study import protocol_content

    examples = before_resampling_examples(tmp_path)
    undeclared, _ = init_study(tmp_path, examples=examples, name="undeclared-study")
    assert spec_of(undeclared)["protocol_digest"] == BIKE_PROTOCOL_UNDECLARED and "resampling" not in spec_of(undeclared)
    content = protocol_content(load_declaration(examples / "bike_day"), dataset_sha256="0" * 64, memberships_sha256="0" * 64, references_sha256="0" * 64)
    assert "resampling" not in content
    live, _ = init_study(tmp_path, name="live-study")
    assert spec_of(live)["protocol_digest"] == BIKE_PROTOCOL != BIKE_PROTOCOL_UNDECLARED
    assert spec_of(live)["resampling"] == json.loads((EXAMPLES / "bike_day" / "workload.json").read_text(encoding="utf-8"))["resampling"]
