"""`compare` for two Assessments of the tool-using agent Track: Episodes aligned by Case and Repeat.

A core module (ADR 0001): it reads Assessments, their per-Item files, the Observation sets and Attempt
manifests they point to, and imports neither a Track, scikit-learn, NumPy nor Inspect. `hypotrail.core.comparison`
loads it for an Assessment of an `agentic` Observation set and keeps the parts both Tracks share.

The checks run in a fixed order over what the two Assessments record; nothing is written before every one has
passed (SPEC CMP-01, CMP-02, T12). `AGENT_CHECKS` lists them:

1. `population`: the same Partition and the same Cases (not the same Episodes: a difference in Repeats has its own check);
2. the Partition is `dev` or `public_check` (`COMPARISON_PARTITION_NOT_DEV` otherwise); a `public_check` Comparison is an
   Exposure, recorded in the journal once every check has passed (`hypotrail.core.exposure`);
3. `references`, `scorer`, `unit`: as for the bike (`comparison.check_assessments`);
4. `repeats`: the same planned Repeats for each Case;
5. `tools`, `model`, `budgets`: the same tools, model and budgets, each where both sides establish it. A native
   Attempt's manifest records them; an Import's header or lines declare them or leave them `unknown`;
6. `mode`: a `scripted_fixture` side against an `llm_live` side is refused, an Import counting as the Mode it
   declares. A side whose Mode is not declared is not refused.

A difference in `repeats`, `tools`, `model` or `budgets` is refused with its own code (exit 3) unless the request
declares it as the intentional factor (`--factor`); the Configuration is the intentional factor by default, and the
record keeps `declared_factor`. A factor a side does not establish is recorded as not checked (`not_established`)
and the Comparison is descriptive, never strict, as it is when a side is an Import.

Episodes are aligned by (case_id, repeat). An Episode on one side only, or not scored for the primary Criterion on
a side, is shown in the coverage and never dropped. The matrix of each side keeps every Criterion state of every
Episode. With full coverage (every Episode scored on both sides), each Criterion is aggregated per Case first
(its share of Repeats scored true) and every Case weighs the same; the main delta is that of the primary Criterion
(owner decision 1A on chadlis/hypotrail#9), the others are secondary. Without full coverage the value is null with a
Reason, and the rates of coverage and the two named rates of each side (CMP-04) stand beside it. No interval is
computed over Episodes. Latency and the numbers of calls are descriptive; tokens and cost are null unless observable.
"""

import csv
import io
import re
import uuid
from pathlib import Path

from hypotrail.core import artifacts, canonical, contracts, exposure, study_write
from hypotrail.core import study as layout
from hypotrail.core.comparison import (
    EXTERNAL_MODE,
    REASON_PROVENANCE,
    REFUSALS,
    STAGE,
    _refuse,
    check_assessments,
    check_partition,
    describe_environments,
    import_scope_warning,
    record_exposure,
)
from hypotrail.core.factors import DEFAULT_FACTOR, FACTORS  # noqa: F401

AGENT_CHECKS = ("population", "references", "scorer", "unit", "repeats", "tools", "model", "budgets", "mode")
REASON_DECLARED = "declared_factor"
REASON_NOT_ESTABLISHED = "not_established"
REASON_COVERAGE = "coverage_incomplete"
WARNING_NOT_ESTABLISHED = "COMPARISON_FACTOR_NOT_ESTABLISHED"
PRODUCTION_MODES = ("scripted_fixture", "llm_live")
UNIT = "share of Repeats per Case, every Case weighted equally"
DELTA_DEFINITION = (
    "Share(Candidate) - Share(Control), where Share is the mean over Cases of each Case's share of Repeats scored true; "
    "every Case has the same weight; positive means the Candidate is better (the Criterion is higher-is-better)"
)
PAIRED_COLUMNS = ["case_id", "repeats", "control_share", "candidate_share", "delta_share"]
LIMITATIONS = [
    "The Repeats of a Case are not independent samples: the Comparison carries no binomial interval over Episodes, no confidence interval and no significance claim; every Case weighs the same.",
    "Latency and the numbers of model and tool calls are descriptive only, and no Criterion rests on them; tokens and cost are null where they are not observable, never 0, and no cost is compared.",
    "The shares describe the Cases of this Workload, not agents in general.",
]


def _population(study: Path, side: dict) -> dict:
    document = canonical.loads(artifacts.read_verified(study, side["observation_set"]["population_ref"]))
    episodes = sorted((e["case_id"], e["repeat"]) for e in document["episodes"])
    repeats = {}
    for case_id, _ in episodes:
        repeats[case_id] = repeats.get(case_id, 0) + 1
    return {"episodes": episodes, "cases": sorted(repeats), "repeats": dict(sorted(repeats.items()))}


