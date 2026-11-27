# The ranking Track's contract

Status: accepted, 2026-11-27 (M0). The Track's decision record is [ADR 0008](../adr/0008-the-ranking-track.md).

The ranking Track evaluates a score per (entity, as-of date) that a kit writes outside Hypotrail. Each Item is one entity at one as-of date. Its Reference is whether the event happened within the horizon after that date. Hypotrail imports the score file (`hypotrail import ml`), assesses it against the References, and compares two Assessments.

This page writes none of that code. It fixes the file formats and the rules the code will follow:
- M1 imports and assesses;
- M2 compares, and builds the interval's estimator;
- M3 compares two populations.

The formats are in [`src/hypotrail/ml/contracts/ml-scores-1/`](../../src/hypotrail/ml/contracts/ml-scores-1/README.md):

| Contract | File | Written by |
|---|---|---|
| `ml-scores/1` | `scores.csv`, `mapping.json`, `population.json` | the kit's exporter |
| `ranking-items/1` | `items.csv` | the kit's builder |
| `ranking-reference/1` | `references-dev.csv`, `references-held_out.csv` | the kit's builder |
| `ranking-build/1` | `build.json` | the kit's builder |

All four are at version 1, and they are no longer drafts. A change that makes a once-valid file invalid, or changes what a valid file means, is version 2. Every change gets a line in [`docs/contracts/CHANGELOG.md`](CHANGELOG.md) and a dated line in ADR 0008. chadlis/mlkit then moves its copy in a contract-pin pull request.

## 1. The Item ID and the mapping

An Item ID is `<entity_id>@<as_of>`:
- `entity_id` matches `^[A-Za-z0-9_-]+$`;
- `as_of` is an ISO date.

The Items exist in `items.csv`. A score file only joins to them, by ID and never by position.

The Track keeps the mapping that `import ml` already reads:
- `row_id` is `item_id`;
- `y_pred` is `score`;
- `dataset_sha256` is required.

An Item needs nothing more than its ID to be joined: its entity and its date are columns of `items.csv`, which the Track reads through the same ID. So `ml-scores/2` is not needed before mlkit's exporter is trusted.

`score` is a finite number. A higher score ranks first, and ties are broken by `item_id` ascending. The exporter never rounds or rescales.

Extra columns of `scores.csv` are tolerated and reported as `unmapped_columns`. A population holds the Items of one Partition, and it may be smaller than its Partition.

`settings` is recorded `declared`. Until M1 accepts it in a mapping, `import ml` refuses a mapping that holds it with `MAPPING_KEY_UNKNOWN`.

Sources: D-172 on chadlis/hypotrail#75, C1 and answer 1 ("Wrong if M0 finds that the Track cannot keep the `row_id` / `y_pred` / `dataset_sha256` mapping"); `src/hypotrail/ml/imports.py` at `865aa4e` (`MAPPING_KEYS`, the join by ID, `unmapped_columns`, one Partition per population).

## 2. The digest rule

`dataset_sha256` is the sha256 of the `items.csv` the scores were made for. It binds a score file to one build.

The ranking Workload declares each file of the build as a `data-manifest/1` source (`dataset_id`, `sha256`, `size_bytes`, `as_of`, `license`, `notice`, `notice_sha256`). `build.json` and the manifest must agree, digest for digest:
- `data verify` checks the bytes only, and a mismatch exits 3;
- `import ml` compares `dataset_sha256` with the manifest's digest of `items.csv`, and refuses another with `DATASET_DIGEST_MISMATCH`, exit 3.

A later build, with a later cutoff, gives a new `items.csv`, a new digest and a follow-up Study. It never rewrites a Reference.

Sources: D-172 on chadlis/hypotrail#75, C1 ("`dataset_sha256` is the digest of the C2 `items.csv` the scores were made for") and C2 ("`build.json` and the manifest must agree, digest for digest"); D-180 on chadlis/hypotrail#75, item 3 ("`data verify` checks bytes only, exit 3").

## 3. The metric

The Metric is `recall_at_top_fraction`, with `fraction` 0.1. It is computed per as-of date of the population, as follows.

1. Take the n Items of the date, ranked by score from highest to lowest, with ties broken by `item_id` ascending.
2. Keep the top k = ceil(fraction × n). The product is exact: the fraction is read as a decimal, not as a binary float.
3. The date's recall is the number of positive Items among the top k, divided by the number of positive Items on that date.
4. A date with no positive Item has no recall and is left out.
5. The Metric is the mean of the dates' recalls.

The Assessment states how many dates were left out. When every date is left out, the Metric has no value.

The interval resamples entities, so all the Items of one `entity_id` are drawn together. It uses S2-1's constants: percentile, 0.95, 2,000 resamples. M0 fixes only the unit and those constants. The estimator is M2's, because recall in a top fraction is not a mean per Item.

mlkit computes the same Metric on its dev windows. Its value for a score file must equal Hypotrail's Assessment value within 1e-9.

