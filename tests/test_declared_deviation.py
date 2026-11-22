"""Ticket #155 (T1 of slice #150, ticket B2): the `deviation` command and the Declared deviation record.

A Declared deviation is one record of the Study, one file `declared_deviations/<seq>-<id>.json` that is never rewritten. It either declares,
citing Attempts and References sets, or withdraws, citing exactly one earlier Declared deviation. No model is called.
"""

import json
import shutil
from pathlib import Path

import pytest
from _assess_helpers import references_id
from _deviation_helpers import FOLDER, PENDING, declare, deviation, files, outcome, seq
from _study_helpers import init_study, run_ml
from test_study_lock import held_by_another_process
from test_write_sequence import entries, tree

from hypotrail.core import artifacts, contracts
from hypotrail.core.errors import HypotrailError


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    """A Bike Study that holds one Attempt."""
    study, _ = init_study(tmp_path_factory.mktemp("deviation"))
    code, payload, err = run_ml(study, "seasonal_7", "dev", "held")
    assert code == 0, (payload, err)
    return study


@pytest.fixture
def study(base, tmp_path):
    target = tmp_path / "study"
    shutil.copytree(base, target)
    return target


def attempt_of(study) -> str:
    [folder] = sorted((Path(study) / "attempts").iterdir())
    return read(folder / "attempt.json")["attempt_id"]


# --- TB2.2: the record, its fields, and how it is published ----------------------------------------------------------------


def test_the_command_records_one_declared_deviation_whose_file_matches_the_contract_and_holds_every_field_it_was_given(study):
    cited, before = attempt_of(study), seq(study)
    code, payload, err = deviation(study, [cited], author="proxy", source="the gate reader", request_id="dv-1")
    assert (code, outcome(payload)) == (0, "ok"), (payload, err)
    assert len(files(study)) == 1, files(study)
    [file] = files(study)
    record = read(file)
    contracts.validate(record)
    assert payload == {"ok": True, "replayed": False, "declared_deviation": record}
    assert {key: record[key] for key in ("text", "author", "source", "cited_ids", "request_id", "read_sequence")} == {
        "text": PENDING,
        "author": "proxy",
        "source": "the gate reader",
        "cited_ids": [cited],
        "request_id": "dv-1",
        "read_sequence": before,
    }
    assert (record["kind"], record["schema_version"]) == ("declared_deviation", "declared_deviation/1")
    assert record["write_sequence"] == before + 1 and record["revision"] == read(study / "study.json")["revision"]
    assert file.name == f"000001-{record['declared_deviation_id']}.json" and file.parent.name == FOLDER


def test_a_declared_deviation_file_is_never_rewritten_by_a_later_declaration_or_by_its_withdrawal(study):
    first = declare(study, [attempt_of(study)])
    [file] = files(study)
    kept = file.read_bytes()
    declare(study, [references_id(study)], text="a second one")
    declare(study, [first["declared_deviation_id"]], text="the review is done")
    assert len(files(study)) == 3 and files(study)[0] == file
    assert file.read_bytes() == kept


def test_a_declared_deviation_is_published_atomically_under_the_writer_lock(study):
    declare(study, [attempt_of(study)])
    assert len(files(study)) == 1, files(study)
    [file] = files(study)
    assert not [p for p in Path(study).rglob("*") if p.name.endswith(artifacts.TEMP_SUFFIX)]
    with pytest.raises(HypotrailError) as refusal:
        artifacts.publish_bytes(study, f"{FOLDER}/{file.name}", b"{}", media_type="application/json", role="declared_deviation")
    assert refusal.value.code == "ARTIFACT_IMMUTABLE"
    before = tree(study)
    with held_by_another_process(study):  # another writer is at work: the command is refused at once and writes nothing
        code, payload, err = deviation(study, [attempt_of(study)])
    assert (code, outcome(payload)) == (6, "STUDY_LOCKED"), (payload, err)
    assert tree(study) == before


