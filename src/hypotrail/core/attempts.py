"""What every Track's writer does with an Attempt's manifest: its timestamps, its failure and its read-back.

Shared by `run ml`, `import ml` and `import agent`: the three publish a `running` manifest, then a
terminal one; an error inside the live process leaves a `failed` Attempt, and a replayed request
reads back every artifact its manifest references.
"""

import datetime
from pathlib import Path

from hypotrail.core import artifacts, canonical, contracts
from hypotrail.core.errors import HypotrailError

ITEM_STATUSES = ("produced", "failed", "missing")


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def record_failure(study: Path, manifest_path: str, running: dict, error: Exception) -> None:
    """An error inside this live process: the Attempt is `failed`, with finished_at and a Reason.

    Its published artifacts stay. If even this write fails, the manifest stays `running`: no state
    is invented. The Reason names the error, never a secret: an OS error by its message, a Hypotrail
    error by its code, anything else by its type only.
    """
    if isinstance(error, OSError):
        reason = f"{type(error).__name__}: {error}"
    elif isinstance(error, HypotrailError):
        reason = f"{error.code}: {error.message}"
    else:
        reason = f"unexpected {type(error).__name__}"
    failed = {**running, "technical_status": "failed", "finished_at": now(), "reason": reason}
    try:
        contracts.validate(failed)
        artifacts.replace_bytes(study, manifest_path, canonical.dumps(failed))
    except Exception:
        pass


def verify_recorded(study: Path, manifest: dict) -> None:
    for ref in [*manifest["input_refs"], *manifest.get("output_refs", [])]:
        artifacts.read_verified(study, ref)
