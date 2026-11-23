"""The VS Code client in `clients/vscode/`: its manifest and tooling, the CI job of its tests, the listings over its sources, and the CLI output its tests keep.

The client's own tests are TypeScript, under `clients/vscode/test/`, and `npm test` runs them; these are the checks that read the repository
with no Node. Nothing here calls a model, and the CLI is run in process, offline.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest
from _study_helpers import init_study, run_cli

ROOT = Path(__file__).resolve().parent.parent
CLIENT = ROOT / "clients" / "vscode"
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
KEPT = CLIENT / "test" / "cli"


def tracked(*pathspecs: str) -> list:
    """The tracked files under the pathspecs, as `git ls-files` lists them (paths relative to the repository root)."""
    listing = subprocess.run(["git", "ls-files", "-z", "--", *pathspecs], cwd=ROOT, capture_output=True, text=True, check=True)
    return sorted(name for name in listing.stdout.split("\0") if name)


def read_json(path: Path):
    assert path.is_file(), f"{path.relative_to(ROOT)} does not exist"
    return json.loads(path.read_text(encoding="utf-8"))


def sources() -> dict:
    """{path: text} of every tracked file under `clients/vscode/src/`."""
    return {name: (ROOT / name).read_text(encoding="utf-8") for name in tracked("clients/vscode/src")}


# --- the extension's project ---------------------------------------------------------------------------------------------------


def test_the_manifest_and_tsconfig_hold_the_decided_values():
    manifest = read_json(CLIENT / "package.json")
    assert manifest.get("publisher") == "hypotrail-local"
    assert manifest.get("name") == "hypotrail"
    assert manifest.get("private") is True
    assert "license" not in manifest
    assert sorted(manifest.get("devDependencies", {})) == ["@types/node", "@types/vscode", "typescript"]
    assert manifest["devDependencies"]["@types/node"] == "^22"
    assert not manifest.get("dependencies")
    engine = re.fullmatch(r"\^(\d+)\.(\d+)\.(\d+)", manifest.get("engines", {}).get("vscode", ""))
    assert engine and tuple(map(int, engine.groups())) >= (1, 95, 0), manifest.get("engines")
    assert "onUri" in manifest.get("activationEvents", [])
    assert read_json(CLIENT / "tsconfig.json")["compilerOptions"]["types"] == ["node", "vscode"]


def test_the_client_tracks_its_lockfile_tsconfig_contract_sources_and_tests_and_no_other_manifest_declares_a_vscode_engine():
    files = tracked("clients/vscode")
    for name in ("package.json", "package-lock.json", "tsconfig.json", "contract.json"):
        assert f"clients/vscode/{name}" in files, name
    assert [f for f in files if f.startswith("clients/vscode/src/")], "no tracked file under clients/vscode/src/"
    assert [f for f in files if f.startswith("clients/vscode/test/")], "no tracked file under clients/vscode/test/"
    others = []
    for name in tracked():
        if name.endswith("package.json") and not name.startswith("clients/vscode/"):
            if "vscode" in json.loads((ROOT / name).read_text(encoding="utf-8")).get("engines", {}):
                others.append(name)
    assert others == []


def test_the_manifest_contributes_no_setting():
    assert "configuration" not in read_json(CLIENT / "package.json").get("contributes", {})


# --- CI --------------------------------------------------------------------------------------------------------------------------

# The job `pytest` as it stands at the base, `main` at 62b8c8d.
PYTEST_JOB_AT_THE_BASE = """\
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.13"
      - run: uv sync --locked --all-extras
      # Offline: the suite blocks outbound network in every test. No secret is
      # passed, so no live model call can run here (AGENTS.md).
      - run: uv run --locked --all-extras pytest
