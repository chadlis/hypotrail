"""Two Studies made by the commands that print an id, and their files as `tests/fixtures/printed_ids/` keeps them.

The Bike Study: `init`, two `run ml` on dev (`seasonal_7`, `ridge_v1`), an `assess` of each, the `compare` of the two Assessments and a
`decide` on that Comparison. The Chinook Study: `init`, a `scripted_fixture` `run agent`, an `import agent` of the kit's authored answers
and the `assess` of the Import. Each id a command takes is read from the Study's files, so that the CLI of `main` `07197ea`, which prints no
Observation set ID and no References ID, makes the same Studies: the kept files were made there, with `write_kept`.

A file whose bytes are those of a file under `examples/` (a copy of the Workload's data or declaration) is kept as the SHA-256 of its
bytes, so that no copy of the Workload's data is kept. Every other file is kept as its text once the rules below are applied: a JSON record
whole, any other text up to `TEXT_LIMIT` characters, and a longer text (a CSV of one row per Item) as the SHA-256 of that text; a file
that is not UTF-8 text is kept as the SHA-256 of its bytes. The rules:

- a JSON file takes the keyed rules of `tests/_client_helpers.py::fixed` (`code_revision`, `python`, `size_bytes`), and the SHA-256 of
  `uv.lock` in every `dependency_lock` of a `code_environment` is set to null: the commit, the dirty mark and the lock digest name the
  checkout that ran, not what the command wrote;
- each UUID, timestamp and 64-hex digest is replaced by its numbered placeholder, as `tests/_client_helpers.py::replaced` numbers them, in
  one numbering over the Study: `study.json` first, then the write journal in its order, which names every record a command wrote, then
  every other file in the order of its replaced path;
- the name of the Inspect log of an Attempt (a timestamp and a random suffix) becomes `LOG.eval`, in paths and in texts;
- a float is written to 12 significant digits, the rule of `tests/_client_helpers.py::first_difference`.

Two files are kept by name only, each with the reason: the `observations.jsonl` of the `scripted_fixture` Attempt holds the latencies the
Episodes measured, and the Inspect log is a zip archive that holds its own timestamps and identifiers. Each differs between two Studies made
by the same code; the records that reference them hold their digest, which the numbering replaces.
"""

import hashlib
import json
import re
import shutil
from pathlib import Path

from _assess_helpers import observation_set_id, references_id
from _chinook_helpers import FIXTURE, fixture_population
from _client_helpers import DIGEST, TIMESTAMP, UUID, fixed, numbered
from _study_helpers import EXAMPLES, ROOT, run_json

KEPT = ROOT / "tests" / "fixtures" / "printed_ids"
TEXT_LIMIT = 4096
LOG_NAME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2}[-+][0-9]{2}-[0-9]{2}_[A-Za-z0-9_-]+\.eval")
FLOAT = re.compile(r"(?<![\w.:])-?[0-9]+\.[0-9]+(?:[eE][-+]?[0-9]+)?(?![\w.])")  # not the seconds of a timestamp, not a version
MEASURED = "kept by name only: the latencies the Episodes measured"
ARCHIVE = "kept by name only: a zip archive that holds its own timestamps and identifiers"


def ok(*args) -> dict:
    code, payload, err = run_json(*args)
    assert code == 0, (args, payload, err)
    return payload


def bike_study(folder) -> Path:
    study = Path(folder) / "bike"
    ok("init", "--workload", "bike_day", "--study", study, "--examples-dir", EXAMPLES)
    assessments = []
    for config in ("seasonal_7", "ridge_v1"):
        attempt = ok("run", "ml", "--study", study, "--config", config, "--partition", "dev", "--request-id", f"kept-{config}", "--examples-dir", EXAMPLES)["attempt"]
        assessments.append(ok(
            "assess", "--study", study, "--observations", observation_set_id(study, attempt), "--scorer", "regression_mae_v1",
            "--references", references_id(study), "--examples-dir", EXAMPLES,
        )["assessment"]["assessment_id"])
    comparison = ok("compare", "--study", study, "--control", assessments[0], "--candidate", assessments[1])["comparison"]["comparison_id"]
    sequence = ok("status", "--study", study)["write_sequence"]
    ok(
        "decide", "--study", study, "--question", "Which Configuration?", "--option", "seasonal_7", "--author", "human", "--artifact", comparison,
        "--request-id", "kept-decide", "--read-sequence", sequence,
    )
    return study


