# The panel and the CLI share one contract: the Study decides, a client reads `status --json` and writes through the CLI

Status: accepted

A client of a Study, such as a panel that shows it and records decisions, and the CLI must agree on who decides, how a client reads, how it writes, and what happens when the Study changed between its read and its write. The contract below is the CLI side of it, as implemented by chadlis/hypotrail#107 to #110. It reuses the boundary of the earlier companion (one authoritative state, shared rules for every client), not its SQLite protocol or its state files.

## The contract

- The Study is the only decision authority. A decision is a record of the Study, kept in a file of its own and never rewritten (`decisions/<seq>-<id>.json`); a client holds none of its own.
- A client reads through `status --json`, which takes no lock and writes nothing, and writes only through the documented CLI commands.
- The Study keeps a write sequence: the number of entries of its write journal, which every command that writes appends to: two entries per command (one just before its first write, one after its last), none when the command is refused before its first write. A writer that was killed has therefore still advanced it. Nothing else changes it. `status --json` shows it as the top-level `write_sequence`; a Study written before the journal shows 0.
- Every command that writes to a Study accepts `--read-sequence N`, the write sequence its author read; `decide` requires `--read-sequence N` and `--request-id`. A command not given the option checks nothing. `init` that creates a Study takes none (it is refused), and `report` compares it only when its page records an Exposure.
- Under the Study's writer lock, a write made on an older write sequence is refused with `STUDY_CHANGED` (exit 6, stage `sequence`, `details` `read_sequence`, `write_sequence` and `writes_since`), and nothing is written. A write made on a write sequence above the Study's is refused with `WRITE_SEQUENCE_AHEAD` (exit 2). A request identity already recorded is checked before the sequence: the same `--request-id` with the same request returns the recorded record and writes nothing, and with another request it is `REQUEST_CONFLICT` (exit 6).
- Whether a decision still applies is computed when the Study is read, from the ids it cites and the records of the Study, and is never stored: `status --json` lists each decision with `applies` and its `reasons`, and no record is written or changed when the answer changes.
- A client reads the Study (`status --json`) and passes the write sequence it read on every write. L2.1 writes no agent instruction: the places that write this rule for agents are L2.2 and L2.6.
- A panel never shows `public_check` content that no Assessment or Comparison has journaled. A live view of artifacts already recorded is not a « report » (GLOSSARY, **Exposure**): such a view records no Exposure and writes nothing, so it does not advance the write sequence.
- The client's location and tooling are not decided here: L2.4 decides them.

## Considered options

- **A digest of `status --json` as the token a write must present** (rejected, D-031 item 1): the digest changes without a write (`writer_alive`, temporary files), so a client would be refused although the Study had not been written to.
- **The Protocol revision as the token** (rejected, D-031 item 1): recording a decision does not change the Protocol revision, so the revision misses decisions.
- **A write sequence that every write advances** (chosen): it moves exactly when the Study is written to, and a read cannot move it.
- **Making `--read-sequence` required for every writing command** (not chosen): direct evaluation stays usable without a client (ROADMAP: « Direct evaluation remains usable without the workflow »), so only `decide` requires it.

## Consequences

- A client that passes a stale write sequence gets `STUDY_CHANGED` and `writes_since`, reads again, and decides again: it cannot record a decision over a write it never saw.
- The write sequence, the write journal and the decision record are part of the record format of a Study.
- A client that skips `--read-sequence` on a writing command other than `decide` is not protected from a stale write: the rule that it passes it rests on the instructions of L2.2 and L2.6.
