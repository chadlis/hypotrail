"""`figures --study=DIR --json`: for each Comparison of a Study, the lines of its `paired_deltas.csv`, and the bins and the five numbers of a
box that the core computes from its paired deltas, or the reason why its entry holds none. It takes no lock and writes nothing.

No model is called: the Chinook sides are Imports of the kit's answers.
"""

import builtins
import csv
import io
import json
import math
import os
from pathlib import Path

import pytest
from _client_helpers import FIGURES_STUDIES
from _figures_helpers import built_cases, built_studies, copy_of, edited, figures, set_cell, strict
from _review_helpers import exposure_count, files, status
from _study_helpers import run_cli
from test_study_lock import held_by_another_process

from hypotrail.core import canonical
from hypotrail.core import figures as module

ENTRY_KEYS = ["comparison_id", "unavailable", "paired_deltas", "histogram", "quartiles"]
FIGURE_KEYS = ("paired_deltas", "histogram", "quartiles")
REASONS = ("delta_withheld", "artifact_missing", "artifact_integrity", "artifact_malformed", "value_not_finite")


@pytest.fixture(scope="module")
def studies(tmp_path_factory):
    return built_studies(tmp_path_factory.mktemp("figures-studies"))


@pytest.fixture(scope="module")
def cases(tmp_path_factory):
    return built_cases(tmp_path_factory.mktemp("figures-cases"))


@pytest.fixture(scope="module")
def reads(studies):
    """{name: the object of the read} of each fixture Study."""
    made = {}
    for name, study in studies.items():
        code, payload, err = figures(study)
        assert code == 0, (name, payload, err)
        made[name] = payload
    return made


def paired_rows(study, comparison) -> tuple:
    """(header, data rows) of the `paired_deltas.csv` a Comparison record names."""
    text = (Path(study) / comparison["paired_deltas_ref"]["path"]).read_text(encoding="utf-8")
    header, *rows = csv.reader(io.StringIO(text))
    return header, rows


def assert_equal_to_the_file(study, payload):
    """Each entry whose `unavailable` is null holds its Comparison's `paired_deltas.csv`, line by line, both ways; returns the entries compared."""
    records = {record["comparison_id"]: record for record in status(study)["comparisons"]}
    compared = 0
    for entry in payload["comparisons"]:
        if entry["unavailable"] is not None:
            continue
        header, rows = paired_rows(study, records[entry["comparison_id"]])
        assert len(entry["paired_deltas"]) == len(rows), entry["comparison_id"]
        for element, row in zip(entry["paired_deltas"], rows):
            assert list(element) == header
            expected = {name: cell if index == 0 else (int(cell) if name == "repeats" else float(cell)) for index, (name, cell) in enumerate(zip(header, row))}
            assert element == expected
            assert all(type(element[name]) is type(expected[name]) for name in header)
        compared += 1
    return compared


# --- the fixture Studies --------------------------------------------------------------------------------------------------


def test_the_public_check_compared_study_records_an_exposure_and_status_lists_a_comparison_on_public_check(studies):
    study = studies["public-check-compared"]
    assert exposure_count(study) > 0
    [comparison] = status(study)["comparisons"]
    population = json.loads((Path(study) / comparison["population_ref"]["path"]).read_text(encoding="utf-8"))
    assert population["partition"] == "public_check"


def test_the_chinook_spread_study_holds_at_least_two_distinct_delta_share_values_and_a_delta_with_a_value(studies):
    study = studies["chinook-spread"]
    [comparison] = status(study)["comparisons"]
    header, rows = paired_rows(study, comparison)
    assert len({row[header.index("delta_share")] for row in rows}) >= 2
    assert comparison["delta"]["value"] is not None


# --- the read writes nothing ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(FIGURES_STUDIES))
def test_the_read_writes_nothing_keeps_the_write_sequence_and_answers_while_another_writer_holds_the_lock(studies, name):
    study = studies[name]
    before, sequence = files(study), status(study)["write_sequence"]
    code, payload, err = figures(study)
    assert code == 0 and payload["ok"] is True, (payload, err)
    assert files(study) == before
    assert status(study)["write_sequence"] == sequence
    with held_by_another_process(study):
        code, payload, err = figures(study)
    assert code == 0 and payload["ok"] is True, (payload, err)
    assert files(study) == before


