"""Shared by the handbook test (#68): provoke each refusal of `import agent` and of `assess` on a Chinook Study."""

from _chinook_helpers import FIXTURE, fixture_lines, fixture_population, import_agent, init_chinook, write_lines


def agent_import_refusals(tmp_path):
    """Provoke each refusal of `import agent`; return {code: (exit code, stage, set of details keys)}."""
    found = {}

    def record(result):
        code, payload, _ = result
        error = payload["error"]
        found[error["code"]] = (code, error["stage"], set(error["details"]))

    study = init_chinook(tmp_path, name="refusals")[0]
    population = fixture_population(tmp_path)
    lines = fixture_lines()
    gone = tmp_path / "gone"
    record(import_agent(study, gone, population, "r"))
    record(import_agent(study, FIXTURE, gone, "r"))
    pickled = tmp_path / "answers.pkl"
    pickled.write_bytes(b"\x80\x04N.")
    record(import_agent(study, pickled, population, "r"))
    latin = tmp_path / "latin.jsonl"
    latin.write_bytes(b'{"case_id": "\xe9"}\n')
    record(import_agent(study, latin, population, "r"))
    for name, content in {
        "p1.json": "[1]",
        "p2.json": '{"episodes": [{"case_id": "Z99", "repeat": 0}]}',
        "p3.json": '{"episodes": [{"case_id": "D01", "repeat": 0}, {"case_id": "E01", "repeat": 0}]}',
    }.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
        record(import_agent(study, FIXTURE, tmp_path / name, "r"))
    raw = tmp_path / "raw.jsonl"
    raw.write_text("{nope\n", encoding="utf-8")
    record(import_agent(study, raw, population, "r"))
    raw.write_text("[1]\n", encoding="utf-8")
    record(import_agent(study, raw, population, "r"))

    def with_first(change, name):
        edited = [{**lines[0], **change}, *lines[1:]]
        record(import_agent(study, write_lines(tmp_path / name, edited), population, "r"))

    with_first({"repeat": "0"}, "f1.jsonl")
    with_first({"observation_status": "done"}, "f2.jsonl")
    with_first({"raw_answer": "{}"}, "f3.jsonl")
    with_first({"unexpected": None}, "unknown-key.jsonl")
    without = [{k: v for k, v in lines[0].items() if k != "final_answer"}, *lines[1:]]
    record(import_agent(study, write_lines(tmp_path / "f4.jsonl", without), population, "r"))
    record(import_agent(study, write_lines(tmp_path / "f5.jsonl", [*lines, {**lines[0], "case_id": "Z99"}]), population, "r"))
    record(import_agent(study, write_lines(tmp_path / "f6.jsonl", [*lines, lines[0]]), population, "r"))
    record(import_agent(study, write_lines(tmp_path / "f7.jsonl", lines[1:]), population, "r"))
    return found
