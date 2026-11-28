# Parity reference

The archived French reproduction is the approved reference. The English twin
replays the same old panel and walk on Auto MPG using the old tool's English
copy. The owner approves the twin at gate 0 before Wave 3 begins. An unsigned
difference in [the parity table](table.md) blocks the corresponding surface
merge. [Translation inventory](translated.md) lists texts with no English source.

## Checks for surface changes

1. Run `npm test` in `clients/vscode` when the surface ticket adds its DOM
   check. It compares the kept state to the twin's ordered element list with tag,
   classes, data attributes and their specified identity values, and own text.
2. Run `uv run --frozen python -m pytest tests/test_parity_texts.py` once T06
   lands. It compares served text and checks the legacy English source digests.
3. After T03, run
   `node .claude/skills/verify-panel/render.js <out> <head> --parity <reference-folder>`.
   Review both board themes at 420 px and 900 px, including charts, layout and
   contrast. Keep the sheet with the ticket's review evidence.

The old Models screen opens as a Path review while Now shows Variants. Its two
fixture slots use that same view. The completed Study has no alternate Path
entry, so both completion slots use its final Now view.

Compare figures at the precision shown in the reference. Only EBM differences
within 0.15 mpg are eligible for an owner-signed row. A conflict between a new
rule and the reference is an owner decision.

## Regenerate the legacy CLI fixtures

Use a read-only checkout of the old tool at
`4ef4925af0568dbf57ec02ed872a1af2b1f00b14` with its framework environment installed.
Pass the archived replay bundle at `9d1d294` and a fresh scratch directory.
The capture uses the bundle's scripted answers for the old Auto MPG Study.
The four French-only scripted inputs use the English text of the specification.
No old engine or live model runs in CI.

```sh
python scripts/parity/capture_old.py \
  --old-hypotrail /path/to/legacy-checkout \
  --replay /path/to/parity-v1/replay \
  --scratch /path/to/empty-capture-directory \
  --out tests/fixtures/parity/reference-en
uv run --frozen python -m pytest tests/test_parity_reference.py
```

## Section 1.4 branch checklist

Each row cites a separate capture from the old Auto MPG walk. The change option
asks for a different value and records no adoption. A split change uses a new
Workload revision in the new tool.

| Step | Branch | Fixture basename |
| --- | --- | --- |
| 2 | Change something | `02-prediction_time-pause.change` |
| 3 | Change something | `03-feature_availability-pause.change` |
| 4 | Change something | `04-split-pause.change` |
| 5 | Change something | `05-error_metric-pause.change` |
| 6 | Change something | `06-success_criterion-pause.change` |
| 6 | Set the minimum reduction to 20% | `06-success_criterion-pause.20-percent` |
| 8 | Change something | `08-preprocessing-pause.change` |
| 11 | Change something | `12-model_variant-pause.change` |
| 12 | Change something | `14-model_choice-pause.change` |
| 12 | Choose the EBM | `14-model_choice-pause.ebm` |
| 12 | Choose the reference | `14-model_choice-pause.reference` |
| 13 | Change something | `16-final_test-pause.change` |
| 14 | Change something | `17-conclusion-pause.change` |
| 14 | Keep the reference | `17-conclusion-pause.keep-reference` |
| 14 | Do not conclude | `17-conclusion-pause.do-not-conclude` |
| 2 | Show the refusal for a missing proposal | `02-prediction_time-pause.refusal` |
