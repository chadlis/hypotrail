# agent-answers/1

Owner: chadlis/hypotrail. Copy: chadlis/agentkit, `contracts/agent-answers-1/`, byte for byte, pinned in its `contracts.lock.json`. The decision is D-172 on chadlis/hypotrail#75 (C3).

A kit writes `answers.jsonl` and `population.json`; `hypotrail import agent` reads them. Until now the contract was `LINE_KEYS` in `agentic/imports.py` and section 2.1 of agentkit's design; this directory writes it down.

**Status.** The consumer has accepted `outcome`, `usage`, `metadata` and `settings` since S1 (`04b5806`). `tests/test_contracts_agent_answers.py` compares this schema with `LINE_KEYS`, `USAGE_FIELDS` and `OUTCOMES` and calls `import agent` on the examples. A new Import with an unknown top-level line key is refused with `LINE_KEY_UNKNOWN` (chadlis/hypotrail#278). An existing request with an unchanged request identity can still replay its recorded Import. Copies move through contract-pin pull requests.

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
- Historical sources may include `unknown_fields`, an advisory array of strings. The original file retains the array. Hypotrail derives the Observation set's provenance and its list of unknown fields independently.

## Examples

`examples/answers.jsonl` and `examples/population.json`: one `produced` line and one `failed` line, shortened from `examples/chinook_prose/fixtures/answers-concise.jsonl`.

Each directory in `examples/refused/` contains one case the schema and importer refuse. Its `expected.json` records the contract, the importer refusal code, the exit code and `caught_by`.

## Tests

`tests/test_contracts_agent_answers.py`.

## Changes

`docs/contracts/CHANGELOG.md`. A change that makes a once-valid line invalid, or changes what a valid line means, is `agent-answers/2`.
