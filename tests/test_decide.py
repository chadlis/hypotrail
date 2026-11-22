"""Ticket #109 (slice #104, L2.1): the `decide` command and the decision record.

D-031 on chadlis/hypotrail#75, D-033 on chadlis/hypotrail#75, D-034 on chadlis/hypotrail#75, D-035 on chadlis/hypotrail#75, D-036 on chadlis/hypotrail#75 and D-037 on chadlis/hypotrail#75 settle what is tested here. A decision is one record of the Study, one
file `decisions/<seq>-<id>.json` that is never rewritten. `decide` requires `--request-id` and `--read-sequence`, holds the writer lock, and
cites at least one id the Study holds. The rows of #108's and #107's parametrised tests that name `decide` are in `test_stale_sequence.py`
and `test_write_sequence.py`. No model is called.
"""

import json
import shutil
from pathlib import Path

import pytest
from _assess_helpers import references_id
from _chinook_helpers import FIXTURE_CASES, episodes_file, fixture_lines, fixture_population, import_agent, init_chinook, write_lines
from _import_helpers import import_ml, ready, write_json
from _report_tracks import Bike
from _revision_helpers import new_revision
from _run_agent_helpers import fixture
from _study_helpers import examples_copy, init_study, run_json, run_ml
from test_study_lock import held_by_another_process
from test_write_sequence import entries, seq, tree

from hypotrail.core import contracts
from hypotrail.core.errors import IntegrityError

QUESTION = "Which Configuration do we keep?"
OPTION = "ridge_v1"


# --- helpers ---------------------------------------------------------------------------------------------------------


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def error_of(payload):
    assert payload["ok"] is False and set(payload) == {"ok", "error"}, payload
    assert set(payload["error"]) == {"code", "message", "stage", "details"}
    return payload["error"]


def decision_files(study):
    folder = Path(study) / "decisions"
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def held(study) -> dict:
    """An id of each kind of record the Study holds, each read from the record that holds it."""
    study = Path(study)
    attempt = sorted(p.name for p in (study / "attempts").iterdir())[0]
    assessment = sorted((study / "assessments").glob("*/assessment.json"))[0]
    comparison = sorted((study / "comparisons").glob("*/comparison.json"))[0]
    return {
        "attempt": read(study / "attempts" / attempt / "attempt.json")["attempt_id"],
        "observation_set": read(study / "attempts" / attempt / "observation_set.json")["observation_set_id"],
        "assessment": read(assessment)["assessment_id"],
        "comparison": read(comparison)["comparison_id"],
        "study_artifact": references_id(study),
        "revision": read(study / "study.json")["revision"],
        "earlier_revision": read(study / "revisions" / "1" / "study.json")["revision"],
        "freeze_record": read(study / "revisions" / "1" / "freeze.json")["freeze_id"],
        "exposure_entry": read(sorted((study / "exposures").glob("*.json"))[0])["entry_id"],
    }


def decide(study, *, cited=None, omit=(), read_sequence=None, **fields):
    """`decide` on the command line: the flags of `fields` (question, option, author, source, request_id) and one `--artifact` per cited id."""
    values = {"question": QUESTION, "option": OPTION, "author": "human", "source": None, "request_id": "d-1", **fields}
    flags = [
        ("--study", study),
        ("--question", values["question"]),
        ("--option", values["option"]),
        ("--author", values["author"]),
        ("--request-id", values["request_id"]),
        ("--read-sequence", seq(study) if read_sequence is None else read_sequence),
    ]
    if values["source"] is not None:
        flags.append(("--source", values["source"]))
    flags += [("--artifact", cited_id) for cited_id in (cited if cited is not None else [held(study)["attempt"]])]
    return run_json("decide", *[part for flag, value in flags if flag not in omit for part in (flag, value)])


def made(study, **kwargs):
    """The decision a `decide` that is accepted records."""
    code, payload, err = decide(study, **kwargs)
    assert code == 0, (payload, err)
    return payload["decision"]