def test_given_the_current_sequence_the_command_records_the_declared_deviation_and_advances_the_write_sequence_by_two(study):
    before = seq(study)
    record = declare(study, [attempt_of(study)], read_sequence=before)
    assert seq(study) == before + 2
    assert [entry["phase"] for entry in entries(study)[before:]] == ["begin", "end"]
    assert entries(study)[-1]["written"] == [{"kind": "declared_deviation", "id": record["declared_deviation_id"]}]


REQUIRED = ["--study", "--text", "--author", "--artifact", "--request-id", "--read-sequence"]


@pytest.mark.parametrize("flag", REQUIRED, ids=lambda flag: "no " + flag)
def test_without_a_required_flag_the_command_is_refused_as_invalid_arguments_and_nothing_is_written(flag, study):
    # "no --artifact" is the record that cites no id: a Declared deviation cites at least one
    files_before = tree(study)
    code, payload, err = deviation(study, [attempt_of(study)], omit=(flag,))
    assert (code, outcome(payload)) == (2, "INVALID_ARGUMENTS"), (payload, err)
    assert payload["error"]["details"] == {"command": "hypotrail deviation"} and flag in payload["error"]["message"]
    assert tree(study) == files_before


def writer_refusals(study):
    """{case: (the call, the exit code, the outcome)}: the neighbouring cases of `decide`'s refusals, and a valid case."""
    cited = attempt_of(study)
    recorded = declare(study, [cited], request_id="dv-held")
    stale = recorded["read_sequence"]
    return {
        "an empty text": (lambda: deviation(study, [cited], text=""), 2, "DEVIATION_TEXT_EMPTY"),
        "an author outside the two": (lambda: deviation(study, [cited], author="committee"), 2, "INVALID_ARGUMENTS"),
        "no --read-sequence": (lambda: deviation(study, [cited], omit=("--read-sequence",)), 2, "INVALID_ARGUMENTS"),
        "a cited id the Study does not hold": (lambda: deviation(study, ["not-held"]), 2, "CITED_ID_NOT_FOUND"),
        "a stale sequence": (lambda: deviation(study, [cited], read_sequence=stale), 6, "STUDY_CHANGED"),
        "the same request_id and the same request": (lambda: deviation(study, [cited], request_id="dv-held", read_sequence=stale), 0, "ok"),
        "the same request_id and another request": (lambda: deviation(study, [cited], request_id="dv-held", text="another text"), 6, "REQUEST_CONFLICT"),
        "a valid record": (lambda: deviation(study, [cited]), 0, "ok"),
    }


WRITER_CASES = [
    "an empty text",
    "an author outside the two",
    "no --read-sequence",
    "a cited id the Study does not hold",
    "a stale sequence",
    "the same request_id and the same request",
    "the same request_id and another request",
    "a valid record",
]


@pytest.mark.parametrize("case", WRITER_CASES)
def test_each_refusal_a_writer_gives_has_its_code_and_exit_and_writes_nothing_and_a_valid_record_is_written(case, study):
    call, exit_code, expected = writer_refusals(study)[case]
    before, sequence = tree(study), seq(study)
    code, payload, err = call()
    assert (code, outcome(payload)) == (exit_code, expected), (payload, err)
    if case == "a valid record":
        assert len(files(study)) == 2 and seq(study) == sequence + 2
    else:
        assert tree(study) == before and seq(study) == sequence
    if case == "the same request_id and the same request":
        assert payload["replayed"] is True and payload["declared_deviation"] == read(files(study)[0])


# --- TB2.2c: one request_id namespace for the Attempts, the decisions and the Declared deviations of a Study ---------------------


def conflict_details(payload) -> dict:
    assert payload is not None and payload.get("ok") is False, payload
    error = payload["error"]
    assert (error["code"], error["stage"]) == ("REQUEST_CONFLICT", "request"), error
    return error["details"]


