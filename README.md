# Hypotrail

Hypotrail runs small, explicit studies of machine-learning models and LLM agents. It runs a configuration or imports outputs produced elsewhere, keeps those outputs, scores them against frozen references, and compares two configurations under one protocol. Unknowns, failures and wrong answers stay distinct, each with its own count.

## Status

The first milestone runs two public Workloads end to end: a daily bike-rental regression and a tool-using agent on the Chinook SQLite database (chadlis/hypotrail#1). `init` creates a Study, `run ml` records a Bike Attempt, `run agent` records a Chinook Attempt, `import ml` and `import agent` adopt outputs produced elsewhere, `assess` scores them against References, `compare` writes a Comparison of two Assessments of either Track, `status` shows a Study's state and decision history, `recover` repairs it, `figures` summarizes paired deltas, `decide` records a decision, `deviation` a Declared deviation, `data verify` and `data fetch` check and acquire public data, and `report` renders one self-contained page. The handbook gives each capability in detail. A Study holds a frozen Protocol per revision and a write sequence.

Acceptance is test by test in the [acceptance grid](docs/handbook/handbook.html#acceptance-grid) (T01–T24). `OFFLINE_ACCEPTED` reached. `LIVE_ACCEPTED` conditional: References E01–E10 reviewed by proxy, owner review pending. The 2026-11-21 Campaign (T20 holds) did not alternate its Configurations, against AG-12 of the L1 specification (`SPEC-LOT-1.md`, linked from chadlis/hypotrail#1; chapter 16). `USABILITY_REVIEW_PENDING` open: an agent walked the README path, no other reader has; it is not claimed usable by a third party until one has. L2 was demonstrated by the owner on 2026-11-25 (D-132).

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
uv run python -m hypotrail status --study runs/bike --json                 # the freeze record, the Exposure journal, the check_informed marks, the write sequence, and the decisions with whether each still applies
```

`assess` takes two ids that the commands before it print: `OBSERVATION_SET_ID` is the Observation set ID that `run ml`, `import ml`, `run agent` and `import agent` print at the end of their line, after `Observation set`, and under `observation_set_id` with `--json`; `REFERENCES_ID` is the References ID that `init` and `init --new-revision` print at the end of theirs, after `references_id`, and under `references_id` with `--json`.

Every command that writes to an existing Study takes `--read-sequence N`, the write sequence its author read (`write_sequence` of `status --json`): when the Study was written to since, the command is refused with `STUDY_CHANGED` and writes nothing; not given, nothing is checked. `init` that creates a Study takes none (it is refused), and `report` compares it only when its page records an Exposure. `status --study runs/bike --since N --json` gives the same object as `status --json` plus `writes_since`, the write-journal entries after write sequence N; a value above the Study's is refused with `WRITE_SEQUENCE_AHEAD`. The contract between a client and the CLI is [ADR 0004](docs/adr/0004-panel-cli-contract.md).

`decide` records one decision in a Study and requires `--read-sequence`: `decide --study runs/bike --question TEXT --option TEXT --author human --artifact ASSESSMENT_ID --request-id decide-a --read-sequence N` (`--author human|proxy`, `--artifact` repeatable, `--source TEXT` optional). It is not part of the path above: that path is the one walked for T24.

Chinook `compare` (`compare --study runs/chinook --control ASSESSMENT_ID --candidate ASSESSMENT_ID [--factor model]`) needs two agent Assessments over the same Cases; the path above makes none, so it is not part of it.

`spike live` is opt-in and paid, never part of the tests, and records nothing in a Study (it writes under `--out`): `python -m hypotrail spike live --config plain|verify --model anthropic/<model> --out DIR [--examples-dir DIR]`, with the key in `HYPOTRAIL_ANTHROPIC_API_KEY` (see the handbook). The live Episodes kept in `docs/handbook/traces/` (`live-l12-*` of 2026-11-06 and `live-l12b-*` of 2026-11-07: Cases D03 and D05, one Repeat each, per Configuration, on `anthropic/claude-sonnet-5-5`) come from it and are not scored against References. The owner reviewed the References of D07, D08, E11 and E12 on 2026-11-06, before them (chadlis/hypotrail#8).

The one paid `run agent` Attempt (2026-11-20, `plain`, D03 and D05) is kept whole in `docs/handbook/traces/run-agent-live-plain/`. The live Campaign (2026-11-21, 72 Episodes on `public_check`: `plain` and `verify`, their Assessments, the Comparison and the report) is kept whole in `docs/handbook/traces/campaign-public-check/`.

## Use the VS Code panel

The VS Code client shows a Study's pending decisions with their evidence, including figures of each Comparison's paired deltas, and records a Decision through the CLI. From a checkout:

1. `uv sync --locked --all-extras` at the checkout root.
2. `npm ci && npm run compile` in `clients/vscode/`.
3. In VS Code, `Developer: Install Extension from Location...` and pick `clients/vscode/`.

Then open the checkout, or a Study's folder, and run the command "Hypotrail: Open the Study panel". The handbook's chapter on the client gives the detail.

The extension also gives Copilot chat in VS Code two tools: `hypotrail_read_study` reads the Study, and `hypotrail_decide` records a Decision through `decide` once you confirm it in VS Code (unless you chose "Always Allow" for the tool).

## Give Claude Code the Study at every prompt

`clients/claude-code/` holds a template of a Claude Code `UserPromptSubmit` hook: at every prompt it reads one Study with `status --since 0 --json` and adds, as context, its write sequence, its pending decisions and its decisions, with the rule for an agent (pass the write sequence read as `--read-sequence`; record a rule-based answer with `decide --author proxy` and a `--source`). On a checkout installed with `uv sync`, copy `clients/claude-code/settings-fragment.json` into `.claude/settings.local.json` and set its `--study` to the Study's folder, one entry per Study. It writes and keeps nothing; this repository's `.claude/settings.json` does not register it. The handbook's chapter on the client gives the detail.

## Give Copilot the rule for a Study

`clients/vscode/copilot-instructions.md` is a template of Copilot's instructions file. It tells Copilot chat to read the Study with `hypotrail_read_study` at the start of each turn, to pass the `write_sequence` it read as `read_sequence` on every write, to record a Decision only through `hypotrail_decide`, and to record an answer chosen by a stated rule with `author` `proxy` and a `source` that names the rule. Copy it to `.github/copilot-instructions.md` in the workspace that holds the Study; this repository's own `.github/` holds none. The handbook's chapter on the client gives the detail.

## Where to look

- [`docs/handbook/`](docs/handbook/): the English handbook, built into [`handbook.html`](docs/handbook/handbook.html) with `python docs/handbook/build.py`.
- [`docs/handbook/handbook.html#acceptance-grid`](docs/handbook/handbook.html#acceptance-grid): the acceptance grid T01–T24, with the three statuses and the account of the live Campaign (T20).
- [`docs/handbook/walk-t24.html`](docs/handbook/walk-t24.html): the record of the clean-install walk of the README's path (T24).
- [`docs/product/l2-acceptance.md`](docs/product/l2-acceptance.md): the L2 acceptance grid: each criterion with its tests, its owner checks and its engineer checks.
- [`docs/demo/demonstration.py`](docs/demo/demonstration.py): the frozen demonstration, a first Bike Study, a second on a Workload copy that records, outdates and refuses Decisions, then Chinook, with no live model call and no network: `uv run python docs/demo/demonstration.py --work DIR`, DIR a new folder outside the checkout; the end-to-end tests run its steps (the handbook's chapter on the demonstration).
- [`docs/demo/edit_copy.py`](docs/demo/edit_copy.py): the script that makes each edit of task 6 of the L2 demonstration in a Workload copy and rewrites the copy's lock (the handbook's chapter on the L2 demonstration).
- `src/hypotrail/` (`core/`, `agentic/`, `ml/`, `report/`) and `examples/` (declarative Workloads and their data, such as `examples/bike_day`, and `examples/external/`, programs that stand in for someone else's and never import `hypotrail`); `tests/`.
- [`clients/vscode/`](clients/vscode/): the VS Code client (the extension, its CLI bridge, the Study panel and the Copilot tools).
- [`clients/vscode/copilot-instructions.md`](clients/vscode/copilot-instructions.md): the template of Copilot's instructions file, copied to `.github/copilot-instructions.md` in a workspace that holds a Study.
- [`clients/claude-code/`](clients/claude-code/): the Claude Code `UserPromptSubmit` hook template (the script and the settings fragment that registers it).
- [`GLOSSARY.md`](GLOSSARY.md): the domain vocabulary.
- [`docs/adr/`](docs/adr/): architecture decisions and why they were made.
- [`docs/product/PRODUCT.md`](docs/product/PRODUCT.md): product direction: users, journeys and product boundaries.
- [`docs/product/ROADMAP.md`](docs/product/ROADMAP.md): milestone direction: current work, the selected milestones L2 and L3, later options and legacy reuse.
- [`docs/product/PACKAGE-CANDIDATES.md`](docs/product/PACKAGE-CANDIDATES.md): package candidates: research leads to examine when a milestone needs them.
- [`AGENTS.md`](AGENTS.md): rules for contributors and coding agents.
- [`.claude/skills/drive/`](.claude/skills/drive/SKILL.md): how a slice is taken from its issue to a pull request (`/drive`, or `/drive #n` for a given slice), with the agent types it uses in [`.claude/agents/`](.claude/agents/) and the checks on its fix prompts and merges (`premises.py`, `fix_prompt_check.py`, `post_fix_prompt.sh`, `check_record.py`; the hooks are registered in [`.claude/settings.json`](.claude/settings.json)).
- [`.claude/skills/verify-panel/`](.claude/skills/verify-panel/SKILL.md): a contact sheet of the VS Code client's Study panel at a given head, in VS Code's four default themes, drawn by headless Chrome.
- [chadlis/hypotrail-learning](https://github.com/chadlis/hypotrail-learning): the learning book (French) and the original specification of the first milestone.

## License

Not chosen yet.