@pytest.fixture(scope="module")
def exposed(tmp_path_factory):
    """A Bike Study with an Attempt, an Observation set, Assessments, a Comparison, a freeze record, Exposure entries and two revisions."""
    study, _ = Bike().exposed_study(tmp_path_factory.mktemp("decide"))
    return study


@pytest.fixture
def study(exposed, tmp_path):
    """A private copy of that Study, in a folder beside which other files can be seen."""
    (tmp_path / "workspace").mkdir()
    target = tmp_path / "workspace" / "study"
    shutil.copytree(exposed, target)
    return target


# --- criterion 1, Tightened E, L, M, O: the record --------------------------------------------------------------------


def test_decide_records_one_decision_and_every_field_is_read_back_from_the_study(study):
    cited, before = held(study)["attempt"], seq(study)
    code, payload, err = decide(study, author="proxy", source="rule: the lower MAE", request_id="d-1", cited=[cited])
    assert (code, payload.get("ok")) == (0, True), (payload, err)
    assert set(payload) == {"ok", "replayed", "decision"} and payload["replayed"] is False
    [file] = decision_files(study)
    record = read(file)
    assert payload["decision"] == record
    assert {key: record[key] for key in ("question", "option", "author", "source", "cited_ids", "request_id", "read_sequence")} == {
        "question": QUESTION,
        "option": OPTION,
        "author": "proxy",
        "source": "rule: the lower MAE",
        "cited_ids": [cited],
        "request_id": "d-1",
        "read_sequence": before,
    }
    assert (record["kind"], record["write_sequence"]) == ("decision", before + 1)
    assert file.name == f"000001-{record['decision_id']}.json"


def a_record() -> dict:
    return {
        "kind": "decision",
        "schema_version": "decision/1",
        "decision_id": "11111111-1111-4111-8111-111111111111",
        "request_id": "d-1",
        "question": QUESTION,
        "option": OPTION,
        "author": "human",
        "source": None,
        "cited_ids": ["a1"],
        "revision": "r" * 64,
        "read_sequence": 4,
        "write_sequence": 5,
    }


FIELDS = [key for key in a_record() if key != "kind"]


def test_a_well_formed_decision_record_matches_the_contract_schema():
    contracts.validate(a_record())


@pytest.mark.parametrize("field", FIELDS)
def test_a_decision_record_missing_a_field_is_refused_with_contract_violation(field):
    record = a_record()
    del record[field]
    with pytest.raises(IntegrityError) as caught:
        contracts.validate(record)
    error = caught.value
    assert (error.code, error.exit_code, error.stage) == ("CONTRACT_VIOLATION", 3, "contract")
    assert error.details["kind"] == "decision"
    assert f"'{field}' is a required property" in error.details["message"], error.details


@pytest.mark.parametrize(
    "change",
    [
        {"author": "committee"},
        {"question": ""},
        {"option": ""},
        {"cited_ids": []},
        {"cited_ids": [""]},
        {"read_sequence": -1},
        {"write_sequence": "5"},
        {"author_name": "Ada"},
    ],
    ids=lambda change: next(iter(change)) + "=" + repr(next(iter(change.values()))),
)
def test_a_decision_record_with_a_wrong_value_or_an_extra_field_is_refused_with_contract_violation(change):
    with pytest.raises(IntegrityError) as caught:
        contracts.validate({**a_record(), **change})
    assert caught.value.code == "CONTRACT_VIOLATION"
    assert caught.value.details["kind"] == "decision"
    assert "not valid under any of the given schemas" not in caught.value.details["message"], caught.value.details