# --- the envelope and the entries ---------------------------------------------------------------------------------------------


def test_the_write_sequence_of_the_read_is_the_one_status_shows(studies, reads):
    for name, study in studies.items():
        assert reads[name]["write_sequence"] == status(study)["write_sequence"], name


def test_the_read_holds_one_entry_per_comparison_in_the_order_status_lists_them(studies, reads):
    assert len(reads["several-pending"]["comparisons"]) == 2
    for name, study in studies.items():
        assert [entry["comparison_id"] for entry in reads[name]["comparisons"]] == [c["comparison_id"] for c in status(study)["comparisons"]], name


def test_the_envelope_holds_ok_the_write_sequence_and_the_entries_only(reads):
    for name, payload in reads.items():
        assert list(payload) == ["ok", "write_sequence", "comparisons"], name


def test_every_entry_holds_its_five_keys_and_its_three_figure_keys_are_null_exactly_when_it_holds_a_reason(reads, cases):
    payloads = dict(reads)
    for name, (study, _) in cases.items():
        code, payload, err = figures(study)
        assert code == 0, (name, payload, err)
        payloads[name] = payload
    entries = [(name, entry) for name, payload in payloads.items() for entry in payload["comparisons"]]
    assert {entry["unavailable"] for _, entry in entries} == {None, *REASONS}  # every reason is met over these Studies
    for name, entry in entries:
        assert list(entry) == ENTRY_KEYS, name
        assert entry["unavailable"] is None or entry["unavailable"] in REASONS, name
        assert [entry[key] is None for key in FIGURE_KEYS] == [entry["unavailable"] is not None] * 3, (name, entry["unavailable"])


def test_no_read_prints_a_non_finite_number(studies, cases):
    for name, study in [*studies.items(), *((n, s) for n, (s, _) in cases.items())]:
        code, out, err = run_cli("figures", f"--study={study}", "--json")
        assert code == 0, (name, out, err)
        strict(out)


# --- the values per Item and per Case ------------------------------------------------------------------------------------------


def test_each_entry_with_figures_holds_the_lines_of_its_paired_deltas_file_in_order_with_its_column_names(studies, reads):
    compared = {name: assert_equal_to_the_file(study, reads[name]) for name, study in studies.items()}
    assert compared["public-check-compared"] == 1 and compared["chinook-spread"] == 1 and compared["several-pending"] == 2


def test_on_the_agent_track_repeats_is_printed_as_an_integer(reads):
    [entry] = reads["chinook-spread"]["comparisons"]
    assert [type(element["repeats"]) for element in entry["paired_deltas"]] == [int] * 4


class Opened:
    """Records each path opened through `builtins.open`, `io.open` or `os.open` while armed."""

    def __init__(self, monkeypatch):
        self.paths = set()
        for owner in (builtins, io, os):
            monkeypatch.setattr(owner, "open", self.recording(owner.open))

    def recording(self, real):
        def wrapper(file, *args, **kwargs):
            if not isinstance(file, int):
                self.paths.add(Path(os.fsdecode(file)).resolve())
            return real(file, *args, **kwargs)

        return wrapper

    def under(self, study) -> set:
        root = Path(study).resolve()
        return {path.relative_to(root).as_posix() for path in self.paths if path.is_relative_to(root)}


def opened_by(monkeypatch, *args) -> tuple:
    """(the paths the command opened, its exit code), the command run in this process with the three open functions recording."""
    with monkeypatch.context() as patch:
        recorder = Opened(patch)
        code, _, _ = run_cli(*args)
    return recorder, code


@pytest.mark.parametrize("name", list(FIGURES_STUDIES))
def test_the_read_opens_no_file_beyond_those_status_opens_but_the_paired_deltas_of_each_comparison_whose_delta_is_not_withheld(studies, name, monkeypatch):
    """The listing is bounded by its conventions: it sees a file the read opens in its own process through `builtins.open`, `io.open` or
    `os.open`; a file opened another way escapes it."""
    study = studies[name]
    expected = {c["paired_deltas_ref"]["path"] for c in status(study)["comparisons"] if c["delta"]["value"] is not None}
    by_status, _ = opened_by(monkeypatch, "status", f"--study={study}", "--json")
    by_figures, code = opened_by(monkeypatch, "figures", f"--study={study}", "--json")
    assert code == 0
    assert by_figures.under(study) - by_status.under(study) == expected


