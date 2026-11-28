"""`report --study DIR --out FILE`: render the Study's page and publish it by an atomic rename.

The order (nothing is written before the checks that precede it):

1. the Study is read (`STUDY_NOT_FOUND`, exit 2, when there is none), of either Track; `--out` must not be inside the Study, nor a directory, and its folder must exist
   (`REPORT_OUTPUT_INVALID`, exit 2);
2. the records are read, each file the page uses against its digest (`ARTIFACT_INTEGRITY`, exit 3); the ranking page uses aggregates;
3. a page that shows `public_check` Items is an Exposure (GLOSSARY): under the Study's writer lock (`STUDY_LOCKED`,
   exit 6), `--read-sequence` is compared with the Study's write sequence (`STUDY_CHANGED`, exit 6, or `WRITE_SEQUENCE_AHEAD`, exit 2;
   a page of `dev` Items only is written as without the option), then the freeze record is written first if the revision has none, then one journal entry names the Attempts,
   Assessments and Comparisons the page shows of those Items. A Study with `dev` Items only records nothing and takes no lock;
4. a protected ranking Study is checked under the writer lock before reading records. Its evaluator report is JSON containing only aggregates and record identifiers;
5. the report is written to a temporary file beside `--out` and renamed onto it by `artifacts.replace_atomically`, which then fsyncs the folder of `--out`; an existing file is replaced.
"""

from pathlib import Path

from hypotrail.core import artifacts, canonical, evaluator, exposure, study_write
from hypotrail.core import study as layout
from hypotrail.core.errors import InvalidInputError
from hypotrail.report import gather, render

STAGE = "report"


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


def _result(out, spec, model, entry) -> dict:
    return {
        "out": str(out),
        "sections": [section_id for section_id, _ in render.sections_of(spec["domain"])],
        "exposure": {"recorded": entry is not None, "entry_id": entry["entry_id"] if entry else None, "journal_entries": len(model["exposure"]["entries"])},
    }


def report(study, out, *, live_basis=None, read_sequence: int | None = None, profile=None, run_tool: bool = False) -> dict:
    """Publish the Study report at `out`; return the evaluator aggregates or the ordinary page metadata.

    `live_basis` is what `exposure.record` calls to digest the Workload; the command passes it, the package imports no Track.
    `profile` is what the page of a regression Study draws in its Data profile section: a function of the Study's folder that
    returns the Track's read (`ok` true) or its refusal's code (`ok` false); the command passes it, and it is called once.
    Direct CLI reports check `read_sequence` only when the page records an Exposure (#108 Tightened F). A guarded report
    checks the sequence and establishes its scope under the writer lock before gathering.
    """
    study, out = Path(study), Path(out)
    study_write.check_read_sequence(study_write.REPORT, read_sequence)
    spec = layout.read_spec(study)
    protected = evaluator.is_protected(spec) or evaluator.inside()
    if not protected:
        check_output(study, out)
    entry = None
    links = None if protected else render.Links(study, out)
    drawn = None
    if not run_tool and not protected:
        model = gather.load(study)
        shown = gather.touched(model)
        drawn = profile(study) if profile is not None and spec["domain"] == gather.REGRESSION else None
        model["profile"] = drawn
        if not any(shown.values()):
            artifacts.replace_atomically(out, render.render(model, links).encode("utf-8"))
            return _result(out, spec, model, entry)

    with study_write.locked(study, study_write.REPORT, read_sequence=read_sequence) as write:
        write.require_current()
        model = gather.load(study, guarded=run_tool, profile=profile if run_tool else None)
        if not run_tool and not protected:
            model["profile"] = drawn
            shown = gather.touched(model)
            entry = exposure.record(
                study,
                write,
                model["spec"],
                live_basis,
                attempt_ids=shown["attempts"],
                assessment_ids=shown["assessments"],
                comparison_ids=shown["comparisons"],
            )
            model["exposure"] = gather.exposure_of(study)  # the count includes this report's own entry
        if protected:
            check_output(study, out)
            artifacts.replace_atomically(out, canonical.dumps(model))
            return model
        artifacts.replace_atomically(out, render.render(model, links, entry).encode("utf-8"))
    return _result(out, model["spec"] if run_tool else spec, model, entry)