def test_a_decision_file_that_no_longer_matches_the_contract_is_refused_when_it_is_read(study):
    first = made(study)
    [file] = decision_files(study)
    sequence = seq(study)  # `status` reads the decisions too (#110): the sequence is read before the file is broken
    broken = {key: value for key, value in first.items() if key != "option"}
    file.write_text(json.dumps(broken), encoding="utf-8")
    code, payload, err = decide(study, read_sequence=sequence)  # a replay reads the record
    error = error_of(payload)
    assert (code, error["code"], error["details"]["kind"]) == (3, "CONTRACT_VIOLATION", "decision"), payload
    assert "'option' is a required property" in error["details"]["message"]


def test_the_record_of_a_human_decision_holds_the_author_kind_and_the_source_and_no_other_author_field(study):
    record = made(study, author="human", source="the owner, in chat")
    assert (record["author"], record["source"]) == ("human", "the owner, in chat")
    assert {key for key in record if key.startswith("author")} == {"author"}
    assert set(record) == {
        "kind", "schema_version", "decision_id", "request_id", "question", "option", "author", "source",
        "cited_ids", "revision", "read_sequence", "write_sequence",
    }


def test_the_record_keeps_request_id_at_top_level_and_the_sequence_its_author_read_one_below_its_own(study):
    before = seq(study)
    record = made(study, request_id="the-request", read_sequence=before)
    assert record["request_id"] == "the-request"
    assert record["read_sequence"] == before
    assert record["read_sequence"] == record["write_sequence"] - 1


@pytest.mark.parametrize("field", ["request_id", "read_sequence"])
def test_a_decision_record_without_request_id_or_read_sequence_is_refused_with_contract_violation(field):
    record = a_record()
    del record[field]
    with pytest.raises(IntegrityError) as caught:
        contracts.validate(record)
    assert (caught.value.code, caught.value.details["kind"]) == ("CONTRACT_VIOLATION", "decision")
    assert f"'{field}' is a required property" in caught.value.details["message"]


def test_two_decisions_land_in_numbered_files_and_each_holds_the_position_of_its_begin_entry(study):
    first = made(study, request_id="d-1")
    second = made(study, request_id="d-2", option="seasonal_7")
    files = decision_files(study)
    assert [f.name for f in files] == [f"000001-{first['decision_id']}.json", f"000002-{second['decision_id']}.json"]
    journal = entries(study)
    for record in (first, second):
        position = next(
            number for number, entry in enumerate(journal, 1) if entry["phase"] == "begin" and entry["command"] == "decide" and entry["request_id"] == record["request_id"]
        )
        assert record["write_sequence"] == position


def test_a_decision_file_is_never_rewritten_by_later_writes(study):
    first = made(study, request_id="d-1")
    [file] = decision_files(study)
    kept = file.read_bytes()
    made(study, request_id="d-2", option="seasonal_7")
    made(study, request_id="later", option="ridge_v1")
    assert decision_files(study)[0] == file and file.read_bytes() == kept
    assert read(file) == first


def test_the_decision_stores_the_revision_the_study_holds_and_a_new_revision_changes_it(study, tmp_path):
    before = made(study, request_id="d-1")
    assert before["revision"] == read(study / "study.json")["revision"]

    def corrected_day(table):
        row = next(r for r in table if r["dteday"] == "2012-03-16")
        row["cnt"], row["registered"] = str(int(row["cnt"]) + 1000), str(int(row["registered"]) + 1000)

    code, payload, err = new_revision(study, "--examples-dir", examples_copy(tmp_path, rows=corrected_day, name="third"), "--read-sequence", seq(study))
    assert code == 0, (payload, err)
    after = made(study, request_id="d-2")
    assert after["revision"] == read(study / "study.json")["revision"] != before["revision"]


# --- criterion 2 and Tightened A: the flags -----------------------------------------------------------------------------

REQUIRED = ["--study", "--question", "--option", "--author", "--request-id", "--read-sequence", "--artifact"]


