# Hypotrail

Hypotrail runs small, explicit studies of machine-learning models and LLM agents. It runs a configuration or imports outputs produced elsewhere, keeps those outputs, scores them against frozen references, and compares two configurations under one protocol. Unknowns, failures and wrong answers stay distinct, each with its own count.

## Status

Early development. The first milestone runs two public Workloads end to end: a daily bike-rental regression and a tool-using agent on the Chinook SQLite database (plan: chadlis/hypotrail#1). What exists: `init` creates a Study, `run ml` records a Bike Attempt, `import ml` and `import agent` adopt outputs produced elsewhere (a predictions CSV, agent answers, an Inspect log), `assess` scores them against the Study's References, `compare` writes a Comparison of two Assessments of either Track, and `status` and `recover` show and repair a Study's local state. A Study holds one frozen Protocol per revision (`init --new-revision`), a freeze record and an Exposure journal for `public_check`. There is no report yet. The handbook chapters give each capability in detail.

## Install

Needs [uv](https://docs.astral.sh/uv/) and Python 3.13.

```
uv sync --locked --all-extras                 # the core (Python plus jsonschema) needs no extra: uv sync --locked
uv run --locked --all-extras pytest           # offline: no network, no model call
uv run python -m hypotrail data verify        # check the public datasets
uv run python -m hypotrail init --workload bike_day --study runs/bike
uv run python -m hypotrail run ml --study runs/bike --config seasonal_7 --partition dev --request-id ml-dev-a
uv run python -m hypotrail assess --study runs/bike --observations OBSERVATION_SET_ID --scorer regression_mae_v1 --references REFERENCES_ID
uv run python -m hypotrail import ml --study runs/bike --source predictions.csv --mapping mapping.json --population population.json --request-id import-a
uv run python -m hypotrail init --workload chinook --study runs/chinook
uv run python -m hypotrail import agent --study runs/chinook --source answers.jsonl --population population.json --request-id import-b   # or --source LOG.eval, an Inspect log
uv run python -m hypotrail assess --study runs/chinook --observations OBSERVATION_SET_ID --scorer chinook_contract_v1 --references REFERENCES_ID
uv run python -m hypotrail compare --study runs/bike --control ASSESSMENT_ID --candidate ASSESSMENT_ID
uv run python -m hypotrail compare --study runs/chinook --control ASSESSMENT_ID --candidate ASSESSMENT_ID [--factor model]   # two agent Assessments
uv run python -m hypotrail init --study runs/chinook --new-revision    # after a corrected References file in the Workload
uv run python -m hypotrail status --study runs/bike --json                 # the freeze record, the Exposure journal and the check_informed marks too
```

A live spike is opt-in and paid, never part of the tests, and records no Attempt in a Study (it writes under `--out`): `python -m hypotrail spike live --config plain|verify --model anthropic/<model> --out DIR`, with the key in `HYPOTRAIL_ANTHROPIC_API_KEY` (see the handbook). The command was rehearsed offline, and one Attempt per Configuration (`plain`, `verify`; Cases D03 and D05, one Repeat each, on `anthropic/claude-sonnet-5-5`) is recorded under `docs/handbook/traces/live-l12-plain/` and `live-l12-verify/`, and a second Attempt per Configuration (2026-11-07, under the limits their `run.json` records) under `live-l12b-plain/` and `live-l12b-verify/`; they are not scored against References, and the owner reviewed the References of D07, D08, E11 and E12 on 2026-11-06, before these Attempts (chadlis/hypotrail#8); that review precedes any live Attempt.

## Where to look

- [`docs/handbook/`](docs/handbook/): the English handbook, built into [`handbook.html`](docs/handbook/handbook.html) with `python docs/handbook/build.py`.
- `src/hypotrail/` (`core/`, `agentic/`, `ml/`) and `examples/` (declarative Workloads and their data, such as `examples/bike_day`, and `examples/external/`, programs that stand in for someone else's and never import `hypotrail`); `tests/`.
- [`GLOSSARY.md`](GLOSSARY.md): the domain vocabulary.
- [`docs/adr/`](docs/adr/): architecture decisions and why they were made.
- [`docs/product/PRODUCT.md`](docs/product/PRODUCT.md): product direction: users, journeys and product boundaries.
- [`docs/product/ROADMAP.md`](docs/product/ROADMAP.md): milestone direction: current work, candidate milestones and legacy reuse.
- [`docs/product/PACKAGE-CANDIDATES.md`](docs/product/PACKAGE-CANDIDATES.md): package candidates: research leads to examine when a milestone needs them.
- [`AGENTS.md`](AGENTS.md): rules for contributors and coding agents.
- [`.claude/skills/drive/`](.claude/skills/drive/SKILL.md): how a slice is taken from its issue to a pull request (`/drive`, or `/drive #n` for a given slice), with the agent types it uses in [`.claude/agents/`](.claude/agents/).
- [chadlis/hypotrail-learning](https://github.com/chadlis/hypotrail-learning): the learning book (French) and the original specification of the first milestone.

## License

Not chosen yet.
