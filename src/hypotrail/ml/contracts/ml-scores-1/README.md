# ml-scores/1, ranking-items/1, ranking-reference/1, ranking-build/1

Accepted on 2026-11-27 by the ranking Track's contract, `docs/contracts/ranking-track.md` in chadlis/hypotrail (M0), which says why each rule holds. Owner: chadlis/hypotrail. Copy: chadlis/mlkit, `contracts/ml-scores-1/`, byte for byte, pinned in its `contracts.lock.json`. The decisions are D-172 on chadlis/hypotrail#75 (C1 and C2) and D-180 on chadlis/hypotrail#75.

A kit writes these files; `hypotrail import ml` reads the score file, and the ranking Track's `init` reads the Items and the References. The score file has the shape `import ml` already reads on `main` (`MAPPING_KEYS` in `ml/imports.py`), so the Track adds a Workload and a Scorer, not a file format.

## Files

| Schema | Describes | Written by |
|---|---|---|
| `mapping.schema.json` | `mapping.json`: the column names, the digest of the `items.csv` the scores were made for, the producer claims, and the flat `settings` map | the kit's exporter |
| `population.schema.json` | `population.json`: the Items the score file holds, all of one Partition | the kit's exporter |
| `scores.schema.json` | `scores.csv`: `item_id`, `score`, one row per Item of the population; no label | the kit's exporter |
| `ranking-items.schema.json` | `items.csv`: `item_id`, `entity_id`, `as_of`, `partition`, `mature`; no label | the kit's builder |
| `ranking-reference.schema.json` | `references-dev.csv` and `references-held_out.csv`: `item_id`, `label` | the kit's builder |
| `ranking-build.schema.json` | `build.json`: `schema_version`, `label_cutoff`, `frame_digest`, `source.sha256`, and the sha256 and size of each file of the build; other keys are allowed | the kit's builder |

A CSV file is checked as the object `{"columns": <its header>, "rows": [<one object per row, every value a string>]}`. The schemas are JSON Schema 2020-12.

## Rules a schema cannot say

- `item_id` is `<entity_id>@<as_of>`. The Items exist in `items.csv`; the score file only joins to them, by ID, never by position.
- A higher `score` ranks first. Ties are the Track's to break, by `item_id` ascending. The exporter never rounds or rescales.
- `dataset_sha256` is the sha256 of the `items.csv` the scores were made for.
- `settings` is recorded `declared`. The kit writes `kit_commit`, `run_id`, `frame_digest`, `candidates_compared`. Until Hypotrail accepts `settings` in a mapping (M1), a mapping that holds it is refused with `MAPPING_KEY_UNKNOWN`: a pinned known difference, which `tests/test_contracts_ml_scores.py` asserts on the example mapping and M1 turns around.
- `mature` is true when `as_of + horizon <= label_cutoff`, and `label_cutoff` is the day after the last observed day. An immature Item has an empty `partition` (the schema checks this), is in no References file and in no population.
- A References file holds one row per mature Item of its Partition. Every dev label window closes before the first held-out `as_of`.
- `references-held_out.csv` is written and read inside the evaluator job only, by a second Study in the job's workspace.
- `build.json` and the Workload's data manifest agree, digest for digest.
- `y_pred_raw`, a mapping key of the regression Track, is not a key of `ml-scores/1`.
- A population smaller than its Partition is valid.

## Examples

`examples/` holds one accepted set: `items.csv`, `references-dev.csv`, `build.json` (the digest and size of those two files), `scores.csv`, `mapping.json` (its digest is the one of `examples/items.csv`) and `population.json`. The values are made up; the kit commit, the frame digest and the source digest are zeros. The page records mlkit's real export of its reference run by digests and counts; no real data is committed here.

`examples/refused/<case>/` holds one refused case each, with the files it changes and `expected.json`: the contract, the refusal `code`, the `exit`, and `caught_by`. `schema` means the schemas refuse it; `import` means the files are schema-valid and only `hypotrail import ml` refuses them; `init` means they are schema-valid and only `hypotrail init` and `init --new-revision` refuse them. A case the schemas refuse is also refused, with its code, by the command that reads its file. The consumer test checks both sides of that line now; M1 runs each case through its command.

## Tests

`tests/test_contracts_ml_scores.py`, and `tests/test_ranking_track_page.py` for the page. The import of the examples into a ranking Workload, and each refusal through its command, are M1's to add; the page lists them.

## Changes

`docs/contracts/CHANGELOG.md`. A change that makes a once-valid file invalid, or changes what a valid file means, is `ml-scores/2`.