def test_nothing_of_the_attempt_on_public_check_that_no_assessment_assessed_reaches_the_read(studies):
    study = studies["public-check"]
    [attempt] = [a for a in status(study)["attempts"] if a["request_id"] == "ml-public_check-seasonal_7"]
    code, out, err = run_cli("figures", f"--study={study}", "--json")
    assert code == 0, (out, err)
    strings = [attempt["attempt_id"], attempt["request_id"], *(artifact["path"] for artifact in attempt["artifacts"])]
    assert len(strings) > 2
    assert [text for text in strings if text in out] == []


# --- the numbers the core computes ------------------------------------------------------------------------------------------


def numbers(values) -> dict:
    return module.figures_of([float(v) for v in values])


def test_one_value_gives_five_equal_numbers_and_one_bin_of_count_one():
    """n = 1: every quantile position (n - 1)p is 0, so each of the five numbers is the value; one bin, low = high = 2.5, count 1."""
    assert numbers([2.5]) == {"unavailable": None, "histogram": [{"low": 2.5, "high": 2.5, "count": 1}], "quartiles": dict.fromkeys(["min", "q1", "median", "q3", "max"], 2.5)}


def test_four_values_all_zero_give_five_zeros_and_one_bin_of_count_four():
    """All values equal: the five numbers are that value, 0.0, and there is one bin with low = high = 0.0 and count 4."""
    assert numbers([0.0] * 4) == {"unavailable": None, "histogram": [{"low": 0.0, "high": 0.0, "count": 4}], "quartiles": dict.fromkeys(["min", "q1", "median", "q3", "max"], 0.0)}


def test_182_values_all_1e308_give_five_1e308_and_one_bin_and_no_inf():
    """All equal: the five numbers are 1e308 and one bin [1e308, 1e308] holds 182; no number overflows."""
    result = numbers([1e308] * 182)
    assert result == {"unavailable": None, "histogram": [{"low": 1e308, "high": 1e308, "count": 182}], "quartiles": dict.fromkeys(["min", "q1", "median", "q3", "max"], 1e308)}
    assert "Infinity" not in json.dumps(result)


def test_an_odd_count_gives_the_quartiles_by_linear_interpolation():
    """Sorted 1, 2, 4, 8, 16 (n = 5): positions (n - 1)p = 1, 2, 3 are whole, so q1 = 2, median = 4, q3 = 8; min 1, max 16.
    Bins: ceil(log2 5) + 1 = 4, width (16 - 1) / 4 = 3.75, edges 1, 4.75, 8.5, 12.25, 16: counts 3 (1, 2, 4), 1 (8), 0, 1 (16)."""
    result = numbers([8, 1, 16, 4, 2])
    assert result["quartiles"] == {"min": 1.0, "q1": 2.0, "median": 4.0, "q3": 8.0, "max": 16.0}
    assert result["histogram"] == [{"low": 1.0, "high": 4.75, "count": 3}, {"low": 4.75, "high": 8.5, "count": 1}, {"low": 8.5, "high": 12.25, "count": 0}, {"low": 12.25, "high": 16.0, "count": 1}]


def test_an_even_count_gives_the_quartiles_by_linear_interpolation():
    """Sorted 0, 1, 2, 10 (n = 4): q1 at 0.75 = 0(0.25) + 1(0.75) = 0.75; median at 1.5 = 1(0.5) + 2(0.5) = 1.5; q3 at 2.25 = 2(0.75) + 10(0.25) = 4.0.
    Bins: ceil(log2 4) + 1 = 3, width 10 / 3, edges 0, 10/3, 20/3, 10: counts 3 (0, 1, 2), 0, 1 (10)."""
    result = numbers([10, 0, 2, 1])
    assert result["quartiles"] == {"min": 0.0, "q1": 0.75, "median": 1.5, "q3": 4.0, "max": 10.0}
    assert [b["count"] for b in result["histogram"]] == [3, 0, 1]
    assert [b["low"] for b in result["histogram"]] == [0.0, 0.0 + 1 * (10.0 / 3), 0.0 + 2 * (10.0 / 3)]
    assert result["histogram"][-1]["high"] == 10.0


