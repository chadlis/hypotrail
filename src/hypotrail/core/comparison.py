"""`compare`: a Comparison of two Assessments of a Study, one the Control and one the Candidate.

The Comparison is a core concept (ADR 0001, GLOSSARY): it reads Assessments, their per-Item files and
the Observation sets and Attempt manifests they point to, all kept by the Study. This module imports
neither the Tracks, scikit-learn, NumPy nor Inspect.

The checks run in a fixed order over what the two Assessments record; nothing is written before every
one has passed (SPEC CMP-01, CMP-02, T12):

1. both Assessments exist in the Study, and everything read is read back against its digest (exit 2, 3);
2. `population`: the same Partition and the same expected Items (an Import's population file, or the Study's memberships);
3. the Partition is `dev` or `public_check` (`COMPARISON_PARTITION_NOT_DEV` otherwise);
4. `references`: the same References set (by digest);
5. `scorer`: the same Scorer id, version and configuration digest;
6. `unit`: the same unit of the Metric;
7. `items`: the same Items, aligned by `row_id`. Two Assessments whose Items differ by even one are
   refused with the counts on each side; no intersection is ever computed;
8. `mode`: the same Mode of production. A side that is an Import (`external_unknown`) does not refuse:
   the Comparison is then `descriptive_only` and carries a warning on its scope;
9. `coverage`: every Item is scored on both sides, so the paired differences hide no missing Item.

A Comparison of `public_check` Items is an Exposure (`hypotrail.core.exposure`): once the Items and the Mode
have been checked, and before the paired differences are computed, the Study's freeze record is written if the
revision has none and one journal entry names the Comparison and the Assessments and Attempts of both sides
(`PROTOCOL_CHANGED`, exit 3, when the Workload's Protocol is no longer the revision's). A Comparison refused
at `coverage` after that leaves its entry: the Exposure had happened. Its ID names no Comparison.

A side whose Assessment lists, in `single_feature_check`, lag features of its own Configuration that beat it gets one warning
(`COMPARISON_SINGLE_FEATURE_BEATS`) naming the side and those features with their Metrics, also in `limitations`. It is read
from the record, never computed here, and it leaves the status as the checks and Imports compute it. A side whose field is
empty or absent gets none.

A refused check raises its own code (exit 3) whose details carry the `check`, its Reason code, the
values of both sides and the checks evaluated so far, and writes no Comparison. `delta` is the Metric of
the Candidate minus the Metric of the Control: a positive value means the Candidate is worse (lower is
better). The command holds the Study's writer lock for its whole execution.
"""

import csv
import io
import uuid
from pathlib import Path

from hypotrail.core import artifacts, canonical, contracts, exposure, study_write
from hypotrail.core import study as layout
from hypotrail.core.errors import IntegrityError, InvalidInputError

STAGE = "compare"
DEV = "dev"
PUBLIC_CHECK = "public_check"
EXTERNAL_MODE = "external_unknown"
AGENTIC = "agentic"
PAIRED_COLUMNS = ["row_id", "control_abs_error", "candidate_abs_error", "delta_abs_error"]
DELTA_DEFINITION = "Metric(Candidate) - Metric(Control); positive means the Candidate is worse (the Metric is lower-is-better)"

