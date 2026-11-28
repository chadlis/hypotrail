"""Keep the journey's first-use vocabulary anchored to the glossary."""

import re
from pathlib import Path


GLOSSARY = Path(__file__).resolve().parents[1] / "GLOSSARY.md"
JOURNEY_TERMS = {
    "Study", "Write sequence", "Decision", "Pending decision", "Workload",
    "Track", "Protocol", "Exposure", "Partition", "Item", "Configuration",
    "Attempt", "Observation set", "Reference", "Scorer", "Metric", "Assessment",
    "Comparison", "Control", "Candidate", "Journey", "Target look",
}


def test_journey_terms_have_in_ml_lines_before_avoid():
    parts = re.split(r"^\*\*(.+?)\*\*:\s*$", GLOSSARY.read_text(encoding="utf-8"), flags=re.MULTILINE)
    entries = dict(zip(parts[1::2], parts[2::2], strict=True))
    missing = JOURNEY_TERMS.difference(entries)
    assert not missing
    for term in sorted(JOURNEY_TERMS):
        entry = entries[term]
        assert re.search(r"^_In ML_: \S[^\n]*\n_Avoid_: ", entry, re.MULTILINE), term
