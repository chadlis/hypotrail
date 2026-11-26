import sqlite3,sys
c=sqlite3.connect("file:/home/user/hypotrail/.claude/worktrees/s1-263/examples/chinook/data/Chinook_Sqlite.sqlite?mode=ro",uri=True)
for q in sys.argv[1:]:
    print("==",q)
    for r in c.execute(q): print(r)
