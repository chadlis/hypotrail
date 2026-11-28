"""Derive the journey's steps and pause from Study status and the Track's declarations."""

import re
from collections.abc import Collection, Mapping, Sequence
from typing import Literal, NotRequired, TypedDict

from hypotrail.core.cite import NamedValue, Resolver, Segment, fill


class Step(TypedDict):
    step: str
    name: str
    short: str
    title: str
    moment: str
    decision: bool
    depends_on: list[str]


class Moment(TypedDict):
    id: str
    title: str


class Completion(TypedDict):
    complete: bool
    results: list[str]


class Choice(TypedDict):
    id: str
    label: str
    value: NotRequired[object]
    recommended: NotRequired[bool]


class PauseContext(TypedDict, total=False):
    availability: Literal["ready", "running", "blocked"]
    question: str | list[Segment] | None
    restatement: str | list[Segment]
    choice_options: list[Choice]
    cited_ids: list[str]
    value_unchanged: bool
    reconfirm_question: str
    review: bool


class Command(TypedDict):
    command: str
    arguments: list[str]


class ThenTemplate(TypedDict):
    text: str
    commands: list[Command]


class PauseTemplates(TypedDict, total=False):
    digest: list[str]
    recommended: dict[str, str]
    value: dict[str, str]
    proposal: str
    explain: list[str]
    change_note: str
    then: ThenTemplate
    panel_line: str
    limitations: list[dict[str, str]]


# English words from guidance.py at the pinned old tool's revision.
_OPTION_LABELS = {
    "adopt": "I adopt this decision",
    "change": "Change something",
    "explain": "Explain first",
    "continue": "Let's continue",
}
_ADOPTION_QUESTION = "Do you adopt this decision?"
_MAX_DIGEST_WORDS = 200


def _step_decisions(history: Sequence[dict]) -> tuple[dict, dict]:
    """Index the latest recorded and the latest applicable Decision separately."""
    journey_decisions = [
        row for row in history if (row.get("question_id") or "").startswith("journey:")
    ]
    recorded = {}
    applicable = {}
    for row in sorted(journey_decisions, key=lambda decision: decision["write_sequence"]):
        step = row["question_id"].removeprefix("journey:")
        recorded[step] = row
        if row["applies"]:
            applicable[step] = row
    return recorded, applicable


def _reopened(decision: dict | None, dependencies: Sequence[str], recorded: dict) -> bool:
    if decision is None:
        return False
    if not decision["applies"]:
        return True
    return any(
        recorded[step]["write_sequence"] > decision["write_sequence"]
        for step in dependencies if step in recorded
    )


def _recap(rows: list[dict], moments: list[dict], current: dict | None) -> str:
    # English wording from the pinned old tool's junior.plan_recap.
    names = {row["step"]: row["name"] for row in rows}
    parts = []
    for moment in moments:
        if moment["steps"]:
            members = ", ".join(names[step] for step in moment["steps"])
            parts.append(f'{moment["title"]} ({members})' if moment["title"] else members)
    text = "The plan, in order: " + "; ".join(parts) + "."
    if current is None:
        return f"{text} Every step of the plan is done."
    return f'{text} Current step: {names[current["step"]]} ({current["n"]} of {len(rows)}).'


def steps(
    status: Mapping,
    order: Sequence[Step],
    moments: Sequence[Moment],
    completion: Mapping[str, Completion],
) -> dict:
    """Return the steps for a Study read.

    The Track supplies completion of any work besides the step's Decision, with the
    current result IDs, for every step. The core derives each Decision and the
    position without changing any input.
    """
    recorded, applicable = _step_decisions(status["decisions"])
    rows = []
    current = None
    moment_steps: dict[str, list[str]] = {moment["id"]: [] for moment in moments}
    for n, step in enumerate(order, 1):
        step_id = step["step"]
        fact = completion[step_id]
        decision = applicable.get(step_id) if step["decision"] else None
        reopened = step["decision"] and _reopened(recorded.get(step_id), step["depends_on"], recorded)
        done = fact["complete"] and (not step["decision"] or decision is not None) and not reopened
        if done:
            state = "done"
        elif current is None:
            state = "current"
            current = {"step": step_id, "n": n}
        else:
            state = "upcoming"
        rows.append({
            "step": step_id, "n": n, "name": step["name"], "short": step["short"],
            "title": step["title"], "moment": step["moment"], "state": state,
            "value_words": decision["option"] if decision is not None else None,
            "decision": (
                {key: decision[key] for key in ("decision_id", "option_id", "level")}
                if decision is not None else None
            ),
            "results": list(fact["results"]),
            "reopened": reopened,
        })
        moment_steps[step["moment"]].append(step_id)
    grouped = [{**moment, "steps": moment_steps[moment["id"]]} for moment in moments]
    return {"total": len(rows), "current": current, "recap": _recap(rows, grouped, current), "moments": grouped, "list": rows}


def _options(ids: Sequence[str], recommended: str | None) -> list[dict]:
    return [
        {"id": option, "label": _OPTION_LABELS[option], "recommended": option == recommended}
        for option in ids
    ]


