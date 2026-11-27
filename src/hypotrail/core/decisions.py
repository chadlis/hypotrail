"""`decide`: one decision, kept in the Study (chadlis/hypotrail#109, slice #104; D-031 on chadlis/hypotrail#75 and the decisions that follow it on that issue).

The Study is the only decision authority: a decision is a record of the Study, and nowhere else. It is one file,

```
decisions/<seq>-<decision_id>.json   one decision each, published atomically and never rewritten
```

`<seq>` is the decision's position among the Study's decisions, count + 1, six digits, as in `exposures/`. The record (`DecisionRecord` of the
contract schema) holds the question it answers and the option chosen, both free text and never empty; the author, `human` or `proxy`, recorded by
its kind only; a declared `source` text, or null; the ids it cites, de-duplicated and sorted, at least one; its `request_id`; the `revision` of the
Study's current StudySpec; and two numbers of the write sequence (`hypotrail.core.write_journal`): the `read_sequence` its author read and its
own `write_sequence`, the position of the `begin` entry of the command that recorded it, always one above the first. `decide` writes
`decision/2` (`DecisionRecordV2`), which holds three keys more, always present: `question_id` and `option_id`, the ids of the pending question
and of the option chosen, checked against `PENDING_QUESTION` and `PENDING_OPTIONS`; and `words`, the person's texts kept whole with the
channel and `by` label its caller declared and `authenticated` false, never read by a check. Each is null when not given. A `decision/1`
record stays as it was written. Words with the channel `file_relayed` need a `source` that is not empty, which names the outside act the
file comes from; nothing checks it.

`decide` takes its steps in the order that `hypotrail.core.study_write` gives a writer that has a `request_id` (the checks of the other writers are listed in handbook chapter 04): the arguments and the Study before the lock, then the lock. The arguments (the read sequence value is the library's first argument check, then
`REQUEST_ID_EMPTY`, the author, that `--read-sequence` is given, that `--artifact` is given, `DECISION_FIELD_EMPTY`, then the ids and the words); `STUDY_NOT_FOUND`. Under the lock: the request identity; the stale sequence (`Write.replay_decision` runs both); then `CITED_ID_NOT_FOUND`. A refusal appends nothing to
the write journal. The request identity is shared with the Attempts of the Study (one namespace, `hypotrail.core.requests`): the same `request_id` with
the same decision (question, option, author, source, cited ids, question id, option id and words; the read sequence is not part of it) returns the recorded decision and writes
nothing, even when the sequence has moved on; with another decision, or when it names an Attempt, it is `REQUEST_CONFLICT`.

An id is citable when the Study holds a record with that id, of one of these kinds: Attempt, Observation set, Assessment, Comparison, Study artifact,
revision (by its `revision` value, never its `revision_number`), freeze record, Exposure entry, decision or Declared deviation, a withdrawal included. A `request_id`, the `study_id`, a path
and a file's content digest (`sha256`, `protocol_digest`) are not citable.

`status` lists the decisions with whether each still applies (chadlis/hypotrail#110; D-033 on chadlis/hypotrail#75, amended by D-034 on chadlis/hypotrail#75, D-035 on chadlis/hypotrail#75, D-036 on chadlis/hypotrail#75 and D-037 on chadlis/hypotrail#75): `history(study)`.
Whether a decision applies is computed when the Study is read, from the ids it cites and the records of the Study, and is never stored: no record is written
or changed when it changes. A decision no longer applies when a cited id is no longer held (`cited_id_not_held`), when the Study's current revision differs
from the `revision` its record stores (`revision_changed`, its `id` the current `revision`), or when a cited Assessment has a later Assessment of the same
Observation set and the same Scorer id, whatever its version (`assessment_superseded`, its `id` the latest of the later Assessments). "Later" is the
order of `write_journal.assessment_order`. A later decision on the same question changes nothing.

The rule follows a cited Comparison one hop, to its two Assessments, the Control then the Candidate (`sides`): one that has a later Assessment gives
`compared_assessment_superseded`, its `id` the latest of the later ones, and one the Study does not hold gives `compared_assessment_not_held`, its
`id` the missing Assessment. Each Assessment reached gives one entry at most, at the first cited Comparison that names it, in the order of
`cited_ids`; these entries come after those of the three reasons above. The hop starts from a cited Comparison only and goes no further.

Each decision also gets `evidence_change`, what happened to its evidence since: null when no Assessment it cites or reaches has a later Assessment,
otherwise `{state, lines}`, one line per such Assessment (its anchor), in the order of first appearance through `cited_ids`. The `state` of a line is
`result_changed` when a later Assessment that counts changed an Item, `evidence_rescored` when one counts and none changed an Item, and `repeated`
otherwise; a later Assessment counts only when its `rescoring.earlier_assessment_id` is the anchor or an Assessment later than it (`_counts`). The
`state` of `evidence_change` is the strongest of its lines. A line shows the Metric values of the anchor and of the latest later Assessment as their
records hold them, and no difference of the two.

Each decision also gets `level`, computed when the Study is read and never stored (`level`): `pr` when a `human` decision's `source` has the
form of a pull request citation, else `panel`, `relayed` or `undeclared` by the channel of its words, and null for a `proxy` decision.

`status` also lists the pending decisions (`pending`): a Comparison is pending when both its Assessments are of the current revision, neither has
a later Assessment, and no decision that applies cites it. Each comes with the one question and the three options of `PENDING_QUESTION` and
`PENDING_OPTIONS`, each option with its consequence text. Without `--question-id` and `--option-id`, `decide` records a question and an option as given and checks neither against them.
"""

