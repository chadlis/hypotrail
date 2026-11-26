"""`text_facts_v1` (#265): the five Criteria of a prose answer against a `text-reference/1` Reference, one row per situation."""

import json
from pathlib import Path

import pytest

from hypotrail.core import text_facts

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "examples" / "chinook_prose" / "scoring" / "text-facts.json").read_text(encoding="utf-8"))
NO_PHRASES = {**CONFIG, "outcome_phrases": {}}


def reference(**changes) -> dict:
    record = {
        "case_id": "X01",
        "reference_version": "test-references/1",
        "expected_outcome": "answered",
        "expected_identifiers": [{"kind": "invoice", "value": "34"}, {"kind": "customer", "value": "12"}],
        "expected_facts": [
            {"fact_id": "total", "type": "decimal", "value": 1234.5, "tolerance": 0.005, "rule": "SELECT 1"},
            {"fact_id": "date", "type": "date", "value": "2009-05-23", "rule": "SELECT 1"},
            {"fact_id": "country", "type": "text", "value": "Brazil", "rule": "SELECT 1"},
        ],
        "reference_text": "Customer 12 has invoice 34, dated 2009-05-23, of 1,234.50, billed to Brazil.",
        "as_of": "2026-11-26",
    }
    record.update(changes)
    return record


ALL = "Customer 12 has invoice 34, dated 2009-05-23, of 1,234.50, billed to Brazil."
TRUE = {name: ("scored", True, None) for name in text_facts.CRITERIA}


def expect(**rows):
    """The five Criteria, all scored true but those given as (state, score, reason)."""
    return {**TRUE, **rows}


def false(reason):
    return ("scored", False, reason)


def count_fact(value, tolerance=0, kind="integer"):
    fact = {"fact_id": "n", "type": kind, "value": value, "rule": "SELECT 1"}
    if kind in ("integer", "decimal"):
        fact["tolerance"] = tolerance
    return reference(expected_identifiers=[], expected_facts=[fact])


def raising_config():
    kinds = CONFIG["identifier_kinds"]
    return {**CONFIG, "identifier_kinds": {**kinds, "invoice": {**kinds["invoice"], "pattern": "("}}}


ROWS = {
    "all present": (ALL, reference(), CONFIG, None, expect()),
    "an expected identifier missing": (
        ALL.replace("invoice 34", "an invoice"),
        reference(),
        CONFIG,
        None,
        expect(identifiers_complete=false("identifier_missing"), text_facts_success=false("identifier_missing")),
    ),
    "an unexpected identifier": (
        ALL + " See also invoice 35.",
        reference(),
        CONFIG,
        None,
        expect(no_unexpected_identifier=false("identifier_unexpected"), text_facts_success=false("identifier_unexpected")),
    ),
    "an identifier found that is allowed": (
        ALL + " See also INV-0035.",
        reference(allowed_identifiers=[{"kind": "invoice", "value": "35"}]),
        CONFIG,
        None,
        expect(),
    ),
    "an allowed identifier the answer does not name": (ALL, reference(allowed_identifiers=[{"kind": "invoice", "value": "35"}]), CONFIG, None, expect()),
    "an identifier found that is neither expected nor allowed": (
        ALL + " See also invoice 36.",
        reference(allowed_identifiers=[{"kind": "invoice", "value": "35"}]),
        CONFIG,
        None,
        expect(no_unexpected_identifier=false("identifier_unexpected"), text_facts_success=false("identifier_unexpected")),
    ),
    "an identifier with leading zeros": (ALL.replace("invoice 34", "INV-0034"), reference(), CONFIG, None, expect()),
    "an identifier with a separator": (ALL.replace("Customer 12", "Customer 1_2"), reference(), CONFIG, None, expect()),
    "an identifier in another case": (ALL.replace("invoice 34", "INVOICE 34"), reference(), CONFIG, None, expect()),
    "a number within tolerance": ("There are 130.004 of them.", count_fact(130.0, 0.005, "decimal"), CONFIG, None, expect()),
    "a number outside it": (
        "There are 130.01 of them.",
        count_fact(130.0, 0.005, "decimal"),
        CONFIG,
        None,
        expect(facts_present=false("fact_missing"), text_facts_success=false("fact_missing")),
    ),
    "a number inside an identifier against a count": (
        "Customer 12 bought some tracks.",
        reference(expected_identifiers=[{"kind": "customer", "value": "12"}], expected_facts=[count_fact(12)["expected_facts"][0]]),
        CONFIG,
        None,
        expect(facts_present=false("fact_missing"), text_facts_success=false("fact_missing")),
    ),
    "a number beside an identifier that holds it": (
        "Customer 12 has 12 invoices.",
        reference(expected_identifiers=[{"kind": "customer", "value": "12"}], expected_facts=[count_fact(12)["expected_facts"][0]]),
        CONFIG,
        None,
        expect(),
    ),
    "a year inside a date against a count": (
        "The first one was billed on 2010-03-11.",
        count_fact(2010),
        CONFIG,
        None,
        expect(facts_present=false("fact_missing"), text_facts_success=false("fact_missing")),
    ),
    "a number with , thousands": ("The total is $12,345.",  count_fact(12345), CONFIG, None, expect()),
    "a number with % against a plain fact": (
        "That is 45% of them.",
        count_fact(45),
        CONFIG,
        None,
        expect(facts_present=false("fact_missing"), text_facts_success=false("fact_missing")),
    ),
    "an ISO date": ("It was billed on 2009-05-23 00:00:00.", count_fact("2009-05-23", kind="date"), CONFIG, None, expect()),
    "a text fact in another case": ("The customer lives in BRAZIL.", count_fact("Brazil", kind="text"), CONFIG, None, expect()),
    "a Markdown table holding the identifiers": (
        "| Invoice | Customer | Date | Total | Country |\n|---|---|---|---|---|\n| INV-0034 | customer 12 | 2009-05-23 | 1,234.50 | Brazil |",
        reference(),
        CONFIG,
        None,
        expect(),
    ),
    "outcome declared and equal": ("Do you mean by spend?", reference(expected_identifiers=[], expected_facts=[], expected_outcome="needs_clarification"), NO_PHRASES, "needs_clarification", expect()),
    "outcome declared and different": (
        ALL,
        reference(),
        CONFIG,
        "not_answerable",
        expect(outcome_matches=false("outcome_mismatch"), text_facts_success=false("outcome_mismatch")),
    ),
    "no outcome, a phrase rule recognising a clarification": (
        "Could you clarify which measure you mean?",
        reference(expected_identifiers=[], expected_facts=[], expected_outcome="needs_clarification"),
        CONFIG,
        None,
        expect(),
    ),
    "no outcome, a phrase rule recognising a no-data answer": (
        "There is no data on refunds for invoice 98.",
        reference(expected_identifiers=[{"kind": "invoice", "value": "98"}], expected_facts=[], expected_outcome="not_answerable"),
        CONFIG,
        None,
        expect(),
    ),
    "no outcome and an answered Reference with no phrase recognised": (ALL, reference(), CONFIG, None, expect()),
    "no outcome and no phrase rules": (
        ALL,
        reference(),
        NO_PHRASES,
        None,
        expect(outcome_matches=("unscored", None, "outcome_not_declared"), text_facts_success=("unscored", None, "outcome_not_declared")),
    ),
    "Reference absent": (ALL, None, CONFIG, None, {name: ("unscored", None, "reference_missing") for name in text_facts.CRITERIA}),
    "Reference invalid": (
        ALL,
        reference(expected_outcome="maybe"),
        CONFIG,
        None,
        {name: ("unscored", None, "reference_invalid") for name in text_facts.CRITERIA},
    ),
    "Reference whose allowed_identifiers is not a list of {kind, value}": (
        ALL,
        reference(allowed_identifiers=[{"kind": "invoice"}]),
        CONFIG,
        None,
        {name: ("unscored", None, "reference_invalid") for name in text_facts.CRITERIA},
    ),
    "Reference allowing an identifier kind the config lacks": (
        ALL,
        reference(allowed_identifiers=[{"kind": "playlist", "value": "1"}]),
        CONFIG,
        None,
        {name: ("unscored", None, "reference_invalid") for name in text_facts.CRITERIA},
    ),
    "Reference naming an identifier kind the config lacks": (
        ALL,
        reference(expected_identifiers=[{"kind": "playlist", "value": "1"}]),
        CONFIG,
        None,
        {name: ("unscored", None, "reference_invalid") for name in text_facts.CRITERIA},
    ),
    "the function raising": (ALL, reference(), raising_config(), None, {name: ("errored", None, "scoring_failed") for name in text_facts.CRITERIA}),
}


