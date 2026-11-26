# agent-answers/1

Owner: chadlis/hypotrail. Copy: chadlis/agentkit, `contracts/agent-answers-1/`, byte for byte, pinned in its `contracts.lock.json`. The decision is D-172 on chadlis/hypotrail#75 (C3).

A kit writes `answers.jsonl` and `population.json`; `hypotrail import agent` reads them. Until now the contract was `LINE_KEYS` in `agentic/imports.py` and section 2.1 of agentkit's design; this directory writes it down.

**Status.** The consumer that accepts `outcome`, `usage`, `metadata` and `settings` is on `claude/s1-263` (`941ffd8`), not on `main`. The test that compares this schema with `LINE_KEYS`, `USAGE_FIELDS` and `OUTCOMES` is a strict expected failure until S1 reaches `main`: the pull request that merges S1 removes the marker. Version 1 is frozen at that merge (SP1 of D-172).

## Files

| Schema | Describes |
|---|---|
| `line.schema.json` | One line of `answers.jsonl`: one (Case, Repeat) of the run, a `failed` or `missing` pair included |
| `population.schema.json` | `population.json`: `{"episodes": [{"case_id", "repeat"}, ...]}`, all Cases of one Partition |

JSON Schema 2020-12. Each line is checked on its own.

## Rules a schema cannot say

- `settings` is the same object on every line of a file, or the Observation set records it `unknown`.
- A measure the producer does not know is `null`, never 0.
- A `failed` or `missing` pair still has its line; the lines and the population are the same set of pairs.
- The kit writes `raw_answer`, never `final_answer`.

## Examples

`examples/answers.jsonl` and `examples/population.json`: one `produced` line and one `failed` line, shortened from `examples/chinook_prose/fixtures/answers-concise.jsonl` on `claude/s1-263`.

`examples/refused/<case>/` holds one refused case each, with `expected.json`: the contract, the refusal `code` of `import agent` at `941ffd8` (null when that import does not refuse it), the `exit`, and `caught_by`. All four are refused by the schema. An unknown key is ignored by the import at `941ffd8`; the schema refuses it. Which side moves is open until version 1 is frozen at the S1 merge.

## Tests

`tests/test_contracts_agent_answers.py`.

## Changes

`docs/contracts/CHANGELOG.md`. A change that makes a once-valid line invalid, or changes what a valid line means, is `agent-answers/2`.
