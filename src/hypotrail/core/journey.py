"""Derive the journey's steps from Study status and the Track's declarations."""

from collections.abc import Mapping, Sequence
from typing import TypedDict


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
