"""Shared by the checks of the `figures` read: running it, the Studies it is checked on, and the copies of a Study whose files a case
changes. No model is called: the Chinook sides are Imports of the kit's answers."""

import csv
import io
import json
from pathlib import Path

from _client_helpers import FIGURES_STUDIES, bike_withheld_study, compared_study, rescored_study, result_changed_study
from _compare_helpers import assessed
from _review_helpers import copy_of
from _study_helpers import run_cli

from hypotrail.core import canonical


def refused_constant(name):
    raise AssertionError(f"the read printed a non-finite number: {name}")


def strict(text: str) -> dict:
    """The one JSON object of `text`, refusing `NaN`, `Infinity` and `-Infinity`."""
    return json.loads(text, parse_constant=refused_constant)


def figures(study) -> tuple:
    """(exit code, the object of the read, stderr) of `figures --study=DIR --json`."""
    code, out, err = run_cli("figures", f"--study={study}", "--json")
    return code, strict(out), err


def the_comparison(study) -> Path:
    """The folder of the Study's one Comparison."""
    [folder] = [p for p in (Path(study) / "comparisons").iterdir() if p.is_dir()]
    return folder


def rows_of(text: str) -> list:
    return list(csv.reader(io.StringIO(text)))


def text_of(rows) -> str:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue()


def rewritten(study, rows, *, matching_record=True) -> Path:
    """The Study with its one Comparison's `paired_deltas.csv` replaced by `rows`; with `matching_record`, the record's `paired_deltas_ref`
    digest and size are set to the new bytes."""
    folder = the_comparison(study)
    data = text_of(rows).encode("utf-8")
    (folder / "paired_deltas.csv").write_bytes(data)
    if matching_record:
        record = json.loads((folder / "comparison.json").read_text(encoding="utf-8"))
        record["paired_deltas_ref"] = {**record["paired_deltas_ref"], "sha256": canonical.sha256_hex(data), "size_bytes": len(data)}
        (folder / "comparison.json").write_bytes(canonical.dumps(record))
    return study


def edited(study, edit, **options) -> Path:
    """The Study with `edit` applied to the rows of its one Comparison's `paired_deltas.csv` (header first)."""
    rows = rows_of((the_comparison(study) / "paired_deltas.csv").read_text(encoding="utf-8"))
    return rewritten(study, edit(rows), **options)


def set_cell(row: int, column: int, value: str):
    def edit(rows):
        rows[row][column] = value
        return rows

    return edit


def removed_paired_file(study) -> Path:
    (the_comparison(study) / "paired_deltas.csv").unlink()
    return study


def one_byte_changed(study) -> Path:
    path = the_comparison(study) / "paired_deltas.csv"
    data = bytearray(path.read_bytes())
    data[-2] = ord("9") if data[-2] != ord("9") else ord("8")
    path.write_bytes(bytes(data))
    return study


def two_assessments_no_comparison(tmp_path) -> Path:
    study, _, _ = assessed(tmp_path, "seasonal_7", "ridge_v1")
    return study


# The cases of the read on a Study whose Comparison's figures cannot be given, each with the reason its entry holds, and the cases of a
# Comparison of an earlier Study revision. Each is made from one built Study: (the name of the Study it is made from, the change).
COMPARED_CASES = {
    "7-paired-deltas-removed": (removed_paired_file, "artifact_missing"),
    "8-one-byte-changed": (one_byte_changed, "artifact_integrity"),
    "9-column-renamed": (lambda s: edited(s, set_cell(0, 1, "control_error")), "artifact_malformed"),
    "10-cell-abc": (lambda s: edited(s, set_cell(1, 3, "abc")), "artifact_malformed"),
    "11-header-alone": (lambda s: edited(s, lambda rows: rows[:1]), "artifact_malformed"),
    "12-cell-inf": (lambda s: edited(s, set_cell(1, 3, "inf")), "value_not_finite"),
    "13-cell-nan": (lambda s: edited(s, set_cell(1, 3, "nan")), "value_not_finite"),
    "14-range-overflows": (lambda s: edited(s, lambda rows: set_cell(2, 3, "1.7e308")(set_cell(1, 3, "-1.7e308")(rows))), "value_not_finite"),
}


def built_cases(tmp_path) -> dict:
    """{case: (Study, the reason its one entry holds, or None)} for cases (6) to (17), each made under `tmp_path`."""
    for name in ("compared", "withheld", "no-comparison", "rescored", "result-changed"):
        (tmp_path / name).mkdir(parents=True)
    compared = compared_study(tmp_path / "compared")
    withheld = bike_withheld_study(tmp_path / "withheld")
    cases = {"6-no-comparison": (two_assessments_no_comparison(tmp_path / "no-comparison"), None)}
    for name, (change, reason) in COMPARED_CASES.items():
        cases[name] = (change(copy_of(compared, tmp_path / name)), reason)
    cases["15-withheld-file-removed"] = (removed_paired_file(copy_of(withheld, tmp_path / "15")), "delta_withheld")
    cases["16-rescored"] = (rescored_study(tmp_path / "rescored"), None)
    cases["17-result-changed"] = (result_changed_study(tmp_path / "result-changed"), None)
    return cases


def built_studies(tmp_path) -> dict:
    """{name: Study} of the fixture Studies of the read, each made under `tmp_path`."""
    studies = {}
    for name, make in FIGURES_STUDIES.items():
        (tmp_path / name).mkdir(parents=True)
        studies[name] = make(tmp_path / name)
    return studies


def key_paths(value, prefix="") -> set:
    """The paths of the leaves of `value`, in the form of `key_paths`: `.` between keys, `[]` for a list element."""
    if isinstance(value, dict):
        return {path for key, item in value.items() for path in key_paths(item, f"{prefix}.{key}" if prefix else key)}
    if isinstance(value, list):
        return {path for item in value for path in key_paths(item, f"{prefix}[]")}
    return {prefix}


def leaf_paths(payloads) -> set:
    """The leaf paths printed over `payloads`: a path printed with null that is a container in another payload is not a leaf."""
    found = set().union(*(key_paths(payload) for payload in payloads))
    return {path for path in found if not any(other.startswith((f"{path}.", f"{path}[]")) for other in found)}
