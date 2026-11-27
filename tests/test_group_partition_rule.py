"""The Workload's rule `group_partition_rule: disjoint` (#292): a group carried by Cases of two Partitions is refused when the
Workload is loaded, and only when the Workload declares the rule.

Every Workload here is a copy of `chinook_prose`, whose 10 `dev` groups and 2 `public_check` groups share none. No provider is called.
"""

import json
import shutil
from pathlib import Path

import pytest
from _chinook_helpers import episodes_file, import_agent, spec_of
from _revision_helpers import new_revision, snapshot_files
from _study_helpers import EXAMPLES, run_json

from hypotrail.core.errors import InvalidInputError

PROSE = EXAMPLES / "chinook_prose"
DEV_FILE = "cases/chinook-prose-dev.jsonl"
PUBLIC_FILE = "cases/chinook-prose-public-check.jsonl"
RULE = "group_partition_rule"
# P01 is given the group of D01, D02 and D03.
MOVED = {"P01": "customer-12-invoices"}
MOVED_DETAILS = {"path": "cases", "group": "customer-12-invoices", "case_ids": ["D01", "D02", "D03", "P01"], "partitions": ["dev", "public_check"]}


def read_cases(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_cases(path: Path, cases: list) -> None:
    path.write_text("".join(json.dumps(case) + "\n" for case in cases), encoding="utf-8")


def edit_prose(examples: Path, *, rule=None, groups=None) -> Path:
    """Change, in the copy `examples`, the declared rule of `chinook_prose` (None removes it) and the `group` of the Cases `groups` names."""
    workload = examples / "chinook_prose"
    path = workload / "workload.json"
    declaration = json.loads(path.read_text(encoding="utf-8"))
    declaration.pop(RULE, None)
    if rule is not None:
        declaration[RULE] = rule
    path.write_text(json.dumps(declaration, indent=2), encoding="utf-8")
    for file in (DEV_FILE, PUBLIC_FILE):
        cases = read_cases(workload / file)
        write_cases(workload / file, [{**case, "group": groups.get(case["case_id"], case["group"])} for case in cases])
    return examples


def prose_copy(tmp_path, *, rule=None, groups=None, name="examples") -> Path:
    target = Path(tmp_path) / name
    shutil.copytree(EXAMPLES, target)
    return edit_prose(target, rule=rule, groups=groups or {})


def load(examples: Path):
    from hypotrail.agentic.declaration import load_workload

    return load_workload(examples / "chinook_prose")


def refused_by(call) -> InvalidInputError:
    with pytest.raises(InvalidInputError) as caught:
        call()
    return caught.value


def refusal(result) -> dict:
    code, payload, err = result
    assert (code, payload["ok"]) == (2, False), (payload, err)
    return payload["error"]


# --- the refusal on each entry point that writes a Study -----------------------------------------------------------------------


def refused_init(tmp_path):
    examples = prose_copy(tmp_path, rule="disjoint", groups=MOVED)
    study = tmp_path / "study"
    error = refusal(run_json("init", "--workload", "chinook_prose", "--study", study, "--examples-dir", examples))
    assert not study.exists()
    return error


def refused_on_a_study(tmp_path, act):
    """`act(study, examples)` on a Study made before the copy declared the rule and moved a group; the Study is left as it was."""
    examples = prose_copy(tmp_path)
    study = tmp_path / "study"
    code, payload, err = run_json("init", "--workload", "chinook_prose", "--study", study, "--examples-dir", examples)
    assert code == 0, (payload, err)
    edit_prose(examples, rule="disjoint", groups=MOVED)
    before = snapshot_files(study)
    error = refusal(act(study, examples))
    assert snapshot_files(study) == before
    return error


def refused_new_revision(tmp_path):
    return refused_on_a_study(tmp_path, lambda study, examples: new_revision(study, "--examples-dir", examples))


def refused_import(tmp_path):
    source = PROSE / "fixtures" / "answers-concise.jsonl"
    population = episodes_file(tmp_path, [(line["case_id"], line["repeat"]) for line in read_cases(source)])
    return refused_on_a_study(
        tmp_path, lambda study, examples: import_agent(study, source, population, "group-rule-import", "--examples-dir", examples)
    )


@pytest.mark.parametrize("entry_point", [refused_init, refused_new_revision, refused_import], ids=["init", "init --new-revision", "import agent"])
def test_a_group_carried_by_a_dev_case_and_a_public_check_case_is_refused_with_its_sorted_details_and_nothing_written(tmp_path, entry_point):
    error = entry_point(tmp_path)
    assert (error["code"], error["stage"], error["details"]) == ("GROUP_IN_TWO_PARTITIONS", "declaration", MOVED_DETAILS)


def test_the_refusal_names_the_first_shared_group_in_sorted_order_with_every_case_that_carries_it(tmp_path):
    examples = prose_copy(tmp_path, rule="disjoint", groups={**MOVED, "P04": "ambiguous-customer"})
    workload = examples / "chinook_prose"
    write_cases(workload / DEV_FILE, read_cases(workload / DEV_FILE)[::-1])  # the Cases are read in no sorted order
    path = workload / "workload.json"
    declaration = json.loads(path.read_text(encoding="utf-8"))
    declaration["cases"] = {"public_check": declaration["cases"]["public_check"], "dev": declaration["cases"]["dev"]}  # nor the Partitions
    path.write_text(json.dumps(declaration, indent=2), encoding="utf-8")
    error = refused_by(lambda: load(examples))
    assert (error.code, error.details) == (
        "GROUP_IN_TWO_PARTITIONS",
        {"path": "cases", "group": "ambiguous-customer", "case_ids": ["D16", "D17", "D18", "P04"], "partitions": ["dev", "public_check"]},
    )


def test_a_case_id_in_two_partitions_keeps_its_own_code_under_the_rule(tmp_path):
    examples = prose_copy(tmp_path, rule="disjoint")
    public = examples / "chinook_prose" / PUBLIC_FILE
    write_cases(public, read_cases(public) + [read_cases(examples / "chinook_prose" / DEV_FILE)[0]])
    error = refused_by(lambda: load(examples))
    assert (error.code, error.details["case_ids"]) == ("PARTITIONS_NOT_DISJOINT", ["D01"])


# --- without the rule ----------------------------------------------------------------------------------------------------------


def test_without_the_rule_an_entity_by_snapshot_panel_with_every_group_in_both_partitions_gives_a_study(tmp_path):
    public_groups = ["track-1-album", "germany-invoices-2012"]
    panel = {case["case_id"]: public_groups[number % 2] for number, case in enumerate(read_cases(PROSE / DEV_FILE))}
    examples = prose_copy(tmp_path, groups=panel)
    cases = examples / "chinook_prose"
    groups = {partition: {case["group"] for case in read_cases(cases / file)} for partition, file in (("dev", DEV_FILE), ("public_check", PUBLIC_FILE))}
    assert groups["dev"] == groups["public_check"] == set(public_groups)
    study = tmp_path / "study"
    code, payload, err = run_json("init", "--workload", "chinook_prose", "--study", study, "--examples-dir", examples)
    assert code == 0, (payload, err)
    assert spec_of(study)["study_id"] == payload["study"]["study_id"]


# --- the Protocol --------------------------------------------------------------------------------------------------------------


def protocol_of(examples: Path) -> dict:
    from hypotrail.agentic.study import protocol_content

    return protocol_content(load(examples), dataset_sha256="0" * 64)


def test_the_protocol_of_a_workload_that_declares_the_rule_holds_it_and_that_of_one_without_holds_no_such_key(tmp_path):
    assert protocol_of(prose_copy(tmp_path, rule="disjoint", name="declared")).get(RULE) == "disjoint"
    assert RULE not in protocol_of(prose_copy(tmp_path, name="undeclared"))


# --- the closed schema ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["shared", None, True], ids=["shared", "null", "true"])
def test_a_rule_other_than_disjoint_is_refused_as_a_value_the_schema_does_not_allow(tmp_path, value):
    from hypotrail.agentic.declaration import check_schema

    declaration = {**json.loads((PROSE / "workload.json").read_text(encoding="utf-8")), RULE: value}
    error = refused_by(lambda: check_schema(declaration))
    assert (error.code, error.details) == ("DECLARATION_VALUE_NOT_ALLOWED", {"key": RULE, "path": RULE})
