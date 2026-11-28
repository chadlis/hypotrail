"""The calls behind `tests/_order_table.py`: one Study per writer, a fault for each row, and the call that makes it.

Each Study a call works on is built once (a template folder) and copied for every row. A builder takes the row's `tmp_path` and gives
`(study, call)`: `call(read)` runs the command line with `--read-sequence read` (`init` that creates a Study takes no such option, so its
`call` leaves it out and ignores `read`). Nothing here calls a model: the only Mode of `run agent` that reaches the lock is `scripted_fixture`, and every
`llm_live` call here is refused by a check that comes before the lock.
"""

import atexit
import contextlib
import json
import shutil
import sys
import tempfile
import unittest.mock
from pathlib import Path

from _assess_helpers import observation_set_id, references_id
from _chinook_helpers import chinook_examples, database_of, fixture_lines, fixture_population, init_chinook, write_lines
from _import_helpers import ready
from _ranking_helpers import initialize, write_build
from _report_tracks import TRACKS
from _run_agent_helpers import MODEL, fixture
from _study_helpers import examples_copy, init_study, run_json, run_ml
from test_run_ml import killed
from test_write_sequence import seq

from hypotrail.core import data

_HOME = tempfile.TemporaryDirectory(prefix="order-probe-")
atexit.register(_HOME.cleanup)
HOME = Path(_HOME.name)
_built: dict = {}


def once(name, build):
    """The template `name`, built on first use: `build(folder)` returns the facts of the world."""
    if name not in _built:
        folder = HOME / name
        folder.mkdir()
        _built[name] = build(folder)
    return _built[name]


def ok(result):
    code, payload, err = result
    assert code == 0, (payload, err)
    return payload


def decide(study, request_id, artifact, read, option="seasonal_7"):
    argv = ["decide", "--study", study, "--question", "Which Configuration?", "--option", option, "--author", "human", "--artifact", artifact]
    return run_json(*argv, "--request-id", request_id, "--read-sequence", read)


def deviation(study, request_id, artifact, read):
    argv = ["deviation", "--study", study, "--text", "owner review of References pending", "--author", "human", "--artifact", artifact]
    return run_json(*argv, "--request-id", request_id, "--read-sequence", read)


# --- the Studies: each holds an Attempt `r1`, a Decision `d1`, a Declared deviation `v1`, an Import `i1`, and one write made after the value `stale` was read


def bike_world(folder):
    study, _ = init_study(folder)
    attempt = ok(run_ml(study, "seasonal_7", "dev", "r1"))["attempt"]
    other = ok(run_ml(study, "ridge_v1", "dev", "r2"))["attempt"]
    ok(decide(study, "d1", attempt["attempt_id"], seq(study)))
    ok(deviation(study, "v1", attempt["attempt_id"], seq(study)))
    (folder / "files").mkdir()
    source, mapping, population, _ = ready(folder / "files")
    ok(run_json("import", "ml", "--study", study, "--source", source, "--mapping", mapping, "--population", population, "--request-id", "i1"))
    refs = references_id(study)
    first, second = (
        ok(run_json("assess", "--study", study, "--observations", observation_set_id(study, each), "--scorer", "regression_mae_v1", "--references", refs))
        for each in (attempt, other)
    )
    stale = seq(study)
    ok(run_ml(study, "seasonal_7", "dev", "bump"))
    return {
        "study": study, "stale": stale, "attempt": attempt["attempt_id"], "observations": observation_set_id(study, attempt), "references": refs,
        "control": first["assessment"]["assessment_id"], "candidate": second["assessment"]["assessment_id"],
        "source": source, "mapping": mapping, "population": population,
    }


def chinook_world(folder):
    study, _ = init_chinook(folder)
    attempt = ok(fixture(study, "plain", "r1"))["attempt"]
    ok(decide(study, "d1", attempt["attempt_id"], seq(study), option="plain"))
    ok(deviation(study, "v1", attempt["attempt_id"], seq(study)))
    source = write_lines(folder / "answers.jsonl", fixture_lines())
    population = fixture_population(folder)
    ok(run_json("import", "agent", "--study", study, "--source", source, "--population", population, "--request-id", "i1"))
    stale = seq(study)
    ok(fixture(study, "plain", "bump"))
    return {"study": study, "stale": stale, "source": source, "population": population}


def public_world(folder):
    study, _ = TRACKS["bike"].public_outputs(folder)  # a page that shows public_check Items is an Exposure
    stale = seq(study)
    ok(run_ml(study, "seasonal_7", "dev", "bump"))
    return {"study": study, "stale": stale}


