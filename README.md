# Hypotrail

Hypotrail runs small, explicit studies of machine-learning models and LLM agents. It runs a configuration or imports outputs produced elsewhere, keeps those outputs, scores them against frozen references, and compares two configurations under one protocol. Unknowns, failures and wrong answers stay distinct, each with its own count.

## Status

Early development. The first milestone runs two public Workloads end to end: a daily bike-rental regression and a tool-using agent on the Chinook SQLite database (plan: chadlis/hypotrail#1). So far only the feasibility spike exists: a locked Python 3.13 environment, verified datasets, an Inspect task where a model calls a read-only SQL tool on Chinook, scoring of a kept log, and one recorded live trace. There is no study, comparison or report yet.

## Install

Needs [uv](https://docs.astral.sh/uv/) and Python 3.13.

```
uv sync --locked --all-extras                 # the core alone needs no extra: uv sync --locked
uv run --locked --all-extras pytest           # offline: no network, no model call
uv run python -m hypotrail data verify        # check the public datasets
```

A live model run is opt-in and paid, never part of the tests: `python -m hypotrail spike live --model anthropic/<model> --out DIR`, with the key in `HYPOTRAIL_ANTHROPIC_API_KEY` (see the handbook).

## Where to look

- [`docs/handbook/`](docs/handbook/): the English handbook, built into [`handbook.html`](docs/handbook/handbook.html) with `python docs/handbook/build.py`.
- `src/hypotrail/` (the core, agentic and later ML code) and `examples/` (declarative Workloads and their data); `tests/`.
- [`GLOSSARY.md`](GLOSSARY.md): the domain vocabulary.
- [`docs/adr/`](docs/adr/): architecture decisions and why they were made.
- [`AGENTS.md`](AGENTS.md): rules for contributors and coding agents.
- [`.claude/skills/drive/`](.claude/skills/drive/SKILL.md): how a slice is taken from its issue to a pull request (`/drive`, or `/drive #n` for a given slice).
- [chadlis/hypotrail-learning](https://github.com/chadlis/hypotrail-learning): the learning book (French) and the original specification of the first milestone.

## License

Not chosen yet.