def pause(step_view: Mapping, revision: str, context: PauseContext) -> dict:
    """Return the pause frame for the current step of a journey's step view.

    The Track supplies the current text and choices. For a reopened step it can
    supply the reconfirmation question with the result of comparing the offered
    value with the previous value, including any restated words.
    """
    current = step_view["current"]
    step_id = current["step"] if current else None
    position = {
        "step_id": step_id,
        "n": current["n"] if current else None,
        "total": step_view["total"],
        "completed": sum(step["state"] == "done" for step in step_view["list"]),
    }
    question = None
    options = []
    choices = []
    availability = context.get("availability", "ready")
    if current is None:
        kind = "complete"
    elif availability in ("running", "blocked"):
        kind = availability
    elif "restatement" in context:
        kind = "decision"
        reopened = step_view["list"][current["n"] - 1]["reopened"]
        closed = _ADOPTION_QUESTION
        if reopened and context.get("value_unchanged"):
            closed = context["reconfirm_question"]
        restatement = context["restatement"]
        suffix = f"\n\n{closed}"
        if isinstance(restatement, str):
            question = restatement + suffix
        else:
            question = [*restatement, {"text": suffix}]
        options = _options(("adopt", "change", "explain"), None if context.get("review") else "adopt")
        options[0]["description"] = restatement
    elif context.get("choice_options"):
        kind = "choice"
        question = context.get("question")
        choices = [dict(choice) for choice in context["choice_options"]]
        options = [
            {"id": choice["id"], "label": choice["label"], "recommended": choice.get("recommended", False)}
            for choice in choices
        ]
    else:
        kind = "action"
        question = context.get("question")
        options = _options(("continue", "explain"), "continue")
    return {
        "schema_version": "journey-pause/1",
        "id": step_id,
        "kind": kind,
        "position": position,
        "question": question,
        "options": options,
        "choice_options": choices,
        "cited_ids": list(dict.fromkeys([revision, *context.get("cited_ids", [])])) if current else [],
        "delegable": False,
    }


def _visible(segments: Sequence[Segment]) -> str:
    return "".join(segment["text"] for segment in segments)


def _join_parts(parts: Sequence[list[Segment]], separator: str) -> list[Segment]:
    joined = []
    for part in parts:
        if part:
            if joined:
                joined.append({"text": separator})
            joined.extend(part)
    return joined


def _fit_digest(parts: list[list[Segment]]) -> list[Segment]:
    # The pinned old junior._fit drops trailing parts before clipping one oversized part.
    parts = [part for part in parts if part]
    counts = [len(_visible(part).split()) for part in parts]
    total = sum(counts)
    while len(parts) > 1 and total > _MAX_DIGEST_WORDS:
        parts.pop()
        total -= counts.pop()
    if total <= _MAX_DIGEST_WORDS:
        return _join_parts(parts, " ")

    part, = parts
    # Legacy clipping normalizes whitespace. Cut at a word boundary in the combined
    # text, then trim only plain segments so cited values retain their provenance.
    remaining = list(re.finditer(r"\S+", _visible(part)))[_MAX_DIGEST_WORDS - 1].end()
    clipped = []
    for segment in part:
        if remaining <= 0:
            break
        text = segment["text"]
        if "record_id" in segment:
            clipped.append(segment)
        else:
            plain = re.sub(r"\s+", " ", text[:remaining])
            if not clipped:
                plain = plain.lstrip()
            if plain:
                clipped.append({"text": plain})
        remaining -= len(text)
    return clipped


def enrich(
    frame: Mapping,
    templates: PauseTemplates,
    resolver: Resolver,
    *,
    slots: Collection[str] = (),
    facts: Mapping[str, str] | None = None,
    values: Mapping[str, NamedValue] | None = None,
) -> dict:
    """Fill the Track's pause templates using its resolver, without changing the frame."""

    def segments(template: str) -> list[Segment]:
        return fill(template, resolver, slots=slots, facts=facts, values=values)

    def optional_segments(template: str | None) -> list[Segment] | None:
        return segments(template) if template is not None else None

    recommended = templates.get("recommended")
    value = templates.get("value")
    then = templates.get("then")
    return {
        **frame,
        "digest": _fit_digest([segments(part) for part in templates.get("digest", [])]),
        "recommended": {"value_id": recommended["value_id"], "why": segments(recommended["why"])} if recommended else None,
        "value": {"id": value["id"], "words": segments(value["words"])} if value else None,
        "proposal": optional_segments(templates.get("proposal")),
        "explain": _join_parts([segments(part) for part in templates.get("explain", [])], "\n\n"),
        "change_note": optional_segments(templates.get("change_note")),
        "then": {
            "text": segments(then["text"]),
            "commands": [{"command": command["command"], "arguments": list(command["arguments"])} for command in then["commands"]],
        } if then else None,
        "panel_line": optional_segments(templates.get("panel_line")),
        "limitations": [
            {"code": item["code"], "text": segments(item["text"])} for item in templates.get("limitations", [])[:3]
        ],
    }
