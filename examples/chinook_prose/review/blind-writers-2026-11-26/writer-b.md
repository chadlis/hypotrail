# Writer B answers

Script: writer-b-query.py (same folder). Database opened read-only via URI `mode=ro`.

## Shared SQL, artist questions (Q1-Q3)

```sql
-- by tracks sold
SELECT ar.Name, SUM(il.Quantity) q FROM InvoiceLine il JOIN Track t USING(TrackId)
 JOIN Album al USING(AlbumId) JOIN Artist ar USING(ArtistId)
 GROUP BY ar.ArtistId ORDER BY q DESC LIMIT 3;
-- Iron Maiden 140, U2 107, Metallica 91
-- by revenue (UnitPrice*Quantity): Iron Maiden 138.60, U2 105.93, Metallica 90.09
-- by distinct customers who bought
SELECT ar.Name, COUNT(DISTINCT i.CustomerId) n FROM InvoiceLine il JOIN Invoice i USING(InvoiceId)
 JOIN Track t USING(TrackId) JOIN Album al USING(AlbumId) JOIN Artist ar USING(ArtistId)
 GROUP BY ar.ArtistId ORDER BY n DESC LIMIT 5;
-- U2 29, Led Zeppelin 28, Iron Maiden 27, Metallica 27, Os Paralamas Do Sucesso 16
```

## Shared SQL, Frank questions (Q4-Q6)

```sql
SELECT CustomerId, FirstName, LastName FROM Customer
 WHERE FirstName LIKE 'Frank%' OR LastName LIKE 'Frank%';
-- 16 Frank Harris, 24 Frank Ralston
SELECT c.CustomerId, c.FirstName, c.LastName, ROUND(SUM(i.Total),2), COUNT(*), MIN(i.InvoiceDate), MAX(i.InvoiceDate)
 FROM Customer c JOIN Invoice i USING(CustomerId) WHERE c.FirstName='Frank' GROUP BY c.CustomerId;
-- Harris 37.62 (7 invoices, 2009-02-19..2013-07-04); Ralston 43.62 (7 invoices, 2010-02-08..2013-08-20)
```

## Q1. "Which artist is the most popular with our customers?"
- Status: needs_clarification
- Reason: "popular" can mean most tracks bought / most revenue (Iron Maiden: 140 tracks, 138.60) or most distinct customers who bought them (U2: 29 customers). The natural meanings give different artists. Ask: by purchases or by number of customers?
- Confidence: medium-high. A colleague could pick answered (Iron Maiden, by sales volume) since sales is the default proxy; I judge "with our customers" pulls toward customer reach, making both natural.

## Q2. "Who is our customers' favourite artist?"
- Status: needs_clarification
- Reason: same split. "Favourite" could be the artist most customers buy (U2, 29) or the one bought most (Iron Maiden, 140 tracks). No ratings or preference data exist, so it must be a purchase proxy, and the proxies disagree.
- Confidence: medium-high. A colleague could reasonably answer Iron Maiden by sales.

## Q3. "Tell me which artist our customers like best."
- Status: needs_clarification
- Reason: same as Q2; "like best" has no direct data (no ratings), and the two purchase proxies give Iron Maiden vs U2.
- Confidence: medium. A colleague might choose not_answerable (no "liking" data) or answered (Iron Maiden); I think a purchase proxy is the expected reading, so clarification is right.

## Q4. "How much has Frank spent with us?"
- Status: needs_clarification
- Reason: two customers named Frank: Frank Harris (id 16, 37.62) and Frank Ralston (id 24, 43.62). The answers differ; ask which Frank.
- Confidence: high. Little room for another status; combining them (81.24) would not be a natural reading.

## Q5. "What is Frank's total spend so far?"
- Status: needs_clarification
- Reason: same two Franks, 37.62 vs 43.62. "So far" adds nothing ambiguous: data ends 2013, all invoices included.
- Confidence: high.

## Q6. "Can you give me Frank's lifetime spend?"
- Status: needs_clarification
- Reason: same two Franks, 37.62 vs 43.62 (sum of Invoice.Total over all invoices).
- Confidence: high.