Sources: D-172 on chadlis/hypotrail#75 (recall among the top 10 % of scores per date, averaged over dates, the interval by entity); D-180 on chadlis/hypotrail#75, item 1 ("the top count is `ceil(fraction × n)`; a date with no positive is left out of the mean; ties go by `item_id`"); chadlis/mlkit#11 (`recall_at_top` in `src/mlkit/run.py`); chadlis/hypotrail#291, item 4.

## 4. The held-out References and the group rule

**Held-out References.** `references-held_out.csv` is written and read inside the evaluator job only. It enters a second Study in the job's workspace, with the same Workload and its own References set. The dev Study never holds a held-out Reference.

**The group rule.** "A group in two Partitions is refused" is a rule a Workload declares, as `group_partition_rule: disjoint`. When it is not declared, there is no such rule. A ranking Workload does not declare it: in a panel, every entity is in several Partitions by construction, with dev dates and held-out dates. The entity is still the interval's unit (point 3).

Sources: D-172 on chadlis/hypotrail#75, C2 ("proposed: a second Study in the job's workspace, same Workload, its own References set"; "must be a rule the Workload declares, because in a panel every entity is in several Partitions by construction"); chadlis/hypotrail#292 (`group_partition_rule: disjoint`, "Absence means no rule").

## 5. The build file, the refusals and `y_pred_raw`

### `ranking-build/1`

`build.json` follows `ranking-build.schema.json`.

Required keys: `schema_version`, `label_cutoff`, `frame_digest`, `source.sha256`, `files`.

Each entry of `files` requires: `sha256`, `size_bytes`.

What the keys mean:
- `schema_version` is `ranking-build/1`.
- `label_cutoff` is the day after the last observed day. An Item is mature when `as_of + horizon <= label_cutoff`.
- `files` maps each file name of the build to its digest and size.

Other keys are allowed, such as the counts, the dropped lines and the positive rate per date that mlkit writes.

The `build.json` mlkit writes at `393058b` has no `schema_version` and no sizes, so it is not valid yet. chadlis/mlkit#18 changes it.

### The refused cases

Each case lives in `examples/refused/<case>/`. Its `expected.json` gives the contract, the code, the exit and `caught_by`:
- `schema`: the schemas refuse the case, and the command that reads the file refuses it too, with the code;
- `import`: only `hypotrail import ml` refuses it;
- `init`: only `hypotrail init` and `init --new-revision` refuse it.

The content of a References file is refused by `init`, exit 2. A population that holds an immature Item is refused by `import ml`, exit 2, and M1 checks it before `POPULATION_ITEM_UNKNOWN`.

Each case is M1's to run through its command, with the test named in the last column.

| Case | Contract | Code | Exit | Caught by | M1's test |
|---|---|---|---|---|---|
| `dataset-digest-mismatch` | `ml-scores/1` | `DATASET_DIGEST_MISMATCH` | 3 | `import` | `tests/test_import_ml_ranking.py::test_each_refused_score_file_is_refused_by_import_ml_with_its_code[dataset-digest-mismatch]` |
| `mapping-key-unknown` | `ml-scores/1` | `MAPPING_KEY_UNKNOWN` | 2 | `schema` | `tests/test_import_ml_ranking.py::test_each_refused_score_file_is_refused_by_import_ml_with_its_code[mapping-key-unknown]` |
| `population-immature-item` | `ml-scores/1` | `POPULATION_ITEM_IMMATURE` | 2 | `import` | `tests/test_import_ml_ranking.py::test_each_refused_score_file_is_refused_by_import_ml_with_its_code[population-immature-item]` |
| `population-item-absent` | `ml-scores/1` | `POPULATION_ITEM_ABSENT` | 2 | `import` | `tests/test_import_ml_ranking.py::test_each_refused_score_file_is_refused_by_import_ml_with_its_code[population-item-absent]` |
| `population-mixed-partitions` | `ml-scores/1` | `POPULATION_MIXED_PARTITIONS` | 2 | `import` | `tests/test_import_ml_ranking.py::test_each_refused_score_file_is_refused_by_import_ml_with_its_code[population-mixed-partitions]` |
| `prediction-not-finite` | `ml-scores/1` | `PREDICTION_NOT_FINITE` | 2 | `schema` | `tests/test_import_ml_ranking.py::test_each_refused_score_file_is_refused_by_import_ml_with_its_code[prediction-not-finite]` |
| `reference-duplicate` | `ranking-reference/1` | `REFERENCE_ROW_DUPLICATE` | 2 | `init` | `tests/test_init_ranking.py::test_each_refused_references_file_is_refused_by_init_with_its_code[reference-duplicate]` |
| `reference-immature-item` | `ranking-reference/1` | `REFERENCE_ITEM_IMMATURE` | 2 | `init` | `tests/test_init_ranking.py::test_each_refused_references_file_is_refused_by_init_with_its_code[reference-immature-item]` |
| `reference-item-unknown` | `ranking-reference/1` | `REFERENCE_ITEM_UNKNOWN` | 2 | `init` | `tests/test_init_ranking.py::test_each_refused_references_file_is_refused_by_init_with_its_code[reference-item-unknown]` |
| `reference-label-not-binary` | `ranking-reference/1` | `REFERENCE_LABEL_NOT_BINARY` | 2 | `schema` | `tests/test_init_ranking.py::test_each_refused_references_file_is_refused_by_init_with_its_code[reference-label-not-binary]` |
| `row-id-duplicate` | `ml-scores/1` | `ROW_ID_DUPLICATE` | 2 | `import` | `tests/test_import_ml_ranking.py::test_each_refused_score_file_is_refused_by_import_ml_with_its_code[row-id-duplicate]` |
| `row-id-outside-population` | `ml-scores/1` | `ROW_ID_OUTSIDE_POPULATION` | 2 | `import` | `tests/test_import_ml_ranking.py::test_each_refused_score_file_is_refused_by_import_ml_with_its_code[row-id-outside-population]` |

