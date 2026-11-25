"""The later Assessment has one order: the write-journal position first, then `(recorded_at, id)`.

`status` (whether a Decision applies), `assess` (the earlier Assessment its `rescoring` names) and `report` (the order of the page) are asked about the same two
Assessments, whose journal order and `recorded_at` disagree, for a regression Study and for an agentic Study. No model is called.
"""

import ast
import datetime

import pytest
from _architecture import SOURCE, calls, owners_in, parse_all
from _assess_helpers import assess as assess_regression
from _assess_helpers import fresh_study, observation_set_id, references_id
from _revision_helpers import new_revision
from _study_helpers import examples_copy
from test_decision_history import corrected_day, decide, row_of
from test_rescoring import assessed as assessed_agent
from test_rescoring import correct_d03, imported, revised

from hypotrail.agentic import assess as agent_assess
from hypotrail.ml import assess as ml_assess
from hypotrail.report import gather


class Clock:
    """A `now` that runs through the given instants, one per call, each as an ISO string, so that `recorded_at` can run backwards.

    It replaces the `now` an assess module calls, and no other: the Exposure and write-journal records keep the real time.
    """

    def __init__(self, *instants):
        self.instants = list(instants)

    def now(self) -> str:
        return self.instants.pop(0).isoformat()


def instant(day: int) -> datetime.datetime:
    return datetime.datetime(2026, 1, day, tzinfo=datetime.timezone.utc)


def regression(tmp_path, monkeypatch):
    """(study, assess again, assess after a correction): the Observation set of one Attempt, assessed with MAE."""
    study, attempts = fresh_study(tmp_path / "regression", "seasonal_7")
    observations = observation_set_id(study, attempts["seasonal_7"])

    def assess_once():
        code, payload, err = assess_regression(study, observations, "regression_mae_v1", references_id(study))
        assert code == 0, (payload, err)
        return payload["assessment"]

    def correct():
        code, payload, err = new_revision(study, "--examples-dir", examples_copy(tmp_path, rows=corrected_day, name="revised"))
        assert code == 0, (payload, err)

    return study, assess_once, correct, ml_assess


def agentic(tmp_path, monkeypatch):
    study, observations = imported(tmp_path, name="agentic")

    def assess_once():
        return assessed_agent(study, observations)

    def correct():
        revised(study, correct_d03, tmp_path, "corrected")

    return study, assess_once, correct, agent_assess


@pytest.mark.parametrize("track", [regression, agentic])
def test_two_assessments_whose_journal_order_and_recorded_at_disagree_are_ordered_the_same_way_by_status_assess_and_report(tmp_path, monkeypatch, track):
    study, assess_once, correct, module = track(tmp_path, monkeypatch)
    clock = Clock(instant(20), instant(10), instant(30))
    monkeypatch.setattr(module, "now", clock.now)
    first, second = assess_once(), assess_once()
    assert first["recorded_at"] > second["recorded_at"], "the clock did not run backwards"
    decision = decide(study, [first["assessment_id"]], request_id="d-1")
    observed = {
        "decision": row_of(study, decision["decision_id"])["reasons"],
        "report": [a["record"]["assessment_id"] for a in gather.load(study)["assessments"]],
    }
    correct()
    third = assess_once()
    observed["rescoring"] = third["rescoring"]["earlier_assessment_id"]
    assert observed == {
        "decision": [{"reason": "assessment_superseded", "id": second["assessment_id"]}],
        "report": [first["assessment_id"], second["assessment_id"]],
        "rescoring": second["assessment_id"],
    }


# --- the order is defined once, in `core/write_journal.py`, and read nowhere else --------------------------------------------------

ORDER_FUNCTION = "hypotrail.core.write_journal.assessment_order"
CALLERS = {"hypotrail.core.decisions", "hypotrail.core.rescoring", "hypotrail.report.gather", "hypotrail.report.gather_agent"}
# The functions under `src/` that read the key `recorded_at`: the order function, and the Exposure table of the page, which shows an Exposure entry's `recorded_at` and orders no Assessment.
RECORDED_AT_READS = {
    "hypotrail.core.write_journal:assessment_order": "the order of the Assessments",
    "hypotrail.report.render:_exposure": "shows the `recorded_at` of an Exposure entry, orders no Assessment",
}


def recorded_at_reads(trees: dict) -> set:
    """The functions (the outermost one that holds the read, `module:function`; `module:<module>` outside any) that read the key `recorded_at`: a subscript or a `.get` whose key is that string constant.

    The conventions that bound it: a read spelled with the literal key. A key held in a variable is outside it; no code under `src/` reads it that way, and a planted one
    is a stated limit of this test.
    """
    found = set()
    for module, tree in trees.items():
        for node, owner in owners_in(module, tree):
            subscript = isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == "recorded_at"
            get = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and bool(node.args)
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "recorded_at"
            )
            if subscript or get:
                found.add(owner)
    return found


def test_the_modules_that_call_the_order_function_of_write_journal_are_decisions_rescoring_and_the_two_gathers():
    assert {site.module for site in calls(parse_all(SOURCE)) if site.callee == ORDER_FUNCTION} == CALLERS


def test_no_code_under_src_reads_recorded_at_but_the_order_function_and_the_exposure_table_of_the_page():
    assert recorded_at_reads(parse_all(SOURCE)) == set(RECORDED_AT_READS)


def test_a_sort_by_recorded_at_planted_in_a_module_of_report_is_found(tmp_path):
    root = tmp_path / "src"
    (root / "hypotrail" / "report").mkdir(parents=True)
    (root / "hypotrail" / "__init__.py").write_text("", encoding="utf-8")
    (root / "hypotrail" / "report" / "__init__.py").write_text("", encoding="utf-8")
    (root / "hypotrail" / "report" / "x.py").write_text('def f(rows):\n    return sorted(rows, key=lambda r: r["recorded_at"])\n', encoding="utf-8")
    assert recorded_at_reads(parse_all(root)) == {"hypotrail.report.x:f"}
