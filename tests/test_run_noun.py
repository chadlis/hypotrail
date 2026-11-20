"""R3-01, #77 Tightened B2, GLOSSARY Attempt (_Avoid_: run, job, execution record), D-012 item 17.

« run » is not the noun for an Attempt or for an execution anywhere in the corpus: `src/`, `tests/`, the handbook chapters and
`README.md`. What is let through is an explicit allow-list: the command names (`run agent`, `run ml`, `spike live`), the file
`run.json`, the name « run record » and the verb. The noun is found after a determiner or an adjective that only a noun takes.
This file is the one file of the corpus left out of the scan, because its sentences quote the noun on purpose.
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
# The Mode names are adjectives only after a determiner (« an llm_live run »): alone they are a subject (« llm_live runs one Partition »).
MODE_ADJECTIVES = r"llm_live|scripted_fixture"
# Names that contain the word without using it as the noun: `run agent`, `run ml`, `run record`, and `run.json`.
ALLOWED_AFTER = r"(?!\.json|\s+(?:agent|ml|record|command|subcommand)\b)"
NOUN = re.compile(
    rf"\b(?:(?:{DETERMINERS})\s+(?:(?:{ADJECTIVES}|{MODE_ADJECTIVES})\s+)*|(?:{ADJECTIVES})\s+)runs?\b{ALLOWED_AFTER}(?:'s)?",
    re.IGNORECASE,
)


def run_as_a_noun(text):
    """The places of `text` where « run » or « runs » is the noun, each with its surroundings."""
    text = re.sub(r"\s*\n\s*(?:(?:#|\"\"\")\s*)?", " ", text)  # a sentence continued on the next line or the next comment line
    text = re.sub(r"<[^>]+>", " ", html.unescape(text))  # a chapter as its reader reads it
    text = " ".join(text.split()).replace("spike live", "spike_live")  # the command name is not an adjective and a noun
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
]
VERB_AND_NAME_SENTENCES = [
    "run agent --mode llm_live; run ml; the run.json file; the run record; spike live runs one Configuration",
    "an Attempt runs exactly one Configuration; the machine that runs; A replay runs no scan; the query runs in a thread",
    "the Attempts run under it; To run it again, use a new request id; the checks run in a fixed order",
    "uv run python -m hypotrail; --study runs/bike; run_fixture; Assessing runs no model",
    "to run <code>ridge_v1</code>; the <code>run</code> subcommand; <code>run agent</code>",
]


@pytest.mark.parametrize("sentence", NOUN_SENTENCES)
def test_the_finder_sees_run_as_the_noun_for_an_attempt_or_an_execution(sentence):
    assert run_as_a_noun(sentence), sentence


@pytest.mark.parametrize("sentence", VERB_AND_NAME_SENTENCES)
def test_the_finder_lets_the_command_names_the_file_the_record_name_and_the_verb_through(sentence):
    assert run_as_a_noun(sentence) == [], sentence


def test_the_corpus_is_the_whole_of_src_tests_the_chapters_and_the_readme():
    names = {p.name for p in corpus()}
    assert {"cli.py", "live.py", "run.py", "test_handbook.py", "test_run_agent_record.py", "03-agentic-track.html", "README.md"} <= names
    assert THIS_FILE.name not in names and len(names) > 100


@pytest.mark.parametrize("path", corpus(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_file_calls_an_attempt_or_an_execution_a_run(path):
    assert run_as_a_noun(path.read_text(encoding="utf-8")) == []