import contextlib
import re
import uuid
from pathlib import Path

from hypotrail.core import artifacts, contracts, deviations, exposure, requests, revisions, study_write, write_journal  # `deviations` imports this module too: each uses the other only when called
from hypotrail.core import study as layout
from hypotrail.core.errors import InvalidInputError

DECISIONS_DIR = "decisions"
STAGE = "decision"
AUTHORS = ("human", "proxy")
# the fields that make "the same decision" (D-034 on chadlis/hypotrail#75), in the order `differs` lists them; a `decision/1` record holds
# none of the last three and is compared as holding null for each
IDENTITY_FIELDS = ("question", "option", "author", "source", "cited_ids", "question_id", "option_id", "words")
SCHEMA_VERSION = "decision/2"
# who declared where the words come from; `authenticated` is false whatever the channel
CHANNELS = ("panel", "choice", "chat_relayed", "file_relayed")
CHOICE, CHAT_RELAYED, FILE_RELAYED = "choice", "chat_relayed", "file_relayed"
# The levels of a `human` Decision, strongest first (ADR 0006, point 4), derived when the Study is read and never stored; a `proxy` Decision
# has none. `pr` is when "`source` cites a merged pull request", which is "written in `source` as
# `https://github.com/<owner>/<repo>/pull/<n>@<40-hex merge commit>`. Hypotrail checks only its form, offline, and never asks the forge."
# (ADR 0006, points 4 and 5)
LEVELS = ("pr", "panel", "relayed", "undeclared")
LEVEL_OF_CHANNEL = {"panel": "panel", "choice": "panel", "chat_relayed": "relayed", "file_relayed": "relayed"}
PULL_REQUEST_CITATION = re.compile(r"https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9._-]+/pull/[1-9][0-9]*@[0-9a-f]{40}")
CITED_ID_NOT_HELD, REVISION_CHANGED, ASSESSMENT_SUPERSEDED = "cited_id_not_held", "revision_changed", "assessment_superseded"
COMPARED_ASSESSMENT_SUPERSEDED, COMPARED_ASSESSMENT_NOT_HELD = "compared_assessment_superseded", "compared_assessment_not_held"
# "A constant in `core/decisions.py` lists the reason codes." (D-078 on chadlis/hypotrail#75, item 4)
REASON_CODES = (CITED_ID_NOT_HELD, REVISION_CHANGED, ASSESSMENT_SUPERSEDED, COMPARED_ASSESSMENT_SUPERSEDED, COMPARED_ASSESSMENT_NOT_HELD)
RESULT_CHANGED, EVIDENCE_RESCORED, REPEATED = "result_changed", "evidence_rescored", "repeated"
# the states of `evidence_change`, the strongest first
EVIDENCE_STATES = (RESULT_CHANGED, EVIDENCE_RESCORED, REPEATED)

