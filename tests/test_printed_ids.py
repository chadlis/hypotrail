"""Ticket #219: the four Attempt writers print the Observation set ID they recorded, and the two forms of `init` print the References ID.

"Each of the four Attempt writers prints the Observation set ID it recorded, and each of the two forms of `init` prints the References ID
of the revision it made. The id is in the id line and under one new top-level key of the `--json` object: `observation_set_id` beside
`attempt`, `references_id` beside `study`." (#219, "What to build"). No provider is called: `run agent` runs `llm_live` on Inspect's mock
model, patched as the `run agent` tests do, or `scripted_fixture`.
"""

import json
import re
from pathlib import Path

import pytest
from _assess_helpers import references_id
from _chinook_helpers import FIXTURE, fixture_population, init_chinook
from _import_helpers import ready
from _kept_studies import KEPT, STUDIES, kept_files
from _revision_helpers import corrected_chinook_references, entry_of, error_of, spec_of
from _run_agent_helpers import live_args, patch_model
from _study_helpers import examples_copy, init_study, run_cli, run_json
from test_run_ml import killed
from test_study_revision import bike_rows_with_a_corrected_day, correct_d03
from test_write_sequence import (
    import_agent_scenario,
    import_ml_scenario,
    init_new,
    init_new_revision,
    run_agent_scenario,
    run_ml_scenario,
)

from hypotrail.core import artifacts
from hypotrail.core.errors import EXIT_INVALID_INPUT

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
SCORERS = {"bike_day": "regression_mae_v1", "chinook": "chinook_contract_v1"}


def the_line(out: str) -> str:
    """The one line a command prints on stdout without `--json`."""
    lines = out.splitlines()
    assert len(lines) == 1, out
    return lines[0]


def journal(study) -> list:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((Path(study) / "write_journal").glob("*.json"))]


# --- the four Attempt writers: each is (its Study, the argument list of one new request without `--json`, the Scorer of that Study) -----------
# `run agent` runs `llm_live`: an Observation set of `scripted_fixture` records scenarios, and `assess` refuses it.


def run_ml_request(tmp_path, monkeypatch):
    study, _ = init_study(tmp_path)
    return study, ["run", "ml", "--study", study, "--config", "seasonal_7", "--partition", "dev", "--request-id", "ids-run-ml"], "regression_mae_v1"


def import_ml_request(tmp_path, monkeypatch):
    study, _ = init_study(tmp_path)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source, mapping, population, _ = ready(inputs)
    args = ["import", "ml", "--study", study, "--source", source, "--mapping", mapping, "--population", population, "--request-id", "ids-import-ml"]
    return study, args, "regression_mae_v1"


def run_agent_request(tmp_path, monkeypatch):
    patch_model(monkeypatch)
    study, _ = init_chinook(tmp_path)
    return study, ["run", "agent", "--study", study, *live_args("plain", "ids-run-agent")], "chinook_contract_v1"


def import_agent_request(tmp_path, monkeypatch):
    study, _ = init_chinook(tmp_path)
    args = ["import", "agent", "--study", study, "--source", FIXTURE, "--population", fixture_population(tmp_path), "--request-id", "ids-import-agent"]
    return study, args, "chinook_contract_v1"


ATTEMPT_WRITERS = {"run ml": run_ml_request, "import ml": import_ml_request, "run agent": run_agent_request, "import agent": import_agent_request}


@pytest.mark.parametrize("writer", ATTEMPT_WRITERS)
def test_each_attempt_writer_prints_the_observation_set_id_that_its_journal_entry_lists_and_assess_accepts_and_prints_it_again_when_the_request_is_sent_again(
    writer, tmp_path, monkeypatch
):
    study, args, scorer = ATTEMPT_WRITERS[writer](tmp_path, monkeypatch)
    code, out, err = run_cli(*args)
    assert code == 0, err
    line = the_line(out)
    end = journal(study)[-1]
    assert (end["phase"], end["command"]) == ("end", writer), end
    [journaled] = [written["id"] for written in end["written"] if written["kind"] == "observation_set"]

    code, payload, err = run_json(*args)  # the request sent again
    assert code == 0 and payload["replayed"] is True, (payload, err)
    assert "observation_set_id" in payload, payload
    printed = payload["observation_set_id"]
    assert printed == journaled
    assert f"Observation set {printed}" in line, line

    code, payload, err = run_json("assess", "--study", study, "--observations", printed, "--scorer", scorer, "--references", references_id(study))
    assert code == 0, (payload, err)
    assert payload["assessment"]["observation_set_id"] == printed


# --- an Attempt that recorded no Observation set ------------------------------------------------------------------------------------------