def test_a_value_equal_to_an_inner_edge_is_counted_in_the_bin_it_opens():
    """Values 0, 1, 2, 3, 4 (n = 5): 4 bins of width 1, edges 0, 1, 2, 3, 4; the value 1 equals the low of the second bin and is counted there,
    as 2 and 3 are in the third and fourth: counts 1, 1, 1, 2."""
    result = numbers([0, 1, 2, 3, 4])
    assert [(b["low"], b["high"], b["count"]) for b in result["histogram"]] == [(0.0, 1.0, 1), (1.0, 2.0, 1), (2.0, 3.0, 1), (3.0, 4.0, 2)]


def test_the_maximum_is_counted_in_the_last_bin():
    """Values 0 and 1 (n = 2): 2 bins, edges 0, 0.5, 1; the maximum 1 equals the last high and is counted in the last bin: counts 1, 1."""
    result = numbers([1, 0])
    assert result["histogram"] == [{"low": 0.0, "high": 0.5, "count": 1}, {"low": 0.5, "high": 1.0, "count": 1}]


@pytest.mark.parametrize(("count", "bins"), [(2, 2), (3, 3), (5, 4), (9, 5)])
def test_the_bin_count_is_sturges_the_last_high_is_the_maximum_and_each_value_is_counted_against_the_printed_edges(count, bins):
    """ceil(log2 n) + 1: n = 2 gives 1 + 1; n = 3 gives 2 + 1; n = 5 gives 3 + 1; n = 9 gives 4 + 1. Values 0.1 × k² for k = 0..n−1."""
    values = [0.1 * k * k for k in range(count)]
    histogram = numbers(values)["histogram"]
    assert len(histogram) == bins
    assert histogram[0]["low"] == min(values) and histogram[-1]["high"] == max(values)
    for index, bin_ in enumerate(histogram):
        last = index == len(histogram) - 1
        assert bin_["count"] == sum(1 for v in values if bin_["low"] <= v and (v <= bin_["high"] if last else v < bin_["high"]))


@pytest.mark.parametrize("values", [[1.0, math.inf], [math.nan, 2.0], [-1.7e308, 1.7e308]], ids=["inf", "nan", "range-overflows"])
def test_a_value_that_is_not_finite_or_a_range_that_overflows_gives_value_not_finite_and_no_number(values):
    assert module.figures_of(values) == {"unavailable": "value_not_finite", "histogram": None, "quartiles": None}


def independent(values) -> dict:
    """The bins and the five numbers by the definitions of handbook chapter 17, written here without the module's functions."""
    s, n = sorted(values), len(values)
    if s[0] == s[-1]:
        return {"histogram": [{"low": s[0], "high": s[0], "count": n}], "quartiles": dict.fromkeys(["min", "q1", "median", "q3", "max"], s[0])}

    def quantile(p):
        position = (n - 1) * p
        lower = math.floor(position)
        t = position - lower
        a, b = s[lower], s[min(lower + 1, n - 1)]
        return a * (1 - t) + b * t

    bins = math.ceil(math.log2(n)) + 1
    edges = [s[0], *(s[0] + k * ((s[-1] - s[0]) / bins) for k in range(1, bins)), s[-1]]
    counts = [0] * bins
    for v in s:
        counts[next(i for i in range(bins) if edges[i] <= v and (v <= edges[i + 1] if i == bins - 1 else v < edges[i + 1]))] += 1
    return {
        "histogram": [{"low": edges[i], "high": edges[i + 1], "count": counts[i]} for i in range(bins)],
        "quartiles": {"min": s[0], "q1": quantile(0.25), "median": quantile(0.5), "q3": quantile(0.75), "max": s[-1]},
    }


def test_on_the_fixture_studies_each_entry_holds_the_numbers_of_an_independent_computation_on_its_paired_deltas(reads):
    checked = 0
    for name, payload in reads.items():
        for entry in payload["comparisons"]:
            if entry["unavailable"] is not None:
                continue
            column = "delta_share" if "case_id" in entry["paired_deltas"][0] else "delta_abs_error"
            expected = independent([element[column] for element in entry["paired_deltas"]])
            assert (entry["histogram"], entry["quartiles"]) == (expected["histogram"], expected["quartiles"]), (name, entry["comparison_id"])
            checked += 1
    assert checked >= 7