def _is_import(side: dict) -> bool:
    return side["observation_set"]["mode"] == EXTERNAL_MODE


def _declared(entry):
    """The value an Import declares in `{value, origin}`, or None when it is `unknown`."""
    if isinstance(entry, dict) and entry.get("origin") == "declared" and entry.get("value") not in (None, ""):
        return entry["value"]
    return None


def _tools(value):
    """A native list or an Import's string, as the sorted names it holds."""
    if isinstance(value, str):
        value = [name for name in re.split(r"[,\s]+", value) if name]
    return sorted(value)


def _established(side: dict, factor: str):
    """What the side's Attempt establishes for `factor` (`tools`, `model` or `budgets`), or None."""
    config = side["manifest"]["effective_config"]
    if _is_import(side):
        entry = {"model": (config.get("producer") or {}).get("model"), "tools": (config.get("producer") or {}).get("tool_use"), "budgets": (config.get("log") or {}).get("limits")}[factor]
        value = _declared(entry)
    else:
        value = {"model": config.get("model"), "tools": config.get("tools"), "budgets": config.get("limits")}[factor]
    if value in (None, "", "unknown"):
        return None
    return _tools(value) if factor == "tools" else value


def _declared_mode(side: dict):
    """The Mode of production of the side: its own, or for an Import the one its file or log declares (None when it declares none)."""
    mode = side["observation_set"]["mode"]
    if mode != EXTERNAL_MODE:
        return mode
    value = _declared(((side["manifest"]["effective_config"].get("producer") or {}).get("file_mode")))
    return value if value in PRODUCTION_MODES else None


def _check_repeats(control, candidate, populations, checks, declared):
    c, d = populations["control"]["repeats"], populations["candidate"]["repeats"]
    if c == d:
        checks.append({"check": "repeats", "passed": True, "reason": None})
    elif declared == "repeats":
        checks.append({"check": "repeats", "passed": True, "reason": REASON_DECLARED})
    else:
        raise _refuse(
            "repeats",
            [*checks, {"check": "repeats", "passed": False, "reason": REFUSALS["repeats"][1]}],
            {"repeats": c},
            {"repeats": d},
            "the two Assessments do not plan the same Repeats for each Case",
        )


def _check_factor(name, control, candidate, checks, declared):
    c, d = _established(control, name), _established(candidate, name)
    if c is None or d is None:
        checks.append({"check": name, "passed": False, "reason": REASON_NOT_ESTABLISHED})
    elif canonical.dumps(c) == canonical.dumps(d):
        checks.append({"check": name, "passed": True, "reason": None})
    elif declared == name:
        checks.append({"check": name, "passed": True, "reason": REASON_DECLARED})
    else:
        raise _refuse(
            name,
            [*checks, {"check": name, "passed": False, "reason": REFUSALS[name][1]}],
            {name: c},
            {name: d},
            f"the two Attempts do not share their {name}, and the request declares {declared!r} as the intentional factor",
        )


def _check_mode(control, candidate, checks):
    modes = (_declared_mode(control), _declared_mode(candidate))
    if None not in modes and modes[0] != modes[1]:
        raise _refuse(
            "mode",
            [*checks, {"check": "mode", "passed": False, "reason": REFUSALS["mode"][1]}],
            {"mode": modes[0]},
            {"mode": modes[1]},
            "the two sides were not produced in the same Mode: no ranking between a scripted_fixture and an llm_live side",
        )
    imports = [side["role"] for side in (control, candidate) if _is_import(side)]
    if imports:
        checks.append({"check": "mode", "passed": False, "reason": REASON_PROVENANCE})  # descriptive, never strict: not a refusal
    else:
        checks.append({"check": "mode", "passed": True, "reason": None})
    return imports


def _episodes(side: dict) -> dict:
    """{(case_id, repeat): {execution_status, criteria: {name: {state, score, reason}}}} from the side's per-Item file."""
    episodes = {}
    for row in side["per_item"]:
        entry = episodes.setdefault((row["case_id"], int(row["repeat"])), {"execution_status": row["execution_status"], "criteria": {}})
        entry["criteria"][row["criterion"]] = {
            "state": row["state"],
            "score": None if row["score"] == "" else row["score"] == "true",
            "reason": row["reason"] or None,
        }
    return episodes


def _scored(episode, criterion) -> bool:
    return episode is not None and episode["criteria"][criterion]["state"] == "scored"