"""


def workflow_jobs(text: str) -> dict:
    """{name: the job's lines, its header included} of the `jobs:` mapping of a workflow."""
    body = text.split("\njobs:\n", 1)[1]
    starts = [m for m in re.finditer(r"^  ([A-Za-z0-9_-]+):\n", body, re.M)]
    return {m[1]: body[m.start() : (starts[i + 1].start() if i + 1 < len(starts) else len(body))] for i, m in enumerate(starts)}


def test_the_workflow_has_a_second_job_that_sets_up_node_22_and_runs_npm_ci_and_npm_test_in_the_client_and_passes_no_secret():
    text = WORKFLOW.read_text(encoding="utf-8")
    jobs = workflow_jobs(text)
    assert len(jobs) == 2, sorted(jobs)
    assert list(jobs)[0] == "pytest"
    assert jobs["pytest"].rstrip("\n") + "\n" == PYTEST_JOB_AT_THE_BASE
    second = list(jobs.values())[1]
    for needle in ('node-version: "22"', "npm ci", "npm test", "clients/vscode"):
        assert needle in second, needle
    assert "secrets." not in text


# --- the CLI output the client tests keep -----------------------------------------------------------------------------------------


def kept_status_names() -> list:
    return sorted(Path(name).stem for name in tracked("clients/vscode/test/cli") if re.fullmatch(r".*/status-[a-z-]+\.out", name))


# The id each record of the object holds for itself, by list.
OWN_IDS = {"attempts": "attempt_id", "assessments": "assessment_id", "comparisons": "comparison_id", "decisions": "decision_id", "declared_deviations": "declared_deviation_id"}


def test_each_kept_status_read_holds_numbered_placeholders_in_order_of_first_appearance_of_the_shape_they_replace_and_no_two_records_share_an_id():
    from _client_helpers import DIGEST, TIMESTAMP, UUID, placeholder

    names = kept_status_names()
    assert "status-success" in names and "status-not-found" in names
    for name in names:
        text = (KEPT / f"{name}.out").read_text(encoding="utf-8")
        for kind, pattern in (("uuid", UUID), ("timestamp", TIMESTAMP), ("digest", DIGEST)):
            found = list(dict.fromkeys(pattern.findall(text)))
            assert found == [placeholder(kind, number) for number in range(1, len(found) + 1)], (name, kind, found)
            assert all(pattern.fullmatch(each) for each in found), (name, kind)
        payload = json.loads(text)
        if not payload["ok"]:
            continue
        ids = [payload["study"]["study_id"]] + [record[key] for list_name, key in OWN_IDS.items() for record in payload[list_name]]
        assert len(ids) == len(set(ids)), (name, ids)


@pytest.mark.parametrize(
    "case, edit",
    [
        ("a code_revision that is not an object", lambda o: o["comparisons"][0]["code_environment"]["control"].update(code_revision="62b8c8d")),
        ("a python that is not a text", lambda o: o["comparisons"][0]["code_environment"]["control"].update(python=3.13)),
        ("a request_id that is not a text", lambda o: o["attempts"][0].update(request_id=None)),
        ("two Attempts that share a request_id", lambda o: o["attempts"][1].update(request_id=o["attempts"][0]["request_id"])),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_a_value_the_four_rules_cannot_take_fails_the_making_with_no_fall_back(case, edit):
    from _client_helpers import replaced

    payload = json.loads((KEPT / "status-success.out").read_text(encoding="utf-8"))
    assert replaced(json.dumps(payload, indent=2)) is not None
    edit(payload)
    with pytest.raises(AssertionError):
        replaced(json.dumps(payload, indent=2))


def test_each_kept_status_read_whose_ok_is_true_is_the_clis_own_once_its_values_are_replaced_and_the_four_rules_applied(tmp_path):
    from _client_helpers import first_difference, kept, status_outputs

    made = status_outputs(tmp_path)
    assert sorted(made) == kept_status_names()
    for name, (code, out, err) in made.items():
        kept_code, kept_out, kept_err = kept(name)
        assert (code, err) == (kept_code, kept_err), name
        if not json.loads(kept_out)["ok"]:
            assert out == kept_out, name  # a refusal names no scratch folder and is kept as printed
            continue
        assert first_difference(json.loads(kept_out), json.loads(out)) is None, name


# Each kept read, with the keys that make its case: the counts of `pending_decisions` and `decisions`, the `withdrawn` values of
# `declared_deviations`, and the `workload` of the Study.
KEPT_CASES = {
    "status-success": (1, 0, [], "bike_day"),
    "status-chinook-pending": (1, 0, [], "chinook"),
    "status-several-pending": (2, 0, [], "bike_day"),
    "status-decided": (0, 1, [], "bike_day"),
    "status-deviation": (1, 0, [False, True, False], "bike_day"),
}


def test_each_kept_read_holds_the_case_it_is_kept_for():
    names = kept_status_names()
    for name, (pending, decided, withdrawn, workload) in KEPT_CASES.items():
        assert name in names, name
        payload = read_json(KEPT / f"{name}.out")
        assert (len(payload["pending_decisions"]), len(payload["decisions"])) == (pending, decided), name
        assert [entry["withdrawn"] for entry in payload["declared_deviations"]] == withdrawn, name
        assert payload["study"]["workload"] == workload, name


# --- the listings over the client's sources ---------------------------------------------------------------------------------------

# Names whose uses the client's sources may hold, each with the files allowed to hold it. A name with no file is held by none.
# Matching is by text: a name is found as a substring, except the two patterns, which are regular expressions, case-insensitive.
PROCESS_NAMES = ["child_process", "spawn", "node:net", "node:http"]
PROCESS_PATTERNS = {"exec(": r"(?<!\.)\bexec\(", "shell": r"\bshell\b"}
VSCODE_RUNNERS = ["createTerminal", "sendText", "executeTask", "ShellExecution", "ProcessExecution", "CustomExecution", "startDebugging"]
STATE_NAMES = ["globalState", "workspaceState", "setState", "localStorage"]
WRITE_NAMES = ["writeFile", "appendFile", "createWriteStream"]
# The names of a watcher and of a read on visibility or on a timer, and the names that read or open a file.
WATCH_NAMES = ["createFileSystemWatcher", "watch(", "watchFile", "onDidChangeViewState", "onDidChangeTextDocument", "setInterval"]
FILE_READ_NAMES = ["readFile", "readFileSync", "createReadStream", "openTextDocument", "showTextDocument", "vscode.open", "workspace.fs"]
EXPECTED_LISTING = {("clients/vscode/src/bridge.ts", "child_process")}
STUDY_FILE_HOLDERS = ["clients/vscode/src/studies.ts"]
# Names each found exactly once in the client's sources, in the file given: the one call that creates a webview panel,
# the one assignment of a webview's document, and the one receiver of the document's messages.
ONCE_NAMES = {"createWebviewPanel": "clients/vscode/src/panel.ts", ".html =": "clients/vscode/src/panel.ts", "onDidReceiveMessage": "clients/vscode/src/panel.ts"}
CHILD_PROCESS_IMPORT = 'import { execFile } from "node:child_process";'
VSCODE_IMPORT = 'import * as vscode from "vscode";'


def listing(files: dict) -> set:
    """Each pair (file, name) for a name of the lists above that the file holds."""
    found = set()
    for path, text in files.items():
        for name in PROCESS_NAMES + VSCODE_RUNNERS + STATE_NAMES + WRITE_NAMES + WATCH_NAMES + FILE_READ_NAMES:
            if name in text:
                found.add((path, name))
        for name, pattern in PROCESS_PATTERNS.items():
            if re.search(pattern, text, re.I):
                found.add((path, name))
    return found


def listing_problems(files: dict) -> list:
    """What the listing finds against its own lists, both ways, and the import lines that are not the two conventions."""
    problems = []
    found = listing(files)
    problems += [f"found and not expected: {pair}" for pair in sorted(found - EXPECTED_LISTING)]
    problems += [f"expected and not found: {pair}" for pair in sorted(EXPECTED_LISTING - found)]
    for path, text in files.items():
        for line in text.splitlines():
            if "child_process" in line and (path != "clients/vscode/src/bridge.ts" or line.strip() != CHILD_PROCESS_IMPORT):
                problems.append(f"{path}: {line.strip()}")
            if 'from "vscode"' in line and line.strip() != VSCODE_IMPORT:
                problems.append(f"{path}: {line.strip()}")
    for name, where in ONCE_NAMES.items():
        held = sorted((path, text.count(name)) for path, text in files.items() if name in text)
        if held != [(where, 1)]:
            problems.append(f"{name} is held by {held}, not once by {where}")
    holders = sorted(path for path, text in files.items() if "study.json" in text)
    if holders != STUDY_FILE_HOLDERS:
        problems.append(f"the files that name study.json: {holders}")
    return problems


def test_only_the_bridge_starts_a_process_and_only_through_execfile_and_no_source_keeps_state_writes_a_file_or_reads_study_json():
    """The listing is bounded by the conventions of D-083 on chadlis/hypotrail#75: only `src/bridge.ts` imports `node:child_process`, and only
    as `import { execFile } from "node:child_process"`; `vscode` is imported only as `import * as vscode from "vscode"`. The stop rule of D-054
    on chadlis/hypotrail#75, read with `clients/vscode/src/` in the place of `src/`: "**Stop rule.** A later escape that code under `src/`
    actually uses is a blocker. An escape that is only planted is a stated limit, written down in the test's docstring and in the PR body."
    """
    files = sources()
    assert "clients/vscode/src/bridge.ts" in files
    assert listing_problems(files) == []


PLANTED = [
    ("a second file that imports spawn", "clients/vscode/src/other.ts", 'import { spawn } from "node:child_process";\n'),
    ("exec( in the bridge", "clients/vscode/src/bridge.ts", "exec(command);\n"),
    ("a require of child_process", "clients/vscode/src/other.ts", 'const cp = require("child_process");\n'),
    ("a named import from vscode", "clients/vscode/src/other.ts", 'import { window } from "vscode";\n'),
    ("the word in a comment", "clients/vscode/src/other.ts", "// opens a Shell\n"),
    ("node:net", "clients/vscode/src/other.ts", 'import * as net from "node:net";\n'),
    ("node:http", "clients/vscode/src/other.ts", 'import * as http from "node:http";\n'),
    *[(name, "clients/vscode/src/other.ts", f"vscode.window.{name}();\n") for name in VSCODE_RUNNERS],
    *[(name, "clients/vscode/src/other.ts", f"context.{name}.update();\n") for name in STATE_NAMES + WRITE_NAMES],
    ("a second file that names study.json", "clients/vscode/src/other.ts", 'const marker = "study.json";\n'),
    ("a second panel created in another file", "clients/vscode/src/other.ts", 'vscode.window.createWebviewPanel("x", "x", 1, {});\n'),
    ("a second document assigned", "clients/vscode/src/panel.ts", 'other.webview.html = "<p></p>";\n'),
    ("a second message receiver", "clients/vscode/src/other.ts", "other.webview.onDidReceiveMessage(listen);\n"),
    *[(name, "clients/vscode/src/other.ts", f"vscode.workspace.{name}(target);\n") for name in WATCH_NAMES + FILE_READ_NAMES],
]


@pytest.mark.parametrize("case, path, line", PLANTED, ids=[case for case, _, _ in PLANTED])
def test_a_planted_escape_is_found_by_the_listing(case, path, line):
    files = sources()
    files[path] = files.get(path, "") + line
    assert listing_problems(files) != [], case


@pytest.mark.parametrize("line", ["const found = pattern.exec(text);\n", "function buildShellLess() {}\nconst x = buildShell;\n"])
def test_a_method_named_exec_and_a_name_that_holds_the_word_are_not_found(line):
    files = sources()
    files["clients/vscode/src/other.ts"] = line
    assert listing_problems(files) == []


# --- the licence -------------------------------------------------------------------------------------------------------------------


def test_no_licence_file_no_licence_key_in_the_manifest_and_the_readme_licence_section_reads_not_chosen_yet():
    assert [name for name in tracked() if re.match(r"(license|licence|copying)", Path(name).name, re.I)] == []
    assert "license" not in read_json(CLIENT / "package.json")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.split("## License\n", 1)[1].strip().splitlines()[0] == "Not chosen yet."


def test_no_client_file_but_the_lockfile_holds_copyright_or_license_and_the_lockfile_root_entry_has_no_license_key():
    files = tracked("clients/vscode")
    assert "clients/vscode/package-lock.json" in files
    holding = [f for f in files if f != "clients/vscode/package-lock.json" and re.search(r"copyright|license", (ROOT / f).read_text(encoding="utf-8"), re.I)]
    assert holding == []
    assert "license" not in read_json(CLIENT / "package-lock.json")["packages"][""]


# --- the ported passages -----------------------------------------------------------------------------------------------------------

NOTE = re.compile(r"// Ported from hypotrail/hypotrail@4ef4925, clients/vscode-companion/(?P<path>[^:\s]+):(?P<lines>\d+(?:-\d+)?)\.")
CHAPTER = ROOT / "docs" / "handbook" / "chapters" / "18-vscode-client.html"
# The companion's places that hold French: no note may name them.
FRENCH_PLACES = re.compile(r"^(lib/l10n\.js|media/copy-fr/.*)$")


def ported_sentence(chapter: str) -> str:
    found = re.findall(r'<p id="ported-passages">(.*?)</p>', chapter, re.S)
    assert len(found) == 1, "the chapter has no single sentence that lists the ported passages"
    return found[0]


def provenance_problems(files: dict, sentence: str) -> list:
    """Each note that is not of the form, each note the sentence does not list, each entry of the sentence with no note."""
    problems, notes = [], []
    for path, text in files.items():
        for line in text.splitlines():
            if line.lstrip().startswith("// Ported from"):
                match = NOTE.fullmatch(line.strip())
                if not match:
                    problems.append(f"{path}: a note of another form: {line.strip()}")
                    continue
                notes.append((match["path"], match["lines"]))
                first = int(match["lines"].split("-")[0])
                if FRENCH_PLACES.match(match["path"]) or (match["path"] == "lib/refusals.js" and first >= 99):
                    problems.append(f"{path}: a note that names a place holding French: {line.strip()}")
    listed = re.findall(r"clients/vscode-companion/([^:\s<]+):(\d+(?:-\d+)?)", sentence)
    problems += [f"a note the handbook does not list: {n}" for n in sorted(set(notes) - set(listed))]
    problems += [f"a handbook entry with no note: {n}" for n in sorted(set(listed) - set(notes))]
    return problems


def client_files() -> dict:
    return {name: (ROOT / name).read_text(encoding="utf-8") for name in tracked("clients/vscode")}


def test_every_provenance_note_has_its_form_and_the_notes_equal_the_handbook_sentence_both_ways():
    assert CHAPTER.is_file(), "the handbook has no chapter for the client"
    assert provenance_problems(client_files(), ported_sentence(CHAPTER.read_text(encoding="utf-8"))) == []


NOTE_LINE = "// Ported from hypotrail/hypotrail@4ef4925, clients/vscode-companion/lib/cli.js:224-227."
PLANTED_NOTES = [
    ("a note in another form", {"clients/vscode/src/x.ts": "// Ported from the companion, lib/cli.js.\n"}, "none"),
    ("a note the handbook does not list", {"clients/vscode/src/x.ts": NOTE_LINE + "\n"}, "none"),
    ("a handbook entry with no note", {}, "clients/vscode-companion/lib/cli.js:224-227"),
    ("a note that names French", {"clients/vscode/src/x.ts": NOTE_LINE.replace("lib/cli.js:224-227", "lib/l10n.js:1-5") + "\n"}, "clients/vscode-companion/lib/l10n.js:1-5"),
]


@pytest.mark.parametrize("case, files, sentence", PLANTED_NOTES, ids=[case for case, _, _ in PLANTED_NOTES])
def test_a_planted_provenance_fault_is_found(case, files, sentence):
    assert provenance_problems(files, sentence) != [], case
    assert provenance_problems({"clients/vscode/src/x.ts": NOTE_LINE + "\n"}, "clients/vscode-companion/lib/cli.js:224-227") == []


def test_no_tracked_client_file_is_javascript():
    assert [f for f in tracked("clients/vscode") if re.search(r"\.(js|mjs|cjs|jsx)$", f)] == []


# --- the README ----------------------------------------------------------------------------------------------------------------------

README_LINE = "- [`clients/vscode/`](clients/vscode/): the VS Code client (the extension, its CLI bridge and the Study panel)."


def test_where_to_look_names_the_client_directory_which_holds_the_manifest():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    where = readme.split("## Where to look\n", 1)[1].split("\n## ", 1)[0]
    assert README_LINE in where.splitlines()
    assert (CLIENT / "package.json").is_file()


# --- the bridge's writes ----------------------------------------------------------------------------------------------------------


def leaf_commands() -> dict:
    """{command: {flag: required}} of every command of the parser that takes no further command."""
    from hypotrail.cli import build_parser

    leaves = {}

    def walk(parser, path):
        subs = [a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"]
        if not subs:
            leaves[" ".join(path)] = {flag: a.required for a in parser._actions for flag in a.option_strings if flag not in ("-h", "--help")}
        for sub in subs:
            for name, child in sub.choices.items():
                walk(child, (*path, name))

    walk(build_parser(), ())
    return leaves


def test_the_decide_argument_lists_the_client_tests_keep_are_accepted_by_the_parser_and_give_back_their_values():
    from hypotrail.cli import build_parser

    lists = read_json(CLIENT / "test" / "decide-arguments.json")
    assert len(lists) == 3
    assert [(each["decision"]["question"], each["decision"]["option"]) for each in lists if each["decision"]["question"] == "-x"] == [("-x", "--study")]
    for each in lists:
        assert each["arguments"][0] == "decide", each["name"]
        parsed = build_parser().parse_args(each["arguments"])
        decision = each["decision"]
        assert str(parsed.study) == each["study"], each["name"]
        assert (parsed.question, parsed.option, parsed.author) == (decision["question"], decision["option"], decision["author"]), each["name"]
        assert parsed.source == decision.get("source"), each["name"]
        assert parsed.artifact == decision["cited_ids"], each["name"]
        assert (parsed.request_id, parsed.read_sequence, parsed.json) == (decision["request_id"], decision["read_sequence"], True), each["name"]


KEPT_WRITES = [
    "decide-success",
    "decide-replay",
    "decide-study-changed",
    "decide-write-sequence-ahead",
    "decide-request-conflict",
    "decide-invalid-arguments",
    "decide-study-not-found",
]


def test_the_kept_decide_outputs_are_the_clis_own_once_each_uuid_and_the_scratch_folder_are_replaced(tmp_path):
    from _client_helpers import decide_outputs, kept

    made = decide_outputs(tmp_path)
    assert sorted(made) == sorted(KEPT_WRITES)
    for name in KEPT_WRITES:
        assert kept(name) == made[name], name
    codes = {name: json.loads(made[name][1]).get("error", {}).get("code") for name in KEPT_WRITES}
    assert codes == {
        "decide-success": None,
        "decide-replay": None,
        "decide-study-changed": "STUDY_CHANGED",
        "decide-write-sequence-ahead": "WRITE_SEQUENCE_AHEAD",
        "decide-request-conflict": "REQUEST_CONFLICT",
        "decide-invalid-arguments": "INVALID_ARGUMENTS",
        "decide-study-not-found": "STUDY_NOT_FOUND",
    }
    assert made["decide-invalid-arguments"][2].startswith("usage: ")


def test_the_client_reads_and_writes_are_leaf_commands_each_write_requires_the_request_id_and_read_sequence_and_no_other_writer_is_listed():
    contract = read_json(CLIENT / "contract.json")
    leaves = leaf_commands()
    assert contract["reads"] == ["status"] and contract["writes"] == ["decide"]
    for command in contract["reads"] + contract["writes"]:
        assert command in leaves, command
    for command in contract["writes"]:
        assert leaves[command].get("--request-id") is True and leaves[command].get("--read-sequence") is True, command
    for command in ("report", "assess", "compare", "recover", "init"):
        assert command not in contract["reads"] + contract["writes"], command


# --- the panel and deep links ---------------------------------------------------------------------------------------------------


def test_the_manifest_contributes_exactly_the_one_command_and_its_title():
    commands = read_json(CLIENT / "package.json").get("contributes", {}).get("commands")
    assert commands == [{"command": "hypotrail.openPanel", "title": "Hypotrail: Open the Study panel"}]


def test_the_authority_of_both_link_forms_is_the_manifests_publisher_and_name():
    manifest = read_json(CLIENT / "package.json")
    forms = read_json(CLIENT / "contract.json").get("link_forms", [])
    assert len(forms) == 2
    assert [re.match(r"vscode://([^/]+)/", form)[1] for form in forms] == [f"{manifest['publisher']}.{manifest['name']}"] * 2


# --- the texts of a pending decision ------------------------------------------------------------------------------------------------


def pending_texts() -> list:
    """The question's text and each option's text and consequence, as the core holds them (`hypotrail.core.decisions`)."""
    from hypotrail.core.decisions import PENDING_OPTIONS, PENDING_QUESTION

    return [PENDING_QUESTION["text"]] + [option[key] for option in PENDING_OPTIONS for key in ("text", "consequence")]


def pending_text_holders(files: dict) -> list:
    """Each pair (file, text) for a text of a pending decision that a file holds."""
    return [(path, text) for path, held in sorted(files.items()) for text in pending_texts() if text in held]


def client_source_and_contract() -> dict:
    return {**sources(), "clients/vscode/contract.json": (CLIENT / "contract.json").read_text(encoding="utf-8")}


def test_no_client_source_and_not_contract_json_holds_a_text_of_the_pending_decision():
    assert len(pending_texts()) == 7
    assert pending_text_holders(client_source_and_contract()) == []


def test_a_planted_file_that_holds_an_option_text_is_found():
    from hypotrail.core.decisions import PENDING_OPTIONS

    files = client_source_and_contract()
    files["clients/vscode/src/other.ts"] = f'const option = "{PENDING_OPTIONS[1]["text"]}";\n'
    assert pending_text_holders(files) == [("clients/vscode/src/other.ts", PENDING_OPTIONS[1]["text"])]
