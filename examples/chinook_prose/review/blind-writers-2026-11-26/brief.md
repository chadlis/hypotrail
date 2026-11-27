You answer questions for a data assistant over a music store database (SQLite, read-only):
examples/chinook/data/Chinook_Sqlite.sqlite
Open it only with sqlite3.connect("file:<path>?mode=ro", uri=True).

For each question, decide which of these is right:
- answered: the question has one clear meaning and the data gives its answer;
- needs_clarification: a careful analyst must ask the user something before answering, because the question has two or more natural meanings that give DIFFERENT answers;
- not_answerable: the data cannot answer it.

Give the status, your reason, and the SQL you ran. If answered, give the answer. Also say how confident you are, and whether you think a careful colleague could reasonably pick another status.

Questions:
Q1. "Which artist is the most popular with our customers?"
Q2. "Who is our customers' favourite artist?"
Q3. "Tell me which artist our customers like best."
Q4. "How much has Frank spent with us?"
Q5. "What is Frank's total spend so far?"
Q6. "Can you give me Frank's lifetime spend?"

Note (2026-11-26, added when this file was committed): the brief the writers received gave the database as an absolute path into a local worktree of this repository; it is written here relative to the repository root.
