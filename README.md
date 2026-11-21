# Hypotrail

Hypotrail runs small, explicit studies of machine-learning models and LLM agents. It runs a configuration or imports outputs produced elsewhere, keeps those outputs, scores them against frozen references, and compares two configurations under one protocol. Unknowns, failures and wrong answers stay distinct, each with its own count.

## Status

Early development. The first milestone runs two public Workloads end to end: a daily bike-rental regression and a tool-using agent on the Chinook SQLite database (plan: chadlis/hypotrail#1). What exists: `init` creates a Study, `run ml` records a Bike Attempt, `run agent` records a Chinook Attempt (the scenarios with Inspect's mock model, or an opt-in paid live Attempt), `import ml` and `import agent` adopt outputs produced elsewhere, `assess` scores them against the Study's References, `compare` writes a Comparison of two Assessments of either Track, `status` and `recover` show and repair a Study's state, `data verify` and `data fetch` check and acquire the public data, and `report` renders one self-contained HTML page for a Study. A Study holds one frozen Protocol per revision, a freeze record and an Exposure journal for `public_check`. The handbook gives each capability in detail.

Acceptance is test by test in the [acceptance grid](docs/handbook/handbook.html#acceptance-grid) (T01–T24). `OFFLINE_ACCEPTED` reached. `LIVE_ACCEPTED` conditional: References E01–E10 reviewed by proxy, owner review pending. The Campaign ran on 2026-11-21 (T20 holds); its Configurations' order was not alternated (AG-12). `USABILITY_REVIEW_PENDING` open: an agent walked the README path, no other reader has, and it is not claimed usable by a third party until one has.

## Install

Needs [uv](https://docs.astral.sh/uv/) and Python 3.13.

The supported install is a checkout with `uv sync`: the commands below find the Workloads in its `examples/`. No Workload is packaged in the wheel, so any other install passes `--examples-dir` with the directory (a checkout's `examples/` or a copy); without it, such an install is refused before anything is written. A checkout already holds the verified data. A copy that lacks a data file acquires it with `data fetch` (below): the file comes from its lock's URL, is checked against the lock, and a file that is already there is left or refused, never replaced (to acquire it again, remove it first).

```
uv sync --locked --all-extras                 # the core (Python plus jsonschema) needs no extra: uv sync --locked
uv run --locked --all-extras pytest           # offline: no network, no model call
uv run python -m hypotrail data verify        # check the public datasets
uv run python -m hypotrail data fetch --lock examples/bike_day/data-sources.lock.json --dest examples/bike_day    # acquire a missing data file from the lock's URL, checked against the lock
uv run python -m hypotrail init --workload bike_day --study runs/bike
uv run python -m hypotrail run ml --study runs/bike --config seasonal_7 --partition dev --request-id ml-dev-a
uv run python -m hypotrail assess --study runs/bike --observations OBSERVATION_SET_ID --scorer regression_mae_v1 --references REFERENCES_ID
uv run python -m hypotrail import ml --study runs/bike --source predictions.csv --mapping mapping.json --population population.json --request-id import-a
uv run python -m hypotrail init --workload chinook --study runs/chinook
uv run python -m hypotrail run agent --study runs/chinook --mode scripted_fixture --config plain --request-id fixture-a    # the scenarios: mock model, no key
uv run python -m hypotrail run agent --study runs/chinook --mode llm_live --config plain --partition dev --cases D03 --cases D05 --repeats 1 --model anthropic/<model> --request-id live-a    # opt-in, paid, needs the key
uv run python -m hypotrail import agent --study runs/chinook --source docs/handbook/traces/run-agent-live-plain/inspect/2026-11-20T21-46-56-00-00_chinook-plain_e5SoHDfMBV3vBUjsjaQWVu.eval --population population.json --request-id import-b   # the kept Inspect log; or --source answers.jsonl, agent answers
uv run python -m hypotrail assess --study runs/chinook --observations OBSERVATION_SET_ID --scorer chinook_contract_v1 --references REFERENCES_ID
uv run python -m hypotrail compare --study runs/bike --control ASSESSMENT_ID --candidate ASSESSMENT_ID
uv run python -m hypotrail report --study runs/bike --out runs/bike-report.html    # one HTML page, outside the Study
uv run python -m hypotrail report --study runs/chinook --out runs/chinook-report.html    # the same page for a Chinook Study
uv run python -m hypotrail init --study runs/chinook --new-revision    # after a corrected References file or a changed Cases file in the Workload
uv run python -m hypotrail status --study runs/bike --json                 # the freeze record, the Exposure journal and the check_informed marks too
```

Chinook `compare` (`compare --study runs/chinook --control ASSESSMENT_ID --candidate ASSESSMENT_ID [--factor model]`) needs two agent Assessments over the same Cases; the path above makes none, so it is not part of it.

`spike live` is opt-in and paid, never part of the tests, and records nothing in a Study (it writes under `--out`): `python -m hypotrail spike live --config plain|verify --model anthropic/<model> --out DIR [--examples-dir DIR]`, with the key in `HYPOTRAIL_ANTHROPIC_API_KEY` (see the handbook). The live Episodes kept in `docs/handbook/traces/` (`live-l12-*` of 2026-11-06 and `live-l12b-*` of 2026-11-07: Cases D03 and D05, one Repeat each, per Configuration, on `anthropic/claude-sonnet-5-5`) come from it and are not scored against References. The owner reviewed the References of D07, D08, E11 and E12 on 2026-11-06, before them (chadlis/hypotrail#8).

The one paid `run agent` Attempt (2026-11-20, `plain`, D03 and D05) is kept whole in `docs/handbook/traces/run-agent-live-plain/`. The live Campaign (2026-11-21, 72 Episodes on `public_check`: `plain` and `verify`, their Assessments, the Comparison and the report) is kept whole in `docs/handbook/traces/campaign-public-check/`.

## Where to look

- [`docs/handbook/`](docs/handbook/): the English handbook, built into [`handbook.html`](docs/handbook/handbook.html) with `python docs/handbook/build.py`.
- [`docs/handbook/handbook.html#acceptance-grid`](docs/handbook/handbook.html#acceptance-grid): the acceptance grid T01–T24, with the three statuses and the account of the live Campaign (T20).
- [`docs/handbook/walk-t24.html`](docs/handbook/walk-t24.html): the record of the clean-install walk of the README's path (T24).
- `src/hypotrail/` (`core/`, `agentic/`, `ml/`, `report/`) and `examples/` (declarative Workloads and their data, such as `examples/bike_day`, and `examples/external/`, programs that stand in for someone else's and never import `hypotrail`); `tests/`.
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
