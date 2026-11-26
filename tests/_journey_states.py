"""The journey the panel mockups v2 show, driven in scratch folders, and the reads `clients/vscode/test/cli/journey/` keeps of it.

The mockups v2 are kept in chadlis/hypotrail-learning, `notes/refonte-panneau/maquettes-v2/` (`83ffa12`); their data keeps, for each real
state, the command list that made it. `drive` gives those commands again, in a work folder: one Bike Study through states 00 to 18, a
duplicate of the Bike Study at state 18 driven to state 19 (two interrupted Attempts), and one Chinook Study through states 30 to 33. Both
Studies are given a copy of `examples/` as `--examples-dir`, as the mockups' `demo-examples`, so that states 07 and 08 edit the copy with
`docs/demo/edit_copy.py` and never a Reference of the repository. Each id a command takes is read from the Study's files or from the output
of the command that wrote it, as `tests/_kept_studies.py` does. States 17 and 19 kill the writer of a `run ml` once its running manifest is
published, the pattern of `tests/test_run_ml.py::killed`; state 32 imports the Inspect log of the paid Attempt of 2026-11-20 that the repository keeps, read
in place.

No command calls a live model or the network: `run agent` is given the Mode `scripted_fixture` only, and the killed writer is started
without the live key in its environment.

After each state, `status --since 0 --json` is read, and `figures --json` when the state holds a Comparison. Each read is kept as three
files, `<NN>-<name>.<read>.exit`, `.out` and `.err`, with the scratch folders replaced by `SCRATCH` and, when its `ok` is true, its values
replaced as `tests/_client_helpers.py::replaced` replaces them, with one numbering per Study over its reads in the order they are taken;
the name of an Inspect log (a timestamp and a random suffix) becomes `LOG.eval` first, the rule of `tests/_kept_studies.py`, and the
`code` of each freeze record takes a fixed value (`FIXED_FREEZE_CODE`).
The duplicate of state 19 holds the Bike Study (the same `study_id` and records), so its reads go on with the Bike Study's numbering.
State 00 is a read in a folder that holds no Study: the refusal names no scratch folder and is kept as printed.
"""

import contextlib
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from _assess_helpers import observation_set_id, references_id
from _client_helpers import KEPT, replaced
from _kept_studies import LOG_NAME
from _study_helpers import EXAMPLES, ROOT, run_cli

JOURNEY_KEPT = KEPT / "journey"
EDIT_COPY = ROOT / "docs" / "demo" / "edit_copy.py"
TRACE = ROOT / "docs" / "handbook" / "traces" / "run-agent-live-plain" / "inspect" / "2026-11-20T21-46-56-00-00_chinook-plain_e5SoHDfMBV3vBUjsjaQWVu.eval"
POPULATION = '{"episodes": [{"case_id": "D03", "repeat": 0}, {"case_id": "D05", "repeat": 0}]}\n'
QUESTION = "Which Configuration do we keep after this Comparison?"
PROXY_SOURCE = "rule: keep the Configuration with the lowest MAE"
LIVE_KEY = "HYPOTRAIL_ANTHROPIC_API_KEY"
NO_STUDY = "no-study-here"

# Each state, in the order the driver makes it: its number and name, and the Study it reads.
STATES = [
    ("00", "no-study", None),
    ("01", "init", "bike"),
    ("02", "attempts", "bike"),
    ("03", "assessments", "bike"),
    ("04", "pending", "bike"),
    ("05", "decided", "bike"),
    ("06", "resume", "bike"),
    ("07", "rescored", "bike"),
    ("08", "result-changed", "bike"),
    ("09", "new-compare", "bike"),
    ("10", "proxy", "bike"),
    ("11", "study-changed", "bike"),
    ("12", "public-check-run", "bike"),
    ("13", "exposure", "bike"),
    ("14", "exposure-report", "bike"),
    ("15", "deviation", "bike"),
    ("16", "deviation-withdrawn", "bike"),
    ("17", "interrupted", "bike"),
    ("18", "recovered", "bike"),
    ("19", "two-interrupted", "bike-duplicate"),
    ("30", "chinook-init", "chinook"),
    ("31", "chinook-scenarios", "chinook"),
    ("32", "chinook-import", "chinook"),
    ("33", "chinook-assessed", "chinook"),
]
# The numbering each Study's reads share: the duplicate holds the Bike Study.
NUMBERING = {"bike": "bike", "bike-duplicate": "bike", "chinook": "chinook"}

# A `run ml` whose writing process dies right after its `kill_at`-th publication, as `tests/test_run_ml.py::KILL` makes one but once the
# file is in place: a temporary file would carry the process id and a random suffix in its name. Its arguments follow.
KILL = textwrap.dedent(
    """
    import os, sys
    from hypotrail import cli

    kill_at, replaced = int(sys.argv[1]), [0]
    real = os.replace

    def counting_replace(source, target, *args, **kwargs):
        if "write_journal" in str(target):  # the write journal's entries are not publications of the Attempt
            return real(source, target, *args, **kwargs)
        real(source, target, *args, **kwargs)
        replaced[0] += 1
        if replaced[0] == kill_at:
            os._exit(9)  # the writing process dies once this publication is made, leaving no temporary file


    os.replace = counting_replace
    sys.exit(cli.main(sys.argv[2:]))
    """
)
KILL_AT = 1  # the running manifest is published, and nothing after it
KILLED_EXIT = 9


