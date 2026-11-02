"""Projecting an Inspect eval log into one record per Episode (Case x Repeat).

The log is read through Inspect's public log API only. An Episode is `produced`
when it ran to an answer or to a limit, `failed` when its execution stopped
with an error, and `missing` when the log holds nothing for it. Inspect's
`epoch` is 1-based; a Repeat is 0-based, as in the kit's fixture.
"""

import json
from collections.abc import Iterable

from inspect_ai.log import read_eval_log


def _message_text(message) -> str:
    return message.text


def _steps(messages) -> list[dict]:
    steps = []
    turn = 0
    conversation = [m for m in messages if m.role in ("assistant", "tool")]
    for index, message in enumerate(conversation):
        if message.role == "assistant":
            turn += 1
            steps.append({"kind": "model_turn", "turn": turn})
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


def _episode(sample, model: str) -> dict:
    inputs = []
    for message in sample.messages:
        if message.role in ("system", "user"):
            inputs.append({"role": message.role, "content": message.text})
        else:
            break
    steps = _steps(sample.messages)
    final = next((s["text"] for s in steps if s["kind"] == "final_answer"), None)
    failed = sample.error is not None
    return {
        "case_id": str(sample.id),
        "repeat": sample.epoch - 1,
        "status": "failed" if failed else "produced",
        "model": model,
        "provider": model.split("/", 1)[0],
        "input": inputs,
        "steps": steps,
        "final_answer": None if failed else final,
        "limit": None if sample.limit is None else {"type": sample.limit.type, "limit": sample.limit.limit},
        "turn_count": sample.turn_count,
        "error": None if not failed else {"present": True},
    }


def project_log(location: str, *, expected: Iterable[tuple[str, int]]) -> list[dict]:
    """One record per expected (case_id, repeat), in the order given."""
    log = read_eval_log(location)
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
                    "model": model,
                    "provider": model.split("/", 1)[0],
                    "input": [],
                    "steps": [],
                    "final_answer": None,
                    "limit": None,
                    "turn_count": None,
                    "error": None,
                }
            )
        else:
            records.append(_episode(sample, model))
    return records