# The question and the options of a pending decision: the same for every Comparison of every Study, and held by no Workload file.
PENDING_QUESTION = {"id": "keep_after_comparison", "text": "Which Configuration do we keep after this Comparison?"}
_NOTHING_ELSE = "The Comparison stops being pending while that Decision applies. Beyond that Decision and its two write-journal entries, nothing is written, and the Study enforces nothing on later work"
PENDING_OPTIONS = (
    {
        "id": "keep_control",
        "text": "Keep the Control",
        "consequence": f'A Decision that cites this Comparison is recorded with the option "Keep the Control". {_NOTHING_ELSE}.',
    },
    {
        "id": "keep_candidate",
        "text": "Keep the Candidate",
        "consequence": f'A Decision that cites this Comparison is recorded with the option "Keep the Candidate". {_NOTHING_ELSE}.',
    },
    {
        "id": "keep_neither",
        "text": "Choose neither yet",
        "consequence": (
            f'A Decision that cites this Comparison is recorded with the option "Choose neither yet". {_NOTHING_ELSE}: '
            "a later compare writes a new Comparison that is pending under the same rule."
        ),
    },
)


def records(study) -> list:
    """The Study's decisions, in the order they were recorded; each is validated after it is read."""
    return layout.read_records(study, DECISIONS_DIR)


def find_by_request(study, request_id: str):
    """The decision recorded under `request_id`, or None."""
    return next((record for record in records(study) if record["request_id"] == request_id), None)


def held_ids(study) -> set:
    """The ids of the records of the Study that a decision may cite."""
    study = Path(study)
    found = set(layout.attempt_ids(study))
    for attempt_id in layout.attempt_ids(study):
        for ref in layout.observation_set_refs(layout.read_manifest(study, attempt_id)):
            with contextlib.suppress(OSError):  # a referenced record that is missing holds no id
                found.add(layout.read_record(study, ref["path"])["observation_set_id"])
    found |= {record["assessment_id"] for record in layout.assessment_records(study)}
    found |= {record["comparison_id"] for record in layout.comparison_records(study)}
    for spec in revisions.revision_specs(study):
        found.add(spec["revision"])
        found |= {entry["artifact_id"] for entry in spec["artifacts"]}
    found |= {record["freeze_id"] for record in exposure.freeze_records(study)}
    found |= {record["entry_id"] for record in exposure.entries(study)}
    found |= {record["decision_id"] for record in records(study)}
    found |= {record["declared_deviation_id"] for record in deviations.records(study)}
    return found


def level(record: dict) -> str | None:
    """The level of a Decision (`LEVELS`), or None for a `proxy` Decision, which is off the scale."""
    if record["author"] != "human":
        return None
    if record["source"] is not None and PULL_REQUEST_CITATION.fullmatch(record["source"]):
        return "pr"
    words = record.get("words")
    return "undeclared" if words is None else LEVEL_OF_CHANNEL[words["channel"]]


def _later(assessment: dict, assessments: dict, order) -> list:
    """The later Assessments of `assessment`: of the same Observation set and the same Scorer id, whatever its version."""
    return [
        other
        for other in assessments.values()
        if other["observation_set_id"] == assessment["observation_set_id"]
        and other["scorer"]["id"] == assessment["scorer"]["id"]
        and order(other) > order(assessment)
    ]


def sides(comparison: dict) -> tuple:
    """(`control`, its Assessment id), (`candidate`, its Assessment id) of a Comparison record: its `roles`, or left and right when it holds none."""
    roles = comparison.get("roles")
    if roles is None:
        return ("control", comparison["left_assessment_id"]), ("candidate", comparison["right_assessment_id"])
    return ("control", roles["control_assessment_id"]), ("candidate", roles["candidate_assessment_id"])


