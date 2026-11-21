"""R3-01, #77 Tightened B2, GLOSSARY Attempt (_Avoid_: run, job, execution record), D-012 on chadlis/hypotrail#75 item 17.

"run" is not the noun for an Attempt or for an execution anywhere in the corpus: `src/`, `tests/`, the handbook chapters and
`README.md`. What is let through is an explicit allow-list: the command names (`run agent`, `run ml`, `spike live`), the file
`run.json` (`run_json` in an identifier), the name "run record", the words "run command" and "run subcommand" (the command and its parser), and the verb.
The noun is found after a determiner or an adjective that only a noun takes, with a noun between the adjective and "run" allowed
("a live model run"). An identifier is read as words (`_` separates them), a `.py` file is read as text (its `<` and `>` are
operators, not tags), and only a chapter is read as its reader reads it (tags stripped). This file is the one file of the corpus left out of the scan, because its sentences quote the noun on purpose.
"""

import html
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
THIS_FILE = Path(__file__).resolve()
CHAPTERS = ROOT / "docs" / "handbook" / "chapters"

DETERMINERS = r"the|a|an|this|each|every|one|two|three|its|their|his|her|our|same|other|another|per|any|no|whole"
ADJECTIVES = (
    r"live|paid|failed|failing|scripted|offline|kept|first|last|next|previous|recorded|single|real|new|earlier|fresh|spike|library|native|"
    r"imported|successful|full|complete|aborted|interrupted|opt-in|bounded|dry|good|bad"
)
# The Mode names are adjectives only after a determiner ("an llm_live run"): alone they are a subject ("llm_live runs one Partition").
# The Mode names are kept whole when an identifier is read as words.
MODE_ADJECTIVES = r"llmlive|scriptedfixture"
# A noun that sits between an adjective and the noun "run" ("a live model run"); after a determiner alone it is a subject ("the model runs").
MODIFIERS = r"model|llm|provider|agent|ml|study"
# Names that contain the word without using it as the noun: `run agent`, `run ml`, `run record`, `run command`, `run subcommand` and `run.json`.
ALLOWED_AFTER = r"(?!\.json|\s+(?:json|agent|ml|record|command|subcommand)\b)"
NOUN = re.compile(
    rf"\b(?:(?:{DETERMINERS})\s+(?:(?:{ADJECTIVES}|{MODE_ADJECTIVES})\s+)*|(?:{ADJECTIVES})\s+(?:(?:{ADJECTIVES})\s+)*(?:(?:{MODIFIERS})\s+)*)runs?\b{ALLOWED_AFTER}(?:'s)?",
    re.IGNORECASE,
)


def run_as_a_noun(text, markup=False):
    """The places of `text` where "run" or "runs" is the noun, each with its surroundings. `markup`: a chapter, read with its tags stripped."""
    text = re.sub(r"\s*\n\s*(?:(?:#|\"\"\")\s*)?", " ", text)  # a sentence continued on the next line or the next comment line
    if markup:
        text = re.sub(r"<[^>]+>", " ", html.unescape(text))  # a chapter as its reader reads it
    text = " ".join(text.split()).replace("spike live", "spikelive")  # the command name is not an adjective and a noun
    text = text.replace("llm_live", "llmlive").replace("scripted_fixture", "scriptedfixture").replace("_", " ")  # an identifier is words: `test_a_failing_run_...` calls a run a run
    return [text[max(0, m.start() - 30) : m.end() + 30] for m in NOUN.finditer(text)]


def corpus():
    files = [*(ROOT / "src").rglob("*.py"), *(ROOT / "tests").rglob("*.py"), *CHAPTERS.glob("*.html"), ROOT / "README.md"]
    return sorted(p for p in files if p.resolve() != THIS_FILE)


NOUN_SENTENCES = [
    "after a failed run the same warnings",
    "the Chinook file changed during an llm_live run; the Attempt",
    "hashed before and after the run: a difference",
    "One paid run was planned",
    "the run's own value",
    "Scripted runs and offline runs",
    "A native run of a declared Configuration",
    "this run's, or the kept log's",
    "a run takes the Partition dev or public_check",
    "It records the Attempt from the Inspect log of the run",
    "the same code a live\n# run uses",
    "each run writes",
    "<td>The same, during a <code>scripted_fixture</code> run</td><td>3</td>",
    "<h3>Scripted runs</h3><p>Offline runs use",
    # R4-01, the reader's examples: a noun after a noun, and the identifiers
    "Preconditions of a live model run",
    "def test_a_failing_run_without_a_leak_keeps_its_own_error(",
    "def test_a_key_is_scanned_after_an_llm_live_run_whether_or_not_it_failed(",
    "def test_the_database_is_hashed_during_the_run_is_database_changed(",
    "def test_a_key_planted_in_the_runs_output_is_found(",
    "def test_the_log_of_the_live_run_recorded(",
    "by_the_run = request.source is RequestSource.THIS_ATTEMPT",
]
# Python source is text: its `<` and `>` are operators, and a span between two of them is not a tag.
PYTHON_NOUN_SOURCES = ["if a <= b:\n    pass\n# the run's own value, in a record the run writes\nif c > d:\n    pass\n"]
VERB_AND_NAME_SENTENCES = [
    "run agent --mode llm_live; run ml; the run.json file; the run record; spike live runs one Configuration",
    "an Attempt runs exactly one Configuration; the machine that runs; A replay runs no scan; the query runs in a thread",
    "the Attempts run under it; To run it again, use a new request id; the checks run in a fixed order",
    "uv run python -m hypotrail; --study runs/bike; run_fixture; Assessing runs no model",
    "to run <code>ridge_v1</code>; the <code>run</code> subcommand; <code>run agent</code>",
    "def run_fixture(; run_episodes(; def test_run_agent_replays_a_request(; def test_the_checks_run_in_a_fixed_order(; the_model_runs_one_case",
    "uv_run_python; the model runs one Episode; the model run_agent; def test_a_run_command_is_parsed(",
]


@pytest.mark.parametrize("sentence", NOUN_SENTENCES)
def test_the_finder_sees_run_as_the_noun_for_an_attempt_or_an_execution(sentence):
    assert run_as_a_noun(sentence, markup="</" in sentence), sentence


@pytest.mark.parametrize("source", PYTHON_NOUN_SOURCES)
def test_the_finder_reads_python_source_as_text_and_not_as_markup(source):
    assert run_as_a_noun(source), source
    assert run_as_a_noun(source, markup=True) == []  # the tag strip is what hid it


@pytest.mark.parametrize("sentence", VERB_AND_NAME_SENTENCES)
def test_the_finder_lets_the_command_names_the_file_the_record_name_and_the_verb_through(sentence):
    assert run_as_a_noun(sentence) == [], sentence


def test_the_corpus_is_the_whole_of_src_tests_the_chapters_and_the_readme():
    names = {p.name for p in corpus()}
    assert {"cli.py", "live.py", "run.py", "test_handbook.py", "test_run_agent_record.py", "03-agentic-track.html", "README.md"} <= names
    assert THIS_FILE.name not in names and len(names) > 100


@pytest.mark.parametrize("path", corpus(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_file_calls_an_attempt_or_an_execution_a_run(path):
    assert run_as_a_noun(path.read_text(encoding="utf-8"), markup=path.suffix == ".html") == []