class FailedTerminalWrite:
    """`artifacts.replace_bytes`, patched: the write of the terminal manifest raises an OS error, inside the live process, so the Attempt is left `failed`."""

    def __init__(self, monkeypatch):
        self.real, self.manifests, self.armed = artifacts.replace_bytes, 0, True
        monkeypatch.setattr(artifacts, "replace_bytes", self.replace_bytes)

    def replace_bytes(self, study, relative, data):
        if self.armed and str(relative).endswith("/attempt.json"):
            self.manifests += 1
            if self.manifests == 2:
                raise OSError("disk full")
        return self.real(study, relative, data)


# The writers that print an Attempt whose manifest names no Observation set: a manifest the recorder leaves `failed` names none, and a writer
# prints one only for a request sent again. `import ml`, `run agent` and `import agent` exit 4 on that request (their line reads a key a
# `failed` manifest does not hold), so they print none.
PRINT_AN_ATTEMPT_WITHOUT_ONE = ["run ml"]


@pytest.mark.parametrize("writer", PRINT_AN_ATTEMPT_WITHOUT_ONE)
def test_a_request_sent_again_for_a_failed_attempt_prints_a_null_observation_set_id_and_a_line_that_names_no_observation_set(writer, tmp_path, monkeypatch):
    study, args, _ = ATTEMPT_WRITERS[writer](tmp_path, monkeypatch)
    fault = FailedTerminalWrite(monkeypatch)
    code, out, err = run_cli(*args)
    assert code != 0 and fault.manifests == 3, (out, err)  # the running manifest, the refused terminal one, then the failed one
    fault.armed = False

    code, payload, err = run_json(*args)
    assert code == 0 and payload["replayed"] is True and payload["attempt"]["technical_status"] == "failed", (payload, err)
    assert "observation_set_id" in payload and payload["observation_set_id"] is None
    code, out, err = run_cli(*args)
    assert code == 0, err
    line = the_line(out)
    assert line.endswith("; no Observation set") and not re.search(rf"Observation set {UUID}", line), line


# --- the two forms of `init`, each on a changed copy of its Workload ------------------------------------------------------------------------


def changed_copy(workload, tmp_path):
    if workload == "bike_day":
        return examples_copy(tmp_path, rows=bike_rows_with_a_corrected_day, name="changed")
    return corrected_chinook_references(tmp_path, correct_d03, name="changed")


def init_call(form, workload, tmp_path, changed, name):
    """The argument list, without `--json`, of the `init` call of `form` on `changed`; for `--new-revision`, its Study is first created on `examples/`."""
    study = tmp_path / name
    if form == "init":
        return study, ["init", "--workload", workload, "--study", study, "--examples-dir", changed]
    code, payload, err = run_json("init", "--workload", workload, "--study", study)
    assert code == 0, (payload, err)
    return study, ["init", "--study", study, "--new-revision", "--examples-dir", changed]


def an_observation_set(workload, study, changed, tmp_path) -> str:
    if workload == "bike_day":
        args = ["run", "ml", "--study", study, "--config", "seasonal_7", "--partition", "dev", "--request-id", "ids-init"]
    else:
        args = ["import", "agent", "--study", study, "--source", FIXTURE, "--population", fixture_population(tmp_path), "--request-id", "ids-init"]
    code, payload, err = run_json(*args, "--examples-dir", changed)
    assert code == 0, (payload, err)
    return payload["observation_set_id"]


@pytest.mark.parametrize("workload", ["bike_day", "chinook"])
@pytest.mark.parametrize("form", ["init", "init --new-revision"])
def test_each_form_of_init_prints_the_references_id_of_the_revision_it_made_and_assess_accepts_it(form, workload, tmp_path):
    changed = changed_copy(workload, tmp_path)

    study, args = init_call(form, workload, tmp_path, changed, "json")
    code, payload, err = run_json(*args)
    assert code == 0, (payload, err)
    assert "references_id" in payload, payload
    entry = entry_of(payload["study"], "references")
    assert payload["references_id"] == entry["artifact_id"]
    if form == "init --new-revision":
        assert entry["version"] == 2  # the References of the revision it made, not of the one before
    code, assessed, err = run_json(
        "assess", "--study", study, "--observations", an_observation_set(workload, study, changed, tmp_path), "--scorer", SCORERS[workload],
        "--references", payload["references_id"], "--examples-dir", changed,
    )
    assert code == 0, (assessed, err)
    assert assessed["assessment"]["references_ref"] == entry["ref"]

    study, args = init_call(form, workload, tmp_path, changed, "text")
    code, out, err = run_cli(*args)
    assert code == 0, err
    on_disk = entry_of(spec_of(study), "references")["artifact_id"]
    assert on_disk == payload["references_id"]  # the same changed copy gives the same References, and an artifact's ID names its digest
    assert the_line(out).endswith(f", references_id {on_disk}"), out


# --- nothing else moves ---------------------------------------------------------------------------------------------------------------------