@pytest.mark.parametrize("command", ["run ml", "run agent", "import ml", "import agent"])
def test_a_run_or_an_import_whose_request_id_names_a_declared_deviation_is_a_request_conflict_with_it_and_writes_nothing(command, tmp_path):
    from test_decide import row

    study, call = row(tmp_path, command)
    recorded = declare(study, [references_id_of(study)], request_id="shared")
    before = tree(study)
    code, payload, err = call("shared")
    assert code == 6, (payload, err)
    assert conflict_details(payload) == {
        "request_id": "shared", "attempt_id": None, "decision_id": None, "declared_deviation_id": recorded["declared_deviation_id"], "differs": ["command"],
    }
    assert tree(study) == before


def references_id_of(study) -> str:
    """The `artifact_id` of the References set of the Study's current revision, whatever its Track."""
    return next(e["artifact_id"] for e in read(Path(study) / "study.json")["artifacts"] if e["ref"]["role"] == "references")


def test_a_decide_whose_request_id_names_a_declared_deviation_is_a_request_conflict_with_it_and_writes_nothing(study):
    from test_decide import decide

    recorded = declare(study, [attempt_of(study)], request_id="shared")
    before = tree(study)
    code, payload, err = decide(study, request_id="shared", cited=[attempt_of(study)])
    assert code == 6, (payload, err)
    assert conflict_details(payload) == {
        "request_id": "shared", "attempt_id": None, "decision_id": None, "declared_deviation_id": recorded["declared_deviation_id"], "differs": ["command"],
    }
    assert tree(study) == before


def test_a_declared_deviation_whose_request_id_names_an_attempt_is_a_request_conflict_with_the_attempt_and_writes_nothing(study):
    attempt = read(study / "attempts" / attempt_of(study) / "attempt.json")
    before = tree(study)
    code, payload, err = deviation(study, [attempt["attempt_id"]], request_id=attempt["request_id"])
    assert code == 6, (payload, err)
    assert conflict_details(payload) == {
        "request_id": attempt["request_id"], "attempt_id": attempt["attempt_id"], "decision_id": None, "declared_deviation_id": None, "differs": ["command"],
    }
    assert tree(study) == before


def test_a_declared_deviation_whose_request_id_names_a_decision_is_a_request_conflict_with_the_decision_and_writes_nothing(study):
    from test_decide import made

    decision = made(study, request_id="shared", cited=[attempt_of(study)])
    before = tree(study)
    code, payload, err = deviation(study, [attempt_of(study)], request_id="shared")
    assert code == 6, (payload, err)
    assert conflict_details(payload) == {
        "request_id": "shared", "attempt_id": None, "decision_id": decision["decision_id"], "declared_deviation_id": None, "differs": ["command"],
    }
    assert tree(study) == before


def test_two_declared_deviations_under_one_request_id_that_differ_name_the_fields_that_differ_in_the_order_of_the_record(study):
    first = declare(study, [attempt_of(study)], request_id="shared", author="human")
    code, payload, err = deviation(study, [references_id(study)], request_id="shared", text="another text", author="proxy", source="a rule")
    assert code == 6, (payload, err)
    assert conflict_details(payload) == {
        "request_id": "shared", "attempt_id": None, "decision_id": None, "declared_deviation_id": first["declared_deviation_id"],
        "differs": ["text", "author", "source", "cited_ids"],
    }


# --- TB2.2d: the replay of a withdrawal ----------------------------------------------------------------------------------------


def test_a_withdrawal_repeated_with_its_request_id_and_the_same_request_is_a_replay_that_returns_it_and_writes_nothing(study):
    declared = declare(study, [attempt_of(study)])
    withdrawal = declare(study, [declared["declared_deviation_id"]], text="the review is done", request_id="w-1")
    before = tree(study)
    code, payload, err = deviation(study, [declared["declared_deviation_id"]], text="the review is done", request_id="w-1", read_sequence=withdrawal["read_sequence"])
    assert (code, outcome(payload)) == (0, "ok"), (payload, err)
    assert payload["replayed"] is True and payload["declared_deviation"] == withdrawal
    assert tree(study) == before


