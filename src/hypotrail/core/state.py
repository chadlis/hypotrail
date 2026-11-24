"""The local state of a Study: `status` reads it, `recover` records an interrupted Attempt.

`status` only reads (SPEC §5: an explicit command inspects and recovers the local state): it lists
every Attempt with its `technical_status`, its artifacts (the partial ones of an Attempt that never
reached its terminal manifest included, each with the digest of its bytes) and whether a live writer
holds the Study; and every revision of the Study (`hypotrail.core.revisions`) with its Protocol digest and
its Protocol artifacts; the freeze records, the Exposure journal and every `check_informed` mark
(`hypotrail.core.exposure`). A Study with no journal entry reports zero Exposures recorded in this Study and
says that any earlier exposure is unknown. It shows the Study's write sequence, the number of entries of its write journal
(`hypotrail.core.write_journal`), as the top-level key `write_sequence`. It lists the Study's decisions, in the order they were recorded, each with the fields `decide` recorded
and whether it still applies (`hypotrail.core.decisions`, `history`), computed now and never stored, as the top-level key `decisions`, and its Declared
deviations, each with whether it is withdrawn (`hypotrail.core.deviations`, `listing`), as the top-level key `declared_deviations`. It lists every Assessment
record (`assessments`) and every Comparison record (`comparisons`) the Study holds, each as stored, in the order of the write journal
(`decisions.assessments_in_order` and `write_journal.comparison_order`), and the Comparisons that wait for a decision (`pending_decisions`,
`hypotrail.core.decisions`, `pending`). It writes nothing and holds no lock; it probes whether a
writer holds the lock (`lock.is_held`) with a non-blocking shared lock taken and dropped at once, so a writer starting at
that instant is refused.

`recover` is the explicit command that writes (chadlis/hypotrail#65, Tightened A). Under the writer
lock, it records as `interrupted`, with `finished_at` and a Reason, an Attempt that is `running`
while no writer is alive; the lock being taken is the proof that none is. It keeps every artifact
the Attempt published and resubmits nothing. It refuses an Attempt that is already terminal
(`ATTEMPT_TERMINAL`, exit 3), an Attempt the Study does not hold (`ATTEMPT_NOT_FOUND`, exit 2) and,
while a writer is alive, the whole command (`STUDY_LOCKED`, exit 6).

A lock that is gone never proves that a remote call was cancelled: an Attempt whose Mode calls a
provider (`llm_live`) is recorded with `outcome_unknown: true`, whatever it held before.
"""

import datetime
from pathlib import Path

from hypotrail.core import artifacts, canonical, contracts, decisions, deviations, exposure, lock, revisions, study_write, write_journal
from hypotrail.core import study as layout
from hypotrail.core.errors import InvalidInputError

PROVIDER_MODES = ("llm_live",)
RECOVER_REASON = (
    "the writer ended before the terminal manifest; recorded as interrupted by `recover` "
    "(partial artifacts kept, nothing resubmitted)"
)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _listed_artifacts(study: Path, manifest: dict) -> tuple[list, list]:
    """The artifacts found in the Attempt's folder, and the temporary files a dead writer left behind."""
    folder = f"{layout.ATTEMPTS_DIR}/{manifest['attempt_id']}"
    roles = {ref["path"]: ref["role"] for ref in [*manifest["input_refs"], *manifest.get("output_refs", [])]}
    found, leftovers = [], []
    for path in sorted(artifacts.resolve(study, folder).rglob("*")):
        relative = path.relative_to(study.resolve()).as_posix()
        if not path.is_file() or relative == f"{folder}/{layout.MANIFEST_NAME}":
            continue
        if path.name.endswith(artifacts.TEMP_SUFFIX):
            leftovers.append(relative)
            continue
        data = artifacts.resolve(study, relative).read_bytes()
        found.append(
            {
                "path": relative,
                "sha256": canonical.sha256_hex(data),
                "size_bytes": len(data),
                "media_type": layout.media_type_of(relative),
                "referenced": relative in roles,
                "role": roles.get(relative),
            }
        )
    return found, leftovers