def _delta(criterion: str, control: dict, candidate: dict, keys: list) -> tuple:
    """(the delta record of `criterion`, {case_id: (repeats, control share, candidate share)} or None when not computable)."""
    base = {"metric": criterion, "unit": UNIT, "definition": DELTA_DEFINITION}
    if not all(_scored(control.get(key), criterion) and _scored(candidate.get(key), criterion) for key in keys):
        return {**base, "value": None, "reason": REASON_COVERAGE, "control": None, "candidate": None}, None
    by_case = {}
    for case_id, repeat in keys:
        by_case.setdefault(case_id, []).append((control[(case_id, repeat)]["criteria"][criterion]["score"], candidate[(case_id, repeat)]["criteria"][criterion]["score"]))
    cases = {
        case_id: (len(pairs), sum(c for c, _ in pairs) / len(pairs), sum(d for _, d in pairs) / len(pairs)) for case_id, pairs in sorted(by_case.items())
    }
    control_value = sum(c for _, c, _ in cases.values()) / len(cases)
    candidate_value = sum(d for _, _, d in cases.values()) / len(cases)
    return {**base, "value": candidate_value - control_value, "reason": None, "control": control_value, "candidate": candidate_value}, cases


def _matrix(side: dict, assessment: dict) -> dict:
    cases = {}
    for (case_id, repeat), episode in sorted(_episodes(side).items()):
        cases.setdefault(case_id, []).append({"repeat": repeat, **episode})
    return {"assessment_id": assessment["assessment_id"], "cases": [{"case_id": case_id, "episodes": episodes} for case_id, episodes in cases.items()]}


def _measures(study: Path, side: dict) -> dict:
    """The descriptive measures of a side, each None unless it is known for every Episode that ran (never a partial sum, never 0).

    Counts need a trace; latency and tokens need the `usage` an Inspect log import keeps (a JSONL import has none); no
    Observation set holds a cost.
    """
    entries = [canonical.loads(line) for line in artifacts.read_verified(study, side["observation_set"]["normalized_ref"]).decode("utf-8").splitlines() if line.strip()]
    ran = [entry for entry in entries if entry["status"] != "missing"]
    observable = bool(ran) and all(isinstance(entry.get("trace"), list) for entry in ran)

    def count(kind):
        return sum(step.get("kind") == kind for entry in ran for step in entry["trace"]) if observable else None

    def usage(name):
        values = [(entry.get("usage") or {}).get(name) for entry in ran]
        return sum(values) if ran and all(isinstance(v, (int, float)) for v in values) else None

    return {"latency_seconds": usage("latency_seconds"), "model_calls": count("model_turn"), "tool_calls": count("tool_call"), "tokens": usage("tokens"), "cost": None}


def _rate(scored: int, expected: int):
    return scored / expected if expected else None