def killed_world(folder):
    study, attempt = killed(folder, kill_at=4)
    stale = seq(study)
    ok(run_ml(study, "seasonal_7", "dev", "bump"))
    return {"study": study, "stale": stale, "attempt": attempt.name}


def ranking_world(folder):
    examples, build_dir = write_build(folder)
    study = folder / "study"
    initialized = ok(initialize((examples, build_dir, study)))
    stale = seq(study)
    ok(run_json(
        "deviation", "--study", study, "--text", "Synthetic probe", "--author", "proxy",
        "--artifact", initialized["references_id"], "--request-id", "probe", "--read-sequence", stale,
    ))
    return {"study": study, "stale": stale}


WORLDS = {"bike": bike_world, "chinook": chinook_world, "public": public_world, "killed": killed_world, "ranking": ranking_world}
WORLD_OF = {
    "init --new-revision": "bike", "run ml": "bike", "run agent": "chinook", "import ml": "bike", "import agent": "chinook", "assess": "bike",
    "compare": "bike", "recover": "killed", "report": "public", "decide": "bike", "deviation": "bike",
    "review import": "ranking",
}


class Built:
    """A copy of a world's Study in the row's folder; `facts` are those of the world the writer's own options are read from."""

    def __init__(self, writer, tmp_path, world=None):
        self.tmp_path = Path(tmp_path)
        self.facts = once(WORLD_OF[writer], WORLDS[WORLD_OF[writer]])
        template = once(world, WORLDS[world]) if world else self.facts
        self.study = self.tmp_path / "study"
        shutil.copytree(template["study"], self.study)
        self.stale = template["stale"]


# --- the options of each writer --------------------------------------------------------------------------------------------------------


def options_of(writer, built):
    facts = built.facts
    return {
        "init --new-revision": lambda: {"--new-revision": True},
        "run ml": lambda: {"--config": "seasonal_7", "--partition": "dev", "--request-id": "new"},
        "run agent": lambda: {"--mode": "scripted_fixture", "--config": "plain", "--request-id": "new"},
        "import ml": lambda: {"--source": facts["source"], "--mapping": facts["mapping"], "--population": facts["population"], "--request-id": "new"},
        "import agent": lambda: {"--source": facts["source"], "--population": facts["population"], "--request-id": "new"},
        "assess": lambda: {"--observations": facts["observations"], "--scorer": "regression_mae_v1", "--references": facts["references"]},
        "compare": lambda: {"--control": facts["control"], "--candidate": facts["candidate"]},
        "recover": lambda: {"--attempt": facts["attempt"]},
        "report": lambda: {"--out": built.tmp_path / "page.html"},
        "decide": lambda: {
            "--question": "Which Configuration?", "--option": "seasonal_7", "--author": "human", "--artifact": facts["attempt"], "--request-id": "new",
        },
        "deviation": lambda: {"--text": "owner review of References pending", "--author": "human", "--artifact": facts["attempt"], "--request-id": "new"},
        "review import": lambda: {"--receipt": built.tmp_path / "missing.json"},
    }[writer]()


def flat(options):
    """The flags of `options`: `True` is a flag without a value, a list repeats the option."""
    argv = []
    for flag, value in options.items():
        for each in value if isinstance(value, list) else [value]:
            argv += [flag] if each is True else [flag, each]
    return argv


def call_of(writer, built, options, around=None):
    def call(read):
        with around() if around else contextlib.nullcontext():
            return run_json(*writer.split(), "--study", built.study, *flat(options), "--read-sequence", read)

    return call


def of(writer, *, world=None, setup=None, around=None, **change):
    """The call of `writer`, with `change` applied to its options.

    `world` names the Study the command is called on when it is not the writer's own. `change` is a dict of options, or a function of the
    built Study that returns one (`setup(built)` has run on the copy first).
    """

    def build(tmp_path):
        built = Built(writer, tmp_path, world)
        if setup:
            setup(built)
        wanted = change["options"](built) if "options" in change else change
        return built.study, call_of(writer, built, {**options_of(writer, built), **wanted}, around)

    return build


# --- the faults ------------------------------------------------------------------------------------------------------------------------------


