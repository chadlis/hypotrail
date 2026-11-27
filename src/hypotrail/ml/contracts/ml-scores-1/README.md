# ml-scores/1, ranking-items/1, ranking-reference/1

**Draft** until the ranking Track's contract (M0) accepts it. Owner: chadlis/hypotrail. Copy: chadlis/mlkit, `contracts/ml-scores-1/`, byte for byte, pinned in its `contracts.lock.json`. The decision is D-172 on chadlis/hypotrail#75 (C1 and C2).

A kit writes these files; `hypotrail import ml` reads the score file, and the planned ranking Track reads the Items and the References. The score file has the shape `import ml` already reads on `main` (`MAPPING_KEYS` in `ml/imports.py`), so the Track adds a Workload and a Scorer, not a file format.

## Files

| Schema | Describes | Written by |
|---|---|---|
| `mapping.schema.json` | `mapping.json`: the column names, the digest of the `items.csv` the scores were made for, the producer claims, and the flat `settings` map | the kit's exporter |
| `population.schema.json` | `population.json`: the Items the score file holds, all of one Partition | the kit's exporter |
| `scores.schema.json` | `scores.csv`: `item_id`, `score`, one row per Item of the population; no label | the kit's exporter |
| `ranking-items.schema.json` | `items.csv`: `item_id`, `entity_id`, `as_of`, `partition`, `mature`; no label | the kit's builder |
| `ranking-reference.schema.json` | `references-dev.csv` and `references-held_out.csv`: `item_id`, `label` | the kit's builder |

A CSV file is checked as the object `{"columns": <its header>, "rows": [<one object per row, every value a string>]}`. The schemas are JSON Schema 2020-12.

## Rules a schema cannot say

- `item_id` is `<entity_id>@<as_of>`. The Items exist in `items.csv`; the score file only joins to them, by ID, never by position.
- A higher `score` ranks first. Ties are the Track's to break, by `item_id` ascending. The exporter never rounds or rescales.
- `dataset_sha256` is the sha256 of the `items.csv` the scores were made for.
- `settings` is recorded `declared`. The kit writes `kit_commit`, `run_id`, `frame_digest`, `candidates_compared`. Until Hypotrail accepts `settings` in a mapping (M1, chadlis/hypotrail#277), a mapping that holds it is refused with `MAPPING_KEY_UNKNOWN`: a pinned known difference, which `tests/test_contracts_ml_scores.py` asserts on the example mapping and M1 turns around.
- `mature` is true when `as_of + horizon <= label_cutoff`. An immature Item has an empty `partition` (the schema checks this), is in no References file and in no population.
- A References file holds one row per mature Item of its Partition. Every dev label window closes before the first held-out `as_of`.
- `references-held_out.csv` is written and read inside the evaluator job only.
- A population smaller than its Partition is valid.

Left to M0: the schema of `build.json` (`ranking-build/1`), whose key names are not fixed yet; how the held-out References enter a Study that exists only inside the job; and the Partition rule for a group, since in a panel every entity is in several Partitions.

## Examples

`examples/` holds one accepted set: `items.csv`, `references-dev.csv`, `scores.csv`, `mapping.json` (its digest is the one of `examples/items.csv`) and `population.json`. The values are made up; the kit commit and the frame digest are zeros.

`examples/refused/<case>/` holds one refused case each, with the files it changes and `expected.json`: the contract, the refusal `code` (null where M1 has not named it yet), the `exit`, and `caught_by`. `schema` means the schemas refuse it; `import` means the files are schema-valid and only the import refuses them. The consumer test checks both sides of that line now; M1 runs the `import` cases through `hypotrail import ml`.

## Tests

`tests/test_contracts_ml_scores.py`. The import of the examples into a ranking Workload, and each `import` refusal with its code, are M1's to add.

## Changes

`docs/contracts/CHANGELOG.md`. A change that makes a once-valid file invalid, or changes what a valid file means, is `ml-scores/2`.