@pytest.mark.parametrize("flag", REQUIRED)
def test_without_a_required_flag_decide_is_refused_as_invalid_arguments_and_nothing_is_written(flag, study):
    files = tree(study)
    code, payload, err = decide(study, omit=(flag,))
    error = error_of(payload)
    assert (code, error["code"], error["stage"]) == (2, "INVALID_ARGUMENTS", "config")
    assert error["details"] == {"command": "hypotrail decide"}  # the `decide` parser refused it, not the top-level one
    assert flag in error["message"], error["message"]
    assert tree(study) == files


# --- the third criterion: the sequence --------------------------------------------------------------------------------


def test_given_the_current_sequence_decide_records_the_decision_and_advances_the_write_sequence_by_two(study):
    before = seq(study)
    record = made(study, read_sequence=before)
    assert seq(study) == before + 2
    assert [entry["phase"] for entry in entries(study)[before:]] == ["begin", "end"]
    assert record["read_sequence"] == before


def test_a_decision_made_on_an_older_sequence_is_refused_with_study_changed_and_nothing_is_written(study):
    read_before = seq(study)
    made(study, request_id="bump")  # another write moves the sequence on
    files = tree(study)
    code, payload, err = decide(study, read_sequence=read_before)
    error = error_of(payload)
    assert (code, error["code"], error["stage"]) == (6, "STUDY_CHANGED", "sequence")
    assert error["details"]["read_sequence"] == read_before
    assert tree(study) == files and len(decision_files(study)) == 1  # the one that moved the sequence on


# --- Tightened author: human or proxy, a source optional for either -----------------------------------------------------


@pytest.mark.parametrize("source", [None, "minutes of the review"])
@pytest.mark.parametrize("author", ["human", "proxy", "committee"])
def test_the_author_is_human_or_proxy_with_or_without_a_source_and_another_author_is_refused(author, source, study):
    files = tree(study)
    code, payload, err = decide(study, author=author, source=source)
    if author == "committee":
        error = error_of(payload)
        assert (code, error["code"], error["stage"]) == (2, "INVALID_ARGUMENTS", "config")
        assert error["details"] == {"command": "hypotrail decide"} and "--author" in error["message"]
        assert tree(study) == files
    else:
        assert code == 0, (payload, err)
        assert (payload["decision"]["author"], payload["decision"]["source"]) == (author, source)


# --- the fifth criterion: the writer lock ---------------------------------------------------------------------------------


def test_while_another_writer_holds_the_lock_decide_is_refused_with_study_locked_and_writes_nothing(study):
    files = tree(study)
    with held_by_another_process(study):
        code, payload, err = decide(study)
    error = error_of(payload)
    assert (code, error["code"], error["stage"]) == (6, "STUDY_LOCKED", "lock")
    assert tree(study) == files and not decision_files(study)


# --- the sixth criterion: the Study only ----------------------------------------------------------------------------------