def chinook_study(folder) -> Path:
    study = Path(folder) / "chinook"
    inputs = Path(folder) / "chinook-inputs"
    inputs.mkdir(parents=True)
    ok("init", "--workload", "chinook", "--study", study, "--examples-dir", EXAMPLES)
    ok("run", "agent", "--study", study, "--mode", "scripted_fixture", "--config", "plain", "--request-id", "kept-fixture", "--examples-dir", EXAMPLES)
    attempt = ok(
        "import", "agent", "--study", study, "--source", FIXTURE, "--population", fixture_population(inputs), "--request-id", "kept-import",
        "--examples-dir", EXAMPLES,
    )["attempt"]
    ok(
        "assess", "--study", study, "--observations", observation_set_id(study, attempt), "--scorer", "chinook_contract_v1",
        "--references", references_id(study), "--examples-dir", EXAMPLES,
    )
    return study


STUDIES = {"bike": bike_study, "chinook": chinook_study}


def _without_lock_digest(value):
    """`value` with the digest of `uv.lock` set to null in every `dependency_lock` it holds, at every depth: an Attempt's `code_environment`
    holds one, and a Comparison's holds one for each side."""
    if isinstance(value, list):
        return [_without_lock_digest(each) for each in value]
    if not isinstance(value, dict):
        return value
    out = {key: _without_lock_digest(each) for key, each in value.items()}
    if isinstance(out.get("dependency_lock"), dict):
        out["dependency_lock"]["sha256"] = None
    return out


def _json_rules(record):
    return _without_lock_digest(fixed(record))


def _float(match) -> str:
    return format(float(match[0]), ".12g")


def kept_files(study) -> dict:
    """{replaced path: replaced text, or {"sha256": ...}} for every file of `study`."""
    study = Path(study)
    seen: dict = {}

    def numbering(text: str) -> str:
        text = LOG_NAME.sub("LOG.eval", text)
        for kind, pattern in (("uuid", UUID), ("timestamp", TIMESTAMP), ("digest", DIGEST)):
            text = numbered(text, kind, pattern, seen.setdefault(kind, {}))
        return text

    def path_of(file: Path) -> str:
        relative = LOG_NAME.sub("LOG.eval", file.relative_to(study).as_posix())
        unknown = [value for value in UUID.findall(relative) if value not in seen.get("uuid", {})]
        assert not unknown, f"{relative} names an id that no journal entry names: {unknown}"
        return numbering(relative)

    workload = {hashlib.sha256(p.read_bytes()).hexdigest() for p in EXAMPLES.rglob("*") if p.is_file()}
    measured = {
        manifest.parent / "observations.jsonl"
        for manifest in study.glob("attempts/*/attempt.json")
        if json.loads(manifest.read_text(encoding="utf-8"))["mode"] == "scripted_fixture"
    }

    def kept(file: Path):
        if file in measured:
            return MEASURED
        if file.suffix == ".eval":
            return ARCHIVE
        data = file.read_bytes()
        if hashlib.sha256(data).hexdigest() in workload:
            return {"sha256": hashlib.sha256(data).hexdigest()}
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return {"sha256": hashlib.sha256(data).hexdigest()}
        if file.suffix == ".json":
            text = json.dumps(_json_rules(json.loads(text)), indent=2) + "\n"
        text = FLOAT.sub(_float, numbering(text))
        return text if file.suffix == ".json" or len(text) <= TEXT_LIMIT else {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}

    files = sorted(p for p in study.rglob("*") if p.is_file())
    first = [study / "study.json", *sorted((study / "write_journal").glob("*.json"))]
    out = {}
    for file in first:
        out[path_of(file)] = kept(file)
    for path, file in sorted((path_of(file), file) for file in files if file not in first):
        out[path] = kept(file)
    return out


def write_kept(folder) -> None:
    """Make both Studies under `folder` and write their kept files under `KEPT`, one JSON object per Study."""
    KEPT.mkdir(parents=True, exist_ok=True)
    for name, make in STUDIES.items():
        (KEPT / f"{name}.json").write_text(json.dumps(kept_files(make(folder)), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    shutil.rmtree(Path(folder) / "chinook-inputs", ignore_errors=True)