def name_of(number: str, name: str) -> str:
    return f"{number}-{name}"


def _cli(expected: int, *args) -> tuple:
    code, out, err = run_cli(*args)
    assert code == expected, (args, code, out, err)
    return code, out, err


def _ok(*args) -> dict:
    return json.loads(_cli(0, *args, "--json")[1])


def _sequence(study) -> int:
    return _ok("status", "--study", study)["write_sequence"]


def _killed(study, examples, request_id) -> None:
    env = {key: value for key, value in os.environ.items() if key != LIVE_KEY}
    args = ["run", "ml", "--study", str(study), "--config", "ridge_v1", "--partition", "dev", "--request-id", request_id, "--examples-dir", str(examples)]
    result = subprocess.run([sys.executable, "-B", "-c", KILL, str(KILL_AT), *args], capture_output=True, text=True, env=env)
    assert result.returncode == KILLED_EXIT, result.stderr


def _edit_copy(examples, edit: str) -> None:
    result = subprocess.run([sys.executable, "-I", "-B", str(EDIT_COPY), "--copy", str(examples), "--edit", edit], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _decide(study, option: str, author: str, comparison: str, request_id: str, read_sequence: int, *more, expected: int = 0):
    return _cli(
        expected, "decide", "--study", study, "--question", QUESTION, "--option", option, "--author", author, *more, "--artifact", comparison,
        "--request-id", request_id, "--read-sequence", read_sequence, "--json",
    )


def drive(folder):
    """Make the journey in `folder`, yielding (state name, Study folder or None) once each state is made, in the order of `STATES`."""
    folder = Path(folder)
    examples = folder / "demo-examples"
    shutil.copytree(EXAMPLES, examples)
    bike, chinook = folder / "bike", folder / "chinook"
    names = iter(name_of(number, name) for number, name, _ in STATES)

    yield next(names), None

    _cli(0, "init", "--workload", "bike_day", "--study", bike, "--examples-dir", examples)
    _cli(2, "init", "--workload", "bike_day", "--study", bike, "--examples-dir", examples)  # STUDY_EXISTS
    yield next(names), bike

    attempts = {}
    for config, request_id in (("seasonal_7", "seasonal"), ("ridge_v1", "ridge"), ("seasonal_7", "seasonal")):  # the third is a replay
        attempts[config] = _ok("run", "ml", "--study", bike, "--config", config, "--partition", "dev", "--request-id", request_id, "--examples-dir", examples)["attempt"]
    observations = {config: observation_set_id(bike, attempt) for config, attempt in attempts.items()}
    yield next(names), bike

    def assess_both() -> dict:
        return {
            config: _ok(
                "assess", "--study", bike, "--observations", observations[config], "--scorer", "regression_mae_v1", "--references", references_id(bike),
                "--examples-dir", examples,
            )["assessment"]["assessment_id"]
            for config in ("seasonal_7", "ridge_v1")
        }

    def compare(assessments: dict) -> str:
        return _ok(
            "compare", "--study", bike, "--control", assessments["seasonal_7"], "--candidate", assessments["ridge_v1"], "--examples-dir", examples,
        )["comparison"]["comparison_id"]

    assessments = assess_both()
    yield next(names), bike

    comparison = compare(assessments)
    yield next(names), bike

    sequence = _sequence(bike)
    _decide(bike, "Keep the Control", "human", comparison, "panel-1", sequence)
    yield next(names), bike

    _cli(0, "status", "--study", bike, "--since", _sequence(bike), "--json")  # VS Code reopened: the panel reads the Study again
    yield next(names), bike

    for edit in ("6.1", "6.2"):
        _edit_copy(examples, edit)
        _cli(0, "init", "--study", bike, "--new-revision", "--examples-dir", examples)
        assessments = assess_both()
        yield next(names), bike

    comparison = compare(assessments)
    yield next(names), bike

    _decide(bike, "Keep the Control", "proxy", comparison, "proxy-1", _sequence(bike), "--source", PROXY_SOURCE)
    yield next(names), bike

    comparison = compare(assessments)
    read = _sequence(bike)  # the panel's read; the terminal then writes, and Record sends the read it holds
    _ok("run", "ml", "--study", bike, "--config", "seasonal_7", "--partition", "dev", "--request-id", "demo-s1", "--examples-dir", examples)
    _decide(bike, "Keep the Candidate", "human", comparison, "panel-2", read, expected=6)  # STUDY_CHANGED
    yield next(names), bike

    check = _ok("run", "ml", "--study", bike, "--config", "seasonal_7", "--partition", "public_check", "--request-id", "check", "--examples-dir", examples)["attempt"]
    yield next(names), bike

    _cli(
        0, "assess", "--study", bike, "--observations", observation_set_id(bike, check), "--scorer", "regression_mae_v1", "--references", references_id(bike),
        "--examples-dir", examples,
    )
    yield next(names), bike

    _cli(0, "report", "--study", bike, "--out", folder / "bike-report.html", "--examples-dir", examples)
    yield next(names), bike

    deviation = _ok(
        "deviation", "--study", bike, "--text", "owner review of References pending", "--author", "human", "--artifact", references_id(bike),
        "--request-id", "dv-1", "--read-sequence", _sequence(bike),
    )["declared_deviation"]["declared_deviation_id"]
    yield next(names), bike

    _ok(
        "deviation", "--study", bike, "--text", "the owner review of References is done", "--author", "human", "--artifact", deviation,
        "--request-id", "dv-2", "--read-sequence", _sequence(bike),
    )
    yield next(names), bike

    _killed(bike, examples, "killed")
    yield next(names), bike

    [killed] = [attempt["attempt_id"] for attempt in _ok("status", "--study", bike)["attempts"] if attempt["request_id"] == "killed"]
    _ok("recover", "--study", bike, "--attempt", killed)
    yield next(names), bike

    duplicate = folder / "bike-duplicate"
    shutil.copytree(bike, duplicate)
    for request_id in ("killed-2", "killed-3"):
        _killed(duplicate, examples, request_id)
    yield next(names), duplicate

    _cli(0, "init", "--workload", "chinook", "--study", chinook, "--examples-dir", examples)
    yield next(names), chinook

    _cli(0, "run", "agent", "--study", chinook, "--mode", "scripted_fixture", "--config", "plain", "--request-id", "fixture", "--examples-dir", examples)
    yield next(names), chinook

    population = folder / "population.json"
    population.write_text(POPULATION, encoding="utf-8")
    imported = _ok(
        "import", "agent", "--study", chinook, "--source", TRACE, "--population", population, "--request-id", "import", "--examples-dir", examples,
    )["attempt"]
    yield next(names), chinook

    _cli(
        0, "assess", "--study", chinook, "--observations", observation_set_id(chinook, imported), "--scorer", "chinook_contract_v1",
        "--references", references_id(chinook), "--examples-dir", examples,
    )
    yield next(names), chinook


# The `code` of a freeze record as kept: its commit and dirty mark name the checkout that ran, not what the command wrote, the reason
# `tests/_client_helpers.py::fixed` gives an Attempt's `code_revision` its fixed value.
FIXED_FREEZE_CODE = {"dirty": False, "revision": "0" * 40}


def _kept(out: str, study, numbering: dict) -> str:
    payload = json.loads(LOG_NAME.sub("LOG.eval", out.replace(str(study), "SCRATCH")))
    for record in payload.get("freeze_records") or []:
        assert set(record["code"]) == set(FIXED_FREEZE_CODE), record["code"]
        record["code"] = dict(FIXED_FREEZE_CODE)
    return replaced(json.dumps(payload), numbering)


def journey_outputs(folder) -> dict:
    """{kept name: (exit code, stdout, stderr)} of the reads of each state of `drive(folder)`, `NN-name.status` and, where the state holds a
    Comparison, `NN-name.figures`."""
    folder = Path(folder)
    made, seen = {}, {}
    studies = dict((name_of(number, name), study) for number, name, study in STATES)
    with contextlib.chdir(folder):  # state 00 reads a folder, named relatively, that holds no Study
        for name, study in drive(folder):
            if study is None:
                made[f"{name}.status"] = run_cli("status", "--study", NO_STUDY, "--since", "0", "--json")
                continue
            numbering = seen.setdefault(NUMBERING[studies[name]], {})
            code, out, err = run_cli("status", "--study", study, "--since", "0", "--json")
            assert code == 0, (name, out, err)
            made[f"{name}.status"] = (code, _kept(out, study, numbering), err.replace(str(study), "SCRATCH"))
            if json.loads(out)["comparisons"]:
                code, out, err = run_cli("figures", "--study", study, "--json")
                assert code == 0, (name, out, err)
                made[f"{name}.figures"] = (code, _kept(out, study, numbering), err.replace(str(study), "SCRATCH"))
    return made


def kept_journey(name: str) -> tuple:
    return tuple(
        int(text) if part == "exit" else text
        for part, text in ((part, (JOURNEY_KEPT / f"{name}.{part}").read_text(encoding="utf-8")) for part in ("exit", "out", "err"))
    )


def write_journey_kept(folder) -> None:
    """Writes the files of `journey_outputs(folder)` under `JOURNEY_KEPT`; used by hand, when a record the journey writes changes."""
    JOURNEY_KEPT.mkdir(parents=True, exist_ok=True)
    for name, (code, out, err) in journey_outputs(folder).items():
        (JOURNEY_KEPT / f"{name}.exit").write_text(f"{code}\n", encoding="utf-8")
        (JOURNEY_KEPT / f"{name}.out").write_text(out, encoding="utf-8")
        (JOURNEY_KEPT / f"{name}.err").write_text(err, encoding="utf-8")
