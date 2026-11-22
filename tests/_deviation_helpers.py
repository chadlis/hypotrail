"""Shared by the Declared deviation tests (#155): the `deviation` command on the command line, and the records it writes."""

import json
import uuid
from pathlib import Path

from _study_helpers import run_cli, run_json

CODE = "COMPARISON_DEVIATION_DECLARED"
PENDING = "owner review of References pending"
FOLDER = "declared_deviations"


def seq(study) -> int:
    code, payload, err = run_json("status", "--study", study)
    assert code == 0, (payload, err)
    return payload["write_sequence"]


def deviation(study, cited, *, text=PENDING, author="human", source=None, request_id=None, read_sequence=None, omit=()):
    """`deviation --json` on the command line: (exit code, the JSON object on stdout or None when it printed none, stderr).

    A call that names no `request_id` gets a new one, so two calls are two requests.
    """
    flags = [
        ("--study", study),
        ("--text", text),
        ("--author", author),
        ("--request-id", f"dv-{uuid.uuid4()}" if request_id is None else request_id),
        ("--read-sequence", seq(study) if read_sequence is None else read_sequence),
    ]
    if source is not None:
        flags.append(("--source", source))
    flags += [("--artifact", cited_id) for cited_id in cited]
    code, out, err = run_cli("deviation", *[part for flag, value in flags if flag not in omit for part in (flag, value)], "--json")
    return code, (json.loads(out) if out.strip() else None), err


def outcome(payload):
    """The error code of a refusal, "ok" for a record written or replayed, None when the command printed nothing."""
    if payload is None:
        return None
    return "ok" if payload.get("ok") else payload.get("error", {}).get("code")


def declare(study, cited, **fields) -> dict:
    """The record of a Declared deviation the command accepts."""
    code, payload, err = deviation(study, cited, **fields)
    assert (code, outcome(payload)) == (0, "ok"), (payload, err)
    return payload["declared_deviation"]


def files(study) -> list:
    folder = Path(study) / FOLDER
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def coded(record, code=CODE) -> list:
    """The warnings of a Comparison record that have `code`."""
    return [warning for warning in record["warnings"] if warning["code"] == code]


# --- the Comparisons a Declared deviation covers, for either Track ----------------------------------------------------------------


def compare_ids(study, control, candidate, *more):
    """`compare --json` of two Assessment ids: the Comparison record it wrote."""
    code, payload, err = run_json("compare", "--study", study, "--control", control, "--candidate", candidate, *more)
    assert code == 0, (payload, err)
    return payload["comparison"]


def covered(roles) -> str:
    """The words a warning opens with for the sides it covers: `roles` is ("control",), ("candidate",) or both."""
    return f"The {' and the '.join(roles)} of this Comparison {'is' if len(roles) == 1 else 'are'} covered by the Declared deviation"


def references_of(study) -> str:
    """The `artifact_id` of the References set of the Study's current revision, whatever its Track."""
    spec = json.loads((Path(study) / "study.json").read_text(encoding="utf-8"))
    return next(entry["artifact_id"] for entry in spec["artifacts"] if entry["ref"]["role"] == "references")


def bike_world(tmp_path, count=4):
    """A Bike Study with `count` Attempts of seasonal_7 on dev, each assessed: (study, [Attempt ids], [Assessment ids])."""
    from _assess_helpers import assess, observation_set_id
    from _study_helpers import init_study, run_ml

    study, _ = init_study(tmp_path)
    attempts, assessments = [], []
    for number in range(count):
        code, payload, err = run_ml(study, "seasonal_7", "dev", f"run-{number}")
        assert code == 0, (payload, err)
        attempts.append(payload["attempt"]["attempt_id"])
        code, payload, err = assess(study, observation_set_id(study, payload["attempt"]), "regression_mae_v1", references_of(study))
        assert code == 0, (payload, err)
        assessments.append(payload["assessment"]["assessment_id"])
    return study, attempts, assessments


def chinook_world(tmp_path, count=4):
    """A Chinook Study with `count` imports of the same answers, each assessed: (study, [Attempt ids], [Assessment ids])."""
    from _agent_compare_helpers import answer_lines, imported
    from _chinook_helpers import init_chinook

    study, _ = init_chinook(tmp_path)
    attempts, assessments = [], []
    for number in range(count):
        attempt, assessment = imported(tmp_path, study, f"answers-{number}", answer_lines())
        attempts.append(attempt["attempt_id"])
        assessments.append(assessment["assessment_id"])
    return study, attempts, assessments


def reassessed(study, attempt_ids, scorer):
    """A new Assessment of the Observation set of each Attempt, against the References set of the Study's current revision."""
    found = []
    for attempt_id in attempt_ids:
        folder = Path(study) / "attempts" / attempt_id
        observations = json.loads((folder / "observation_set.json").read_text(encoding="utf-8"))["observation_set_id"]
        code, payload, err = run_json("assess", "--study", study, "--observations", observations, "--scorer", scorer, "--references", references_of(study))
        assert code == 0, (payload, err)
        found.append(payload["assessment"]["assessment_id"])
    return found


def ids_named(record) -> list:
    """The Declared deviation ids that the warnings of the code of TB2.3 name, in the order of the warnings."""
    return [warning["message"].split("covered by the Declared deviation ", 1)[1].split(" ", 1)[0].rstrip(",:") for warning in coded(record)]


# --- the scenarios, each called for both Tracks by tests/test_compare.py and tests/test_compare_agent.py --------------------------


