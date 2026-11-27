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

When the Study's current revision declares a `resampling` by blocks, the Comparison's `interval` resamples the paired differences in the
order of the days the Study's memberships give, by circular blocks of the declared length (`hypotrail.core.intervals`), once the
Exposure entry is written; a population that lists fewer days than its Partition gets none (`series_not_contiguous`).

A side whose Assessment lists, in `single_feature_check`, lag features of its own Configuration that beat it gets one warning
(`COMPARISON_SINGLE_FEATURE_BEATS`) naming the side and those features with their Metrics, also in `limitations`. It is read
from the record, never computed here, and it leaves the status as the checks and Imports compute it. A side whose field is
empty or absent gets none.

A side that a declaration in force covers, a Declared deviation of the Study (`hypotrail.core.deviations`) that cites its Attempt or the
References set its Assessment was scored against, gets one warning for that declaration (`COMPARISON_DEVIATION_DECLARED`), naming the side or
sides, the Declared deviation's id and its text, also in `limitations`. Two declarations give two warnings, in the order of their
`write_sequence`. It is read when the Comparison is written, and it leaves the status as the checks and Imports compute it. Both Tracks
add it (`declared_deviation_warnings`).

A refused check raises its own code (exit 3) whose details carry the `check`, its Reason code, the
values of both sides and the checks evaluated so far, and writes no Comparison. `delta` is the Metric of
the Candidate minus the Metric of the Control. A positive ranking delta means the Candidate has higher
recall. The command holds the Study's writer lock for its whole execution.
"""

import csv
import io
import uuid
from decimal import Decimal
from pathlib import Path

from hypotrail.core import artifacts, canonical, contracts, deviations, exposure, intervals, ranking_intervals, study_write
from hypotrail.core import study as layout
from hypotrail.core.errors import IntegrityError, InvalidInputError

STAGE = "compare"
DEV = "dev"
PUBLIC_CHECK = "public_check"
EXTERNAL_MODE = "external_unknown"
AGENTIC = "agentic"
RANKING = "ranking"
PAIRED_COLUMNS = ["row_id", "control_abs_error", "candidate_abs_error", "delta_abs_error"]
DELTA_DEFINITION = "Metric(Candidate) - Metric(Control); positive means the Candidate is worse (the Metric is lower-is-better)"
RANKING_DELTA_DEFINITION = "Recall(Candidate) - Recall(Control); positive means the Candidate is better (the Metric is higher-is-better)"

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
WARNING_DEVIATION_DECLARED = "COMPARISON_DEVIATION_DECLARED"
# The warnings of a regression Comparison that state a deviation rather than a descriptive scope: `compare` and the report name
# their codes beside the status, as for `agent_comparison.DEVIATIONS`, since a `compatible` Comparison can hold them.
DEVIATIONS = (WARNING_SINGLE_FEATURE, WARNING_DEVIATION_DECLARED)
LIMITATION_DEPENDENCE = "Daily observations are dependent: the delta carries no confidence interval and no significance claim."
# The first limitation once a block interval is computed (`hypotrail.core.intervals`), with the declared block length. Its clause on
# strong dependence states what the kept coverage simulation measured (`docs/handbook/simulations/interval-coverage.json`).
LIMITATION_BLOCKS = (
    "Daily observations are dependent: the interval resamples blocks of {length} consecutive days, which assumes that the dependence "
    "beyond {length} days is weak, and it can be too narrow under strong dependence; the delta carries no significance claim."
)
LIMITATION_ENTITIES = (
    "The ranking interval resamples paired entity histories. It describes the scored population and dates, with no significance claim."
)


def _not_found(code, message, **details):
    return InvalidInputError(code, message, stage=STAGE, details=details)


def _rows(data: bytes) -> list:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"), newline="")))


def _population_identity(study: Path, observation_set: dict) -> tuple[str, list | None]:
    """The digest and expected Items of a side's population.

    An Import's population file and the Study's memberships name the same population when they expect the same
    Items, so the artifact's bytes are not compared (the agent Track compares its Cases, `agent_comparison`).
    """
    ref = observation_set["population_ref"]
    if observation_set["domain"] == AGENTIC:
        return ref["sha256"], None
    partition = observation_set["provenance"].get("partition")
    expected = layout.expected_row_ids(study, ref, partition)
    return canonical.sha256_hex(canonical.dumps({"partition": partition, "row_ids": expected})), expected


def _side(study: Path, role: str, assessment_id: str, *, run_tool: bool = False) -> dict:
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
    partition = observation_set["provenance"].get("partition")
    if run_tool:
        exposure.refuse_public_check(PUBLIC_CHECK, manifest["effective_config"].get("partition"), partition)
    if observation_set["domain"] == RANKING and partition != DEV:
        raise _not_found("COMPARISON_PARTITION_NOT_DEV", "a ranking Comparison is computed on dev only", partition=partition)
    per_item = _rows(artifacts.read_verified(study, assessment["per_item_ref"]))
    digest, expected = _population_identity(study, observation_set)
    return {
        "role": role,
        "assessment": assessment,
        "observation_set": observation_set,
        "manifest": manifest,
        "partition": partition,
        "population_sha256": digest,
        "expected_items": expected,
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


def declared_deviation_warnings(study: Path, control: dict, candidate: dict) -> list:
    """One warning for each declaration in force that covers a side, in the order of their `write_sequence`, read from the Study's records.

    A declaration covers a side when it cites that side's Attempt, or the References set that side's Assessment was scored against (the
    Study artifact whose digest is the Assessment's `references_ref` digest). A withdrawn declaration and a withdrawal cover nothing.
    """
    references = deviations.references_sets(study)
    warnings = []
    for declared in sorted(deviations.in_force(study), key=lambda record: record["write_sequence"]):
        cited = set(declared["cited_ids"])
        roles = [
            side["role"]
            for side in (control, candidate)
            if side["manifest"]["attempt_id"] in cited
            or any(references.get(each) == side["assessment"]["references_ref"]["sha256"] for each in cited)
        ]
        if roles:
            message = (
                f"The {' and the '.join(roles)} of this Comparison {'is' if len(roles) == 1 else 'are'} covered by the Declared deviation "
                f"{declared['declared_deviation_id']}, recorded by {declared['author']}: {declared['text']}"
            )
            warnings.append({"code": WARNING_DEVIATION_DECLARED, "message": message})
    return warnings


def compare(
    study, control_id: str, candidate_id: str, factor: str | None = None, *,
    live_basis=None, read_sequence: int | None = None, run_tool: bool = False,
) -> dict:
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
        return _compare_locked(study, write, control_id, candidate_id, factor, live_basis, run_tool=run_tool)


def date_order(study: Path, spec: dict, partition: str, row_ids: list):
    """`row_ids` in the order of their dates in the Study's memberships, or None when they are not every day of `partition`.

    The order is read from the `date` column, never from the spelling of a `row_id`; a population that lists fewer days than the
    Partition is a series with gaps, whose blocks would join days that are not consecutive.
    """
    ref = next(entry["ref"] for entry in spec["artifacts"] if entry["ref"]["role"] == "memberships")
    rows = csv.DictReader(io.StringIO(artifacts.read_verified(study, ref).decode("utf-8"), newline=""))
    days = {row["row_id"]: row["date"] for row in rows if row["partition"] == partition}
    if set(row_ids) != set(days):
        return None
    return sorted(row_ids, key=days.__getitem__)


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


def _ranking_items_match(control: dict, candidate: dict) -> bool:
    fields = ("entity_id", "as_of", "label")
    for side in (control, candidate):
        if len(side["items"]) != len(side["per_item"]) or sorted(side["items"]) != side["expected_items"]:
            return False
    return all(
        all(c[key] == candidate["items"][item_id][key] for key in fields)
        for item_id, c in control["items"].items()
    )


def _ranking_pair(control: dict, candidate: dict) -> ranking_intervals.RankingPair:
    return ranking_intervals.RankingPair(
        control["item_id"], control["entity_id"], control["as_of"], control["label"] == "1",
        Decimal(control["score"]), Decimal(candidate["score"]),
    )


def _paired_deltas(study: Path, folder: str, pairs: list) -> dict:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(PAIRED_COLUMNS)
    for row_id, c_error, d_error in pairs:
        writer.writerow([row_id, repr(c_error), repr(d_error), repr(d_error - c_error)])
    return artifacts.publish_bytes(
        study, f"{folder}/paired_deltas.csv", out.getvalue().encode("utf-8"), media_type="text/csv", role="paired_deltas"
    )


def _compare_locked(study: Path, write, control_id: str, candidate_id: str, factor: str | None, live_basis, *, run_tool: bool = False) -> dict:
    control = _side(study, "control", control_id, run_tool=run_tool)
    candidate = _side(study, "candidate", candidate_id, run_tool=run_tool)

    if control["observation_set"]["domain"] == AGENTIC:
        from hypotrail.core import agent_comparison  # loaded for an agent Comparison only

        return agent_comparison.compare_sides(study, write, control, candidate, factor, live_basis)

    ranking = control["observation_set"]["domain"] == RANKING
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

    for side in (control, candidate):
        key = "item_id" if side["observation_set"]["domain"] == RANKING else "row_id"
        side["items"] = {row[key]: row for row in side["per_item"]}
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
    if ranking and not _ranking_items_match(control, candidate):
        raise _refuse(
            "items",
            [*checks, {"check": "items", "passed": False, "reason": REFUSALS["items"][1]}],
            {"items": len(control["items"])},
            {"items": len(candidate["items"])},
            "ranking Assessments must record each expected Item once with the same entity, date and Reference on both sides",
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
        if ranking:  # The ranking importer requires one finite score for every expected Item.
            paired.append(_ranking_pair(c, d))
            scored["control"] += 1
            scored["candidate"] += 1
            continue
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

    if ranking:
        interval = ranking_intervals.record(paired, control["population_sha256"])
        first = LIMITATION_ENTITIES
    else:
        spec = layout.read_spec(study)
        resampling = spec.get("resampling")
        ordered = None if resampling is None or delta is None else date_order(study, spec, control["partition"], row_ids)
        differences = {row_id: d_error - c_error for row_id, c_error, d_error in paired}
        interval = intervals.record(
            resampling,
            None if ordered is None else [differences[row_id] for row_id in ordered],
            missing=intervals.DELTA_WITHHELD if delta is None else intervals.SERIES_NOT_CONTIGUOUS,
        )
        first = LIMITATION_DEPENDENCE if interval["reason"] is not None else LIMITATION_BLOCKS.format(length=interval["block_length"])
    environment, environment_sentence = describe_environments(control["manifest"], candidate["manifest"])
    limitations = [first, environment_sentence]
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
    for warning in declared_deviation_warnings(study, control, candidate):
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
    paired_ref = None if ranking else _paired_deltas(study, folder, paired)
    delta_record = {
        "metric": control["metric"]["id"], "value": delta, "unit": control["metric"]["unit"],
        "definition": RANKING_DELTA_DEFINITION if ranking else DELTA_DEFINITION,
    }
    if ranking and delta is None:
        delta_record["reason"] = control["metric"].get("reason") or candidate["metric"].get("reason") or intervals.DELTA_WITHHELD
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
        "delta": delta_record,
        "interval": interval,
        **exposure.marks(study, [control["manifest"], candidate["manifest"]], [ca, da]),
        "code_environment": environment,
        "warnings": warnings,
        "limitations": limitations,
    }
    contracts.validate(record)
    artifacts.publish_record(study, f"{folder}/comparison.json", record, role="comparison")
    return record
