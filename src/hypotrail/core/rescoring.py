"""What a new Assessment says about the earlier one of the same Observation set: the `rescoring` field (T11).

A corrected Reference, a changed numeric tolerance (held by the Reference) or a new Scorer version
changes verdicts without any change of the evaluated system, so the Assessment that follows says so
(RES-02; SPEC §5 « Une nouvelle évaluation ou correction de référence crée un nouvel assessment_id »).

The earlier Assessment is the latest one of the same Observation set and the same Scorer id that differs
from the new one in at least one of three things: the References set (by digest), the Scorer's version,
the Scorer's `config_digest`. The first of those that differs, in that order, is the `cause`; any other is
listed in `other_changes`, so nothing that changed is hidden. When nothing differs from any earlier
Assessment the new one is a repeat and `rescoring` is null. The Items whose verdict changed are listed with
both verdicts, one entry per Item and Criterion; an Episode's Item ID is `CASE_ID#REPEAT`.

This reads only files the Study keeps, each read back against its digest: no model, no tool and no
Workload file.
"""

import csv
import io

from hypotrail.core import artifacts
from hypotrail.core import study as layout

CAUSES = ("references_version", "scorer_version", "scorer_config_digest")


def _causes(earlier: dict, scorer: dict, references_ref: dict) -> list:
    differs = {
        "references_version": earlier["references_ref"]["sha256"] != references_ref["sha256"],
        "scorer_version": earlier["scorer"]["version"] != scorer["version"],
        "scorer_config_digest": earlier["scorer"]["config_digest"] != scorer["config_digest"],
    }
    return [cause for cause in CAUSES if differs[cause]]


def verdicts_of(per_item: bytes) -> dict:
    """{(item ID, Criterion): {state, score, reason}} of a `per_item.csv` of either Track."""
    out = {}
    for row in csv.DictReader(io.StringIO(per_item.decode("utf-8"), newline="")):
        if "row_id" in row:  # a numeric loss: the score is the value
            item, score = row["row_id"], (float(row["value"]) if row["value"] != "" else None)
        else:  # an Episode: the score is a boolean
            item, score = f"{row['case_id']}#{row['repeat']}", {"true": True, "false": False, "": None}[row["score"]]
        out[(item, row["criterion"])] = {"state": row["state"], "score": score, "reason": row["reason"] or None}
    return out


def describe(study, *, observation_set_id: str, scorer: dict, references_ref: dict, per_item: bytes):
    """The `rescoring` object of a new Assessment (not yet written), or None when it repeats an earlier one."""
    candidates = []
    for earlier in layout.assessment_records(study):
        if earlier["observation_set_id"] != observation_set_id or earlier["scorer"]["id"] != scorer["id"]:
            continue
        causes = _causes(earlier, scorer, references_ref)
        if causes:
            candidates.append((earlier.get("recorded_at", ""), earlier["assessment_id"], earlier, causes))
    if not candidates:
        return None
    _, _, earlier, causes = max(candidates, key=lambda c: c[:2])
    before = verdicts_of(artifacts.read_verified(study, earlier["per_item_ref"]))
    now = verdicts_of(per_item)
    changes = [
        {"item_id": item, "criterion": criterion, "earlier": before.get((item, criterion)), "now": now.get((item, criterion))}
        for item, criterion in sorted(set(before) | set(now))
        if before.get((item, criterion)) != now.get((item, criterion))
    ]
    rescoring = {"earlier_assessment_id": earlier["assessment_id"], "cause": causes[0], "changed_items": changes}
    if causes[1:]:
        rescoring["other_changes"] = causes[1:]
    return rescoring
