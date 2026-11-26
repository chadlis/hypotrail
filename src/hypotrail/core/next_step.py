"""`next_step`: what waits in a Study, judged by the core when the Study is read and never stored (chadlis/hypotrail#251; D-136 and D-151
on chadlis/hypotrail#75).

`status` gives it as one top-level key, always present, with seven keys. The priority, in D-136's words:

1. "an interrupted Attempt goes to "To handle", never to Now": `to_handle` lists the id of each Attempt that is `recoverable`, in the order
   of `attempts`, whatever the rules below give;
2. "a Pending decision is Now, with any earlier Decision that no longer applies shown inside it as context": `kind` is `decide`, `ids`
   lists the Comparison id of each pending decision, in the order of `pending_decisions`, and `context` the flagged Decisions;
3. "with no Pending decision and a Decision that no longer applies, Now says "your Decision no longer applies"": `kind` is
   `look_again`, `text` is "Your Decision no longer applies." and `ids` lists the flagged Decisions;
4. "otherwise nothing waits": `kind` and `text` are null and `ids` is empty.

`text` is null under every rule but 3, and `context` empty under every rule but 2.

"A Decision that no longer applies stops being flagged once a later applying Decision answers a Comparison of the same two
Configurations." A Decision that no longer applies is `flagged` (its id) or `answered` (`{decision, by}`, `by` the first later Decision,
in the order `decide` recorded them, that applies and cites a Comparison of the same two Configurations as a Comparison the first one
cites), each in the order of `decisions`. A Decision that cites no Comparison is never answered.

"The same two Configurations" is the unordered pair of the identities of a Comparison's two sides. The drive's answer, refining D-151
answer 2 and logged as D-159: "A side's identity is `configuration_digest_of(manifest)` when it is not None (a declared Configuration),
and otherwise the Attempt's own id (an Import is only ever the same as itself)." A side is found from its Assessment, through its Observation set, to the
manifest of the Attempt that recorded it; a side the Study does not hold has no identity, and its Comparison is of no pair. So the same
declared Configuration is the same one on every Partition, and two Imports never match by both declaring none; a changed Workload
already stops a Decision through `revision_changed`.
"""

from hypotrail.core import decisions, exposure
from hypotrail.core import study as layout

DECIDE, LOOK_AGAIN = "decide", "look_again"
NO_LONGER_APPLIES = "Your Decision no longer applies."


def _identity(study, assessment, found: dict):
    """The identity of one side: its Configuration digest, else its Attempt id; None when the Study does not hold the side's records."""
    if assessment is None:
        return None
    observation_set_id = assessment["observation_set_id"]
    if observation_set_id not in found:
        located = layout.find_observation_set(study, observation_set_id)
        manifest = None if located is None else located[1]
        found[observation_set_id] = None if manifest is None else exposure.configuration_digest_of(manifest) or manifest["attempt_id"]
    return found[observation_set_id]


def _pairs(study, comparisons: dict, assessments: dict) -> dict:
    """{comparison id: the sorted pair of its sides' identities}, for each Comparison whose two sides have one."""
    found: dict = {}
    pairs = {}
    for comparison_id, comparison in comparisons.items():
        sides = [_identity(study, assessments.get(assessment_id), found) for _, assessment_id in decisions.sides(comparison)]
        if None not in sides:
            pairs[comparison_id] = tuple(sorted(sides))
    return pairs


def next_step(study, attempts: list, history: list, pending: list) -> dict:
    """The `next_step` of a read, from its `attempts`, its `decisions` (`history`) and its `pending_decisions` (read only)."""
    pairs = {}
    if any(not row["applies"] for row in history):
        comparisons = {record["comparison_id"]: record for record in layout.comparison_records(study)}
        assessments = {record["assessment_id"]: record for record in layout.assessment_records(study)}
        pairs = _pairs(study, comparisons, assessments)
    flagged, answered = [], []
    for at, row in enumerate(history):
        if row["applies"]:
            continue
        own = {pairs[cited] for cited in row["cited_ids"] if cited in pairs}
        by = next(
            (later["decision_id"] for later in history[at + 1:] if later["applies"] and any(pairs.get(cited) in own for cited in later["cited_ids"])),
            None,
        )
        if by is None:
            flagged.append(row["decision_id"])
        else:
            answered.append({"decision": row["decision_id"], "by": by})
    step = {"kind": None, "text": None, "ids": [], "context": []}
    if pending:
        step = {"kind": DECIDE, "text": None, "ids": [entry["comparison_id"] for entry in pending], "context": list(flagged)}
    elif flagged:
        step = {"kind": LOOK_AGAIN, "text": NO_LONGER_APPLIES, "ids": list(flagged), "context": []}
    return {
        **step,
        "to_handle": [attempt["attempt_id"] for attempt in attempts if attempt["recoverable"]],
        "flagged": flagged,
        "answered": answered,
    }
