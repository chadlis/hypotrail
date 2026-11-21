"""The Partition roles of the temporal regression Track.

`train`, `dev` and `public_check` are protocol vocabulary (GLOSSARY: a Partition has
a fixed role in the protocol; Exposure), defined once, here. Everything else about
Partitions is the Workload's: how many there are besides these, and their date ranges.
Fitting is always on `train`; metrics and Comparisons are computed on `dev`;
`public_check` is touched only through the Exposure journal (SPEC section 2): inside a Study (`requires_exposure`),
and nowhere else (`require_dev`).
"""

from hypotrail.core.errors import InvalidInputError

TRAIN = "train"
DEV = "dev"
PUBLIC_CHECK = "public_check"
ROLES = (TRAIN, DEV, PUBLIC_CHECK)


def require_dev(partition: str, *, public_check_code: str, not_dev_code: str, what: str, stage: str) -> None:
    """The one guard on the Partition a metric or a Comparison is computed on: `dev` only.

    `public_check` has its own code (it waits for the Exposure journal); any other
    Partition is refused with `not_dev_code`.
    """
    if partition == DEV:
        return
    if partition == PUBLIC_CHECK:
        raise InvalidInputError(
            public_check_code,
            f"{what} on {PUBLIC_CHECK} is refused: this entry point has no Study, so no Exposure journal to record it in",
            stage=stage,
            details={"partition": partition},
        )
    raise InvalidInputError(
        not_dev_code, f"{what} is computed on {DEV} only, not on {partition!r}", stage=stage, details={"partition": partition}
    )


def requires_exposure(partition: str, *, not_dev_code: str, what: str, stage: str) -> bool:
    """The guard of an entry point that has a Study: `dev` and `public_check` are allowed, any other Partition is refused.

    True for `public_check`: the caller records the Exposure in the Study's journal before it computes anything
    on those Items (`hypotrail.core.exposure`). An entry point with no Study uses `require_dev` and keeps its refusal.
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