def _reasons(record: dict, *, held: set, revision: str, assessments: dict, comparisons: dict, order) -> list:
    """Why `record` no longer applies: `[{"reason", "id"}]`, empty when it applies."""

    reasons = [{"reason": CITED_ID_NOT_HELD, "id": cited} for cited in record["cited_ids"] if cited not in held]
    if record["revision"] != revision:
        reasons.append({"reason": REVISION_CHANGED, "id": revision})
    for cited in record["cited_ids"]:
        cited_assessment = assessments.get(cited)
        if cited_assessment is None:
            continue
        later = _later(cited_assessment, assessments, order)
        if later:
            reasons.append({"reason": ASSESSMENT_SUPERSEDED, "id": max(later, key=order)["assessment_id"]})
    reached: set = set()
    for cited in record["cited_ids"]:
        comparison = comparisons.get(cited)
        if comparison is None:
            continue
        for _, assessment_id in sides(comparison):
            if assessment_id in reached:
                continue
            reached.add(assessment_id)
            assessment = assessments.get(assessment_id)
            if assessment is None:
                reasons.append({"reason": COMPARED_ASSESSMENT_NOT_HELD, "id": assessment_id})
                continue
            later = _later(assessment, assessments, order)
            if later:
                reasons.append({"reason": COMPARED_ASSESSMENT_SUPERSEDED, "id": max(later, key=order)["assessment_id"]})
    return reasons


def _counts(later: dict, anchor: dict, assessments: dict, order) -> bool:
    """Whether `later` counts as rescored or changed for the line of `anchor`: its `rescoring` names the anchor or an Assessment later than it.

    A `rescoring` that is null, or absent from the record, or that names an earlier Assessment or one the Study does not hold, counts as a repeat.
    """
    rescoring = later.get("rescoring")
    if rescoring is None:
        return False
    earlier = assessments.get(rescoring["earlier_assessment_id"])
    return earlier is not None and (earlier["assessment_id"] == anchor["assessment_id"] or order(earlier) > order(anchor))


def _line(anchor: dict, comparison_id, role, later: list, assessments: dict, order) -> dict:
    counted = [other for other in later if _counts(other, anchor, assessments, order)]
    changed = [other for other in counted if other["rescoring"]["changed_items"]]
    latest = max(later, key=order)
    latest_values = {metric["id"]: metric["value"] for metric in latest["metrics"]}
    return {
        "assessment_id": anchor["assessment_id"],
        "comparison_id": comparison_id,
        "role": role,
        "latest_assessment_id": latest["assessment_id"],
        "state": RESULT_CHANGED if changed else EVIDENCE_RESCORED if counted else REPEATED,
        "changed_item_count": len({item["item_id"] for other in changed for item in other["rescoring"]["changed_items"]}),
        "metrics": [{"id": metric["id"], "cited": metric["value"], "latest": latest_values.get(metric["id"])} for metric in anchor["metrics"]],
    }


def _evidence_change(record: dict, *, assessments: dict, comparisons: dict, order, **_) -> dict | None:
    """What happened to the evidence of `record` since: `{state, lines}`, or None when no Assessment it cites or reaches has a later Assessment."""
    reached = {}  # the first cited Comparison that names each Assessment, and the role it names it in
    for cited in record["cited_ids"]:
        if cited in comparisons:
            for role, assessment_id in sides(comparisons[cited]):
                reached.setdefault(assessment_id, (cited, role))
    anchors = []  # in the order of first appearance through `cited_ids`
    for cited in record["cited_ids"]:
        for assessment_id in [assessment_id for _, assessment_id in sides(comparisons[cited])] if cited in comparisons else [cited]:
            if assessment_id in assessments and assessment_id not in anchors:
                anchors.append(assessment_id)
    lines = []
    for assessment_id in anchors:
        anchor = assessments[assessment_id]
        later = _later(anchor, assessments, order)
        if later:
            lines.append(_line(anchor, *reached.get(assessment_id, (None, None)), later, assessments, order))
    if not lines:
        return None
    return {"state": min((line["state"] for line in lines), key=EVIDENCE_STATES.index), "lines": lines}


def history(study) -> list:
    """The Study's decisions in the order they were recorded, each with every field `decide` recorded, `applies`, `reasons` and `evidence_change` (read only)."""
    study = Path(study)
    recorded = records(study)
    if not recorded:
        return []
    shared = {
        "held": held_ids(study),
        "revision": layout.read_spec(study)["revision"],
        "assessments": {record["assessment_id"]: record for record in layout.assessment_records(study)},
        "comparisons": {record["comparison_id"]: record for record in layout.comparison_records(study)},
        "order": write_journal.assessment_order(study),
    }
    rows = []
    for record in recorded:
        reasons = _reasons(record, **shared)
        rows.append({**record, "applies": not reasons, "reasons": reasons, "evidence_change": _evidence_change(record, **shared), "level": level(record)})
    return rows