# The comparability checks, in the order they run, with the code of the refusal and the Reason of the failure.
CHECKS = ("population", "references", "scorer", "unit", "items", "mode", "coverage")
REFUSALS = {
    "population": ("COMPARISON_POPULATION_DIFFERS", "population_differs"),
    "references": ("COMPARISON_REFERENCES_DIFFER", "references_differ"),
    "scorer": ("COMPARISON_SCORER_DIFFERS", "scorer_differs"),
    "unit": ("COMPARISON_UNIT_DIFFERS", "unit_differs"),
    "items": ("COMPARISON_ITEMS_DIFFER", "items_differ"),
    "mode": ("COMPARISON_MODE_DIFFERS", "mode_differs"),
    "coverage": ("COMPARISON_COVERAGE_INSUFFICIENT", "coverage_insufficient"),
}
# The extra checks of an agent Comparison (`hypotrail.core.agent_comparison`): the same content of each Case, and the same planned
# Repeats, tools, model and budgets.
REFUSALS.update(
    {
        "cases": ("COMPARISON_CASES_DIFFER", "cases_differ"),
        "repeats": ("COMPARISON_REPEATS_DIFFER", "repeats_differ"),
        "tools": ("COMPARISON_TOOLS_DIFFER", "tools_differ"),
        "model": ("COMPARISON_MODEL_DIFFERS", "model_differs"),
        "budgets": ("COMPARISON_BUDGETS_DIFFER", "budgets_differ"),
    }
)
REASON_PROVENANCE = "provenance_unverified"
WARNING_DESCRIPTIVE = "COMPARISON_DESCRIPTIVE_IMPORT"
WARNING_SINGLE_FEATURE = "COMPARISON_SINGLE_FEATURE_BEATS"
# The warnings of a regression Comparison that state a deviation rather than a descriptive scope: `compare` and the report name
# their codes beside the status, as for `agent_comparison.DEVIATIONS`, since a `compatible` Comparison can hold them.
DEVIATIONS = (WARNING_SINGLE_FEATURE,)
LIMITATION_DEPENDENCE = "Daily observations are dependent: the delta carries no confidence interval and no significance claim."


def _not_found(code, message, **details):
    return InvalidInputError(code, message, stage=STAGE, details=details)


def _rows(data: bytes) -> list:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"), newline="")))


def _population_digest(study: Path, observation_set: dict) -> str:
    """What identifies the population of a side: the Partition and the expected Items for the regression Track.

    An Import's population file and the Study's memberships name the same population when they expect the same
    Items, so the artifact's bytes are not compared (the agent Track compares its Cases, `agent_comparison`).
    """
    ref = observation_set["population_ref"]
    if observation_set["domain"] == AGENTIC:
        return ref["sha256"]
    partition = observation_set["provenance"].get("partition")
    return canonical.sha256_hex(canonical.dumps({"partition": partition, "row_ids": layout.expected_row_ids(study, ref, partition)}))


def _side(study: Path, role: str, assessment_id: str) -> dict:
    assessment = layout.find_assessment(study, assessment_id)
    if assessment is None:
        raise _not_found(
            "ASSESSMENT_NOT_FOUND", f"the Study keeps no Assessment {assessment_id!r}", role=role, assessment_id=str(assessment_id)
        )
    found = layout.find_observation_set(study, assessment["observation_set_id"])
    if found is None:
        raise _not_found(
            "OBSERVATION_SET_NOT_FOUND",
            f"the Study keeps no Observation set {assessment['observation_set_id']!r}",
            role=role,
            observation_set_id=assessment["observation_set_id"],
        )
    observation_set, manifest = found
    per_item = _rows(artifacts.read_verified(study, assessment["per_item_ref"]))
    return {
        "role": role,
        "assessment": assessment,
        "observation_set": observation_set,
        "manifest": manifest,
        "partition": observation_set["provenance"].get("partition"),
        "population_sha256": _population_digest(study, observation_set),
        "per_item": per_item,
        "metric": assessment["metrics"][0],
    }


def _refuse(check, evaluated, control, candidate, message):
    code, reason = REFUSALS[check]
    return IntegrityError(
        code,
        message,
        stage=STAGE,
        details={"check": check, "reason": reason, "control": control, "candidate": candidate, "checks": evaluated},
    )


def _scorer_differences(control: dict, candidate: dict) -> list:
    return [key for key in ("id", "version", "config_digest") if control["scorer"][key] != candidate["scorer"][key]]


