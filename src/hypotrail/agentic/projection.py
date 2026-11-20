"""Projecting an Inspect eval log into one record per Episode (Case x Repeat).

The log is read through Inspect's public log API only. An Episode is `produced`
when it ran to an answer, `failed` when its execution stopped with an error, at one of our
limits (turns, time, tokens) before any final answer, or with its answer cut by the output cap, and `missing` when the log holds nothing for it. Inspect's
`epoch` is 1-based; a Repeat is 0-based, as in the kit's fixture.
"""

import json
from collections.abc import Iterable

from inspect_ai.log import read_eval_log


def _stop_reasons(sample) -> list[str | None]:
    """Why each model call stopped, in call order, as Inspect normalises it.

    One entry per completed model event: `stop` (a complete answer), `tool_calls`,
    `max_tokens` (cut by the output cap), `model_length`, `content_filter` or `unknown`.
    """
    reasons = []
    for event in sample.events or []:
        if event.event == "model" and event.output is not None and event.output.choices:
            reasons.append(event.output.choices[0].stop_reason)
    return reasons


def _steps(messages, stop_reasons=()) -> list[dict]:
    steps = []
    turn = 0
    conversation = [m for m in messages if m.role in ("assistant", "tool")]
    for message in conversation:
        if message.role == "assistant":
            turn += 1
            steps.append(
                {
                    "kind": "model_turn",
                    "turn": turn,
                    "stop_reason": stop_reasons[turn - 1] if turn <= len(stop_reasons) else None,
                }
            )
            if message.tool_calls:
                for call in message.tool_calls:
                    steps.append(
                        {
                            "kind": "tool_call",
                            "native_tool_call_id": call.id,
                            "function": call.function,
                            "arguments": call.arguments,
                        }
                    )
            else:
                steps.append({"kind": "final_answer", "text": message.text})
        else:
            try:
                result = json.loads(message.text)
            except json.JSONDecodeError:
                result = None
            steps.append(
                {
                    "kind": "tool_result",
                    "native_tool_call_id": message.tool_call_id,
                    "app_tool_call_id": result.get("tool_call_id") if isinstance(result, dict) else None,
                    "result": result,
                    "tool_error": None if message.error is None else {"type": message.error.type},
                }
            )
    return steps


def _final_stop_reason(steps: list[dict]) -> str | None:
    """Why the model call that gave the final answer stopped (None without a final answer)."""
    for before, step in zip(steps, steps[1:]):
        if step["kind"] == "final_answer":
            return before["stop_reason"]
    return None


def _scoring_events(sample):
    """Span events of the scoring phase: structured fields only, never error text."""
    spans = [e for e in (sample.events or []) if e.event == "span_begin"]
    started = any(e.type == "scorers" for e in spans)
    names = [e.name for e in spans if e.type == "scorer"]
    return started, names


def _episode(sample, model: str) -> dict:
    inputs = []
    for message in sample.messages:
        if message.role in ("system", "user"):
            inputs.append({"role": message.role, "content": message.text})
        else:
            break
    steps = _steps(sample.messages, _stop_reasons(sample))
    final = next((s["text"] for s in steps if s["kind"] == "final_answer"), None)

    status, reason, criteria = "produced", None, []
    if sample.error is not None:
        # Inspect marks both kinds of breakage as an errored sample. What tells
        # them apart is whether the scoring phase had begun when it happened.
        scoring_started, scorer_names = _scoring_events(sample)
        if scoring_started:
            criteria = [
                {"name": name, "state": "errored", "reason": "scoring_failed"}
                for name in scorer_names
                if name not in (sample.scores or {})
            ]
        else:
            status, reason, final = "failed", "execution_failed", None
    elif final is not None and _final_stop_reason(steps) == "max_tokens":
        # A final answer is in the state and was cut by the output cap (our setting): `failed`, Reason
        # `output_cap`, whatever limit Inspect recorded (D1); the cut text stays in the steps.
        status, reason, final = "failed", "output_cap", None
    elif sample.limit is not None and final is None:
        # No final answer, and Inspect recorded a limit: the Episode is `failed` (GLOSSARY, Observation set),
        # never `produced` with no answer. The Reason names the limit.
        status, reason = "failed", f"{sample.limit.type}_limit"
    return {
        "case_id": str(sample.id),
        "repeat": sample.epoch - 1,
        "status": status,
        "reason": reason,
        "criteria": criteria,
        "model": model,
        "provider": model.split("/", 1)[0],
        "input": inputs,
        "steps": steps,
        "final_answer": final,
        "stopped_by_limit": None
        if sample.limit is None
        else {"type": sample.limit.type, "limit": sample.limit.limit},
        "turn_count": sample.turn_count,
    }


def project_log(location: str, *, expected: Iterable[tuple[str, int]]) -> list[dict]:
    """One record per expected (case_id, repeat), in the order given."""
    return project_episodes(read_eval_log(location), expected=expected)


def project_episodes(log, *, expected: Iterable[tuple[str, int]]) -> list[dict]:
    """The same projection of a log already read through the public API (`import agent` reads it once)."""
    model = log.eval.model
    by_key = {(str(s.id), s.epoch - 1): s for s in (log.samples or [])}
    records = []
    for case_id, repeat in expected:
        sample = by_key.get((case_id, repeat))
        if sample is None:
            records.append(
                {
                    "case_id": case_id,
                    "repeat": repeat,
                    "status": "missing",
                    "reason": "missing_from_log",
                    "criteria": [],
                    "model": model,
                    "provider": model.split("/", 1)[0],
                    "input": [],
                    "steps": [],
                    "final_answer": None,
                    "stopped_by_limit": None,
                    "turn_count": None,
                }
            )
        else:
            records.append(_episode(sample, model))
    return records
