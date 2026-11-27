# The text_facts corpus

The case table of the block reader of `text_facts_v1` (chadlis/hypotrail#271). Each row of `corpus.jsonl` is one answer
and what reading it must give: per identifier kind, exactly its identifier set, and exactly its set of fact numbers.

## How it was written

- **Two blind writers.** Each wrote its rows from the contract of #271 and its brief alone, blind to the code and to the
  other writer, not to the rulings of D-171 on chadlis/hypotrail#75.
- **Reconciled.** A reader paired the probes of both writers and checked every row against the contract's rules 1 to 9
  and limits L1 to L12. A probe appears once, with both writers' row ids in `source_rows`; a free row appears under its
  own id. `provenance` says which writer gave the row (`A`, `B` or `both`).
- **A sealed quarter.** One row in four of the reconciled set (47 rows) was held out by the drive. A fresh reader, who had
  not seen the code, ran it against the reader at 7ac6777 and it scored 47 of 47. It was then merged into
  `corpus.jsonl`.

## The files

- `brief.md`: the brief as the two writers received it.
- `writer-a.jsonl`, `writer-b.jsonl`: each writer's rows, byte for byte as written. A test pins their SHA-256.
- `corpus.jsonl`: the reconciled rows, the sealed quarter included. They are not edited by hand.
- `rulings.jsonl`: one ruling per tagged or disputed row, and the rows a decision adds, each with the row id, the decided
  expectation (`identifiers` per kind and `fact_numbers`), the point, the date, the limit if one applies, and the ruler.
  A ruling's expectation holds instead of the row's own. A ruling changes only through the proxy.