def assessments_in_order(study) -> list:
    """Every Assessment record of the Study, as stored, in the one order of the later Assessment (`write_journal.assessment_order`): `status` lists them so."""
    return sorted(layout.assessment_records(study), key=write_journal.assessment_order(study))


def pending(study, rows: list) -> list:
    """The pending decisions: each Comparison of the current revision whose two Assessments have no later Assessment and that no Decision of
    `rows` (the `history`) that applies cites, in the order of `write_journal.comparison_order`, with the question and the options (read only).

    An Assessment is of the current revision when its record holds a `study_revision` whose `revision` is the Study's; one that holds none, or
    that the Study does not hold, is not.
    """
    study = Path(study)
    revision = layout.read_spec(study)["revision"]
    assessments = {record["assessment_id"]: record for record in layout.assessment_records(study)}
    order = write_journal.assessment_order(study)
    cited = {cited_id for row in rows if row["applies"] for cited_id in row["cited_ids"]}
    found = []
    for comparison in sorted(layout.comparison_records(study), key=write_journal.comparison_order(study)):
        (_, control), (_, candidate) = sides(comparison)
        if comparison["comparison_id"] in cited:
            continue
        if not all(side in assessments and (assessments[side].get("study_revision") or {}).get("revision") == revision for side in (control, candidate)):
            continue
        if any(_later(assessments[side], assessments, order) for side in (control, candidate)):
            continue
        found.append(
            {
                "comparison_id": comparison["comparison_id"],
                "control_assessment_id": control,
                "candidate_assessment_id": candidate,
                "question": dict(PENDING_QUESTION),
                "options": [dict(option) for option in PENDING_OPTIONS],
            }
        )
    return found


def _invalid(message: str) -> InvalidInputError:
    return study_write.invalid_arguments(message, study_write.DECIDE)


def _read_words_file(path) -> str:
    """The text of one `--words-file`, whole: its bytes decoded as UTF-8, nothing stripped or normalised."""
    try:
        data = Path(path).read_bytes()
    except OSError as error:
        raise _invalid(f"--words-file {str(path)!r} cannot be read: {error.strerror or error}") from None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise _invalid(f"--words-file {str(path)!r} is not UTF-8 text") from None


def _words(words: list, *, author: str, option: str, option_id, channel, by, source) -> dict | None:
    """The `words` of the record, or None: `words` lists `("text", TEXT)` and `("file", PATH)` in the order given."""
    texts = [value if kind == "text" else _read_words_file(value) for kind, value in words]
    if channel == CHOICE:
        if option_id is None:
            raise _invalid("--channel choice records the text of the option chosen: --option-id is required")
        if texts:
            raise _invalid("--channel choice records the text of the option chosen: give no --words or --words-file")
        texts = [option]
    if not texts:
        if channel is not None or by is not None:
            raise _invalid("--channel and --by describe the person's words: give --words or --words-file")
        return None
    if channel is not None and channel not in CHANNELS:
        raise _invalid(f"the channel of the words is one of {', '.join(CHANNELS)}, not {channel!r}")
    if channel == FILE_RELAYED and not source:
        raise _invalid("--channel file_relayed relays words read from a file: --source names the outside act the file comes from, and is not empty")
    if author != "human":
        raise _invalid("the words on a decision are the words of a human: they need --author human")
    if any(not text for text in texts):
        raise _invalid("a text of the words must not be empty")
    return {"texts": texts, "channel": channel or CHAT_RELAYED, "by": by, "authenticated": False}


