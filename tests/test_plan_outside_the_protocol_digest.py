"""ADR 0005: the Plan is a Study record outside the Protocol digest, and the rules on when information is available stay inside it.

The ticket sentence the file checks: "ADR 0005 has the parts of ADR 0004: title, "Status: accepted", the decision, "Considered options",
"Consequences". It names `availability` as `src/hypotrail/ml/study.py` holds it and `revision_changed` as `core/decisions.py` does, and every
consequence that is not built says so." (chadlis/hypotrail#243)
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADR_DIR = ROOT / "docs" / "adr"


def adr() -> str:
    found = sorted(ADR_DIR.glob("0005-*.md"))
    assert len(found) == 1, f"there is no single ADR 0005 in docs/adr/: {[p.name for p in sorted(ADR_DIR.glob('*.md'))]}"
    return found[0].read_text(encoding="utf-8")


def section(text: str, title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"the ADR has no section '{title}'"
    return match[1]


def bullets(text: str) -> list:
    return [" ".join(b.split()) for b in re.split(r"^- ", text, flags=re.M)[1:]]


def squash(text: str) -> str:
    return " ".join(text.split())


def test_the_adr_is_accepted_and_has_the_decision_the_considered_options_and_the_consequences():
    text = adr()
    assert text.startswith("# ") and "\nStatus: accepted\n" in text
    for title in ("Decision", "Considered options", "Consequences"):
        assert section(text, title).strip(), title


def test_the_decision_puts_the_plan_outside_the_protocol_digest_and_keeps_availability_inside_as_the_code_names_both():
    decision = squash(section(adr(), "Decision"))
    assert "outside the Protocol digest" in decision and all(f"`{key}`" in decision for key in ("rule", "budget", "delegation")), decision
    assert "`availability`" in decision and "`src/hypotrail/ml/study.py`" in decision, decision
    assert "`revision_changed`" in decision and "`core/decisions.py`" in decision, decision
    assert '"availability": {' in (ROOT / "src" / "hypotrail" / "ml" / "study.py").read_text(encoding="utf-8")
    assert 'REVISION_CHANGED' in (source := (ROOT / "src" / "hypotrail" / "core" / "decisions.py").read_text(encoding="utf-8")) and '"revision_changed"' in source


def test_the_considered_options_hold_the_plan_inside_the_digest_quoting_the_second_reading():
    options = bullets(section(adr(), "Considered options"))
    inside = [b for b in options if "inside the digest" in b]
    assert len(inside) == 1, options
    assert '"He wants strict pre-registration: the Plan goes inside the digest (Option B)."' in inside[0], inside[0]


def test_every_consequence_says_it_is_not_built():
    consequences = bullets(section(adr(), "Consequences"))
    assert consequences and [b for b in consequences if "not built" not in b] == [], consequences


def test_the_adr_cites_every_decision_with_its_issue_and_quotes_no_french():
    text = squash(adr())
    assert [m[0] for m in re.finditer(r"D-\d{3}(?! on chadlis/hypotrail#75)", text)] == []
    assert "\u00ab" not in text and "\u00bb" not in text
