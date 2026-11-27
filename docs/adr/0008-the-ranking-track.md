# The ranking Track

Status: accepted

## Context

D-167 on chadlis/hypotrail#75 has chadlis/mlkit write "a score file per (entity, date) in Hypotrail's import format". D-172 on chadlis/hypotrail#75 drafted that file as `ml-scores/1`, and the labels and maturity as C2. #274 wrote them as drafts "until M0 accepts it". Hypotrail has no ranking Track yet: `import ml` reads the score file's shape on `main`, but no Workload declares Items that are an entity at an as-of date, and no Scorer ranks them. The open points of the draft were answered by the owner's proxy (D-180 on chadlis/hypotrail#75).

## Decision

1. **A ranking Track.** Hypotrail gains a Track whose Item is one entity at one as-of date, whose Reference is a binary outcome within a horizon, and whose Metric is the recall among the top fraction of scores per date. It is built in M1 (import and assess), M2 (compare) and M3 (two populations), on the public twin.
2. **Its contract is one page.** [`docs/contracts/ranking-track.md`](../contracts/ranking-track.md) states the Item ID, the digest rule, the Metric, the held-out References, the group rule, the build file, the refusal codes and the example, each with its source. The page and the files under `src/hypotrail/ml/contracts/ml-scores-1/` agree, and `tests/test_ranking_track_page.py` checks that they do.
3. **The score file keeps the shape `import ml` reads.** The Track adds a Workload and a Scorer, not a file format.

## Consequences

- **Durable formats.** `ml-scores/1`, `ranking-items/1`, `ranking-reference/1` and `ranking-build/1` become durable once a Study imports a file or holds a References set built from them. Until M1 or M2 builds on a point, it can be changed by a pull request that changes the page, the schemas, the CHANGELOG and this ADR's dated lines.
- chadlis/mlkit updates its copy in a contract-pin pull request. Its `build.json` gains `schema_version` and the file sizes (chadlis/mlkit#18).
- No real data of the twin is committed here. Whether it may be is the owner's.

## Changes

One dated line per version change of a contract this Track reads (D-172 on chadlis/hypotrail#75, rule 5).

- 2026-11-27: `ml-scores/1`, `ranking-items/1` and `ranking-reference/1` accepted at version 1; `ranking-build/1` first written; the five References and population refusal codes named.
