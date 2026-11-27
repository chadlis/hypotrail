# Hypotrail

Hypotrail runs small, explicit studies of machine-learning models and LLM agents. It runs a configuration or imports outputs produced elsewhere, keeps those outputs, scores them against frozen references, and compares two configurations under one protocol. Unknowns, failures and wrong answers stay distinct, each with its own count.

## Status

The first milestone runs two public Workloads end to end: a daily bike-rental regression and a tool-using agent on Chinook's SQLite database (chadlis/hypotrail#1). `init` creates a Study, `run ml` records a Bike Attempt, `run agent` records a Chinook Attempt, `import ml` and `import agent` adopt outputs produced elsewhere, `assess` scores them against References, `compare` writes a Comparison of two Assessments of either Track, `status` shows a Study's state and decision history, `recover` repairs it, `figures` summarizes paired deltas, `profile` reads a Bike Study's `train` data, `lesson` any Study's cards, `decide` records a decision, `deviation` a Declared deviation, `data verify` and `data fetch` check and acquire public data, and `report` renders one self-contained page. The handbook gives each capability in detail. Studies hold a frozen Protocol per revision and a write sequence.

The [acceptance grid](docs/handbook/handbook.html#acceptance-grid) holds acceptance, test by test (T01–T24). `OFFLINE_ACCEPTED` reached. `LIVE_ACCEPTED` conditional: References E01–E10 reviewed by proxy, owner review pending. The 2026-11-21 Campaign (T20 holds) did not alternate its Configurations, against AG-12 of the L1 specification (`SPEC-LOT-1.md`, linked from chadlis/hypotrail#1; chapter 16). `USABILITY_REVIEW_PENDING` open: only an agent walked the README path; no third-party usability is claimed until another reader has. L2 was demonstrated on 2026-11-25 (D-132 on chadlis/hypotrail#75).

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
uv run python -m hypotrail assess --study runs/chinook --observations OBSERVATION_SET_ID --scorer chinook_contract_v1 --references REFERENCES_ID    # a chinook_prose Study takes --scorer text_facts_v1
uv run python -m hypotrail compare --study runs/bike --control ASSESSMENT_ID --candidate ASSESSMENT_ID
uv run python -m hypotrail report --study runs/bike --out runs/bike-report.html    # one HTML page, outside the Study
uv run python -m hypotrail report --study runs/chinook --out runs/chinook-report.html    # the same page for a Chinook Study
uv run python -m hypotrail init --study runs/chinook --new-revision    # after a corrected References file or a changed Cases file in the Workload
uv run python -m hypotrail status --study runs/bike --json                 # the freeze record, the Exposure journal, the check_informed marks, the write sequence, and the decisions with whether each still applies
```

`assess` takes two ids that the commands before it print: `OBSERVATION_SET_ID` is the Observation set ID that `run ml`, `import ml`, `run agent` and `import agent` print at the end of their line, after `Observation set`, and under `observation_set_id` with `--json`; `REFERENCES_ID` is the References ID that `init` and `init --new-revision` print at the end of theirs, after `references_id`, and under `references_id` with `--json`.

Every command that writes to an existing Study takes `--read-sequence N`, the write sequence its author read (`write_sequence` of `status --json`): when the Study was written to since, the command is refused with `STUDY_CHANGED` and writes nothing; not given, nothing is checked. `init` that creates a Study takes none (it is refused), and `report` compares it only when its page records an Exposure. `status --study runs/bike --since N --json` gives the same object as `status --json` plus `writes_since`, the write-journal entries after write sequence N; a value above the Study's is refused with `WRITE_SEQUENCE_AHEAD`. The contract between a client and the CLI is [ADR 0004](docs/adr/0004-panel-cli-contract.md).

`decide` records one decision in a Study and requires `--read-sequence`: `decide --study runs/bike --question TEXT --option TEXT --author human --artifact ASSESSMENT_ID --request-id decide-a --read-sequence N` (`--author human|proxy`, `--artifact` repeatable, `--source TEXT` optional; `--question-id` and `--option-id` name the pending decision answered, and `--words-file FILE` or `--words TEXT`, with `--channel` and `--by`, record a human's own words whole on the Decision). It is not part of the path above: that path is the one walked for T24.

A Comparison carries an interval on its delta, resampled over the unit its Workload declares: Cases for Chinook, days in circular blocks of 7 for Bike, whole groups of paraphrased Cases for `chinook_prose` ("over N groups"); a Study made before that declaration gets none until `init --new-revision`. An agent Comparison of Imports also lists each setting the two sides declare as `equal`, `different` or `unknown`, without changing its comparability.

Chinook `compare` (`compare --study runs/chinook --control ASSESSMENT_ID --candidate ASSESSMENT_ID [--factor model]`) needs two agent Assessments over the same Cases; the path above makes none, so it is not part of it.

A `chinook_prose` Study takes prose answers with `usage`, `metadata` and `settings` on each line, then `assess --scorer text_facts_v1`; it is not part of the path above: `import agent --study runs/chinook-prose --source examples/chinook_prose/fixtures/answers-concise.jsonl --population population.json --request-id import-prose`, after `init --workload chinook_prose --study runs/chinook-prose`.

Check a lesson pack without a Study with `python -m hypotrail lesson check PACK_DIR --kept clients/vscode/test/cli`.

`spike live` is opt-in and paid, never part of the tests, and records nothing in a Study (it writes under `--out`): `python -m hypotrail spike live --config plain|verify --model anthropic/<model> --out DIR [--examples-dir DIR]`, with the key in `HYPOTRAIL_ANTHROPIC_API_KEY` (see the handbook). The live Episodes kept in `docs/handbook/traces/` (`live-l12-*` of 2026-11-06 and `live-l12b-*` of 2026-11-07: Cases D03 and D05, one Repeat each, per Configuration, on `anthropic/claude-sonnet-5-5`) come from it and are not scored against References. The owner reviewed the References of D07, D08, E11 and E12 on 2026-11-06, before them (chadlis/hypotrail#8).

The one paid `run agent` Attempt (2026-11-20, `plain`, D03 and D05) is kept whole in `docs/handbook/traces/run-agent-live-plain/`. The live Campaign (2026-11-21, 72 Episodes on `public_check`: `plain` and `verify`, their Assessments, the Comparison and the report) is kept whole in `docs/handbook/traces/campaign-public-check/`.

A third Workload, `examples/chinook_prose`, is a data assistant that answers in prose about the same Chinook bytes, which it declares by a data manifest of digests (`data-manifest.json`) and never opens: it is evaluated only through `import agent`, and `run agent` refuses it.

The Chinook Workload holds 100 `dev` Cases, the 8 of the kit and 92 whose References two writers wrote apart (the review record is `examples/chinook/references/chinook-references-2.review.jsonl`), and 12 `public_check` Cases. The live Campaign on `dev` (2026-11-26, `plain` and `verify`, one Repeat each, its plan, ceiling, captures, estimated spend and report) is kept whole in `docs/handbook/traces/campaign-chinook-dev/`, its Study in `docs/handbook/traces/campaign-chinook-dev/study/`. The demonstration, in `docs/demo/`, compares and decides again on a copy of that Study, offline, then gives the copy a new revision whose Workload declares its resampling and compares with an interval over Cases. The handbook's chapter on the larger Chinook Workload gives the detail.

## Use the VS Code panel

The VS Code client shows a Study on one page: a band with the Write sequence and the number of writes since its last read, then "Now", which says what waits, from the core's `next_step`: the first pending decision, whole, with its evidence, including figures of its Comparison's paired deltas, and each other pending decision under "Waiting", folded to its question. "The Study so far" follows, in moments ("Frame", "Produce", "Assess and compare", "Decide and follow") with one line per step, which folds open to its review form, then its chart, then its limitation; on a Bike Study its first step is "Data profile", the `profile` read of the `train` data drawn as figures; then "Tools". Between "Waiting" and "The Study so far" stand the lesson cards the Study's Track serves (`lesson --json`), each a closed fold that explains a kind of step shown and, while open, outlines where the panel shows the values it speaks of. It records a Decision through the CLI. A control beside each output path it shows, and beside the path of each record's own file, opens that file in the editor, read-only. From a checkout:

1. `uv sync --locked --all-extras` at the checkout root.
2. `npm ci && npm run compile` in `clients/vscode/`.
3. In VS Code, `Developer: Install Extension from Location...` and pick `clients/vscode/`.

Then open the checkout, or a Study's folder, and run the command "Hypotrail: Open the Study panel". The handbook's chapter on the client gives the detail.

The extension also gives Copilot chat in VS Code three tools: `hypotrail_read_study` reads the Study and its lesson cards, and `hypotrail_decide` records a Decision through `decide` once you confirm it in VS Code (unless you chose "Always Allow" for the tool). Given your own messages as `words`, it records them whole on the Decision as relayed by Copilot (`chat_relayed`), and its confirmation shows them.
`hypotrail_run` can run `run`, `assess`, `compare`, `profile` and `report` on the Study once you confirm it. It refuses other commands, the paid Mode `llm_live` and reads of `public_check` Items. The CLI checks the Partition again under the Study's lock before opening the payloads of a guarded Assessment, Comparison or report. See `clients/vscode/run-tool.contract.md` for the command and refusal lists.

## Give Claude Code the Study at every prompt

`clients/claude-code/` holds a template of a Claude Code `UserPromptSubmit` hook: at every prompt it reads one Study with `status --since 0 --json` and adds, as context, its write sequence, its pending decisions and its decisions (each with the channel of its words, never the words), with the rule for an agent (pass the write sequence read as `--read-sequence`; record a rule-based answer with `decide --author proxy` and a `--source`; when the person states the choice, record their own words with `--words-file` and the pending decision's `--question-id` and `--option-id`). On a checkout installed with `uv sync`, copy `clients/claude-code/settings-fragment.json` into `.claude/settings.local.json` and set its `--study` to the Study's folder, one entry per Study. It writes and keeps nothing; this repository's `.claude/settings.json` does not register it. The handbook's chapter on the client gives the detail.

## Give Copilot the rule for a Study

`clients/vscode/copilot-instructions.md` is a template of Copilot's instructions file. It tells Copilot chat to read the Study with `hypotrail_read_study` at the start of each turn, to pass the `write_sequence` it read as `read_sequence` on every write, to record a Decision only through `hypotrail_decide`, to record an answer chosen by a stated rule with `author` `proxy` and a `source` that names the rule, and, when the user states the choice, to pass the user's own messages as `words` with `question_id` and `option_id`. Copy it to `.github/copilot-instructions.md` in the workspace that holds the Study; this repository's own `.github/` holds none. The handbook's chapter on the client gives the detail.

For guided use, copy [the Hypotrail Guide agent](clients/vscode/hypotrail-guide.agent.md) into the workspace's `.github/agents/` and select **Hypotrail Guide** in Copilot Chat. It uses the Study's lesson cards and directs you to Record in the panel for your Decision.

## Where to look

- [`docs/handbook/`](docs/handbook/): the English handbook, built into [`handbook.html`](docs/handbook/handbook.html) with `python docs/handbook/build.py`.
- [`docs/handbook/handbook.html#acceptance-grid`](docs/handbook/handbook.html#acceptance-grid): the acceptance grid T01–T24, with the three statuses and the account of the live Campaign (T20).
- [`docs/handbook/walk-t24.html`](docs/handbook/walk-t24.html): the record of the clean-install walk of the README's path (T24).
- [`docs/product/l2-acceptance.md`](docs/product/l2-acceptance.md): the L2 acceptance grid: each criterion with its tests, its owner checks and its engineer checks.
- [`docs/demo/demonstration.py`](docs/demo/demonstration.py): the frozen demonstration, a first Bike Study, a second on a Workload copy that records, outdates and refuses Decisions, then Chinook, then a copy of the kept Chinook Campaign, with no live model call and no network: `uv run python docs/demo/demonstration.py --work DIR`, DIR a new folder outside the checkout; the end-to-end tests run its steps (the handbook's chapter on the demonstration).
- [`docs/demo/edit_copy.py`](docs/demo/edit_copy.py): the script that makes each edit of task 6 of the L2 demonstration in a Workload copy and rewrites the copy's lock (the handbook's chapter on the L2 demonstration).
- `src/hypotrail/` (`core/`, `agentic/`, `ml/`, `report/`) and `examples/` (declarative Workloads and their data, such as `examples/bike_day`, and `examples/external/`, programs that stand in for someone else's and never import `hypotrail`); `tests/`.
- [`clients/vscode/`](clients/vscode/): the VS Code client (the extension, its CLI bridge, the Study panel and the Copilot tools).
- [`clients/vscode/run-tool.contract.md`](clients/vscode/run-tool.contract.md): the contract of the Copilot run tool, with its case corpus under `clients/vscode/test/run-tool-corpus/`.
- [`clients/vscode/copilot-instructions.md`](clients/vscode/copilot-instructions.md): the template of Copilot's instructions file, copied to `.github/copilot-instructions.md` in a workspace that holds a Study.
- [`clients/claude-code/`](clients/claude-code/): the Claude Code `UserPromptSubmit` hook template (the script and the settings fragment that registers it).
- [`GLOSSARY.md`](GLOSSARY.md): the domain vocabulary.
- [`docs/adr/`](docs/adr/): architecture decisions and why they were made.
- `src/hypotrail/ml/contracts/` and `src/hypotrail/agentic/contracts/`: the file formats that chadlis/mlkit and chadlis/agentkit write for `import ml` and `import agent` (JSON Schemas, examples, refused cases), with their changes in [`docs/contracts/CHANGELOG.md`](docs/contracts/CHANGELOG.md). The ranking Track's contract, [`docs/contracts/ranking-track.md`](docs/contracts/ranking-track.md), says what the ranking Track will read from chadlis/mlkit.
- [`docs/product/PRODUCT.md`](docs/product/PRODUCT.md): product direction: users, journeys and product boundaries.
- [`docs/product/ROADMAP.md`](docs/product/ROADMAP.md): milestone direction: current work, the selected milestones L2 and L3, later options and legacy reuse.
- [`docs/product/PACKAGE-CANDIDATES.md`](docs/product/PACKAGE-CANDIDATES.md): package candidates: research leads to examine when a milestone needs them.
- [`AGENTS.md`](AGENTS.md): rules for contributors and coding agents.
- [`.claude/skills/drive/`](.claude/skills/drive/SKILL.md): how a slice is taken from its issue to a pull request (`/drive`, or `/drive #n` for a given slice), with the agent types it uses in [`.claude/agents/`](.claude/agents/) and the checks on its fix prompts and merges (`premises.py`, `fix_prompt_check.py`, `post_fix_prompt.sh`, `check_record.py`; the hooks are registered in [`.claude/settings.json`](.claude/settings.json)).
- [`.claude/skills/verify-panel/`](.claude/skills/verify-panel/SKILL.md): a contact sheet of the VS Code client's Study panel at a given head, in VS Code's four default themes, drawn by headless Chrome.
- [chadlis/hypotrail-learning](https://github.com/chadlis/hypotrail-learning): the learning book (French) and the original specification of the first milestone.

## License

Not chosen yet.