def check_assessments(control: dict, candidate: dict, checks: list) -> None:
    """The References, Scorer and unit checks, common to every Track: each appended to `checks` when it passes, a refusal otherwise."""
    ca, da = control["assessment"], candidate["assessment"]
    if ca["references_ref"]["sha256"] != da["references_ref"]["sha256"]:
        raise _refuse(
            "references",
            [*checks, {"check": "references", "passed": False, "reason": REFUSALS["references"][1]}],
            {"references_sha256": ca["references_ref"]["sha256"]},
            {"references_sha256": da["references_ref"]["sha256"]},
            "the two Assessments were scored against different References",
        )
    checks.append({"check": "references", "passed": True, "reason": None})

    differs = _scorer_differences(ca, da)
    if differs:
        raise _refuse(
            "scorer",
            [*checks, {"check": "scorer", "passed": False, "reason": REFUSALS["scorer"][1]}],
            ca["scorer"],
            da["scorer"],
            f"the two Assessments were made by different Scorers (differs: {', '.join(differs)})",
        )
    checks.append({"check": "scorer", "passed": True, "reason": None})

    if control["metric"]["unit"] != candidate["metric"]["unit"]:
        raise _refuse(
            "unit",
            [*checks, {"check": "unit", "passed": False, "reason": REFUSALS["unit"][1]}],
            {"unit": control["metric"]["unit"]},
            {"unit": candidate["metric"]["unit"]},
            "the two Assessments are in different units",
        )
    checks.append({"check": "unit", "passed": True, "reason": None})


def describe_environments(control_manifest: dict, candidate_manifest: dict) -> tuple:
    """(the `code_environment` block of a Comparison, the sentence of its limitations): what differs, never "identical" (ID-03).

    An Import records the code environment of the importer, not of the program that produced its outputs. A Comparison
    with an Import therefore establishes nothing about a shared environment: `same` is null, and no sentence says the executions share or differ in their environment.
    """
    environments = (control_manifest["code_environment"], candidate_manifest["code_environment"])
    differs = sorted(
        key for key in set(environments[0]) | set(environments[1]) if canonical.dumps(environments[0].get(key)) != canonical.dumps(environments[1].get(key))
    )
    block = {"same": not differs, "differs": differs, "control": environments[0], "candidate": environments[1]}
    imports = [role for role, manifest in (("control", control_manifest), ("candidate", candidate_manifest)) if manifest["mode"] == EXTERNAL_MODE]
    if imports:
        block = {**block, "same": None}
        sentence = (
            f"The {' and '.join(imports)} of this Comparison is an Import: it records the code environment of the importer, not of the program "
            "that produced its outputs, so whether the two executions ran in the same code environment is not established."
        )
    elif differs:
        sentence = (
            f"The two Attempts ran in different code environments (differs: {', '.join(differs)}): "
            "the two executions are not identical, and the difference may owe something to that."
        )
    else:
        sentence = "The two Attempts record the same code environment; this does not establish that the two executions were identical."
    return block, sentence


def import_scope_warning(imports: list) -> dict:
    """The warning of a descriptive Comparison: the roles that are an Import and what that leaves unverified."""
    message = (
        f"The {' and '.join(imports)} of this Comparison is an Import (Mode {EXTERNAL_MODE}): its producer, model, generation time "
        "and exposure to public_check are declared or unknown, never verified. The Comparison is descriptive, not strict: "
        "it supports no claim that the two sides were produced under the same conditions."
    )
    return {"code": WARNING_DESCRIPTIVE, "message": message}


def single_feature_warning(side: dict):
    """The warning of a side whose Assessment records lag features that beat it, read from its `single_feature_check`; None otherwise."""
    beating = side["assessment"].get("single_feature_check", {}).get("beating", [])
    if not beating:
        return None
    unit = side["metric"]["unit"]
    features = ", ".join(f"{entry['feature']} ({entry['value']:.6g} {unit})" for entry in beating)
    message = (
        f"The {side['role']} of this Comparison (Assessment {side['assessment']['assessment_id']}, {side['metric']['id']} "
        f"{side['metric']['value']:.6g} {unit}) is beaten by lag features of its own Configuration, each used alone as the forecast "
        f"on the same Items: {features}."
    )
    return {"code": WARNING_SINGLE_FEATURE, "message": message}