def _check_ids(question: str, option: str, question_id, option_id) -> None:
    """`--question-id` and `--option-id` are given together, each an id the core supplies, with `--question` and `--option` its texts."""
    if (question_id is None) != (option_id is None):
        raise _invalid("--question-id and --option-id are given together")
    if question_id is None:
        return
    if question_id != PENDING_QUESTION["id"]:
        raise _invalid(f"the question id of a decision is {PENDING_QUESTION['id']!r}, not {question_id!r}")
    texts = {entry["id"]: entry["text"] for entry in PENDING_OPTIONS}
    if option_id not in texts:
        raise _invalid(f"the option id of a decision is one of {', '.join(texts)}, not {option_id!r}")
    if question != PENDING_QUESTION["text"]:
        raise _invalid(f"--question is the text of {question_id!r}: {PENDING_QUESTION['text']!r}")
    if option != texts[option_id]:
        raise _invalid(f"--option is the text of {option_id!r}: {texts[option_id]!r}")


def decide(
    study,
    *,
    question: str,
    option: str,
    author: str,
    source: str | None,
    cited_ids: list,
    request_id: str,
    read_sequence: int,
    question_id: str | None = None,
    option_id: str | None = None,
    words: list = (),
    channel: str | None = None,
    by: str | None = None,
) -> tuple[dict, bool]:
    """Record (or replay) one decision under the Study's writer lock; return the record and whether it was recorded already.

    `words` lists `("text", TEXT)` for a `--words` and `("file", PATH)` for a `--words-file`, in the order given.
    """
    study = Path(study)
    study_write.check_arguments(study_write.DECIDE, read_sequence, request_id)
    if author not in AUTHORS:
        raise _invalid(f"the author of a decision is one of {', '.join(AUTHORS)}, not {author!r}")
    if read_sequence is None:
        raise _invalid("a decision is made on the write sequence its author read: --read-sequence is required")
    if not cited_ids:
        raise _invalid("a decision cites at least one id: --artifact is required")
    for field, value in (("question", question), ("option", option)):
        if not value:
            raise InvalidInputError("DECISION_FIELD_EMPTY", f"the {field} of a decision must not be empty", stage=STAGE, details={"field": field})
    _check_ids(question, option, question_id, option_id)
    recorded_words = _words(list(words), author=author, option=option, option_id=option_id, channel=channel, by=by, source=source)
    layout.read_spec(study)  # a folder that is no Study is refused before a lock file is created in it
    wanted = {
        "question": question, "option": option, "author": author, "source": source, "cited_ids": sorted(set(cited_ids)),
        "question_id": question_id, "option_id": option_id, "words": recorded_words,
    }
    with study_write.locked(study, study_write.DECIDE, request_id, read_sequence=read_sequence) as write:
        return _decide_locked(study, write, wanted, request_id, read_sequence)


def _decide_locked(study: Path, write, wanted: dict, request_id: str, read_sequence: int) -> tuple[dict, bool]:
    def check_recorded(recorded: dict) -> None:
        differs = [field for field in IDENTITY_FIELDS if recorded.get(field) != wanted[field]]
        if differs:
            raise requests.conflict_between_decisions(request_id, recorded["decision_id"], differs)

    recorded = write.replay_decision(check_recorded)
    if recorded is not None:
        return recorded, True
    spec = layout.read_spec(study)  # read under the lock, after the stale check
    unknown = sorted(set(wanted["cited_ids"]) - held_ids(study))
    if unknown:
        raise InvalidInputError(
            "CITED_ID_NOT_FOUND",
            f"the Study holds no record with the id {', '.join(map(repr, unknown))}; nothing was written",
            stage=STAGE,
            details={"ids": unknown},
        )
    decision_id = str(uuid.uuid4())
    five = {field: wanted[field] for field in ("question", "option", "author", "source", "cited_ids")}
    record = {
        "kind": "decision",
        "schema_version": SCHEMA_VERSION,
        "decision_id": decision_id,
        "request_id": request_id,
        **five,
        "revision": spec["revision"],
        "read_sequence": read_sequence,
        "write_sequence": write_journal.write_sequence(study) + 1,  # the position of the `begin` entry that is appended next
        "question_id": wanted["question_id"],
        "option_id": wanted["option_id"],
        "words": wanted["words"],
    }
    contracts.validate(record)
    write.begin()
    position = layout.next_position(study, DECISIONS_DIR)
    artifacts.publish_record(study, f"{DECISIONS_DIR}/{position:06d}-{decision_id}.json", record, role="decision")
    write.wrote(study_write.DECISION, decision_id)
    return record, False
