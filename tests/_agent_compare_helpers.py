"""Shared by the agent Comparison tests (#72): answers written elsewhere, imported and assessed, and native Attempts built by hand."""

import json
import uuid
from pathlib import Path

from _chinook_helpers import FIXTURE_CASES, episodes_file, fixture_lines, import_agent, references_id, write_lines
from _study_helpers import run_json

from hypotrail.core import artifacts, canonical, contracts

SCORER = "chinook_contract_v1"
REPEATS = 3
TOOLS = "describe_schema,query_readonly"
LIMITS = {"model_turns": 6, "tool_calls": 8, "time_seconds": 60, "output_token_budget": 4000}


def trace_of(evidence_id="c1"):
    """The projected steps of an Episode that called one tool and cited it."""
    return [
        {"kind": "model_turn", "turn": 1, "stop_reason": "tool_calls"},
        {"kind": "tool_call", "native_tool_call_id": "n1", "function": "query_readonly", "arguments": {"sql": "SELECT 1"}},
        {"kind": "tool_result", "native_tool_call_id": "n1", "app_tool_call_id": evidence_id, "result": {"tool_call_id": evidence_id}, "tool_error": None},
        {"kind": "model_turn", "turn": 2, "stop_reason": "stop"},
        {"kind": "final_answer", "text": "done"},
    ]


def answer_lines(*, wrong=(), failed=(), skip=(), repeats=REPEATS, traced=True, model="model-a", tool_use=TOOLS, mode="llm_live"):
    """One line per Case and Repeat of the kit's four authored answers.

    `wrong` and `failed` are sets of (case_id, repeat); `skip` leaves a line out. An answered Case cites the one tool call
    of its trace. `model`, `tool_use` and `mode` are what the file claims (None leaves the claim out).
    """
    base = {line["case_id"]: line for line in fixture_lines()}
    lines = []
    for case_id in FIXTURE_CASES:
        for repeat in range(repeats):
            if (case_id, repeat) in skip:
                continue
            line = {"case_id": case_id, "repeat": repeat, "origin": "agent_output"}
            producer = {name: value for name, value in (("model", model), ("tool_use", tool_use)) if value is not None}
            if producer:
                line["producer"] = producer
            if mode is not None:
                line["mode"] = mode
            if (case_id, repeat) in failed:
                line["observation_status"] = "failed"
                lines.append(line)
                continue
            answer = json.loads(json.dumps(base[case_id]["final_answer"]))
            answered = answer["status"] == "answered"
            if answered and traced:
                answer["evidence"] = ["c1"]
            if (case_id, repeat) in wrong:
                if answered:
                    answer["rows"] = [[0]]
                else:
                    answer["reason_code"] = "criterion_undefined" if answer["reason_code"] == "field_not_available" else "field_not_available"
            line.update(observation_status="produced", final_answer=answer)
            if traced:
                line["trace"] = trace_of() if answered else [{"kind": "model_turn", "turn": 1, "stop_reason": "stop"}, {"kind": "final_answer", "text": "done"}]
            lines.append(line)
    return lines


def keys_of(repeats=REPEATS, cases=FIXTURE_CASES):
    return [(case, repeat) for case in cases for repeat in range(repeats)]


def assess(study, observation_set):
    code, payload, err = run_json("assess", "--study", study, "--observations", observation_set, "--scorer", SCORER, "--references", references_id(study))
    assert code == 0, (payload, err)
    return payload["assessment"]


def observation_set_of(study, attempt):
    folder = Path(study) / "attempts" / attempt["attempt_id"]
    return json.loads((folder / "observation_set.json").read_text())["observation_set_id"]


def imported(tmp_path, study, name, lines, *, repeats=REPEATS):
    """(Attempt, Assessment) of an import of `lines` into `study`."""
    source = write_lines(Path(tmp_path) / f"{name}.jsonl", lines)
    population = episodes_file(tmp_path, keys_of(repeats), name=f"{name}-population.json")
    code, payload, err = import_agent(study, source, population, name)
    assert code == 0, (payload, err)
    return payload["attempt"], assess(study, observation_set_of(study, payload["attempt"]))