def compare(study, control_id: str, candidate_id: str, factor: str | None = None, *, live_basis=None, read_sequence: int | None = None) -> dict:
    """Write and return a Comparison of the Assessment `control_id` (Control) and `candidate_id` (Candidate).

    `factor` is the factor the request declares as the intentional one (agent Track only). Holds the Study's
    writer lock for the whole command: a second writer is refused at once. `live_basis` is a function of the
    Study's spec that returns the Track's `freeze_basis` of the Workload; it is called only for a Comparison of
    `public_check` Items, to freeze the Workload's digests (see `hypotrail.core.exposure`).
    """
    study = Path(study)
    study_write.check_read_sequence(study_write.COMPARE, read_sequence)
    spec = layout.read_spec(study)  # a folder that is no Study is refused before a lock file is created in it
    if factor is not None and spec["domain"] != AGENTIC:
        raise InvalidInputError(
            "UNSUPPORTED_CAPABILITY",
            f"a Comparison of a Study of the {spec['domain']!r} domain declares no factor: only the agentic Track has one",
            stage=STAGE,
            details={"factor": factor, "study_domain": spec["domain"]},
        )
    with study_write.locked(study, study_write.COMPARE, read_sequence=read_sequence) as write:
        write.require_current()
        return _compare_locked(study, write, control_id, candidate_id, factor, live_basis)


def check_partition(partition) -> bool:
    """True for `public_check` (the Comparison is an Exposure), False for `dev`; any other Partition is refused."""
    if partition in (DEV, PUBLIC_CHECK):
        return partition == PUBLIC_CHECK
    raise InvalidInputError(
        "COMPARISON_PARTITION_NOT_DEV",
        f"a Comparison is computed on {DEV} or {PUBLIC_CHECK} only, not on {partition!r}",
        stage=STAGE,
        details={"partition": partition},
    )


def record_exposure(study: Path, write, control: dict, candidate: dict, comparison_id: str, live_basis) -> None:
    """Append the journal entry of a Comparison of `public_check` Items, before the Comparison computes on them."""
    exposure.record(
        study,
        write,
        layout.read_spec(study),
        live_basis,
        attempt_ids=[side["manifest"]["attempt_id"] for side in (control, candidate)],
        assessment_ids=[side["assessment"]["assessment_id"] for side in (control, candidate)],
        comparison_ids=[comparison_id],
    )


