# agent-answers/1

Owner: chadlis/hypotrail. Copy: chadlis/agentkit, `contracts/agent-answers-1/`, byte for byte, pinned in its `contracts.lock.json`. The decision is D-172 on chadlis/hypotrail#75 (C3).

A kit writes `answers.jsonl` and `population.json`; `hypotrail import agent` reads them. Until now the contract was `LINE_KEYS` in `agentic/imports.py` and section 2.1 of agentkit's design; this directory writes it down.

**Status.** The consumer that accepts `outcome`, `usage`, `metadata` and `settings` is on `main` since S1 (`04b5806`). `tests/test_contracts_agent_answers.py` compares this schema with `LINE_KEYS`, `USAGE_FIELDS` and `OUTCOMES` on `main`, and runs `import agent` on the examples. One known difference is kept and pinned by a test: an unknown key, which the schema refuses and `import agent` ignores (chadlis/hypotrail#278 decides which side moves, before the SP1 freeze of D-172). The copies in chadlis/agentkit and chadlis/mlkit pin `owner_commit` to a commit of `claude/contracts`; the final pin, to the merge commit, comes when chadlis/hypotrail#274 merges.

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

`examples/answers.jsonl` and `examples/population.json`: one `produced` line and one `failed` line, shortened from `examples/chinook_prose/fixtures/answers-concise.jsonl`.

`examples/refused/<case>/` holds one refused case each, with `expected.json`: the contract, the refusal `code` of `import agent` on `main` (null when that import does not refuse it), the `exit`, and `caught_by`. All four are refused by the schema. `unknown-key` is the one the import accepts: it ignores the key. Which side moves is open in chadlis/hypotrail#278.

## Tests

`tests/test_contracts_agent_answers.py`.

## Changes

`docs/contracts/CHANGELOG.md`. A change that makes a once-valid line invalid, or changes what a valid line means, is `agent-answers/2`.
