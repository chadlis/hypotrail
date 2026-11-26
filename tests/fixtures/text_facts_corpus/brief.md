# Brief: a blind case corpus for reading identifiers block by block

You are one of two corpus writers. You write test rows for a reader that finds record identifiers and numbers in Markdown answers. The reader's rules are the contract in chadlis/hypotrail#271, "S1 close: read identifiers block by block". Read its sections "The contract" and "Documented limits" in full before you write. The contract already holds the proxy's rulings (D-171 on chadlis/hypotrail#75); there is no open point left in it. You are blind to the code and to the other writer, not to those rulings.

## What you may read

- **Allowed:** issue #271's body, and this brief.
- **Not allowed:** the hypotrail repository, its code, tests, fixtures, branches, other issues or pull requests, and the other writer's file.

Write your expectations from the contract's words alone. When the contract does not settle a row, do not guess how the code behaves: tag the row (see `open`) and say why in `note`. The proxy rules on tagged rows later, in a separate file; your file is committed byte for byte as you wrote it, in `tests/fixtures/text_facts_corpus/`, before any code changes.

## What to write

Write realistic answers of a SQL-analyst assistant about the Chinook music store. The answers are in English Markdown. The assistant answers a store employee's question in prose, lists and tables. It may show its SQL, ask for clarification, or say the data does not hold the answer.

For each answer, give the identifiers the reader must find, per kind, and the numbers it must offer as facts.

The values need not be true to the data, but keep them plausible. Chinook has:
- 412 invoices (ids 1 to 412), 59 customers, 3503 tracks, 347 albums;
- 275 artists, 8 employees, 25 genres, 18 playlists;
- invoice dates from 2009-01-01 to 2013-12-22, stored as "2009-01-01 00:00:00";
- totals such as 0.99, 1.98, 13.86.

**The four identifier kinds** (the Workload's scoring config):

| Kind | Its words, any case |
|---|---|
| `invoice` | "invoice", "invoices", "inv" |
| `customer` | "customer", "customers", "cust" |
| `track` | "track", "tracks" |
| `album` | "album", "albums" |

- **The pattern.** The word may be followed by " id", " no", " no." or " number". Then come any spaces, `#`, `:` or `-`, then the digits. The digits may hold `_` between them. The word must start a word: "soundtrack 5" is no track.
- **Not matched by the pattern.** "InvoiceId 34" and "Invoice IDs 34" are not matched as such. Rule 4 (labelled lists) may still apply; a table header gives no role (L4).
- **Label words** (rule 4) are only the kind's key, with an optional "s", in any case: "invoice", "invoices", "Invoice IDs:" holds one. "inv" and "cust" are pattern words but not label words, so "Inv:" is no lead-in (L11).
- **Normalisation.** `_` is removed, leading zeros are stripped, and case is folded. "INV-0034" is invoice `34`; "cust#5" is customer `5`; "Track 1_2" is track `12`.
- **Other kinds.** Artist, employee, genre, playlist and media type are not kinds (L5).

## The rows

Each writer writes **at least 60 rows**: every probe below, then **at least 30 free rows**.

**The probes.** Write each probe once with its text verbatim as the whole answer. Write `\n` as a real newline in the answer. You may also embed a probe in a longer free row, which counts as a free row.

Round 1 (for context; include them):
- R1-1 `Customer 12 bought some tracks.`
- R1-2 `The first one was billed on 2010-03-11.`

Round 2:
- R2-1 `Customer 1. Number of invoices: 7`
- R2-2 `Customer 1. Invoices: 7`
- R2-3 `Customer 1 has 7 invoices.`
- R2-4 `Customer 1. Number of invoices : 7.`
- R2-5 `Customer 1 - invoices:7`
- R2-6 `See invoice 7.`
- R2-7 `See invoice #7.`
- R2-8 `See Invoice: 7.`
- R2-9 `See invoice no. 7.`
- R2-10 `See inv 7.`

Round 3:
- R3-1 `Invoices: 269, 291, 293`
- R3-2 `Invoices: 16 and 24`
- R3-3 `Count of tracks: 7`
- R3-4 `Total customers: 7`
- R3-5 `Total number of albums: 7`

Round 4:
- R4-1 `Customer 12 has invoices 34, 155, 166, 221, 350, 373 and 395.`
- R4-2 `Number of  invoices: 7` (two spaces)
- R4-3 `Number of\ninvoices: 7`
- R4-4 `Numbers of invoices: 7`
- R4-5 `invoices #34 & #155 or\n166`
- R4-6 `invoices 34 and 155 for a total of 9.90`
- R4-7 `See invoices 34 and 155. 9 more are due.`
- R4-8 `invoices 34 and 155 and customer 12`
- R4-9 `invoice 34, 2009-05-23`
- R4-10 `invoice 34, 49.62 in all`
- R4-11 `| invoice 34 | 2009-05-23 | $0.99 |`

Round 5:
- R5-1 `1. Invoice 98\n2. Invoice 99`
- R5-2 `Invoice 34\n\n2 more are pending`
- R5-3 `invoices 34, 155 and 166, 3 in total`
- R5-4 `Invoices:\n- 34\n- 155`
- R5-5 `the number of invoices 34 and 155 is 2`
- R5-6 `Invoice 98 1 track`
- R5-7 `invoices 34\n155`
- R5-8 `Invoices:\n- 34\nSee also\n- 155`
- R5-9 `Invoice 34\n- 155`
- R5-10 `Invoices:\n\n2 more are pending`
- R5-11 `Invoices:\n* 34\n* 155\n* 166`
- R5-12 `Invoices:\n1. 34\n2. 155\n3. 166`
- R5-13 `Invoices:\n+ 34\n+ 155`
- R5-14 `Invoices:\n1) 34\n2) 155`
- R5-15 `invoices 34; 155; 166`

Round 6:
- R6-1 `invoices #34 & #155 & #166`
- R6-2 `invoices 34, 155 or 166 and 200`
- R6-3 `Invoices:\n- 34 ($0.99)\n- 155 ($1.98)`
- R6-4 `**Invoices:**\n- 34\n- 155`
- R6-5 `Invoice IDs:\n- 34\n- 155`
- R6-6 `The invoices are:\n- 34\n- 155`
- R6-7 `1. Invoice 98, $3.96\n2. Invoice 99, $1.98` (built from the finding "in 1. …\n2. …, the 1 and the 2 can satisfy an integer fact")
- R6-8 `Number of invoices: 2\n\n- invoice 34\n- invoice 155` (built from the finding "the phrase still drops the list after it"; R5-5 is the original)

**The free rows.** Write them as an assistant would: a sentence of context, the result, sometimes a note or the SQL. Use 1 to 25 lines each, and vary the kinds and the values. A row may count towards several of these minimums:

- 8 tables:
  - at least 3 whose header names a kind over cells holding bare numbers ("| Invoice | Total |", "| InvoiceId | ... |"; they pin L4);
  - at least 2 whose cells hold "invoice 34" forms;
  - amount and date columns.
- 8 numbered lists (`1.` and `1)`): rankings ("top 5 tracks"), some items annotated, some lists starting at a number other than 1;
  - at least 2 ordered lists starting above 1 right under a lead-in ("Invoices:\n2. 34\n3. 155").
- 8 bulleted lists (`-`, `*`, `+`): tight and loose, at least 2 nested (one a list grouped by year, L7).
- 6 labelled lists with varied lead-ins:
  - bold, worded, "IDs", "for customer N";
  - at least 2 with a heading as the label and no colon, and at least 2 with no colon at all (they pin L4);
  - at least 2 whose leading numbers are not ids ("- 2 were refunded"; L9).
- 5 answers with a fenced SQL block holding ids and numbers (`WHERE CustomerId = 12`, `LIMIT 5`), and 3 with inline code spans, at least 2 of them holding an identifier ("invoice `34`", "`INV-0034`"). A span's content is text (rule 1).
- 5 answers with counts: count phrases before a value, before a list and after a list;
  - at least 3 trailing counts: one "in total", one "in all", one in other words ("3 altogether", L6).
- 3 paragraphs with a line break inside: one beside a joiner, one between a label and its value, one lead-in with no blank line before the next line (L1).
- 4 answers naming records of other kinds (artist, employee, genre, playlist ids).
- 4 clarification or no-data answers. Some name candidate records ("Do you mean customer 16 or customer 24?").
- 4 answers naming several kinds (a customer, their invoices, their tracks).
- 4 answers with dates and money: ISO dates, timestamps ("2009-05-23 00:00:00" gives no number, rule 8), a non-ISO date (L2), `$`, `,` thousands, `%`.
- 1 row with CRLF line ends (`\r\n` in the JSON string), and 1 identifier holding `_` ("Track 1_2").
- 3 answers with headings that hold identifiers.
- 3 follow-up answers ("As above, ...", "Of those, ...").

Use only `.` as the decimal point and `,` for thousands; no other number formats.

## The format

Write one JSON object per line, UTF-8, to the file the drive gives you (`writer-a.jsonl` or `writer-b.jsonl`). Example (one line in the file):

```json
{"row_id": "A-001", "probe": null, "question": "When was customer 7 last billed?", "answer": "Customer 7 was last billed on **2013-07-02**, invoice 377, for $1.98.", "identifiers": {"invoice": ["377"], "customer": ["7"], "track": [], "album": []}, "fact_numbers": [1.98], "rules": ["2", "8"], "open": [], "limit": [], "note": "Two kind patterns in one paragraph; the ISO date gives no number, the amount is a fact."}
```

Each line holds these keys:

- **`row_id`.** `A-NNN` or `B-NNN` (your letter), unique in your file.
- **`probe`.** The probe id, or `null` for a free row.
- **`question`.** The employee's question the answer replies to (for realism; never read by the reader).
- **`answer`.** The Markdown answer, exactly as the assistant wrote it.
- **`identifiers`.** An object holding the four kinds, each a list of normalised values as strings, sorted as strings, without duplicates. An empty kind is `[]`.
- **`fact_numbers`.** The distinct numbers the reader offers as facts (rule 8), as JSON numbers, sorted. "$1,234.50" is `1234.5`. A number that is both an identifier value and a fact elsewhere is listed: "Customer 12 has 12 invoices" gives `[12]`. Leave out:
  - marker numbers;
  - identifier values;
  - the parts of an ISO date;
  - anything inside a fenced code block (an inline code span is text, so its numbers count).
  A time right after an ISO date ("2009-05-23 00:00:00") is part of the date and gives no number.
- **`rules`.** The contract rules (`"1"` to `"9"`) the row exercises.
- **`open`.** `[]`, or one short phrase naming a contract sentence that does not settle this row (a new ambiguity). Where you tag it, give what the answer actually names, as a careful human reads it, and say in `note` what the readings would give.
- **`limit`.** The documented limits (`"L1"` to `"L12"`) the row's expectation follows, or `[]`. Where a limit applies, give what the contract's rule gives, not what a human would read.
- **`note`.** One or two sentences: why these identifiers and numbers.

## Before you hand in

- Every probe id appears once, as its own row.
- Every line parses as JSON with exactly these ten keys.
- `identifiers` lists all four kinds.
- Hand back the file path, the row count, and any contract sentence you found ambiguous, with the rows it affects.