# --- a withheld delta, and the Agent Track ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "reason"),
    [("bike-withheld", "delta_withheld"), ("chinook-withheld", "delta_withheld"), ("chinook-pending", None), ("chinook-spread", None)],
)
def test_an_entry_whose_delta_is_withheld_holds_delta_withheld_and_the_agent_comparisons_are_carried_per_case(reads, name, reason):
    [entry] = reads[name]["comparisons"]
    assert entry["unavailable"] == reason
    assert [entry[key] is None for key in FIGURE_KEYS] == [reason is not None] * 3
    if reason is None:
        assert [element["case_id"] for element in entry["paired_deltas"]] == ["D01", "D03", "D07", "D08"]


# --- what the read refuses, and what it marks -----------------------------------------------------------------------------------


def refusal(*args) -> tuple:
    """(exit code, the error's code, its stage) of a command; an answer with `ok` true gives (0, None, None)."""
    code, out, err = run_cli(*args)
    error = json.loads(out).get("error", {})
    return code, error.get("code"), error.get("stage")


@pytest.mark.parametrize("case", ["1-no-folder", "2-a-file", "3-no-study-json", "4-schema-refused", "5-no-study-flag"])
def test_the_read_refuses_the_study_where_status_refuses_it_with_the_same_code_and_opens_no_comparison_file(case, tmp_path, monkeypatch, studies):
    target = tmp_path / "study"
    if case == "2-a-file":
        target.write_text("not a Study\n", encoding="utf-8")
    elif case == "3-no-study-json":
        target.mkdir()
    elif case == "4-schema-refused":
        copy_of(studies["compared"], target)
        spec = json.loads((target / "study.json").read_text(encoding="utf-8"))
        del spec["workload"]
        (target / "study.json").write_bytes(canonical.dumps(spec))
    flags = [] if case == "5-no-study-flag" else [f"--study={target}"]
    before = files(target) if target.is_dir() else None
    by_figures, _ = opened_by(monkeypatch, "figures", *flags, "--json")
    refused = refusal("figures", *flags, "--json")
    assert refused == refusal("status", *flags, "--json")
    if case.startswith(("1-", "2-", "3-")):
        assert refused == (2, "STUDY_NOT_FOUND", "study")
    assert [path for path in by_figures.under(tmp_path) if "comparisons/" in path] == []
    if before is not None:
        assert files(target) == before


def unreadable(path: Path) -> None:
    """The record at `path` stripped of its `kind`, which the contract schema requires, so that reading it refuses."""
    record = json.loads(path.read_text(encoding="utf-8"))
    del record["kind"]
    path.write_bytes(canonical.dumps(record))


def status_refusal(case: str, tmp_path: Path, studies: dict) -> list:
    """The arguments, after the command, of a Study `status` refuses: the cases the tests of `status` make (tests/test_study_lock.py,
    tests/test_handbook.py and the five above), and a copy of `compared_study` with one record `status` reads made unreadable."""
    if case == "no-study-flag":
        return []
    if case in ("no-folder", "unknown-flag"):
        return [f"--study={tmp_path / 'none'}", *(["--bogus"] if case == "unknown-flag" else [])]
    study = tmp_path / "study"
    if case == "a-file":
        study.write_text("not a Study\n", encoding="utf-8")
    elif case == "no-study-json":
        study.mkdir()
    else:
        copy_of(studies["compared"], study)
        unreadable(sorted(study.glob(case))[0])
    return [f"--study={study}"]


@pytest.mark.parametrize(
    "case",
    ["no-folder", "a-file", "no-study-json", "no-study-flag", "unknown-flag", "study.json", "attempts/*/attempt.json", "assessments/*/assessment.json"],
)
def test_the_read_refuses_every_study_status_refuses_with_the_same_exit_code_and_stage(case, tmp_path, studies):
    flags = status_refusal(case, tmp_path, studies)
    by_status = refusal("status", *flags, "--json")
    assert by_status[0] != 0, by_status
    assert refusal("figures", *flags, "--json") == by_status


