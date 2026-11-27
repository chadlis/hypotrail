# Contract changes

The contracts this repository owns, under `src/hypotrail/*/contracts/`. One line per change: date, contract, version, what changed, the pull request. A copying repository moves its copy in its own contract-pin pull request (D-172 on chadlis/hypotrail#75, rule 5).

| Date | Contract | Version | Change | Pull request |
|---|---|---|---|---|
| 2026-11-26 | `ml-scores/1`, `ranking-items/1`, `ranking-reference/1` | 1, draft | First written, from C1 and C2 of D-172; draft until M0 accepts it | chadlis/hypotrail#274 |
| 2026-11-26 | `agent-answers/1` | 1 | First written, from C3 of D-172; checked against `import agent` on `main` after S1, with the unknown-key difference open in chadlis/hypotrail#278 | chadlis/hypotrail#274 |
| 2026-11-27 | `ml-scores/1`, `ranking-items/1`, `ranking-reference/1`, `ranking-build/1` | 1 | Accepted by M0, the ranking Track's contract ([`ranking-track.md`](ranking-track.md), ADR 0008); `ranking-build/1` first written; the refusal codes of the References cases and of an immature Item in a population named; three References cases are `caught_by: init`, a new value, and `reference-label-not-binary` stays `schema` (D-180 on chadlis/hypotrail#75) | chadlis/hypotrail#305 |
| 2026-11-27 | `agent-answers/1` | 1 | The importer refuses unknown top-level line keys with `LINE_KEY_UNKNOWN`. The closed schema declares the historical advisory `unknown_fields` array explicitly. Previously recorded Imports can still replay. | For chadlis/hypotrail#278 |
