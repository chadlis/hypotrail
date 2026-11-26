"""The reads `clients/vscode/test/cli/journey/` keeps of the journey the panel mockups show, made again offline by `tests/_journey_states.py`.

The CLI is run in process on scratch Studies, under the suite's network guard (the `journey_reads` fixture); nothing calls a model.
"""

import ast
import json
import re
import subprocess
from pathlib import Path

from _client_helpers import first_difference
from _journey_states import JOURNEY_KEPT, STATES, kept_journey, name_of

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "tests" / "_journey_states.py"
PARTS = ("exit", "out", "err")


def tracked_names() -> list:
    """The name of each tracked file under `journey/`."""
    listing = subprocess.run(["git", "ls-files", "-z", "--", JOURNEY_KEPT.relative_to(ROOT).as_posix()], cwd=ROOT, capture_output=True, text=True, check=True)
    return sorted(Path(name).name for name in listing.stdout.split("\0") if name)


def kept_object(name: str) -> dict:
    return json.loads((JOURNEY_KEPT / f"{name}.status.out").read_text(encoding="utf-8"))


def test_the_driver_makes_the_twenty_three_real_states_and_the_two_interrupted_one_and_the_kept_files_are_their_reads_both_ways(journey_reads):
    states = [name_of(number, name) for number, name, _ in STATES]
    assert len(states) == 24 and "19-two-interrupted" in states
    expected = set()
    for state in states:
        expected |= {f"{state}.status.{part}" for part in PARTS}
        code, out, _ = journey_reads[f"{state}.status"]
        if code == 0 and json.loads(out)["comparisons"]:
            expected |= {f"{state}.figures.{part}" for part in PARTS}
    made = {f"{name}.{part}" for name in journey_reads for part in PARTS}
    names = set(tracked_names())
    for name in sorted(names | made | expected):
        assert name in names and name in made and name in expected, name


def test_each_kept_read_of_the_journey_is_the_clis_own_once_its_values_are_replaced_and_state_00_is_the_refusal_as_printed(journey_reads):
    assert journey_reads
    for name, (code, out, err) in journey_reads.items():
        kept_code, kept_out, kept_err = kept_journey(name)
        assert (code, err) == (kept_code, kept_err), name
        if not json.loads(kept_out)["ok"]:
            assert out == kept_out, name  # a refusal names no scratch folder and is kept as printed
            continue
        assert first_difference(json.loads(kept_out), json.loads(out)) is None, name
    code, out, _ = journey_reads["00-no-study.status"]
    assert code == 2 and json.loads(out)["error"]["code"] == "STUDY_NOT_FOUND"


# Each kept state, with the case it is kept for: the counts of `pending_decisions` and `decisions`, the `state` of each Decision's
# `evidence_change` (None when it is null) and its `author`, the `withdrawn` values of `declared_deviations`, the count of `recoverable`
# Attempts, and the counts of `assessments` and `comparisons`.
JOURNEY_CASES = {
    "04-pending": (1, 0, [], [], 0, 2, 1),
    "07-rescored": (0, 1, [("evidence_rescored", "human")], [], 0, 4, 1),
    "08-result-changed": (0, 1, [("result_changed", "human")], [], 0, 6, 1),
    "10-proxy": (0, 2, [("result_changed", "human"), (None, "proxy")], [], 0, 6, 2),
    "15-deviation": (1, 2, [("result_changed", "human"), (None, "proxy")], [False], 0, 7, 3),
    "16-deviation-withdrawn": (1, 2, [("result_changed", "human"), (None, "proxy")], [True, False], 0, 7, 3),
    "17-interrupted": (1, 2, [("result_changed", "human"), (None, "proxy")], [True, False], 1, 7, 3),
    "18-recovered": (1, 2, [("result_changed", "human"), (None, "proxy")], [True, False], 0, 7, 3),
    "19-two-interrupted": (1, 2, [("result_changed", "human"), (None, "proxy")], [True, False], 2, 7, 3),
    "33-chinook-assessed": (0, 0, [], [], 0, 1, 0),
}


def test_each_kept_state_of_the_journey_holds_the_case_it_is_kept_for():
    for name, (pending, decided, evidence, withdrawn, recoverable, assessments, comparisons) in JOURNEY_CASES.items():
        read = kept_object(name)
        assert (len(read["pending_decisions"]), len(read["decisions"])) == (pending, decided), name
        assert [((d["evidence_change"] or {}).get("state"), d["author"]) for d in read["decisions"]] == evidence, name
        assert [entry["withdrawn"] for entry in read["declared_deviations"]] == withdrawn, name
        assert sum(attempt["recoverable"] for attempt in read["attempts"]) == recoverable, name
        assert (len(read["assessments"]), len(read["comparisons"])) == (assessments, comparisons), name


def test_state_12_holds_an_attempt_on_public_check_that_no_assessment_cites_whose_produced_count_is_184():
    read = kept_object("12-public-check-run")
    [check] = [attempt for attempt in read["attempts"] if attempt["request_id"] == "check"]
    assert check["item_counts"]["produced"] == 184
    records = json.dumps([read["assessments"], read["comparisons"]])
    assert check["attempt_id"] not in records and all(artifact["path"] not in records for artifact in check["artifacts"])
    assert read["exposures"]["entries"] == []


def test_the_driver_gives_run_agent_the_scripted_fixture_mode_only_and_names_no_live_mode():
    tree = ast.parse(DRIVER.read_text(encoding="utf-8"))
    texts = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    assert not [text for text in texts if re.search(r"llm_live", text)]
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    modes = [
        call.args[at + 1].value
        for call in calls
        for at, arg in enumerate(call.args[:-1])
        if isinstance(arg, ast.Constant) and arg.value == "--mode" and isinstance(call.args[at + 1], ast.Constant)
    ]
    assert modes == ["scripted_fixture"]