@pytest.mark.parametrize("row", list(ROWS))
def test_text_facts_v1_gives_each_criterion_its_state_score_and_reason(row):
    answer, record, config, outcome, expected = ROWS[row]
    result = text_facts.apply(answer, record, config, outcome)
    assert [c["name"] for c in result["criteria"]] == list(text_facts.CRITERIA)
    assert {c["name"]: (c["state"], c["score"], c["reason"]) for c in result["criteria"]} == expected


def test_the_raw_answer_is_never_altered():
    answer = ALL + " 45%"
    kept = str(answer)
    text_facts.apply(answer, reference(), CONFIG)
    assert answer == kept


def test_the_committed_scoring_config_matches_its_schema():
    from importlib import resources

    from jsonschema import Draft202012Validator

    schema = json.loads(resources.files("hypotrail.core").joinpath("text-facts.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(CONFIG)) == []


KINDS = ("invoice", "customer", "track", "album")
# "number of", "count of" or "total" before the plural makes a count phrase, whose number is no identifier.
COUNT_FORMS = ("Number of {kind}s: 7", "number of {kind}s : 7.", "Count of {kind}s: 7", "Total {kind}s: 7", "Total number of {kind}s: 7", "We hold 7 {kind}s.")
# A labelled form names identifiers; a labelled list reads its first identifier only.
LABELLED_FORMS = (("{Kind}s: 269, 291, 293", {"269"}), ("{Kind}s: 16 and 24", {"16"}), ("{kind}s:7", {"7"}), ("{kind}s 7", {"7"}))
ID_FORMS = ("See {kind} 7.", "See {kind} #7.", "See {Kind}: 7.", "See {kind} no. 7.")


def values_of(kind, text):
    return {value for found, value in text_facts.identifiers_in(text, CONFIG) if found == kind}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("form", COUNT_FORMS)
def test_a_count_phrase_is_read_as_the_count_fact_and_names_no_identifier(form, kind):
    text = form.format(kind=kind)
    result = {c["name"]: (c["state"], c["score"], c["reason"]) for c in text_facts.score_text(text, count_fact(7), CONFIG, None)["criteria"]}
    assert result["facts_present"] == ("scored", True, None)
    assert text_facts.identifiers_in(text, CONFIG) == set()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("form", LABELLED_FORMS, ids=lambda form: form[0])
def test_a_labelled_form_reads_its_first_identifier_only(form, kind):
    text, first = form
    assert values_of(kind, text.format(kind=kind, Kind=kind.capitalize())) == first


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("form", ID_FORMS)
def test_a_record_named_by_its_number_is_read_as_that_identifier(form, kind):
    assert values_of(kind, form.format(kind=kind, Kind=kind.capitalize())) == {"7"}