# --- TB2.4, TB2.13: a declaration or a withdrawal, and the order of the refusals of the ids a record cites -----------------------

MIX, SEVERAL, CITES_A_WITHDRAWAL = "DEVIATION_CITES_A_MIX", "DEVIATION_CITES_SEVERAL_DEVIATIONS", "DEVIATION_CITES_A_WITHDRAWAL"
NOT_HELD, NOT_CITABLE, ALREADY_WITHDRAWN = "CITED_ID_NOT_FOUND", "CITED_KIND_NOT_CITABLE", "DEVIATION_ALREADY_WITHDRAWN"


@pytest.fixture(scope="module")
def compared_base(tmp_path_factory):
    """A Bike Study with two Attempts of seasonal_7 on dev, each assessed: {"study", "attempts", "assessments"}."""
    from _compare_helpers import assessed

    study, _ = init_study(tmp_path_factory.mktemp("cited"))
    attempts, assessments = [], []
    for name in ("a", "b"):
        code, payload, err = run_ml(study, "seasonal_7", "dev", f"run-{name}")
        assert code == 0, (payload, err)
        attempts.append(payload["attempt"]["attempt_id"])
        assessments.append(assessed_one(study, payload["attempt"]))
    return study, attempts, assessments


def assessed_one(study, attempt) -> str:
    from _assess_helpers import assess, observation_set_id

    code, payload, err = assess(study, observation_set_id(study, attempt), "regression_mae_v1", references_id(study))
    assert code == 0, (payload, err)
    return payload["assessment"]["assessment_id"]


@pytest.fixture
def cited(compared_base, tmp_path):
    """A copy of that Study with three declarations, one of them withdrawn: the ids of each kind a record can cite."""
    base, attempts, assessments = compared_base
    study = tmp_path / "study"
    shutil.copytree(base, study)
    d1 = declare(study, [attempts[0]])["declared_deviation_id"]
    d2 = declare(study, [attempts[0]], text="withdrawn later")["declared_deviation_id"]
    d3 = declare(study, [references_id(study)], text="a third one")["declared_deviation_id"]
    w = declare(study, [d2], text="the review is done")["declared_deviation_id"]
    return {"study": study, "attempt": attempts[0], "references": references_id(study), "assessment": assessments[0], "assessments": assessments,
            "declaration": d1, "other declaration": d3, "withdrawn": d2, "withdrawal": w, "unknown": "11111111-1111-4111-8111-111111111111"}


# (the ids the record cites, by their names in `cited`; the code of its refusal, or "ok")
CITATIONS = {
    "a withdrawal of a Declared deviation that does not exist": (["unknown"], NOT_HELD),
    "a withdrawal of a declaration already withdrawn": (["withdrawn"], ALREADY_WITHDRAWN),
    "a record that cites a withdrawal": (["withdrawal"], CITES_A_WITHDRAWAL),
    "a declaration cited with an Attempt": (["declaration", "attempt"], MIX),
    "a declaration cited with a References set": (["declaration", "references"], MIX),
    "a declaration cited with an Assessment": (["declaration", "assessment"], MIX),
    "a withdrawal cited with an Attempt": (["withdrawal", "attempt"], MIX),
    "several declarations": (["declaration", "other declaration"], SEVERAL),
    "1 with 2: an id not held, a declaration and an Attempt": (["unknown", "declaration", "attempt"], NOT_HELD),
    "2 with 3: two declarations and an Attempt": (["declaration", "other declaration", "attempt"], MIX),
    "3 with 4: a declaration and a withdrawal": (["declaration", "withdrawal"], SEVERAL),
    "4 with 5 cannot co-occur: a withdrawal cited with an Assessment": (["withdrawal", "assessment"], MIX),
    "5 with 6 cannot co-occur: a declaration already withdrawn cited with an Assessment": (["withdrawn", "assessment"], MIX),
    "a withdrawal of a declaration that is not withdrawn": (["declaration"], "ok"),
}