def a_declaration_covers_the_sides_whose_attempt_it_cites(world, roles):
    study, attempts, assessments = world
    before = compare_ids(study, assessments[0], assessments[1])
    cited = [attempts[0]] * ("control" in roles) + [attempts[1]] * ("candidate" in roles)
    declared = declare(study, cited)
    record = compare_ids(study, assessments[0], assessments[1])
    warnings = coded(record)
    assert len(warnings) == 1, record["warnings"]
    message = warnings[0]["message"]
    assert message.startswith(covered(roles)), message
    assert declared["declared_deviation_id"] in message and PENDING in message, message
    assert message in record["limitations"]
    assert record["comparability"]["status"] == before["comparability"]["status"]
    assert [w for w in record["warnings"] if w["code"] != CODE] == before["warnings"]  # it adds this warning and nothing else


def a_references_citation_covers_both_sides(world):
    study, _, assessments = world
    declared = declare(study, [references_of(study)])
    warnings = coded(compare_ids(study, assessments[0], assessments[1]))
    assert len(warnings) == 1, warnings
    assert warnings[0]["message"].startswith(covered(("control", "candidate"))) and declared["declared_deviation_id"] in warnings[0]["message"]


def a_declaration_covers_no_other_side(world):
    study, attempts, assessments = world
    declare(study, [attempts[0]])
    record = compare_ids(study, assessments[2], assessments[3])
    assert coded(record) == [], record["warnings"]


def two_declarations_give_one_warning_each_in_the_order_of_their_write_sequence(world):
    study, attempts, assessments = world
    first = declare(study, [references_of(study)])
    second = declare(study, [attempts[0]], text="the Control's Attempt was rerun by hand")
    assert first["write_sequence"] < second["write_sequence"]
    record = compare_ids(study, assessments[0], assessments[1])
    assert ids_named(record) == [first["declared_deviation_id"], second["declared_deviation_id"]], record["warnings"]


def a_withdrawal_gives_no_coverage(world):
    study, attempts, assessments = world
    declared = declare(study, [attempts[0]])
    withdrawal = declare(study, [declared["declared_deviation_id"]], text="the review is done")
    record = compare_ids(study, assessments[0], assessments[1])
    assert coded(record) == [], record["warnings"]
    named = (declared["declared_deviation_id"], withdrawal["declared_deviation_id"])
    assert not [w for w in record["warnings"] if any(each in w["message"] for each in named)], record["warnings"]


def a_comparison_is_not_updated_and_a_new_compare_is_the_remedy(world):
    from _study_helpers import sha256

    study, attempts, assessments = world

    def digest(record):
        return sha256(Path(study) / "comparisons" / record["comparison_id"] / "comparison.json")

    first = compare_ids(study, assessments[0], assessments[1])
    kept = digest(first)
    declared = declare(study, [attempts[0]])
    assert digest(first) == kept
    second = compare_ids(study, assessments[0], assessments[1])
    kept_second = digest(second)
    declare(study, [declared["declared_deviation_id"]], text="the review is done")
    assert digest(second) == kept_second
    third = compare_ids(study, assessments[0], assessments[1])
    assert len({first["comparison_id"], second["comparison_id"], third["comparison_id"]}) == 3
    assert [len(coded(record)) for record in (first, second, third)] == [0, 1, 0]


def a_corrected_references_set_is_not_covered(earlier_set, earlier, corrected, study):
    """`earlier` and `corrected` are two Assessments of the same two Observation sets, against the earlier References set and the corrected one."""
    declare(study, [earlier_set])
    assert coded(compare_ids(study, *corrected)) == []
    assert len(coded(compare_ids(study, *earlier))) == 1


# --- the report: what each Comparison's card shows --------------------------------------------------------------------------------


def comparison_cards(page: str) -> dict:
    """{comparison_id: the text of its card, tags removed}, in the order of the page: a card is the `<div class="card">` that opens with that Comparison."""
    import re

    cards = {}
    for match in re.finditer(r'<div class="card"><p><b>Comparison </b>([0-9a-f-]{36})</p>', page):
        depth, at = 0, match.start()
        for tag in re.finditer(r"<(/?)div\b", page[at:]):
            depth += -1 if tag.group(1) else 1
            if depth == 0:
                cards[match.group(1)] = " ".join(re.sub(r"<[^>]+>", " ", page[at:at + tag.end()]).split())
                break
    return cards


def comparability_cells(out) -> dict:
    """{comparison_id: the cell of its row `Comparability`} of a rendered page."""
    from _report_helpers import doc_of

    doc = doc_of(out)
    order = list(comparison_cards(Path(out).read_text(encoding="utf-8")))
    return {comparison_id: dict((row[0], row[1]) for row in doc.body(f"comparison-{index}"))["Comparability"] for index, comparison_id in enumerate(order)}


def rendered(study, out) -> str:
    from _report_helpers import report

    code, payload, err = report(study, out)
    assert code == 0, (payload, err)
    return Path(out).read_text(encoding="utf-8")


def the_report_shows_what_each_comparison_recorded_and_computes_nothing_from_the_declared_deviations(world, out_folder):
    study, _, assessments = world
    first = compare_ids(study, assessments[0], assessments[1])
    declared = declare(study, [references_of(study)])
    page = rendered(study, out_folder / "declared.html")
    assert CODE not in page and declared["declared_deviation_id"] not in page
    second = compare_ids(study, assessments[0], assessments[1])
    cards = comparison_cards(rendered(study, out_folder / "compared.html"))
    assert CODE in cards[second["comparison_id"]] and CODE not in cards[first["comparison_id"]], cards
    withdrawal = declare(study, [declared["declared_deviation_id"]], text="the review is done")
    page = rendered(study, out_folder / "withdrawn.html")
    assert CODE in comparison_cards(page)[second["comparison_id"]] and withdrawal["declared_deviation_id"] not in page