def check_informed(study: Path) -> list:
    """Every record that carries the `check_informed` mark: a revision, an Attempt, an Assessment or a Comparison."""
    marked = [
        {"kind": "revision", "id": each["revision"], "revision_number": revisions.revision_number(each)}
        for each in revisions.revision_specs(study)
        if each.get("check_informed")
    ]
    marked += [{"kind": "attempt", "id": attempt_id} for attempt_id in layout.attempt_ids(study) if layout.read_manifest(study, attempt_id).get("check_informed")]
    marked += [{"kind": "assessment", "id": r["assessment_id"]} for r in layout.assessment_records(study) if r.get("check_informed")]
    marked += [{"kind": "comparison", "id": r["comparison_id"]} for r in layout.comparison_records(study) if r.get("check_informed")]
    return marked


def status(study) -> dict:
    """The Study's local state, read only."""
    study = Path(study)
    spec = layout.read_spec(study)
    writer_alive = lock.is_held(study)  # probed before the state is read
    attempts = []
    for attempt_id in layout.attempt_ids(study):
        manifest = layout.read_manifest(study, attempt_id)
        found, leftovers = _listed_artifacts(study, manifest)
        running = manifest["technical_status"] == "running"
        attempts.append(
            {
                **{
                    key: manifest[key]
                    for key in ("attempt_id", "request_id", "operation", "mode", "technical_status", "started_at", "finished_at", "outcome_unknown", "retry_of")
                },
                "reason": manifest.get("reason"),
                "item_counts": manifest.get("item_counts"),
                "writer_alive": running and writer_alive,
                "recoverable": running and not writer_alive,
                "artifacts": found,
                "temporary_files": leftovers,
            }
        )
    history = decisions.history(study)
    return {
        "study": {
            **{key: spec[key] for key in ("study_id", "workload", "protocol_id", "protocol_digest", "revision")},
            "revision_number": revisions.revision_number(spec),
        },
        "writer_alive": writer_alive,
        "revisions": [
            {
                "revision_number": revisions.revision_number(each),
                "revision": each["revision"],
                "previous_revision": each.get("previous_revision"),
                "protocol_digest": each["protocol_digest"],
                "artifacts": [
                    {"artifact_id": e["artifact_id"], "role": e["ref"]["role"], "version": revisions.version_of(e), "sha256": e["ref"]["sha256"]}
                    for e in each["artifacts"]
                ],
            }
            for each in revisions.revision_specs(study)
        ],
        "attempts": attempts,
        "freeze_records": exposure.freeze_records(study),
        "exposures": exposure.summary(study),
        "check_informed": check_informed(study),
        "write_sequence": write_journal.write_sequence(study),
        "decisions": history,
        "declared_deviations": deviations.listing(study),
        "assessments": decisions.assessments_in_order(study),
        "comparisons": sorted(layout.comparison_records(study), key=write_journal.comparison_order(study)),
        "pending_decisions": decisions.pending(study, history),
    }


def recover(study, attempt_id: str, *, read_sequence: int | None = None) -> dict:
    """Record the Attempt `attempt_id`, running with no live writer, as interrupted; return its manifest."""
    study = Path(study)
    study_write.check_read_sequence(study_write.RECOVER, read_sequence)
    layout.read_spec(study)
    with study_write.locked(study, study_write.RECOVER, read_sequence=read_sequence) as write:
        write.require_current()
        if attempt_id not in layout.attempt_ids(study):
            raise InvalidInputError(
                "ATTEMPT_NOT_FOUND",
                f"the Study holds no Attempt {attempt_id!r}",
                stage="attempt",
                details={"attempt_id": attempt_id},
            )
        manifest = layout.read_manifest(study, attempt_id)
        if manifest["technical_status"] != "running":
            raise artifacts.terminal_attempt(attempt_id, manifest["technical_status"], layout.attempt_manifest_path(attempt_id))
        interrupted = {
            **manifest,
            "technical_status": "interrupted",
            "finished_at": _now(),
            "reason": RECOVER_REASON,
            "outcome_unknown": manifest["outcome_unknown"] or manifest["mode"] in PROVIDER_MODES,
        }
        contracts.validate(interrupted)
        write.begin()
        artifacts.replace_bytes(study, layout.attempt_manifest_path(attempt_id), canonical.dumps(interrupted))
        write.wrote(study_write.ATTEMPT, attempt_id)
        return interrupted