SIX = {
    "init": (init_new, "references_id"),
    "init --new-revision": (init_new_revision, "references_id"),
    "run ml": (run_ml_scenario, "observation_set_id"),
    "run agent": (run_agent_scenario, "observation_set_id"),
    "import ml": (import_ml_scenario, "observation_set_id"),
    "import agent": (import_agent_scenario, "observation_set_id"),
}


@pytest.mark.parametrize("command", SIX)
def test_with_its_new_key_removed_the_json_object_of_each_of_the_six_commands_holds_the_record_on_disk_and_nothing_else(command, tmp_path):
    scenario, key = SIX[command]
    study, act = scenario(tmp_path)
    code, payload, err = act()
    assert code == 0, (payload, err)
    assert key in payload, payload
    rest = {name: value for name, value in payload.items() if name != key}
    if key == "references_id":
        assert rest == {"ok": True, "study": spec_of(study)}
    else:
        manifest = json.loads((Path(study) / "attempts" / payload["attempt"]["attempt_id"] / "attempt.json").read_text(encoding="utf-8"))
        expected = {"ok": True, "replayed": False, "attempt": manifest}
        if command == "run agent":
            expected["warnings"] = []
        assert rest == expected


ADDED_LIMITS = re.compile(r'^ *"(cost_limit_usd": null|parallel_tool_calls": false),\n', re.M)


def without_the_limits_added_after_the_kept_study(path, text):
    """The text of a made file without the two limit lines #234 added, in the one Attempt record and run record that hold limits."""
    if not isinstance(text, str) or not path.endswith(("/attempt.json", "/run.json")) or '"limits"' not in text and '"effective_limits"' not in text:
        return text
    return ADDED_LIMITS.sub("", text)


@pytest.mark.parametrize("name", STUDIES)
def test_the_files_of_a_study_made_by_the_commands_that_print_ids_equal_those_kept_from_main_but_by_their_ids_and_timestamps(name, tmp_path):
    """The kept files were made by the same commands at `main` `07197ea`, before the ids were printed (`tests/_kept_studies.py`).

    Both sides pass through the same rules. Excluded by name, each with its reason: the `observations.jsonl` of the `scripted_fixture` Attempt,
    which holds the latencies its Episodes measured; the Inspect log, a zip archive that holds its own timestamps and identifiers; and the
    `code_environment` fields that name the checkout that ran, `code_revision` (its commit, dirty mark and fingerprint) and the digest of
    `uv.lock`. One more exclusion, made after `07197ea`: the two limits #234 added (`cost_limit_usd` null and `parallel_tool_calls`
    false) are taken out of the limits of the `scripted_fixture` Attempt's `attempt.json` and `run.json`, where they are present. Nothing
    else is excluded.
    """
    kept = json.loads((KEPT / f"{name}.json").read_text(encoding="utf-8"))
    made = {path: without_the_limits_added_after_the_kept_study(path, text) for path, text in kept_files(STUDIES[name](tmp_path)).items()}
    union = sorted(set(kept) | set(made))
    differing = [(path, "kept only" if path not in made else "made only" if path not in kept else "differs") for path in union if kept.get(path) != made.get(path)]
    assert differing == []


# --- the two edge cases: a refused `init --new-revision`, and `recover` ---------------------------------------------------------------------


def test_an_init_new_revision_refused_with_protocol_unchanged_keeps_ok_and_error_as_its_keys_and_prints_no_id(tmp_path):
    study, _ = init_chinook(tmp_path)
    code, payload, err = run_json("init", "--study", study, "--new-revision")
    assert (code, error_of(payload)["code"]) == (EXIT_INVALID_INPUT, "PROTOCOL_UNCHANGED"), (payload, err)
    assert set(payload) == {"ok", "error"}
    code, out, err = run_cli("init", "--study", study, "--new-revision")
    assert code == EXIT_INVALID_INPUT and out == "" and "PROTOCOL_UNCHANGED" in err, (out, err)


RECOVER_LINE = (
    "Attempt {attempt_id} recorded as interrupted (partial artifacts kept; to make it again, record a new Attempt with a new --request-id and"
    " --retry-of)\n"
)


def test_recover_prints_the_object_and_the_line_it_printed_before_the_ids_were_added(tmp_path):
    study, folder = killed(tmp_path / "json", kill_at=4)
    code, payload, err = run_json("recover", "--study", study, "--attempt", folder.name)
    assert code == 0, (payload, err)
    assert payload == {"ok": True, "attempt": json.loads((folder / "attempt.json").read_text(encoding="utf-8"))}
    study, folder = killed(tmp_path / "text", kill_at=4)
    code, out, err = run_cli("recover", "--study", study, "--attempt", folder.name)
    assert code == 0, err
    assert out == RECOVER_LINE.format(attempt_id=folder.name)