def test_decide_creates_or_changes_no_file_outside_the_study_folder(study, tmp_path, monkeypatch):
    (tmp_path / "workspace" / "notes.txt").write_text("beside the Study", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    before = tree(tmp_path)
    made(study)
    after = tree(tmp_path)
    inside = "workspace/study/"
    assert {k: v for k, v in after.items() if not k.startswith(inside)} == {k: v for k, v in before.items() if not k.startswith(inside)}
    assert any(k.startswith(inside + "decisions/") for k in after)  # the decision is there


# --- Tightened B and I: an empty question or option, a missing --artifact ------------------------------------------------


@pytest.mark.parametrize("field", ["question", "option"])
def test_an_empty_question_or_option_is_refused_with_decision_field_empty_and_nothing_is_written(field, study):
    files = tree(study)
    code, payload, err = decide(study, **{field: ""})
    error = error_of(payload)
    assert (code, error["code"], error["stage"], error["details"]) == (2, "DECISION_FIELD_EMPTY", "decision", {"field": field}), payload
    assert tree(study) == files


def test_two_unknown_ids_given_out_of_order_beside_a_known_one_are_refused_with_every_unknown_id_sorted(study):
    files = tree(study)
    known = held(study)["attempt"]
    code, payload, err = decide(study, cited=["zz-unknown", known, "aa-unknown"])
    error = error_of(payload)
    assert (code, error["code"], error["stage"], error["details"]) == (2, "CITED_ID_NOT_FOUND", "decision", {"ids": ["aa-unknown", "zz-unknown"]}), payload
    assert tree(study) == files


# --- Tightened C, J, N: which ids are citable --------------------------------------------------------------------------

KINDS = ["attempt", "observation_set", "assessment", "comparison", "study_artifact", "revision", "earlier_revision", "freeze_record", "exposure_entry"]


def a_declared_deviation(study, kind) -> str:
    """The id of a declaration that cites an Attempt, or of the withdrawal of one."""
    from _deviation_helpers import declare

    declared = declare(study, [held(study)["attempt"]])["declared_deviation_id"]
    return declared if kind == "declared_deviation" else declare(study, [declared], text="withdrawn")["declared_deviation_id"]


@pytest.mark.parametrize("kind", [*KINDS, "decision", "declared_deviation", "withdrawal"])
def test_an_id_of_each_kind_of_record_the_study_holds_is_citable(kind, study):
    if kind == "decision":
        cited = made(study, request_id="first")["decision_id"]
    elif kind in ("declared_deviation", "withdrawal"):
        cited = a_declared_deviation(study, kind)
    else:
        cited = held(study)[kind]
    code, payload, err = decide(study, request_id="d-kind", cited=[cited])
    assert code == 0, (payload, err)
    assert payload["decision"]["cited_ids"] == [cited]


def not_citable(study, tmp_path) -> dict:
    spec = read(study / "study.json")
    artifact = spec["artifacts"][0]["ref"]
    return {
        "a request_id": read(study / "attempts" / held(study)["attempt"] / "attempt.json")["request_id"],
        "the study_id": spec["study_id"],
        "an artifact's path": artifact["path"],
        "an artifact's sha256": artifact["sha256"],
        "a revision_number": str(spec["revision_number"]),
        "the protocol_digest": spec["protocol_digest"],
    }


@pytest.mark.parametrize("what", ["a request_id", "the study_id", "an artifact's path", "an artifact's sha256", "a revision_number", "the protocol_digest"])
def test_a_value_that_names_no_record_is_not_citable(what, study, tmp_path):
    value = not_citable(study, tmp_path)[what]
    files = tree(study)
    code, payload, err = decide(study, cited=[value])
    error = error_of(payload)
    assert (code, error["code"], error["stage"], error["details"]) == (2, "CITED_ID_NOT_FOUND", "decision", {"ids": [value]}), payload
    assert tree(study) == files


def test_an_id_given_twice_and_ids_out_of_order_are_recorded_once_and_sorted(study):
    ids = held(study)
    cited = [ids["comparison"], ids["attempt"], ids["comparison"], ids["assessment"]]
    record = made(study, cited=cited)
    assert record["cited_ids"] == sorted({ids["comparison"], ids["attempt"], ids["assessment"]})


def test_status_json_with_a_decision_recorded_has_the_thirteen_top_level_keys_with_the_listings_and_no_list_of_observation_sets(study):
    made(study)
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, err
    assert set(payload) == {"ok", "study", "writer_alive", "revisions", "attempts", "freeze_records", "exposures", "check_informed", "write_sequence", "decisions", "declared_deviations", "assessments", "comparisons"}
    assert "observation_sets" not in payload


# --- the order of the refusals ------------------------------------------------------------------------------------------------


def test_an_empty_request_id_is_refused_as_request_id_empty(study):
    code, payload, err = decide(study, request_id="")
    assert (code, error_of(payload)["code"]) == (2, "REQUEST_ID_EMPTY")


def test_no_study_is_refused_as_study_not_found(tmp_path):
    code, payload, err = run_json(
        "decide", "--study", tmp_path / "none", "--question", QUESTION, "--option", OPTION, "--author", "human", "--artifact", "a", "--request-id", "d", "--read-sequence", 0
    )
    assert (code, error_of(payload)["code"]) == (2, "STUDY_NOT_FOUND")


def test_an_older_sequence_with_an_unknown_id_is_refused_as_study_changed(study):
    stale = seq(study)
    made(study, request_id="bump")  # another write moves the sequence on
    code, payload, err = decide(study, read_sequence=stale, cited=["unknown"])
    assert (code, error_of(payload)["code"]) == (6, "STUDY_CHANGED")


def test_a_sequence_above_the_current_one_is_refused_as_write_sequence_ahead(study):
    code, payload, err = decide(study, read_sequence=seq(study) + 1)
    error = error_of(payload)
    assert (code, error["code"], error["stage"]) == (2, "WRITE_SEQUENCE_AHEAD", "sequence")


# --- Tightened D, K, P: the identity of a request -------------------------------------------------------------------------------


def test_a_decide_repeated_after_the_write_sequence_moved_on_is_a_replay_that_returns_the_record_and_writes_nothing(study):
    first = made(study, request_id="d-1")
    stale = first["read_sequence"]
    made(study, request_id="bump")  # another write moves the sequence on
    files = tree(study)
    code, payload, err = decide(study, request_id="d-1", read_sequence=stale)
    assert code == 0, (payload, err)
    assert payload["replayed"] is True and payload["decision"] == first
    assert tree(study) == files


def test_the_same_decision_with_its_ids_repeated_and_in_another_order_is_a_replay(study):
    ids = held(study)
    first = made(study, request_id="d-1", cited=[ids["attempt"], ids["assessment"]])
    files = tree(study)
    code, payload, err = decide(study, request_id="d-1", cited=[ids["assessment"], ids["attempt"], ids["assessment"]])
    assert code == 0, (payload, err)
    assert payload["replayed"] is True and payload["decision"] == first
    assert tree(study) == files


def test_the_same_request_id_with_another_option_is_a_request_conflict_that_names_the_decision(study):
    first = made(study, request_id="d-1")
    files = tree(study)
    code, payload, err = decide(study, request_id="d-1", option="seasonal_7")
    error = error_of(payload)
    assert (code, error["code"], error["stage"]) == (6, "REQUEST_CONFLICT", "request")
    assert error["details"] == {"request_id": "d-1", "attempt_id": None, "decision_id": first["decision_id"], "declared_deviation_id": None, "differs": ["option"]}
    assert "an Attempt" not in error["message"]
    assert tree(study) == files


def test_a_conflict_between_two_decisions_lists_the_differing_fields_in_the_order_of_the_record(study):
    ids = held(study)
    made(study, request_id="d-1", author="human", source=None, cited=[ids["attempt"]])
    code, payload, err = decide(
        study, request_id="d-1", question="Another question?", option="seasonal_7", author="proxy", source="a rule", cited=[ids["assessment"]]
    )
    assert error_of(payload)["details"]["differs"] == ["question", "option", "author", "source", "cited_ids"]


def test_another_option_and_another_source_are_named_in_that_order(study):
    made(study, request_id="d-1", source=None)
    code, payload, err = decide(study, request_id="d-1", option="seasonal_7", source="a rule")
    assert error_of(payload)["details"]["differs"] == ["option", "source"]


def test_a_request_id_that_names_an_attempt_is_a_request_conflict_with_the_attempt_and_no_decision(study):
    attempt = read(study / "attempts" / held(study)["attempt"] / "attempt.json")
    files = tree(study)
    code, payload, err = decide(study, request_id=attempt["request_id"])
    error = error_of(payload)
    assert (code, error["code"], error["stage"]) == (6, "REQUEST_CONFLICT", "request")
    assert error["details"] == {
        "request_id": attempt["request_id"], "attempt_id": attempt["attempt_id"], "decision_id": None, "declared_deviation_id": None, "differs": ["command"],
    }
    assert tree(study) == files


# one row per command: a request_id that an earlier Attempt of another request holds, and one that a decision holds


def bike(tmp_path):
    study, _ = init_study(tmp_path)
    source, mapping, population, _ = ready(tmp_path)
    smaller = write_json(tmp_path / "smaller.json", {"item_ids": read(population)["item_ids"][:-1]})
    return {
        "run ml": (study, lambda rid, other=False: run_ml(study, "ridge_v1" if other else "seasonal_7", "dev", rid)),
        "import ml": (study, lambda rid, other=False: import_ml(study, source, mapping, smaller if other else population, rid)),
    }


def chinook(tmp_path):
    study, _ = init_chinook(tmp_path)
    source = write_lines(tmp_path / "answers.jsonl", fixture_lines())
    smaller = episodes_file(tmp_path, [(case, 0) for case in FIXTURE_CASES[:-1]], name="smaller.json")
    return {
        "run agent": (study, lambda rid, other=False: fixture(study, "verify" if other else "plain", rid)),
        "import agent": (study, lambda rid, other=False: import_agent(study, source, smaller if other else fixture_population(tmp_path), rid)),
    }


def row(tmp_path, command):
    return (bike if command.endswith("ml") else chinook)(tmp_path)[command]


COMMANDS = ["run ml", "run agent", "import ml", "import agent"]


@pytest.mark.parametrize("command", COMMANDS)
def test_a_request_id_of_an_earlier_attempt_of_another_request_is_a_request_conflict_with_the_attempt_and_no_decision(command, tmp_path):
    study, call = row(tmp_path, command)
    code, payload, err = call("shared")
    assert code == 0, (payload, err)
    files = tree(study)
    code, payload, err = call("shared", True)
    error = error_of(payload)
    assert (code, error["code"], error["stage"]) == (6, "REQUEST_CONFLICT", "request"), payload
    assert set(error["details"]) == {"request_id", "attempt_id", "decision_id", "declared_deviation_id", "differs"}
    assert (error["details"]["attempt_id"], error["details"]["decision_id"]) == (read(sorted((study / "attempts").glob("*/attempt.json"))[0])["attempt_id"], None)
    assert tree(study) == files


@pytest.mark.parametrize("command", COMMANDS)
def test_a_request_id_that_a_decision_holds_is_a_request_conflict_with_the_decision_and_no_attempt(command, tmp_path):
    study, call = row(tmp_path, command)
    cited = read(study / "study.json")["artifacts"][0]["artifact_id"]
    recorded = made(study, request_id="shared", cited=[cited])
    files = tree(study)
    code, payload, err = call("shared")
    error = error_of(payload)
    assert (code, error["code"], error["stage"]) == (6, "REQUEST_CONFLICT", "request"), payload
    assert error["details"] == {
        "request_id": "shared", "attempt_id": None, "decision_id": recorded["decision_id"], "declared_deviation_id": None, "differs": ["command"],
    }
    assert "an Attempt" not in error["message"] and "decision" in error["message"]
    assert tree(study) == files


# --- the glossary --------------------------------------------------------------------------------------------------------------


def test_the_glossary_has_a_decision_entry_with_its_avoid_line_and_its_relationships_to_the_study_and_the_write_sequence():
    text = (Path(__file__).resolve().parent.parent / "GLOSSARY.md").read_text(encoding="utf-8")
    assert "**Decision**:" in text, "GLOSSARY.md has no entry Decision"
    entry = text.split("**Decision**:", 1)[1].split("\n\n", 1)[0]
    assert "_Avoid_: note, verdict, conclusion" in entry
    assert "Study" in entry and "write sequence" in entry
    assert "- A **Decision** " in text, "GLOSSARY.md has no relationship line for a Decision"
