"""`report --study DIR --out FILE`: render the Study's page and publish it by an atomic rename.

The order (nothing is written before the checks that precede it):

1. the Study is read (`STUDY_NOT_FOUND`, exit 2, when there is none), of either Track; `--out` must not be inside the Study, nor a directory, and its folder must exist
   (`REPORT_OUTPUT_INVALID`, exit 2);
2. the records are read, each artifact against its digest (`ARTIFACT_INTEGRITY`, exit 3);
3. a page that shows `public_check` Items is an Exposure (GLOSSARY): under the Study's writer lock (`STUDY_LOCKED`,
   exit 6), `--read-sequence` is compared with the Study's write sequence (`STUDY_CHANGED`, exit 6, or `WRITE_SEQUENCE_AHEAD`, exit 2;
   a page of `dev` Items only is written as without the option), then the freeze record is written first if the revision has none, then one journal entry names the Attempts,
   Assessments and Comparisons the page shows of those Items. A Study with `dev` Items only records nothing and takes no lock;
4. the page is written to a temporary file beside `--out` and renamed onto it; an existing file is replaced.
"""

import os
import uuid
from pathlib import Path

from hypotrail.core import exposure, lock, write_journal
from hypotrail.core import study as layout
from hypotrail.core.errors import InvalidInputError
from hypotrail.report import gather, render

STAGE = "report"
TEMP_SUFFIX = ".tmp"


def _refuse(code, message, **details):
    return InvalidInputError(code, message, stage=STAGE, details=details)


def check_output(study: Path, out: Path) -> None:
    study_root, target = Path(study).resolve(), Path(out).resolve()
    if target == study_root or target.is_relative_to(study_root):
        raise _refuse(
            "REPORT_OUTPUT_INVALID",
            f"--out {out} is inside the Study: the page is rebuilt from the Study and never kept among its records",
            out=str(out),
            reason="inside_study",
        )
    if target.is_dir():
        raise _refuse("REPORT_OUTPUT_INVALID", f"--out {out} is a directory", out=str(out), reason="is_directory")
    if not target.parent.is_dir():
        raise _refuse("REPORT_OUTPUT_INVALID", f"the folder of --out {out} does not exist", out=str(out), reason="no_folder")


def _publish(out: Path, data: bytes) -> None:
    """Temporary file beside `out`, flushed and fsynced, then renamed onto it: an existing file is replaced."""
    target = Path(out)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}{TEMP_SUFFIX}")
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def report(study, out, *, live_basis=None, read_sequence: int | None = None) -> dict:
    """Render the page of `study` at `out`; return what was done (`out`, `sections`, `exposure`).

    `live_basis` is what `exposure.record` calls to digest the Workload; the command passes it, the package imports no Track.
    `read_sequence` is compared with the Study's write sequence only when the page records an Exposure (#108 Tightened F).
    """
    study, out = Path(study), Path(out)
    write_journal.require_valid_read_sequence(read_sequence, "report")
    spec = layout.read_spec(study)
    check_output(study, out)
    model = gather.load(study)
    shown = gather.touched(model)
    entry = None
    links = render.Links(study, out)
    if any(shown.values()):
        with lock.writer_lock(study), write_journal.writing(study, "report"):
            write_journal.require_current(study, read_sequence)
            model = gather.load(study)  # again, under the lock: what the page shows is what the entry names
            shown = gather.touched(model)
            entry = exposure.record(
                study,
                model["spec"],
                live_basis,
                attempt_ids=shown["attempts"],
                assessment_ids=shown["assessments"],
                comparison_ids=shown["comparisons"],
            )
            model["exposure"] = gather.exposure_of(study)  # the count includes this report's own entry
            _publish(out, render.render(model, links, entry).encode("utf-8"))
    else:
        _publish(out, render.render(model, links).encode("utf-8"))
    return {
        "out": str(out),
        "sections": [section_id for section_id, _ in render.SECTIONS],
        "exposure": {"recorded": entry is not None, "entry_id": entry["entry_id"] if entry else None, "journal_entries": len(model["exposure"]["entries"])},
    }
