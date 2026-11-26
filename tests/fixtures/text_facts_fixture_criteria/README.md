# The Criteria of the chinook_prose fixtures at 941ffd8

`criteria-941ffd8.jsonl` pins, before the block reader of `text_facts_v1` (chadlis/hypotrail#271), the five Criteria of:

- every fixture answer line of `examples/chinook_prose/fixtures/`, with the outcome its line declares;
- every `reference_text` of `examples/chinook_prose/references/chinook-prose-references.jsonl`, against its own Reference,
  with no declared outcome.

One row per line: its `source`, its `case_id`, and each Criterion as `[state, score, reason]`. The table was computed by
running `text_facts.apply` from a checkout of 941ffd8, not from the code that reads it now. It is not edited by hand.

## Differences at the block reader

None. All 96 rows (60 fixture answers and 36 reference texts) give the same state, score and reason under the block
reader as at 941ffd8. `tests/test_text_facts_fixture_criteria.py` holds every row to that.
