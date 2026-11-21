"""The Partition roles of the tool-using agent Track.

`dev` and `public_check` are protocol vocabulary (GLOSSARY: a Partition has a fixed role in the
protocol; Exposure), defined once, here (ADR 0002, amendment of 2026-11-04). A Workload sets which
file holds the Cases of each role, but it cannot add a role: `workload.schema.json` closes `cases`
to these names.

`requires_exposure` is the guard of `assess`, which has a Study: it allows both roles and refuses any other Partition.
Counting and rescoring through the library functions, which take no Study and so have no Exposure journal to write to, refuse
`public_check` Items. Inside a Study, `assess` scores and counts them and journals the Exposure (`hypotrail.core.exposure`).
Scoring one answer against one Reference stays allowed (owner decision D2). Building a Workload
reads every declared Cases file in full, to check that the Partitions are disjoint.
"""

from hypotrail.core.errors import InvalidInputError

DEV = "dev"
PUBLIC_CHECK = "public_check"
ROLES = (DEV, PUBLIC_CHECK)


def requires_exposure(partition: str, *, not_dev_code: str, what: str, stage: str) -> bool:
    """The guard of an entry point that has a Study: `dev` and `public_check` are allowed, any other Partition is refused.

    True for `public_check`: the caller records the Exposure in the Study's journal before it computes anything
    on those Items (`hypotrail.core.exposure`).
    """
    if partition == DEV:
        return False
    if partition == PUBLIC_CHECK:
        return True
    raise InvalidInputError(
        not_dev_code,
        f"{what} is computed on {DEV} or {PUBLIC_CHECK} only, not on {partition!r}",
        stage=stage,
        details={"partition": partition},
    )


def refuse_public_check(workload, case_ids, *, code: str, what: str, stage: str) -> None:
    """Refuse a call whose Items include a `public_check` Case, read from the Workload's declaration.

    The Partition of an Item is the one the Workload declares for its Case, never a label the caller
    passes. Items the declaration does not list (technical scenario Cases) have no Partition and pass.
    The refusal comes before anything is computed or read.
    """
    held = sorted({case_id for case_id in case_ids if workload.partition_of(case_id) == PUBLIC_CHECK})
    if held:
        raise InvalidInputError(
            code,
            f"{what} on {PUBLIC_CHECK} Items is refused: this entry point has no Study, so no Exposure journal to record it in",
            stage=stage,
            details={"partition": PUBLIC_CHECK, "case_ids": held},
        )