def flipped(path):
    content = bytearray(Path(path).read_bytes())
    content[len(content) // 2] ^= 1
    Path(path).write_bytes(bytes(content))


def bike_examples(built, *, edit=None, name="examples"):
    return examples_copy(built.tmp_path, edit=edit, name=name)


def spoiled_bike_data(built):
    examples = bike_examples(built, name="flipped")
    flipped(examples / "bike_day" / "data" / "day.csv")
    return {"--examples-dir": examples}


def spoiled_chinook_notice(built):
    examples = chinook_examples(built.tmp_path, name="flipped")
    notice = examples / "chinook" / "licenses" / "Chinook-MIT.txt"
    notice.write_text(notice.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
    return {"--examples-dir": examples}


def bike_without(key):
    """The Workload's declaration lacks a key the schema leaves optional."""

    def edit(declaration):
        del declaration[key]

    return lambda built: {"--examples-dir": bike_examples(built, edit=edit, name="incomplete")}


def spoil_the_study_dataset(built):
    """A byte of the Study's own copy of the dataset is no longer the one its reference holds."""
    spec = json.loads((built.study / "study.json").read_text(encoding="utf-8"))
    flipped(built.study / spec["dataset_refs"][0]["path"])


def bike_declaration_replaced(built, text=None):
    """The Workload's declaration is not there (`text` None) or holds `text`."""
    examples = bike_examples(built, name="broken")
    declaration = examples / "bike_day" / "workload.json"
    if text is None:
        declaration.unlink()
    else:
        declaration.write_text(text, encoding="utf-8")
    return {"--examples-dir": examples}


def spoil_the_recorded_outputs(request_id):
    """A byte of the first output the Study recorded for `request_id` is no longer the one its reference holds."""

    def setup(built):
        for folder in (built.study / "attempts").iterdir():
            manifest = json.loads((folder / "attempt.json").read_text(encoding="utf-8"))
            if manifest["request_id"] == request_id:
                flipped(built.study / manifest["output_refs"][0]["path"])
                return
        raise AssertionError(f"the Study records no Attempt of the request {request_id!r}")

    return setup


def a_log_that_is_not_one(built):
    junk = built.tmp_path / "junk.eval"
    junk.write_bytes(b"not a log")
    return {"--source": junk}


def another_copy_of(path, built, name):
    """The same file with one more byte: the same request with another digest."""
    target = built.tmp_path / name
    target.write_bytes(Path(path).read_bytes() + b"\n")
    return target


def chinook_without(built, *, edit=None, remove=None):
    examples = chinook_examples(built.tmp_path, edit=edit, name="broken")
    if remove:
        (examples / "chinook" / remove).unlink()
    return {"--examples-dir": examples}


def live(**change):
    return {"--mode": "llm_live", "--partition": "dev", "--repeats": "1", "--model": MODEL, **change}


def the_default_examples_are_missing():
    """A checkout whose `examples/` is gone: the options are unchanged, the default directory is what is missing."""

    return unittest.mock.patch.object(data, "default_examples_dir", lambda: HOME / "no-examples")


def inspect_is_not_installed():
    return unittest.mock.patch.dict(sys.modules, {"inspect_ai": None})


def new_study(tmp_path, *, workload="bike_day", examples=None, around=None, read_sequence=False):
    """An `init` that creates a Study of `workload` in a folder whose lock another process holds: `(study, call)`.

    The folder holds the (empty) lock file already, so the files of the Study are the same before and after the call. `init` that creates a
    Study takes no `--read-sequence`: `call` ignores the value it is given, unless `read_sequence` passes the option (which `init` refuses).
    """
    study = Path(tmp_path) / "fresh"
    study.mkdir()
    (study / "writer.lock").touch()

    def call(read):
        argv = ["init", "--workload", workload, "--study", study, *(["--examples-dir", examples] if examples else [])]
        if read_sequence:
            argv += ["--read-sequence", read]
        with around() if around else contextlib.nullcontext():
            return run_json(*argv)

    return study, call


def new_bike_study(tmp_path, *, edit=None, spoil=False, around=None, read_sequence=False):
    examples = examples_copy(Path(tmp_path), edit=edit, name="examples") if edit or spoil else None
    if spoil:
        flipped(examples / "bike_day" / "data" / "day.csv")
    return new_study(tmp_path, examples=examples, around=around, read_sequence=read_sequence)


def new_chinook_study(tmp_path, *, edit=None, spoil=False):
    examples = chinook_examples(Path(tmp_path), edit=edit, name="examples") if edit or spoil else None
    if spoil:
        flipped(database_of(examples))
    return new_study(tmp_path, workload="chinook", examples=examples)


def a_track_the_study_cannot_have(declaration):
    declaration["track"] = "not_a_track"


def without_a_question(declaration):
    del declaration["question"]


def without_the_train_partition(declaration):
    del declaration["partitions"]["train"]


def with_a_key_the_track_does_not_know(declaration):
    declaration["not_a_key"] = 1


# --- the table's rows, as calls --------------------------------------------------------------------------------------------------------------

LOCK_HELD = {
    "init --read-sequence": lambda tmp_path: new_bike_study(tmp_path, read_sequence=True),
    "init": lambda tmp_path: new_bike_study(tmp_path),
    "init agent": lambda tmp_path: new_chinook_study(tmp_path),
    "init --new-revision agent": of("init --new-revision", world="chinook"),
    "assess agent": of("assess", world="chinook", **{"--scorer": "chinook_contract_v1"}),
    **{writer: of(writer) for writer in WORLD_OF},
    "deviation empty text": of("deviation", **{"--text": ""}),
}

CHECKS_BEFORE_THE_LOCK = {
    "init examples": lambda tmp_path: new_bike_study(tmp_path, around=the_default_examples_are_missing),
    "init data": lambda tmp_path: new_bike_study(tmp_path, spoil=True),
    "init Track": lambda tmp_path: new_bike_study(tmp_path, edit=a_track_the_study_cannot_have),
    "init declaration schema": lambda tmp_path: new_bike_study(tmp_path, edit=without_the_train_partition),
    "init declaration": lambda tmp_path: new_bike_study(tmp_path, edit=without_a_question),
    "init agent data": lambda tmp_path: new_chinook_study(tmp_path, spoil=True),
    "init agent Workload": lambda tmp_path: new_chinook_study(tmp_path, edit=with_a_key_the_track_does_not_know),
    "init agent declaration": lambda tmp_path: new_chinook_study(tmp_path, edit=without_a_question),
    "run agent Track": of("run agent", world="bike"),
    "run agent examples": of("run agent", around=the_default_examples_are_missing),
    "run agent Workload": of("run agent", options=lambda b: chinook_without(b, remove="workload.json")),
    "run agent --config": of("run agent", **{"--config": "not_declared"}),
    "run agent scenarios not declared": of("run agent", options=lambda b: chinook_without(b, edit=lambda d: d.pop("scenarios"))),
    "run agent scenarios file": of("run agent", options=lambda b: chinook_without(b, remove="fixtures/scenarios.json")),
    "run agent Partition cases": of("run agent", options=lambda b: {**chinook_without(b, edit=lambda d: d["cases"].pop("public_check")), **live(**{"--partition": "public_check"})}),
    "run agent --cases outside": of("run agent", **live(**{"--partition": "public_check", "--cases": ["D03"]})),
    "import agent Inspect": of("import agent", options=lambda b: {"--source": b.tmp_path / "log.eval"}, around=inspect_is_not_installed),
    "compare --factor": of("compare", **{"--factor": "model"}),
    "report records": of("report", setup=spoil_the_study_dataset),
    "report --out": of("report", options=lambda b: {"--out": b.study / "page.html"}),
}

UNDER_THE_LOCK = {
    "init --new-revision examples": of("init --new-revision", around=the_default_examples_are_missing),
    "init --new-revision agent examples": of("init --new-revision", world="chinook", around=the_default_examples_are_missing),
    "run ml declaration keys": of("run ml", options=bike_without("id_prefix")),
    "run agent Workload lock": of("run agent", options=lambda b: chinook_without(b, remove="data-sources.lock.json")),
    "import ml declaration keys": of("import ml", options=bike_without("id_prefix")),
    "import agent answer schema": of("import agent", options=lambda b: chinook_without(b, edit=lambda d: d.pop("answer_schema"))),
    "report examples": of("report", around=the_default_examples_are_missing),
    "run ml examples": of("run ml", around=the_default_examples_are_missing),
    "run ml declaration file": of("run ml", options=bike_declaration_replaced),
    "run ml declaration JSON": of("run ml", options=lambda b: bike_declaration_replaced(b, "{")),
    "run ml replay artifacts": of("run ml", setup=spoil_the_recorded_outputs("r1"), **{"--request-id": "r1"}),
    "run ml Track": of("run ml", world="chinook"),
    "run ml data": of("run ml", options=spoiled_bike_data),
    "run ml Study artifact": of("run ml", setup=spoil_the_study_dataset),
    "run ml --partition": of("run ml", **{"--partition": "not_a_partition"}),
    "run ml --config": of("run ml", **{"--config": "not_declared"}),
    "run ml --retry-of": of("run ml", **{"--retry-of": "no_attempt"}),
    "run ml replay": of("run ml", **{"--request-id": "r1"}),
    "run ml request conflict": of("run ml", **{"--request-id": "r1", "--config": "ridge_v1"}),
    "run ml request_id of a decision": of("run ml", **{"--request-id": "d1"}),
    "run agent --retry-of": of("run agent", **{"--retry-of": "no_attempt"}),
    "run agent replay": of("run agent", **{"--request-id": "r1"}),
    "run agent replay artifacts": of("run agent", setup=spoil_the_recorded_outputs("r1"), **{"--request-id": "r1"}),
    "run agent request conflict": of("run agent", **{"--request-id": "r1", "--config": "verify"}),
    "run agent request_id of a decision": of("run agent", **{"--request-id": "d1"}),
    "import ml Track": of("import ml", world="chinook"),
    "import ml data": of("import ml", options=spoiled_bike_data),
    "import ml Study artifact": of("import ml", setup=spoil_the_study_dataset),
    "import ml source": of("import ml", options=lambda b: {"--source": b.tmp_path / "none.csv"}),
    "import ml mapping": of("import ml", options=lambda b: {"--mapping": b.tmp_path / "none.json"}),
    "import ml population": of("import ml", options=lambda b: {"--population": b.tmp_path / "none.json"}),
    "import ml examples": of("import ml", around=the_default_examples_are_missing),
    "import ml declaration file": of("import ml", options=bike_declaration_replaced),
    "import ml declaration JSON": of("import ml", options=lambda b: bike_declaration_replaced(b, "{")),
    "import ml replay": of("import ml", **{"--request-id": "i1"}),
    "import ml replay artifacts": of("import ml", setup=spoil_the_recorded_outputs("i1"), **{"--request-id": "i1"}),
    "import ml request conflict": of("import ml", options=lambda b: {"--request-id": "i1", "--mapping": another_copy_of(b.facts["mapping"], b, "mapping.json")}),
    "import ml request_id of a decision": of("import ml", **{"--request-id": "d1"}),
    "import agent Track": of("import agent", world="bike"),
    "import agent Workload files": of("import agent", options=spoiled_chinook_notice),
    "import agent Study artifact": of("import agent", setup=spoil_the_study_dataset),
    "import agent source": of("import agent", options=lambda b: {"--source": b.tmp_path / "none.jsonl"}),
    "import agent population": of("import agent", options=lambda b: {"--population": b.tmp_path / "none.json"}),
    "import agent examples": of("import agent", around=the_default_examples_are_missing),
    "import agent Workload": of("import agent", options=lambda b: chinook_without(b, remove="workload.json")),
    "import agent log": of("import agent", options=a_log_that_is_not_one),
    "import agent replay": of("import agent", **{"--request-id": "i1"}),
    "import agent replay artifacts": of("import agent", setup=spoil_the_recorded_outputs("i1"), **{"--request-id": "i1"}),
    "import agent request conflict": of("import agent", options=lambda b: {"--request-id": "i1", "--source": another_copy_of(b.facts["source"], b, "answers.jsonl")}),
    "import agent request_id of a decision": of("import agent", **{"--request-id": "d1"}),
    "assess Scorer": of("assess", **{"--scorer": "not_a_scorer"}),
    "assess agent Observation set": of("assess", world="chinook", **{"--scorer": "chinook_contract_v1", "--observations": "no_observations"}),
    "compare Assessment": of("compare", **{"--control": "no_assessment"}),
    "recover Attempt": of("recover", **{"--attempt": "no_attempt"}),
    "report Exposure": of("report"),
    "decide replay": of("decide", **{"--request-id": "d1"}),
    "decide request conflict": of("decide", **{"--request-id": "d1", "--question": "Another question?"}),
    "decide request_id of an Attempt": of("decide", **{"--request-id": "r1"}),
    "decide cited id": of("decide", **{"--artifact": "no_record"}),
    "run ml request_id of a declared deviation": of("run ml", **{"--request-id": "v1"}),
    "run agent request_id of a declared deviation": of("run agent", **{"--request-id": "v1"}),
    "import ml request_id of a declared deviation": of("import ml", **{"--request-id": "v1"}),
    "import agent request_id of a declared deviation": of("import agent", **{"--request-id": "v1"}),
    "decide request_id of a declared deviation": of("decide", **{"--request-id": "v1"}),
    "deviation replay": of("deviation", **{"--request-id": "v1"}),
    "deviation request conflict": of("deviation", **{"--request-id": "v1", "--text": "another text"}),
    "deviation request_id of an Attempt": of("deviation", **{"--request-id": "r1"}),
    "deviation request_id of a decision": of("deviation", **{"--request-id": "d1"}),
    "deviation cited id": of("deviation", **{"--artifact": "no_record"}),
    "review import receipt": of("review import"),
}
