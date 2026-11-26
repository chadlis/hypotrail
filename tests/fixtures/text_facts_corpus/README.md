# The text_facts corpus

The case table of the block reader of `text_facts_v1` (chadlis/hypotrail#271). Each row of `corpus.jsonl` is one answer
and what reading it must give: per identifier kind, exactly its identifier set, and exactly its set of fact numbers.

## How it was written

- **Two blind writers.** Each wrote its rows from the contract of #271 and its brief alone, blind to the code and to the
  other writer, not to the rulings of D-171 on chadlis/hypotrail#75.
- **Reconciled.** A reader paired the probes of both writers and checked every row against the contract's rules 1 to 9
  and limits L1 to L12. A probe appears once, with both writers' row ids in `source_rows`; a free row appears under its
  own id. `provenance` says which writer gave the row (`A`, `B` or `both`).
- **A sealed quarter.** One row in four of the reconciled set is held out by the drive and is not in this directory. It
  is run against the reader by the drive, never by the builder.

## The files

- `corpus.jsonl`: the reconciled rows the builder sees. They are not edited by hand.
- `rulings.jsonl`: one ruling per tagged or disputed row, with the row id, the decided expectation, the ruler and the
  date. A ruling's expectation holds instead of the row's own. A ruling changes only through the proxy.