@pytest.mark.parametrize("case", CITATIONS)
def test_each_record_whose_cited_ids_are_refused_has_the_code_of_the_first_check_that_fails_and_writes_nothing(case, cited):
    names, expected = CITATIONS[case]
    # D-071 on chadlis/hypotrail#75, Conditions: "there are three refusals, each with its own code, exit and no-write witness:" | "a mix;" |
    # "several Declared deviations;" | "citing a withdrawal, which is distinct from "already withdrawn";"
    assert len({MIX, SEVERAL, CITES_A_WITHDRAWAL}) == 3 and CITES_A_WITHDRAWAL != ALREADY_WITHDRAWN
    study = cited["study"]
    before, sequence = tree(study), seq(study)
    code, payload, err = deviation(study, [cited[name] for name in names], text="withdrawn: the review is done")
    assert (code, outcome(payload)) == ((0, "ok") if expected == "ok" else (2, expected)), (payload, err)
    if expected == "ok":
        assert payload["declared_deviation"]["cited_ids"] == [cited["declaration"]]
        return
    assert tree(study) == before and seq(study) == sequence
    if case == "a record that cites a withdrawal":  # a declaration once withdrawn stays withdrawn
        from _compare_helpers import compare
        from _study_helpers import run_json

        rows = {row["declared_deviation_id"]: row for row in run_json("status", "--study", study)[1]["declared_deviations"]}
        assert (rows[cited["withdrawn"]]["withdrawn"], rows[cited["withdrawn"]]["withdrawn_by"]) == (True, cited["withdrawal"])
        code, payload, err = compare(study, *cited["assessments"])
        assert code == 0, (payload, err)
        assert not [w for w in payload["comparison"]["warnings"] if cited["withdrawn"] in w["message"]], payload["comparison"]["warnings"]


# --- TB2.7, TB2.8: which ids a Declared deviation may cite ---------------------------------------------------------------------


def _bike_revised(base):
    from _revision_helpers import new_revision
    from _study_helpers import examples_copy

    def corrected_day(table):
        row = next(r for r in table if r["dteday"] == "2012-03-15")
        row["cnt"], row["registered"] = str(int(row["cnt"]) + 1000), str(int(row["registered"]) + 1000)

    study, _ = init_study(base)
    code, payload, err = new_revision(study, "--examples-dir", examples_copy(base, rows=corrected_day, name="revised"))
    assert code == 0, (payload, err)
    return study


def _chinook_revised(base):
    from _chinook_helpers import init_chinook
    from _revision_helpers import corrected_chinook_references, new_revision

    study, _ = init_chinook(base)
    corrected = corrected_chinook_references(base, lambda records: records["D03"].update(rows=[[1300]], reference_version="chinook-references/2"))
    code, payload, err = new_revision(study, "--examples-dir", corrected)
    assert code == 0, (payload, err)
    return study


@pytest.fixture(scope="module")
def revised(tmp_path_factory):
    """{Track: a Study whose second revision holds a corrected References set}."""
    return {"bike": _bike_revised(tmp_path_factory.mktemp("bike")), "chinook": _chinook_revised(tmp_path_factory.mktemp("chinook"))}


def study_artifacts(study) -> list:
    """(artifact_id, role) of every entry of `artifacts` of every revision, as `status --json` lists them."""
    from _study_helpers import run_json

    return [(entry["artifact_id"], entry["role"]) for revision in run_json("status", "--study", study)[1]["revisions"] for entry in revision["artifacts"]]


@pytest.mark.parametrize("track", ["bike", "chinook"])
def test_a_study_artifact_cited_alone_is_accepted_when_its_role_is_references_and_refused_as_a_kind_that_cannot_be_cited_otherwise(track, revised, tmp_path):
    listed = study_artifacts(revised[track])
    assert len({artifact_id for artifact_id, role in listed if role == "references"}) == 2  # the earlier set and the corrected one
    assert {role for _, role in listed} - {"references"}, listed  # the walk reaches roles that are refused
    for number, (artifact_id, role) in enumerate(listed):
        study = tmp_path / f"copy-{number}"
        shutil.copytree(revised[track], study)
        before, sequence = tree(study), seq(study)
        code, payload, err = deviation(study, [artifact_id])
        if role == "references":
            assert (code, outcome(payload)) == (0, "ok"), (artifact_id, role, payload)
        else:
            assert (code, outcome(payload)) == (2, NOT_CITABLE), (artifact_id, role, payload)
            assert tree(study) == before and seq(study) == sequence