Each `init` test also covers `init --new-revision`.

### `y_pred_raw`

`y_pred_raw` is a mapping key of the regression Track, for the unclipped prediction. `ml-scores/1` leaves it out, because its mapping schema is closed and does not list it. M1 refuses it, for a ranking Workload, with `MAPPING_KEY_UNKNOWN`. The regression Track is unchanged and still accepts it.

M1 test: `tests/test_import_ml_ranking.py::test_import_ml_refuses_y_pred_raw_for_a_ranking_workload_with_mapping_key_unknown`

Sources: D-180 on chadlis/hypotrail#75, items 2, 3 and 6; chadlis/hypotrail#274 (the draft schemas, the 12 refused cases and `tests/test_contracts_ml_scores.py`); chadlis/mlkit#18.

## 6. The example

The examples under `examples/` are made up, and they stay the accepted set. No real data is committed: whether a real export may be committed, in full or in part, is a data clearance question, and it stays with the owner.

mlkit's real export of its reference run on the twin (Online Retail II, CC BY 4.0) is recorded here by its digests and counts.

**How it was made.** It was re-made on 2026-11-27 at mlkit `393058b439c84ead8a1a57e093badeae621ec7e8`, the merge of K1 (chadlis/mlkit#11) on mlkit `main`. No model was called, and the commands were `mlkit build`, `mlkit run --reference` and `mlkit export --run r-0001`.

At mlkit `main` (`9b0dba3af7480703bdcfb5e6ff4ed337a52dc958`), `mlkit build` gives the same `items.csv` and `references-dev.csv`. Its frame digest is `1ca6c4ce3914a8bdf5c128ce6cdbbec407469f9334821f205af561474693bbcd`, because the launcher added a budget and stops to `frame.yaml`. `mlkit run` is refused there with `GATE_BLOCKED` until the owner answers the framing questions.

**The source and the frame.**
- The source `online_retail_II.xlsx` has sha256 `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980`.
- The frame digest at `393058b` is `50d1136b1c8ac4fb21b219026d99601b8e4bb4ce20f5da800a8bdaab413d45ff`.

**The files.**

| File | sha256 | Bytes | Content |
|---|---|---|---|
| `items.csv` | `90df66d75339a9b366e37f90c427bd1f1b935c7f8cc10c489783d6ae403d8e67` | 3,656,064 | 84,109 Items of 5,881 customers: 37,239 mature `dev`, 20,374 mature `held_out`, 9,542 mature in no Partition (2011-04-01 and 2011-05-01), 16,954 immature |
| `references-dev.csv` | `52199c1346800cc7544026e1a6723f7d12b456946b50d92fd9fdb2d40c2e1478` | 707,555 | 37,239 rows, 15,927 positive |
| `build.json` | `e39a884d3a5990efcad7d30af56107b3d17971b04f4cfadff7da8e8eff98851f` | 1,868 | 1,067,371 lines read; `label_cutoff` 2011-12-10 |
| `scores.csv` | `bcc8682b750a2153da7bf997d8ac65d4b863e34c7e0ecd2e463df8b2c322e283` | 792,362 | 37,239 rows |
| `population.json` | `afb34350abe36bfc4bc531169edb706ee6d3702b16c588e9b39c1abd46f17ab4` | 893,759 | 37,239 Items, all `dev` and mature: 10 dates, 4,539 entities |
| `mapping.json` | `98079ab7ab38ad1512891015f97ac4af7a0cf997f92abefa81b8893661e874bb` | 500 | `dataset_sha256` is the digest of `items.csv`; `generated_at` is the run's time, so another run gives another digest |

**Validation.** The export, `items.csv` and `references-dev.csv` are valid against `mapping.schema.json`, `population.schema.json`, `scores.schema.json`, `ranking-items.schema.json` and `ranking-reference.schema.json`. `build.json` is not yet valid against `ranking-build.schema.json` (chadlis/mlkit#18).

**The reference run.** r-0001, the recency rule, has `recall_at_top_fraction` 0.1610428251347026 over the 10 dev dates. No date was left out, and the per-date recall runs from 0.1300 (2010-10-01) to 0.2076 (2011-01-01).

Sources: D-172 on chadlis/hypotrail#75, SP2 ("M0 accepted, with K1's real export beside it"); D-180 on chadlis/hypotrail#75, item 4 ("M0 keeps the made-up set. The page records the real export by kit commit, digests, counts and the r-0001 value"); chadlis/mlkit#3; chadlis/mlkit#11.