def native(study, attempt, *, mode="llm_live", configuration="plain", model="model-a", tools=("describe_schema", "query_readonly"), limits=None, repeats=REPEATS, environment=None, partition="dev", assessed=True):
    """(Attempt, Assessment) of a native Attempt built from `attempt`'s observations: no ticket of #9 runs the agent Track into a Study yet.

    The manifest records what a native Attempt of this Track would: its Mode, its Configuration, its model, its tools,
    its limits and its planned Repeats.
    """
    as_mode = mode
    if assessed and mode == "scripted_fixture":
        mode = "llm_live"  # `assess` refuses the Mode (#74); the side is recorded under its Mode after it is assessed (`reclassified`)
    source = Path(study) / "attempts" / attempt["attempt_id"]
    new_id = str(uuid.uuid4())
    folder = Path(study) / "attempts" / new_id
    folder.mkdir()
    for name in ("observations.jsonl", "population.json"):
        (folder / name).write_bytes((source / name).read_bytes())
    normalized = artifacts.ref_of_existing(study, f"attempts/{new_id}/observations.jsonl", media_type="application/jsonl", role="observations")
    population = artifacts.ref_of_existing(study, f"attempts/{new_id}/population.json", media_type="application/json", role="import_population")
    record = json.loads((source / "observation_set.json").read_text())
    record.update(
        observation_set_id=str(uuid.uuid4()),
        attempt_id=new_id,
        origin="generated",
        mode=mode,
        population_ref=population,
        raw_refs=[],
        normalized_ref=normalized,
        provenance={"produced_by": "hypotrail", "partition": partition},
        unknown_fields=[],
    )
    contracts.validate(record)
    (folder / "observation_set.json").write_bytes(canonical.dumps(record))
    set_ref = artifacts.ref_of_existing(study, f"attempts/{new_id}/observation_set.json", media_type="application/json", role="observation_set")
    manifest = json.loads((source / "attempt.json").read_text())
    config = {
        "command": "run agent",
        "workload": "chinook",
        "mode": mode,
        "partition": partition,
        "configuration": configuration,
        "model": model,
        "tools": list(tools) if tools is not None else None,
        "limits": limits if limits is not None else LIMITS,
        "repeats": repeats,
    }
    config = {key: value for key, value in config.items() if value is not None}
    manifest.update(
        attempt_id=new_id,
        request_id=f"native-{new_id}",
        operation="execute",
        mode=mode,
        effective_config=config,
        effective_config_digest=canonical.digest(config),
        output_refs=[normalized, set_ref],
    )
    if environment is not None:
        manifest["code_environment"] = {**manifest["code_environment"], **environment}
    contracts.validate(manifest)
    (folder / "attempt.json").write_bytes(canonical.dumps(manifest))
    if not assessed:
        return manifest, record["observation_set_id"]
    assessment = assess(study, record["observation_set_id"])
    return reclassified(study, manifest, record, as_mode), assessment


def reclassified(study, manifest, record, mode):
    """The same Attempt recorded under another Mode, after it was assessed.

    `assess` refuses an Observation set of the `scripted_fixture` Mode (#74, D-012 on chadlis/hypotrail#75 item 15), so a native side of that
    Mode, which `compare` must still refuse next to a `llm_live` one, is an assessed side whose records say so afterwards.
    """
    if mode == manifest["mode"]:
        return manifest
    folder = Path(study) / "attempts" / manifest["attempt_id"]
    record = {**record, "mode": mode}
    (folder / "observation_set.json").write_bytes(canonical.dumps(record))
    set_ref = artifacts.ref_of_existing(study, f"attempts/{manifest['attempt_id']}/observation_set.json", media_type="application/json", role="observation_set")
    config = {**manifest["effective_config"], "mode": mode}
    manifest = {
        **manifest,
        "mode": mode,
        "effective_config": config,
        "effective_config_digest": canonical.digest(config),
        "output_refs": [r for r in manifest["output_refs"] if r["role"] != "observation_set"] + [set_ref],
    }
    contracts.validate(manifest)
    (folder / "attempt.json").write_bytes(canonical.dumps(manifest))
    return manifest


def compare(study, control, candidate, *more):
    return run_json("compare", "--study", study, "--control", control["assessment_id"], "--candidate", candidate["assessment_id"], *more)


def comparison_files(study):
    folder = Path(study) / "comparisons"
    return sorted(p.relative_to(study).as_posix() for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else []