@pytest.fixture(scope="module")
def every_kind(tmp_path_factory):
    """A Bike Study that holds one record of each kind: Attempts, Assessments, a Comparison, two revisions, a freeze record, Exposure entries."""
    from _report_tracks import Bike

    study, _ = Bike().exposed_study(tmp_path_factory.mktemp("kinds"))
    return study


KINDS_BUT_STUDY_ARTIFACTS = ["attempt", "observation_set", "assessment", "comparison", "revision", "earlier_revision", "freeze_record", "exposure_entry", "decision"]


@pytest.mark.parametrize("kind", [*KINDS_BUT_STUDY_ARTIFACTS, "a declaration", "an Attempt beside an id that is not citable"])
def test_a_held_id_of_each_kind_is_refused_as_a_kind_that_cannot_be_cited_but_an_attempt_and_a_declaration(kind, every_kind, tmp_path):
    from test_decide import KINDS, held, made

    assert set(KINDS) - {"study_artifact"} == set(KINDS_BUT_STUDY_ARTIFACTS) - {"decision"}  # the list `decide`'s test of citable kinds uses
    study = tmp_path / "study"
    shutil.copytree(every_kind, study)
    ids = held(study)
    if kind == "decision":
        cited = [made(study, request_id="first")["decision_id"]]
    elif kind == "a declaration":
        cited = [declare(study, [ids["attempt"]])["declared_deviation_id"]]
    elif kind == "an Attempt beside an id that is not citable":
        cited = [ids["attempt"], ids["assessment"]]
    else:
        cited = [ids[kind]]
    before, sequence = tree(study), seq(study)
    code, payload, err = deviation(study, cited)
    if kind in ("attempt", "a declaration"):
        assert (code, outcome(payload)) == (0, "ok"), (kind, payload)
    else:
        assert (code, outcome(payload)) == (2, NOT_CITABLE), (kind, payload)
        assert tree(study) == before and seq(study) == sequence


# --- TB2.5: `status --json` lists each Declared deviation, whether it is withdrawn and by which one --------------------------------


def test_status_lists_each_declared_deviation_with_its_fields_whether_it_is_withdrawn_and_the_id_that_withdrew_it_computed_at_read(study):
    from _study_helpers import run_json

    written, digests = [], []
    for cited, text in (([attempt_of(study)], PENDING), ([references_id(study)], "a second one"), (None, "the review is done")):
        written.append(declare(study, cited or [written[0]["declared_deviation_id"]], text=text))
        digests.append(tree(study)[f"{FOLDER}/{files(study)[-1].name}"])  # the digest of each file when it was written
    first, second, withdrawal = written
    before, sequence = tree(study), seq(study)
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    rows = payload.get("declared_deviations")
    assert isinstance(rows, list) and len(rows) == 3, rows
    properties = set(contracts.schema()["$defs"]["DeclaredDeviationRecord"]["properties"])
    assert not {"withdrawn", "withdrawn_by"} & properties  # neither is stored
    assert all(set(row) == properties | {"withdrawn", "withdrawn_by"} for row in rows), rows
    assert [{key: row[key] for key in properties} for row in rows] == [first, second, withdrawal]
    assert [(row["withdrawn"], row["withdrawn_by"]) for row in rows] == [(True, withdrawal["declared_deviation_id"]), (False, None), (False, None)]
    assert tree(study) == before and seq(study) == sequence
    assert [tree(study)[f"{FOLDER}/{file.name}"] for file in files(study)] == digests