EXPECTED = {
    "6-no-comparison": None,
    "7-paired-deltas-removed": "artifact_missing",
    "8-one-byte-changed": "artifact_integrity",
    "9-column-renamed": "artifact_malformed",
    "10-cell-abc": "artifact_malformed",
    "11-header-alone": "artifact_malformed",
    "12-cell-inf": "value_not_finite",
    "13-cell-nan": "value_not_finite",
    "14-range-overflows": "value_not_finite",
    "15-withheld-file-removed": "delta_withheld",
    "16-rescored": None,
    "17-result-changed": None,
}


@pytest.mark.parametrize("case", list(EXPECTED))
def test_a_comparison_whose_figures_cannot_be_given_holds_the_first_reason_that_applies_and_the_read_gives_ok_true(case, cases):
    study, _ = cases[case]
    before = files(study)
    code, payload, err = figures(study)
    assert code == 0 and payload["ok"] is True, (payload, err)
    assert files(study) == before
    if case == "6-no-comparison":
        assert payload["comparisons"] == []
    elif case.startswith(("16-", "17-")):
        assert assert_equal_to_the_file(study, payload) == len(payload["comparisons"]) == 1
    else:
        [entry] = payload["comparisons"]
        assert entry["unavailable"] == EXPECTED[case]


# --- the open points of a line of the file: its cells, its ids, `repeats` -------------------------------------------------------


@pytest.fixture
def compared_copy(studies, tmp_path):
    return copy_of(studies["compared"], tmp_path / "study")


@pytest.mark.parametrize(("edit", "reason"), [("fewer-cells", "artifact_malformed"), ("more-cells", "artifact_malformed")])
def test_a_line_with_fewer_or_more_cells_than_the_header_gives_artifact_malformed(compared_copy, edit, reason):
    edited(compared_copy, lambda rows: [*rows[:1], rows[1][:-1] if edit == "fewer-cells" else [*rows[1], "0.0"], *rows[2:]])
    [entry] = figures(compared_copy)[1]["comparisons"]
    assert entry["unavailable"] == reason


def test_an_empty_id_and_a_repeated_id_are_carried_as_recorded(compared_copy):
    edited(compared_copy, lambda rows: [rows[0], ["", *rows[1][1:]], rows[2], rows[2], *rows[3:]])
    [entry] = figures(compared_copy)[1]["comparisons"]
    assert entry["unavailable"] is None
    ids = [element["row_id"] for element in entry["paired_deltas"]]
    assert ids[0] == "" and ids[1] == ids[2]
    assert assert_equal_to_the_file(compared_copy, figures(compared_copy)[1]) == 1


def test_a_repeats_cell_that_float_parses_but_is_not_whole_is_printed_as_its_number(studies, tmp_path):
    study = copy_of(studies["chinook-spread"], tmp_path / "study")
    edited(study, set_cell(1, 1, "1.5"))
    [entry] = figures(study)[1]["comparisons"]
    assert entry["unavailable"] is None
    assert entry["paired_deltas"][0]["repeats"] == 1.5 and [type(e["repeats"]) for e in entry["paired_deltas"]] == [float, int, int, int]


# --- the human form ---------------------------------------------------------------------------------------------------------


def test_without_json_the_read_prints_one_line_per_comparison_with_its_id_and_its_count_of_pairs_and_five_numbers_or_its_reason(studies, reads):
    for name, study in studies.items():
        code, out, err = run_cli("figures", f"--study={study}")
        assert code == 0, (name, out, err)
        lines = out.splitlines()
        assert len(lines) == len(reads[name]["comparisons"]), name
        for line, entry in zip(lines, reads[name]["comparisons"]):
            assert entry["comparison_id"] in line, name
            if entry["unavailable"] is None:
                assert f"{len(entry['paired_deltas'])} pairs" in line, line
                for key, value in entry["quartiles"].items():
                    assert f"{key} {value:.6g}" in line, (key, line)
            else:
                assert entry["unavailable"] in line, line


def test_without_json_a_study_with_no_comparison_prints_one_line_that_says_so(cases):
    study, _ = cases["6-no-comparison"]
    code, out, err = run_cli("figures", f"--study={study}")
    assert (code, out) == (0, "no Comparison in this Study\n"), err
