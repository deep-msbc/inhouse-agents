#!/usr/bin/env python
"""Test whether kuzu schema persists to disk for Docker to read."""
import kuzu
import os

DB_PATH = "/mnt/c/Users/yug.chauhan/Desktop/InHouseAgents/data/test_persist.kuzu"

# Remove old test file
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
    print(f"Removed existing: {DB_PATH}")

# Create fresh DB
db = kuzu.Database(DB_PATH)
conn = kuzu.Connection(db)

# Create a simple table
conn.execute("CREATE NODE TABLE TestNode(id INT64, name STRING, PRIMARY KEY(id))")
conn.execute("CREATE (:TestNode {id: 1, name: 'hello'})")
conn.execute("CREATE (:TestNode {id: 2, name: 'world'})")

# Checkpoint
conn.execute("CHECKPOINT")
print("CHECKPOINT called")

# Verify before closing
r = conn.execute("MATCH (n:TestNode) RETURN count(n)")
print(f"Nodes before close: {r.get_next()[0]}")

# Close
conn.close()
db.__del__() if hasattr(db, '__del__') else None
del conn
del db
print("Connection closed")

import gc
gc.collect()

# Reopen and verify
print("\nReopening to verify...")
db2 = kuzu.Database(DB_PATH, read_only=True)
conn2 = kuzu.Connection(db2)

r2 = conn2.execute("CALL show_tables() RETURN *")
print("Tables after reopen:")
print(r2.get_as_df())

r3 = conn2.execute("MATCH (n:TestNode) RETURN count(n)")
print(f"Nodes after reopen: {r3.get_next()[0]}")

print(f"\nFile size: {os.path.getsize(DB_PATH)} bytes")
print("Done.")
