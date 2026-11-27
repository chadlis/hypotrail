"""Shared by the tests of the `lesson` read: run the demonstration's step list to a given step, and resolve a card's key path on a read."""

import copy
import json

import pytest

from _demonstration_helpers import demonstration, run_in_process
from _study_helpers import run_cli

from conftest import NetworkGuard, block_network

LESSON = "lesson"


def lesson(study, *more):
    """(exit code, the object printed, stderr) of `lesson --study=DIR --json`."""
    code, out, err = run_cli(LESSON, f"--study={study}", *more, "--json")
    return code, json.loads(out), err


def resolved(payload, path: str) -> list:
    """The values a key path names in a read, `.` between keys and `[]` for every entry of a list. A key that is missing from the read, or
    from any entry of a list, and a list with no entry name no value: the path gives []."""
    values = [payload]
    for part in path.split("."):
        name, lists = part.rstrip("[]"), part.count("[]")
        if not all(isinstance(value, dict) and name in value for value in values):
            return []
        values = [value[name] for value in values]
        for _ in range(lists):
            if not all(isinstance(value, list) for value in values):
                return []
            values = [entry for value in values for entry in value]
    return values


def demonstration_until(work, last_step: str, *, after=None, first_step=None):
    """The demonstration's step list carried out in `work` from `first_step` (the first step when None) up to `last_step`, both included,
    under the network guard. `after` maps a step id to the actions added at its end, so that a read is made at that state of the Study."""
    module = demonstration()
    ids = [step["id"] for step in module.STEPS]
    start = 0 if first_step is None else ids.index(first_step)
    steps = copy.deepcopy(module.STEPS[start : ids.index(last_step) + 1])
    for step in steps:
        step["actions"].extend((after or {}).get(step["id"], []))
    guard = NetworkGuard()
    with pytest.MonkeyPatch.context() as patch:
        block_network(patch, guard)
        recording = run_in_process(work, steps=steps)
    assert guard.attempts == [], guard.attempts
    assert recording.outcome.code == 0, recording.transcript[-2000:]
    return recording
