import sqlite3
p="/home/user/hypotrail/.claude/worktrees/s1-263/examples/chinook/data/Chinook_Sqlite.sqlite"
c=sqlite3.connect(f"file:{p}?mode=ro",uri=True)
Q={
"frank":"SELECT CustomerId,FirstName,LastName FROM Customer WHERE FirstName LIKE 'Frank%' OR LastName LIKE 'Frank%'",
"frank_spend":"SELECT c.CustomerId,c.FirstName,c.LastName,ROUND(SUM(i.Total),2),COUNT(*),MIN(i.InvoiceDate),MAX(i.InvoiceDate) FROM Customer c JOIN Invoice i USING(CustomerId) WHERE c.FirstName='Frank' GROUP BY c.CustomerId",
"by_revenue":"SELECT ar.Name,ROUND(SUM(il.UnitPrice*il.Quantity),2) r FROM InvoiceLine il JOIN Track t USING(TrackId) JOIN Album al USING(AlbumId) JOIN Artist ar USING(ArtistId) GROUP BY ar.ArtistId ORDER BY r DESC LIMIT 3",
"by_qty":"SELECT ar.Name,SUM(il.Quantity) q FROM InvoiceLine il JOIN Track t USING(TrackId) JOIN Album al USING(AlbumId) JOIN Artist ar USING(ArtistId) GROUP BY ar.ArtistId ORDER BY q DESC LIMIT 3",
"by_customers":"SELECT ar.Name,COUNT(DISTINCT i.CustomerId) n FROM InvoiceLine il JOIN Invoice i USING(InvoiceId) JOIN Track t USING(TrackId) JOIN Album al USING(AlbumId) JOIN Artist ar USING(ArtistId) GROUP BY ar.ArtistId ORDER BY n DESC LIMIT 5",
}
for k,q in Q.items():
    print(k, c.execute(q).fetchall())
