# Writer A answers

Script: writer-a-q.py (read-only sqlite3 URI connection).

Shared SQL for Q1-Q3:
```sql
-- by units sold / revenue
SELECT ar.Name, SUM(il.Quantity) q, ROUND(SUM(il.UnitPrice*il.Quantity),2) rev, COUNT(DISTINCT i.CustomerId) nc
FROM InvoiceLine il JOIN Invoice i USING(InvoiceId) JOIN Track t USING(TrackId)
JOIN Album al USING(AlbumId) JOIN Artist ar USING(ArtistId)
GROUP BY ar.ArtistId ORDER BY q DESC LIMIT 5;
-- by distinct customers
... same joins ... ORDER BY nc DESC LIMIT 5;
```
Results: by tracks sold Iron Maiden 140 (U2 107); by revenue Iron Maiden $138.60 (U2 $105.93); by distinct customers buying U2 29, Led Zeppelin 28, Iron Maiden 27.

Shared SQL for Q4-Q6:
```sql
SELECT CustomerId, FirstName, LastName, Country FROM Customer
WHERE FirstName LIKE '%Frank%' OR LastName LIKE '%Frank%';
SELECT c.CustomerId, c.FirstName, c.LastName, ROUND(SUM(i.Total),2), COUNT(*)
FROM Customer c JOIN Invoice i USING(CustomerId) WHERE c.FirstName='Frank' GROUP BY 1;
```
Results: two customers named Frank: Frank Harris (id 16, USA) $37.62 over 7 invoices; Frank Ralston (id 24, USA) $43.62 over 7 invoices. No employee named Frank.

## Q1. "Which artist is the most popular with our customers?"
- Status: needs_clarification
- Reason: "most popular" can mean most tracks bought / most revenue (Iron Maiden) or bought by the most distinct customers (U2, 29 vs 27). The natural readings give different artists.
- Ask: measure by tracks purchased, by revenue, or by number of customers?
- Confidence: medium-high (0.75). A colleague could reasonably answer Iron Maiden (units sold is the common default for "popular").

## Q2. "Who is our customers' favourite artist?"
- Status: needs_clarification
- Reason: same split as Q1; "favourite" leans slightly toward breadth across customers (U2) but purchase volume (Iron Maiden) is equally natural. Also could mean each customer's own favourite (mode of per-customer top artist) — another reading.
- Confidence: medium-high (0.75). A colleague could pick answered (Iron Maiden).

## Q3. "Tell me which artist our customers like best."
- Status: needs_clarification
- Reason: "like best" has no data equivalent other than purchases; volume (Iron Maiden) vs reach (U2) disagree. There are no ratings in the data; a colleague might call it not_answerable for that reason, or answered with Iron Maiden.
- Confidence: medium (0.7).

## Q4. "How much has Frank spent with us?"
- Status: needs_clarification
- Reason: two customers named Frank: Frank Harris $37.62, Frank Ralston $43.62. Must ask which Frank.
- Confidence: high (0.95). Little room for another status.

## Q5. "What is Frank's total spend so far?"
- Status: needs_clarification
- Reason: same ambiguity of identity (Harris $37.62 vs Ralston $43.62). "So far" = all invoices to 2013-12-22, not an issue.
- Confidence: high (0.95).

## Q6. "Can you give me Frank's lifetime spend?"
- Status: needs_clarification
- Reason: same: which Frank (Harris $37.62, Ralston $43.62). Lifetime = sum of all invoice totals.
- Confidence: high (0.95).