def _compare_locked(study: Path, write, control_id: str, candidate_id: str, factor: str | None, live_basis) -> dict:
    control = _side(study, "control", control_id)
    candidate = _side(study, "candidate", candidate_id)

    if control["observation_set"]["domain"] == AGENTIC:
        from hypotrail.core import agent_comparison  # loaded for an agent Comparison only

        return agent_comparison.compare_sides(study, write, control, candidate, factor, live_basis)

    for side in (control, candidate):
        side["items"] = {row["row_id"]: row for row in side["per_item"]}
    checks = []

    def passed(check, ok, reason=None):
        checks.append({"check": check, "passed": ok, "reason": reason})

    # population
    if control["partition"] != candidate["partition"] or control["population_sha256"] != candidate["population_sha256"]:
        evaluated = [*checks, {"check": "population", "passed": False, "reason": REFUSALS["population"][1]}]
        raise _refuse(
            "population",
            evaluated,
            {"partition": control["partition"], "population_sha256": control["population_sha256"]},
            {"partition": candidate["partition"], "population_sha256": candidate["population_sha256"]},
            f"the Control is on {control['partition']!r} and the Candidate on {candidate['partition']!r} (or on another population): "
            "not the same population",
        )
    passed("population", True)
    exposed = check_partition(control["partition"])

    ca, da = control["assessment"], candidate["assessment"]
    check_assessments(control, candidate, checks)

    only_control = sorted(set(control["items"]) - set(candidate["items"]))
    only_candidate = sorted(set(candidate["items"]) - set(control["items"]))
    if only_control or only_candidate:
        raise _refuse(
            "items",
            [*checks, {"check": "items", "passed": False, "reason": REFUSALS["items"][1]}],
            {"items": len(control["items"]), "only_here": len(only_control)},
            {"items": len(candidate["items"]), "only_here": len(only_candidate)},
            f"the Control has {len(control['items'])} Items and the Candidate {len(candidate['items'])}; "
            f"{len(only_control)} and {len(only_candidate)} are on one side only: no paired Comparison, and no intersection is computed",
        )
    passed("items", True)

    modes = (control["observation_set"]["mode"], candidate["observation_set"]["mode"])
    external = [side["role"] for side in (control, candidate) if side["observation_set"]["mode"] == EXTERNAL_MODE]
    if external:
        passed("mode", False, REASON_PROVENANCE)  # descriptive, never strict: not a refusal
    elif modes[0] != modes[1]:
        raise _refuse(
            "mode",
            [*checks, {"check": "mode", "passed": False, "reason": REFUSALS["mode"][1]}],
            {"mode": modes[0]},
            {"mode": modes[1]},
            "the two sides were not produced in the same Mode",
        )
    else:
        passed("mode", True)

    comparison_id = str(uuid.uuid4())
    if exposed:  # before any paired difference is computed
        record_exposure(study, write, control, candidate, comparison_id, live_basis)
    row_ids = sorted(control["items"])
    paired = []
    scored = {"control": 0, "candidate": 0}
    for row_id in row_ids:
        c, d = control["items"][row_id], candidate["items"][row_id]
        scored["control"] += c["state"] == "scored"
        scored["candidate"] += d["state"] == "scored"
        if c["state"] == "scored" and d["state"] == "scored":
            paired.append((row_id, float(c["value"]), float(d["value"])))
    coverage = {
        "expected": len(row_ids),
        "control_scored": scored["control"],
        "candidate_scored": scored["candidate"],
        "paired": len(paired),
    }
    if len(paired) != len(row_ids):
        raise _refuse(
            "coverage",
            [*checks, {"check": "coverage", "passed": False, "reason": REFUSALS["coverage"][1]}],
            {"expected": coverage["expected"], "scored": scored["control"]},
            {"expected": coverage["expected"], "scored": scored["candidate"]},
            f"only {len(paired)} of {len(row_ids)} Items are scored on both sides: the paired Comparison would hide the others",
        )
    passed("coverage", True)

    control_metric, candidate_metric = control["metric"]["value"], candidate["metric"]["value"]
    delta = None if control_metric is None or candidate_metric is None else candidate_metric - control_metric

    environment, environment_sentence = describe_environments(control["manifest"], candidate["manifest"])
    limitations = [LIMITATION_DEPENDENCE, environment_sentence]
    warnings = []
    descriptive = bool(external)
    if descriptive:
        warning = import_scope_warning(external)
        warnings.append(warning)
        limitations.append(warning["message"])
    for side in (control, candidate):
        warning = single_feature_warning(side)
        if warning is not None:
            warnings.append(warning)
            limitations.append(warning["message"])

    folder = f"{layout.COMPARISONS_DIR}/{comparison_id}"
    population = {
        "partition": control["partition"],
        "population_sha256": control["population_sha256"],
        "count": len(row_ids),
        "row_ids": row_ids,
    }
    write.begin()  # a Comparison of dev Items writes nothing before this; an Exposure began the command already
    population_ref = artifacts.publish_record(study, f"{folder}/population.json", population, role="comparison_population")
    write.wrote(study_write.COMPARISON, comparison_id)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(PAIRED_COLUMNS)
    for row_id, c_error, d_error in paired:
        writer.writerow([row_id, repr(c_error), repr(d_error), repr(d_error - c_error)])
    paired_ref = artifacts.publish_bytes(
        study, f"{folder}/paired_deltas.csv", out.getvalue().encode("utf-8"), media_type="text/csv", role="paired_deltas"
    )
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
        "coverage": coverage,
        "delta": {"metric": control["metric"]["id"], "value": delta, "unit": control["metric"]["unit"], "definition": DELTA_DEFINITION},
        **exposure.marks(study, [control["manifest"], candidate["manifest"]], [ca, da]),
        "code_environment": environment,
        "warnings": warnings,
        "limitations": limitations,
    }
    contracts.validate(record)
    artifacts.publish_record(study, f"{folder}/comparison.json", record, role="comparison")
    return record