def compare_sides(study: Path, write, control: dict, candidate: dict, factor: str | None, live_basis=None) -> dict:
    """Write and return the Comparison of two agent sides (`hypotrail.core.comparison` has read them).

    A Comparison of `public_check` Episodes is an Exposure: its journal entry is appended once the checks have passed
    and before the Episodes are paired (`hypotrail.core.comparison.record_exposure`).
    """
    declared = factor or DEFAULT_FACTOR
    checks = []
    populations = {"control": _population(study, control), "candidate": _population(study, candidate)}

    if control["partition"] != candidate["partition"] or populations["control"]["cases"] != populations["candidate"]["cases"]:
        raise _refuse(
            "population",
            [{"check": "population", "passed": False, "reason": REFUSALS["population"][1]}],
            {"partition": control["partition"], "cases": populations["control"]["cases"]},
            {"partition": candidate["partition"], "cases": populations["candidate"]["cases"]},
            f"the Control is on {control['partition']!r} and the Candidate on {candidate['partition']!r}, or the two cover other Cases: not the same population",
        )
    checks.append({"check": "population", "passed": True, "reason": None})
    exposed = check_partition(control["partition"])

    check_assessments(control, candidate, checks)
    _check_repeats(control, candidate, populations, checks, declared)
    for name in ("tools", "model", "budgets"):
        _check_factor(name, control, candidate, checks, declared)
    imports = _check_mode(control, candidate, checks)
    assert [c["check"] for c in checks] == list(AGENT_CHECKS)

    comparison_id = str(uuid.uuid4())
    if exposed:  # before any Episode is paired
        record_exposure(study, control, candidate, comparison_id, live_basis)
    ca, da = control["assessment"], candidate["assessment"]
    primary = ca["primary_criterion"]
    side_episodes = {"control": _episodes(control), "candidate": _episodes(candidate)}
    keys = sorted(set(side_episodes["control"]) | set(side_episodes["candidate"]))
    only_control = sorted(set(side_episodes["control"]) - set(side_episodes["candidate"]))
    only_candidate = sorted(set(side_episodes["candidate"]) - set(side_episodes["control"]))
    control_scored = sum(_scored(side_episodes["control"].get(key), primary) for key in keys)
    candidate_scored = sum(_scored(side_episodes["candidate"].get(key), primary) for key in keys)
    paired = sum(_scored(side_episodes["control"].get(key), primary) and _scored(side_episodes["candidate"].get(key), primary) for key in keys)
    coverage = {
        "unit": "Episodes",
        "criterion": primary,
        "expected": len(keys),
        "control_scored": control_scored,
        "candidate_scored": candidate_scored,
        "paired": paired,
        "control_rate": _rate(control_scored, len(keys)),
        "candidate_rate": _rate(candidate_scored, len(keys)),
        "only_control": len(only_control),
        "only_candidate": len(only_candidate),
        "complete": bool(keys) and paired == len(keys),
    }

    delta, cases = _delta(primary, side_episodes["control"], side_episodes["candidate"], keys)
    secondary = [_delta(name, side_episodes["control"], side_episodes["candidate"], keys)[0] for name in dict.fromkeys(row["criterion"] for row in control["per_item"]) if name != primary]

    environment, environment_sentence = describe_environments(control["manifest"], candidate["manifest"])
    limitations = [*LIMITATIONS, environment_sentence]
    warnings = []
    if imports:
        warnings.append(import_scope_warning(imports))
    else:
        missing = [f"{c['check']}" for c in checks if c["reason"] == REASON_NOT_ESTABLISHED]
        if missing:
            warnings.append(
                {
                    "code": WARNING_NOT_ESTABLISHED,
                    "message": f"A side does not record its {', '.join(missing)}, so the Comparison could not check that both sides share them: it is descriptive, not strict.",
                }
            )
    limitations.extend(w["message"] for w in warnings)
    descriptive = bool(imports) or any(not c["passed"] for c in checks)

    folder = f"{layout.COMPARISONS_DIR}/{comparison_id}"
    population = {"partition": control["partition"], "count": len(keys), "cases": populations["control"]["cases"], "episodes": [list(key) for key in keys]}
    write.begin()  # a Comparison of dev Episodes writes nothing before this; an Exposure began the command already
    population_ref = artifacts.publish_record(study, f"{folder}/population.json", population, role="comparison_population")
    write.wrote(study_write.COMPARISON, comparison_id)
    matrix = {"criteria": list(dict.fromkeys(row["criterion"] for row in control["per_item"])), "control": _matrix(control, ca), "candidate": _matrix(candidate, da)}
    matrix_ref = artifacts.publish_record(study, f"{folder}/matrix.json", matrix, role="comparison_matrix")
    paired_ref = None
    if cases is not None:
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(PAIRED_COLUMNS)
        for case_id, (repeats, c_share, d_share) in cases.items():
            writer.writerow([case_id, repeats, repr(c_share), repr(d_share), repr(d_share - c_share)])
        paired_ref = artifacts.publish_bytes(study, f"{folder}/paired_deltas.csv", out.getvalue().encode("utf-8"), media_type="text/csv", role="paired_deltas")

    record = {
        "kind": "comparison",
        "schema_version": "comparison/1",
        "comparison_id": comparison_id,
        "left_assessment_id": ca["assessment_id"],
        "right_assessment_id": da["assessment_id"],
        "roles": {"control_assessment_id": ca["assessment_id"], "candidate_assessment_id": da["assessment_id"]},
        "comparability": {"status": "descriptive_only" if descriptive else "compatible", "checks": checks},
        "population_ref": population_ref,
        "paired_deltas_ref": paired_ref,
        "matrix_ref": matrix_ref,
        "coverage": coverage,
        "primary_criterion": primary,
        "delta": delta,
        "secondary_deltas": secondary,
        "rates": {
            side["role"]: {"metrics": side["assessment"]["metrics"], "unknowns": side["assessment"]["unknowns"], "operational_errors": side["assessment"]["operational_errors"]}
            for side in (control, candidate)
        },
        **exposure.marks(study, [control["manifest"], candidate["manifest"]], [ca, da]),
        "declared_factor": declared,
        "descriptive": {"control": _measures(study, control), "candidate": _measures(study, candidate)},
        "code_environment": environment,
        "warnings": warnings,
        "limitations": limitations,
    }
    contracts.validate(record)
    artifacts.publish_record(study, f"{folder}/comparison.json", record, role="comparison")
    return record
