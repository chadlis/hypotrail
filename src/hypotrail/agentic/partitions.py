"""The Partition roles of the tool-using agent Track.

`dev` and `public_check` are protocol vocabulary (GLOSSARY: a Partition has a fixed role in the
protocol; Exposure), defined once, here (ADR 0002, amendment of 2026-11-04). A Workload sets which
file holds the Cases of each role, but it cannot add a role: `workload.schema.json` closes `cases`
to these names. No score is computed on `public_check` Items before the Exposure journal that #9 builds; the Case IDs of
each Partition are read, to check that the Partitions are disjoint.
"""

from hypotrail.core.errors import InvalidInputError

DEV = "dev"
PUBLIC_CHECK = "public_check"
ROLES = (DEV, PUBLIC_CHECK)


def refuse_public_check(workload, case_ids, *, code: str, what: str, stage: str) -> None:
    """Refuse a call whose Items include a `public_check` Case, read from the Workload's declaration.

    The Partition of an Item is the one the Workload declares for its Case, never a label the caller
    passes. Items the declaration does not list (technical scenario Cases) have no Partition and pass.
    The refusal comes before anything is computed or read; it waits for #9's Exposure journal.
    """
    held = sorted({case_id for case_id in case_ids if workload.partition_of(case_id) == PUBLIC_CHECK})
    if held:
        raise InvalidInputError(
            code,
            f"{what} on {PUBLIC_CHECK} Items is refused: no Exposure journal exists yet",
            stage=stage,
            details={"partition": PUBLIC_CHECK, "case_ids": held},
        )
